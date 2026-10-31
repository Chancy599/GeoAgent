from __future__ import annotations

from geoagent.state.schemas import GeometricEvidenceState, GeometryObject, Relation


def _state(tmp_path) -> GeometricEvidenceState:
    return GeometricEvidenceState(image_path=str(tmp_path / "img.png"), image_size={"width": 574, "height": 367})


def test_objects_relations_and_bindings_roundtrip(tmp_path) -> None:
    state = _state(tmp_path)
    oid = state.add_object(
        GeometryObject(
            id="point_O",
            type="point",
            label="O",
            coords={"px": [287.4, 300.6]},
            normalized={"x": 0.5, "y": 0.82},
            source="cv:bind_point_labels",
            status="candidate",
        )
    )
    assert oid == "point_O"

    rid = state.add_relation(
        Relation(id="", subject="point_O", relation="center_of", object="circle_01", source="geometry_agent")
    )
    assert rid in state.relations

    state.label_bindings["O"] = "point_O"
    state.add_conflict("arc extent", [{"source": "cv", "claim": "upper semicircle"}])
    state.add_unresolved({"source": "cv", "issue": "B label slightly ambiguous"})

    path = tmp_path / "state.json"
    state.save(path)
    loaded = GeometricEvidenceState.load(path)
    assert loaded.objects["point_O"].label == "O"
    assert loaded.label_bindings == {"O": "point_O"}
    assert len(loaded.conflicts) == 1
    assert len(loaded.unresolved_issues) == 1


def test_summary_exposes_ids_and_labels(tmp_path) -> None:
    state = _state(tmp_path)
    state.add_object({"id": "seg_MN", "type": "segment", "coords": {"a_px": [50, 301], "b_px": [525, 301]}})
    state.add_object({"id": "point_P", "type": "point", "label": "P", "coords": {"px": [287, 63]}})
    text = state.summary(max_objects=20, max_chars=4000)
    assert "seg_MN" in text
    assert "P" in text


def test_summary_exposes_critic_gate_flags(tmp_path) -> None:
    state = _state(tmp_path)
    state.critic_reports.append(
        {
            "assessment_score": 0.9,
            "must_repair": True,
            "checklist_score": 0.75,
            "issues": [
                {"severity": "low", "type": "other", "description": "extra dot", "flaky": True}
            ],
            "checks": [
                {"object_id": "seg_MN", "status": "missing", "note": "not drawn"},
                {"object_id": "point_A", "status": "present", "note": ""},
            ],
        }
    )
    text = state.summary()
    assert "must_repair=True" in text
    assert "flaky" in text
    assert "checklist=0.75" in text
    assert "[check missing] seg_MN" in text


def test_best_version_uses_latest_scored_version(tmp_path) -> None:
    state = _state(tmp_path)
    state.add_tikz_version("\\documentclass{standalone}\\begin{document}x\\end{document}", agent="test", mode="generate")
    state.mark_compilation(
        1,
        ok=True,
        tex_path="a.tex",
        pdf_path="a.pdf",
        png_path="a.png",
        errors=[],
        warnings=[],
        seconds=1.0,
    )
    state.update_best()
    assert state.best_version == 1
    state.attach_critic(1, {"verdict": "ok", "issues": []}, 0.9)
    state.update_best()
    assert state.best_version == 1
    assert state.best_score == 0.9


def test_best_version_prefers_fewer_serious_critic_issues(tmp_path) -> None:
    state = _state(tmp_path)
    for _ in range(2):
        state.add_tikz_version("tex", agent="test", mode="generate")
    for version in (1, 2):
        state.mark_compilation(
            version,
            ok=True,
            tex_path=f"v{version}.tex",
            pdf_path=f"v{version}.pdf",
            png_path=f"v{version}.png",
            errors=[],
            warnings=[],
            seconds=1.0,
        )
    state.attach_critic(
        1,
        {
            "issues": [{"type": "label_error", "severity": "medium", "description": "missing P"}],
            "actionable_counts": {"high": 0, "medium": 1, "low": 0},
            "must_repair": True,
        },
        0.95,
    )
    state.attach_critic(
        2,
        {"issues": [], "actionable_counts": {"high": 0, "medium": 0, "low": 0}, "must_repair": False},
        0.93,
    )
    state.update_best()
    assert state.best_version == 2
    assert state.best_score == 0.93


def test_best_version_prefers_higher_checklist_score(tmp_path) -> None:
    state = _state(tmp_path)
    for _ in range(2):
        state.add_tikz_version("tex", agent="test", mode="generate")
    for version in (1, 2):
        state.mark_compilation(
            version,
            ok=True,
            tex_path=f"v{version}.tex",
            pdf_path=f"v{version}.pdf",
            png_path=f"v{version}.png",
            errors=[],
            warnings=[],
            seconds=1.0,
        )
    state.attach_critic(
        1,
        {
            "issues": [],
            "checklist_score": 0.6,
            "actionable_counts": {"high": 0, "medium": 0, "low": 0},
            "must_repair": False,
        },
        0.95,
    )
    state.attach_critic(
        2,
        {
            "issues": [],
            "checklist_score": 0.9,
            "actionable_counts": {"high": 0, "medium": 0, "low": 0},
            "must_repair": False,
        },
        0.90,
    )
    state.update_best()
    assert state.best_version == 2
    assert state.best_score == 0.90
