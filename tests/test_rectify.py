from __future__ import annotations

import math

import numpy as np
import pytest

from geoagent.state.rectify import rectify_right_angles
from geoagent.state.schemas import GeometricEvidenceState, GeometryObject, Relation


def _unit(vec) -> np.ndarray:
    arr = np.asarray(vec, float)
    return arr / np.linalg.norm(arr)


def _state(tmp_path) -> GeometricEvidenceState:
    return GeometricEvidenceState(
        image_path=str(tmp_path / "img.png"), image_size={"width": 400, "height": 300}
    )


def _marker(vertex, u1, u2, side: float = 20.0) -> dict:
    vertex = np.asarray(vertex, float)
    u1, u2 = _unit(u1), _unit(u2)
    p1 = vertex + side * u1
    p3 = vertex + side * u2
    p2 = p1 + p3 - vertex
    return {
        "vertex_px": vertex.tolist(),
        "mark_points_px": [p1.tolist(), p2.tolist(), p3.tolist()],
        "side_length_px": side,
    }


def _add_segment(state, object_id: str, a, b) -> None:
    state.add_object(
        GeometryObject(
            id=object_id,
            type="segment",
            coords={"a_px": list(map(float, a)), "b_px": list(map(float, b))},
            status="confirmed",
            source="cv:detect_lines",
        )
    )


def _add_marker(state, object_id: str, vertex, u1, u2, *, source="cv:detect_right_angle_marker") -> None:
    state.add_object(
        GeometryObject(
            id=object_id,
            type="right_angle",
            coords=_marker(vertex, u1, u2),
            status="confirmed",
            source=source,
            attributes={"evidence": {"side1_ink_coverage": 0.9}},
        )
    )


def _angle_between(a, b) -> float:
    d1, d2 = _unit(a), _unit(b)
    return math.degrees(math.acos(float(np.clip(abs(d1 @ d2), -1.0, 1.0))))


def _assert_perpendicular(a, b) -> None:
    # Check the actual stored coordinates, not the rounded report angle.
    assert abs(float(_unit(a) @ _unit(b))) < 1e-10


def _corner_state(tmp_path, horizontal=(200.0, 4.0), vertical=(-4.0, -100.0)):
    vertex = np.array([100.0, 100.0])
    a = vertex + np.asarray(horizontal, float)
    b = vertex + np.asarray(vertical, float)
    state = _state(tmp_path)
    _add_segment(state, "seg_h", vertex, a)
    _add_segment(state, "seg_v", vertex, b)
    _add_marker(state, "right_angle_01", vertex, a - vertex, b - vertex)
    return state, vertex, a, b


def test_simple_corner_becomes_exact(tmp_path) -> None:
    state, vertex, a, b = _corner_state(tmp_path)
    report = rectify_right_angles(state)

    assert report["applied"] is True
    detail = report["right_angles"][0]
    assert abs(detail["error_deg"]) < 0.05

    h = state.objects["seg_h"].coords
    v = state.objects["seg_v"].coords
    # The corner is shared exactly after rectification.
    assert np.allclose(h["a_px"], v["a_px"], atol=0.011)
    assert _angle_between(
        np.subtract(h["b_px"], h["a_px"]), np.subtract(v["b_px"], v["a_px"])
    ) < 0.05 or abs(_angle_between(
        np.subtract(h["b_px"], h["a_px"]), np.subtract(v["b_px"], v["a_px"])
    ) - 90.0) < 0.05

    marker = state.objects["right_angle_01"].coords
    p1, p2, p3 = (np.asarray(p, float) for p in marker["mark_points_px"])
    corner = np.asarray(marker["vertex_px"], float)
    assert abs(_angle_between(p1 - corner, p3 - corner) - 90.0) < 0.05
    assert np.allclose(p2, p1 + p3 - corner, atol=0.02)
    assert state.objects["right_angle_01"].status == "confirmed"
    assert state.objects["seg_h"].status == "confirmed"
    assert any(note.startswith("rectify:") for note in state.objects["right_angle_01"].notes)
    assert any(ev.source == "right_angle_rectifier" for ev in state.evidence.values())
    assert state.meta["rectification"]["revision"] == 1

    # The corner itself barely moves (the arms absorb the correction).
    assert float(np.linalg.norm(np.asarray(h["a_px"], float) - vertex)) < 5.0


def test_rectangle_chain_satisfies_all_four_corners(tmp_path) -> None:
    a = np.array([100.0, 100.0])
    b = np.array([300.0, 103.0])
    c = np.array([298.0, 300.0])
    d = np.array([102.0, 297.0])
    state = _state(tmp_path)
    for name, p, q in (("AB", a, b), ("BC", b, c), ("CD", c, d), ("DA", d, a)):
        _add_segment(state, f"seg_{name}", p, q)
    for name, vertex, p, q in (
        ("A", a, b, d),
        ("B", b, c, a),
        ("C", c, d, b),
        ("D", d, a, c),
    ):
        _add_marker(state, f"right_angle_{name}", vertex, p - vertex, q - vertex)

    report = rectify_right_angles(state)

    assert report["applied"] is True
    assert len(report["right_angles"]) == 4
    assert all(abs(item["error_deg"]) < 0.05 for item in report["right_angles"])
    assert report["max_shift_px"] < 5.0

    coords = {name: state.objects[f"seg_{name}"].coords for name in ("AB", "BC", "CD", "DA")}
    assert np.allclose(coords["AB"]["b_px"], coords["BC"]["a_px"], atol=0.011)
    assert np.allclose(coords["BC"]["b_px"], coords["CD"]["a_px"], atol=0.011)
    assert np.allclose(coords["CD"]["b_px"], coords["DA"]["a_px"], atol=0.011)
    assert np.allclose(coords["DA"]["b_px"], coords["AB"]["a_px"], atol=0.011)

    def direction(name: str) -> np.ndarray:
        seg = coords[name]
        return np.subtract(seg["b_px"], seg["a_px"])

    assert _angle_between(direction("AB"), direction("CD")) < 0.1
    assert _angle_between(direction("BC"), direction("DA")) < 0.1
    for first, second in (("AB", "BC"), ("BC", "CD"), ("CD", "DA"), ("DA", "AB")):
        _assert_perpendicular(direction(first), direction(second))


def test_t_junction_foot_stays_on_base(tmp_path) -> None:
    base_a = np.array([50.0, 100.0])
    base_b = np.array([300.0, 103.0])
    vertex = np.array([150.0, 101.5])
    apex = np.array([148.0, 20.0])
    state = _state(tmp_path)
    _add_segment(state, "seg_base", base_a, base_b)
    _add_segment(state, "seg_alt", vertex, apex)
    _add_marker(state, "right_angle_01", vertex, base_b - vertex, apex - vertex)

    report = rectify_right_angles(state)

    detail = report["right_angles"][0]
    assert report["applied"] is True
    assert set(detail["kinds"]) == {"through", "end"}
    assert abs(detail["error_deg"]) < 0.05

    base = state.objects["seg_base"].coords
    alt = state.objects["seg_alt"].coords
    corner = np.asarray(state.objects["right_angle_01"].coords["vertex_px"], float)
    a, b = np.asarray(base["a_px"], float), np.asarray(base["b_px"], float)
    foot_distance = abs((b - a)[0] * (corner - a)[1] - (b - a)[1] * (corner - a)[0]) / np.linalg.norm(b - a)
    assert foot_distance < 1e-9
    _assert_perpendicular(np.subtract(alt["b_px"], alt["a_px"]), b - a)
    assert np.allclose(alt["a_px"], corner, atol=0.011)
    assert abs(_angle_between(np.subtract(alt["b_px"], alt["a_px"]), b - a) - 90.0) < 0.05


def test_overshooting_arm_endpoints_merge_into_the_vertex(tmp_path) -> None:
    # Both strokes stop a few pixels away from the marked corner: the vertical
    # ends 7 px below V and the horizontal 7 px left of V. They must still be
    # recognised as the two arms of the same vertex.
    vertex = np.array([69.0, 632.0])
    vertical_far = np.array([69.0, 58.0])
    horizontal_far = np.array([360.0, 632.0])
    state = _state(tmp_path)
    _add_segment(state, "seg_v", vertical_far, vertex + np.array([0.0, 7.0]))
    _add_segment(state, "seg_h", horizontal_far, vertex - np.array([7.0, 0.0]))
    _add_marker(
        state,
        "right_angle_01",
        vertex,
        vertical_far - vertex,
        horizontal_far - vertex,
    )

    report = rectify_right_angles(state)

    assert report["applied"] is True
    assert report["rejected"] == []
    assert abs(report["right_angles"][0]["error_deg"]) < 0.05
    assert report["max_shift_px"] < 5.0
    assert set(report["right_angles"][0]["kinds"]) == {"end"}
    v = state.objects["seg_v"].coords
    h = state.objects["seg_h"].coords
    assert np.allclose(v["b_px"], h["b_px"], atol=0.011)
    assert abs(
        _angle_between(np.subtract(v["b_px"], v["a_px"]), np.subtract(h["a_px"], h["b_px"]))
        - 90.0
    ) < 0.05


def test_false_positive_is_rejected_without_changes(tmp_path) -> None:
    vertex = np.array([100.0, 100.0])
    a = vertex + np.array([200.0, 0.0])
    b = vertex + np.array([50.0, 86.6025])  # ~60 degrees from the first arm
    state = _state(tmp_path)
    _add_segment(state, "seg_a", vertex, a)
    _add_segment(state, "seg_b", vertex, b)
    _add_marker(state, "right_angle_01", vertex, a - vertex, b - vertex)
    before = {oid: dict(obj.coords) for oid, obj in state.objects.items()}

    report = rectify_right_angles(state)

    assert report["applied"] is False
    assert report["reason"] == "no_rectifiable_right_angles"
    assert [item["reason"] for item in report["rejected"]] == ["initial_angle_off"]
    assert {oid: dict(obj.coords) for oid, obj in state.objects.items()} == before
    assert not any(ev.source == "right_angle_rectifier" for ev in state.evidence.values())


def test_max_shift_gate_rejects_whole_correction(tmp_path) -> None:
    state, *_ = _corner_state(tmp_path)
    before = {oid: dict(obj.coords) for oid, obj in state.objects.items()}

    report = rectify_right_angles(state, max_shift_px=0.5)

    assert report["applied"] is False
    assert report["reason"] == "max_shift_exceeded"
    assert {oid: dict(obj.coords) for oid, obj in state.objects.items()} == before


def test_second_call_is_idempotent(tmp_path) -> None:
    state, *_ = _corner_state(tmp_path)
    first = rectify_right_angles(state)
    assert first["applied"] is True
    coords = {oid: dict(obj.coords) for oid, obj in state.objects.items()}
    notes = list(state.objects["right_angle_01"].notes)

    second = rectify_right_angles(state)

    assert second["applied"] is False
    assert second["reason"] == "already_rectified"
    assert second["revision"] == 1
    assert {oid: dict(obj.coords) for oid, obj in state.objects.items()} == coords
    assert state.objects["right_angle_01"].notes == notes


def test_no_right_angles_is_noop(tmp_path) -> None:
    state = _state(tmp_path)
    _add_segment(state, "seg_AB", [10, 10], [200, 10])

    report = rectify_right_angles(state)

    assert report["applied"] is False
    assert report["reason"] == "no_right_angles"
    assert state.evidence == {}


def test_point_follows_vertex_and_state_round_trips(tmp_path) -> None:
    state, vertex, *_ = _corner_state(tmp_path)
    state.add_object(
        GeometryObject(
            id="point_A",
            type="point",
            label="A",
            coords={"px": [100.5, 99.5]},
            status="confirmed",
            source="cv:bind_point_labels",
        )
    )
    state.label_bindings["A"] = "point_A"

    rectify_right_angles(state)

    point = np.asarray(state.objects["point_A"].coords["px"], float)
    corner = np.asarray(state.objects["right_angle_01"].coords["vertex_px"], float)
    assert np.allclose(point, corner, atol=0.011)
    assert state.objects["point_A"].label == "A"
    assert state.label_bindings == {"A": "point_A"}

    path = tmp_path / "state.json"
    state.save(path)
    loaded = GeometricEvidenceState.load(path)
    assert loaded.objects["point_A"].coords == state.objects["point_A"].coords
    assert any(note.startswith("rectify:") for note in loaded.objects["right_angle_01"].notes)
    assert any(ev.source == "right_angle_rectifier" for ev in loaded.evidence.values())
    assert loaded.meta["rectification"]["applied"] is True


def test_non_segment_objects_and_relations_are_untouched(tmp_path) -> None:
    state, *_ = _corner_state(tmp_path)
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
    state.add_relation(
        Relation(
            id="",
            subject="circle_01",
            relation="perpendicular",
            object="seg_h",
            source="geometry_agent",
        )
    )
    before_circle = dict(state.objects["circle_01"].coords)
    before_label = dict(state.objects["label_A"].coords)
    before_relations = {rid: rel.model_dump() for rid, rel in state.relations.items()}

    rectify_right_angles(state)

    assert state.objects["circle_01"].coords == before_circle
    assert state.objects["label_A"].coords == before_label
    assert {rid: rel.model_dump() for rid, rel in state.relations.items()} == before_relations


@pytest.mark.parametrize("offset", [0.00001, 0.01, 0.5, 4.0])
def test_hard_right_angle_survives_serialization(tmp_path, offset) -> None:
    state, *_ = _corner_state(tmp_path, horizontal=(200.0, offset), vertical=(-offset, -100.0))
    report = rectify_right_angles(state)
    assert report["applied"]
    assert report["constraint_mode"] == "hard_projection"
    state.save(tmp_path / "exact.json")
    loaded = GeometricEvidenceState.load(tmp_path / "exact.json")
    h, v = (loaded.objects[name].coords for name in ("seg_h", "seg_v"))
    _assert_perpendicular(np.subtract(h["b_px"], h["a_px"]), np.subtract(v["b_px"], v["a_px"]))
    marker = loaded.objects["right_angle_01"].coords
    corner = np.asarray(marker["vertex_px"])
    _assert_perpendicular(np.subtract(marker["mark_points_px"][0], corner),
                          np.subtract(marker["mark_points_px"][2], corner))


def test_failed_hard_projection_does_not_write_coordinates(tmp_path, monkeypatch) -> None:
    import geoagent.state.rectify as module
    state, *_ = _corner_state(tmp_path)
    before = {oid: dict(obj.coords) for oid, obj in state.objects.items()}

    def fail(*args, **kwargs):
        raise ValueError("inconsistent constraints")

    monkeypatch.setattr(module, "_project_right_angles", fail)
    report = rectify_right_angles(state)
    assert not report["ok"]
    assert not report["applied"]
    assert report["reason"] == "constraint_projection_failed"
    assert {oid: dict(obj.coords) for oid, obj in state.objects.items()} == before
