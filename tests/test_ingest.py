from __future__ import annotations

from geoagent.orchestration.ingest import ingest_cv_result
from geoagent.state.schemas import GeometricEvidenceState


def _state(tmp_path) -> GeometricEvidenceState:
    return GeometricEvidenceState(image_path=str(tmp_path / "img.png"), image_size={"width": 574, "height": 367})


def test_ingest_lines_creates_segment_objects(tmp_path) -> None:
    state = _state(tmp_path)
    payload = {
        "ok": True,
        "purpose": "detect lines",
        "results": {
            "count": 1,
            "segments": [
                {
                    "a_px": [50.0, 301.0],
                    "b_px": [525.0, 301.0],
                    "a_norm": [0.087, 0.82],
                    "b_norm": [0.915, 0.82],
                    "length_px": 475.0,
                    "angle_deg": 0.0,
                    "style": "solid",
                    "style_metrics": {"ink_support": 1.0},
                    "style_notes": [],
                }
            ],
        },
    }
    added = ingest_cv_result(state, "detect_lines", {}, payload)
    assert added == ["seg_01"]
    assert state.objects["seg_01"].type == "segment"
    assert state.objects["seg_01"].style["line"] == "solid"
    assert len(state.cv_runs) == 1


def test_ingest_binding_links_labels_to_points(tmp_path) -> None:
    state = _state(tmp_path)
    payload = {
        "ok": True,
        "results": {
            "count": 2,
            "points": [
                {"id": "point_01", "coords_px": [287.4, 300.6]},
                {"id": "point_02", "coords_px": [287.0, 63.2]},
            ],
            "labels": [
                {"id": "label_01", "chosen": "O", "box_px": [270, 310, 300, 340], "top": [{"ncc": 0.93}]},
                {"id": "label_02", "chosen": "P", "box_px": [278, 40, 300, 70], "top": [{"ncc": 0.91}]},
            ],
            "bindings": [
                {"char": "O", "point_id": "point_01", "distance_px": 12.0},
                {"char": "P", "point_id": "point_02", "distance_px": 9.0},
            ],
        },
    }
    added = ingest_cv_result(state, "bind_point_labels", {}, payload)
    assert "point_01" in added and "point_02" in added
    assert state.label_bindings == {"O": "point_01", "P": "point_02"}
    assert state.objects["point_01"].label == "O"
    assert any(r.relation == "labels_point" for r in state.relations.values())


def test_failed_tool_is_recorded_as_evidence(tmp_path) -> None:
    state = _state(tmp_path)
    ingest_cv_result(state, "detect_circles", {}, {"ok": False, "error": "no image", "results": {}})
    assert state.cv_runs and state.cv_runs[-1]["ok"] is False
    assert any("failed" in record.summary for record in state.evidence.values())
