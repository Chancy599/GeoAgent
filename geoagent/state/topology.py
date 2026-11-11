"""Source-backed requirements for named straight edges in generated TikZ."""
from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from itertools import combinations, product
from pathlib import Path

import numpy as np

from ..cv_tools.common import load_ink
from .coordinate_contract import MEASURED_POINT_SOURCES, build_coordinate_contract
from .measured_topology import measured_topology
from .schemas import GeometricEvidenceState
from .tikz_geometry import NAME, clean

MAX_ENDPOINT_CASES = 6


def _xy(value):
    try:
        point = np.asarray(value, dtype=float)
    except (TypeError, ValueError):
        return None
    return point if point.shape == (2,) and np.isfinite(point).all() else None


def _continuous_source_ink(mask, a, b) -> bool:
    offset = b - a
    length = float(np.linalg.norm(offset))
    if length < 25:
        return False
    direction = offset / length
    normal = np.array([-direction[1], direction[0]])
    center = a + np.linspace(2, length - 2, max(25, int(length)))[:, None] * direction
    sample = np.rint(center[:, None, :] + np.arange(-1, 2)[None, :, None] * normal).astype(int)
    x, y = sample[..., 0], sample[..., 1]
    height, width = mask.shape
    valid = (x >= 0) & (x < width) & (y >= 0) & (y < height)
    ink = np.zeros_like(valid)
    ink[valid] = mask[y[valid], x[valid]] > 0
    hits = ink.any(axis=1)
    return bool(hits.mean() >= .98 and min(section.mean() for section in np.array_split(hits, 12)) >= .90)


def build_topology_plan(state: GeometricEvidenceState, *, include_extensions: bool = True) -> dict:
    """Keep strong CV evidence and expose competing endpoint interpretations."""
    contract = build_coordinate_contract(state) or {}
    construction = state.meta.get('source_construction', {})
    reliable = set(contract.get("points", {}))
    points, point_ids = {}, set()
    for label, key in state.label_bindings.items():
        obj = state.objects.get(key)
        if (not re.fullmatch("[A-Z]", label) or obj is None or obj.type != "point"
                or obj.label != label or obj.source not in MEASURED_POINT_SOURCES
                or obj.status in ("rejected", "conflict")):
            continue
        point = _xy(obj.coords.get("px"))
        if point is not None:
            points[label] = point
            point_ids.add(key)
    requirements = [row for row in construction.get('strokes',[]) if all(n in reliable for n in row['edge'])]
    marks = {v: mark for v, mark in construction.get('marks',{}).items()
             if all(n in reliable for n in (v,*mark['arms']))}
    required = {tuple(row['edge']) for row in requirements}
    for name, point in contract.get('points', {}).items():
        if include_extensions and (anchor := point.get('extension_from')):
            edge = sorted((anchor, name))
            required.add(tuple(edge))
            requirements.append({'edge': edge, 'style': 'solid'})
    ink_confirmed = set()
    cases = []
    if len(points) < 2:
        return {"required_edges": [], "pending": [], "adjudicated": [], "ink_confirmed_edges": []}

    def add_case(stroke_id, options, **evidence):
        case = {
            "stroke_id": stroke_id,
            "options": [list(edge) for edge in options],
            "points_px": {label: points[label].tolist() for edge in options for label in edge},
            "ambiguous_labels": sorted({label for edge in options for label in edge} - reliable),
            **evidence,
        }
        case["id"] = hashlib.sha256(json.dumps(case, sort_keys=True).encode()).hexdigest()[:16]
        cases.append(case)

    # Reuse the existing bend/marker logic with current CV label bindings.
    cv_objects = {
        key: obj for key, obj in state.objects.items()
        if obj.source.startswith("cv:") and obj.status not in ("rejected", "conflict")
        and (obj.type != "point" or key in point_ids)
        and (obj.type not in ("segment", "line")
             or all(_xy(obj.coords.get(k)) is not None for k in ("a_px", "b_px")))
        and (obj.type != "right_angle" or (
            obj.status == "confirmed" and _xy(obj.coords.get("vertex_px")) is not None
            and len(obj.coords.get("mark_points_px") or []) >= 2
            and all(_xy(p) is not None for p in obj.coords["mark_points_px"])))
    }
    evidence = measured_topology(state.model_copy(update={"objects": cv_objects}))
    if construction:
        for item in evidence['verified_right_angle_arms']:
            a, v, b = item['labels']
            if {a, v, b} <= reliable and item['marker_side_px']:
                marks.setdefault(v, {'arms': sorted((a, b)), 'side_px': item['marker_side_px']})
    uncertain_edges = {}
    for kind in ("supported_shallow_bends", "verified_right_angle_arms"):
        for item in evidence[kind]:
            a, v, b = item["labels"]
            for edge in (tuple(sorted((a, v))), tuple(sorted((v, b)))):
                if set(edge) <= reliable:
                    required.add(edge)
                else:
                    uncertain_edges.setdefault(edge, {})[kind] = item
    for edge, support in sorted(uncertain_edges.items()):
        add_case("junction:" + "--".join(edge), [edge], junction=support)

    diagonal = math.hypot(state.image_size.get("width", 0), state.image_size.get("height", 0))
    mask = None
    tried_image = False
    for key, obj in cv_objects.items():
        if obj.type not in ("segment", "line"):
            continue
        a, b = (_xy(obj.coords.get(field)) for field in ("a_px", "b_px"))
        if a is None or b is None:
            continue
        length = float(np.linalg.norm(b - a))
        if length < max(15, 0.04 * diagonal):
            continue
        dashed = obj.style.get("line") == "dashed"
        tight = max(3.5, min(7.0, 0.012 * diagonal))
        # A fitted solid span can overshoot a true endpoint as well. Only the
        # wider search goes to visual review; automatic confirmation stays tight.
        radius = max(tight, min(24.0, 0.037 * diagonal))
        axis = (b - a) / length
        candidates = []
        for endpoint in (a, b):
            near = []
            for label, point in points.items():
                offset = point - endpoint
                distance = float(np.linalg.norm(offset))
                across = abs(float(offset[0] * axis[1] - offset[1] * axis[0]))
                if distance <= min(radius, length / 3) and across <= 3.5:
                    near.append((distance, label))
            candidates.append(sorted(near)[:3])
        ranked = sorted(
            (left[0] + right[0], tuple(sorted((left[1], right[1]))))
            for left, right in product(*candidates) if left[1] != right[1]
        )
        if not ranked:
            continue
        options = sorted({edge for score, edge in ranked if score <= ranked[0][0] + tight})
        if len(options) == 1 and set(options[0]) <= reliable:
            edge = options[0]
            if all(near[0][0] <= tight for near in candidates):
                required.add(edge)
                continue
            if obj.style.get("line") == "solid":
                if not tried_image:
                    tried_image = True
                    if Path(state.image_path).is_file():
                        try:
                            mask, _ = load_ink(state.image_path)
                        except (OSError, ValueError):
                            pass
                if mask is not None and _continuous_source_ink(mask, *(points[label] for label in edge)):
                    required.add(edge)
                    ink_confirmed.add(edge)
                    continue
        if len(options) != 1 or options[0] not in uncertain_edges:
            add_case(key, options, stroke_px=[a.tolist(), b.tolist()], dashed=dashed)

    pending, adjudicated = [], []
    decisions = state.meta.get("topology_decisions", {})
    rule_edges = required.copy()
    for case in cases:
        if any(tuple(edge) in rule_edges for edge in case["options"]):
            continue
        decision = decisions.get(case["id"])
        if decision is None:
            pending.append(case)
        else:
            adjudicated.append({"case_id": case["id"], **decision})
            if decision["edge"] is not None:
                required.add(tuple(decision["edge"]))
    return {"required_edges": [list(edge) for edge in sorted(required)], "pending": pending,
            "adjudicated": adjudicated, "ink_confirmed_edges": [list(edge) for edge in sorted(ink_confirmed)],
            "required_styles": requirements, "required_marks": marks}


def validate_endpoint_decisions(plan: dict, rows) -> dict:
    """Accept only choices from the current CV evidence shown to the Critic."""
    cases = {case["id"]: case["options"] for case in plan["pending"][:MAX_ENDPOINT_CASES]}
    accepted = {}
    if not isinstance(rows, list):
        return accepted
    for row in rows[:MAX_ENDPOINT_CASES]:
        if not isinstance(row, dict) or not isinstance(row.get("case_id"), str):
            continue
        case_id = row["case_id"]
        reason = row.get("reason")
        if case_id not in cases or not isinstance(reason, str) or not reason.strip() or "edge" not in row:
            continue
        edge = row["edge"]
        if edge is not None:
            if not isinstance(edge, list) or not all(isinstance(label, str) for label in edge):
                continue
            edge = sorted(edge)
            if edge not in cases[case_id]:
                continue
        if case_id in accepted:
            return {}
        accepted[case_id] = {"edge": edge, "reason": reason.strip()[:300]}
    return accepted


_VERTEX = rf"\(\s*({NAME})\s*\)"
_CHAIN = re.compile(rf"{_VERTEX}(?:\s*--\s*{_VERTEX})+(?:\s*--\s*cycle)?")
_DRAW = re.compile(r"\\(?:draw|filldraw)\b\s*(?:\[([^\[\]]*)\]\s*)?([^;]*);")
_CARTESIAN = re.compile(r"\s*\(\s*([-+\d.eE]+)\s*,\s*([-+\d.eE]+)\s*\)\s*")
_NON_DRAWING_OR_LOCAL = re.compile(
    r"(?:\bdraw\s*=\s*none\b|\b(?:draw\s+)?opacity\s*=\s*0(?:\.0*)?\s*(?:,|$)"
    r"|\b(?:shift|[xy]shift|scale|[xy]scale|rotate|cm|transform\s+canvas|shorten\s*[<>])\s*=)"
)


def _has_collinear_chain(start, end, edges, points):
    if start not in points or end not in points:
        return False
    origin = points[start]
    offset = points[end] - origin
    length = float(np.linalg.norm(offset))
    if length < 1e-9:
        return False
    axis = offset / length
    tolerance = max(0.003, min(0.025, 0.005 * length))
    on_segment = set()
    for name, point in points.items():
        delta = point - origin
        across = abs(float(delta[0] * axis[1] - delta[1] * axis[0]))
        if across <= tolerance and -0.003 <= delta @ axis <= length + 0.003:
            on_segment.add(name)
    reached = {start}
    while True:
        expanded = reached | {
            b if a in reached else a for a, b in edges
            if a in on_segment and b in on_segment and (a in reached or b in reached)
        }
        if end in expanded:
            return True
        if expanded == reached:
            return False
        reached = expanded


def _overlapping_strokes(strokes, points):
    duplicates = set()
    for first, second in combinations(strokes, 2):
        if first == second:
            duplicates.add((first, second))
            continue
        if any(name not in points for edge in (first, second) for name in edge):
            continue
        longer, shorter = sorted((first, second), key=lambda edge: np.linalg.norm(points[edge[1]]-points[edge[0]]),
                                 reverse=True)
        start, end = (points[name] for name in longer)
        axis = end-start
        length = np.linalg.norm(axis)
        axis /= length
        offsets = np.asarray([points[name]-start for name in shorter])
        along = offsets@axis
        across = offsets@np.array([-axis[1], axis[0]])
        tolerance = max(.003, min(.045, .006*length))
        if (min(along) >= -tolerance and max(along) <= length+tolerance
                and np.max(np.abs(across)) <= tolerance
                and abs(across[1]-across[0]) <= math.tan(math.radians(2))*abs(along[1]-along[0])):
            duplicates.add(tuple(sorted((longer, shorter))))
    return [[list(a), list(b)] for a, b in sorted(duplicates)]


def check_topology(tex: str, plan: dict) -> dict:
    """Check explicit named edges, including shared vertices and closed chains."""
    required = plan["required_edges"]
    edges = set()
    styled = {'solid':set(), 'dashed':set()}
    solid_strokes = []
    text = clean(tex)
    definitions = re.findall(rf"\\coordinate\s*{_VERTEX}\s*at\b([^;]*);", text)
    counts = Counter(name for name, _ in definitions)
    defined = {name for name, count in counts.items() if count == 1}
    points = {}
    for name, expr in definitions:
        match = _CARTESIAN.fullmatch(expr)
        if name in defined and match and (point := _xy(match.groups())) is not None:
            points[name] = point
    for options, path in _DRAW.findall(text):
        if _NON_DRAWING_OR_LOCAL.search(options) or not _CHAIN.fullmatch(path.strip()):
            continue
        names = re.findall(_VERTEX, path)
        if path.rstrip().endswith("cycle"):
            names.append(names[0])
        chain = [tuple(sorted((a,b))) for a,b in zip(names,names[1:])
                 if a in defined and b in defined and a != b
                 and not (a in points and b in points and np.array_equal(points[a], points[b]))]
        edges.update(chain)
        if not re.search(r'\bdotted\b', options):
            style = 'dashed' if re.search(r'\bdashed\b|\bdash pattern\s*=', options) else 'solid'
            styled[style].update(chain)
            if style == 'solid':
                solid_strokes.extend(chain)
    missing = [[a, b] for a, b in required
               if tuple(sorted((a, b))) not in edges and not _has_collinear_chain(a, b, edges, points)]
    styles = [row for row in plan.get('required_styles', [])
              if tuple(row['edge']) not in styled[row['style']]
              and not _has_collinear_chain(*row['edge'],styled[row['style']],points)]
    seen_marks = {(v,tuple(sorted((a,b)))) for a,v,b in re.findall(
        rf'\bright angle\s*=\s*({NAME})\s*--\s*({NAME})\s*--\s*({NAME})',text)}
    marks = [v for v,mark in plan.get('required_marks',{}).items() if (v,tuple(mark['arms'])) not in seen_marks]
    duplicates = _overlapping_strokes(solid_strokes, points)
    result = {"passed": not (missing or styles or marks or duplicates), "missing_edges": missing}
    if styles: result['unverified_styles'] = styles
    if marks: result['unverified_marks'] = marks
    if duplicates: result['overlapping_strokes'] = duplicates
    return result
