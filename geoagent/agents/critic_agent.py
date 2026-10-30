"""Critic subagent: compare the original figure with the latest render.

The two figures are composed into one side-by-side image with identically
sized panels, so the model compares shapes at the same scale instead of
guessing across different resolutions.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

from ..llm.client import LLMClient
from ..state.schemas import GeometricEvidenceState
from .base import compact_json
from .prompts import CRITIC_SYSTEM

# Two 620 px panels + 12 px separator = 1252 px, inside the default 1280 px
# image_max_dim, so the client does not downscale the composite again.
PANEL_PX = 620
GAP_PX = 12
_SEPARATOR = (225, 225, 225)

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


def build_comparison_image(
    original: str | Path,
    render: str | Path,
    out_path: str | Path,
    *,
    panel_px: int = PANEL_PX,
    gap_px: int = GAP_PX,
) -> Path:
    """Compose LEFT=original, RIGHT=render into equally sized square panels.

    Each figure is scaled to fit inside its panel (longest side = panel_px) and
    centred, so both are compared at the same visual scale.
    """
    panel_px = max(64, int(panel_px))
    gap_px = max(2, int(gap_px))
    canvas = Image.new("RGB", (2 * panel_px + gap_px, panel_px), (255, 255, 255))
    ImageDraw.Draw(canvas).rectangle(
        [panel_px, 0, panel_px + gap_px - 1, panel_px - 1], fill=_SEPARATOR
    )
    for index, path in enumerate((original, render)):
        with Image.open(path) as im:
            im = im.convert("RGB")
            scale = min(panel_px / im.width, panel_px / im.height)
            size = (max(1, round(im.width * scale)), max(1, round(im.height * scale)))
            scaled = im.resize(size, Image.Resampling.LANCZOS)
        x0 = index * (panel_px + gap_px) + (panel_px - size[0]) // 2
        y0 = (panel_px - size[1]) // 2
        canvas.paste(scaled, (x0, y0))
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out, format="PNG")
    return out


class CriticAgent:
    def __init__(
        self,
        client: LLMClient,
        state: GeometricEvidenceState,
        out_dir: str | Path | None = None,
    ):
        self.client = client
        self.state = state
        self.out_dir = Path(out_dir) if out_dir else None

    def run(
        self,
        original_image: str | Path,
        render_png: str | Path,
        *,
        focus: str = "",
        version: int | None = None,
    ) -> dict[str, Any]:
        comparison: Path | None = None
        if self.out_dir is not None:
            try:
                comparison = build_comparison_image(
                    original_image,
                    render_png,
                    self.out_dir / "critic" / f"compare_v{version or 0}.png",
                )
            except Exception:
                comparison = None
        if comparison is not None:
            images = [comparison]
            layout = (
                "SINGLE IMAGE: a side-by-side comparison. The LEFT panel is the "
                "ORIGINAL figure; the RIGHT panel is the RENDERED TIKZ output. "
                "Both panels have the same pixel size and the same scale."
            )
        else:
            images = [original_image, render_png]
            layout = "ORIGINAL IMAGE is the first image; RENDERED TIKZ is the second image."

        summary = self.state.summary(max_objects=30, max_chars=5000)
        user = (
            f"{layout}\n"
            f"FOCUS: {focus or 'overall faithfulness'}\n"
            f"VERSION: {version}\n"
            f"GEOMETRY STATE (for reference):\n{summary}\n\n"
            "Return only the JSON critique."
        )
        report = self.client.complete_json(
            CRITIC_SYSTEM,
            user,
            images=images,
            tag="critic_agent",
            max_tokens=4096,
        )
        clean = _sanitise(report)
        clean["version"] = version
        clean["raw_meta"] = compact_json(
            {k: v for k, v in report.items() if k not in clean}, 1000
        )
        return clean
