"""Straight-line detection, collinear merging and solid/dashed analysis.

Algorithms: skeletonisation + probabilistic Hough transform (LSD fallback),
union-find collinear merging with ink-verified gap bridging, and a centreline
gap-run analysis that refuses to call a single text-contact interruption
"dashed".
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Callable

import numpy as np

from ..config import PROJECT_ROOT
from .common import (
    angle_of,
    arc_evidence_reliable,
    draw_label,
    draw_segment,
    envelope,
    estimate_stroke_width,
    hough_segments,
    lsd_segments,
    load_ink,
    merge_collinear_segments,
    new_overlay,
    normalize_point,
    parse_roi,
    roi_info,
    save_png,
    thin,
)


def _style_metrics(mask: np.ndarray, a: Any, b: Any, stroke_w: float) -> dict[str, Any]:
    a = np.asarray(a, float)
    b = np.asarray(b, float)
    length = float(np.linalg.norm(b - a))
    h, w = mask.shape
    if length < 3:
        return {"supported": False, "reason": "segment too short"}
    unit = (b - a) / length
    perp = np.array([-unit[1], unit[0]])
    tol = max(1.5, 0.7 * stroke_w)
    radius = int(np.ceil(tol))
    offsets = np.arange(-radius, radius + 1, 1.0)  # integer offsets; always contains 0
    n = max(10, int(length))
    ts = np.linspace(0.04, 0.96, n)
    ink = np.zeros(n, bool)
    for i, t in enumerate(ts):
        p = a + t * (b - a)
        for off in offsets:
            q = p + perp * off
            x, y = int(round(q[0])), int(round(q[1]))
            if 0 <= x < w and 0 <= y < h and mask[y, x]:
                ink[i] = True
                break

    support = float(ink.mean())
    runs: list[tuple[bool, int]] = []
    if len(ink):
        start = 0
        for i in range(1, len(ink)):
            if ink[i] != ink[start]:
                runs.append((bool(ink[start]), i - start))
                start = i
        runs.append((bool(ink[start]), len(ink) - start))
    step_px = float(np.mean(np.diff(ts)) * length) if len(ts) > 1 else 1.0
    dash_lengths = [r * step_px for is_ink, r in runs if is_ink]
    gaps = [r * step_px for is_ink, r in runs if not is_ink]
    # ignore leading/trailing blank margins produced by the 4%/.96% trim
    gaps = [g for g in gaps if g >= 1.5]
    gap_count = len(gaps)
    coverage = float(sum(dash_lengths) / max(1.0, sum(dash_lengths) + sum(gaps)))
    return {
        "supported": support >= 0.55,
        "ink_support": round(support, 3),
        "gap_count": gap_count,
        "gap_lengths_px": [round(g, 1) for g in gaps[:12]],
        "dash_lengths_px": [round(d, 1) for d in dash_lengths[:16]],
        "ink_coverage": round(coverage, 3),
        "sampled_length_px": round(length, 1),
    }


def classify_style(metrics: dict[str, Any], stroke_w: float) -> tuple[str, list[str]]:
    """Conservative solid/dashed/uncertain decision, with explicit reasons."""
    notes: list[str] = []
    if not metrics.get("supported", False):
        return "uncertain", ["centreline is not well supported by ink"]
    gaps = metrics.get("gap_count", 0)
    gap_lengths = metrics.get("gap_lengths_px") or []
    dash_lengths = metrics.get("dash_lengths_px") or []
    if gaps == 0:
        return "solid", notes
    if gaps <= 2:
        longest = max(gap_lengths) if gap_lengths else 0.0
        if longest <= max(9.0, 5.0 * stroke_w) and metrics.get("ink_coverage", 0) >= 0.72:
            notes.append(
                f"{gaps} localized interruption(s) treated as solid; likely text/label contact "
                "rather than a dashed pattern"
            )
            return "solid", notes
        notes.append(f"{gaps} interruption(s) too long for a clean solid line")
        return "uncertain", notes
    if len(dash_lengths) < 4:
        notes.append("too few ink runs for a dashed pattern")
        return "uncertain", notes
    median_dash = float(np.median(dash_lengths))
    if median_dash < 2.0:
        notes.append("dash fragments are sub-pixel/noise-like")
        return "uncertain", notes
    gaps_arr = np.asarray(gap_lengths, float)
    if len(gaps_arr) >= 3:
        regular = float(np.std(gaps_arr) / max(np.mean(gaps_arr), 1e-6))
    else:
        regular = 1.0
    if metrics.get("ink_coverage", 0) >= 0.45 and (regular < 0.85 or gaps >= 4):
        notes.append(f"{gaps} repeated gaps with stable dashes -> dashed")
        return "dashed", notes
    notes.append("repeated gaps but irregular geometry -> uncertain")
    return "uncertain", notes


def _suppress_compact_components(mask: np.ndarray, stroke_w: float) -> np.ndarray:
    """Remove glyph-like compact blobs before skeletonisation/Hough.

    Elongated thin components (dashes, line fragments) are kept; compact blobs
    with low PCA elongation (letters, digits, point dots) are erased.  This
    stops Hough from inventing short "lines" from the strokes of a label.
    """
    import cv2 as _cv2

    work = (mask > 0).astype(np.uint8).copy()
    n, labels, stats, _ = _cv2.connectedComponentsWithStats(work, 8)
    h, w = work.shape
    limit = 0.16 * min(h, w)
    for i in range(1, n):
        x, y, cw, ch, area = (int(v) for v in stats[i])
        if area < 4:
            work[labels == i] = 0
            continue
        ys, xs = np.where(labels == i)
        pts = np.column_stack([xs, ys]).astype(float)
        mu = pts.mean(0)
        _u, singular, _vt = np.linalg.svd(pts - mu, full_matrices=False)
        elongation = float(singular[0] / max(singular[1], 1e-6))
        if max(cw, ch) <= limit and elongation < 5.0:
            work[labels == i] = 0
    return work


def _diagnose_style(image_path: str | Path, a: Any, b: Any) -> dict[str, Any]:
    mask, _grey = load_ink(image_path)
    skel = thin(mask)
    stroke_w = estimate_stroke_width(mask, skel)
    metrics = _style_metrics(mask, a, b, stroke_w)
    style, notes = classify_style(metrics, stroke_w)
    return {"style": style, "metrics": metrics, "notes": notes, "stroke_width_px": round(stroke_w, 2)}


def _remove_circle_ink(
    skel: np.ndarray,
    circles: list[dict[str, Any]],
    stroke_w: float,
    offset: np.ndarray,
) -> np.ndarray:
    """Erase circle/arc skeleton points so Hough does not shred arcs into chords."""
    # Only trustworthy arcs may delete ink: a spurious circle fitted to a
    # tangent chord would otherwise erase that whole straight edge (a real
    # failure mode on figures with a chord tangent to the arc).
    circles = [circ for circ in circles or [] if arc_evidence_reliable(circ)]
    if not circles:
        return skel
    ys, xs = np.where(skel > 0)
    if not len(xs):
        return skel
    pts = np.column_stack([xs, ys]).astype(float) + offset
    keep = np.ones(len(pts), bool)
    tol = max(2.0, 1.5 * stroke_w)
    for circ in circles:
        center = np.asarray(circ["center_px"], float)
        radius = float(circ["radius_px"])
        dist = np.abs(np.linalg.norm(pts - center, axis=1) - radius)
        keep &= dist >= tol
    out = np.zeros_like(skel)
    kept = pts[keep].astype(int) - offset.astype(int)
    if len(kept):
        out[kept[:, 1], kept[:, 0]] = 255
    return out


def _recover_dash_chains(
    mask: np.ndarray,
    stroke_w: float,
    offset: np.ndarray,
) -> list[dict[str, Any]]:
    """Chain collinear thin dash components into dashed line spans (pixel coords)."""
    import cv2 as _cv2

    h, w = mask.shape
    n, labels, stats, _ = _cv2.connectedComponentsWithStats((mask > 0).astype(np.uint8), 8)
    pieces: list[tuple[np.ndarray, np.ndarray, float]] = []
    for i in range(1, n):
        x, y, cw, ch, area = (int(v) for v in stats[i])
        if area < 4 or max(cw, ch) > 45:
            continue
        ys, xs = np.where(labels == i)
        pts = np.column_stack([xs, ys]).astype(float)
        mu = pts.mean(0)
        _u, singular, vt = np.linalg.svd(pts - mu, full_matrices=False)
        major = float(np.linalg.norm(pts - mu, axis=1).max() * 2.0)
        minor = float(2.0 * singular[-1] / max(1.0, math.sqrt(len(pts))))
        if major < 5.0 or major < 4.0 * max(minor, 0.7) or minor > 2.5 * stroke_w + 1.0:
            continue
        direction = vt[0]
        t = (pts - mu) @ direction
        p0, p1 = mu + t.min() * direction, mu + t.max() * direction
        pieces.append((p0, p1, angle_of(p0, p1)))
    if len(pieces) < 3:
        return []
    m = len(pieces)
    parent = list(range(m))

    def find(a: int) -> int:
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    cap_h = max(16.0, 5.5 * stroke_w)
    gap_limit = max(7.0, 1.15 * cap_h)
    for i in range(m):
        for j in range(i + 1, m):
            da = abs(pieces[i][2] - pieces[j][2])
            if math.degrees(min(da, math.pi - da)) > 12.0:
                continue
            dist = min(
                float(np.linalg.norm(pa - pb))
                for pa in (pieces[i][0], pieces[i][1])
                for pb in (pieces[j][0], pieces[j][1])
            )
            if dist <= gap_limit:
                parent[find(i)] = find(j)
    groups: dict[int, list[int]] = {}
    for i in range(m):
        groups.setdefault(find(i), []).append(i)
    chains = []
    for idx in groups.values():
        if len(idx) < 3:
            continue
        pts = np.array([pieces[i][k] for i in idx for k in (0, 1)], float)
        mu = pts.mean(0)
        _u, singular, vt = np.linalg.svd(pts - mu, full_matrices=False)
        direction = vt[0]
        t = (pts - mu) @ direction
        p0, p1 = mu + t.min() * direction, mu + t.max() * direction
        length = float(np.linalg.norm(p1 - p0))
        if length < max(20.0, 0.05 * min(h, w)):
            continue
        unit = (p1 - p0) / max(length, 1e-9)
        p0, p1 = p0 - unit * gap_limit, p1 + unit * gap_limit
        chains.append(
            {
                "a": p0 + offset,
                "b": p1 + offset,
                "pieces": len(idx),
                "chain_length_px": round(length, 2),
            }
        )
    return chains


def _extend_endpoint(
    mask: np.ndarray,
    p: np.ndarray,
    unit: np.ndarray,
    stroke_w: float,
    max_extension: float,
    gap_tol: float,
    gate: Callable[[np.ndarray], bool] | None = None,
) -> np.ndarray:
    """Walk outward from ``p`` along ``unit`` while the stroke's ink continues.

    Hough clips a span where circle suppression erased its ink (a chord that
    grazes or tangents its arc is erased along the annulus), so the remaining
    ink has to recover the true end.  ``gate`` confines the walk to the region
    where suppression happened; short gaps (dash spacing) are bridged.
    """
    h, w = mask.shape
    radius = max(1, int(round(0.9 * stroke_w + 1.0)))
    last_hit = 0.0
    distance = 0.0
    while distance < max_extension:
        distance += 1.0
        q = p + unit * distance
        x, y = int(round(q[0])), int(round(q[1]))
        if not (0 <= x < w and 0 <= y < h):
            break
        if gate is not None and not gate(q):
            break
        window = mask[max(0, y - radius): y + radius + 1, max(0, x - radius): x + radius + 1]
        if window.any():
            last_hit = distance
        elif distance - last_hit > gap_tol:
            break
    return p + unit * last_hit if last_hit > 0 else p


def _extend_span(
    mask: np.ndarray,
    a: np.ndarray,
    b: np.ndarray,
    stroke_w: float,
    *,
    max_extension: float,
    gap_tol: float,
    gate: Callable[[np.ndarray], bool] | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    length = float(np.linalg.norm(b - a))
    if length < 1e-6:
        return a, b
    unit = (b - a) / length
    a2 = _extend_endpoint(mask, a, -unit, stroke_w, max_extension, gap_tol, gate)
    b2 = _extend_endpoint(mask, b, unit, stroke_w, max_extension, gap_tol, gate)
    return a2, b2


def _circle_band_gate(
    circles: list[dict[str, Any]],
    stroke_w: float,
    offset: np.ndarray | None = None,
) -> Callable[[np.ndarray], bool] | None:
    """Only allow extension where circle suppression could have erased ink.

    ``offset`` converts full-image circle centres into the ROI-local frame
    the extension walk runs in.
    """
    reliable = [circ for circ in circles or [] if arc_evidence_reliable(circ)]
    if not reliable:
        return None
    delta = np.zeros(2, float) if offset is None else np.asarray(offset, float)
    band = max(2.0, 1.5 * stroke_w) * 2.5
    centers = [
        (np.asarray(circ["center_px"], float) - delta, float(circ["radius_px"]))
        for circ in reliable
    ]

    def gate(point: np.ndarray) -> bool:
        return any(abs(float(np.linalg.norm(point - center)) - radius) <= band for center, radius in centers)

    return gate


def _overlaps_solid(chain_a: np.ndarray, chain_b: np.ndarray, solids: list[tuple[np.ndarray, np.ndarray]]) -> bool:
    from .common import point_line_distance

    ca = (chain_a + chain_b) / 2.0
    for a, b in solids:
        if point_line_distance(ca, a, b) > 5.0:
            continue
        ang1 = angle_of(chain_a, chain_b)
        ang2 = angle_of(a, b)
        diff = abs(ang1 - ang2)
        if math.degrees(min(diff, math.pi - diff)) > 5.0:
            continue
        # project onto the solid and test overlap of the chain span
        d = b - a
        L2 = float(d @ d)
        if L2 < 1e-9:
            continue
        ts = [float(np.clip((p - a) @ d / L2, 0.0, 1.0)) for p in (chain_a, chain_b)]
        if max(ts) - min(ts) > 0.25:
            return True
    return False


def detect_lines(
    image_path: str | Path,
    roi: Any = None,
    *,
    min_length_frac: float = 0.02,
    max_gap_frac: float = 0.015,
    merge: bool = True,
    max_lines: int = 80,
    visualize: bool = True,
    out_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Detect straight segments; returns merged infinite-line spans by default."""
    mask, grey = load_ink(image_path)
    height, width = mask.shape
    roi_box = parse_roi(roi, width, height)
    sub_mask = mask[roi_box.y0:roi_box.y1, roi_box.x0:roi_box.x1]
    sub_grey = grey[roi_box.y0:roi_box.y1, roi_box.x0:roi_box.x1]
    raw_skel = thin(sub_mask)
    stroke_w = estimate_stroke_width(sub_mask, raw_skel)
    work_mask = _suppress_compact_components(sub_mask, stroke_w)
    skel = thin(work_mask)

    circles: list[dict[str, Any]] = []
    try:
        from .circle_detection import detect_circles

        circles = detect_circles(image_path, roi, visualize=False)["results"]["circles"]
    except Exception:
        circles = []
    skel = _remove_circle_ink(skel, circles, stroke_w, np.array([roi_box.x0, roi_box.y0], float))

    min_length = max(12, int(min_length_frac * min(sub_mask.shape)))
    raw = hough_segments(
        skel,
        min_length_frac=min_length_frac,
        max_gap_frac=max_gap_frac,
    )
    method = "skeleton + probabilistic Hough after glyph/circle suppression"
    if len(raw) < 3:
        lsd = lsd_segments(sub_grey, min_length=min_length)
        if lsd:
            raw = raw + lsd
            method += " (LSD supplement)"

    if merge:
        merged = merge_collinear_segments(raw, sub_mask)
        spans = [
            (
                np.array(m["a"]) + [roi_box.x0, roi_box.y0],
                np.array(m["b"]) + [roi_box.x0, roi_box.y0],
                len(m["parts"]),
            )
            for m in merged
        ]
    else:
        spans = [
            (
                np.array([s[0], s[1]]) + [roi_box.x0, roi_box.y0],
                np.array([s[2], s[3]]) + [roi_box.x0, roi_box.y0],
                1,
            )
            for s in raw
        ]

    # Recover the true stroke extent: Hough spans stop where circle
    # suppression erased ink, but the remaining ink still supports the full
    # length (and overhangs past labelled vertices are part of the figure).
    # Spans are in full-image coordinates while the ink masks are ROI-local,
    # so walk in the local frame against the glyph-suppressed mask; the gate
    # limits growth to the annulus where suppression happened, which keeps
    # the walk from crawling into label glyphs.
    offset = np.array([roi_box.x0, roi_box.y0], float)
    ink_mask = (work_mask > 0).astype(np.uint8)
    band_gate = _circle_band_gate(circles, stroke_w, offset)
    max_extension = max(20.0, 0.12 * min(sub_mask.shape))
    gap_tol = max(3.0, min(10.0, 4.0 * stroke_w + 1.0))
    extended = []
    for a, b, parts in spans:
        a_l = np.asarray(a, float) - offset
        b_l = np.asarray(b, float) - offset
        a_l, b_l = _extend_span(
            ink_mask,
            a_l,
            b_l,
            stroke_w,
            max_extension=max_extension,
            gap_tol=gap_tol,
            gate=band_gate,
        )
        extended.append((a_l + offset, b_l + offset, parts))
    spans = extended

    segments: list[dict[str, Any]] = []
    for a, b, parts in spans:
        length = float(np.linalg.norm(b - a))
        if length < min_length:
            continue
        diagnostic = _diagnose_style(image_path, a, b)
        segments.append(
            {
                "a_px": [round(float(a[0]), 2), round(float(a[1]), 2)],
                "b_px": [round(float(b[0]), 2), round(float(b[1]), 2)],
                "a_norm": normalize_point(a[0], a[1], width, height),
                "b_norm": normalize_point(b[0], b[1], width, height),
                "length_px": round(length, 2),
                "angle_deg": round(math.degrees(angle_of(a, b)), 2),
                "style": diagnostic["style"],
                "style_metrics": diagnostic["metrics"],
                "style_notes": diagnostic["notes"],
                "hough_parts": parts,
                "detection_kind": "solid_span",
            }
        )

    # Recover dashed spans that Hough cannot connect (isolated dashes).
    dash_chains = _recover_dash_chains(sub_mask, stroke_w, np.array([roi_box.x0, roi_box.y0], float))
    solid_arrays = [(np.asarray(a, float), np.asarray(b, float)) for a, b, _ in spans]
    for chain in dash_chains:
        ca, cb = np.asarray(chain["a"], float), np.asarray(chain["b"], float)
        # Dash spacing is wider than the solid-line gap tolerance used above;
        # walking the glyph-suppressed mask keeps the chain from bridging
        # across a nearby label and overshooting its true extent.
        ca_l, cb_l = ca - offset, cb - offset
        ca_l, cb_l = _extend_span(
            ink_mask,
            ca_l,
            cb_l,
            stroke_w,
            max_extension=max_extension,
            gap_tol=max(gap_tol, 9.0),
        )
        ca, cb = ca_l + offset, cb_l + offset
        length = float(np.linalg.norm(cb - ca))
        if length < min_length or _overlaps_solid(ca, cb, solid_arrays):
            continue
        segments.append(
            {
                "a_px": [round(float(ca[0]), 2), round(float(ca[1]), 2)],
                "b_px": [round(float(cb[0]), 2), round(float(cb[1]), 2)],
                "a_norm": normalize_point(ca[0], ca[1], width, height),
                "b_norm": normalize_point(cb[0], cb[1], width, height),
                "length_px": round(length, 2),
                "angle_deg": round(math.degrees(angle_of(ca, cb)), 2),
                "style": "dashed",
                "style_metrics": {
                    "dash_pieces": chain["pieces"],
                    "chain_length_px": chain["chain_length_px"],
                },
                "style_notes": [
                    f"collinear chain of {chain['pieces']} thin ink dashes with consistent direction"
                ],
                "hough_parts": 0,
                "detection_kind": "dash_chain",
            }
        )
    segments.sort(key=lambda s: s["length_px"], reverse=True)
    kept = segments[:max_lines]
    for idx, item in enumerate(kept, start=1):
        item["id"] = f"line_{idx:02d}"

    viz = None
    if visualize:
        overlay = new_overlay(image_path)
        for item in kept:
            color = (30, 160, 60)
            if item["style"] == "dashed":
                color = (30, 90, 220)
            elif item["style"] == "uncertain":
                color = (230, 140, 20)
            draw_segment(overlay, item["a_px"], item["b_px"], color, 2)
            draw_label(overlay, item["id"], item["a_px"], color)
        base = Path(out_dir) if out_dir else PROJECT_ROOT / "outputs" / "cv_preview" / Path(image_path).stem
        viz = save_png(base / "detect_lines.png", overlay)

    notes = []
    if not kept:
        notes.append("no straight line reached the minimum length; the figure may be purely curved")
    if any(s["style_notes"] for s in kept):
        notes.append("per-line style diagnostics are heuristic; see style_notes")

    return envelope(
        "detect_lines",
        image_path,
        roi=roi_info(roi_box, width, height),
        method=method,
        params={
            "min_length_frac": min_length_frac,
            "max_gap_frac": max_gap_frac,
            "merge_collinear": merge,
            "stroke_width_px": round(stroke_w, 2),
        },
        results={"count": len(kept), "segments": kept},
        notes=notes,
        visualization=viz,
    )


def merge_collinear_segments_tool(
    image_path: str | Path,
    segments: list[dict[str, Any]] | None = None,
    roi: Any = None,
    *,
    angle_tol_deg: float = 3.0,
    dist_tol_px: float = 4.5,
    visualize: bool = True,
    out_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Merge a supplied segment list (or run detection first)."""
    if not segments:
        detected = detect_lines(image_path, roi, merge=False, visualize=False)
        segments = detected["results"]["segments"]
    raw: list[list[float]] = []
    for seg in segments:
        if "a_px" in seg and "b_px" in seg:
            raw.append([*seg["a_px"], *seg["b_px"]])
        elif "a" in seg and "b" in seg:
            raw.append([*seg["a"], *seg["b"]])
    mask, _ = load_ink(image_path)
    merged = merge_collinear_segments(raw, mask, angle_tol_deg=angle_tol_deg, dist_tol_px=dist_tol_px)
    height, width = mask.shape
    groups = []
    for idx, item in enumerate(merged, start=1):
        a = np.asarray(item["a"], float)
        b = np.asarray(item["b"], float)
        groups.append(
            {
                "id": f"merged_{idx:02d}",
                "a_px": [round(float(a[0]), 2), round(float(a[1]), 2)],
                "b_px": [round(float(b[0]), 2), round(float(b[1]), 2)],
                "a_norm": normalize_point(a[0], a[1], width, height),
                "b_norm": normalize_point(b[0], b[1], width, height),
                "length_px": round(float(np.linalg.norm(b - a)), 2),
                "angle_deg": item["angle_deg"],
                "merged_parts": len(item["parts"]),
            }
        )
    viz = None
    if visualize:
        overlay = new_overlay(image_path)
        for group in groups:
            draw_segment(overlay, group["a_px"], group["b_px"], (30, 160, 60), 2)
            draw_label(overlay, group["id"], group["a_px"], (30, 160, 60))
        base = Path(out_dir) if out_dir else PROJECT_ROOT / "outputs" / "cv_preview" / Path(image_path).stem
        viz = save_png(base / "merge_collinear_segments.png", overlay)
    return envelope(
        "merge_collinear_segments",
        image_path,
        roi=roi_info(parse_roi(roi, width, height), width, height),
        method="union-find on (angle, line offset, ink-verified gap bridge)",
        params={"angle_tol_deg": angle_tol_deg, "dist_tol_px": dist_tol_px, "input_count": len(segments)},
        results={"count": len(groups), "merged": groups},
        notes=["merge operates in pixel coordinates of the full image"],
        visualization=viz,
    )


def analyze_line_style(
    image_path: str | Path,
    *,
    a: Any = None,
    b: Any = None,
    segments: list[dict[str, Any]] | None = None,
    visualize: bool = True,
    out_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Classify one or many segments as solid / dashed / uncertain."""
    mask, _ = load_ink(image_path)
    height, width = mask.shape
    targets: list[dict[str, Any]] = []
    if a is not None and b is not None:
        targets.append({"id": "style_01", "a_px": list(a), "b_px": list(b)})
    elif segments:
        for idx, seg in enumerate(segments, start=1):
            pa = seg.get("a_px") or seg.get("a")
            pb = seg.get("b_px") or seg.get("b")
            if pa is not None and pb is not None:
                targets.append({"id": seg.get("id", f"style_{idx:02d}"), "a_px": list(pa), "b_px": list(pb)})
    else:
        detected = detect_lines(image_path, visualize=False)
        targets = [{"id": s["id"], "a_px": s["a_px"], "b_px": s["b_px"]} for s in detected["results"]["segments"]]

    results = []
    for target in targets:
        diagnostic = _diagnose_style(image_path, target["a_px"], target["b_px"])
        results.append(
            {
                "id": target["id"],
                "a_px": target["a_px"],
                "b_px": target["b_px"],
                "style": diagnostic["style"],
                "metrics": diagnostic["metrics"],
                "notes": diagnostic["notes"],
                "heuristic_confidence_kind": "rules over gap-run statistics; not a probability",
            }
        )
    viz = None
    if visualize and results:
        overlay = new_overlay(image_path)
        for item in results:
            color = {"solid": (30, 160, 60), "dashed": (30, 90, 220)}.get(item["style"], (230, 140, 20))
            draw_segment(overlay, item["a_px"], item["b_px"], color, 2)
            draw_label(overlay, f"{item['id']}:{item['style']}", item["a_px"], color)
        base = Path(out_dir) if out_dir else PROJECT_ROOT / "outputs" / "cv_preview" / Path(image_path).stem
        viz = save_png(base / "analyze_line_style.png", overlay)
    return envelope(
        "analyze_line_style",
        image_path,
        roi=roi_info(parse_roi(None, width, height), width, height),
        method="centreline sampling with perpendicular tolerance; gap-run classification",
        params={"segments": len(results)},
        results={"count": len(results), "styles": results},
        notes=[
            "a single short interruption is treated as solid (text/label contact), not dashed",
            "dashed requires >=3 repeated gaps and >=4 ink runs",
        ],
        visualization=viz,
    )
