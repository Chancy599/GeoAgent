"""Critic subagent: compare the original figure with the latest render."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ..llm.client import LLMClient
from ..state.schemas import GeometricEvidenceState
from .base import compact_json
from .prompts import CRITIC_SYSTEM

ISSUE_TYPES = {
    "missing_element",
    "wrong_position",
    "wrong_style",
    "label_error",
    "arc_error",
    "layout_error",
    "other",
}
SEVERITIES = {"high", "medium", "low"}


def _sanitise(report: dict[str, Any]) -> dict[str, Any]:
    try:
        score = float(report.get("assessment_score", 0.0))
    except (TypeError, ValueError):
        score = 0.0
    score = max(0.0, min(1.0, score))
    issues = []
    for raw in (report.get("issues") or [])[:12]:
        if not isinstance(raw, dict):
            continue
        issue_type = str(raw.get("type", "other"))
        severity = str(raw.get("severity", "medium"))
        issues.append(
            {
                "type": issue_type if issue_type in ISSUE_TYPES else "other",
                "severity": severity if severity in SEVERITIES else "medium",
                "description": str(raw.get("description", ""))[:500],
                "suggestion": str(raw.get("suggestion", ""))[:500],
            }
        )
    labels = report.get("labels") if isinstance(report.get("labels"), dict) else {}
    return {
        "assessment_score": round(score, 3),
        "score_kind": "heuristic visual similarity (not a calibrated probability)",
        "verdict": str(report.get("verdict", ""))[:300],
        "figure_type": report.get("figure_type") if isinstance(report.get("figure_type"), dict) else {},
        "issues": issues,
        "matches": [str(m)[:200] for m in (report.get("matches") or [])[:12]],
        "labels": {
            "present": [str(x) for x in (labels.get("present") or [])][:20],
            "missing": [str(x) for x in (labels.get("missing") or [])][:20],
            "extra": [str(x) for x in (labels.get("extra") or [])][:20],
        },
    }


class CriticAgent:
    def __init__(self, client: LLMClient, state: GeometricEvidenceState):
        self.client = client
        self.state = state

    def run(
        self,
        original_image: str | Path,
        render_png: str | Path,
        *,
        focus: str = "",
        version: int | None = None,
    ) -> dict[str, Any]:
        summary = self.state.summary(max_objects=30, max_chars=5000)
        user = (
            "ORIGINAL IMAGE is the first image; RENDERED TIKZ is the second image.\n"
            f"FOCUS: {focus or 'overall faithfulness'}\n"
            f"VERSION: {version}\n"
            f"GEOMETRY STATE (for reference):\n{summary}\n\n"
            "Return only the JSON critique."
        )
        report = self.client.complete_json(
            CRITIC_SYSTEM,
            user,
            images=[original_image, render_png],
            tag="critic_agent",
            max_tokens=4096,
        )
        clean = _sanitise(report)
        clean["version"] = version
        clean["raw_meta"] = compact_json(
            {k: v for k, v in report.items() if k not in clean}, 1000
        )
        return clean
