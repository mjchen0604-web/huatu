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

import numpy as np
from PIL import Image


SVG_NS = "http://www.w3.org/2000/svg"
INKSCAPE_LABEL = "{http://www.inkscape.org/namespaces/inkscape}label"
SKIP_LAYER_TAGS = {"defs", "style", "metadata", "title", "desc", "script"}


@dataclass
class RenderedLayer:
    name: str
    image: Image.Image
    visible: bool = True


def export_layered_psd_from_svg(
    svg_path: str | Path,
    psd_path: str | Path | None = None,
    layers_zip_path: str | Path | None = None,
    source_image_path: str | Path | None = None,
    max_layers: int = 120,
) -> dict[str, str | int]:
    """Render SVG groups into PSD layers and optionally add the original image as a 1:1 base layer."""
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
        rendered_layers.append(RenderedLayer(name=f"GPT {name}", image=image, visible=False))
        image.save(layers_dir / f"{index:02d}_{_filename_safe(name)}.png")

    original_layer = _load_original_layer(source_image_path, width, height)
    if original_layer is not None:
        merged = original_layer.image.convert("RGB")
    else:
        merged = _merged_preview(rendered_layers, width, height)
    _write_psd(psd_path, width, height, rendered_layers, merged, original_layer=original_layer)

    with zipfile.ZipFile(layers_zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for layer_png in sorted(layers_dir.glob("*.png")):
            archive.write(layer_png, arcname=f"layers/{layer_png.name}")

    return {
        "psd_path": str(psd_path),
        "layers_zip_path": str(layers_zip_path),
        "layer_count": len(rendered_layers),
        "source_layer": 1 if original_layer is not None else 0,
        "width": width,
        "height": height,
    }


def export_layered_psd_from_image(
    image_path: str | Path,
    psd_path: str | Path | None = None,
    layers_zip_path: str | Path | None = None,
    *,
    max_layers: int = 32,
    white_threshold: int = 245,
    min_area: int = 48,
    dilation_iterations: int = 3,
) -> dict[str, str | int]:
    """Split a raster figure into full-canvas transparent PNG layers and write a PSD.

    This mode is intentionally independent from SVG/SAM. It keeps every exported
    layer at the original canvas size, removes only the connected white
    background, adds a white PSD base layer, and packages the transparent layer
    PNGs into layers.zip for manual Photoshop workflows.
    """
    image_path = Path(image_path)
    if psd_path is None:
        psd_path = image_path.with_name("final.psd")
    if layers_zip_path is None:
        layers_zip_path = image_path.with_name("layers.zip")
    psd_path = Path(psd_path)
    layers_zip_path = Path(layers_zip_path)

    source = Image.open(image_path).convert("RGBA")
    width, height = source.size
    arr = np.array(source)
    alpha_mask = arr[..., 3] > 8
    rgb = arr[..., :3].astype(np.int16)
    near_white = (
        (rgb[..., 0] >= white_threshold)
        & (rgb[..., 1] >= white_threshold)
        & (rgb[..., 2] >= white_threshold)
    )
    rgb_max = rgb.max(axis=2)
    rgb_min = rgb.min(axis=2)
    saturation = rgb_max - rgb_min
    neutral_light = (rgb_min >= 180) & (saturation <= 35)
    background_mask = (near_white | neutral_light) & alpha_mask
    foreground_mask = alpha_mask & ~background_mask

    layers_dir = image_path.parent / "layers"
    layers_dir.mkdir(parents=True, exist_ok=True)
    for old_png in layers_dir.glob("*.png"):
        old_png.unlink()

    grouped_mask = _dilate_mask(foreground_mask, iterations=dilation_iterations)
    components = _connected_components(grouped_mask, min_area=min_area)
    components.sort(key=lambda item: item["area"], reverse=True)

    rendered_layers: list[RenderedLayer] = []
    used_mask = np.zeros((height, width), dtype=bool)
    selected_components = components[:max_layers]
    for index, component in enumerate(selected_components, start=1):
        component_mask = np.zeros((height, width), dtype=bool)
        ys = component["ys"]
        xs = component["xs"]
        component_mask[ys, xs] = True
        layer_mask = foreground_mask & component_mask
        if int(layer_mask.sum()) < min_area:
            continue
        used_mask |= layer_mask
        name = f"Raster Layer {index:02d}"
        layer_image = _mask_to_layer_image(arr, layer_mask)
        rendered_layers.append(RenderedLayer(name, layer_image, visible=True))
        layer_image.save(layers_dir / f"{index:02d}_{_filename_safe(name)}.png")

    misc_mask = foreground_mask & ~used_mask
    if int(misc_mask.sum()) >= min_area:
        name = "Raster Layer Misc"
        layer_image = _mask_to_layer_image(arr, misc_mask)
        rendered_layers.append(RenderedLayer(name, layer_image, visible=True))
        layer_image.save(layers_dir / f"{len(rendered_layers):02d}_{_filename_safe(name)}.png")

    if not rendered_layers:
        layer_image = source.copy()
        rendered_layers.append(RenderedLayer("Raster Layer 01", layer_image, visible=True))
        layer_image.save(layers_dir / "01_Raster_Layer_01.png")

    _write_psd(psd_path, width, height, rendered_layers, source.convert("RGB"))

    with zipfile.ZipFile(layers_zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for layer_png in sorted(layers_dir.glob("*.png")):
            archive.write(layer_png, arcname=f"layers/{layer_png.name}")

    return {
        "psd_path": str(psd_path),
        "layers_zip_path": str(layers_zip_path),
        "layer_count": len(rendered_layers),
        "source_layer": 0,
        "width": width,
        "height": height,
    }


def _edge_connected_mask(candidate: np.ndarray) -> np.ndarray:
    """Return candidate pixels connected to the image border using 4-neighbours."""
    height, width = candidate.shape
    visited = np.zeros_like(candidate, dtype=bool)
    stack: list[tuple[int, int]] = []

    def push(y: int, x: int) -> None:
        if candidate[y, x] and not visited[y, x]:
            visited[y, x] = True
            stack.append((y, x))

    for x in range(width):
        push(0, x)
        push(height - 1, x)
    for y in range(height):
        push(y, 0)
        push(y, width - 1)

    while stack:
        y, x = stack.pop()
        if y > 0:
            push(y - 1, x)
        if y + 1 < height:
            push(y + 1, x)
        if x > 0:
            push(y, x - 1)
        if x + 1 < width:
            push(y, x + 1)
    return visited


def _dilate_mask(mask: np.ndarray, iterations: int = 3) -> np.ndarray:
    out = mask.astype(bool, copy=True)
    height, width = out.shape
    for _ in range(max(0, iterations)):
        padded = np.pad(out, 1, mode="constant", constant_values=False)
        grown = np.zeros_like(out, dtype=bool)
        for dy in range(3):
            for dx in range(3):
                grown |= padded[dy : dy + height, dx : dx + width]
        out = grown
    return out


def _connected_components(mask: np.ndarray, min_area: int = 48) -> list[dict[str, np.ndarray | int]]:
    height, width = mask.shape
    visited = np.zeros_like(mask, dtype=bool)
    components: list[dict[str, np.ndarray | int]] = []
    ys_all, xs_all = np.nonzero(mask)
    for start_y, start_x in zip(ys_all.tolist(), xs_all.tolist()):
        if visited[start_y, start_x]:
            continue
        visited[start_y, start_x] = True
        stack = [(start_y, start_x)]
        ys: list[int] = []
        xs: list[int] = []
        while stack:
            y, x = stack.pop()
            ys.append(y)
            xs.append(x)
            if y > 0 and mask[y - 1, x] and not visited[y - 1, x]:
                visited[y - 1, x] = True
                stack.append((y - 1, x))
            if y + 1 < height and mask[y + 1, x] and not visited[y + 1, x]:
                visited[y + 1, x] = True
                stack.append((y + 1, x))
            if x > 0 and mask[y, x - 1] and not visited[y, x - 1]:
                visited[y, x - 1] = True
                stack.append((y, x - 1))
            if x + 1 < width and mask[y, x + 1] and not visited[y, x + 1]:
                visited[y, x + 1] = True
                stack.append((y, x + 1))

        area = len(ys)
        if area >= min_area:
            components.append(
                {
                    "ys": np.array(ys, dtype=np.int32),
                    "xs": np.array(xs, dtype=np.int32),
                    "area": area,
                }
            )
    return components


def _mask_to_layer_image(source_rgba: np.ndarray, mask: np.ndarray) -> Image.Image:
    layer_arr = np.zeros_like(source_rgba)
    layer_arr[..., :3] = source_rgba[..., :3]
    layer_arr[..., 3] = np.where(mask, source_rgba[..., 3], 0).astype(np.uint8)
    return Image.fromarray(layer_arr, mode="RGBA")


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


def _load_original_layer(source_image_path: str | Path | None, width: int, height: int) -> RenderedLayer | None:
    if not source_image_path:
        return None
    path = Path(source_image_path)
    if not path.is_file():
        return None
    image = Image.open(path).convert("RGBA")
    if image.size != (width, height):
        image = image.resize((width, height), Image.Resampling.LANCZOS)
    return RenderedLayer("Original 1:1 Base Image", image, visible=True)


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


def _write_psd(
    path: Path,
    width: int,
    height: int,
    layers: list[RenderedLayer],
    merged: Image.Image,
    original_layer: RenderedLayer | None = None,
) -> None:
    layer_records = bytearray()
    layer_channel_data = bytearray()
    psd_layers = list(layers)
    if original_layer is not None:
        psd_layers.append(original_layer)
    psd_layers += [
        RenderedLayer("White Background", Image.new("RGBA", (width, height), "white"), visible=True)
    ]

    for layer in psd_layers:
        channels = _channel_data(layer.image)
        layer_records += struct.pack(">iiiiH", 0, 0, height, width, len(channels))
        for channel_id, data in channels:
            layer_records += struct.pack(">hI", channel_id, len(data) + 2)
        layer_records += b"8BIM"
        layer_records += b"norm"
        flags = 0 if layer.visible else 2
        layer_records += struct.pack(">BBBB", 255, 0, flags, 0)
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
