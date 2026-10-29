"""Point-label candidates, template matching, and exclusive label binding.

Pipeline: remove long line structures from the ink mask, split compact glyph
blobs, normalise each glyph, compare against Computer-Modern-like templates by
normalised cross-correlation (NCC), then solve an exclusive assignment between
label centroids and geometric vertices with the Hungarian algorithm.
"""
from __future__ import annotations

import math
import os
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy.optimize import linear_sum_assignment

from ..config import PROJECT_ROOT
from .common import (
    angle_of,
    cluster_points,
    draw_box,
    draw_label,
    draw_segment,
    envelope,
    estimate_stroke_width,
    hough_segments,
    in_arc,
    line_circle_intersections,
    load_ink,
    new_overlay,
    normalize_box,
    normalize_point,
    parse_roi,
    roi_info,
    save_png,
    thin,
)

GLYPH_SIZE = 40
CHAR_SET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
FONT_CANDIDATES = [
    r"C:\Windows\Fonts\times.ttf",
    r"C:\Windows\Fonts\georgia.ttf",
    r"C:\Windows\Fonts\cambria.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
]


# --------------------------------------------------------------------------- #
# glyph utilities
# --------------------------------------------------------------------------- #
def _normalise_glyph(img: np.ndarray, size: int = GLYPH_SIZE) -> np.ndarray | None:
    ys, xs = np.where(img > 0)
    if not len(ys):
        return None
    crop = img[ys.min(): ys.max() + 1, xs.min(): xs.max() + 1].astype(np.float32)
    ch, cw = crop.shape
    scale = size / max(ch, cw, 1)
    nh, nw = max(1, int(round(ch * scale))), max(1, int(round(cw * scale)))
    small = cv2.resize(crop, (nw, nh), interpolation=cv2.INTER_AREA)
    small /= small.max() or 1.0
    canvas = np.zeros((size, size), np.float32)
    y0, x0 = (size - nh) // 2, (size - nw) // 2
    canvas[y0: y0 + nh, x0: x0 + nw] = small
    canvas = cv2.GaussianBlur(canvas, (3, 3), 0.7)
    return (canvas - canvas.mean()) / (canvas.std() + 1e-6)


def _font(size: int, family: str = "cmr10"):
    paths: list[str] = []
    try:
        from matplotlib import font_manager as fm

        paths.append(fm.findfont(family, fallback_to_default=False))
    except Exception:
        pass
    if family == "cmmi10":
        try:
            from matplotlib import font_manager as fm

            paths.append(fm.findfont("cmr10", fallback_to_default=False))
        except Exception:
            pass
    paths.extend(FONT_CANDIDATES)
    for path in paths:
        if path and os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return None


_TEMPLATE_CACHE: dict[str, np.ndarray] = {}


def _templates() -> dict[str, np.ndarray]:
    """Letters use Computer Modern math italic (cmmi10), digits use cmr10.

    TikZ point labels live in math mode, so a serif upright template badly
    mismatches italic glyphs; using the real math font is the highest-value fix.
    """
    if _TEMPLATE_CACHE:
        return _TEMPLATE_CACHE
    italic = _font(64, "cmmi10")
    roman = _font(64, "cmr10")
    for ch in CHAR_SET:
        font = italic if ch.isalpha() else roman
        if font is None:
            continue
        image = Image.new("L", (100, 100), 0)
        ImageDraw.Draw(image).text((15, 8), ch, fill=255, font=font)
        template = _normalise_glyph(np.asarray(image))
        if template is not None:
            _TEMPLATE_CACHE[ch] = template
    return _TEMPLATE_CACHE


def _cap_height(mask: np.ndarray, stroke_w: float) -> float:
    n, lab, stats, _ = cv2.connectedComponentsWithStats((mask > 0).astype(np.uint8), 8)
    heights = []
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if area >= 10 and h >= 6 and h <= 3.0 * (max(stroke_w, 2.0)) ** 2 + 40:
            heights.append(h)
    if heights:
        return float(np.clip(np.median(heights), 10.0, 32.0))
    return 20.0


def _sampled_component(seg: tuple[float, float, float, float], labels: np.ndarray) -> set[int]:
    """Component ids touched by a Hough segment at several sample points."""
    x1, y1, x2, y2 = seg
    ids: set[int] = set()
    hh, ww = labels.shape
    for t in (0.15, 0.35, 0.5, 0.65, 0.85):
        x = int(round(x1 + t * (x2 - x1)))
        y = int(round(y1 + t * (y2 - y1)))
        if not (0 <= x < ww and 0 <= y < hh):
            continue
        window = labels[max(0, y - 1): y + 2, max(0, x - 1): x + 2]
        ids.update(int(v) for v in window[window > 0])
    return ids


def _glyph_groups(text: np.ndarray, cap_h: float) -> list[dict[str, Any]]:
    """Group fragments of one glyph that line suppression split apart.

    Components are formed on a lightly dilated copy (bridging the erased line
    band), but each group's pixels/bbox come from the *original* text mask.
    Groups that no longer fit a single glyph are discarded.
    """
    kernel = max(3, int(round(0.35 * cap_h)) | 1)
    dil = cv2.dilate(text, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kernel, kernel)))
    n, lab, stats, cents = cv2.connectedComponentsWithStats(dil, 8)
    groups: list[dict[str, Any]] = []
    for i in range(1, n):
        x, y, w, h, _area = (int(v) for v in stats[i])
        if w > 2.6 * cap_h or h > 1.9 * cap_h:
            continue
        sel = (lab == i) & (text > 0)
        if int(sel.sum()) < 8:
            continue
        ys, xs = np.where(sel)
        gb = [int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1]
        groups.append(
            {
                "mask": sel,
                "bbox": gb,
                "centroid": [float(xs.mean()), float(ys.mean())],
                "area": int(sel.sum()),
            }
        )
    return groups


def _line_suppressed_text(image_path: str | Path) -> tuple[np.ndarray, np.ndarray, float, float]:
    """Return (ink, text_mask, stroke_w, cap_h) in full-image coordinates."""
    mask, _grey = load_ink(image_path)
    skel = thin(mask)
    stroke_w = estimate_stroke_width(mask, skel)
    raw = hough_segments(skel, min_length_frac=0.035, max_gap_frac=0.01)
    # Hough also fires on the 15-25 px strokes of glyphs.  Erasing those with a
    # thick band destroys the very text we are trying to read, so a segment is
    # ignored when all of its supporting ink belongs to glyph-sized components.
    _, full_labels, full_stats, _ = cv2.connectedComponentsWithStats((mask > 0).astype(np.uint8), 8)
    glyph_limit = 14.0 * stroke_w
    line_mask = np.zeros_like(mask)
    thickness = max(3, int(math.ceil(2.2 * stroke_w + 2)))
    for seg in raw:
        ids = _sampled_component(seg, full_labels)
        if ids and all(
            max(full_stats[cid][2], full_stats[cid][3]) <= glyph_limit for cid in ids
        ):
            continue  # glyph stroke, not a figure line
        x1, y1, x2, y2 = seg
        cv2.line(line_mask, (int(x1), int(y1)), (int(x2), int(y2)), 1, thickness)
    text = ((mask > 0) & (line_mask == 0)).astype(np.uint8)
    text = cv2.morphologyEx(text, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)))
    cap_h = _cap_height(text, stroke_w)
    return mask, text, stroke_w, cap_h


# --------------------------------------------------------------------------- #
# 1. candidates
# --------------------------------------------------------------------------- #
def extract_label_candidates(
    image_path: str | Path,
    roi: Any = None,
    *,
    max_labels: int = 30,
    visualize: bool = True,
    out_dir: str | Path | None = None,
) -> dict[str, Any]:
    mask, text, stroke_w, cap_h = _line_suppressed_text(image_path)
    height, width = mask.shape
    roi_box = parse_roi(roi, width, height)

    base = Path(out_dir) if out_dir else PROJECT_ROOT / "outputs" / "cv_preview" / Path(image_path).stem
    glyph_dir = base / "glyphs"
    glyph_dir.mkdir(parents=True, exist_ok=True)

    candidates: list[dict[str, Any]] = []
    for group in _glyph_groups(text, cap_h):
        x, y, bx1, by1 = group["bbox"]
        w, h = bx1 - x, by1 - y
        cx, cy = group["centroid"]
        area = group["area"]
        if not (roi_box.x0 - 2 <= cx <= roi_box.x1 + 2 and roi_box.y0 - 2 <= cy <= roi_box.y1 + 2):
            continue
        if area < 8 or h < 5 or w < 2:
            continue
        if not (0.42 * cap_h <= h <= 1.9 * cap_h):
            continue
        if w > 2.6 * cap_h or max(h, w) < 0.45 * cap_h:
            continue
        if w / max(h, 1) > 3.0:
            continue
        ys_c, xs_c = np.where(group["mask"])
        pts_c = np.column_stack([xs_c, ys_c]).astype(float)
        _u, singular_c, _vt = np.linalg.svd(pts_c - pts_c.mean(0), full_matrices=False)
        elongation = float(singular_c[0] / max(singular_c[1], 1e-6))
        if elongation > 3.4:  # curved arc fragments are elongated, not glyphs
            continue
        component = group["mask"]
        # Recover the original ink inside the bbox for a cleaner glyph template.
        glyph = (mask[y: y + h, x: x + w] * component[y: y + h, x: x + w]).astype(np.uint8)
        if int(glyph.sum()) < 8:
            continue
        fill_ratio = float(component.sum()) / max(1.0, float(w * h))
        crop_path = glyph_dir / f"label_{len(candidates) + 1:02d}.png"
        save_png(crop_path, np.repeat((glyph * 255)[:, :, None], 3, axis=2))
        candidates.append(
            {
                "id": f"label_{len(candidates) + 1:02d}",
                "box_px": [x, y, x + w, y + h],
                "box_norm": normalize_box([x, y, x + w, y + h], width, height),
                "centroid_px": [round(cx, 2), round(cy, 2)],
                "centroid_norm": normalize_point(cx, cy, width, height),
                "width_px": w,
                "height_px": h,
                "area_px": area,
                "fill_ratio": round(fill_ratio, 3),
                "glyph_png": str(crop_path),
                "possible_point_marker": bool(fill_ratio > 0.58 and h <= 1.6 * stroke_w * 2.0),
            }
        )
        if len(candidates) >= max_labels:
            break

    viz = None
    if visualize:
        overlay = new_overlay(image_path)
        for cand in candidates:
            color = (30, 120, 220) if not cand["possible_point_marker"] else (220, 120, 30)
            draw_box(overlay, cand["box_px"], color, 2)
            draw_label(overlay, cand["id"], cand["box_px"][:2], color)
        viz = save_png(base / "extract_label_candidates.png", overlay)

    notes = [
        "long line structures are suppressed from this mask, so glyphs touching edges remain recoverable",
        "possible_point_marker=True means the blob is dot-like; it should not be read as a letter",
    ]
    return envelope(
        "extract_label_candidates",
        image_path,
        roi=roi_info(roi_box, width, height),
        method="long-line suppression + connected components + glyph size/aspect filtering",
        params={"max_labels": max_labels, "cap_height_px": round(cap_h, 2), "stroke_width_px": round(stroke_w, 2)},
        results={"count": len(candidates), "labels": candidates, "glyph_dir": str(glyph_dir)},
        notes=notes,
        visualization=viz,
    )


# --------------------------------------------------------------------------- #
# 2. template matching
# --------------------------------------------------------------------------- #
def _candidate_glyph(mask: np.ndarray, cand: dict[str, Any]) -> np.ndarray | None:
    """Crop a glyph from the ink mask (preferred) or load its saved crop."""
    box = cand.get("box_px")
    if isinstance(box, (list, tuple)) and len(box) == 4:
        x0, y0, x1, y1 = (int(round(float(v))) for v in box)
        h, w = mask.shape
        x0, x1 = max(0, min(x0, w)), max(0, min(x1, w))
        y0, y1 = max(0, min(y0, h)), max(0, min(y1, h))
        if x1 > x0 and y1 > y0:
            crop = (mask[y0:y1, x0:x1] > 0).astype(np.uint8) * 255
            if crop.sum() > 0:
                return crop
    glyph_path = cand.get("glyph_png")
    if glyph_path:
        path = Path(str(glyph_path))
        if path.is_file():
            with Image.open(path) as im:
                return np.asarray(im.convert("L"))
    return None


def match_label_templates(
    image_path: str | Path,
    candidates: list[dict[str, Any]] | None = None,
    *,
    top_k: int = 3,
    visualize: bool = True,
    out_dir: str | Path | None = None,
) -> dict[str, Any]:
    mask, _ = load_ink(image_path)
    height, width = mask.shape
    # Accept either full candidate records or bare ids from an earlier tool
    # reply.  Bare ids cannot be resolved across calls, so re-extract instead
    # of failing.
    if candidates is None or not any(
        isinstance(c, dict) and ("box_px" in c or "glyph_png" in c) for c in candidates
    ):
        extracted = extract_label_candidates(image_path, visualize=False, out_dir=out_dir)
        candidates = extracted["results"]["labels"]
        candidates = [c for c in candidates if "box_px" in c]
    templates = _templates()
    matches: list[dict[str, Any]] = []
    for cand in candidates:
        glyph = _candidate_glyph(mask, cand)
        if glyph is None:
            continue
        normalised = _normalise_glyph((glyph > 127).astype(np.uint8))
        if normalised is None or not templates:
            matches.append({**cand, "top": [], "chosen": "?", "ambiguous": True, "reason": "no glyph/template"})
            continue
        scored = sorted(
            ((ch, float((normalised * tpl).mean())) for ch, tpl in templates.items()),
            key=lambda pair: pair[1],
            reverse=True,
        )[:top_k]
        top = [{"char": ch, "ncc": round(score, 4)} for ch, score in scored]
        ambiguous = len(top) >= 2 and (top[0]["ncc"] - top[1]["ncc"]) < 0.06
        matches.append(
            {
                **cand,
                "top": top,
                "chosen": top[0]["char"] if top else "?",
                "ambiguous": bool(ambiguous),
                "score_kind": "normalised cross-correlation (template match), not a probability",
            }
        )

    viz = None
    if visualize:
        overlay = new_overlay(image_path)
        for match in matches:
            box = match.get("box_px")
            if not (isinstance(box, (list, tuple)) and len(box) == 4):
                continue
            ch = match.get("chosen", "?")
            color = (30, 150, 80) if not match.get("ambiguous") else (220, 140, 30)
            draw_box(overlay, box, color, 2)
            draw_label(overlay, f"{match.get('id', '?')}={ch}", box[:2], color)
        base = Path(out_dir) if out_dir else PROJECT_ROOT / "outputs" / "cv_preview" / Path(image_path).stem
        viz = save_png(base / "match_label_templates.png", overlay)

    return envelope(
        "match_label_templates",
        image_path,
        roi=roi_info(parse_roi(None, width, height), width, height),
        method="normalised glyph crop + NCC against serif/Computer-Modern templates",
        params={"top_k": top_k, "charset": CHAR_SET},
        results={"count": len(matches), "matches": matches},
        notes=[
            "template recognition is best-effort for single Latin letters/digits",
            "ambiguous matches should be escalated to a visual model by the Supervisor",
        ],
        visualization=viz,
    )


# --------------------------------------------------------------------------- #
# 3. geometry-point derivation + exclusive binding
# --------------------------------------------------------------------------- #
def _spans_contain(p: np.ndarray, a: np.ndarray, b: np.ndarray, tol: float = 0.07) -> bool:
    d = b - a
    length2 = float(d @ d)
    if length2 < 1e-9:
        return False
    t = float((p - a) @ d / length2)
    return -tol <= t <= 1 + tol


def _derive_points(image_path: str | Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    from .circle_detection import detect_circles
    from .line_detection import detect_lines

    lines = detect_lines(image_path, visualize=False)
    circles = detect_circles(image_path, visualize=False)
    segments = lines["results"]["segments"]
    raw_lines = [(np.array(s["a_px"], float), np.array(s["b_px"], float)) for s in segments]
    points: list[np.ndarray] = []
    for i in range(len(raw_lines)):
        for j in range(i + 1, len(raw_lines)):
            a, b = raw_lines[i]
            c, d = raw_lines[j]
            r, s = b - a, d - c
            den = r[0] * s[1] - r[1] * s[0]
            if abs(den) < 1e-6:
                continue
            ang = abs(math.degrees(angle_of(a, b) - angle_of(c, d))) % 180
            if min(ang, 180 - ang) < 10:
                continue
            t = ((c - a)[0] * s[1] - (c - a)[1] * s[0]) / den
            p = a + t * r
            if _spans_contain(p, a, b) and _spans_contain(p, c, d):
                points.append(p)
    for circ in circles["results"]["circles"]:
        center = np.array(circ["center_px"], float)
        radius = float(circ["radius_px"])
        points.append(center)
        ranges = circ.get("visible_ranges_deg") or []
        full = bool(circ.get("full_circle"))
        for a, b in raw_lines:
            for p in line_circle_intersections(a, b, center, radius):
                if _spans_contain(p, a, b):
                    theta = math.atan2(p[1] - center[1], p[0] - center[0])
                    if full or any(in_arc(theta, False, math.radians(lo), math.radians(hi)) for lo, hi in ranges):
                        points.append(p)
    clustered = cluster_points(points, eps=6.0)
    out = [
        {
            "id": f"point_{idx:02d}",
            "coords_px": [round(float(p[0]), 2), round(float(p[1]), 2)],
        }
        for idx, p in enumerate(clustered, start=1)
    ]
    meta = {
        "line_segments": len(segments),
        "circles": len(circles["results"]["circles"]),
        "candidate_points": len(out),
    }
    return out, meta


def _point_xy(point: Any) -> list[float] | None:
    if not isinstance(point, dict):
        return None
    for key in ("coords_px", "px"):
        value = point.get(key)
        if isinstance(value, (list, tuple)) and len(value) >= 2:
            return [float(value[0]), float(value[1])]
    coords = point.get("coords")
    if isinstance(coords, (list, tuple)) and len(coords) >= 2:
        return [float(coords[0]), float(coords[1])]
    if isinstance(coords, dict):
        for key in ("px", "point", "xy", "center"):
            value = coords.get(key)
            if isinstance(value, (list, tuple)) and len(value) >= 2:
                return [float(value[0]), float(value[1])]
    return None


def bind_point_labels(
    image_path: str | Path,
    *,
    points: list[dict[str, Any]] | None = None,
    labels: list[dict[str, Any]] | None = None,
    max_distance_px: float | None = None,
    visualize: bool = True,
    out_dir: str | Path | None = None,
) -> dict[str, Any]:
    mask, _ = load_ink(image_path)
    height, width = mask.shape
    _, text, stroke_w, cap_h = _line_suppressed_text(image_path)
    if points is None:
        points, point_meta = _derive_points(image_path)
    else:
        normalised_points: list[dict[str, Any]] = []
        for index, raw in enumerate(points):
            xy = _point_xy(raw)
            if xy is None:
                continue
            record = dict(raw)
            record["coords_px"] = xy
            record.setdefault("id", f"point_{index + 1:02d}")
            normalised_points.append(record)
        points = normalised_points
        point_meta = {"candidate_points": len(points), "source": "supplied"}
    usable_supplied = isinstance(labels, list) and any(
        isinstance(lab, dict) and "centroid_px" in lab and lab.get("chosen") not in (None, "?")
        for lab in labels
    )
    if labels is None or not usable_supplied:
        # Bare ids or partially-filled records: re-derive glyphs + letters.
        matched = match_label_templates(image_path, visualize=False, out_dir=out_dir)
        labels = matched["results"]["matches"]

    maxd = float(max_distance_px if max_distance_px is not None else max(18.0, 2.6 * cap_h))
    usable_labels = [
        lab for lab in labels
        if lab.get("chosen") not in (None, "?") and not lab.get("possible_point_marker") and "centroid_px" in lab
    ]
    label_pts = [np.array(lab["centroid_px"], float) for lab in usable_labels]
    point_pts = [np.array(p.get("coords_px") or p.get("coords") or [0, 0], float) for p in points]

    bindings: list[dict[str, Any]] = []
    unmatched_labels: list[str] = []
    unmatched_points: list[str] = []
    if label_pts and point_pts:
        cost = np.zeros((len(label_pts), len(point_pts)), float)
        for i, lpt in enumerate(label_pts):
            for j, ppt in enumerate(point_pts):
                dist = float(np.linalg.norm(lpt - ppt))
                # Prefer labels sitting outside the figure: small directional bonus
                # for labels that are farther than the median point spacing.
                cost[i, j] = dist if dist <= maxd else 1e6 + dist
        rows, cols = linear_sum_assignment(cost)
        used_labels: set[int] = set()
        used_points: set[int] = set()
        for r, c in zip(rows.tolist(), cols.tolist()):
            if cost[r, c] >= 1e6:
                continue
            lab = usable_labels[r]
            point = points[c]
            bindings.append(
                {
                    "label_id": lab["id"],
                    "char": lab["chosen"],
                    "point_id": point["id"],
                    "point_px": point["coords_px"] if "coords_px" in point else point.get("coords"),
                    "distance_px": round(float(cost[r, c]), 2),
                    "ncc": lab.get("top", [{}])[0].get("ncc"),
                    "ambiguous_template": lab.get("ambiguous", False),
                    "method": "Hungarian exclusive assignment on label-centroid distance",
                }
            )
            used_labels.add(r)
            used_points.add(c)
        unmatched_labels = [usable_labels[i]["id"] for i in range(len(usable_labels)) if i not in used_labels]
        unmatched_points = [points[i]["id"] for i in range(len(points)) if i not in used_points]
    else:
        unmatched_labels = [lab.get("id", "?") for lab in usable_labels]
        unmatched_points = [p.get("id", "?") for p in points]

    viz = None
    if visualize:
        overlay = new_overlay(image_path)
        for point in points:
            xy = point.get("coords_px") or point.get("coords")
            if xy:
                cv2.circle(overlay, (int(round(xy[0])), int(round(xy[1]))), 4, (200, 60, 40), 2)
                draw_label(overlay, point["id"].replace("point_", "p"), xy, (200, 60, 40))
        for lab in usable_labels:
            draw_box(overlay, lab["box_px"], (30, 120, 220), 2)
        for binding in bindings:
            pxy = binding["point_px"]
            lab = next((lab for lab in usable_labels if lab["id"] == binding["label_id"]), None)
            if lab and pxy:
                draw_segment(overlay, lab["centroid_px"], pxy, (20, 150, 80), 1)
                draw_label(overlay, binding["char"], pxy, (20, 150, 80))
        base = Path(out_dir) if out_dir else PROJECT_ROOT / "outputs" / "cv_preview" / Path(image_path).stem
        viz = save_png(base / "bind_point_labels.png", overlay)

    return envelope(
        "bind_point_labels",
        image_path,
        roi=roi_info(parse_roi(None, width, height), width, height),
        method="vertex derivation + Hungarian exclusive label-to-point assignment",
        params={"max_distance_px": maxd, "cap_height_px": round(cap_h, 2), **point_meta},
        results={
            "bindings": bindings,
            "unmatched_labels": unmatched_labels,
            "unmatched_points": unmatched_points,
            "points": points,
            "labels": [
                {
                    "id": lab.get("id"),
                    "chosen": lab.get("chosen"),
                    "box_px": lab.get("box_px"),
                    "centroid_px": lab.get("centroid_px"),
                    "top": lab.get("top"),
                    "ambiguous": lab.get("ambiguous"),
                }
                for lab in usable_labels
            ],
        },
        notes=[
            "bindings are exclusive; ambiguous template matches are flagged and may need visual verification",
            "unmatched candidates are preserved rather than force-assigned",
        ],
        visualization=viz,
    )
