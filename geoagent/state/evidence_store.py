"""Checkpoint persistence for the Geometric Evidence State."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .schemas import GeometricEvidenceState


class EvidenceStore:
    def __init__(self, run_dir: str | Path):
        self.run_dir = Path(run_dir)
        self.run_dir.mkdir(parents=True, exist_ok=True)
        (self.run_dir / "checkpoints").mkdir(exist_ok=True)

    def save(self, state: GeometricEvidenceState, tag: str = "ges") -> Path:
        path = self.run_dir / f"{tag}.json"
        state.save(path)
        return path

    def checkpoint(self, state: GeometricEvidenceState, step: int) -> Path:
        path = self.run_dir / "checkpoints" / f"step_{step:03d}.json"
        state.save(path)
        return path

    def save_result(self, payload: dict[str, Any]) -> Path:
        path = self.run_dir / "result.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def save_trace(self, state: GeometricEvidenceState) -> Path:
        path = self.run_dir / "trace.json"
        trace = {
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "image_path": state.image_path,
            "actions": [a.model_dump() for a in state.action_history],
            "token_usage": state.token_usage,
            "remaining_budget": state.remaining_budget,
        }
        path.write_text(json.dumps(trace, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def append_event(self, event: dict[str, Any]) -> None:
        path = self.run_dir / "events.jsonl"
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, ensure_ascii=False) + "\n")
