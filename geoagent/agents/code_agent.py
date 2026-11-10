"""Code Agent: generate or repair a standalone LaTeX/TikZ document."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..llm.client import LLMClient, parse_json_object
from ..state.schemas import GeometricEvidenceState
from .base import compact_json, message_to_dict, parse_tool_arguments, tool_reply
from .prompts import CODE_SYSTEM
from .schemas import TIKZ_TOOLS
from ..state.measured_topology import topology_block
from ..state.coordinate_contract import (
    apply_coordinate_contract, build_coordinate_contract, contract_prompt, coordinate_frame,
)


def _complete_document(tex: str) -> bool:
    """A submission must be a standalone document, not a bare snippet."""
    lowered = tex.lower()
    return (
        "\\documentclass" in lowered
        and "\\begin{document}" in lowered
        and "\\begin{tikzpicture}" in lowered
        and "\\end{tikzpicture}" in lowered
        and "\\end{document}" in lowered
    )


def _geometry_digest(state: GeometricEvidenceState, limit: int = 8000, measured_labels=()) -> str:
    lines: list[str] = []
    for obj in list(state.objects.values())[:60]:
        if obj.type == 'point' and obj.label in measured_labels:
            continue
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


class CodeAgent:
    def __init__(self, client: LLMClient, state: GeometricEvidenceState, out_dir: Path):
        self.client = client
        self.state = state
        self.out_dir = Path(out_dir)
        self._style_cache: dict[str, Any] | None = None

    def _style_metrics(self) -> dict[str, Any] | None:
        """Measure source stroke/label sizes once per agent instance."""
        if self._style_cache is not None:
            return self._style_cache or None
        metrics: dict[str, Any] = {}
        try:
            from ..cv_tools.label_detection import measure_style_metrics

            measured = measure_style_metrics(self.state.image_path)
            if measured.get("ok"):
                metrics = measured
        except Exception:
            metrics = {}
        self._style_cache = metrics
        return metrics or None

    @staticmethod
    def _style_block(metrics: dict[str, Any]) -> str:
        width, height = metrics["ink_size_px"]
        span = metrics["target_span_units"]
        return (
            "STYLE METRICS (CV-measured from the original; prefer these over defaults):\n"
            f"- Ink bbox {width}x{height} px; longest side {metrics['span_px']} px.\n"
            f"- Stroke width {metrics['stroke_width_px']} px -> line width={metrics['line_width_pt']}pt "
            f"at a span of {span:g} units (cm).\n"
            f"- Label cap height {metrics['cap_height_px']} px -> "
            f"font=\\fontsize{{{metrics['label_font_pt']:g}}}{{{metrics['label_line_pt']:g}}}\\selectfont "
            "on every label node.\n"
            f"- Scale: s={metrics['suggested_scale']} units per pixel so the longest side spans {span:g} units.\n"
            "- Keep these proportions unless a critic issue explicitly targets stroke weight or label size."
        )

    def run(
        self,
        mode: str,
        instruction: str,
        *,
        image_path: str | Path | None = None,
        preserve_cv_coordinates: bool = True,
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
            last_report = next((v.critic_report for v in reversed(self.state.tikz_versions) if v.critic_report), {})
            critic_issues = last_report.get("issues", []) or []

        metrics = self._style_metrics()
        contract = build_coordinate_contract(self.state, metrics) if preserve_cv_coordinates else None
        previous_contract = self.state.meta.get('tikz_coordinate_contracts', {}).get(
            str(latest.version) if latest else '', {}
        ).get('coordinates', {})
        frame_changed = bool(contract and latest and any(
            previous_contract.get(key) != contract[key] for key in ('scale', 'origin_px')
        ))
        parts = [
            f"MODE: {mode}",
            f"INSTRUCTION: {instruction}",
            f"IMAGE SIZE (pixels): {self.state.image_size}",
            "GEOMETRY OBJECTS:",
            _geometry_digest(self.state, measured_labels=contract['points'] if contract else ()),
            topology_block(self.state),
            "RELATIONS: " + compact_json({k: rel.model_dump() for k, rel in list(self.state.relations.items())[:30]}, 2500),
        ]
        required_edges = self.state.meta.get("topology_plan", {}).get("required_edges", [])
        if required_edges:
            parts.append("REQUIRED NAMED EDGES: " + json.dumps(required_edges))
        construction = self.state.meta.get('source_construction', {})
        if construction:
            plan = self.state.meta.get('topology_plan', {})
            parts.append('SOURCE CONSTRUCTION VERIFIED BEFORE GENERATION:\n'
                         + construction['summary'] + '\nREQUIRED STYLES: ' + json.dumps(plan.get('required_styles', []))
                         + '\nREQUIRED RIGHT-ANGLE PIC RAYS: ' + json.dumps(plan.get('required_marks', {})))
        if metrics:
            parts.append(self._style_block(metrics))
        if preserve_cv_coordinates:
            scale, (cx, cy) = coordinate_frame(self.state, metrics)
            parts.append(
                f"SOURCE COORDINATE FRAME: For every point (including unbound points) use "
                f"x=(px_x-{cx})*{scale}, y=({cy}-px_y)*{scale}. "
                "Do not translate or rescale this frame."
            )
        if contract:
            parts.append(contract_prompt(contract))
        if mode == "repair":
            if frame_changed:
                parts.append(
                    "The program has introduced a new coordinate frame since the previous render. "
                    "Reconstruct ALL coordinates from the original and pixel evidence in the frame above. "
                    "Previous coordinate numbers in instructions or Critic issues are stale."
                )
            else:
                parts += ["PREVIOUS TIKZ (full source to fix):", "```latex\n" + previous_tex[:20000] + "\n```"]
            parts += [
                "COMPILER ERRORS: " + compact_json(errors, 3000),
                "COMPILER WARNINGS: " + compact_json(warnings, 1200),
                "CRITIC ISSUES: " + compact_json(critic_issues, 3000),
                "CORRECTED SOURCE BINDINGS (use these vertices in actual paths and labels): "
                + compact_json(self.state.meta.get("reviewed_bindings", {}), 2000),
                "UNVERIFIED NAMED EDGES: " + json.dumps(
                    (latest.topology_check or {}).get("missing_edges", []) if latest else []
                ),
                "Return the complete corrected document via submit_tikz.",
            ]
        else:
            parts.append("Write the complete standalone document via submit_tikz.")

        images = [image_path] if image_path else None
        content: Any = self.client.build_content("\n\n".join(parts), images)
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": CODE_SYSTEM},
            {"role": "user", "content": content},
        ]
        usage: dict[str, Any] = {}

        for _ in range(3):
            result = self.client.chat(messages, tools=TIKZ_TOOLS, tag=f"code_agent:{mode}", max_tokens=4096)
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
                    if not _complete_document(tex):
                        messages.append(
                            tool_reply(
                                call.id,
                                name,
                                {
                                    "ok": False,
                                    "error": (
                                        "tex must be a COMPLETE standalone document: "
                                        "\\documentclass, \\begin{document}, \\begin{tikzpicture}, "
                                        "\\end{tikzpicture}, \\end{document}"
                                    ),
                                },
                            )
                        )
                        continue
                    try:
                        tex, coordinate_audit = apply_coordinate_contract(tex, contract)
                    except ValueError as exc:
                        messages.append(tool_reply(call.id, name, {"ok": False, "error": str(exc)}))
                        continue
                    messages.append(tool_reply(call.id, name, {"ok": True, "chars": len(tex)}))
                    return {"ok": True, "tex": tex, "notes": notes, "usage": usage, "coordinate_contract": coordinate_audit}
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
                start = tex.find("\\documentclass")
                end = tex.rfind("\\end{document}")
                if start >= 0 and end > start:
                    tex = tex[start: end + len("\\end{document}")].strip()
                else:
                    start = tex.find("\\begin{tikzpicture}")
                    end = tex.rfind("\\end{tikzpicture}")
                    if start >= 0 and end > start:
                        tex = tex[start: end + len("\\end{tikzpicture}")].strip()
            if tex and _complete_document(tex):
                try:
                    tex, coordinate_audit = apply_coordinate_contract(tex, contract)
                except ValueError as exc:
                    messages.append({"role": "assistant", "content": text})
                    messages.append({"role": "user", "content": str(exc)+'. Submit the full document again.'})
                    continue
                return {"ok": True, "tex": tex, "notes": notes or "recovered from plain reply", "usage": usage,
                        "coordinate_contract": coordinate_audit}
            if tex:
                messages.append({"role": "assistant", "content": text[:6000]})
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "That is not a complete standalone document. Call submit_tikz with the "
                            "FULL document (\\documentclass ... \\begin{document} ... \\end{document}) "
                            "as one string, no markdown fences, no prose."
                        ),
                    }
                )
                continue
            messages.append({"role": "assistant", "content": text or "(empty)"})
            messages.append(
                {"role": "user", "content": "Please call submit_tikz with the full LaTeX document."}
            )

        return {"ok": False, "tex": None, "notes": "", "error": "no TikZ submission", "usage": usage}
