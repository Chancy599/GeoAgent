"""PDF→PNG rendering via PyMuPDF (no external rasteriser required)."""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import fitz  # PyMuPDF
from PIL import Image, ImageChops


def render_pdf(
    pdf_path: str | Path,
    png_path: str | Path | None = None,
    *,
    dpi: int = 200,
    crop_white: bool = True,
    margin_px: int = 8,
) -> dict[str, Any]:
    """Render the first PDF page and optionally trim surrounding white space."""
    source = Path(pdf_path)
    if not source.exists():
        return {"ok": False, "error": f"PDF not found: {source}", "png_path": None}
    target = Path(png_path) if png_path else source.with_suffix(".png")
    target.parent.mkdir(parents=True, exist_ok=True)

    try:
        with fitz.open(source) as doc:
            if doc.page_count == 0:
                return {"ok": False, "error": "PDF has no pages", "png_path": None}
            page = doc.load_page(0)
            pix = page.get_pixmap(dpi=dpi, alpha=False)
            png_bytes = pix.tobytes("png")
        target.write_bytes(png_bytes)

        if crop_white:
            with Image.open(target) as im:
                rgb = im.convert("RGB")
                background = Image.new("RGB", rgb.size, (255, 255, 255))
                diff = ImageChops.difference(rgb, background)
                bbox = diff.getbbox()
                if bbox and bbox != (0, 0, rgb.width, rgb.height):
                    x0, y0, x1, y1 = bbox
                    x0, y0 = max(0, x0 - margin_px), max(0, y0 - margin_px)
                    x1 = min(rgb.width, x1 + margin_px)
                    y1 = min(rgb.height, y1 + margin_px)
                    rgb.crop((x0, y0, x1, y1)).save(target, format="PNG")
        with Image.open(target) as im:
            size = list(im.size)
        return {"ok": True, "png_path": str(target), "size": size, "dpi": dpi}
    except Exception as exc:  # pragma: no cover - corrupt PDFs
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}", "png_path": None}


def _flatten(image: Image.Image) -> Image.Image:
    """Composite transparency onto white; plain RGB passes through."""
    if image.mode in ("RGBA", "LA") or "transparency" in image.info:
        rgba = image.convert("RGBA")
        return Image.alpha_composite(Image.new("RGBA", rgba.size, "white"), rgba).convert("RGB")
    return image.convert("RGB")


def _ink_bbox(image: Image.Image, threshold: int = 245) -> tuple[int, int, int, int] | None:
    grey = image.convert("L")
    mask = grey.point(lambda value: 255 if value < threshold else 0)
    return mask.getbbox()


def frame_like_original(
    render_path: str | Path,
    original_path: str | Path,
    *,
    threshold: int = 245,
) -> dict[str, Any]:
    """Re-frame a rendered figure so its canvas matches the source image.

    The standalone PDF is tightly cropped around its ink, while the dataset
    image keeps its own margins.  Scaling the render's ink box onto the
    original's ink box (same centre, same extent, white canvas of the original
    size) makes whole-image metrics and the critic panels see both figures at
    the same framing instead of two different amounts of white space.
    """
    render_file = Path(render_path)
    try:
        with Image.open(original_path) as raw_original:
            original = _flatten(raw_original)
        with Image.open(render_file) as raw_render:
            render = _flatten(raw_render)
        original_box = _ink_bbox(original, threshold)
        render_box = _ink_bbox(render, threshold)
        if not original_box or not render_box:
            return {"ok": False, "error": "missing ink bounding box", "png_path": str(render_file)}
        ow, oh = original_box[2] - original_box[0], original_box[3] - original_box[1]
        rw, rh = render_box[2] - render_box[0], render_box[3] - render_box[1]
        if min(ow, oh, rw, rh) <= 0:
            return {"ok": False, "error": "degenerate ink bounding box", "png_path": str(render_file)}
        factor = min(ow / rw, oh / rh)
        if not math.isfinite(factor) or factor <= 0:
            return {"ok": False, "error": f"invalid scale {factor}", "png_path": str(render_file)}
        size = (
            max(1, round(render.width * factor)),
            max(1, round(render.height * factor)),
        )
        scaled = render.resize(size, Image.Resampling.LANCZOS)
        # Align the render ink box centre to the original ink box centre.
        paste_x = round((original_box[0] + original_box[2]) / 2 - (render_box[0] + render_box[2]) / 2 * factor)
        paste_y = round((original_box[1] + original_box[3]) / 2 - (render_box[1] + render_box[3]) / 2 * factor)
        canvas = Image.new("RGB", original.size, (255, 255, 255))
        canvas.paste(scaled, (max(0, paste_x), max(0, paste_y)))
        canvas.save(render_file, format="PNG")
        return {
            "ok": True,
            "png_path": str(render_file),
            "size": list(canvas.size),
            "reference_size": list(original.size),
            "scale": round(float(factor), 4),
            "offset": [int(paste_x), int(paste_y)],
        }
    except Exception as exc:  # pragma: no cover - corrupt images
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}", "png_path": str(render_file)}
