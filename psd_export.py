from __future__ import annotations

import copy
import io
import re
import struct
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from xml.etree import ElementTree as ET

from PIL import Image


SVG_NS = "http://www.w3.org/2000/svg"
INKSCAPE_LABEL = "{http://www.inkscape.org/namespaces/inkscape}label"
SKIP_LAYER_TAGS = {"defs", "style", "metadata", "title", "desc", "script"}


@dataclass
class RenderedLayer:
    name: str
    image: Image.Image


def export_layered_psd_from_svg(
    svg_path: str | Path,
    psd_path: str | Path | None = None,
    layers_zip_path: str | Path | None = None,
    max_layers: int = 120,
) -> dict[str, str | int]:
    """Render SVG groups into full-canvas transparent PSD layers."""
    svg_path = Path(svg_path)
    if psd_path is None:
        psd_path = svg_path.with_name("final.psd")
    if layers_zip_path is None:
        layers_zip_path = svg_path.with_name("layers.zip")
    psd_path = Path(psd_path)
    layers_zip_path = Path(layers_zip_path)

    root = ET.fromstring(svg_path.read_text(encoding="utf-8"))
    width, height = _svg_dimensions(root)
    layer_nodes = _select_layer_nodes(root)[:max_layers]
    if not layer_nodes:
        raise ValueError("SVG does not contain visible elements to export as PSD layers")

    rendered_layers: list[RenderedLayer] = []
    layers_dir = svg_path.parent / "layers"
    layers_dir.mkdir(parents=True, exist_ok=True)
    for index, node in enumerate(layer_nodes, start=1):
        raw_name = _layer_name(node, index)
        name = _clean_layer_name(raw_name, index)
        layer_svg = _build_single_layer_svg(root, node)
        png_bytes = _render_svg_png(layer_svg, width, height)
        image = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
        rendered_layers.append(RenderedLayer(name=name, image=image))
        image.save(layers_dir / f"{index:02d}_{_filename_safe(name)}.png")

    merged = _merged_preview(rendered_layers, width, height)
    _write_psd(psd_path, width, height, rendered_layers, merged)

    with zipfile.ZipFile(layers_zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for layer_png in sorted(layers_dir.glob("*.png")):
            archive.write(layer_png, arcname=f"layers/{layer_png.name}")

    return {
        "psd_path": str(psd_path),
        "layers_zip_path": str(layers_zip_path),
        "layer_count": len(rendered_layers),
        "width": width,
        "height": height,
    }


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _parse_svg_length(value: str | None) -> int | None:
    if not value:
        return None
    match = re.match(r"\s*([0-9.]+)", value)
    if not match:
        return None
    return max(1, int(round(float(match.group(1)))))


def _svg_dimensions(root: ET.Element) -> tuple[int, int]:
    width = _parse_svg_length(root.get("width"))
    height = _parse_svg_length(root.get("height"))
    view_box = root.get("viewBox") or root.get("viewbox")
    if (width is None or height is None) and view_box:
        parts = re.split(r"[\s,]+", view_box.strip())
        if len(parts) == 4:
            width = width or max(1, int(round(float(parts[2]))))
            height = height or max(1, int(round(float(parts[3]))))
    if width is None or height is None:
        raise ValueError("SVG must define width/height or viewBox for PSD export")
    return width, height


def _visible_top_level_children(root: ET.Element) -> list[ET.Element]:
    return [
        child
        for child in list(root)
        if _local_name(child.tag) not in SKIP_LAYER_TAGS and child.get("display") != "none"
    ]


def _select_layer_nodes(root: ET.Element) -> list[ET.Element]:
    top_level = _visible_top_level_children(root)
    semantic_groups = [
        child
        for child in top_level
        if _local_name(child.tag) == "g"
        and (
            child.get("data-layer-name")
            or child.get(INKSCAPE_LABEL)
            or child.get("id")
            or "layer" in (child.get("class") or "").lower()
        )
    ]
    if len(semantic_groups) >= 2:
        return semantic_groups

    groups = [child for child in top_level if _local_name(child.tag) == "g"]
    if len(groups) >= 2:
        return groups
    return top_level


def _layer_name(node: ET.Element, index: int) -> str:
    return (
        node.get("data-layer-name")
        or node.get(INKSCAPE_LABEL)
        or node.get("id")
        or node.get("class")
        or f"Layer {index:02d}"
    )


def _clean_layer_name(name: str, index: int) -> str:
    cleaned = re.sub(r"\s+", " ", str(name)).strip()
    cleaned = cleaned[:80] if cleaned else f"Layer {index:02d}"
    return cleaned


def _filename_safe(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._")
    return cleaned[:80] or "layer"


def _build_single_layer_svg(original_root: ET.Element, layer_node: ET.Element) -> bytes:
    ET.register_namespace("", SVG_NS)
    root = ET.Element(original_root.tag, original_root.attrib)
    for child in list(original_root):
        if _local_name(child.tag) in {"defs", "style"}:
            root.append(copy.deepcopy(child))
    root.append(copy.deepcopy(layer_node))
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _render_svg_png(svg_bytes: bytes, width: int, height: int) -> bytes:
    import cairosvg

    return cairosvg.svg2png(
        bytestring=svg_bytes,
        output_width=width,
        output_height=height,
    )


def _merged_preview(layers: Iterable[RenderedLayer], width: int, height: int) -> Image.Image:
    canvas = Image.new("RGBA", (width, height), "white")
    for layer in layers:
        canvas.alpha_composite(layer.image)
    return canvas.convert("RGB")


def _pascal_string(value: str) -> bytes:
    encoded = value.encode("macroman", errors="replace")[:255]
    payload = bytes([len(encoded)]) + encoded
    padding = (4 - (len(payload) % 4)) % 4
    return payload + (b"\0" * padding)


def _channel_data(image: Image.Image) -> list[tuple[int, bytes]]:
    rgba = image.convert("RGBA")
    r, g, b, a = rgba.split()
    return [
        (0, r.tobytes()),
        (1, g.tobytes()),
        (2, b.tobytes()),
        (-1, a.tobytes()),
    ]


def _write_psd(path: Path, width: int, height: int, layers: list[RenderedLayer], merged: Image.Image) -> None:
    layer_records = bytearray()
    layer_channel_data = bytearray()
    psd_layers = list(layers) + [
        RenderedLayer("White Background", Image.new("RGBA", (width, height), "white"))
    ]

    for layer in psd_layers:
        channels = _channel_data(layer.image)
        layer_records += struct.pack(">iiiiH", 0, 0, height, width, len(channels))
        for channel_id, data in channels:
            layer_records += struct.pack(">hI", channel_id, len(data) + 2)
        layer_records += b"8BIM"
        layer_records += b"norm"
        layer_records += struct.pack(">BBBB", 255, 0, 0, 0)
        extra = struct.pack(">I", 0) + struct.pack(">I", 0) + _pascal_string(layer.name)
        layer_records += struct.pack(">I", len(extra))
        layer_records += extra
        for _channel_id, data in channels:
            layer_channel_data += struct.pack(">H", 0)
            layer_channel_data += data

    layer_info = struct.pack(">h", len(psd_layers)) + layer_records + layer_channel_data
    layer_and_mask = struct.pack(">I", len(layer_info)) + layer_info + struct.pack(">I", 0)

    merged_rgb = merged.convert("RGB")
    r, g, b = merged_rgb.split()
    merged_data = struct.pack(">H", 0) + r.tobytes() + g.tobytes() + b.tobytes()

    with path.open("wb") as handle:
        handle.write(b"8BPS")
        handle.write(struct.pack(">H", 1))
        handle.write(b"\0" * 6)
        handle.write(struct.pack(">HIIHH", 3, height, width, 8, 3))
        handle.write(struct.pack(">I", 0))
        handle.write(struct.pack(">I", 0))
        handle.write(struct.pack(">I", len(layer_and_mask)))
        handle.write(layer_and_mask)
        handle.write(merged_data)
