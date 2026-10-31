from __future__ import annotations

from geoagent.orchestration.runner import (
    _clean_finish_args,
    _finish_gate_problem,
    _issue_list,
    _stops_run,
)
from geoagent.state.schemas import GeometricEvidenceState

_CLEAN_REPORT = {
    "issues": [],
    "actionable_counts": {"high": 0, "medium": 0, "low": 0},
    "must_repair": False,
}


def _state(tmp_path) -> GeometricEvidenceState:
    return GeometricEvidenceState(
        image_path=str(tmp_path / "img.png"), image_size={"width": 200, "height": 100}
    )


def _compiled(state: GeometricEvidenceState, report: dict | None = None, score: float | None = None) -> int:
    version = state.add_tikz_version("tex", agent="test", mode="generate")
    state.mark_compilation(
        version.version,
        ok=True,
        tex_path="a.tex",
        pdf_path="a.pdf",
        png_path="a.png",
        errors=[],
        warnings=[],
        seconds=1.0,
    )
    if report is not None:
        state.attach_critic(version.version, report, score)
    state.update_best(allow_unscored=True)
    return version.version


def test_finish_args_strip_leaked_provider_markup() -> None:
    args = {
        "summary": 'Figure produced.</summary>\n<parameter name="unresolved">["line too thin", "arc extent"]</parameter>\n</invoke>',
        "status": "",
    }
    cleaned = _clean_finish_args(args)
    assert cleaned["summary"] == "Figure produced."
    assert _issue_list(cleaned["unresolved"]) == ["line too thin", "arc extent"]


def test_finish_args_keep_clean_values_untouched() -> None:
    args = {"summary": "compiled v1, score 0.95", "status": "success", "unresolved": ["a"]}
    cleaned = _clean_finish_args(args)
    assert cleaned == args


def test_issue_list_accepts_prose_dict_and_json() -> None:
    assert _issue_list("single issue") == ["single issue"]
    assert _issue_list('["a", "b"]') == ["a", "b"]
    assert _issue_list({"issue": "x"})[0].startswith('{"issue"')
    assert _issue_list(None) == []


def test_only_successful_finish_stops_the_loop() -> None:
    assert _stops_run("finish", {"ok": True}) is True
    assert _stops_run("finish", {"ok": False, "gate": "unresolved_issues"}) is False
    assert _stops_run("run_critic", {"ok": True}) is False


def test_finish_gate_requires_critic_on_latest_render(tmp_path) -> None:
    state = _state(tmp_path)
    _compiled(state)  # compiled but unscored

    problem = _finish_gate_problem(state, visual_left=3, tool_left=5)
    assert problem is not None
    assert problem[0] == "unscored_latest"
    assert "run_critic" in problem[1]
    # No visual budget left: the gate must not deadlock the run.
    assert _finish_gate_problem(state, visual_left=0, tool_left=5) is None


def test_finish_gate_passes_clean_report(tmp_path) -> None:
    state = _state(tmp_path)
    _compiled(state, _CLEAN_REPORT, 0.95)
    assert _finish_gate_problem(state, visual_left=3, tool_left=5) is None


def test_finish_gate_blocks_unresolved_actionable_issues(tmp_path) -> None:
    state = _state(tmp_path)
    report = {
        "issues": [{"type": "label_error", "severity": "high", "description": "missing P"}],
        "actionable_counts": {"high": 1, "medium": 0, "low": 0},
        "must_repair": True,
    }
    _compiled(state, report, 0.9)

    problem = _finish_gate_problem(state, visual_left=3, tool_left=5)
    assert problem is not None
    assert problem[0] == "unresolved_issues"
    assert "must_repair" in problem[1]
    # Not enough calls left for repair + critic: allow the run to end.
    assert _finish_gate_problem(state, visual_left=3, tool_left=1) is None


def test_finish_gate_flags_unscored_newer_version(tmp_path) -> None:
    state = _state(tmp_path)
    _compiled(state, _CLEAN_REPORT, 0.95)
    _compiled(state)  # repair not yet critiqued

    assert state.best_version == 1
    problem = _finish_gate_problem(state, visual_left=3, tool_left=5)
    assert problem is not None
    assert problem[0] == "unscored_latest"
