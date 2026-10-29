"""Right-angle marker detection.

Two perpendicular lines are NOT enough: the small square mark must itself be
traced by ink.  We erase long structural edges from an evidence copy, then test
rotated/normalised square templates in the quadrant spanned by the two arms.
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from ..config import PROJECT_ROOT
from .common import (
    cluster_points,
    draw_box,
    draw_label,
    draw_segment,
    envelope,
    estimate_stroke_width,
    load_ink,
    new_overlay,
    normalize_point,
    parse_roi,
    point_line_distance,
    roi_info,
    save_png,
    thin,
)


def _line_intersection(a: np.ndarray, b: np.ndarray, c: np.ndarray, d: np.ndarray) -> tuple[np.ndarray, float, float] | None:
    r = b - a
    s = d - c
    den = r[0] * s[1] - r[1] * s[0]
    if abs(den) < 1e-9:
        return None
    ca = c - a
    t = (ca[0] * s[1] - ca[1] * s[0]) / den
    u = (ca[0] * r[1] - ca[1] * r[0]) / den
    return a + t * r, t, u


def _seg_cov(dil: np.ndarray, p: Any, q: Any, lo: float = 0.12, hi: float = 0.88) -> float:
    p = np.asarray(p, float)
    q = np.asarray(q, float)
    length = float(np.linalg.norm(q - p))
    if length < 1e-6:
        return 0.0
    n = max(5, int(length))
    ts = np.linspace(lo, hi, n)
    h, w = dil.shape
    xs = np.clip(np.round(p[0] + ts * (q[0] - p[0])).astype(int), 0, w - 1)
    ys = np.clip(np.round(p[1] + ts * (q[1] - p[1])).astype(int), 0, h - 1)
    return float(dil[ys, xs].mean())


def _estimate_cap_height(mask: np.ndarray, stroke_w: float) -> float:
    """Median height of compact components, used as a glyph cap-height proxy."""
    n, lab, stats, _ = cv2.connectedComponentsWithStats((mask > 0).astype(np.uint8), 8)
    heights = []
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if area < 6 or area > 4000:
            continue
        if h < 4 or w < 2:
            continue
        aspect = w / max(h, 1)
        if 0.15 <= aspect <= 3.0 and h <= 4.0 * stroke_w + 30:
            heights.append(h)
    if heights:
        return float(np.clip(np.median(heights), 10.0, 30.0))
    return 20.0


def _erase_long_edges(mask: np.ndarray, edges: list[list[float]], stroke_w: float, cap_h: float) -> np.ndarray:
    independent = mask.astype(np.uint8).copy()
    for seg in edges:
        a = np.array([seg[0], seg[1]], float)
        b = np.array([seg[2], seg[3]], float)
        if np.linalg.norm(b - a) >= 4.0 * cap_h:
            cv2.line(
                independent,
                tuple(np.round(a).astype(int)),
                tuple(np.round(b).astype(int)),
                0,
                max(3, int(math.ceil(2.0 * stroke_w + 1))),
            )
    return independent


def detect_right_angle_marker(
    image_path: str | Path,
    roi: Any = None,
    *,
    lines: list[dict[str, Any]] | None = None,
    angle_tol_deg: float = 10.0,
    visualize: bool = True,
    out_dir: str | Path | None = None,
) -> dict[str, Any]:
    mask, _grey = load_ink(image_path)
    height, width = mask.shape
    roi_box = parse_roi(roi, width, height)
    sub_mask = mask[roi_box.y0:roi_box.y1, roi_box.x0:roi_box.x1]
    skel = thin(sub_mask)
    stroke_w = estimate_stroke_width(sub_mask, skel)
    cap_h = _estimate_cap_height(sub_mask, stroke_w)

    # All line coordinates below are full-image pixel coordinates.
    raw: list[list[float]] = []
    if lines:
        if isinstance(lines[0], dict):
            raw = [[*seg["a_px"], *seg["b_px"]] for seg in lines if "a_px" in seg]
        else:
            raw = [[float(v) for v in seg] for seg in lines if len(seg) == 4]
    else:
        from .line_detection import detect_lines

        detected = detect_lines(image_path, roi, visualize=False)
        raw = [[*s["a_px"], *s["b_px"]] for s in detected["results"]["segments"]]
    lines = raw

    # Keep only long structural edges for vertex candidates.
    structural = [seg for seg in lines if math.hypot(seg[2] - seg[0], seg[3] - seg[1]) >= 3.0 * cap_h]
    vertices: list[np.ndarray] = []
    incident: dict[int, list[list[float]]] = {}
    for i in range(len(structural)):
        for j in range(i + 1, len(structural)):
            a = np.array([structural[i][0], structural[i][1]], float)
            b = np.array([structural[i][2], structural[i][3]], float)
            c = np.array([structural[j][0], structural[j][1]], float)
            d = np.array([structural[j][2], structural[j][3]], float)
            hit = _line_intersection(a, b, c, d)
            if hit is None:
                continue
            p, t, u = hit
            if not (-0.06 <= t <= 1.06 and -0.06 <= u <= 1.06):
                continue
            angle = abs(math.degrees(math.atan2(b[1] - a[1], b[0] - a[0]) - math.atan2(d[1] - c[1], d[0] - c[0]))) % 180
            angle = min(angle, 180 - angle)
            if abs(angle - 90.0) > angle_tol_deg:
                continue
            vertices.append(p)
            incident.setdefault(len(vertices) - 1, [])
    if not vertices:
        notes = ["no near-perpendicular line pair was found inside the ROI"]
        viz = None
        return envelope(
            "detect_right_angle_marker",
            image_path,
            roi=roi_info(roi_box, width, height),
            method="perpendicular line-pair candidates + local square-mark verification",
            params={"angle_tol_deg": angle_tol_deg, "cap_height_px": round(cap_h, 2)},
            results={"count": 0, "markers": [], "perpendicular_without_mark": []},
            notes=notes,
            visualization=viz,
        )

    clustered = cluster_points(vertices, eps=max(4.0, 1.6 * stroke_w))

    # Build independent evidence: original ink minus long structural edges.
    independent = _erase_long_edges(mask, lines, stroke_w, cap_h)
    k = 2 * max(1, int(round(stroke_w / 2))) + 1
    dil = cv2.dilate((mask > 0).astype(np.uint8), np.ones((k, k), np.uint8), 1)
    dil_independent = cv2.dilate(independent, np.ones((k, k), np.uint8), 1)

    markers: list[dict[str, Any]] = []
    perpendicular_without_mark: list[dict[str, Any]] = []
    s_values = [f * cap_h for f in np.arange(0.55, 1.45, 0.1)]
    for vertex in clustered:
        V = np.asarray(vertex, float)
        arms: list[np.ndarray] = []
        for seg in structural:
            a = np.array([seg[0], seg[1]], float)
            b = np.array([seg[2], seg[3]], float)
            if point_line_distance(V, a, b) > max(2.5 * stroke_w, 4.0, 0.5 * cap_h):
                continue
            for endpoint in (a, b):
                direction = endpoint - V
                norm = float(np.linalg.norm(direction))
                if norm < 0.6 * cap_h:
                    continue
                unit = direction / norm
                if all(float(unit @ other) < 0.995 for other in arms):
                    arms.append(unit)
        if len(arms) < 2:
            continue
        accepted = None
        for i in range(len(arms)):
            for j in range(i + 1, len(arms)):
                u1, u2 = arms[i], arms[j]
                if abs(float(u1 @ u2)) > 0.20:  # not perpendicular
                    continue
                for s in s_values:
                    p1 = V + s * u1
                    p2 = V + s * (u1 + u2)
                    p3 = V + s * u2
                    side1 = _seg_cov(dil, p1, p2)
                    side2 = _seg_cov(dil, p2, p3)
                    ind1 = _seg_cov(dil_independent, p1, p2)
                    ind2 = _seg_cov(dil_independent, p2, p3)
                    interior = _seg_cov(dil, V, p2, 0.30, 0.80)
                    if side1 > 0.62 and side2 > 0.62 and interior < 0.35 and (ind1 > 0.48 or ind2 > 0.48):
                        accepted = {
                            "vertex_px": [round(float(V[0]), 2), round(float(V[1]), 2)],
                            "vertex_norm": normalize_point(V[0], V[1], width, height),
                            "arms": [
                                [round(float(u1[0]), 4), round(float(u1[1]), 4)],
                                [round(float(u2[0]), 4), round(float(u2[1]), 4)],
                            ],
                            "side_length_px": round(float(s), 2),
                            "mark_points_px": [
                                [round(float(p1[0]), 2), round(float(p1[1]), 2)],
                                [round(float(p2[0]), 2), round(float(p2[1]), 2)],
                                [round(float(p3[0]), 2), round(float(p3[1]), 2)],
                            ],
                            "evidence": {
                                "side1_ink_coverage": round(float(side1), 3),
                                "side2_ink_coverage": round(float(side2), 3),
                                "interior_ink_coverage": round(float(interior), 3),
                                "independent_side_coverage": [round(float(ind1), 3), round(float(ind2), 3)],
                                "coverage_kind": "pixel-ink fraction (heuristic, not probability)",
                            },
                        }
                        break
                if accepted:
                    break
            if accepted:
                break
        if accepted:
            markers.append(accepted)
        else:
            perpendicular_without_mark.append(
                {
                    "vertex_px": [round(float(V[0]), 2), round(float(V[1]), 2)],
                    "reason": "perpendicular edges present, but no independent square-mark ink was verified",
                }
            )

    for idx, marker in enumerate(markers, start=1):
        marker["id"] = f"right_angle_{idx:02d}"
        marker["note"] = "mark presence is verified from local ink, not from perpendicularity alone"

    viz = None
    if visualize:
        overlay = new_overlay(image_path)
        for marker in markers:
            pts = marker["mark_points_px"] + [marker["vertex_px"]]
            draw_segment(overlay, marker["vertex_px"], marker["mark_points_px"][0], (230, 120, 20), 1)
            draw_segment(overlay, marker["vertex_px"], marker["mark_points_px"][2], (230, 120, 20), 1)
            draw_segment(overlay, marker["mark_points_px"][0], marker["mark_points_px"][1], (230, 120, 20), 2)
            draw_segment(overlay, marker["mark_points_px"][1], marker["mark_points_px"][2], (230, 120, 20), 2)
            draw_label(overlay, marker["id"], marker["vertex_px"], (230, 120, 20))
            x0 = min(p[0] for p in pts) - 4
            y0 = min(p[1] for p in pts) - 4
            x1 = max(p[0] for p in pts) + 4
            y1 = max(p[1] for p in pts) + 4
            draw_box(overlay, [x0, y0, x1, y1], (230, 120, 20), 1)
        base = Path(out_dir) if out_dir else PROJECT_ROOT / "outputs" / "cv_preview" / Path(image_path).stem
        viz = save_png(base / "detect_right_angle_marker.png", overlay)

    notes = []
    if not markers:
        notes.append("no right-angle marker passed the local square-ink test; perpendicularity alone is not reported as a mark")
    if perpendicular_without_mark:
        notes.append(f"{len(perpendicular_without_mark)} perpendicular junction(s) had no verified square mark")

    return envelope(
        "detect_right_angle_marker",
        image_path,
        roi=roi_info(roi_box, width, height),
        method="perpendicular line-pair search + long-edge suppression + rotated square-ink verification",
        params={"angle_tol_deg": angle_tol_deg, "cap_height_px": round(cap_h, 2)},
        results={
            "count": len(markers),
            "markers": markers,
            "perpendicular_without_mark": perpendicular_without_mark,
        },
        notes=notes,
        visualization=viz,
    )
