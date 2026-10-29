"""Translate raw CV-tool payloads into GES objects/relations/evidence.

Kept deliberately mechanical: the deterministic code owns *provenance*, while
the geometry agent owns interpretation (merging, inferring relations).
"""
from __future__ import annotations

from typing import Any

from ..state.schemas import GeometryObject, GeometricEvidenceState, Relation


def _result_payload(tool_result: dict[str, Any]) -> dict[str, Any]:
    return tool_result.get("results", {}) if isinstance(tool_result, dict) else {}


def ingest_cv_result(
    state: GeometricEvidenceState,
    tool_name: str,
    params: dict[str, Any],
    result: dict[str, Any],
) -> list[str]:
    """Store CV evidence and return a list of object ids that were added."""
    payload = _result_payload(result)
    added: list[str] = []
    ok = bool(result.get("ok", True))

    state.add_cv_run(
        {
            "tool": tool_name,
            "params": params,
            "purpose": result.get("purpose"),
            "ok": ok,
            "count": payload.get("count"),
            "visualization": result.get("visualization"),
            "error": result.get("error"),
        }
    )
    if not ok:
        state.add_evidence(
            source="cv_tool",
            method=tool_name,
            summary=f"{tool_name} failed: {result.get('error', 'unknown error')}",
            payload={"params": params},
        )
        return added

    if tool_name in ("detect_lines", "merge_collinear_segments", "analyze_line_style"):
        segments = payload.get("segments", [])
        for index, seg in enumerate(segments, start=1):
            obj_id = f"seg_{index:02d}"
            state.add_object(
                GeometryObject(
                    id=obj_id,
                    type="segment",
                    coords={
                        "a_px": seg.get("a_px"),
                        "b_px": seg.get("b_px"),
                        "length_px": seg.get("length_px"),
                        "angle_deg": seg.get("angle_deg"),
                    },
                    normalized={"a": seg.get("a_norm"), "b": seg.get("b_norm")},
                    style={
                        "line": seg.get("style", "uncertain"),
                        "metrics": seg.get("style_metrics", {}),
                        "notes": seg.get("style_notes", []),
                    },
                    source=f"cv:{tool_name}",
                    status="candidate",
                    notes=[str(n) for n in seg.get("style_notes", [])],
                    attributes={
                        "detection_kind": seg.get("detection_kind"),
                        "hough_parts": seg.get("hough_parts"),
                    },
                )
            )
            added.append(obj_id)

    elif tool_name in ("detect_circles", "fit_arcs", "extract_visible_arc"):
        circles = payload.get("circles", [])
        if not circles and payload.get("center"):
            circles = [payload]
        for index, circ in enumerate(circles, start=1):
            obj_id = f"circle_{index:02d}"
            state.add_object(
                GeometryObject(
                    id=obj_id,
                    type="circle" if circ.get("full_circle") else "arc",
                    coords={
                        "center_px": circ.get("center_px"),
                        "radius_px": circ.get("radius_px"),
                        "visible_ranges_deg": circ.get("visible_ranges_deg"),
                        "visible_span_deg": circ.get("visible_span_deg"),
                    },
                    normalized={"center": circ.get("center_norm"), "radius": circ.get("radius_norm")},
                    source=f"cv:{tool_name}",
                    status="candidate",
                    notes=[str(circ.get("method", ""))],
                    attributes={"ink_coverage": circ.get("ink_coverage"), "angle_frame": circ.get("angle_frame")},
                )
            )
            added.append(obj_id)

    elif tool_name == "detect_right_angle_marker":
        for index, marker in enumerate(payload.get("markers", []), start=1):
            obj_id = f"right_angle_{index:02d}"
            state.add_object(
                GeometryObject(
                    id=obj_id,
                    type="right_angle",
                    coords={
                        "vertex_px": marker.get("vertex_px"),
                        "mark_points_px": marker.get("mark_points_px"),
                        "side_length_px": marker.get("side_length_px"),
                    },
                    source=f"cv:{tool_name}",
                    status="confirmed" if marker.get("evidence") else "candidate",
                    attributes={"evidence": marker.get("evidence")},
                    notes=[marker.get("note", "")],
                )
            )
            added.append(obj_id)

    elif tool_name in ("extract_label_candidates", "match_label_templates"):
        labels = payload.get("labels") or payload.get("matches") or []
        for index, lab in enumerate(labels, start=1):
            box = lab.get("box_px") or lab.get("bbox") or [0, 0, 0, 0]
            obj_id = f"label_{index:02d}"
            state.add_object(
                GeometryObject(
                    id=obj_id,
                    type="label",
                    label=lab.get("chosen"),
                    coords={"box_px": box, "centroid_px": lab.get("centroid_px")},
                    source=f"cv:{tool_name}",
                    status="candidate",
                    attributes={
                        "ncc": lab.get("ncc") or lab.get("top"),
                        "alternatives": lab.get("alternatives") or lab.get("top"),
                        "ambiguous": lab.get("ambiguous"),
                        "possible_point_marker": lab.get("possible_point_marker"),
                    },
                )
            )
            added.append(obj_id)

    elif tool_name == "bind_point_labels":
        for index, point in enumerate(payload.get("points", []), start=1):
            coords = point.get("coords_px") or point.get("coords")
            if not coords:
                continue
            obj_id = str(point.get("id") or f"point_{index:02d}")
            state.add_object(
                GeometryObject(
                    id=obj_id,
                    type="point",
                    coords={"px": coords},
                    source=f"cv:{tool_name}",
                    status="candidate",
                )
            )
            added.append(obj_id)
        for index, lab in enumerate(payload.get("labels", []), start=1):
            if not lab.get("chosen") or lab.get("chosen") == "?":
                continue
            obj_id = str(lab.get("id") or f"label_{index:02d}")
            state.add_object(
                GeometryObject(
                    id=obj_id,
                    type="label",
                    label=lab.get("chosen"),
                    coords={"box_px": lab.get("box_px"), "centroid_px": lab.get("centroid_px")},
                    source=f"cv:{tool_name}",
                    status="candidate",
                    attributes={
                        "ncc": (lab.get("top") or [{}])[0].get("ncc"),
                        "alternatives": lab.get("top"),
                        "ambiguous": lab.get("ambiguous"),
                    },
                )
            )
            added.append(obj_id)
        for binding in payload.get("bindings", []):
            char = binding.get("char")
            point_id = binding.get("point_id")
            if char and point_id:
                state.label_bindings[char] = point_id
                point_obj = state.objects.get(point_id)
                if point_obj is not None:
                    point_obj.label = char
                state.add_relation(
                    Relation(
                        id=f"rel_label_{char}",
                        subject=f"label_{char}",
                        relation="labels_point",
                        object=point_id,
                        source="bind_point_labels",
                        evidence=f"Hungarian assignment distance={binding.get('distance_px')}px",
                        status="candidate",
                    )
                )

    state.add_evidence(
        source="cv_tool",
        method=tool_name,
        summary=f"{tool_name} produced {payload.get('count', len(added))} result(s)",
        payload={"params": params, "tool": tool_name},
    )
    return added
