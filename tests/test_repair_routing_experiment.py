"""Offline checks for the isolated repair-routing pilot's safeguards."""
from pathlib import Path
import json
import pytest

from scripts.test_repair_routing import audit, prepare_seed, verify_geometry
from geoagent.state.schemas import GeometryObject, Relation

ROOT = Path(__file__).resolve().parents[1]


def _seed_available(stem: str) -> bool:
    return (
        (ROOT / "outputs" / "case_studies" / stem / "case.json").exists()
        or (ROOT / "outputs" / "ours100" / "stem" / stem / "state.json").exists()
    )


def test_replay_seed_has_no_historical_repair_answer(tmp_path: Path):
    state = prepare_seed("1260_q_fig2", tmp_path)
    assert len(state.tikz_versions) == 1
    assert state.latest_version().version == 1
    assert "G" not in audit(state)["ges_point_labels"]
    assert "G" not in audit(state)["drawn_labels"]
    assert not state.action_history
    assert not any(i.get("source") == "supervisor" for i in state.unresolved_issues)
    assert state.latest_version().critic_report["must_repair"] is True


def test_audit_detects_label_added_to_code_without_geometry(tmp_path: Path):
    state = prepare_seed("1260_q_fig2", tmp_path)
    state.latest_version().tex += "\n\\node at (0,0) {$G$};"
    assert audit(state)["drawn_labels_without_ges_point"] == ["G"]
    state.add_object(GeometryObject(id="point_G", type="point", label="G", coords={"px": [448, 254]}))
    assert audit(state)["drawn_labels_without_ges_point"] == []


def test_geometry_gate_rejects_unsupported_stroke_and_point_movement(tmp_path: Path):
    state = prepare_seed("1260_q_fig2", tmp_path)
    candidate = state.model_copy(deep=True)
    candidate.objects["point_A"].coords = {"px": [0, 0]}
    candidate.add_object(GeometryObject(id="invented", type="segment",
        coords={"a_px": [400, 10], "b_px": [600, 10]}, style={"line": "dashed"}))
    result = verify_geometry(state, candidate, tmp_path / "cv")
    assert result["passed"] is False
    assert result["moved_existing_points"] == ["point_A"]
    assert result["segment_checks"][0]["supported"] is False
    assert state.objects["point_A"].coords != candidate.objects["point_A"].coords


def test_geometry_gate_quarantines_undeclared_relation_targets(tmp_path: Path):
    state = prepare_seed("1260_q_fig2", tmp_path)
    candidate = state.model_copy(deep=True)
    candidate.add_relation(Relation(id="bad", subject="point_F", relation="on_segment", object="imagined_line"))
    result = verify_geometry(state, candidate, tmp_path / "cv")
    assert result["quarantined_relations"] == [{"relation_id": "bad", "missing_object_ids": ["imagined_line"]}]
    assert candidate.relations["bad"].status == "rejected"
    assert "bad" not in state.relations


def test_roi_cv_id_collision_cannot_overwrite_global_segment(tmp_path: Path):
    state = prepare_seed("1260_q_fig2", tmp_path)
    candidate = state.model_copy(deep=True)
    candidate.objects["seg_01"].coords = {"a_px": [1, 2], "b_px": [3, 4]}
    result = verify_geometry(state, candidate, tmp_path / "cv")
    assert result["restored_existing_objects"][0]["object_id"] == "seg_01"
    assert candidate.objects["seg_01"] == state.objects["seg_01"]


@pytest.mark.parametrize("stem", ["1653_s_fig1", "795_q_fig2", "6215_s_fig1", "3379_q_fig1"])
def test_archive_seed_excludes_later_repair_evidence(tmp_path: Path, stem: str):
    if not _seed_available(stem):
        pytest.skip(f"replay seed for {stem} is not archived in this checkout")
    state = prepare_seed(stem, tmp_path)
    assert len(state.tikz_versions) == 1
    assert not state.action_history
    assert not state.meta.get("finish")
    assert all(e.source in {"cv_tool", "geometry_agent"} for e in state.evidence.values())
    assert all(i.get("source") == "geometry_agent" for i in state.unresolved_issues)


def test_archive_seed_rejects_post_v1_geometry_changes(tmp_path: Path, monkeypatch):
    import scripts.test_repair_routing as module
    directory = tmp_path / "outputs/ours100/stem/unsafe"
    directory.mkdir(parents=True)
    raw = {"action_history": [{"action": "run_tikz_agent"}, {"action": "call_cv_tool:detect_lines"}]}
    (directory / "state.json").write_text(json.dumps(raw), encoding="utf-8")
    monkeypatch.setattr(module, "ROOT", tmp_path)
    with pytest.raises(ValueError, match="revisited geometry"):
        module.prepare_seed("unsafe", tmp_path / "seed")


def test_audit_recognizes_separate_label_bound_to_unnamed_point(tmp_path: Path):
    state = prepare_seed("1260_q_fig2", tmp_path)
    state.latest_version().tex += "\n\\node at (0,0) {$G$};"
    state.add_object(GeometryObject(id="unlabelled", type="point", coords={"px": [448,254]}))
    state.add_object(GeometryObject(id="glyph_G", type="label", label="G"))
    state.add_relation(Relation(id="binding", subject="glyph_G", relation="labels_point", object="unlabelled"))
    assert audit(state)["drawn_labels_without_ges_point"] == []
    state.objects["unlabelled"].status = "rejected"
    assert audit(state)["drawn_labels_without_ges_point"] == ["G"]
