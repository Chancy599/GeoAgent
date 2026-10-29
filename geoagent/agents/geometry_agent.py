"""Geometry subagent: gathers CV evidence and submits consolidated geometry."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..cv_tools.registry import call_cv_tool
from ..llm.client import LLMClient, parse_json_object
from ..state.schemas import EvidenceRecord, GeometricEvidenceState, GeometryObject, Relation
from .base import (
    compact_cv_result,
    compact_json,
    message_to_dict,
    parse_tool_arguments,
    tool_reply,
)
from .prompts import GEOMETRY_SYSTEM
from .schemas import GEOMETRY_TOOLS

ALLOWED_TYPES = {"point", "segment", "line", "circle", "arc", "right_angle", "label", "polygon"}


def merge_geometry_submission(
    state: GeometricEvidenceState,
    submission: dict[str, Any],
    *,
    source: str = "geometry_agent",
) -> dict[str, Any]:
    """Validate and merge a geometry submission into the GES."""
    merged = {"objects": 0, "relations": 0, "conflicts": 0, "rejected": []}
    objects = submission.get("objects") or []
    for raw in objects[:40]:
        if not isinstance(raw, dict):
            continue
        obj_type = str(raw.get("type", "")).lower()
        if obj_type not in ALLOWED_TYPES:
            merged["rejected"].append({"reason": f"bad type {obj_type!r}", "object": raw})
            continue
        try:
            obj = GeometryObject(
                id=str(raw.get("id") or ""),
                type=obj_type,
                label=raw.get("label"),
                coords=raw.get("coords") or {},
                normalized=raw.get("normalized") or {},
                style=raw.get("style") or {},
                source=str(raw.get("source") or source),
                status=str(raw.get("status") or "candidate"),
                confidence=raw.get("confidence"),
                confidence_kind="heuristic-evidence (not a calibrated probability)",
                notes=[str(n) for n in (raw.get("notes") or [])][:6],
                attributes=raw.get("attributes") or {},
            )
            state.add_object(obj, dedupe_by_geometry=bool(obj.id))
            merged["objects"] += 1
        except Exception as exc:
            merged["rejected"].append({"reason": f"{type(exc).__name__}: {exc}", "object": raw})

    for raw in (submission.get("relations") or [])[:40]:
        if not isinstance(raw, dict) or not raw.get("subject") or not raw.get("relation"):
            continue
        state.add_relation(
            Relation(
                id="",
                subject=str(raw["subject"]),
                relation=str(raw["relation"]),
                object=str(raw["object"]) if raw.get("object") else None,
                source=str(raw.get("source") or source),
                evidence=str(raw.get("evidence")) if raw.get("evidence") else None,
                status=str(raw.get("status") or "candidate"),
            )
        )
        merged["relations"] += 1

    for raw in (submission.get("conflicts") or [])[:10]:
        if not isinstance(raw, dict) or not raw.get("topic"):
            continue
        claims = raw.get("claims") if isinstance(raw.get("claims"), list) else []
        state.add_conflict(str(raw["topic"]), claims)
        merged["conflicts"] += 1

    for issue in (submission.get("unresolved") or [])[:12]:
        state.add_unresolved({"source": source, "issue": str(issue)[:400]})

    state.add_evidence(
        source=source,
        method="geometry agent submission",
        summary=str(submission.get("summary", ""))[:1000],
        payload={"merged": merged, "object_ids": [str(o.get("id")) for o in objects[:40]]},
    )
    return merged


class GeometryAgent:
    def __init__(self, client: LLMClient, state: GeometricEvidenceState, out_dir: Path, *, max_calls: int = 6):
        self.client = client
        self.state = state
        self.out_dir = Path(out_dir)
        self.max_calls = max_calls

    def run(
        self,
        instruction: str,
        *,
        cv_calls_left: int = 20,
        image_path: str | Path | None = None,
    ) -> dict[str, Any]:
        state_summary = self.state.summary(max_objects=60, max_chars=9000)
        user_text = (
            f"TASK FROM SUPERVISOR:\n{instruction}\n\n"
            f"CURRENT STATE:\n{state_summary}\n\n"
            "You may run up to "
            f"{min(self.max_calls, max(0, cv_calls_left))} CV tool call(s), then call submit_geometry."
        )
        content: Any = self.client.build_content(user_text, [image_path] if image_path else None)
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": GEOMETRY_SYSTEM},
            {"role": "user", "content": content},
        ]
        cv_used = 0
        submit_error: str | None = None
        token_usage: dict[str, Any] = {}

        for iteration in range(5):
            # Force the submission on the final iteration so the agent cannot keep
            # deliberating until it runs out of iterations without submitting.
            tool_choice: str | dict[str, Any] = "auto"
            if iteration == 4:
                tool_choice = {"type": "function", "function": {"name": "submit_geometry"}}
            result = self.client.chat(
                messages,
                tools=GEOMETRY_TOOLS,
                tag="geometry_agent",
                max_tokens=8192,
                tool_choice=tool_choice,
            )
            token_usage = result.usage
            calls = result.tool_calls
            truncated = (result.finish_reason or "").lower() == "length"
            if not calls:
                text = (result.text or "").strip()
                # A length-stopped reply may contain a half-written JSON object; never
                # treat it as a valid submission even if a prefix happens to parse.
                parsed, err = (None, "response truncated") if truncated else parse_json_object(text)
                if parsed and "objects" in parsed:
                    merged = merge_geometry_submission(self.state, parsed)
                    return {
                        "ok": True,
                        "merged": merged,
                        "summary": str(parsed.get("summary", ""))[:500],
                        "cv_calls": cv_used,
                        "usage": token_usage,
                    }
                messages.append({"role": "assistant", "content": (text or "(empty)")[:6000]})
                if truncated:
                    nudge = (
                        "Your previous response was cut off at the token limit. "
                        "Do not write analysis or prose. Call submit_geometry now with a "
                        "COMPACT JSON object (short summary, essential objects/relations only)."
                    )
                else:
                    nudge = (
                        "Call submit_geometry with the consolidated JSON (key 'objects' "
                        "must be present), or run another CV tool first."
                    )
                messages.append({"role": "user", "content": nudge})
                continue

            messages.append(message_to_dict(result.message))
            submitted = False
            for call in calls:
                name = call.function.name
                args, err = parse_tool_arguments(call)
                if err:
                    messages.append(tool_reply(call.id, name, {"ok": False, "error": err}))
                    continue
                if name == "submit_geometry":
                    payload = args.get("json", args)
                    if isinstance(payload, str):
                        parsed, perr = parse_json_object(payload)
                        if parsed is None:
                            submit_error = perr
                            messages.append(
                                tool_reply(call.id, name, {"ok": False, "error": f"invalid JSON: {perr}"})
                            )
                            continue
                    elif isinstance(payload, dict):
                        parsed = payload
                    else:
                        messages.append(
                            tool_reply(call.id, name, {"ok": False, "error": "json must be a string object"})
                        )
                        continue
                    merged = merge_geometry_submission(self.state, parsed)
                    messages.append(tool_reply(call.id, name, {"ok": True, "merged": merged}))
                    submitted = True
                    return {
                        "ok": True,
                        "merged": merged,
                        "summary": str(parsed.get("summary", ""))[:500],
                        "cv_calls": cv_used,
                        "usage": token_usage,
                    }
                elif name == "call_cv_tool":
                    if cv_used >= min(self.max_calls, cv_calls_left):
                        messages.append(
                            tool_reply(call.id, name, {"ok": False, "error": "CV call budget for this subagent reached"})
                        )
                        continue
                    tool_name = args.get("tool_name", "")
                    params = args.get("params") or {}
                    if "out_dir" in params:
                        params = {k: v for k, v in params.items() if k != "out_dir"}
                    reply = call_cv_tool(tool_name, params, image_path=self.state.image_path, out_dir=self.out_dir)
                    cv_used += 1
                    from ..orchestration.ingest import ingest_cv_result

                    ingest_cv_result(self.state, tool_name, params, reply)
                    messages.append(tool_reply(call.id, name, compact_cv_result(reply, tool_name), limit=7000))
                else:
                    messages.append(tool_reply(call.id, name, {"ok": False, "error": f"unknown tool {name}"}))
            if submitted:
                break

        return {
            "ok": False,
            "merged": {"objects": 0},
            "summary": "geometry agent did not submit",
            "error": submit_error or "no submission",
            "cv_calls": cv_used,
            "usage": token_usage,
        }
