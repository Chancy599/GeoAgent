from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app.py"


def test_app_starts_and_lists_dataset() -> None:
    at = AppTest.from_file(str(APP), default_timeout=120).run()
    assert not at.exception, [exc.value for exc in at.exception]
    titles = [title.value for title in at.title]
    assert any("GeoAgent" in title for title in titles)
    sample = at.sidebar.selectbox[0]
    assert len(sample.options) >= 100
    assert "1035_q_fig1" in sample.options[0]


def test_result_tabs_render_from_session_state(tmp_path) -> None:
    run_dir = tmp_path / "run"
    (run_dir / "tikz" / "v1").mkdir(parents=True)
    png = run_dir / "tikz" / "v1" / "v1.png"
    image = Image.new("RGB", (480, 320), "white")
    ImageDraw.Draw(image).line((40, 280, 440, 280), fill="black", width=2)
    ImageDraw.Draw(image).arc((40, 60, 440, 300), 180, 360, fill="black", width=2)
    image.save(png)

    tex = "\\documentclass[tikz]{standalone}\\begin{document}\\begin{tikzpicture}\\draw (0,0)--(1,0);\\end{tikzpicture}\\end{document}"
    state = {
        "image_path": str(ROOT / "data" / "test" / "image" / "1035_q_fig1.png"),
        "image_size": {"width": 574, "height": 367},
        "objects": {},
        "relations": {},
        "evidence": {},
        "conflicts": [],
        "unresolved_issues": [],
        "label_bindings": {},
        "tikz_versions": [
            {
                "version": 1,
                "tex": tex,
                "ok": True,
                "png_path": str(png),
                "errors": [],
                "critic_score": 0.9,
                "critic_report": {"assessment_score": 0.9, "verdict": "good", "issues": []},
            }
        ],
        "best_version": 1,
        "best_score": 0.9,
        "action_history": [],
        "token_usage": {},
    }
    (run_dir / "state.json").write_text(json.dumps(state), encoding="utf-8")
    result = {
        "run_dir": str(run_dir),
        "image_path": state["image_path"],
        "status": "success",
        "best_version": 1,
        "best_score": 0.9,
        "usage": {"totals": {"total_tokens": 1234}},
        "elapsed_s": 1.0,
        "summary": "unit-test run",
    }

    at = AppTest.from_file(str(APP), default_timeout=120)
    at.session_state["run_result"] = result
    at.session_state["run_dir"] = str(run_dir)
    at.session_state["ges"] = state
    at.session_state["events"] = []
    at.run()

    assert not at.exception, [exc.value for exc in at.exception]
    assert [tab.label for tab in at.tabs] == ["图像与 CV", "TikZ", "Agent 轨迹", "GES", "参考"]
    labels = {metric.label: metric.value for metric in at.metric}
    assert labels["状态"] == "success"
    assert labels["最佳版本"] == "v1"
    assert "下载 .tex" in [button.label for button in at.get("download_button")]
