"""Supervisor prompt construction."""
from __future__ import annotations

from ..state.schemas import GeometricEvidenceState
from .prompts import SUPERVISOR_SYSTEM


def initial_messages(state: GeometricEvidenceState) -> list[dict]:
    task = (
        "TASK: Reconstruct this geometry figure as compilable LaTeX/TikZ.\n"
        f"IMAGE: {state.image_path}\n"
        f"IMAGE SIZE (pixels): {state.image_size['width']}x{state.image_size['height']}\n"
        "The reference LaTeX is NOT available to you. Drive the run with tool calls; "
        "call finish when a compiled figure exists (ideally critic-reviewed) or when blocked.\n\n"
        f"STATE AT START:\n{state.summary()}"
    )
    return [
        {"role": "system", "content": SUPERVISOR_SYSTEM},
        {"role": "user", "content": task},
    ]


def step_nudge(state: GeometricEvidenceState) -> str:
    return (
        "No tool call detected. Reply with exactly one tool call. If you are done, call finish.\n"
        f"CURRENT STATE:\n{state.summary(max_objects=30, max_chars=4500)}"
    )
