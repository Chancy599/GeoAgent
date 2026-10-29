"""Opt-in live end-to-end test (real model + real compiler).

Run with:  $env:GEOAGENT_LIVE=1; python -m pytest tests/test_e2e_live.py -q
It spends real tokens, so it is skipped by default.
"""
from __future__ import annotations

import os

import pytest

from geoagent.orchestration import GeoAgentRunner

pytestmark = pytest.mark.skipif(
    os.environ.get("GEOAGENT_LIVE") != "1",
    reason="set GEOAGENT_LIVE=1 to run a real model end-to-end test",
)


def test_live_semicircle_end_to_end(settings, semicircle_item, tmp_path) -> None:
    runner = GeoAgentRunner(
        str(semicircle_item.image_path),
        run_overrides={
            "max_steps": 12,
            "max_tool_calls": 24,
            "max_visual_calls": 2,
            "max_total_tokens": 250_000,
            "timeout_seconds": 600,
        },
        run_dir=tmp_path / "live_run",
        on_event=lambda event: None,
    )
    result = runner.run()

    assert result["status"] in {"success", "partial"}
    assert result["counts"]["tikz_versions"] >= 1
    assert result["best_png_path"], "expected a compiled and rendered figure"
    assert result["best_tex"] and "tikzpicture" in result["best_tex"]
