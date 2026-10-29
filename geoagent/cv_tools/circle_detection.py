"""Circle and arc detection.

Combines HoughCircles with a skeleton RANSAC circle fit (Kasa least squares on
inliers) and an angular visibility analysis for partial arcs.  The visible arc
range is reported in the image pixel frame (x right, y down); TikZ authors must
flip the y axis when mapping to mathematical coordinates.
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from ..config import PROJECT_ROOT
from .common import (
    angular_span,
    draw_circle,
    draw_label,
    envelope,
    estimate_stroke_width,
    fit_circle_kasa,
    load_ink,
    new_overlay,
    normalize_point,
    parse_roi,
    roi_info,
    save_png,
    thin,
)


def _angle_bin_coverage(
    mask: np.ndarray,
    center: Any,
    radius: float,
    stroke_w: float,
    bins: int = 360,
    min_hits: int = 1,
) -> tuple[np.ndarray, float]:
    """Per-angle visibility for a circle, plus the visible-angle fraction.

    ``min_hits`` is kept configurable; the default of one hit is appropriate
    for the thin (2-3 px) strokes in these figures.  False positives are
    filtered later by contiguous-range and RANSAC-agreement checks.
    """
    h, w = mask.shape
    cx, cy = center
    tol = max(2.0, 1.5 * stroke_w)
    visible = np.zeros(bins, bool)
    radii = np.linspace(radius - tol, radius + tol, 7)
    for i in range(bins):
        theta = 2 * math.pi * i / bins
        hits = 0
        for rr in radii:
            x = int(round(cx + rr * math.cos(theta)))
            y = int(round(cy + rr * math.sin(theta)))
            if 0 <= x < w and 0 <= y < h and mask[y, x]:
                hits += 1
        visible[i] = hits >= min_hits
    return visible, float(visible.mean())


def _merge_ranges(ranges: list[list[float]], max_gap: float = 12.0) -> list[list[float]]:
    """Merge ranges separated by a small (circular) gap.

    A diameter crossing the circle deposits a few ink pixels exactly at the
    arc endpoints; without merging these appear as bogus 3-5 degree "visible
    arcs" that confuse the geometry agent.
    """
    if not ranges:
        return []
    ordered = sorted([list(map(float, r)) for r in ranges])
    merged: list[list[float]] = []
    for lo, hi in ordered:
        if merged and lo - merged[-1][1] <= max_gap:
            merged[-1][1] = max(merged[-1][1], hi)
        else:
            merged.append([lo, hi])
    if len(merged) > 1 and (merged[0][0] + 360.0 - merged[-1][1]) <= max_gap:
        merged[-1][1] = merged[0][1] + 360.0
        merged.pop(0)
    out: list[list[float]] = []
    for lo, hi in merged:
        while lo >= 360.0:
            lo -= 360.0
            hi -= 360.0
        if hi <= 360.0:
            out.append([round(lo, 1), round(hi, 1)])
        else:
            out.append([round(lo, 1), 360.0])
            if hi - 360.0 > 0:
                out.append([0.0, round(hi - 360.0, 1)])
    return out


def _visible_ranges(visible: np.ndarray, min_deg: float = 4.0) -> tuple[bool, list[list[float]]]:
    bins = len(visible)
    # close one-bin holes caused by labels/antialiasing
    closed = visible.copy()
    for i in range(bins):
        if not visible[i] and visible[(i - 1) % bins] and visible[(i + 1) % bins]:
            closed[i] = True
    if closed.mean() >= 0.97:
        return True, [[0.0, 360.0]]
    ranges: list[list[float]] = []
    start = None
    for i in range(bins + 1):
        val = bool(closed[i % bins]) if i < bins else False
        if val and start is None:
            start = i
        elif not val and start is not None:
            length_deg = (i - start) * 360.0 / bins
            if length_deg >= min_deg:
                ranges.append([round(start * 360.0 / bins, 1), round(i * 360.0 / bins, 1)])
            start = None
    return False, _merge_ranges(ranges)


def _longest_range(ranges: list[list[float]]) -> float:
    return max((hi - lo for lo, hi in ranges), default=0.0)


def _ransac_circles(
    mask: np.ndarray,
    skel: np.ndarray,
    stroke_w: float,
    *,
    max_circles: int = 4,
    iterations: int = 500,
    seed: int = 12345,
) -> list[dict[str, Any]]:
    ys, xs = np.where(skel > 0)
    pts = np.column_stack([xs, ys]).astype(float)
    if len(pts) < 50:
        return []
    tol = max(2.0, 1.5 * stroke_w)
    rmax = 0.95 * max(mask.shape)
    rng = np.random.default_rng(seed)
    work = pts
    need = max(30, int(0.08 * len(pts)))
    found: list[dict[str, Any]] = []

    for _ in range(max_circles):
        n = len(work)
        if n < need:
            break
        best: tuple[int, np.ndarray, float, np.ndarray] | None = None
        for _ in range(iterations):
            idx = rng.choice(n, 3, replace=False)
            p1, p2, p3 = work[idx]
            ax, ay, bx, by, cx, cy = p1[0], p1[1], p2[0], p2[1], p3[0], p3[1]
            d = 2.0 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
            if abs(d) < 1e-9:
                continue
            a2, b2, c2 = ax * ax + ay * ay, bx * bx + by * by, cx * cx + cy * cy
            center = np.array(
                [
                    (a2 * (by - cy) + b2 * (cy - ay) + c2 * (ay - by)) / d,
                    (a2 * (cx - bx) + b2 * (ax - cx) + c2 * (bx - ax)) / d,
                ]
            )
            radius = float(np.linalg.norm(p1 - center))
            if not (10.0 <= radius <= rmax):
                continue
            inliers = np.abs(np.linalg.norm(work - center, axis=1) - radius) < tol
            count = int(inliers.sum())
            if best is None or count > best[0]:
                best = (count, center, radius, inliers)
        if best is None or best[0] < need:
            break
        inliers = best[3]
        fit = fit_circle_kasa(work[inliers])
        if fit is None:
            break
        center, radius = fit
        inliers = np.abs(np.linalg.norm(work - center, axis=1) - radius) < tol
        if int(inliers.sum()) < need:
            break
        angles = np.arctan2(work[inliers][:, 1] - center[1], work[inliers][:, 0] - center[0])
        full, lo, hi = angular_span(angles)
        span = 360.0 if full else math.degrees((hi - lo) % (2 * math.pi))
        if span < 80.0:
            break
        visible, coverage = _angle_bin_coverage(mask, center, radius, stroke_w)
        if coverage < 0.20:
            break
        found.append(
            {
                "center": center,
                "radius": radius,
                "full": full,
                "lo": lo,
                "hi": hi,
                "span_deg": span,
                "coverage": coverage,
                "inliers": int(inliers.sum()),
                "method": "skeleton RANSAC + Kasa refit",
            }
        )
        work = work[~inliers]
    return found


def _merge_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    for cand in sorted(candidates, key=lambda c: c["coverage"], reverse=True):
        duplicate = False
        for existing in merged:
            center_dist = float(np.linalg.norm(np.asarray(cand["center"]) - np.asarray(existing["center"])))
            if center_dist <= max(4.0, 0.06 * max(cand["radius"], existing["radius"])) and abs(
                cand["radius"] - existing["radius"]
            ) <= max(4.0, 0.08 * max(cand["radius"], existing["radius"])):
                duplicate = True
                if cand["coverage"] > existing["coverage"]:
                    existing.update(cand)
                break
        if not duplicate:
            merged.append(dict(cand))
    return merged


def detect_circles(
    image_path: str | Path,
    roi: Any = None,
    *,
    max_circles: int = 4,
    visualize: bool = True,
    out_dir: str | Path | None = None,
) -> dict[str, Any]:
    mask, grey = load_ink(image_path)
    height, width = mask.shape
    roi_box = parse_roi(roi, width, height)
    sub_mask = mask[roi_box.y0:roi_box.y1, roi_box.x0:roi_box.x1]
    skel = thin(sub_mask)
    stroke_w = estimate_stroke_width(sub_mask, skel)
    h, w = sub_mask.shape
    candidates: list[dict[str, Any]] = []

    # RANSAC is the primary detector: it recovers partial arcs and does not
    # hallucinate circles tangent to a large arc the way HoughCircles can.
    ransac_cands = _ransac_circles(sub_mask, skel, stroke_w, max_circles=max_circles)
    for cand in ransac_cands:
        visible, coverage = _angle_bin_coverage(sub_mask, cand["center"], cand["radius"], stroke_w)
        full, ranges = _visible_ranges(visible)
        cand = dict(cand)
        cand.update({"full": full, "ranges": ranges, "coverage": max(coverage, cand["coverage"])})
        candidates.append(cand)

    # HoughCircles supplements full/near-full circles; a partial Hough candidate
    # is only trusted when it agrees with a RANSAC circle.
    blurred = cv2.GaussianBlur(sub_mask * 255, (5, 5), 1.2)
    try:
        hough = cv2.HoughCircles(
            blurred,
            cv2.HOUGH_GRADIENT,
            dp=1.2,
            minDist=max(20, int(0.08 * min(h, w))),
            param1=100,
            param2=42,
            minRadius=max(8, int(0.02 * min(h, w))),
            maxRadius=int(0.95 * max(h, w)),
        )
    except Exception:
        hough = None
    if hough is not None:
        for row in hough[0][: max_circles * 3]:
            cx, cy, radius = float(row[0]), float(row[1]), float(row[2])
            visible, coverage = _angle_bin_coverage(sub_mask, (cx, cy), radius, stroke_w)
            if coverage < 0.20:
                continue
            full, ranges = _visible_ranges(visible)
            longest = _longest_range(ranges)
            agrees = any(
                float(np.linalg.norm(np.asarray(rc["center"]) - np.array([cx, cy])))
                <= max(5.0, 0.08 * max(radius, float(rc["radius"])))
                and abs(float(rc["radius"]) - radius) <= max(5.0, 0.08 * max(radius, float(rc["radius"])))
                for rc in ransac_cands
            )
            near_full = full or longest >= 300.0 or coverage >= 0.85
            if not (near_full or agrees):
                continue
            span = 360.0 if full else sum(r[1] - r[0] for r in ranges)
            candidates.append(
                {
                    "center": np.array([cx, cy]),
                    "radius": radius,
                    "full": full,
                    "ranges": ranges,
                    "span_deg": span,
                    "coverage": coverage,
                    "inliers": None,
                    "method": "HoughCircles (near-full or RANSAC-agreeing)",
                }
            )

    merged = _merge_candidates(candidates)[:max_circles]
    results = []
    for idx, cand in enumerate(merged, start=1):
        center = np.asarray(cand["center"], float)
        radius = float(cand["radius"])
        global_center = center + np.array([roi_box.x0, roi_box.y0])
        visible, coverage = _angle_bin_coverage(mask, global_center, radius, stroke_w)
        full = bool(cand.get("full", False))
        ranges = cand.get("ranges") or []
        if ranges:
            full, ranges = _visible_ranges(visible)
            full = bool(full)
        if not full and _longest_range(ranges) < 60.0:
            continue
        results.append(
            {
                "id": f"circle_{idx:02d}",
                "center_px": [round(float(global_center[0]), 2), round(float(global_center[1]), 2)],
                "radius_px": round(radius, 2),
                "center_norm": normalize_point(global_center[0], global_center[1], width, height),
                "radius_norm": round(radius / max(width, height), 4),
                "full_circle": full,
                "visible_ranges_deg": ranges if not full else [[0.0, 360.0]],
                "visible_span_deg": 360.0 if full else round(sum(r[1] - r[0] for r in ranges), 1),
                "ink_coverage": round(float(coverage), 3),
                "method": cand.get("method", "HoughCircles + visibility"),
                "angle_frame": "image pixel frame (x right, y down); flip y for TikZ",
            }
        )

    viz = None
    if visualize:
        overlay = new_overlay(image_path)
        for item in results:
            color = (200, 60, 120)
            if item["full_circle"]:
                draw_circle(overlay, item["center_px"], item["radius_px"], color, 2)
            else:
                for lo, hi in item["visible_ranges_deg"]:
                    draw_circle(overlay, item["center_px"], item["radius_px"], color, 2, lo, hi)
            draw_label(overlay, item["id"], item["center_px"], color)
        base = Path(out_dir) if out_dir else PROJECT_ROOT / "outputs" / "cv_preview" / Path(image_path).stem
        viz = save_png(base / "detect_circles.png", overlay)

    notes = []
    if not results:
        notes.append("no circle/arc candidate survived the ink-coverage check")
    notes.append("Hough and RANSAC candidates are merged by center/radius agreement")
    return envelope(
        "detect_circles",
        image_path,
        roi=roi_info(roi_box, width, height),
        method="HoughCircles + skeleton RANSAC + angular ink-visibility",
        params={"max_circles": max_circles, "stroke_width_px": round(stroke_w, 2)},
        results={"count": len(results), "circles": results},
        notes=notes,
        visualization=viz,
    )


def fit_arcs(
    image_path: str | Path,
    roi: Any = None,
    *,
    points: list[list[float]] | None = None,
    max_arcs: int = 3,
    visualize: bool = True,
    out_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Fit circular arcs either to supplied pixel points or to skeleton RANSAC."""
    mask, _ = load_ink(image_path)
    height, width = mask.shape
    roi_box = parse_roi(roi, width, height)
    sub_mask = mask[roi_box.y0:roi_box.y1, roi_box.x0:roi_box.x1]
    skel = thin(sub_mask)
    stroke_w = estimate_stroke_width(sub_mask, skel)
    arcs: list[dict[str, Any]] = []
    if points:
        arr = np.asarray(points, float)
        fit = fit_circle_kasa(arr)
        if fit is None:
            return envelope(
                "fit_arcs",
                image_path,
                roi=roi_info(roi_box, width, height),
                method="Kasa circle fit",
                params={"points": len(points)},
                results={"count": 0, "arcs": []},
                notes=["circle fit failed: degenerate point set"],
                ok=False,
            )
        center, radius = fit
        angles = np.arctan2(arr[:, 1] - center[1], arr[:, 0] - center[0])
        full, lo, hi = angular_span(angles)
        visible, coverage = _angle_bin_coverage(sub_mask, center, radius, stroke_w)
        full2, ranges = _visible_ranges(visible)
        arcs.append(
            {
                "center_px": [round(float(center[0] + roi_box.x0), 2), round(float(center[1] + roi_box.y0), 2)],
                "radius_px": round(float(radius), 2),
                "full_circle": bool(full or full2),
                "visible_ranges_deg": ranges if not (full or full2) else [[0.0, 360.0]],
                "ink_coverage": round(coverage, 3),
                "residual_rms_px": round(float(np.sqrt(np.mean((np.linalg.norm(arr - center, axis=1) - radius) ** 2))), 3),
                "method": "Kasa fit on supplied points",
            }
        )
    else:
        for cand in _ransac_circles(sub_mask, skel, stroke_w, max_circles=max_arcs):
            center = np.asarray(cand["center"], float) + np.array([roi_box.x0, roi_box.y0])
            visible, coverage = _angle_bin_coverage(mask, center, cand["radius"], stroke_w)
            full, ranges = _visible_ranges(visible)
            arcs.append(
                {
                    "center_px": [round(float(center[0]), 2), round(float(center[1]), 2)],
                    "radius_px": round(float(cand["radius"]), 2),
                    "full_circle": bool(full),
                    "visible_ranges_deg": ranges if not full else [[0.0, 360.0]],
                    "ink_coverage": round(float(coverage), 3),
                    "residual_rms_px": None,
                    "method": "skeleton RANSAC + Kasa refit",
                }
            )
    for idx, arc in enumerate(arcs, start=1):
        arc["id"] = f"arc_{idx:02d}"
        arc["angle_frame"] = "image pixel frame (x right, y down); flip y for TikZ"

    viz = None
    if visualize and arcs:
        overlay = new_overlay(image_path)
        for arc in arcs:
            for lo, hi in arc["visible_ranges_deg"]:
                draw_circle(overlay, arc["center_px"], arc["radius_px"], (200, 60, 120), 2, lo, hi)
            draw_label(overlay, arc["id"], arc["center_px"], (200, 60, 120))
        base = Path(out_dir) if out_dir else PROJECT_ROOT / "outputs" / "cv_preview" / Path(image_path).stem
        viz = save_png(base / "fit_arcs.png", overlay)

    return envelope(
        "fit_arcs",
        image_path,
        roi=roi_info(roi_box, width, height),
        method="RANSAC/Kasa circle fitting with angular visibility",
        params={"max_arcs": max_arcs, "supplied_points": len(points or [])},
        results={"count": len(arcs), "arcs": arcs},
        notes=["arcs are represented by center, radius and visible angular ranges"],
        visualization=viz,
    )


def extract_visible_arc(
    image_path: str | Path,
    cx: float,
    cy: float,
    radius: float,
    *,
    tolerance_px: float | None = None,
    bins: int = 360,
    sample_step_deg: float = 5.0,
    visualize: bool = True,
    out_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Return ordered visible arc samples for a circle hypothesis."""
    mask, _ = load_ink(image_path)
    height, width = mask.shape
    stroke_w = estimate_stroke_width(mask, thin(mask))
    tol = float(tolerance_px if tolerance_px is not None else max(2.0, 1.5 * stroke_w))
    visible, coverage = _angle_bin_coverage(mask, (cx, cy), radius, stroke_w, bins=bins)
    full, ranges = _visible_ranges(visible)
    samples: list[dict[str, float]] = []
    if full:
        step = sample_step_deg
        theta = 0.0
        while theta < 360.0:
            rad = math.radians(theta)
            samples.append(
                {
                    "angle_deg": round(theta, 1),
                    "x_px": round(cx + radius * math.cos(rad), 2),
                    "y_px": round(cy + radius * math.sin(rad), 2),
                }
            )
            theta += step
    else:
        for lo, hi in ranges:
            theta = lo
            while theta <= hi:
                rad = math.radians(theta)
                samples.append(
                    {
                        "angle_deg": round(theta % 360.0, 1),
                        "x_px": round(cx + radius * math.cos(rad), 2),
                        "y_px": round(cy + radius * math.sin(rad), 2),
                    }
                )
                theta += sample_step_deg
    viz = None
    if visualize:
        overlay = new_overlay(image_path)
        if full:
            draw_circle(overlay, (cx, cy), radius, (200, 60, 120), 2)
        else:
            for lo, hi in ranges:
                draw_circle(overlay, (cx, cy), radius, (200, 60, 120), 2, lo, hi)
        for sample in samples[:: max(1, len(samples) // 18)]:
            cv2.circle(overlay, (int(round(sample["x_px"])), int(round(sample["y_px"]))), 2, (20, 120, 220), -1)
        base = Path(out_dir) if out_dir else PROJECT_ROOT / "outputs" / "cv_preview" / Path(image_path).stem
        viz = save_png(base / "extract_visible_arc.png", overlay)
    return envelope(
        "extract_visible_arc",
        image_path,
        roi=roi_info(parse_roi(None, width, height), width, height),
        method="angular ink sampling in an annulus",
        params={"cx": cx, "cy": cy, "radius": radius, "tolerance_px": tol, "bins": bins},
        results={
            "full_circle": full,
            "visible_ranges_deg": ranges if not full else [[0.0, 360.0]],
            "ink_coverage": round(coverage, 3),
            "samples": samples,
            "angle_frame": "image pixel frame (x right, y down); flip y for TikZ",
        },
        notes=["samples are ordered along each visible range", "coverage is a pixel-ink fraction, not a probability"],
        visualization=viz,
    )
