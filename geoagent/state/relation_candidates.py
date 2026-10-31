"""Numerical candidates only: no LLM, reference source, or coordinate mutation."""
from __future__ import annotations

import itertools
import math

RELATION_TYPES = ("parallel", "perpendicular")
DEFAULT_LIMITS = {"angle_deg": 0.5, "relative_distance": 0.005}


def pair_metrics(points, first, second):
    a, b, c, d = [points[n] for n in (*first, *second)]
    u = (b[0]-a[0], b[1]-a[1])
    v = (d[0]-c[0], d[1]-c[1])
    lu, lv = math.hypot(*u), math.hypot(*v)
    span = math.hypot(max(p[0] for p in points.values())-min(p[0] for p in points.values()),
                      max(p[1] for p in points.values())-min(p[1] for p in points.values()))
    if not all(math.isfinite(x) for p in points.values() for x in p) or min(lu,lv,span) <= 1e-12:
        raise ValueError("nonfinite or degenerate geometry")
    if min(lu,lv) <= span*1e-9:
        raise ValueError("degenerate segment")
    angle = math.degrees(math.atan2(abs(u[0]*v[1]-u[1]*v[0]), abs(u[0]*v[0]+u[1]*v[1])))
    return {"parallel_error_deg":angle, "perpendicular_error_deg":90-angle,
            "relative_length_error":abs(lu-lv)/max(lu,lv),
            "relative_line_offset":abs(u[0]*(c[1]-a[1])-u[1]*(c[0]-a[0]))/lu/span,
            "shared_endpoint":bool(set(first)&set(second))}


def accepts(kind, metrics, limits):
    if kind == "parallel":
        return (not metrics["shared_endpoint"] and metrics["parallel_error_deg"] <= limits["angle_deg"]
                and metrics["relative_line_offset"] > limits["relative_distance"])
    if kind == "perpendicular":
        return metrics["perpendicular_error_deg"] <= limits["angle_deg"]
    raise ValueError(f"unsupported relation: {kind}")


def numeric_candidates(geometry, limits=None):
    limits = dict(DEFAULT_LIMITS if limits is None else limits)
    candidates = []
    for first, second in itertools.combinations(sorted(geometry["segments"]), 2):
        try:
            metrics = pair_metrics(geometry["points"], geometry["segments"][first], geometry["segments"][second])
        except ValueError:
            continue
        for kind in RELATION_TYPES:
            if accepts(kind,metrics,limits):
                candidates.append({"type":kind,"segments":[first,second],"metrics":metrics})
    return candidates
