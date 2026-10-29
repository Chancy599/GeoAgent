"""PDF→PNG rendering via PyMuPDF (no external rasteriser required)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import fitz  # PyMuPDF


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
            from PIL import Image, ImageChops

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
