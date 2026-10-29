"""TikZ subagent: generate or repair a standalone LaTeX/TikZ document."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..llm.client import LLMClient, parse_json_object
from ..state.schemas import GeometricEvidenceState
from .base import compact_json, message_to_dict, parse_tool_arguments, tool_reply
from .prompts import TIKZ_SYSTEM
from .schemas import TIKZ_TOOLS


def _geometry_digest(state: GeometricEvidenceState, limit: int = 8000) -> str:
    lines: list[str] = []
    for obj in list(state.objects.values())[:60]:
        piece = obj.type
        if obj.label:
            piece += f" {obj.label}"
        piece += f" | coords={compact_json(obj.coords, 300)}"
        if obj.style:
            piece += f" | style={compact_json(obj.style, 160)}"
        piece += f" | {obj.status}"
        lines.append(piece)
    text = "\n".join(lines) or "(no geometry objects yet)"
    return text[:limit]


class TikZAgent:
    def __init__(self, client: LLMClient, state: GeometricEvidenceState, out_dir: Path):
        self.client = client
        self.state = state
        self.out_dir = Path(out_dir)

    def run(
        self,
        mode: str,
        instruction: str,
        *,
        image_path: str | Path | None = None,
    ) -> dict[str, Any]:
        previous_tex = ""
        errors: list[str] = []
        warnings: list[str] = []
        critic_issues: list[dict[str, Any]] = []
        latest = self.state.latest_version()
        if latest is not None:
            previous_tex = latest.tex
            errors = latest.errors
            warnings = latest.warnings
            if latest.critic_report:
                critic_issues = latest.critic_report.get("issues", []) or []

        parts = [
            f"MODE: {mode}",
            f"INSTRUCTION: {instruction}",
            f"IMAGE SIZE (pixels): {self.state.image_size}",
            "GEOMETRY OBJECTS:",
            _geometry_digest(self.state),
            "RELATIONS: " + compact_json({k: rel.model_dump() for k, rel in list(self.state.relations.items())[:30]}, 2500),
        ]
        if mode == "repair":
            parts += [
                "PREVIOUS TIKZ (full source to fix):",
                "```latex\n" + previous_tex[:20000] + "\n```",
                "COMPILER ERRORS: " + compact_json(errors, 3000),
                "COMPILER WARNINGS: " + compact_json(warnings, 1200),
                "CRITIC ISSUES: " + compact_json(critic_issues, 3000),
                "Return the complete corrected document via submit_tikz.",
            ]
        else:
            parts.append("Write the complete standalone document via submit_tikz.")

        images = [image_path] if image_path else None
        content: Any = self.client.build_content("\n\n".join(parts), images)
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": TIKZ_SYSTEM},
            {"role": "user", "content": content},
        ]
        usage: dict[str, Any] = {}

        for _ in range(3):
            result = self.client.chat(messages, tools=TIKZ_TOOLS, tag=f"tikz_agent:{mode}", max_tokens=4096)
            usage = result.usage
            calls = result.tool_calls
            if calls:
                messages.append(message_to_dict(result.message))
                for call in calls:
                    name = call.function.name
                    args, err = parse_tool_arguments(call)
                    if name != "submit_tikz" or err or not args:
                        messages.append(tool_reply(call.id, name, {"ok": False, "error": err or "expected submit_tikz"}))
                        continue
                    tex = str(args.get("tex") or "").strip()
                    notes = str(args.get("notes") or "")
                    if "\\begin{tikzpicture}" not in tex and "\\documentclass" not in tex:
                        messages.append(
                            tool_reply(call.id, name, {"ok": False, "error": "tex contains no tikzpicture/documentclass"})
                        )
                        continue
                    messages.append(tool_reply(call.id, name, {"ok": True, "chars": len(tex)}))
                    return {"ok": True, "tex": tex, "notes": notes, "usage": usage}
                continue

            text = (result.text or "").strip()
            parsed, _err = parse_json_object(text)
            tex = ""
            notes = ""
            if isinstance(parsed, dict) and parsed.get("tex"):
                tex = str(parsed["tex"])
                notes = str(parsed.get("notes", ""))
            elif "\\begin{tikzpicture}" in text or "\\documentclass" in text:
                tex = text.strip("`").strip()
                if tex.lower().startswith("latex"):
                    tex = tex[5:].strip()
            if tex:
                return {"ok": True, "tex": tex, "notes": notes or "recovered from plain reply", "usage": usage}
            messages.append({"role": "assistant", "content": text or "(empty)"})
            messages.append(
                {"role": "user", "content": "Please call submit_tikz with the full LaTeX document."}
            )

        return {"ok": False, "tex": None, "notes": "", "error": "no TikZ submission", "usage": usage}
