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
    point_segment_distance,
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
    """Glyph cap-height proxy.

    Dash fragments and line stubs are numerous and tiny; a plain median drags
    the estimate down to ~10 px on dashed figures.  Keep only glyph-like
    components and use the upper quartile, which tracks the real text size.
    """
    n, _lab, stats, _ = cv2.connectedComponentsWithStats((mask > 0).astype(np.uint8), 8)
    heights: list[int] = []
    limit = 0.18 * min(mask.shape)
    for i in range(1, n):
        _x, _y, w, h, area = stats[i]
        if area < 25 or h < 12 or w < 4:
            continue
        if h > limit:
            continue
        aspect = w / max(h, 1)
        if 0.2 <= aspect <= 3.0 and h <= 6.0 * stroke_w + 40:
            heights.append(int(h))
    if heights:
        return float(np.clip(np.percentile(heights, 75), 10.0, 40.0))
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


def _unit(vec: np.ndarray) -> np.ndarray | None:
    norm = float(np.linalg.norm(vec))
    if norm < 1e-6:
        return None
    return vec / norm


def _direction_gap_deg(u: np.ndarray, v: np.ndarray) -> float:
    return float(math.degrees(math.acos(min(1.0, abs(float(u @ v))))))


def _line_foot(point: Any, a: Any, b: Any) -> np.ndarray:
    """Foot of the perpendicular from ``point`` onto the line through ``a``-``b``."""
    point = np.asarray(point, float)
    a = np.asarray(a, float)
    b = np.asarray(b, float)
    unit = _unit(b - a)
    if unit is None:
        return a.copy()
    return a + float((point - a) @ unit) * unit


def _supported_arm(
    vertex: np.ndarray,
    p1: np.ndarray,
    p3: np.ndarray,
    structural: list[list[float]],
    stroke_w: float,
    cap_h: float,
) -> tuple[int, list[float]] | None:
    """Return (1|3, long line) when one arm lies on a long structural edge."""
    tol = max(3.0, 0.5 * cap_h)
    for seg in structural:
        a = np.array([seg[0], seg[1]], float)
        b = np.array([seg[2], seg[3]], float)
        if point_segment_distance(vertex, a, b) > tol:
            continue
        unit = _unit(b - a)
        if unit is None:
            continue
        for which, point in ((1, p1), (3, p3)):
            direction = _unit(point - vertex)
            if direction is not None and _direction_gap_deg(direction, unit) < 15.0:
                return which, seg
    return None


def _detect_square_fallback(
    skel: np.ndarray,
    roi_box: Any,
    structural: list[list[float]],
    dil: np.ndarray,
    dil_independent: np.ndarray,
    stroke_w: float,
    cap_h: float,
) -> list[dict[str, Any]]:
    """Find right-angle squares whose second arm is dashed.

    The main path needs two long perpendicular edges; a dashed arm breaks into
    fragments and never qualifies.  Here we pair two short perpendicular
    fragments that meet at the outer square corner, rebuild the square, and
    snap the vertex onto the one arm that *is* a long structural edge.
    """
    min_len = max(6, int(round(0.45 * cap_h)))
    max_gap = max(2, int(round(0.2 * cap_h)))
    segments = cv2.HoughLinesP(
        skel,
        1,
        np.pi / 360.0,
        threshold=max(6, int(round(0.30 * cap_h))),
        minLineLength=min_len,
        maxLineGap=max_gap,
    )
    if segments is None:
        return []

    fragments: list[tuple[np.ndarray, np.ndarray, float]] = []
    for x1, y1, x2, y2 in segments[:, 0]:
        a = np.array([x1 + roi_box.x0, y1 + roi_box.y0], float)
        b = np.array([x2 + roi_box.x0, y2 + roi_box.y0], float)
        length = float(np.linalg.norm(b - a))
        if 0.5 * cap_h <= length <= 1.6 * cap_h:
            fragments.append((a, b, length))

    corner_tol = max(4.0, 0.5 * cap_h)
    found: list[dict[str, Any]] = []
    for i in range(len(fragments)):
        for j in range(i + 1, len(fragments)):
            a, b, _ = fragments[i]
            c, d, _ = fragments[j]
            angle = abs(
                math.degrees(math.atan2(b[1] - a[1], b[0] - a[0])
                             - math.atan2(d[1] - c[1], d[0] - c[0]))
            ) % 180.0
            angle = min(angle, 180.0 - angle)
            if abs(angle - 90.0) > 16.0:
                continue
            hit = _line_intersection(a, b, c, d)
            if hit is None:
                continue
            corner, t, u = hit
            # Hough truncates strokes near corners; the endpoint-gap test below
            # already keeps the intersection local, so allow some shortfall.
            if not (-0.6 <= t <= 1.6 and -0.6 <= u <= 1.6):
                continue
            end_gap = max(
                min(float(np.linalg.norm(corner - a)), float(np.linalg.norm(corner - b))),
                min(float(np.linalg.norm(corner - c)), float(np.linalg.norm(corner - d))),
            )
            if end_gap > corner_tol:
                continue
            far1 = a if np.linalg.norm(corner - a) > np.linalg.norm(corner - b) else b
            far2 = c if np.linalg.norm(corner - c) > np.linalg.norm(corner - d) else d
            if min(float(np.linalg.norm(corner - far1)), float(np.linalg.norm(corner - far2))) < 0.55 * cap_h:
                continue
            d1 = _unit(far1 - corner)
            d2 = _unit(far2 - corner)
            if d1 is None or d2 is None or abs(float(d1 @ d2)) > 0.30:
                continue
            base = 0.5 * (float(np.linalg.norm(corner - far1)) + float(np.linalg.norm(corner - far2)))
            for s in (0.85 * base, 0.95 * base, base, 1.05 * base, 1.15 * base):
                vertex = corner + s * (d1 + d2)
                p1 = corner + s * d2
                p3 = corner + s * d1
                side1 = _seg_cov(dil, corner, p3)
                side2 = _seg_cov(dil, corner, p1)
                ind1 = _seg_cov(dil_independent, corner, p3)
                ind2 = _seg_cov(dil_independent, corner, p1)
                interior = _seg_cov(dil, vertex, corner, 0.30, 0.80)
                arm1 = _seg_cov(dil, vertex, p1, 0.15, 0.95)
                arm2 = _seg_cov(dil, vertex, p3, 0.15, 0.95)
                support = _supported_arm(vertex, p1, p3, structural, stroke_w, cap_h)
                if not (
                    side1 > 0.60
                    and side2 > 0.60
                    and interior < 0.35
                    and (ind1 > 0.48 or ind2 > 0.48)
                    and arm1 > 0.30
                    and arm2 > 0.30
                    and support is not None
                ):
                    continue
                which, line = support
                p_supported, p_other = (p1, p3) if which == 1 else (p3, p1)
                vertex = _line_foot(p_other, line[0:2], line[2:4])
                u_supported = _unit(p_supported - vertex)
                u_other = _unit(p_other - vertex)
                if u_supported is None or u_other is None:
                    continue
                side_len = 0.5 * (
                    float(np.linalg.norm(p_supported - vertex)) + float(np.linalg.norm(p_other - vertex))
                )
                # The dashed arm must continue *past* the square; this rejects
                # L-shaped glyph strokes that happen to look perpendicular.
                ext_other = _seg_cov(dil, p_other, p_other + 1.2 * side_len * u_other, 0.0, 1.0)
                ext_supported = _seg_cov(dil, p_supported, p_supported + 1.5 * side_len * u_supported, 0.0, 1.0)
                if ext_other < 0.45 or ext_supported < 0.40:
                    continue
                m1 = vertex + side_len * u_supported
                m2 = vertex + side_len * (u_supported + u_other)
                m3 = vertex + side_len * u_other
                found.append(
                    {
                        "vertex_px": [round(float(vertex[0]), 2), round(float(vertex[1]), 2)],
                        "arms": [
                            [round(float(u_supported[0]), 4), round(float(u_supported[1]), 4)],
                            [round(float(u_other[0]), 4), round(float(u_other[1]), 4)],
                        ],
                        "side_length_px": round(float(side_len), 2),
                        "mark_points_px": [
                            [round(float(m1[0]), 2), round(float(m1[1]), 2)],
                            [round(float(m2[0]), 2), round(float(m2[1]), 2)],
                            [round(float(m3[0]), 2), round(float(m3[1]), 2)],
                        ],
                        "evidence": {
                            "side1_ink_coverage": round(float(side1), 3),
                            "side2_ink_coverage": round(float(side2), 3),
                            "interior_ink_coverage": round(float(interior), 3),
                            "independent_side_coverage": [round(float(ind1), 3), round(float(ind2), 3)],
                            "arm_extension_coverage": [round(float(ext_supported), 3), round(float(ext_other), 3)],
                            "coverage_kind": "pixel-ink fraction (heuristic, not probability)",
                            "dashed_arm_fallback": True,
                        },
                        "_score": side1 + side2 + ind1 + ind2 + ext_other + ext_supported,
                        "_vertex": vertex,
                    }
                )
                break

    found.sort(key=lambda m: m["_score"], reverse=True)
    markers: list[dict[str, Any]] = []
    for marker in found:
        if all(
            float(np.linalg.norm(marker["_vertex"] - kept["_vertex"])) > 0.6 * cap_h
            for kept in markers
        ):
            marker.pop("_score", None)
            marker.pop("_vertex", None)
            markers.append(marker)
    return markers


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
    if roi is None:
        stroke_w = estimate_stroke_width(sub_mask, skel)
        cap_h = _estimate_cap_height(sub_mask, stroke_w)
    else:
        # Size thresholds on the whole figure: a small ROI crop (e.g. 40x40)
        # contains only the mark itself and would make cap height and stroke
        # width meaningless.
        full_skel = thin(mask)
        stroke_w = estimate_stroke_width(mask, full_skel)
        cap_h = _estimate_cap_height(mask, stroke_w)

    # All line coordinates below are full-image pixel coordinates.
    supplied_lines = bool(lines)
    raw: list[list[float]] = []
    if lines:
        if isinstance(lines[0], dict):
            raw = [[*seg["a_px"], *seg["b_px"]] for seg in lines if "a_px" in seg]
        else:
            raw = [[float(v) for v in seg] for seg in lines if len(seg) == 4]
    else:
        from .line_detection import detect_lines

        # Detect on the full image even when a ROI is given: cropping the image
        # first leaves Hough with 20-50 px arm pieces, none of which clears the
        # structural-length gate below.  The ROI only restricts which vertices
        # are reported.
        detected = detect_lines(image_path, None, visualize=False)
        raw = [[*s["a_px"], *s["b_px"]] for s in detected["results"]["segments"]]
    lines = raw

    # Keep only long structural edges for vertex candidates.
    structural = [seg for seg in lines if math.hypot(seg[2] - seg[0], seg[3] - seg[1]) >= 3.0 * cap_h]
    if supplied_lines and len(structural) < 2:
        # Caller-supplied lines were too short (or every one was clipped) to
        # form an arm pair; fall back to the full-image detection rather than
        # reporting "no mark".
        from .line_detection import detect_lines

        detected = detect_lines(image_path, None, visualize=False)
        extra = [[*s["a_px"], *s["b_px"]] for s in detected["results"]["segments"]]
        lines = lines + extra
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
    clustered = cluster_points(vertices, eps=max(4.0, 1.6 * stroke_w)) if vertices else []
    if roi is not None and len(clustered):
        margin = max(4.0, 0.6 * cap_h)
        clustered = np.array(
            [
                vertex
                for vertex in clustered
                if roi_box.x0 - margin <= vertex[0] <= roi_box.x1 + margin
                and roi_box.y0 - margin <= vertex[1] <= roi_box.y1 + margin
            ]
        )

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

    if not markers:
        # Dashed arms never form a long structural line; fall back to pairing
        # the short square-mark strokes themselves.
        markers = _detect_square_fallback(
            skel, roi_box, structural, dil, dil_independent, stroke_w, cap_h
        )
        for marker in markers:
            vertex = marker["vertex_px"]
            marker["vertex_norm"] = normalize_point(vertex[0], vertex[1], width, height)

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
    if roi is not None:
        notes.append("ROI restricts reported candidate vertices; line evidence is detected on the full image")
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
