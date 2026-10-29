"""Non-destructive separation of text/glyph ink from line ink.

Produces two candidate masks (lines vs. text) plus a reconstruction check.  It
never overwrites the source image and reports competing hypotheses when the
evidence is ambiguous.
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from ..config import PROJECT_ROOT
from .common import (
    component_principal_axis,
    draw_box,
    envelope,
    estimate_stroke_width,
    hough_segments,
    load_ink,
    new_overlay,
    normalize_box,
    parse_roi,
    roi_info,
    save_png,
    thin,
)


def separate_text_and_lines(
    image_path: str | Path,
    roi: Any = None,
    *,
    visualize: bool = True,
    out_dir: str | Path | None = None,
) -> dict[str, Any]:
    mask, _grey = load_ink(image_path)
    height, width = mask.shape
    roi_box = parse_roi(roi, width, height)
    skel = thin(mask)
    stroke_w = estimate_stroke_width(mask, skel)
    base = Path(out_dir) if out_dir else PROJECT_ROOT / "outputs" / "cv_preview" / Path(image_path).stem
    base.mkdir(parents=True, exist_ok=True)

    raw_lines = hough_segments(skel, min_length_frac=0.025, max_gap_frac=0.008)
    roi_mask = np.zeros_like(mask)
    roi_mask[roi_box.y0:roi_box.y1, roi_box.x0:roi_box.x1] = mask[roi_box.y0:roi_box.y1, roi_box.x0:roi_box.x1]

    line_mask = np.zeros_like(mask)
    thickness = max(3, int(math.ceil(2.2 * stroke_w + 2)))
    for x1, y1, x2, y2 in raw_lines:
        cv2.line(line_mask, (int(x1), int(y1)), (int(x2), int(y2)), 1, thickness)
    line_mask = (line_mask & roi_mask).astype(np.uint8)

    # Dashes are line ink too, even when Hough cannot connect them.  Elongated,
    # thin components are added to the line hypothesis, never to text.
    residual0 = ((roi_mask > 0) & (line_mask == 0)).astype(np.uint8)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(residual0, 8)
    dash_like: list[np.ndarray] = []
    for i in range(1, n):
        x, y, w, h, area = (int(v) for v in stats[i])
        if area < 6:
            continue
        ys, xs = np.where(lab == i)
        pts = np.column_stack([xs, ys]).astype(float)
        p0, p1, major, minor = component_principal_axis(pts)
        if major >= 8.0 and major >= 4.0 * max(minor, 0.6) and minor <= 2.2 * stroke_w + 1.5:
            dash_like.append(pts.astype(int))
    for pts in dash_like:
        line_mask[pts[:, 1], pts[:, 0]] = 1

    text_mask = ((roi_mask > 0) & (line_mask == 0)).astype(np.uint8)
    text_mask = cv2.morphologyEx(text_mask, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)))
    n, lab, stats, centroids = cv2.connectedComponentsWithStats(text_mask, 8)
    text_components = []
    for i in range(1, n):
        x, y, w, h, area = (int(v) for v in stats[i])
        if area < 8 or h < 5:
            continue
        if h > 40 or w > 40 or w / max(h, 1) > 4:
            continue
        text_components.append(
            {
                "box_px": [x, y, x + w, y + h],
                "box_norm": normalize_box([x, y, x + w, y + h], width, height),
                "area_px": area,
                "centroid_px": [round(float(centroids[i][0]), 2), round(float(centroids[i][1]), 2)],
            }
        )

    removed = int(((roi_mask > 0) & (line_mask > 0)).sum())
    total_ink = int((roi_mask > 0).sum())
    text_ink = int((text_mask > 0).sum())
    reconstructed = ((line_mask > 0) | (text_mask > 0)).astype(np.uint8)
    reconstruction_coverage = float((reconstructed & roi_mask).sum() / max(1, total_ink))

    line_png = base / "text_line_separation_lines.png"
    text_png = base / "text_line_separation_text.png"
    save_png(line_png, np.repeat((line_mask * 255)[:, :, None], 3, axis=2))
    save_png(text_png, np.repeat((text_mask * 255)[:, :, None], 3, axis=2))

    viz = None
    if visualize:
        overlay = new_overlay(image_path)
        tint = overlay.copy()
        tint[line_mask > 0] = (240, 90, 70)
        tint[text_mask > 0] = (40, 160, 90)
        overlay = cv2.addWeighted(overlay, 0.35, tint, 0.65, 0)
        for comp in text_components:
            draw_box(overlay, comp["box_px"], (40, 160, 90), 1)
        viz = save_png(base / "separate_text_and_lines.png", overlay)

    hypotheses = [
        {
            "name": "line+text",
            "description": "long/dashed structures assigned to line ink; compact blobs assigned to text",
            "line_pixels": removed,
            "text_pixels": text_ink,
            "text_components": len(text_components),
            "reconstruction_coverage": round(reconstruction_coverage, 4),
        },
        {
            "name": "all_drawing",
            "description": "no separation; every ink pixel belongs to the geometric drawing",
            "line_pixels": total_ink,
            "text_pixels": 0,
            "text_components": 0,
            "reconstruction_coverage": 1.0,
        },
    ]
    ambiguous = reconstruction_coverage < 0.9 or text_ink > 0.35 * max(1, total_ink)
    notes = [
        "source image is untouched; masks are saved alongside the run outputs",
        "separation is heuristic: if the two hypotheses disagree strongly, consult a visual model",
    ]
    if ambiguous:
        notes.append("separation may be ambiguous (text/line competition is strong); candidate hypotheses are reported")

    return envelope(
        "separate_text_and_lines",
        image_path,
        roi=roi_info(roi_box, width, height),
        method="Hough long-structure mask + elongated-component dash recovery + residual glyph components",
        params={"stroke_width_px": round(stroke_w, 2), "line_thickness_px": thickness, "hough_segments": len(raw_lines)},
        results={
            "line_mask_png": str(line_png),
            "text_mask_png": str(text_png),
            "text_components": text_components,
            "metrics": {
                "total_ink_px": total_ink,
                "line_ink_px": removed,
                "text_ink_px": text_ink,
                "reconstruction_coverage": round(reconstruction_coverage, 4),
                "ambiguous": bool(ambiguous),
            },
            "hypotheses": hypotheses,
        },
        notes=notes,
        visualization=viz,
    )
