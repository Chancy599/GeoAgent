from __future__ import annotations

import json
from pathlib import Path

from geoagent.archive import archive_and_clean


def _make_run(tmp_path: Path, stem: str = "1266_s_fig1") -> tuple[Path, dict]:
    run = tmp_path / "runs" / "20260101_000000_1266_s_fig1"
    tikz = run / "tikz" / "v1"
    tikz.mkdir(parents=True)
    (tikz / "figure.tex").write_text("% tex", encoding="utf-8")
    (tikz / "figure.pdf").write_bytes(b"%PDF")
    (tikz / "figure.png").write_bytes(b"png")
    (run / "events.jsonl").write_text("{}\n", encoding="utf-8")
    (run / "llm_calls.jsonl").write_text("{}\n", encoding="utf-8")
    state = {
        "tikz_versions": [
            {
                "version": 1,
                "tex": "% tex",
                "tex_path": str(tikz / "figure.tex"),
                "pdf_path": str(tikz / "figure.pdf"),
                "png_path": str(tikz / "figure.png"),
                "critic_report": {"score": 0.93},
            }
        ]
    }
    (run / "state.json").write_text(json.dumps(state), encoding="utf-8")
    result = {
        "run_dir": str(run),
        "image_path": str(tmp_path / "image" / f"{stem}.png"),
        "status": "success",
        "best_version": 1,
        "best_tex_path": str(tikz / "figure.tex"),
        "best_png_path": str(tikz / "figure.png"),
        "best_tex": "% tex",
    }
    return run, result


def test_archive_copies_best_artifacts_and_removes_run_dir(tmp_path: Path) -> None:
    run, result = _make_run(tmp_path)
    archived = archive_and_clean(result, archive_root=tmp_path / "ours")

    target = tmp_path / "ours" / "stem" / "1266_s_fig1"
    for name in ("best.tex", "best.pdf", "best.png", "result.json", "state.json", "events.jsonl", "llm_calls.jsonl", "critic_report.json"):
        assert (target / name).is_file(), name
    assert json.loads((target / "critic_report.json").read_text(encoding="utf-8")) == {"score": 0.93}
    assert (tmp_path / "ours" / "latex" / "1266_s_fig1.tex").read_bytes() == (target / "best.tex").read_bytes()
    assert (tmp_path / "ours" / "image" / "1266_s_fig1.png").read_bytes() == (target / "best.png").read_bytes()
    assert not run.exists()

    assert archived["run_dir"] == str(target)
    assert archived["best_tex_path"] == str(target / "best.tex")
    assert archived["best_png_path"] == str(target / "best.png")
    saved = json.loads((target / "result.json").read_text(encoding="utf-8"))
    assert saved["run_dir"] == str(target)


def test_archive_writes_best_tex_from_result_when_file_missing(tmp_path: Path) -> None:
    run, result = _make_run(tmp_path)
    state = {"tikz_versions": [{"version": 1, "tex": "% fallback"}]}
    (run / "state.json").write_text(json.dumps(state), encoding="utf-8")
    result["best_tex_path"] = None
    result["best_png_path"] = None
    result["best_tex"] = "% fallback"
    archived = archive_and_clean(result, archive_root=tmp_path / "ours")

    target = tmp_path / "ours" / "stem" / "1266_s_fig1"
    assert (target / "best.tex").read_text(encoding="utf-8") == "% fallback"
    assert not (target / "best.png").exists()
    assert (tmp_path / "ours" / "latex" / "1266_s_fig1.tex").is_file()
    assert not (tmp_path / "ours" / "image" / "1266_s_fig1.png").exists()
    assert archived["best_tex_path"] == str(target / "best.tex")


def _make_second_run(tmp_path: Path, stem: str, *, critic_report: dict | None) -> dict:
    run = tmp_path / "runs" / f"20260102_000000_{stem}"
    tikz = run / "tikz" / "v2"
    tikz.mkdir(parents=True)
    (tikz / "figure.tex").write_text("% v2", encoding="utf-8")
    version = {"version": 2, "tex": "% v2", "tex_path": str(tikz / "figure.tex")}
    if critic_report is not None:
        version["critic_report"] = critic_report
    (run / "state.json").write_text(json.dumps({"tikz_versions": [version]}), encoding="utf-8")
    return {
        "run_dir": str(run),
        "image_path": str(tmp_path / "image" / f"{stem}.png"),
        "best_version": 2,
        "best_tex": "% v2",
    }


def test_archive_replaces_stale_critic_report_on_rerun(tmp_path: Path) -> None:
    _run, result = _make_run(tmp_path)
    archive_and_clean(result, archive_root=tmp_path / "ours")

    result2 = _make_second_run(tmp_path, "1266_s_fig1", critic_report={"score": 0.71})
    archive_and_clean(result2, archive_root=tmp_path / "ours")

    target = tmp_path / "ours" / "stem" / "1266_s_fig1"
    assert json.loads((target / "critic_report.json").read_text(encoding="utf-8")) == {"score": 0.71}
    assert (target / "best.tex").read_text(encoding="utf-8") == "% v2"


def test_archive_drops_stale_critic_report_when_rerun_has_none(tmp_path: Path) -> None:
    _run, result = _make_run(tmp_path)
    archive_and_clean(result, archive_root=tmp_path / "ours")

    result2 = _make_second_run(tmp_path, "1266_s_fig1", critic_report=None)
    archive_and_clean(result2, archive_root=tmp_path / "ours")

    assert not (tmp_path / "ours" / "stem" / "1266_s_fig1" / "critic_report.json").exists()


def test_archive_keeps_run_dir_when_nothing_was_archived(tmp_path: Path) -> None:
    run = tmp_path / "runs" / "empty"
    run.mkdir(parents=True)
    result = {
        "run_dir": str(run),
        "image_path": str(tmp_path / "image" / "empty.png"),
        "best_version": 1,
        "best_tex": None,
    }
    archived = archive_and_clean(result, archive_root=tmp_path / "ours")

    assert run.is_dir()
    assert archived["run_dir"] == str(tmp_path / "ours" / "stem" / "empty")


def test_archive_refuses_to_delete_data_directory(tmp_path: Path) -> None:
    run = tmp_path / "data" / "runs" / "sample"
    tikz = run / "tikz" / "v1"
    tikz.mkdir(parents=True)
    (tikz / "figure.tex").write_text("% tex", encoding="utf-8")
    state = {
        "tikz_versions": [
            {"version": 1, "tex": "% tex", "tex_path": str(tikz / "figure.tex")}
        ]
    }
    (run / "state.json").write_text(json.dumps(state), encoding="utf-8")
    result = {
        "run_dir": str(run),
        "image_path": str(tmp_path / "image" / "sample.png"),
        "best_version": 1,
        "best_tex": "% tex",
    }
    archived = archive_and_clean(result, archive_root=tmp_path / "ours")

    assert (tmp_path / "ours" / "stem" / "sample" / "best.tex").is_file()
    assert run.is_dir()  # guarded: never rmtree anything under data/
    assert archived["run_dir"] == str(tmp_path / "ours" / "stem" / "sample")
