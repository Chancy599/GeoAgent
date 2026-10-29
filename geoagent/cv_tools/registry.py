"""Registry of CV tools exposed to the Supervisor.

The Supervisor sees one action, ``call_cv_tool(tool_name, params)``.  Tool
parameters are validated here; a missing/unknown parameter is reported rather
than silently ignored.
"""
from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any, Callable

from .circle_detection import detect_circles, extract_visible_arc, fit_arcs
from .label_detection import bind_point_labels, extract_label_candidates, match_label_templates
from .line_detection import analyze_line_style, detect_lines, merge_collinear_segments_tool
from .right_angle import detect_right_angle_marker
from .text_line_separation import separate_text_and_lines

_TOOLS: dict[str, tuple[Callable[..., dict[str, Any]], str]] = {
    "detect_lines": (
        detect_lines,
        "Detect straight segments; merges collinear fragments. Returns endpoints (px+norm), "
        "length, angle, and heuristic solid/dashed style.",
    ),
    "merge_collinear_segments": (
        merge_collinear_segments_tool,
        "Merge a supplied segment list (or re-detect) into collinear line spans.",
    ),
    "analyze_line_style": (
        analyze_line_style,
        "Classify supplied/auto-detected segments as solid, dashed, or uncertain using gap runs.",
    ),
    "detect_circles": (
        detect_circles,
        "Detect full circles and partial arcs via Hough+RANSAC; returns center, radius, visible ranges.",
    ),
    "fit_arcs": (
        fit_arcs,
        "Fit circular arcs to supplied points or RANSAC skeleton points.",
    ),
    "extract_visible_arc": (
        extract_visible_arc,
        "Given a circle hypothesis (cx, cy, radius), return ordered visible arc samples.",
    ),
    "detect_right_angle_marker": (
        detect_right_angle_marker,
        "Verify drawn right-angle square marks at perpendicular junctions (edges alone are insufficient).",
    ),
    "extract_label_candidates": (
        extract_label_candidates,
        "Extract compact glyph candidates after suppressing long line structures.",
    ),
    "match_label_templates": (
        match_label_templates,
        "Recognise glyph candidates by NCC against CM-like serif templates (best effort).",
    ),
    "bind_point_labels": (
        bind_point_labels,
        "Derive geometric vertices and exclusively bind labels via Hungarian assignment.",
    ),
    "separate_text_and_lines": (
        separate_text_and_lines,
        "Non-destructive text/line separation with competing hypotheses.",
    ),
}

_INJECTED = {"image_path", "out_dir"}


def cv_tool_catalog() -> str:
    lines = ["AVAILABLE CV TOOLS (call via call_cv_tool):"]
    for name, (func, desc) in _TOOLS.items():
        sig = inspect.signature(func)
        params = [
            p.name
            for p in sig.parameters.values()
            if p.name not in _INJECTED and p.default is inspect.Parameter.empty
            and p.kind in (p.POSITIONAL_OR_KEYWORD, p.KEYWORD_ONLY)
        ]
        optional = [
            p.name
            for p in sig.parameters.values()
            if p.name not in _INJECTED and p.default is not inspect.Parameter.empty
        ]
        lines.append(f"- {name}: {desc}")
        lines.append(f"    required params: {params or 'none'}; optional: {optional}")
    lines.append("ROI format: [x0,y0,x1,y1] normalized (0-1) or pixel values > 1. Prefer normalized.")
    return "\n".join(lines)


def CV_TOOL_NAMES() -> list[str]:
    return list(_TOOLS)


def call_cv_tool(
    tool_name: str,
    params: dict[str, Any] | None,
    *,
    image_path: str | Path,
    out_dir: str | Path,
) -> dict[str, Any]:
    if tool_name not in _TOOLS:
        return {
            "ok": False,
            "tool": tool_name,
            "error": f"unknown CV tool; choose one of {list(_TOOLS)}",
        }
    func = _TOOLS[tool_name][0]
    provided = dict(params or {})
    signature = inspect.signature(func)
    allowed = {
        name
        for name, p in signature.parameters.items()
        if name not in _INJECTED and p.kind in (p.POSITIONAL_OR_KEYWORD, p.KEYWORD_ONLY)
    }
    unknown = [key for key in provided if key not in allowed]
    if unknown:
        return {
            "ok": False,
            "tool": tool_name,
            "error": f"unknown parameter(s) {unknown}",
            "allowed_parameters": sorted(allowed),
        }
    kwargs = {key: value for key, value in provided.items() if key in allowed}
    kwargs["image_path"] = image_path
    kwargs.setdefault("out_dir", out_dir)
    try:
        return func(**kwargs)
    except TypeError as exc:
        return {
            "ok": False,
            "tool": tool_name,
            "error": f"invalid parameters: {exc}",
            "allowed_parameters": sorted(allowed),
        }
    except Exception as exc:  # keep the agent loop alive; report the real failure
        return {
            "ok": False,
            "tool": tool_name,
            "error": f"{type(exc).__name__}: {exc}",
        }


CV_TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "call_cv_tool",
            "description": "Run one classical-CV tool (no vision API). " + cv_tool_catalog(),
            "parameters": {
                "type": "object",
                "properties": {
                    "tool_name": {"type": "string", "enum": CV_TOOL_NAMES()},
                    "params": {
                        "type": "object",
                        "description": "Tool-specific parameters (roi, cx, cy, radius, points, ...).",
                    },
                    "purpose": {"type": "string", "description": "Short reason for this call."},
                },
                "required": ["tool_name"],
            },
        },
    }
]
