from __future__ import annotations

import json
import hmac
import os
import queue
import re
import shutil
import signal
import socket
import subprocess
import threading
import time
import uuid
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field


BASE_DIR = Path(__file__).resolve().parent
WEB_DIR = BASE_DIR / "web"
OUTPUTS_DIR = BASE_DIR / "outputs"
OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
UPLOADS_DIR = BASE_DIR / "uploads"
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
CONFIG_PATH = Path(os.environ.get("AUTOFIGURE_CONFIG_PATH", OUTPUTS_DIR / "config.json"))

PYTHON_EXECUTABLE = os.environ.get("AUTOFIGURE_PYTHON") or sys.executable

DEFAULT_SAM_PROMPT = "icon,person,robot,animal"
DEFAULT_PLACEHOLDER_MODE = "label"
DEFAULT_MERGE_THRESHOLD = 0.01
DEFAULT_PROVIDER = os.environ.get("AUTOFIGURE_DEFAULT_PROVIDER", "sub2api")
DEFAULT_IMAGE_MODEL = os.environ.get("AUTOFIGURE_DEFAULT_IMAGE_MODEL", "gpt-image-2")
DEFAULT_SVG_MODEL = os.environ.get("AUTOFIGURE_DEFAULT_SVG_MODEL", "gpt-5.5")
DEFAULT_REASONING_EFFORT = os.environ.get("AUTOFIGURE_DEFAULT_REASONING_EFFORT", "high")
DEFAULT_SAM_BACKEND = os.environ.get("AUTOFIGURE_DEFAULT_SAM_BACKEND", "roboflow")
DEFAULT_RMBG_BACKEND = os.environ.get("AUTOFIGURE_DEFAULT_RMBG_BACKEND", "local")
PROVIDER_DEFAULTS = {
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "image_model": "google/gemini-3.1-flash-image-preview",
        "svg_model": "google/gemini-3.1-pro-preview",
    },
    "bianxie": {
        "base_url": "https://api.bianxie.ai/v1",
        "image_model": "gemini-3.1-flash-image-preview",
        "svg_model": "gemini-3.1-pro-preview",
    },
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta",
        "image_model": "gemini-3.1-flash-image-preview",
        "svg_model": "gemini-3.1-pro-preview",
    },
    "xai": {
        "base_url": "https://api.x.ai/v1",
        "image_model": "grok-imagine-image",
        "svg_model": "grok-4.20-reasoning",
    },
    "sub2api": {
        "base_url": "http://sub2api:8080/v1" if Path("/.dockerenv").exists() else "http://localhost:8080/v1",
        "image_model": "gpt-image-2",
        "svg_model": "gpt-5.5",
    },
}

SVG_EDIT_CANDIDATES = [
    ("vendor/svg-edit/editor/index.html", WEB_DIR / "vendor" / "svg-edit" / "editor" / "index.html"),
    ("vendor/svg-edit/editor.html", WEB_DIR / "vendor" / "svg-edit" / "editor.html"),
    ("vendor/svg-edit/index.html", WEB_DIR / "vendor" / "svg-edit" / "index.html"),
]

SENSITIVE_CMD_FLAGS = {"--api_key", "--sam_api_key", "--bria_api_key"}
JOB_META_NAME = ".job.json"


def _resolve_svg_edit_path() -> tuple[bool, str | None]:
    for rel, path in SVG_EDIT_CANDIDATES:
        if path.is_file():
            return True, f"/{rel}"
    return False, None


def _default_base_url() -> str:
    configured = os.environ.get("AUTOFIGURE_DEFAULT_BASE_URL")
    if configured:
        return configured
    if Path("/.dockerenv").exists():
        return "http://host.docker.internal:8080/v1"
    return "http://localhost:8080/v1"


def _redact_cmd_args(cmd: list[str]) -> str:
    redacted: list[str] = []
    hide_next = False
    for token in cmd:
        if hide_next:
            redacted.append("***")
            hide_next = False
            continue
        redacted.append(token)
        if token in SENSITIVE_CMD_FLAGS:
            hide_next = True
    return " ".join(redacted)


def _job_meta_path(output_dir: Path) -> Path:
    return output_dir / JOB_META_NAME


def _read_job_meta(output_dir: Path) -> dict[str, Any]:
    meta_path = _job_meta_path(output_dir)
    if not meta_path.is_file():
        return {}
    try:
        data = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_job_meta(output_dir: Path, payload: dict[str, Any]) -> None:
    _job_meta_path(output_dir).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _update_job_meta(output_dir: Path, **updates: Any) -> dict[str, Any]:
    payload = _read_job_meta(output_dir)
    payload.update(updates)
    _write_job_meta(output_dir, payload)
    return payload


def _serializable_run_request(req: RunRequest) -> dict[str, Any]:
    return req.model_dump()


def _default_sam_api_key() -> str:
    return (
        os.environ.get("AUTOFIGURE_DEFAULT_SAM_API_KEY")
        or os.environ.get("ROBOFLOW_API_KEY")
        or os.environ.get("FAL_KEY")
        or ""
    )


def _default_bria_api_key() -> str:
    return os.environ.get("BRIA_API_KEY", "")


def _extract_logged_arg(output_dir: Path, flag: str) -> Optional[str]:
    log_path = output_dir / "run.log"
    if not log_path.is_file():
        return None
    try:
        text = log_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None
    match = re.search(rf"\s{re.escape(flag)}\s+(.+?)(?=\s--[A-Za-z0-9_]+|$)", text)
    if not match:
        return None
    value = match.group(1).strip()
    return value if value and value != "***" else None


def _request_value(
    saved_request: dict[str, Any],
    output_dir: Path,
    key: str,
    flag: str,
    default: Optional[str] = None,
) -> Optional[str]:
    value = saved_request.get(key)
    if value not in (None, ""):
        return str(value)
    return _extract_logged_arg(output_dir, flag) or default


def _build_continue_cmd(output_dir: Path) -> list[str]:
    meta = _read_job_meta(output_dir)
    saved_request = meta.get("request") if isinstance(meta.get("request"), dict) else {}
    app_config = _effective_config(include_secrets=True)
    provider = (
        _request_value(saved_request, output_dir, "provider", "--provider")
        or meta.get("provider")
        or app_config.get("provider")
        or DEFAULT_PROVIDER
    )
    provider_defaults = PROVIDER_DEFAULTS.get(provider, PROVIDER_DEFAULTS["sub2api"])
    figure_path = output_dir / "figure.png"
    method_text = _request_value(saved_request, output_dir, "method_text", "--method_text", "")
    source_path: Optional[Path] = figure_path if figure_path.is_file() else None
    if source_path is None:
        stored_source = (
            saved_request.get("source_image_path")
            or meta.get("source_image_path")
            or _extract_logged_arg(output_dir, "--source_figure_path")
        )
        if stored_source:
            candidate = (
                (BASE_DIR / stored_source).resolve()
                if not Path(str(stored_source)).is_absolute()
                else Path(str(stored_source)).resolve()
            )
            if candidate.is_file():
                source_path = candidate

    cmd = [
        PYTHON_EXECUTABLE,
        str(BASE_DIR / "autofigure2.py"),
        "--output_dir",
        str(output_dir),
        "--provider",
        provider,
    ]
    if (output_dir / "samed.png").is_file() and (output_dir / "boxlib.json").is_file():
        cmd += ["--reuse_intermediates"]
    if source_path is not None:
        cmd += ["--source_figure_path", str(source_path)]
    elif method_text:
        cmd += ["--method_text", method_text]
    else:
        raise HTTPException(status_code=400, detail="Cannot continue: missing figure.png or method text")

    api_key = app_config.get("apiKey") or os.environ.get("AUTOFIGURE_DEFAULT_API_KEY", "")
    if api_key:
        cmd += ["--api_key", api_key]
    base_url = _request_value(
        saved_request,
        output_dir,
        "base_url",
        "--base_url",
        app_config.get("baseUrl") or (_default_base_url() if provider == "sub2api" else provider_defaults["base_url"]),
    )
    if base_url:
        cmd += ["--base_url", base_url]
    image_model = _request_value(
        saved_request,
        output_dir,
        "image_model",
        "--image_model",
        app_config.get("imageModel") or (DEFAULT_IMAGE_MODEL if provider == "sub2api" else provider_defaults["image_model"]),
    )
    if image_model:
        cmd += ["--image_model", image_model]
    image_size = _request_value(saved_request, output_dir, "image_size", "--image_size", app_config.get("imageSize"))
    if image_size:
        cmd += ["--image_size", image_size]
    svg_model = _request_value(
        saved_request,
        output_dir,
        "svg_model",
        "--svg_model",
        app_config.get("svgModel") or (DEFAULT_SVG_MODEL if provider == "sub2api" else provider_defaults["svg_model"]),
    )
    if svg_model:
        cmd += ["--svg_model", svg_model]
    reasoning_effort = _request_value(
        saved_request,
        output_dir,
        "reasoning_effort",
        "--reasoning_effort",
        app_config.get("reasoningEffort") or (DEFAULT_REASONING_EFFORT if provider == "sub2api" else None),
    )
    if provider == "sub2api" and reasoning_effort:
        cmd += ["--reasoning_effort", reasoning_effort]

    cmd += [
        "--sam_prompt",
        _request_value(
            saved_request,
            output_dir,
            "sam_prompt",
            "--sam_prompt",
            app_config.get("samPrompt") or DEFAULT_SAM_PROMPT,
        )
        or DEFAULT_SAM_PROMPT,
        "--placeholder_mode",
        _request_value(saved_request, output_dir, "placeholder_mode", "--placeholder_mode", DEFAULT_PLACEHOLDER_MODE)
        or DEFAULT_PLACEHOLDER_MODE,
        "--merge_threshold",
        str(
            _request_value(
                saved_request,
                output_dir,
                "merge_threshold",
                "--merge_threshold",
                str(DEFAULT_MERGE_THRESHOLD),
            )
            or DEFAULT_MERGE_THRESHOLD
        ),
    ]
    sam_backend = _request_value(
        saved_request,
        output_dir,
        "sam_backend",
        "--sam_backend",
        app_config.get("samBackend") or DEFAULT_SAM_BACKEND,
    )
    if sam_backend:
        cmd += ["--sam_backend", sam_backend]
    sam_api_key = app_config.get("samApiKey") or _default_sam_api_key()
    if sam_api_key:
        cmd += ["--sam_api_key", sam_api_key]
    rmbg_backend = _request_value(
        saved_request,
        output_dir,
        "rmbg_backend",
        "--rmbg_backend",
        app_config.get("rmbgBackend") or DEFAULT_RMBG_BACKEND,
    )
    if rmbg_backend:
        cmd += ["--rmbg_backend", rmbg_backend]
    if rmbg_backend == "bria-api":
        bria_api_key = app_config.get("briaApiKey") or _default_bria_api_key() or saved_request.get("bria_api_key") or ""
        if bria_api_key:
            cmd += ["--bria_api_key", str(bria_api_key)]
    optimize_iterations = _request_value(
        saved_request,
        output_dir,
        "optimize_iterations",
        "--optimize_iterations",
        str(app_config.get("optimizeIterations") or "0"),
    )
    if optimize_iterations is not None:
        cmd += ["--optimize_iterations", str(optimize_iterations)]
    return cmd


def _build_optimize_cmd(output_dir: Path, iterations: int) -> list[str]:
    meta = _read_job_meta(output_dir)
    saved_request = meta.get("request") if isinstance(meta.get("request"), dict) else {}
    provider = (
        _request_value(saved_request, output_dir, "provider", "--provider")
        or meta.get("provider")
        or DEFAULT_PROVIDER
    )
    provider_defaults = PROVIDER_DEFAULTS.get(provider, PROVIDER_DEFAULTS["sub2api"])

    cmd = [
        PYTHON_EXECUTABLE,
        str(BASE_DIR / "autofigure2.py"),
        "--continue_optimize",
        "--output_dir",
        str(output_dir),
        "--provider",
        provider,
        "--optimize_iterations",
        str(iterations),
    ]

    api_key = os.environ.get("AUTOFIGURE_DEFAULT_API_KEY") or saved_request.get("api_key") or ""
    if api_key:
        cmd += ["--api_key", str(api_key)]

    base_url = _request_value(
        saved_request,
        output_dir,
        "base_url",
        "--base_url",
        _default_base_url() if provider == "sub2api" else provider_defaults["base_url"],
    )
    if base_url:
        cmd += ["--base_url", base_url]

    svg_model = _request_value(
        saved_request,
        output_dir,
        "svg_model",
        "--svg_model",
        DEFAULT_SVG_MODEL if provider == "sub2api" else provider_defaults["svg_model"],
    )
    if svg_model:
        cmd += ["--svg_model", svg_model]

    reasoning_effort = _request_value(
        saved_request,
        output_dir,
        "reasoning_effort",
        "--reasoning_effort",
        DEFAULT_REASONING_EFFORT if provider == "sub2api" else None,
    )
    if provider == "sub2api" and reasoning_effort:
        cmd += ["--reasoning_effort", reasoning_effort]

    return cmd


def _resolve_job_output_dir(job_id: str) -> Path:
    if "/" in job_id or "\\" in job_id or ".." in job_id:
        raise HTTPException(status_code=400, detail="Invalid job id")
    output_dir = (OUTPUTS_DIR / job_id).resolve()
    if not str(output_dir).startswith(str(OUTPUTS_DIR.resolve())) or not output_dir.is_dir():
        raise HTTPException(status_code=404, detail="Job not found")
    return output_dir


def _delete_uploaded_file_if_owned(path_value: Any) -> None:
    if not isinstance(path_value, str) or not path_value:
        return
    candidate = (BASE_DIR / path_value).resolve() if not Path(path_value).is_absolute() else Path(path_value).resolve()
    uploads_root = UPLOADS_DIR.resolve()
    if candidate.parent != uploads_root or not candidate.is_file():
        return
    try:
        candidate.unlink()
    except FileNotFoundError:
        pass
    except OSError:
        pass


def _classify_artifact(rel_path: str) -> str:
    if rel_path == "figure.png":
        return "figure"
    if rel_path == "samed.png":
        return "samed"
    if rel_path.endswith("_nobg.png"):
        return "icon_nobg"
    if rel_path.startswith("icons/") and rel_path.endswith(".png"):
        return "icon_raw"
    if rel_path == "template.svg":
        return "template_svg"
    if rel_path == "optimized_template.svg":
        return "optimized_template_svg"
    if rel_path == "final.svg":
        return "final_svg"
    if rel_path == "run.log":
        return "log"
    return "artifact"


def _collect_artifacts(output_dir: Path) -> list[dict[str, str]]:
    candidates = [
        output_dir / "figure.png",
        output_dir / "samed.png",
        output_dir / "template.svg",
        output_dir / "optimized_template.svg",
        output_dir / "final.svg",
        output_dir / "run.log",
    ]
    icons_dir = output_dir / "icons"
    if icons_dir.is_dir():
        candidates.extend(sorted(icons_dir.glob("icon_*.png")))

    artifacts: list[dict[str, str]] = []
    for path in candidates:
        if not path.is_file():
            continue
        rel_path = path.relative_to(output_dir).as_posix()
        artifacts.append(
            {
                "kind": _classify_artifact(rel_path),
                "name": path.name,
                "path": rel_path,
                "url": f"/api/artifacts/{output_dir.name}/{rel_path}",
            }
        )
    return artifacts


def _infer_job_state(output_dir: Path, meta: dict[str, Any]) -> tuple[str, Optional[int]]:
    if (output_dir / "final.svg").is_file():
        return "done", 0
    code = meta.get("return_code")
    if isinstance(code, int):
        return ("failed" if code != 0 else "done"), code
    if (output_dir / "run.log").is_file():
        return "saved", None
    return "empty", None


def _build_job_summary(output_dir: Path) -> dict[str, Any]:
    meta = _read_job_meta(output_dir)
    state, code = _infer_job_state(output_dir, meta)
    artifacts = _collect_artifacts(output_dir)
    preview = next(
        (
            item
            for item in reversed(artifacts)
            if item["kind"] in {"final_svg", "optimized_template_svg", "template_svg", "samed", "figure"}
        ),
        None,
    )
    return {
        "job_id": output_dir.name,
        "created_at": meta.get("created_at"),
        "finished_at": meta.get("finished_at"),
        "archived": bool(meta.get("archived", False)),
        "input_mode": meta.get("input_mode"),
        "provider": meta.get("provider"),
        "state": state,
        "return_code": code,
        "artifact_count": len(artifacts),
        "preview_url": preview["url"] if preview else None,
    }


@dataclass
class Job:
    job_id: str
    output_dir: Path
    process: subprocess.Popen
    queue: queue.Queue
    log_path: Path
    log_lock: threading.Lock = field(default_factory=threading.Lock)
    seen: set[str] = field(default_factory=set)
    done: bool = False
    paused: bool = False
    deleted: bool = False

    def push(self, event: str, data: dict) -> None:
        self.queue.put({"event": event, "data": data})

    def write_log(self, stream: str, line: str) -> None:
        with self.log_lock:
            with open(self.log_path, "a", encoding="utf-8") as handle:
                handle.write(f"[{stream}] {line}\n")


class RunRequest(BaseModel):
    method_text: str = ""
    input_mode: str = "text"
    provider: Optional[str] = None
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    image_model: Optional[str] = None
    image_size: Optional[str] = None
    svg_model: Optional[str] = None
    reasoning_effort: Optional[str] = None
    sam_prompt: Optional[str] = None
    sam_backend: Optional[str] = None
    sam_api_key: Optional[str] = None
    sam_max_masks: Optional[int] = None
    rmbg_backend: Optional[str] = None
    bria_api_key: Optional[str] = None
    placeholder_mode: Optional[str] = None
    merge_threshold: Optional[float] = None
    optimize_iterations: Optional[int] = None
    reference_image_path: Optional[str] = None
    source_image_path: Optional[str] = None


class ArchiveRequest(BaseModel):
    archived: bool = True


class OptimizeRequest(BaseModel):
    iterations: int = Field(default=1, ge=1, le=3)


class AdminConfigRequest(BaseModel):
    password: str = ""


class SaveConfigRequest(AdminConfigRequest):
    defaults: dict[str, Any] = Field(default_factory=dict)


app = FastAPI()

JOBS: dict[str, Job] = {}


@app.get("/healthz")
def healthz() -> JSONResponse:
    return JSONResponse({"status": "ok"})


def _admin_password() -> str:
    return os.environ.get("AUTOFIGURE_ADMIN_PASSWORD") or os.environ.get("AUTOFIGURE_DEFAULT_API_KEY", "")


CONFIG_FIELDS = {
    "provider",
    "apiKey",
    "baseUrl",
    "imageModel",
    "imageSize",
    "svgModel",
    "reasoningEffort",
    "optimizeIterations",
    "samBackend",
    "samPrompt",
    "samApiKey",
    "rmbgBackend",
    "briaApiKey",
}
SECRET_CONFIG_FIELDS = {"apiKey", "samApiKey", "briaApiKey"}


def _read_saved_config() -> dict[str, Any]:
    if not CONFIG_PATH.is_file():
        return {}
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    defaults = data.get("defaults")
    if isinstance(defaults, dict):
        return {key: value for key, value in defaults.items() if key in CONFIG_FIELDS}
    return {key: value for key, value in data.items() if key in CONFIG_FIELDS}


def _write_saved_config(defaults: dict[str, Any]) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(
        json.dumps({"defaults": defaults}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _env_config(include_secrets: bool = False) -> dict[str, Any]:
    defaults = {
        "provider": DEFAULT_PROVIDER,
        "apiKey": "",
        "baseUrl": _default_base_url(),
        "imageModel": DEFAULT_IMAGE_MODEL,
        "imageSize": os.environ.get("AUTOFIGURE_DEFAULT_IMAGE_SIZE", "4K"),
        "svgModel": DEFAULT_SVG_MODEL,
        "reasoningEffort": DEFAULT_REASONING_EFFORT,
        "optimizeIterations": os.environ.get("AUTOFIGURE_DEFAULT_OPTIMIZE_ITERATIONS", "0"),
        "samBackend": DEFAULT_SAM_BACKEND,
        "samPrompt": os.environ.get("AUTOFIGURE_DEFAULT_SAM_PROMPT", DEFAULT_SAM_PROMPT),
        "samApiKey": "",
        "rmbgBackend": DEFAULT_RMBG_BACKEND,
        "briaApiKey": "",
    }
    if include_secrets:
        defaults.update(
            {
                "apiKey": os.environ.get("AUTOFIGURE_DEFAULT_API_KEY", ""),
                "samApiKey": _default_sam_api_key(),
                "briaApiKey": _default_bria_api_key(),
            }
        )
    return defaults


def _effective_config(include_secrets: bool = False) -> dict[str, Any]:
    defaults = _env_config(include_secrets=True)
    saved = _read_saved_config()
    for key, value in saved.items():
        if value is not None:
            defaults[key] = value
    admin_password = os.environ.get("AUTOFIGURE_ADMIN_PASSWORD", "")
    if admin_password and defaults.get("apiKey") == admin_password:
        defaults["apiKey"] = ""
    if not include_secrets:
        for key in SECRET_CONFIG_FIELDS:
            defaults[key] = ""
    return defaults


def _config_payload(include_secrets: bool = False) -> dict[str, Any]:
    available, rel_path = _resolve_svg_edit_path()
    return {
        "svgEditAvailable": available,
        "svgEditPath": rel_path,
        "defaults": _effective_config(include_secrets=include_secrets),
    }


def _apply_saved_config_to_env(defaults: dict[str, Any]) -> None:
    mapping = {
        "apiKey": "AUTOFIGURE_DEFAULT_API_KEY",
        "baseUrl": "AUTOFIGURE_DEFAULT_BASE_URL",
        "imageModel": "AUTOFIGURE_DEFAULT_IMAGE_MODEL",
        "imageSize": "AUTOFIGURE_DEFAULT_IMAGE_SIZE",
        "svgModel": "AUTOFIGURE_DEFAULT_SVG_MODEL",
        "reasoningEffort": "AUTOFIGURE_DEFAULT_REASONING_EFFORT",
        "optimizeIterations": "AUTOFIGURE_DEFAULT_OPTIMIZE_ITERATIONS",
        "samBackend": "AUTOFIGURE_DEFAULT_SAM_BACKEND",
        "samPrompt": "AUTOFIGURE_DEFAULT_SAM_PROMPT",
        "samApiKey": "AUTOFIGURE_DEFAULT_SAM_API_KEY",
        "rmbgBackend": "AUTOFIGURE_DEFAULT_RMBG_BACKEND",
        "briaApiKey": "BRIA_API_KEY",
    }
    for key, env_name in mapping.items():
        value = defaults.get(key)
        if value is not None:
            os.environ[env_name] = str(value)


@app.get("/api/config")
def get_config() -> JSONResponse:
    return JSONResponse(_config_payload(include_secrets=False))


@app.post("/api/config/admin")
def get_admin_config(req: AdminConfigRequest) -> JSONResponse:
    expected = _admin_password()
    if not expected or not hmac.compare_digest(req.password, expected):
        raise HTTPException(status_code=401, detail="Invalid admin password")
    return JSONResponse(_config_payload(include_secrets=True))


@app.post("/api/config/save")
def save_config(req: SaveConfigRequest) -> JSONResponse:
    expected = _admin_password()
    if not expected or not hmac.compare_digest(req.password, expected):
        raise HTTPException(status_code=401, detail="Invalid admin password")

    current = _effective_config(include_secrets=True)
    incoming = {
        key: value
        for key, value in req.defaults.items()
        if key in CONFIG_FIELDS and isinstance(value, (str, int, float, bool))
    }
    admin_password = os.environ.get("AUTOFIGURE_ADMIN_PASSWORD", "")
    for key, value in incoming.items():
        current[key] = str(value).strip() if isinstance(value, str) else value
    if admin_password and current.get("apiKey") == admin_password:
        raise HTTPException(status_code=400, detail="API Key cannot be the admin password")
    _write_saved_config(current)
    _apply_saved_config_to_env(current)
    return JSONResponse(_config_payload(include_secrets=True))


@app.get("/api/jobs")
def list_jobs(archived: str = "active") -> JSONResponse:
    archived_filter = archived.strip().lower()
    if archived_filter not in {"active", "archived", "all"}:
        raise HTTPException(status_code=400, detail="Invalid archived filter")

    jobs = []
    for output_dir in sorted(OUTPUTS_DIR.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if not output_dir.is_dir():
            continue
        summary = _build_job_summary(output_dir)
        if archived_filter == "active" and summary["archived"]:
            continue
        if archived_filter == "archived" and not summary["archived"]:
            continue
        jobs.append(summary)
    return JSONResponse({"jobs": jobs})


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> JSONResponse:
    output_dir = _resolve_job_output_dir(job_id)
    summary = _build_job_summary(output_dir)
    summary["artifacts"] = _collect_artifacts(output_dir)
    return JSONResponse(summary)


@app.post("/api/jobs/{job_id}/archive")
def archive_job(job_id: str, req: ArchiveRequest) -> JSONResponse:
    output_dir = _resolve_job_output_dir(job_id)
    _update_job_meta(output_dir, archived=bool(req.archived))
    return JSONResponse(_build_job_summary(output_dir))


@app.delete("/api/jobs/{job_id}")
def delete_job(job_id: str) -> JSONResponse:
    output_dir = _resolve_job_output_dir(job_id)
    if output_dir.parent != OUTPUTS_DIR.resolve():
        raise HTTPException(status_code=400, detail="Invalid job path")
    meta = _read_job_meta(output_dir)

    job = JOBS.pop(job_id, None)
    if job is not None:
        job.deleted = True
        _terminate_job(job)

    saved_request = meta.get("request") if isinstance(meta.get("request"), dict) else {}
    _delete_uploaded_file_if_owned(saved_request.get("source_image_path"))
    _delete_uploaded_file_if_owned(saved_request.get("reference_image_path"))

    try:
        shutil.rmtree(output_dir)
    except FileNotFoundError:
        pass
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Could not delete job: {exc}") from exc
    return JSONResponse({"job_id": job_id, "deleted": True})


@app.post("/api/jobs/{job_id}/pause")
def pause_job(job_id: str) -> JSONResponse:
    job = _get_running_job(job_id)
    _signal_job(job, signal.SIGSTOP)
    job.paused = True
    _update_job_meta(job.output_dir, paused=True)
    job.write_log("system", "任务已暂停")
    job.push("status", {"state": "paused"})
    return JSONResponse({"job_id": job_id, "state": "paused"})


@app.post("/api/jobs/{job_id}/resume")
def resume_job(job_id: str) -> JSONResponse:
    job = _get_running_job(job_id)
    _signal_job(job, signal.SIGCONT)
    job.paused = False
    _update_job_meta(job.output_dir, paused=False)
    job.write_log("system", "任务已继续")
    job.push("status", {"state": "resumed"})
    return JSONResponse({"job_id": job_id, "state": "running"})


@app.post("/api/jobs/{job_id}/continue")
def continue_job(job_id: str) -> JSONResponse:
    output_dir = _resolve_job_output_dir(job_id)
    if (output_dir / "final.svg").is_file():
        return JSONResponse(_build_job_summary(output_dir))

    existing = JOBS.get(job_id)
    if existing and existing.process.poll() is None and not existing.done:
        if existing.paused:
            _signal_job(existing, signal.SIGCONT)
            existing.paused = False
            _update_job_meta(existing.output_dir, paused=False)
            existing.write_log("system", "任务已继续")
            existing.push("status", {"state": "resumed"})
            return JSONResponse({"job_id": job_id, "state": "running"})
        raise HTTPException(status_code=409, detail="Job is already running")

    cmd = _build_continue_cmd(output_dir)
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    log_path = output_dir / "run.log"
    with open(log_path, "a", encoding="utf-8") as handle:
        handle.write(
            f"\n[meta] continue_at={datetime.now().isoformat()}\n"
            f"[meta] cmd={_redact_cmd_args(cmd)}\n"
        )
    _update_job_meta(
        output_dir,
        continued_at=datetime.now().isoformat(),
        return_code=None,
        paused=False,
    )
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
        env=env,
        cwd=str(BASE_DIR),
        start_new_session=True,
    )
    job = Job(
        job_id=job_id,
        output_dir=output_dir,
        process=process,
        queue=queue.Queue(),
        log_path=log_path,
    )
    JOBS[job_id] = job
    monitor_thread = threading.Thread(target=_monitor_job, args=(job,), daemon=True)
    monitor_thread.start()
    return JSONResponse({"job_id": job_id, "state": "running"})


@app.post("/api/jobs/{job_id}/optimize")
def optimize_job(job_id: str, req: OptimizeRequest) -> JSONResponse:
    output_dir = _resolve_job_output_dir(job_id)
    existing = JOBS.get(job_id)
    if existing and existing.process.poll() is None and not existing.done:
        raise HTTPException(status_code=409, detail="Job is already running")

    if not (output_dir / "figure.png").is_file():
        raise HTTPException(status_code=400, detail="Cannot optimize: missing figure.png")
    if not any((output_dir / name).is_file() for name in ("optimized_template.svg", "template.svg", "final.svg")):
        raise HTTPException(status_code=400, detail="Cannot optimize: missing SVG artifact")

    cmd = _build_optimize_cmd(output_dir, req.iterations)
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    log_path = output_dir / "run.log"
    with open(log_path, "a", encoding="utf-8") as handle:
        handle.write(
            f"\n[meta] optimize_at={datetime.now().isoformat()}\n"
            f"[meta] cmd={_redact_cmd_args(cmd)}\n"
        )
    _update_job_meta(
        output_dir,
        optimizing_at=datetime.now().isoformat(),
        return_code=None,
        paused=False,
    )
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
        env=env,
        cwd=str(BASE_DIR),
        start_new_session=True,
    )
    job = Job(
        job_id=job_id,
        output_dir=output_dir,
        process=process,
        queue=queue.Queue(),
        log_path=log_path,
    )
    JOBS[job_id] = job
    monitor_thread = threading.Thread(target=_monitor_job, args=(job,), daemon=True)
    monitor_thread.start()
    return JSONResponse({"job_id": job_id, "state": "running", "iterations": req.iterations})


@app.post("/api/run")
def run_job(req: RunRequest) -> JSONResponse:
    job_id = datetime.now().strftime("%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:8]
    output_dir = OUTPUTS_DIR / job_id
    output_dir.mkdir(parents=True, exist_ok=True)
    app_config = _effective_config(include_secrets=True)

    input_mode = (req.input_mode or "text").strip().lower()
    if input_mode not in {"text", "image"}:
        raise HTTPException(status_code=400, detail="Invalid input mode")

    method_text = (req.method_text or "").strip()
    source_candidate: Optional[Path] = None
    if input_mode == "text" and not method_text:
        raise HTTPException(status_code=400, detail="Method text is required")
    if input_mode == "image":
        if not req.source_image_path:
            raise HTTPException(status_code=400, detail="Source image is required")
        source_candidate = (
            (BASE_DIR / req.source_image_path).resolve()
            if not Path(req.source_image_path).is_absolute()
            else Path(req.source_image_path).resolve()
        )
        if not source_candidate.is_file():
            raise HTTPException(status_code=400, detail="Source image not found")

    provider = (req.provider or str(app_config.get("provider") or DEFAULT_PROVIDER)).strip() or DEFAULT_PROVIDER
    provider_defaults = PROVIDER_DEFAULTS.get(provider, PROVIDER_DEFAULTS["sub2api"])
    api_key = req.api_key or app_config.get("apiKey") or os.environ.get("AUTOFIGURE_DEFAULT_API_KEY", "")
    base_url = req.base_url or app_config.get("baseUrl") or (
        _default_base_url() if provider == "sub2api" else provider_defaults["base_url"]
    )
    image_model = req.image_model or (
        app_config.get("imageModel") or DEFAULT_IMAGE_MODEL
        if provider == "sub2api"
        else provider_defaults["image_model"]
    )
    svg_model = req.svg_model or (
        app_config.get("svgModel") or DEFAULT_SVG_MODEL
        if provider == "sub2api"
        else provider_defaults["svg_model"]
    )
    reasoning_effort = req.reasoning_effort or app_config.get("reasoningEffort")
    if provider == "sub2api" and not reasoning_effort:
        reasoning_effort = DEFAULT_REASONING_EFFORT

    cmd = [
        PYTHON_EXECUTABLE,
        str(BASE_DIR / "autofigure2.py"),
        "--output_dir",
        str(output_dir),
        "--provider",
        provider,
    ]
    if method_text:
        cmd += ["--method_text", method_text]
    if source_candidate is not None:
        cmd += ["--source_figure_path", str(source_candidate)]

    if api_key:
        cmd += ["--api_key", api_key]
    if base_url:
        cmd += ["--base_url", base_url]
    if image_model:
        cmd += ["--image_model", image_model]
    image_size = req.image_size or app_config.get("imageSize")
    if image_size:
        cmd += ["--image_size", str(image_size)]
    if svg_model:
        cmd += ["--svg_model", svg_model]
    if reasoning_effort:
        cmd += ["--reasoning_effort", reasoning_effort]

    sam_prompt = req.sam_prompt or app_config.get("samPrompt") or DEFAULT_SAM_PROMPT
    placeholder_mode = req.placeholder_mode or DEFAULT_PLACEHOLDER_MODE
    merge_threshold = (
        req.merge_threshold if req.merge_threshold is not None else DEFAULT_MERGE_THRESHOLD
    )

    cmd += ["--sam_prompt", sam_prompt]
    cmd += ["--placeholder_mode", placeholder_mode]
    cmd += ["--merge_threshold", str(merge_threshold)]
    sam_backend = req.sam_backend or app_config.get("samBackend") or DEFAULT_SAM_BACKEND
    if sam_backend:
        cmd += ["--sam_backend", sam_backend]
    sam_api_key = req.sam_api_key or app_config.get("samApiKey") or _default_sam_api_key()
    if sam_api_key:
        cmd += ["--sam_api_key", sam_api_key]
    if req.sam_max_masks is not None:
        cmd += ["--sam_max_masks", str(req.sam_max_masks)]
    rmbg_backend = req.rmbg_backend or app_config.get("rmbgBackend") or DEFAULT_RMBG_BACKEND
    if rmbg_backend:
        cmd += ["--rmbg_backend", rmbg_backend]
    bria_api_key = req.bria_api_key or app_config.get("briaApiKey") or _default_bria_api_key()
    if rmbg_backend == "bria-api" and bria_api_key:
        cmd += ["--bria_api_key", bria_api_key]
    optimize_iterations = (
        req.optimize_iterations
        if req.optimize_iterations is not None
        else app_config.get("optimizeIterations")
    )
    if optimize_iterations is not None:
        cmd += ["--optimize_iterations", str(optimize_iterations)]

    reference_path = req.reference_image_path
    if reference_path:
        reference_path = (
            str((BASE_DIR / reference_path).resolve())
            if not Path(reference_path).is_absolute()
            else reference_path
        )
        cmd += ["--reference_image_path", reference_path]

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"

    log_path = output_dir / "run.log"
    log_path.write_text(
        f"[meta] python={PYTHON_EXECUTABLE}\n[meta] cmd={_redact_cmd_args(cmd)}\n",
        encoding="utf-8",
    )
    _write_job_meta(
        output_dir,
        {
            "job_id": job_id,
            "created_at": datetime.now().isoformat(),
            "archived": False,
            "input_mode": input_mode,
            "provider": provider,
            "source_image_path": str(source_candidate) if source_candidate else None,
            "reference_image_path": reference_path,
            "request": _serializable_run_request(req),
        },
    )

    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
        env=env,
        cwd=str(BASE_DIR),
        start_new_session=True,
    )

    job = Job(
        job_id=job_id,
        output_dir=output_dir,
        process=process,
        queue=queue.Queue(),
        log_path=log_path,
    )
    JOBS[job_id] = job

    monitor_thread = threading.Thread(target=_monitor_job, args=(job,), daemon=True)
    monitor_thread.start()

    return JSONResponse({"job_id": job_id})


@app.post("/api/upload")
async def upload_reference(file: UploadFile = File(...)) -> JSONResponse:
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="File must be an image")

    ext = Path(file.filename).suffix.lower()
    if ext not in {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}:
        ext = ".png"

    data = await file.read()
    if len(data) > 20 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File too large")

    name = f"{uuid.uuid4().hex}{ext}"
    out_path = UPLOADS_DIR / name
    out_path.write_bytes(data)

    rel_path = out_path.relative_to(BASE_DIR).as_posix()
    return JSONResponse(
        {"path": rel_path, "url": f"/api/uploads/{name}", "name": file.filename}
    )


@app.get("/api/events/{job_id}")
def stream_events(job_id: str) -> StreamingResponse:
    job = JOBS.get(job_id)
    if not job:
        output_dir = _resolve_job_output_dir(job_id)

        def saved_event_stream():
            summary = _build_job_summary(output_dir)
            if summary["state"] == "done":
                yield _format_sse("status", {"state": "finished", "code": 0})
            elif summary["state"] == "failed":
                yield _format_sse(
                    "status",
                    {"state": "failed", "code": summary["return_code"]},
                )
            else:
                yield _format_sse("status", {"state": summary["state"]})
            for artifact in _collect_artifacts(output_dir):
                yield _format_sse("artifact", artifact)
            log_path = output_dir / "run.log"
            if log_path.is_file():
                try:
                    for raw_line in log_path.read_text(encoding="utf-8", errors="ignore").splitlines():
                        if raw_line.startswith("[") and "] " in raw_line:
                            stream_name, line = raw_line[1:].split("] ", 1)
                        else:
                            stream_name, line = "log", raw_line
                        yield _format_sse("log", {"stream": stream_name, "line": line})
                except OSError:
                    pass
            if summary["state"] == "done":
                yield _format_sse("status", {"state": "finished", "code": 0})
            elif summary["state"] == "failed":
                yield _format_sse(
                    "status",
                    {"state": "failed", "code": summary["return_code"]},
                )
            else:
                yield _format_sse("status", {"state": summary["state"]})

        return StreamingResponse(saved_event_stream(), media_type="text/event-stream")

    def event_stream():
        while True:
            try:
                item = job.queue.get(timeout=1.0)
            except queue.Empty:
                if job.done:
                    break
                continue
            if item.get("event") == "close":
                break
            yield _format_sse(item["event"], item["data"])

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.get("/api/artifacts/{job_id}/{path:path}")
def get_artifact(job_id: str, path: str) -> FileResponse:
    job = JOBS.get(job_id)
    output_dir = job.output_dir if job else _resolve_job_output_dir(job_id)

    candidate = (output_dir / path).resolve()
    if not str(candidate).startswith(str(output_dir.resolve())):
        raise HTTPException(status_code=400, detail="Invalid path")
    if not candidate.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(candidate)


@app.get("/api/uploads/{filename}")
def get_upload(filename: str) -> FileResponse:
    candidate = (UPLOADS_DIR / filename).resolve()
    if not str(candidate).startswith(str(UPLOADS_DIR.resolve())):
        raise HTTPException(status_code=400, detail="Invalid path")
    if not candidate.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(candidate)


def _format_sse(event: str, data: dict) -> str:
    payload = json.dumps(data, ensure_ascii=True)
    return f"event: {event}\ndata: {payload}\n\n"


def _get_running_job(job_id: str) -> Job:
    _resolve_job_output_dir(job_id)
    job = JOBS.get(job_id)
    if not job or job.done or job.process.poll() is not None:
        raise HTTPException(status_code=409, detail="Job is not running")
    return job


def _signal_job(job: Job, sig: signal.Signals) -> None:
    try:
        os.killpg(os.getpgid(job.process.pid), sig)
    except ProcessLookupError:
        raise HTTPException(status_code=409, detail="Job is not running")
    except Exception:
        try:
            job.process.send_signal(sig)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Could not signal job: {exc}")


def _terminate_job(job: Job) -> None:
    if job.process.poll() is not None:
        job.done = True
        return
    try:
        if job.paused:
            os.killpg(os.getpgid(job.process.pid), signal.SIGCONT)
        os.killpg(os.getpgid(job.process.pid), signal.SIGTERM)
    except ProcessLookupError:
        job.done = True
        return
    except Exception:
        try:
            if job.paused:
                job.process.send_signal(signal.SIGCONT)
            job.process.terminate()
        except Exception:
            pass

    try:
        job.process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(job.process.pid), signal.SIGKILL)
        except Exception:
            try:
                job.process.kill()
            except Exception:
                pass
        try:
            job.process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            pass
    job.done = True


def _monitor_job(job: Job) -> None:
    job.push("status", {"state": "started"})

    stdout_thread = threading.Thread(
        target=_pipe_output, args=(job, job.process.stdout, "stdout"), daemon=True
    )
    stderr_thread = threading.Thread(
        target=_pipe_output, args=(job, job.process.stderr, "stderr"), daemon=True
    )
    stdout_thread.start()
    stderr_thread.start()

    idle_cycles = 0
    while True:
        if job.deleted:
            job.done = True
            job.push("status", {"state": "deleted"})
            job.push("close", {})
            return
        _scan_artifacts(job)

        if job.process.poll() is not None:
            idle_cycles += 1
        else:
            idle_cycles = 0

        if idle_cycles >= 4:
            break
        time.sleep(0.5)

    if job.deleted:
        job.done = True
        job.push("status", {"state": "deleted"})
        job.push("close", {})
        return
    _scan_artifacts(job)
    if job.deleted:
        job.done = True
        job.push("status", {"state": "deleted"})
        job.push("close", {})
        return
    _update_job_meta(
        job.output_dir,
        finished_at=datetime.now().isoformat(),
        return_code=job.process.returncode,
    )
    for artifact in _collect_artifacts(job.output_dir):
        if artifact["kind"] in {"optimized_template_svg", "final_svg"}:
            job.push("artifact", artifact)
    job.push("status", {"state": "finished", "code": job.process.returncode})
    job.push(
        "artifact",
        {
            "kind": "log",
            "name": job.log_path.name,
            "path": job.log_path.relative_to(job.output_dir).as_posix(),
            "url": f"/api/artifacts/{job.job_id}/{job.log_path.name}",
        },
    )
    job.done = True
    job.push("close", {})


def _pipe_output(job: Job, pipe, stream_name: str) -> None:
    if pipe is None:
        return
    for line in iter(pipe.readline, ""):
        text = line.rstrip()
        if text:
            job.write_log(stream_name, text)
            job.push("log", {"stream": stream_name, "line": text})
    pipe.close()


def _scan_artifacts(job: Job) -> None:
    for artifact in _collect_artifacts(job.output_dir):
        rel_path = artifact["path"]
        if rel_path in job.seen:
            continue
        job.seen.add(rel_path)
        job.push("artifact", artifact)


def _port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("0.0.0.0", port))
        except OSError:
            return True
    return False


def _pids_on_port(port: int) -> set[int]:
    pids: set[int] = set()

    if shutil.which("lsof"):
        result = subprocess.run(
            ["lsof", "-t", f"-i:{port}"],
            capture_output=True,
            text=True,
        )
        for line in result.stdout.splitlines():
            line = line.strip()
            if line.isdigit():
                pids.add(int(line))
        return pids

    if shutil.which("ss"):
        result = subprocess.run(
            ["ss", "-lptn", f"sport = :{port}"],
            capture_output=True,
            text=True,
        )
        for line in result.stdout.splitlines():
            if "pid=" in line:
                for part in line.split("pid=")[1:]:
                    pid_str = "".join(ch for ch in part if ch.isdigit())
                    if pid_str:
                        pids.add(int(pid_str))
        return pids

    if shutil.which("netstat"):
        result = subprocess.run(
            ["netstat", "-tlnp"],
            capture_output=True,
            text=True,
        )
        for line in result.stdout.splitlines():
            if f":{port} " not in line or "LISTEN" not in line:
                continue
            fields = line.split()
            if fields and "/" in fields[-1]:
                pid_part = fields[-1].split("/")[0]
                if pid_part.isdigit():
                    pids.add(int(pid_part))

    return pids


def _read_cmdline(pid: int) -> str:
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as handle:
            data = handle.read()
        parts = [p for p in data.split(b"\x00") if p]
        return " ".join(part.decode(errors="ignore") for part in parts)
    except OSError:
        return ""


def _is_uvicorn_process(pid: int) -> bool:
    cmdline = _read_cmdline(pid)
    if not cmdline:
        return False
    if "uvicorn" not in cmdline:
        return False
    return "server:app" in cmdline or "server.py" in cmdline


def _terminate_pids(pids: set[int], timeout: float = 2.0) -> None:
    current_pid = os.getpid()
    for pid in sorted(pids):
        if pid <= 1 or pid == current_pid:
            continue
        if not _is_uvicorn_process(pid):
            continue
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            continue

    deadline = time.time() + timeout
    while time.time() < deadline:
        alive = False
        for pid in pids:
            if pid <= 1 or pid == current_pid:
                continue
            if not _is_uvicorn_process(pid):
                continue
            try:
                os.kill(pid, 0)
                alive = True
            except ProcessLookupError:
                continue
        if not alive:
            return
        time.sleep(0.1)

    for pid in sorted(pids):
        if pid <= 1 or pid == current_pid:
            continue
        if not _is_uvicorn_process(pid):
            continue
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            continue


def _ensure_port_free(port: int) -> None:
    if not _port_in_use(port):
        return
    pids = _pids_on_port(port)
    if not pids:
        return
    _terminate_pids(pids)


app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="static")


if __name__ == "__main__":
    import uvicorn

    def find_available_port(start_port: int, max_attempts: int = 100) -> int:
        for port in range(start_port, start_port + max_attempts):
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                try:
                    sock.bind(("0.0.0.0", port))
                    return port
                except OSError:
                    print(f"Port {port} is in use, trying next...")
                    continue
        raise IOError(f"No available ports found in range ({start_port} - {start_port + max_attempts})")

    initial_port = 8000
    
    try:
        actual_port = find_available_port(initial_port)
        
        print(f"--- Starting Server ---")
        print(f"Local access: http://127.0.0.1:{actual_port}")
        print(f"-----------------------")

        uvicorn.run(
            "server:app",
            host="0.0.0.0",
            port=actual_port,
            reload=False,
            access_log=False,
        )
    except Exception as e:
        print(f"Startup failed: {e}")
        sys.exit(1)
