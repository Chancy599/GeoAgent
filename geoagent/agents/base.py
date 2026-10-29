"""Shared helpers for the agent wrappers."""
from __future__ import annotations

import json
from typing import Any

from ..llm.client import LLMClient


def message_to_dict(message: Any) -> dict[str, Any]:
    """Convert an SDK message object into a plain dict for the next request."""
    if isinstance(message, dict):
        return message
    if hasattr(message, "model_dump"):
        data = message.model_dump(exclude_none=True)
    else:  # pragma: no cover - defensive
        data = {
            "role": "assistant",
            "content": getattr(message, "content", None),
        }
        tool_calls = getattr(message, "tool_calls", None)
        if tool_calls:
            data["tool_calls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {"name": call.function.name, "arguments": call.function.arguments},
                }
                for call in tool_calls
            ]
    data.setdefault("role", "assistant")
    if data.get("content") is None and not data.get("tool_calls"):
        data["content"] = ""
    return data


def parse_tool_arguments(call: Any) -> tuple[dict[str, Any] | None, str | None]:
    raw = getattr(getattr(call, "function", None), "arguments", None)
    if raw in (None, ""):
        return {}, None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        return None, f"invalid JSON arguments: {exc}"
    if not isinstance(parsed, dict):
        return None, f"arguments must be an object, got {type(parsed).__name__}"
    return parsed, None


def compact_json(value: Any, limit: int = 9000) -> str:
    text = json.dumps(value, ensure_ascii=False, default=str)
    if len(text) <= limit:
        return text
    return text[:limit] + f"...[truncated {len(text) - limit} chars]"


def tool_reply(tool_call_id: str, name: str, payload: Any, *, limit: int = 9000) -> dict[str, Any]:
    return {
        "role": "tool",
        "tool_call_id": tool_call_id,
        "name": name,
        "content": compact_json(payload, limit) if not isinstance(payload, str) else payload[:limit],
    }


def visual_calls_used(client: LLMClient) -> int:
    return int(client.usage_summary()["totals"].get("visual_calls", 0))


def total_tokens_used(client: LLMClient) -> int:
    return int(client.usage_summary()["totals"].get("total_tokens", 0))


def compact_cv_result(result: dict[str, Any], tool_name: str) -> dict[str, Any]:
    """Strip bulk from CV payloads before feeding them back to an LLM."""
    payload = result.get("results", {})
    out: dict[str, Any] = {
        "ok": result.get("ok"),
        "tool": tool_name,
        "count": payload.get("count"),
        "notes": result.get("notes", [])[:4],
    }
    if not result.get("ok"):
        out["error"] = result.get("error")
        return out
    if tool_name in ("detect_lines", "merge_collinear_segments", "analyze_line_style"):
        out["segments"] = [
            {
                "id": seg.get("id"),
                "a_px": seg.get("a_px"),
                "b_px": seg.get("b_px"),
                "length_px": seg.get("length_px"),
                "angle_deg": seg.get("angle_deg"),
                "style": seg.get("style"),
                "style_notes": seg.get("style_notes"),
            }
            for seg in payload.get("segments", [])[:20]
        ]
    elif tool_name in ("detect_circles", "fit_arcs", "extract_visible_arc"):
        out["circles"] = [
            {
                "id": circ.get("id"),
                "center_px": circ.get("center_px"),
                "radius_px": circ.get("radius_px"),
                "visible_ranges_deg": circ.get("visible_ranges_deg"),
                "visible_span_deg": circ.get("visible_span_deg"),
                "full_circle": circ.get("full_circle"),
                "ink_coverage": circ.get("ink_coverage"),
            }
            for circ in payload.get("circles", [])[:6]
        ]
        if "samples" in payload:
            out["sample_count"] = len(payload.get("samples") or [])
    elif tool_name == "detect_right_angle_marker":
        out["markers"] = payload.get("markers", [])[:6]
        out["perpendicular_without_mark"] = payload.get("perpendicular_without_mark", [])[:6]
    elif tool_name in ("extract_label_candidates", "match_label_templates"):
        items = payload.get("labels") or payload.get("matches") or []
        out["labels"] = [
            {
                "id": lab.get("id"),
                "chosen": lab.get("chosen"),
                "box_px": lab.get("box_px"),
                "centroid_px": lab.get("centroid_px"),
                "top": (lab.get("top") or [])[:3],
                "ambiguous": lab.get("ambiguous"),
                "possible_point_marker": lab.get("possible_point_marker"),
            }
            for lab in items[:20]
        ]
    elif tool_name == "bind_point_labels":
        out["bindings"] = payload.get("bindings", [])[:20]
        out["points"] = payload.get("points", [])[:20]
        out["unmatched_labels"] = payload.get("unmatched_labels")
        out["unmatched_points"] = payload.get("unmatched_points")
    else:
        out["results"] = payload
    return out
