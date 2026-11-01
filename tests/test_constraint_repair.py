from __future__ import annotations

import math

import numpy as np
import pytest

from geoagent.config import load_settings
from geoagent.orchestration.runner import GeoAgentRunner
from geoagent.state.constraint_repair import (
    _project,
    repair_geometry_constraints,
    total_violation,
)
from geoagent.state.rectify import rectify_right_angles
from geoagent.state.schemas import GeometricEvidenceState, GeometryObject, Relation


def _unit(vec) -> np.ndarray:
    arr = np.asarray(vec, float)
    return arr / np.linalg.norm(arr)


def _state(tmp_path) -> GeometricEvidenceState:
    return GeometricEvidenceState(
        image_path=str(tmp_path / "img.png"), image_size={"width": 400, "height": 300}
    )


def _segment(state, object_id: str, a, b, *, status: str = "confirmed") -> None:
    state.add_object(
        GeometryObject(
            id=object_id,
            type="segment",
            coords={"a_px": list(map(float, a)), "b_px": list(map(float, b))},
            status=status,
            source="cv:detect_lines",
        )
    )


def _point(state, object_id: str, px, label: str = "P") -> None:
    state.add_object(
        GeometryObject(
            id=object_id,
            type="point",
            label=label,
            coords={"px": list(map(float, px))},
            status="confirmed",
            source="cv:bind_point_labels",
        )
    )


def _marker(state, object_id: str, vertex, u1, u2, side: float = 20.0) -> None:
    vertex = np.asarray(vertex, float)
    u1, u2 = _unit(u1), _unit(u2)
    p1 = vertex + side * u1
    p3 = vertex + side * u2
    p2 = p1 + p3 - vertex
    state.add_object(
        GeometryObject(
            id=object_id,
            type="right_angle",
            coords={
                "vertex_px": vertex.tolist(),
                "mark_points_px": [p1.tolist(), p2.tolist(), p3.tolist()],
                "side_length_px": side,
            },
            status="confirmed",
            source="cv:detect_right_angle_marker",
            attributes={"evidence": {"side1_ink_coverage": 0.9}},
        )
    )


def _direction(state, object_id: str) -> np.ndarray:
    coords = state.objects[object_id].coords
    return np.subtract(coords["b_px"], coords["a_px"])


def _normalized_cross(u, v) -> float:
    u, v = _unit(u), _unit(v)
    return abs(float(u[0] * v[1] - u[1] * v[0]))


def _normalized_dot(u, v) -> float:
    u, v = _unit(u), _unit(v)
    return abs(float(u @ v))


def _snapshot(state) -> dict[str, dict]:
    return {oid: dict(obj.coords) for oid, obj in state.objects.items()}


def _parallel_pair(tmp_path, status: str = "confirmed") -> GeometricEvidenceState:
    state = _state(tmp_path)
    _segment(state, "seg_1", (50, 50), (250, 50.4), status=status)
    _segment(state, "seg_2", (50, 150), (250, 150.6), status=status)
    return state


def _corner_state(tmp_path) -> GeometricEvidenceState:
    vertex = np.array([100.0, 100.0])
    a = vertex + np.array([200.0, 3.0])
    b = vertex + np.array([-3.0, -100.0])
    state = _state(tmp_path)
    _segment(state, "seg_h", vertex, a)
    _segment(state, "seg_v", vertex, b)
    _marker(state, "right_angle_01", vertex, a - vertex, b - vertex)
    return state


# --------------------------------------------------------------------------- #
# repairs
# --------------------------------------------------------------------------- #
def test_parallel_pair_becomes_exact(tmp_path) -> None:
    state = _parallel_pair(tmp_path)

    report = repair_geometry_constraints(state)

    assert report["applied"] is True
    assert report["reason"] == "applied"
    assert report["revision"] == 1
    assert report["candidate_count"] >= 1
    assert any(ev.source == "geometry_constraint_repair" for ev in state.evidence.values())
    assert _normalized_cross(_direction(state, "seg_1"), _direction(state, "seg_2")) < 1e-9
    assert any(
        note.startswith("constraint_repair:") for note in state.objects["seg_1"].notes
    )
    assert report["max_shift_px"] <= report["tolerances"]["max_shift_px"]


def test_unmarked_perpendicular_pair_becomes_exact(tmp_path) -> None:
    vertex = np.array([100.0, 100.0])
    angle = math.radians(89.9)
    horizontal = np.array([200.0, 0.0])
    slanted = 150.0 * np.array([math.cos(angle), math.sin(angle)])
    state = _state(tmp_path)
    _segment(state, "seg_h", vertex, vertex + horizontal)
    _segment(state, "seg_v", vertex, vertex + slanted)

    report = repair_geometry_constraints(state)

    assert report["applied"] is True
    assert _normalized_dot(_direction(state, "seg_h"), _direction(state, "seg_v")) < 1e-9


def test_near_equal_lengths_become_exact(tmp_path) -> None:
    state = _state(tmp_path)
    _segment(state, "seg_1", (50, 50), (250, 50))
    _segment(state, "seg_2", (50, 150), (250.2, 150))  # 0.1 % length gap

    report = repair_geometry_constraints(state)

    assert report["applied"] is True
    assert report["tolerances"]["equal_length_rel_tol"] == 0.002
    first = float(np.linalg.norm(_direction(state, "seg_1")))
    second = float(np.linalg.norm(_direction(state, "seg_2")))
    assert abs(first - second) / max(first, second) < 1e-9


def test_near_collinear_point_snaps_onto_the_line(tmp_path) -> None:
    state = _state(tmp_path)
    _segment(state, "seg_base", (50, 100), (250, 100))
    _point(state, "point_P", (150.0, 100.4))

    report = repair_geometry_constraints(state)

    assert report["applied"] is True
    point = np.asarray(state.objects["point_P"].coords["px"], float)
    a = np.asarray(state.objects["seg_base"].coords["a_px"], float)
    b = np.asarray(state.objects["seg_base"].coords["b_px"], float)
    edge = b - a
    distance = abs(float(edge[0] * (point - a)[1] - edge[1] * (point - a)[0])) / np.linalg.norm(edge)
    assert distance < 1e-9
    assert point.tolist() != [150.0, 100.4]
    assert any(
        note.startswith("constraint_repair:") for note in state.objects["point_P"].notes
    )


# --------------------------------------------------------------------------- #
# interaction with the hard right-angle rectifier
# --------------------------------------------------------------------------- #
def test_verified_right_angle_geometry_is_locked(tmp_path) -> None:
    state = _corner_state(tmp_path)
    _segment(state, "seg_p1", (50, 220), (250, 220.2))
    _segment(state, "seg_p2", (50, 280), (250, 280.6))
    corner_before = {
        oid: dict(state.objects[oid].coords) for oid in ("seg_h", "seg_v", "right_angle_01")
    }

    report = repair_geometry_constraints(state)

    assert report["applied"] is True
    assert set(report["locked_segments"]) == {"seg_h", "seg_v"}
    assert report["locked_nodes"]
    assert any(item["reason"] == "locked_right_angle" for item in report["rejected"])
    assert {
        oid: dict(state.objects[oid].coords) for oid in ("seg_h", "seg_v", "right_angle_01")
    } == corner_before
    assert _normalized_cross(_direction(state, "seg_p1"), _direction(state, "seg_p2")) < 1e-9


def test_soft_repair_then_hard_rectify_keeps_both(tmp_path) -> None:
    state = _corner_state(tmp_path)
    _segment(state, "seg_p1", (50, 220), (250, 220.2))
    _segment(state, "seg_p2", (50, 280), (250, 280.6))

    soft = repair_geometry_constraints(state)
    hard = rectify_right_angles(state)

    assert soft["applied"] is True
    assert hard["applied"] is True
    assert state.meta["constraint_repair"]["revision"] == 1
    assert state.meta["rectification"]["revision"] == 1
    assert _normalized_cross(_direction(state, "seg_p1"), _direction(state, "seg_p2")) < 1e-9
    detail = hard["right_angles"][0]
    assert abs(detail["error_deg"]) < 0.05
    assert any(note.startswith("constraint_repair:") for note in state.objects["seg_p1"].notes)
    assert any(note.startswith("rectify:") for note in state.objects["seg_h"].notes)
    h = _direction(state, "seg_h")
    v = _direction(state, "seg_v")
    assert _normalized_dot(h, v) < 1e-9


def test_soft_right_angle_mode_repairs_marker_as_soft_constraint(tmp_path) -> None:
    state = _corner_state(tmp_path)
    marker_before = dict(state.objects["right_angle_01"].coords)

    report = repair_geometry_constraints(state, right_angle_mode="soft")

    assert report["applied"] is True
    assert report["right_angle_mode"] == "soft"
    assert report["right_angle_markers"] == 1
    assert report["right_angle_relations"] == 1
    assert report["locked_segments"] == []
    assert _normalized_dot(_direction(state, "seg_h"), _direction(state, "seg_v")) < 1e-9
    # The marker object belongs to the TikZ layer; soft mode only moves strokes.
    assert state.objects["right_angle_01"].coords == marker_before
    detail = next(item for item in report["relations"] if item.get("forced"))
    assert detail["source"] == "right_angle_marker"
    assert detail["after_violation"] < 1e-9


def test_soft_right_angle_mode_reports_ignore_without_markers(tmp_path) -> None:
    state = _parallel_pair(tmp_path)

    report = repair_geometry_constraints(state, right_angle_mode="ignore")

    assert report["right_angle_mode"] == "ignore"
    assert report["right_angle_markers"] == 0
    assert report["applied"] is True


def test_unknown_right_angle_mode_is_rejected(tmp_path) -> None:
    state = _parallel_pair(tmp_path)
    with pytest.raises(ValueError, match="right_angle_mode"):
        repair_geometry_constraints(state, right_angle_mode="strict")


# --------------------------------------------------------------------------- #
# gates and no-ops
# --------------------------------------------------------------------------- #
def test_second_call_is_idempotent(tmp_path) -> None:
    state = _parallel_pair(tmp_path)
    first = repair_geometry_constraints(state)
    assert first["applied"] is True
    coords = _snapshot(state)
    notes = list(state.objects["seg_1"].notes)

    second = repair_geometry_constraints(state)

    assert second["applied"] is False
    assert second["reason"] == "already_satisfied"
    assert second["revision"] == 1
    assert _snapshot(state) == coords
    assert state.objects["seg_1"].notes == notes


def test_max_shift_gate_rejects_without_changes(tmp_path) -> None:
    state = _parallel_pair(tmp_path)
    before = _snapshot(state)

    report = repair_geometry_constraints(state, max_shift_px=0.001)

    assert report["applied"] is False
    assert report["reason"] == "max_shift_exceeded"
    assert _snapshot(state) == before
    assert state.evidence == {}
    assert report["revision"] == 0


def test_default_clustering_tolerance_is_tight(tmp_path) -> None:
    state = _parallel_pair(tmp_path)

    report = repair_geometry_constraints(state)

    assert report["tolerances"]["tolerance_px"] == 2.0
    assert report["tolerances"]["lock_tolerance_px"] == 8.0


def test_endpoint_shift_gate_does_not_hide_behind_cluster_centres(tmp_path) -> None:
    state = _state(tmp_path)
    _segment(state, "seg_1", (100, 100), (300, 100.4))
    _segment(state, "seg_2", (100, 102), (300, 102.4))  # merged at tolerance 5
    _segment(state, "seg_3", (100, 200), (300, 201.0))
    before = _snapshot(state)

    report = repair_geometry_constraints(state, tolerance_px=5.0, max_shift_px=0.5)

    assert report["applied"] is False
    assert report["reason"] == "max_shift_exceeded"
    # The cluster centre barely moves, but write-back would move an endpoint
    # ~1.5 px into the shared vertex. The gate must use the latter.
    assert report["max_node_shift_px"] < 0.5
    assert report["max_shift_px"] > 0.5
    assert _snapshot(state) == before


def test_reported_shift_matches_written_coordinates(tmp_path) -> None:
    state = _parallel_pair(tmp_path)
    before = {
        oid: (np.asarray(obj.coords["a_px"], float), np.asarray(obj.coords["b_px"], float))
        for oid, obj in state.objects.items()
        if obj.type == "segment"
    }

    report = repair_geometry_constraints(state)

    assert report["applied"] is True
    actual = max(
        float(np.linalg.norm(np.asarray(state.objects[oid].coords[key], float) - old))
        for oid, (a, b) in before.items()
        for key, old in (("a_px", a), ("b_px", b))
    )
    assert abs(report["max_shift_px"] - actual) < 1e-6


def test_zero_displacement_fraction_rejects(tmp_path) -> None:
    state = _parallel_pair(tmp_path)
    before = _snapshot(state)

    report = repair_geometry_constraints(state, max_disp_frac=0.0)

    assert report["applied"] is False
    assert report["reason"] == "max_shift_exceeded"
    assert _snapshot(state) == before
    assert state.evidence == {}


def test_disabled_is_audited_noop(tmp_path) -> None:
    state = _parallel_pair(tmp_path)
    before = _snapshot(state)

    report = repair_geometry_constraints(state, enabled=False)

    assert report["enabled"] is False
    assert report["applied"] is False
    assert report["reason"] == "disabled"
    assert report["revision"] == 0
    assert _snapshot(state) == before
    assert state.meta["constraint_repair"]["reason"] == "disabled"


def test_single_segment_has_no_candidates(tmp_path) -> None:
    state = _state(tmp_path)
    _segment(state, "seg_AB", (10, 10), (200, 10))

    report = repair_geometry_constraints(state)

    assert report["applied"] is False
    assert report["reason"] == "no_candidates"
    assert state.evidence == {}


def test_non_segment_objects_and_relations_are_untouched(tmp_path) -> None:
    state = _parallel_pair(tmp_path)
    state.add_object(
        GeometryObject(
            id="circle_01",
            type="circle",
            coords={"center_px": [200, 150], "radius_px": 40},
            status="confirmed",
            source="cv:detect_circles",
        )
    )
    state.add_object(
        GeometryObject(
            id="label_A",
            type="label",
            label="A",
            coords={"box_px": [90, 90, 110, 110], "centroid_px": [100, 100]},
            status="confirmed",
            source="cv:match_label_templates",
        )
    )
    state.add_object(
        GeometryObject(
            id="polygon_01",
            type="polygon",
            coords={"vertices_px": [[10, 10], [40, 10], [25, 30]]},
            status="confirmed",
            source="cv:detect_polygon",
        )
    )
    state.add_relation(
        Relation(
            id="",
            subject="seg_1",
            relation="parallel",
            object="seg_2",
            source="geometry_agent",
        )
    )
    before = {
        oid: dict(state.objects[oid].coords)
        for oid in ("circle_01", "label_A", "polygon_01")
    }
    relations = {rid: rel.model_dump() for rid, rel in state.relations.items()}

    report = repair_geometry_constraints(state)

    assert report["applied"] is True
    assert {oid: dict(state.objects[oid].coords) for oid in before} == before
    assert {rid: rel.model_dump() for rid, rel in state.relations.items()} == relations


def test_state_round_trips_with_report_and_evidence(tmp_path) -> None:
    state = _parallel_pair(tmp_path)
    repair_geometry_constraints(state)

    path = tmp_path / "state.json"
    state.save(path)
    loaded = GeometricEvidenceState.load(path)

    assert loaded.objects["seg_1"].coords == state.objects["seg_1"].coords
    assert any(
        note.startswith("constraint_repair:") for note in loaded.objects["seg_1"].notes
    )
    assert any(ev.source == "geometry_constraint_repair" for ev in loaded.evidence.values())
    report = loaded.meta["constraint_repair"]
    assert report["applied"] is True
    assert report["revision"] == 1
    assert report["constraint_mode"] == "soft_gauss_seidel"


# --------------------------------------------------------------------------- #
# solver and candidate selection units
# --------------------------------------------------------------------------- #
def test_solver_projects_mixed_relations_and_respects_fixed_nodes() -> None:
    P = np.array([[0.0, 0.0], [100.0, 2.0], [2.0, 100.0], [100.0, 100.0]])
    relations = [
        ("perp", 0, 1, 0, 2),
        ("par", 0, 1, 3, 2),
        ("eq", 0, 1, 0, 2),
    ]

    solved = _project(P, relations, iters=200)
    assert total_violation(solved, relations) < 1e-9
    fixed = _project(P, relations, iters=200, fixed_nodes=frozenset({0}))
    assert np.allclose(fixed[0], P[0])
    assert total_violation(fixed, relations) < 1e-9


def test_candidates_reject_loose_angles_and_deduplicate(tmp_path) -> None:
    state = _state(tmp_path)
    # 1 degree apart, different lengths: no relation candidate at 0.5 degrees.
    vertex = np.array([50.0, 50.0])
    angle = math.radians(1.0)
    _segment(state, "seg_a", vertex, vertex + np.array([200.0, 0.0]))
    _segment(
        state,
        "seg_b",
        np.array([50.0, 150.0]),
        np.array([50.0, 150.0]) + 150.0 * np.array([math.cos(angle), math.sin(angle)]),
    )

    report = repair_geometry_constraints(state)

    assert report["applied"] is False
    assert report["reason"] == "no_candidates"


def test_duplicate_segments_do_not_duplicate_relations(tmp_path) -> None:
    state = _state(tmp_path)
    _segment(state, "seg_1", (50, 50), (250, 50.4))
    _segment(state, "seg_1_copy", (250, 50.4), (50, 50))
    _segment(state, "seg_2", (50, 150), (250, 150.6))

    report = repair_geometry_constraints(state)

    types = [item["type"] for item in report["relations"]]
    assert types.count("par") == 1


def test_max_relations_truncates_and_reports_overflow(tmp_path) -> None:
    state = _state(tmp_path)
    _segment(state, "seg_a", (50, 50), (250, 50.2))
    _segment(state, "seg_b", (50, 150), (250, 150.4))
    _segment(state, "seg_c", (50, 250), (250, 250.6))

    report = repair_geometry_constraints(state, max_relations=2)

    assert report["candidate_count"] == 2
    assert any(
        item["reason"] == "max_relations_exceeded" for item in report["rejected"]
    )


def test_collinear_window_excludes_points_outside_the_span(tmp_path) -> None:
    state = _state(tmp_path)
    _segment(state, "seg_base", (50, 100), (250, 100))
    _point(state, "point_P", (248.0, 100.2))  # t = 0.99

    report = repair_geometry_constraints(state)

    assert report["applied"] is False
    assert report["reason"] == "no_candidates"


# --------------------------------------------------------------------------- #
# runner wiring
# --------------------------------------------------------------------------- #
class _FakeTikz:
    def run(self, mode, instruction, image_path=None):  # noqa: ARG002
        return {"ok": True, "tex": "\\draw (0,0)--(1,0);", "notes": ""}


def _runner(tmp_path) -> GeoAgentRunner:
    runner = object.__new__(GeoAgentRunner)
    runner.state = _state(tmp_path)
    runner.settings = load_settings(
        {"geometry_repair": True, "right_angle_mode": "lock", "geometry_repair_stage": "pre_ges"}
    )
    runner.tikz_agent = _FakeTikz()
    runner._compile_version = lambda version: {
        "compile_ok": True,
        "validation_passed": True,
        "errors": [],
        "warnings": [],
        "png_path": None,
    }
    return runner


def test_runner_runs_soft_repair_before_rectify(tmp_path, monkeypatch) -> None:
    import geoagent.orchestration.runner as module

    order: list[str] = []
    monkeypatch.setattr(
        module, "repair_geometry_constraints", lambda state, **kwargs: order.append("soft")
    )
    monkeypatch.setattr(module, "rectify_right_angles", lambda state: order.append("hard"))
    runner = _runner(tmp_path)

    result = runner._do_tikz_agent({"mode": "generate", "use_image": False})

    assert order == ["soft", "hard"]
    assert result["ok"] is True
    assert runner.settings.geometry.enabled is True


def test_runner_can_disable_rectify(tmp_path, monkeypatch) -> None:
    import geoagent.orchestration.runner as module

    order: list[str] = []
    monkeypatch.setattr(
        module, "repair_geometry_constraints", lambda state, **kwargs: order.append("soft")
    )
    monkeypatch.setattr(module, "rectify_right_angles", lambda state: order.append("hard"))
    runner = _runner(tmp_path)
    runner.settings = load_settings(
        {"geometry_repair": True, "rectify": False, "right_angle_mode": "lock", "geometry_repair_stage": "pre_ges"}
    )

    result = runner._do_tikz_agent({"mode": "generate", "use_image": False})

    assert order == ["soft"]
    assert result["ok"] is True
    assert runner.state.meta["rectification"]["reason"] == "disabled"


def test_runner_soft_right_angle_mode_skips_hard_rectify(tmp_path, monkeypatch) -> None:
    import geoagent.orchestration.runner as module

    order: list[str] = []
    seen: dict = {}

    def soft(state, **kwargs):
        seen.update(kwargs)
        order.append("soft")

    monkeypatch.setattr(module, "repair_geometry_constraints", soft)
    monkeypatch.setattr(module, "rectify_right_angles", lambda state: order.append("hard"))
    runner = _runner(tmp_path)
    runner.settings = load_settings({"geometry_repair": True, "right_angle_mode": "soft", "geometry_repair_stage": "pre_ges"})

    result = runner._do_tikz_agent({"mode": "generate", "use_image": False})

    assert order == ["soft"]
    assert seen["right_angle_mode"] == "soft"
    assert result["ok"] is True
    assert runner.state.meta["rectification"]["reason"] == "superseded_by_soft_right_angles"


def test_soft_repair_failure_does_not_block_rectify(tmp_path, monkeypatch) -> None:
    import geoagent.orchestration.runner as module

    def boom(state, **kwargs):
        raise RuntimeError("bad solver")

    called: list[str] = []
    monkeypatch.setattr(module, "repair_geometry_constraints", boom)
    monkeypatch.setattr(module, "rectify_right_angles", lambda state: called.append("hard"))
    runner = _runner(tmp_path)

    result = runner._do_tikz_agent({"mode": "generate", "use_image": False})

    assert called == ["hard"]
    assert result["ok"] is True
    meta = runner.state.meta["constraint_repair"]
    assert meta["ok"] is False
    assert "RuntimeError" in meta["error"]
