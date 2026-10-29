"""Shared classical-CV primitives for the GeoAgent toolbox.

Coordinate conventions
  * pixel coordinates: origin at the image's top-left, x right, y down.
  * normalized coordinates: x/y divided by image width/height, in [0, 1].
  * Every tool reports both, plus an explicit ``coordinate_system`` string.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import cv2
import numpy as np
from PIL import Image
from sklearn.cluster import DBSCAN

COORDINATE_SYSTEM = "pixel: origin top-left, x right, y down; normalized: x/width, y/height in [0,1]"


# --------------------------------------------------------------------------- #
# image loading / ROI
# --------------------------------------------------------------------------- #
@dataclass
class ROI:
    x0: int
    y0: int
    x1: int
    y1: int

    @property
    def width(self) -> int:
        return max(0, self.x1 - self.x0)

    @property
    def height(self) -> int:
        return max(0, self.y1 - self.y0)

    def as_list(self) -> list[int]:
        return [int(self.x0), int(self.y0), int(self.x1), int(self.y1)]


def load_rgb(path: str | Path) -> np.ndarray:
    with Image.open(path) as im:
        return np.asarray(im.convert("RGB"))


def load_ink(path: str | Path) -> tuple[np.ndarray, np.ndarray]:
    """Return (binary ink mask, grey image). Handles LA (alpha) and RGBA."""
    with Image.open(path) as im:
        arr = np.asarray(im)
    if arr.ndim == 3 and arr.shape[2] == 2:  # LA: luminance + coverage
        lum, alpha = arr[..., 0].astype(np.float32), arr[..., 1].astype(np.float32)
        grey = lum * (alpha / 255.0) + 255.0 * (1.0 - alpha / 255.0)
    elif arr.ndim == 3 and arr.shape[2] == 4:  # RGBA
        rgb = arr[..., :3].astype(np.float32)
        alpha = arr[..., 3:4].astype(np.float32) / 255.0
        grey = (rgb * alpha + 255.0 * (1.0 - alpha)).mean(axis=2)
    elif arr.ndim == 3:
        grey = cv2.cvtColor(arr[..., :3].astype(np.uint8), cv2.COLOR_RGB2GRAY).astype(np.float32)
    else:
        grey = arr.astype(np.float32)
    return (grey < 128).astype(np.uint8), grey


def parse_roi(roi: Any, width: int, height: int) -> ROI:
    """Accept dict/list ROI in normalized or pixel space."""
    if roi is None:
        return ROI(0, 0, width, height)
    if isinstance(roi, dict):
        space = str(roi.get("space", "normalized")).lower()
        values = [roi.get("x0"), roi.get("y0"), roi.get("x1"), roi.get("y1")]
        if any(v is None for v in values):
            raise ValueError("ROI dict must contain x0, y0, x1, y1")
        x0, y0, x1, y1 = (float(v) for v in values)
        if space.startswith("px") or space.startswith("pixel"):
            px = [x0, y0, x1, y1]
        else:
            px = [x0 * width, y0 * height, x1 * width, y1 * height]
    elif isinstance(roi, (list, tuple)) and len(roi) == 4:
        vals = [float(v) for v in roi]
        if max(vals) <= 1.0:
            px = [vals[0] * width, vals[1] * height, vals[2] * width, vals[3] * height]
        else:
            px = vals
    else:
        raise ValueError("roi must be None, [x0,y0,x1,y1], or a dict")

    x0 = int(round(min(max(px[0], 0.0), width - 1)))
    y0 = int(round(min(max(px[1], 0.0), height - 1)))
    x1 = int(round(min(max(px[2], 1.0), width)))
    y1 = int(round(min(max(px[3], 1.0), height)))
    if x1 <= x0 or y1 <= y0:
        raise ValueError(f"empty ROI {px}")
    return ROI(x0, y0, x1, y1)


def roi_info(roi: ROI, width: int, height: int) -> dict[str, Any]:
    return {
        "x0": roi.x0,
        "y0": roi.y0,
        "x1": roi.x1,
        "y1": roi.y1,
        "space": "pixel",
        "normalized": [
            round(roi.x0 / width, 4),
            round(roi.y0 / height, 4),
            round(roi.x1 / width, 4),
            round(roi.y1 / height, 4),
        ],
    }


# --------------------------------------------------------------------------- #
# morphology / geometry
# --------------------------------------------------------------------------- #
def thin(mask: np.ndarray) -> np.ndarray:
    binary = (mask > 0).astype(np.uint8) * 255
    try:
        return cv2.ximgproc.thinning(binary)
    except Exception:
        from skimage.morphology import skeletonize

        return (skeletonize(binary > 0).astype(np.uint8)) * 255


def estimate_stroke_width(mask: np.ndarray, skel: np.ndarray) -> float:
    dist = cv2.distanceTransform((mask > 0).astype(np.uint8), cv2.DIST_L2, 5)
    values = dist[(skel > 0) & np.isfinite(dist)]
    if not values.size:
        return 2.0
    width = float(2.0 * np.median(values))
    return width if math.isfinite(width) and width > 0 else 2.0


def line_params(segment: list[float]) -> tuple[float, float]:
    x1, y1, x2, y2 = segment
    phi = math.atan2(y2 - y1, x2 - x1) + math.pi / 2
    phi %= math.pi
    rho = x1 * math.cos(phi) + y1 * math.sin(phi)
    return phi, rho


def point_line_distance(point: Any, a: Any, b: Any) -> float:
    point = np.asarray(point, float)
    a = np.asarray(a, float)
    b = np.asarray(b, float)
    ab = b - a
    length = float(np.hypot(ab[0], ab[1]))
    if length < 1e-9:
        return float(np.linalg.norm(point - a))
    return abs(float(ab[0] * (point[1] - a[1]) - ab[1] * (point[0] - a[0]))) / length


def point_segment_distance(point: Any, a: Any, b: Any) -> float:
    point = np.asarray(point, float)
    a = np.asarray(a, float)
    b = np.asarray(b, float)
    d = b - a
    length2 = float(d @ d)
    if length2 < 1e-9:
        return float(np.linalg.norm(point - a))
    t = float(np.clip((point - a) @ d / length2, 0.0, 1.0))
    return float(np.linalg.norm(point - (a + t * d)))


def merge_collinear_segments(
    segments: list[list[float]],
    ink: np.ndarray | None = None,
    *,
    angle_tol_deg: float = 3.0,
    dist_tol_px: float = 4.5,
) -> list[dict[str, Any]]:
    """Union-find merge of collinear Hough fragments.

    Bridging a gap requires actual ink along the bridge (if an ink mask is
    supplied), so two collinear right-angle glyph sides are not fused.
    """
    if not segments:
        return []
    n = len(segments)
    parent = list(range(n))

    def find(a: int) -> int:
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    params = [line_params(s) for s in segments]
    ends = [((s[0], s[1]), (s[2], s[3])) for s in segments]
    for i in range(n):
        for j in range(i + 1, n):
            dphi = abs(params[i][0] - params[j][0])
            dphi = min(dphi, math.pi - dphi)
            if math.degrees(dphi) >= angle_tol_deg:
                continue
            (ai, bi), (aj, bj) = ends[i], ends[j]
            direction = np.asarray(bi, float) - np.asarray(ai, float)
            length = float(np.linalg.norm(direction))
            if length < 1e-9:
                continue
            unit = direction / length
            lo, hi = sorted(float(np.dot(np.asarray(p, float) - ai, unit)) for p in (aj, bj))
            gap = max(0.0, lo - length, -hi)
            other_len = float(np.linalg.norm(np.asarray(bj, float) - np.asarray(aj, float)))
            gap_limit = max(8.0, min(20.0, 0.2 * min(length, other_len)))
            if gap > gap_limit:
                if ink is None:
                    continue
                start, stop = (length, lo) if lo > length else (hi, 0.0)
                votes = []
                for t in np.linspace(start, stop, max(8, int(gap / 2))):
                    x, y = np.rint(np.asarray(ai, float) + t * unit).astype(int)
                    votes.append(bool(np.any(ink[max(0, y - 2):y + 3, max(0, x - 2):x + 3])))
                if np.mean(votes) < 0.80:
                    continue
            if (
                point_line_distance(aj, ai, bi) <= dist_tol_px
                and point_line_distance(bj, ai, bi) <= dist_tol_px
                and point_line_distance(ai, aj, bj) <= dist_tol_px
                and point_line_distance(bi, aj, bj) <= dist_tol_px
            ):
                parent[find(i)] = find(j)

    groups: dict[int, list[int]] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)
    merged: list[dict[str, Any]] = []
    for idx in groups.values():
        phi = float(np.mean([params[i][0] for i in idx]))
        ux, uy = math.cos(phi + math.pi / 2), math.sin(phi + math.pi / 2)
        points = np.array(
            [[segments[i][0], segments[i][1]] for i in idx] + [[segments[i][2], segments[i][3]] for i in idx],
            float,
        )
        t = points @ np.array([ux, uy])
        p0 = points[int(np.argmin(t))]
        p1 = points[int(np.argmax(t))]
        merged.append({"a": p0.tolist(), "b": p1.tolist(), "parts": idx, "angle_deg": round(math.degrees(phi), 2)})
    return merged


def hough_segments(
    skel: np.ndarray,
    *,
    threshold_frac: float = 0.05,
    min_length_frac: float = 0.02,
    max_gap_frac: float = 0.015,
) -> list[list[float]]:
    h, w = skel.shape
    short = min(h, w)
    lines = cv2.HoughLinesP(
        skel,
        1,
        np.pi / 360,
        max(12, int(threshold_frac * short)),
        minLineLength=max(10, int(min_length_frac * short)),
        maxLineGap=max(2, int(max_gap_frac * short)),
    )
    if lines is None:
        return []
    return [[float(v) for v in row[0]] for row in lines]


def lsd_segments(grey: np.ndarray, min_length: float = 15.0) -> list[list[float]]:
    """OpenCV LSD as a fallback when Hough finds too little structure."""
    try:
        detector = cv2.createLineSegmentDetector(cv2.LSD_REFINE_STD)
        result = detector.detect(grey.astype(np.uint8))[0]
    except Exception:
        return []
    if result is None:
        return []
    out = []
    for row in result[:, 0, :]:
        x1, y1, x2, y2 = (float(v) for v in row)
        if math.hypot(x2 - x1, y2 - y1) >= min_length:
            out.append([x1, y1, x2, y2])
    return out


def fit_circle_kasa(points: np.ndarray) -> tuple[np.ndarray, float] | None:
    pts = np.asarray(points, float)
    if len(pts) < 3:
        return None
    x, y = pts[:, 0], pts[:, 1]
    A = np.column_stack([2 * x, 2 * y, np.ones(len(x))])
    b = x * x + y * y
    try:
        sol, *_ = np.linalg.lstsq(A, b, rcond=None)
    except np.linalg.LinAlgError:
        return None
    cx, cy, c = sol
    r2 = c + cx * cx + cy * cy
    if r2 <= 0:
        return None
    return np.array([cx, cy]), float(math.sqrt(r2))


def circumcenter(p1: Any, p2: Any, p3: Any) -> np.ndarray | None:
    ax, ay = p1
    bx, by = p2
    cx, cy = p3
    d = 2.0 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(d) < 1e-9:
        return None
    a2, b2, c2 = ax * ax + ay * ay, bx * bx + by * by, cx * cx + cy * cy
    return np.array(
        [
            (a2 * (by - cy) + b2 * (cy - ay) + c2 * (ay - by)) / d,
            (a2 * (cx - bx) + b2 * (ax - cx) + c2 * (bx - ax)) / d,
        ]
    )


def angular_span(angles: np.ndarray) -> tuple[bool, float, float]:
    """Return (is_full, lo, hi) for sorted angles in radians."""
    ang = np.sort(np.mod(np.asarray(angles, float), 2 * np.pi))
    if len(ang) == 0:
        return False, 0.0, 0.0
    diffs = np.diff(np.concatenate([ang, ang[:1] + 2 * np.pi]))
    idx = int(np.argmax(diffs))
    if float(diffs[idx]) >= math.radians(300) and len(ang) >= 8:
        return True, 0.0, 2 * math.pi
    lo = float(ang[(idx + 1) % len(ang)])
    hi = float(ang[idx])
    if hi < lo:
        hi += 2 * math.pi
    return False, lo, hi


def in_arc(theta: float, full: bool, lo: float, hi: float, margin_deg: float = 3.0) -> bool:
    if full:
        return True
    margin = math.radians(margin_deg)
    theta = theta % (2 * math.pi)
    lo = lo % (2 * math.pi)
    hi = (hi - lo) % (2 * math.pi) + lo
    if theta < lo:
        theta += 2 * math.pi
    return lo - margin <= theta <= hi + margin


def line_circle_intersections(a: Any, b: Any, center: Any, radius: float) -> list[np.ndarray]:
    a = np.asarray(a, float)
    b = np.asarray(b, float)
    c = np.asarray(center, float)
    d = b - a
    A = float(d @ d)
    if A < 1e-12:
        return []
    B = 2.0 * float(d @ (a - c))
    C = float((a - c) @ (a - c)) - radius * radius
    disc = B * B - 4 * A * C
    if disc < 0:
        return []
    sq = math.sqrt(disc)
    return [a + (-B - sq) / (2 * A) * d, a + (-B + sq) / (2 * A) * d]


def circle_circle_intersections(c1: Any, r1: float, c2: Any, r2: float) -> list[np.ndarray]:
    c1 = np.asarray(c1, float)
    c2 = np.asarray(c2, float)
    d = float(np.linalg.norm(c2 - c1))
    if d < 1e-9 or d > r1 + r2 or d < abs(r1 - r2):
        return []
    a = (r1 * r1 - r2 * r2 + d * d) / (2 * d)
    h2 = r1 * r1 - a * a
    if h2 < 0:
        return []
    h = math.sqrt(h2)
    mid = c1 + a * (c2 - c1) / d
    perp = np.array([-(c2 - c1)[1], (c2 - c1)[0]]) / d
    return [mid + h * perp, mid - h * perp]


def cluster_points(points: list[np.ndarray], eps: float) -> np.ndarray:
    if not points:
        return np.zeros((0, 2), float)
    arr = np.array([p for p in points if np.all(np.isfinite(p))], float)
    if not len(arr):
        return np.zeros((0, 2), float)
    labels = DBSCAN(eps=eps, min_samples=1).fit(arr).labels_
    return np.array([arr[labels == k].mean(0) for k in range(labels.max() + 1)])


def component_principal_axis(points: np.ndarray) -> tuple[np.ndarray, np.ndarray, float, float]:
    pts = np.asarray(points, float)
    mu = pts.mean(0)
    centered = pts - mu
    _, singular, vt = np.linalg.svd(centered, full_matrices=False)
    direction = vt[0]
    t = centered @ direction
    p0, p1 = mu + t.min() * direction, mu + t.max() * direction
    major = float(t.max() - t.min())
    minor = float(2.0 * singular[-1] / math.sqrt(max(len(pts), 1)))
    return p0, p1, major, minor


def angle_of(a: Any, b: Any) -> float:
    return math.atan2(b[1] - a[1], b[0] - a[0]) % math.pi


# --------------------------------------------------------------------------- #
# visualisation
# --------------------------------------------------------------------------- #
def _bgr(img: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(img, cv2.COLOR_RGB2BGR)


def save_png(path: str | Path, img_rgb: np.ndarray) -> str:
    """Unicode-safe PNG write (cv2.imwrite fails on Chinese Windows paths)."""
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    ok, buf = cv2.imencode(".png", _bgr(np.ascontiguousarray(img_rgb)))
    if not ok:
        raise RuntimeError(f"failed to encode image for {out}")
    out.write_bytes(buf.tobytes())
    return str(out)


def draw_segment(img: np.ndarray, a: Any, b: Any, color: tuple[int, int, int], thickness: int = 2) -> None:
    cv2.line(img, (int(round(a[0])), int(round(a[1]))), (int(round(b[0])), int(round(b[1]))), color, thickness)


def draw_label(img: np.ndarray, text: str, xy: Any, color: tuple[int, int, int]) -> None:
    cv2.putText(
        img,
        text,
        (int(round(xy[0])) + 3, int(round(xy[1])) - 3),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.45,
        color,
        1,
        cv2.LINE_AA,
    )


def draw_circle(
    img: np.ndarray,
    center: Any,
    radius: float,
    color: tuple[int, int, int],
    thickness: int = 2,
    start_deg: float | None = None,
    end_deg: float | None = None,
) -> None:
    if start_deg is None or end_deg is None:
        cv2.circle(img, (int(round(center[0])), int(round(center[1]))), int(round(radius)), color, thickness)
        return
    cv2.ellipse(
        img,
        (int(round(center[0])), int(round(center[1]))),
        (int(round(radius)), int(round(radius))),
        0,
        float(start_deg),
        float(end_deg),
        color,
        thickness,
    )


def draw_box(img: np.ndarray, box: Any, color: tuple[int, int, int], thickness: int = 1) -> None:
    x0, y0, x1, y1 = (int(round(v)) for v in box)
    cv2.rectangle(img, (x0, y0), (x1, y1), color, thickness)


def new_overlay(path: str | Path) -> np.ndarray:
    return load_rgb(path).copy()


def envelope(
    tool: str,
    image_path: str | Path,
    *,
    roi: dict[str, Any],
    method: str,
    params: dict[str, Any],
    results: dict[str, Any],
    notes: list[str] | None = None,
    visualization: str | None = None,
    ok: bool = True,
) -> dict[str, Any]:
    return {
        "ok": ok,
        "tool": tool,
        "image": str(image_path),
        "coordinate_system": COORDINATE_SYSTEM,
        "roi": roi,
        "method": method,
        "params": params,
        "results": results,
        "notes": notes or [],
        "visualization": visualization,
        "confidence_kind": "heuristic-evidence (not a calibrated probability)",
    }


def normalize_point(x: float, y: float, width: int, height: int) -> list[float]:
    return [round(float(x) / max(width, 1), 4), round(float(y) / max(height, 1), 4)]


def normalize_box(box: Any, width: int, height: int) -> list[float]:
    x0, y0, x1, y1 = box
    return [
        round(float(x0) / max(width, 1), 4),
        round(float(y0) / max(height, 1), 4),
        round(float(x1) / max(width, 1), 4),
        round(float(y1) / max(height, 1), 4),
    ]


def run_with_roi(
    image_path: str | Path,
    roi_arg: Any,
    fn: Callable[[np.ndarray, np.ndarray, ROI, int, int], Any],
) -> tuple[Any, ROI, int, int, np.ndarray, np.ndarray]:
    """Load image + ink, crop ROI, invoke ``fn(mask, grey, roi, W, H)``.

    The returned mask/grey are ROI-local; callers add ``roi.x0/y0`` offsets.
    """
    mask, grey = load_ink(image_path)
    h, w = mask.shape
    roi = parse_roi(roi_arg, w, h)
    sub_mask = mask[roi.y0:roi.y1, roi.x0:roi.x1]
    sub_grey = grey[roi.y0:roi.y1, roi.x0:roi.x1]
    return fn(sub_mask, sub_grey, roi, w, h), roi, w, h, mask, grey
