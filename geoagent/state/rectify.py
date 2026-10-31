"""Deterministic right-angle rectification for the Geometric Evidence State.

The source figure and its LaTeX are exact: when ``detect_right_angle_marker``
verified the small square mark, the two incident edges are truly perpendicular.
CV endpoints still carry a few pixels of fitting noise, so this module solves a
small least-squares problem over segment endpoints and right-angle vertices and
moves them the minimum amount needed for every verified marker to be exactly
90 degrees.

It is deliberately conservative:

* only markers with CV square-ink evidence are used (never an inferred angle);
* a marker whose measured angle is already far from 90 is left alone;
* a solution that would move any participating endpoint more than
  ``max_shift_px`` is rejected instead of applied;
* object ids, types, styles, statuses and relations are never modified.

The corrected coordinates are written back into the GES and traced through
``object.notes``, ``state.evidence`` and ``state.meta["rectification"]``.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np
from scipy.optimize import least_squares

from ..cv_tools.common import normalize_point, point_segment_distance
from .schemas import GeometricEvidenceState

_EPS = 1e-9
_ARM_MATCH_COS = math.cos(math.radians(30.0))  # arm direction match tolerance
_LENGTH_WEIGHT = 0.2  # soft, prevents arms collapsing onto the vertex
_COLLINEAR_WEIGHT = 10.0  # keeps a T-junction foot exactly on its base line
_ANCHOR_WEIGHT = 1.0
_ANGLE_WEIGHT = 50.0  # px per degree; exactness dominates the position anchors
_CONSTRAINT_TOL_PX = 1e-10


def _project_right_angles(x, seg_nodes, ra_nodes, right_angles):
    """Project the layout seed onto equality constraints, without anchor penalties.

    Each Newton step is the minimum-norm coordinate correction. SVD handles
    dependent constraints (for example the four corners of a rectangle).
    A nonconvergent/degenerate projection must never be written to the GES.
    """
    x = np.asarray(x, float).copy()
    scales = []
    for ra, vertex in zip(right_angles, ra_nodes):
        pos = x.reshape(-1, 2)
        far = [seg_nodes[arm["seg_id"]][arm["far"]] for arm in ra["arms"]]
        scales.append(max(1.0, math.sqrt(
            np.linalg.norm(pos[far[0]] - pos[vertex])
            * np.linalg.norm(pos[far[1]] - pos[vertex])
        )))

    def constraints(value):
        pos = value.reshape(-1, 2)
        rows, jac = [], []
        for ra, vertex, scale in zip(right_angles, ra_nodes, scales):
            far = [seg_nodes[arm["seg_id"]][arm["far"]] for arm in ra["arms"]]
            u, v = pos[far[0]] - pos[vertex], pos[far[1]] - pos[vertex]
            if min(np.linalg.norm(u), np.linalg.norm(v)) < 1.0:
                raise ValueError("degenerate right-angle arm")
            row = np.zeros_like(pos)
            row[far[0]] += v / scale
            row[far[1]] += u / scale
            row[vertex] -= (u + v) / scale
            rows.append(float(u @ v) / scale)
            jac.append(row.ravel())
            for arm in ra["arms"]:
                if arm["kind"] != "through":
                    continue
                a, b = seg_nodes[arm["seg_id"]]
                edge, offset = pos[b] - pos[a], pos[vertex] - pos[a]
                length = float(np.linalg.norm(edge))
                if length < 1.0:
                    raise ValueError("degenerate base")
                # Fixed denominator per linearisation; the zero set is unchanged.
                row = np.zeros_like(pos)
                gb = np.array([offset[1], -offset[0]]) / length
                gv = np.array([-edge[1], edge[0]]) / length
                row[b] += gb
                row[vertex] += gv
                row[a] -= gb + gv
                rows.append(float(edge[0] * offset[1] - edge[1] * offset[0]) / length)
                jac.append(row.ravel())
        return np.asarray(rows), np.asarray(jac)

    for _ in range(30):
        residual, jac = constraints(x)
        if np.max(np.abs(residual), initial=0.0) <= _CONSTRAINT_TOL_PX:
            return x
        # Near a rectangle one equality becomes dependent on the others.
        # Discard that nearly-null direction instead of collapsing the shape.
        delta = np.linalg.lstsq(jac, -residual, rcond=1e-6)[0]
        if not np.all(np.isfinite(delta)):
            break
        x += delta
    raise ValueError("right-angle equality constraints did not converge")


# --------------------------------------------------------------------------- #
# small vector helpers
# --------------------------------------------------------------------------- #
def _point(value: Any) -> np.ndarray | None:
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        try:
            x, y = float(value[0]), float(value[1])
        except (TypeError, ValueError):
            return None
        if math.isfinite(x) and math.isfinite(y):
            return np.array([x, y], float)
    return None


def _unit(vec: np.ndarray) -> np.ndarray | None:
    norm = float(np.linalg.norm(vec))
    if norm < _EPS:
        return None
    return vec / norm


def _signed_angle_deg(d1: np.ndarray, d2: np.ndarray) -> float:
    cross = float(d1[0] * d2[1] - d1[1] * d2[0])
    dot = float(d1 @ d2)
    return math.degrees(math.atan2(cross, dot))


def _perpendicular_error_deg(angle_deg: float) -> float:
    """Signed distance from the nearest multiple of 90 degrees, in [-90, 90]."""
    err = (angle_deg - 90.0) % 180.0
    if err > 90.0:
        err -= 180.0
    return err


def _angle_between_deg(d1: np.ndarray, d2: np.ndarray) -> float:
    cos = float(np.clip(abs(d1 @ d2), -1.0, 1.0))
    return math.degrees(math.acos(cos))


def _coords_point(coords: dict[str, Any], *keys: str) -> np.ndarray | None:
    for key in keys:
        point = _point(coords.get(key))
        if point is not None:
            return point
    return None


# --------------------------------------------------------------------------- #
# tolerances
# --------------------------------------------------------------------------- #
def _cap_height(state: GeometricEvidenceState) -> float:
    heights: list[float] = []
    for obj in state.objects.values():
        if obj.type != "label":
            continue
        box = obj.coords.get("box_px")
        if isinstance(box, (list, tuple)) and len(box) == 4:
            try:
                height = abs(float(box[3]) - float(box[1]))
            except (TypeError, ValueError):
                continue
            if 5.0 <= height <= 80.0:
                heights.append(height)
    if not heights:
        return 20.0
    return float(np.clip(np.median(heights), 10.0, 40.0))


# --------------------------------------------------------------------------- #
# marker / segment association
# --------------------------------------------------------------------------- #
def _segment_record(obj: Any) -> tuple[np.ndarray, np.ndarray] | None:
    if obj.type not in ("segment", "line"):
        return None
    a = _coords_point(obj.coords, "a_px", "a")
    b = _coords_point(obj.coords, "b_px", "b")
    if a is None or b is None or float(np.linalg.norm(b - a)) < 1.0:
        return None
    return a, b


def _marker_arms(obj: Any, cap_h: float) -> tuple[np.ndarray, np.ndarray, np.ndarray, float] | None:
    vertex = _coords_point(obj.coords, "vertex_px", "vertex")
    mark = obj.coords.get("mark_points_px") or obj.coords.get("mark_points")
    if vertex is None or not isinstance(mark, (list, tuple)) or len(mark) < 3:
        return None
    p1, p3 = _point(mark[0]), _point(mark[2])
    if p1 is None or p3 is None:
        return None
    u1, u2 = _unit(p1 - vertex), _unit(p3 - vertex)
    if u1 is None or u2 is None:
        return None
    try:
        side = float(obj.coords.get("side_length_px"))
    except (TypeError, ValueError):
        side = 0.0
    if side < max(4.0, 0.35 * cap_h):
        side = max(4.0, 0.5 * cap_h)
    return vertex, u1, u2, side


def _arm_candidates(
    segments: list[tuple[str, np.ndarray, np.ndarray]],
    vertex: np.ndarray,
    target: np.ndarray,
    tol: float,
    min_arm: float,
) -> list[dict[str, Any]]:
    """Segments whose direction matches ``target`` and that touch ``vertex``."""
    out: list[dict[str, Any]] = []
    for seg_id, a, b in segments:
        da, db = a - vertex, b - vertex
        near_a = float(np.linalg.norm(da)) <= tol
        near_b = float(np.linalg.norm(db)) <= tol
        if near_a and near_b:
            continue  # degenerate: both endpoints at the vertex
        if near_a or near_b:
            near_idx, far_idx = (0, 1) if near_a else (1, 0)
            far = b if far_idx == 1 else a
            direction = _unit(far - vertex)
            length = float(np.linalg.norm(far - vertex))
            if direction is None or length < min_arm:
                continue
            dot = float(direction @ target)
            if dot < _ARM_MATCH_COS:
                continue
            out.append(
                {
                    "seg_id": seg_id,
                    "kind": "end",
                    "far": far_idx,
                    "near": near_idx,
                    "direction": direction,
                    "dot": dot,
                    "distance": float(np.linalg.norm(da if near_idx == 0 else db)),
                    "length": length,
                }
            )
            continue

        # Through segment (altitude foot / T junction): V lies on the span.
        if float(point_segment_distance(vertex, a, b)) > tol:
            continue
        ab = b - a
        span = float(np.linalg.norm(ab))
        t = float((vertex - a) @ ab) / max(span * span, _EPS)
        margin = tol / max(span, _EPS)
        if not (-margin <= t <= 1.0 + margin):
            continue
        for direction, far_idx, near_idx in ((_unit(ab), 1, 0), (-_unit(ab), 0, 1)):
            if direction is None:
                continue
            far = b if far_idx == 1 else a
            length = float((far - vertex) @ direction)
            if length < min_arm:
                continue
            dot = abs(float(direction @ target))
            if dot < _ARM_MATCH_COS:
                continue
            out.append(
                {
                    "seg_id": seg_id,
                    "kind": "through",
                    "far": far_idx,
                    "near": near_idx,
                    "direction": direction,
                    "dot": dot,
                    "distance": float(point_segment_distance(vertex, a, b)),
                    "length": length,
                }
            )
            break  # one direction per segment; the other is the same line
    return out


def _pick_arm(
    candidates: list[dict[str, Any]],
    used: set[str],
) -> tuple[dict[str, Any] | None, str | None]:
    best_per_segment: dict[str, dict[str, Any]] = {}
    for cand in candidates:
        if cand["seg_id"] in used:
            continue
        current = best_per_segment.get(cand["seg_id"])
        if current is None or (cand["dot"], cand["length"]) > (current["dot"], current["length"]):
            best_per_segment[cand["seg_id"]] = cand

    ranked = sorted(
        best_per_segment.values(),
        key=lambda c: (-c["dot"], c["distance"], -c["length"], c["seg_id"]),
    )
    if not ranked:
        return None, "no_incident_segment"
    top = ranked[0]
    if len(ranked) >= 2:
        second = ranked[1]
        if (
            top["dot"] - second["dot"] < 0.02
            and _angle_between_deg(top["direction"], second["direction"]) > 5.0
        ):
            return None, "ambiguous_arm"
    return top, None


def _has_marker_evidence(obj: Any) -> bool:
    if obj.status not in ("confirmed", "candidate"):
        return False
    if str(obj.source).startswith("cv:"):
        return True
    evidence = obj.attributes.get("evidence") if isinstance(obj.attributes, dict) else None
    return bool(evidence)


def _collect_right_angles(
    state: GeometricEvidenceState,
    cap_h: float,
    tol: float,
    min_arm: float,
    angle_tol_deg: float,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    segments = []
    for obj in sorted(state.objects.values(), key=lambda o: o.id):
        record = _segment_record(obj)
        if record is not None:
            segments.append((obj.id, record[0], record[1]))

    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for obj in sorted(state.objects.values(), key=lambda o: o.id):
        if obj.type != "right_angle":
            continue
        if not _has_marker_evidence(obj):
            rejected.append({"object_id": obj.id, "reason": "no_marker_evidence"})
            continue
        arms = _marker_arms(obj, cap_h)
        if arms is None:
            rejected.append({"object_id": obj.id, "reason": "degenerate_marker"})
            continue
        vertex, u1, u2, side = arms
        arm1, err1 = _pick_arm(_arm_candidates(segments, vertex, u1, tol, min_arm), set())
        if arm1 is None:
            rejected.append({"object_id": obj.id, "reason": err1 or "missing_arm"})
            continue
        arm2, err2 = _pick_arm(
            _arm_candidates(segments, vertex, u2, tol, min_arm), {arm1["seg_id"]}
        )
        if arm2 is None:
            rejected.append({"object_id": obj.id, "reason": err2 or "missing_arm"})
            continue

        angle = _signed_angle_deg(arm1["direction"], arm2["direction"])
        err = _perpendicular_error_deg(angle)
        if abs(err) > angle_tol_deg:
            rejected.append(
                {
                    "object_id": obj.id,
                    "reason": "initial_angle_off",
                    "initial_angle_deg": round(angle, 2),
                }
            )
            continue
        accepted.append(
            {
                "object": obj,
                "object_id": obj.id,
                "vertex": vertex,
                "u1": u1,
                "u2": u2,
                "side": side,
                "arms": [arm1, arm2],
                "initial_angle_deg": angle,
                "err_deg": err,
            }
        )
    return accepted, rejected


# --------------------------------------------------------------------------- #
# nodes and solve
# --------------------------------------------------------------------------- #
def _build_nodes(
    state: GeometricEvidenceState,
    right_angles: list[dict[str, Any]],
    tol: float,
) -> tuple[list[np.ndarray], dict[str, list[int]], list[int], list[dict[str, Any]]]:
    """Cluster segment endpoints and right-angle vertices into graph nodes."""
    clusters: list[dict[str, Any]] = []
    seg_nodes: dict[str, list[int]] = {}

    def add_cluster(position: np.ndarray) -> int:
        clusters.append({"positions": [position.copy()]})
        return len(clusters) - 1

    def nearest(position: np.ndarray) -> int | None:
        best, best_d = None, tol
        for idx, cluster in enumerate(clusters):
            centre = np.mean(np.vstack(cluster["positions"]), axis=0)
            distance = float(np.linalg.norm(centre - position))
            if distance <= best_d:
                best, best_d = idx, distance
        return best

    for obj in sorted(state.objects.values(), key=lambda o: o.id):
        record = _segment_record(obj)
        if record is None:
            continue
        nodes: list[int] = []
        for position in record:
            idx = nearest(position)
            if idx is None:
                idx = add_cluster(position)
            clusters[idx]["positions"].append(position.copy())
            nodes.append(idx)
        seg_nodes[obj.id] = nodes

    ra_nodes: list[int] = []
    ra_vertices: dict[int, list[np.ndarray]] = {}
    for ra in right_angles:
        vertex = ra["vertex"]
        idx = nearest(vertex)
        if idx is None:
            idx = add_cluster(vertex)
        else:
            clusters[idx]["positions"].append(vertex.copy())
        ra_nodes.append(idx)
        ra_vertices.setdefault(idx, []).append(vertex.copy())

    # An end arm's near endpoint *is* the right-angle vertex. Greedy clustering
    # can put them in different clusters when another endpoint sits equally
    # close (e.g. a line overshooting the corner by a few pixels), so merge the
    # two clusters explicitly rather than relying on proximity alone.
    parent = list(range(len(clusters)))

    def find(idx: int) -> int:
        while parent[idx] != idx:
            parent[idx] = parent[parent[idx]]
            idx = parent[idx]
        return idx

    def union(left: int, right: int) -> None:
        root_l, root_r = find(left), find(right)
        if root_l != root_r:
            parent[root_r] = root_l

    for ra, node in zip(right_angles, ra_nodes):
        for arm in ra["arms"]:
            if arm["kind"] == "end":
                union(node, seg_nodes[arm["seg_id"]][arm["near"]])

    members: dict[int, list[int]] = {}
    for idx in range(len(clusters)):
        members.setdefault(find(idx), []).append(idx)
    remap: dict[int, int] = {}
    merged: list[dict[str, Any]] = []
    for root, indices in members.items():
        remap[root] = len(merged)
        positions = [p for idx in indices for p in clusters[idx]["positions"]]
        # A verified marker vertex is the reliable corner: the ink square is
        # drawn at the line intersection, while an incident stroke may stop a
        # few pixels short of it because the square obscures its end. Anchor
        # this node on the vertex and let the stroke snap to it, instead of
        # averaging the two and dragging the corner off the printed square.
        vertices = [v for idx in indices for v in ra_vertices.get(idx, [])]
        target = np.mean(np.vstack(vertices), axis=0) if vertices else None
        merged.append({"positions": positions, "target": target})
    clusters = merged
    seg_nodes = {
        seg_id: [remap[find(node)] for node in nodes] for seg_id, nodes in seg_nodes.items()
    }
    ra_nodes = [remap[find(node)] for node in ra_nodes]

    centres = [
        cluster["target"]
        if cluster["target"] is not None
        else np.mean(np.vstack(cluster["positions"]), axis=0)
        for cluster in clusters
    ]
    return centres, seg_nodes, ra_nodes, clusters


def _validate_topology(
    right_angles: list[dict[str, Any]],
    seg_nodes: dict[str, list[int]],
    ra_nodes: list[int],
) -> list[bool]:
    """An end arm must share the vertex node; a through arm must not."""
    keep: list[bool] = []
    for ra, node in zip(right_angles, ra_nodes):
        valid = True
        for arm in ra["arms"]:
            nodes = seg_nodes.get(arm["seg_id"])
            if nodes is None:
                valid = False
                break
            if arm["kind"] == "end":
                if nodes[arm["near"]] != node:
                    valid = False
                    break
            else:
                if node in nodes:
                    valid = False
                    break
        keep.append(valid)
    return keep


def _solve(
    centres: list[np.ndarray],
    seg_nodes: dict[str, list[int]],
    ra_nodes: list[int],
    right_angles: list[dict[str, Any]],
    segment_lengths: dict[str, float],
) -> tuple[np.ndarray, np.ndarray]:
    x0 = np.concatenate([np.asarray(c, float) for c in centres])

    def positions(x: np.ndarray) -> np.ndarray:
        return x.reshape(-1, 2)

    def arm_vector(pos: np.ndarray, ra_node: int, ra: dict[str, Any], arm: dict[str, Any]) -> np.ndarray:
        nodes = seg_nodes[arm["seg_id"]]
        far = pos[nodes[arm["far"]]]
        return far - pos[ra_node]

    def residuals(x: np.ndarray) -> np.ndarray:
        pos = positions(x)
        rows: list[float] = []
        rows.extend(((pos - np.vstack(centres)) * _ANCHOR_WEIGHT).ravel().tolist())
        for ra, ra_node in zip(right_angles, ra_nodes):
            d1 = arm_vector(pos, ra_node, ra, ra["arms"][0])
            d2 = arm_vector(pos, ra_node, ra, ra["arms"][1])
            n1, n2 = float(np.linalg.norm(d1)), float(np.linalg.norm(d2))
            if n1 < _EPS or n2 < _EPS:
                rows.append(1e4)
            else:
                angle = _signed_angle_deg(d1, d2)
                rows.append(_perpendicular_error_deg(angle) * _ANGLE_WEIGHT)
            for arm in ra["arms"]:
                if arm["kind"] != "through":
                    continue
                nodes = seg_nodes[arm["seg_id"]]
                a, b = pos[nodes[0]], pos[nodes[1]]
                unit = _unit(b - a)
                if unit is None:
                    rows.append(1e4)
                else:
                    vertex = pos[ra_node]
                    cross = float(unit[0] * (vertex - a)[1] - unit[1] * (vertex - a)[0])
                    rows.append(cross * _COLLINEAR_WEIGHT)
            for arm in ra["arms"]:
                nodes = seg_nodes[arm["seg_id"]]
                length = float(np.linalg.norm(pos[nodes[1]] - pos[nodes[0]]))
                rows.append((length - segment_lengths.get(arm["seg_id"], length)) * _LENGTH_WEIGHT)
        return np.asarray(rows, float)

    result = least_squares(
        residuals,
        x0,
        method="trf",
        max_nfev=200,
        ftol=1e-10,
        xtol=1e-10,
        gtol=1e-10,
    )
    # Position and length penalties choose a nearby layout only. The final
    # result must satisfy perpendicularity and foot-on-base equalities.
    return x0, _project_right_angles(result.x, seg_nodes, ra_nodes, right_angles)


def _ra_participating_nodes(ra: dict[str, Any], ra_node: int, seg_nodes: dict[str, list[int]]) -> set[int]:
    nodes = {ra_node}
    for arm in ra["arms"]:
        nodes.update(seg_nodes[arm["seg_id"]])
    return nodes


def _ra_angle(ra: dict[str, Any], pos: np.ndarray, ra_node: int, seg_nodes: dict[str, list[int]]) -> float:
    d1 = pos[seg_nodes[ra["arms"][0]["seg_id"]][ra["arms"][0]["far"]]] - pos[ra_node]
    d2 = pos[seg_nodes[ra["arms"][1]["seg_id"]][ra["arms"][1]["far"]]] - pos[ra_node]
    return _signed_angle_deg(d1, d2)


# --------------------------------------------------------------------------- #
# write-back
# --------------------------------------------------------------------------- #
def _note(obj: Any, text: str) -> None:
    if not any(n.startswith("rectify:") for n in obj.notes):
        obj.notes.append(text)


def _apply(
    state: GeometricEvidenceState,
    right_angles: list[dict[str, Any]],
    ra_nodes: list[int],
    centres: list[np.ndarray],
    solved: np.ndarray,
    seg_nodes: dict[str, list[int]],
    tolerance_px: float,
) -> dict[str, Any]:
    pos = solved.reshape(-1, 2)
    displacement = np.linalg.norm(pos - np.vstack(centres), axis=1)
    moved_nodes = {idx for idx, value in enumerate(displacement) if value > _CONSTRAINT_TOL_PX}
    width = int(state.image_size.get("width") or 0)
    height = int(state.image_size.get("height") or 0)
    changed_objects: set[str] = set()
    max_endpoint_move = 0.0

    for obj in sorted(state.objects.values(), key=lambda o: o.id):
        nodes = seg_nodes.get(obj.id)
        if nodes is None:
            continue
        a, b = pos[nodes[0]], pos[nodes[1]]
        old_a = _coords_point(obj.coords, "a_px", "a")
        old_b = _coords_point(obj.coords, "b_px", "b")
        # Endpoint movement, not node displacement: an endpoint that was
        # trimmed by a marker square snaps to the vertex even when the solved
        # node itself barely moves.
        move_a = float(np.linalg.norm(a - old_a)) if old_a is not None else 0.0
        move_b = float(np.linalg.norm(b - old_b)) if old_b is not None else 0.0
        endpoint_move = max(move_a, move_b)
        if endpoint_move <= _CONSTRAINT_TOL_PX:
            continue
        obj.coords["a_px"] = a.tolist()
        obj.coords["b_px"] = b.tolist()
        # keep legacy keys consistent when a geometry-agent segment used them
        if "a" in obj.coords:
            obj.coords["a"] = list(obj.coords["a_px"])
        if "b" in obj.coords:
            obj.coords["b"] = list(obj.coords["b_px"])
        obj.coords["length_px"] = round(float(np.linalg.norm(b - a)), 2)
        obj.coords["angle_deg"] = round(math.degrees(math.atan2(b[1] - a[1], b[0] - a[0])) % 180.0, 2)
        if width > 0 and height > 0:
            obj.normalized["a"] = normalize_point(a[0], a[1], width, height)
            obj.normalized["b"] = normalize_point(b[0], b[1], width, height)
        _note(obj, f"rectify: endpoint adjusted {endpoint_move:.2f} px")
        changed_objects.add(obj.id)
        max_endpoint_move = max(max_endpoint_move, endpoint_move)

    for ra, ra_node in zip(right_angles, ra_nodes):
        obj = ra["object"]
        vertex = pos[ra_node]
        solved_arms = []
        for arm, original in zip(ra["arms"], (ra["u1"], ra["u2"])):
            far_node = seg_nodes[arm["seg_id"]][arm["far"]]
            direction = _unit(pos[far_node] - vertex)
            if direction is None:
                direction = original
            if float(direction @ original) < 0:
                direction = -direction
            solved_arms.append(direction)
        side = ra["side"]
        p1 = vertex + side * solved_arms[0]
        p3 = vertex + side * solved_arms[1]
        p2 = p1 + p3 - vertex
        obj.coords["vertex_px"] = vertex.tolist()
        obj.coords["mark_points_px"] = [p.tolist() for p in (p1, p2, p3)]
        shift = max(float(displacement[idx]) for idx in _ra_participating_nodes(ra, ra_node, seg_nodes))
        _note(obj, f"rectify: {ra['initial_angle_deg']:.1f}° -> 90.0°, max shift {shift:.2f} px")
        changed_objects.add(obj.id)

    # Labelled vertices (separate point objects) follow their corrected node.
    for obj in sorted(state.objects.values(), key=lambda o: o.id):
        if obj.type != "point" or obj.id in changed_objects:
            continue
        px = _coords_point(obj.coords, "px", "point")
        if px is None:
            continue
        for node in moved_nodes:
            if float(np.linalg.norm(centres[node] - px)) <= tolerance_px:
                obj.coords["px"] = pos[node].tolist()
                _note(obj, f"rectify: follows vertex, moved {float(displacement[node]):.2f} px")
                changed_objects.add(obj.id)
                break

    return {
        "moved_nodes": len(moved_nodes),
        "max_shift_px": round(float(displacement.max()) if len(displacement) else 0.0, 3),
        "max_endpoint_move_px": round(max_endpoint_move, 3),
        "changed_objects": len(changed_objects),
        "changed_object_ids": sorted(changed_objects),
    }


# --------------------------------------------------------------------------- #
# public entry point
# --------------------------------------------------------------------------- #
def _store_rectification(
    state: GeometricEvidenceState, report: dict[str, Any], *, applied: bool | None = None
) -> int:
    """Persist the report in ``meta`` while preserving the revision counter."""
    if applied is None:
        applied = bool(report.get("applied"))
    previous = state.meta.get("rectification") or {}
    try:
        revision = int(previous.get("revision", 0) or 0)
    except (TypeError, ValueError):
        revision = 0
    if applied:
        revision += 1
    report["revision"] = revision
    state.meta["rectification"] = report
    return revision


def rectify_right_angles(
    state: GeometricEvidenceState,
    *,
    tolerance_px: float | None = None,
    max_shift_px: float | None = None,
    angle_tol_deg: float = 12.0,
    min_arm_length_px: float | None = None,
    write_back: bool = True,
) -> dict[str, Any]:
    """Make every CV-verified right-angle marker exactly 90 degrees.

    Mutates ``state`` in place (unless ``write_back=False``) and returns a
    compact report. Safe to call repeatedly: the second call is a no-op.
    """
    cap_h = _cap_height(state)
    tol = float(tolerance_px if tolerance_px is not None else max(4.0, 0.4 * cap_h))
    max_shift = float(max_shift_px if max_shift_px is not None else max(3.0, 0.25 * cap_h))
    min_arm = float(min_arm_length_px if min_arm_length_px is not None else max(6.0, 0.6 * cap_h))
    tolerances = {
        "tolerance_px": round(tol, 2),
        "max_shift_px": round(max_shift, 2),
        "min_arm_length_px": round(min_arm, 2),
        "angle_tol_deg": angle_tol_deg,
    }

    marker_count = sum(1 for obj in state.objects.values() if obj.type == "right_angle")
    report: dict[str, Any] = {
        "ok": True,
        "applied": False,
        "reason": "",
        "cap_h_px": round(cap_h, 2),
        "tolerances": tolerances,
        "right_angles": [],
        "rejected": [],
        "constraint_mode": "hard_projection",
        "constraint_tolerance_px": _CONSTRAINT_TOL_PX,
    }
    if marker_count == 0:
        report["reason"] = "no_right_angles"
        _store_rectification(state, report)
        return report

    right_angles, rejected = _collect_right_angles(state, cap_h, tol, min_arm, angle_tol_deg)
    if not right_angles:
        report["reason"] = "no_rectifiable_right_angles"
        report["rejected"] = rejected
        _store_rectification(state, report)
        return report

    centres, seg_nodes, ra_nodes, _clusters = _build_nodes(state, right_angles, tol)
    valid = _validate_topology(right_angles, seg_nodes, ra_nodes)
    kept_ra, kept_nodes = [], []
    for ra, node, ok in zip(right_angles, ra_nodes, valid):
        if ok:
            kept_ra.append(ra)
            kept_nodes.append(node)
        else:
            rejected.append({"object_id": ra["object_id"], "reason": "topology_mismatch"})
    right_angles, ra_nodes = kept_ra, kept_nodes
    if not right_angles:
        report["reason"] = "no_rectifiable_right_angles"
        report["rejected"] = rejected
        _store_rectification(state, report)
        return report

    segment_lengths = {}
    for obj in state.objects.values():
        record = _segment_record(obj)
        if record is not None:
            segment_lengths[obj.id] = float(np.linalg.norm(record[1] - record[0]))

    active = list(range(len(right_angles)))
    solved = None
    for _attempt in range(5):
        sub_ra = [right_angles[i] for i in active]
        sub_nodes = [ra_nodes[i] for i in active]
        try:
            _x0, solved = _solve(centres, seg_nodes, sub_nodes, sub_ra, segment_lengths)
        except ValueError as exc:
            report.update(ok=False, reason="constraint_projection_failed", error=str(exc))
            _store_rectification(state, report)
            return report
        displacements = np.linalg.norm(solved.reshape(-1, 2) - np.vstack(centres), axis=1)
        over = []
        for idx in active:
            ra = right_angles[idx]
            node = ra_nodes[idx]
            shift = max(float(displacements[n]) for n in _ra_participating_nodes(ra, node, seg_nodes))
            if shift > max_shift + 1e-9:
                over.append(idx)
        if not over:
            break
        for idx in over:
            report["rejected"].append(
                {"object_id": right_angles[idx]["object_id"], "reason": "max_shift_exceeded"}
            )
        active = [idx for idx in active if idx not in over]
        if not active:
            break
    else:
        # Every attempt still needed an over-tolerance shift: apply nothing.
        active = []

    if not active:
        report["reason"] = "max_shift_exceeded"
        for idx, ra in enumerate(right_angles):
            report["right_angles"].append(
                {
                    "object_id": ra["object_id"],
                    "initial_angle_deg": round(ra["initial_angle_deg"], 2),
                    "status": "skipped",
                    "reason": "max_shift_exceeded",
                }
            )
        _store_rectification(state, report)
        return report

    solved_pos = solved.reshape(-1, 2)
    diffs = np.linalg.norm(solved_pos - np.vstack(centres), axis=1)
    max_move = float(diffs.max()) if len(diffs) else 0.0

    details: list[dict[str, Any]] = []
    for idx in active:
        ra = right_angles[idx]
        node = ra_nodes[idx]
        final_angle = _ra_angle(ra, solved_pos, node, seg_nodes)
        shift = max(float(diffs[n]) for n in _ra_participating_nodes(ra, node, seg_nodes))
        details.append(
            {
                "object_id": ra["object_id"],
                "vertex_px": [round(float(solved_pos[node][0]), 2), round(float(solved_pos[node][1]), 2)],
                "initial_angle_deg": round(ra["initial_angle_deg"], 2),
                "final_angle_deg": round(final_angle, 2),
                "error_deg": round(_perpendicular_error_deg(final_angle), 3),
                "max_shift_px": round(shift, 3),
                "segments": [ra["arms"][0]["seg_id"], ra["arms"][1]["seg_id"]],
                "kinds": [ra["arms"][0]["kind"], ra["arms"][1]["kind"]],
                "status": "applied" if max_move > _CONSTRAINT_TOL_PX else "already_rectified",
            }
        )

    if max_move <= _CONSTRAINT_TOL_PX:
        report["reason"] = "already_rectified"
        report["right_angles"] = details
        _store_rectification(state, report)
        return report

    if not write_back:
        report["applied"] = True
        report["reason"] = "dry_run"
        report["right_angles"] = details
        report["max_shift_px"] = round(max_move, 3)
        _store_rectification(state, report, applied=False)
        return report

    write = _apply(state, sub_ra, sub_nodes, centres, solved, seg_nodes, tol)
    report.update(
        {
            "applied": True,
            "reason": "applied",
            "right_angles": details,
            "max_shift_px": write["max_shift_px"],
            "max_endpoint_move_px": write["max_endpoint_move_px"],
            "moved_nodes": write["moved_nodes"],
            "changed_objects": write["changed_objects"],
            "changed_object_ids": write["changed_object_ids"],
        }
    )
    _store_rectification(state, report)
    state.add_evidence(
        source="right_angle_rectifier",
        method="least_squares layout with hard perpendicular/collinear projection",
        summary=(
            f"{len(details)} right angle(s) rectified, "
            f"max shift {write['max_shift_px']} px"
        ),
        payload=report,
    )
    return report
