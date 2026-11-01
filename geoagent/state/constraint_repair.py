"""Deterministic soft repair of near-satisfied geometric relations.

GES relations come from the Geometry Agent and are not necessarily backed by
pixel evidence. Segment endpoints extracted by CV, on the other hand, carry a
few pixels of fitting noise, so relations the measurement nearly satisfies
(0.2 degrees / 0.2 % by default, matching geom2code's repair stage) can be made
exact by moving points a minimal amount. This module extracts perpendicular,
parallel, equal-length and collinear candidates from pixel geometry alone and
projects them with the Gauss-Seidel solver used by geom2code.

It is deliberately conservative:

* only relations the detected geometry already almost satisfies become
  candidates -- a loosely detected relation would drag points toward a
  relationship the true figure does not have;
* with ``right_angle_mode="lock"`` (the default) segments and vertices that
  participate in a CV-verified right-angle marker are locked and the hard
  rectifier owns them; ``"soft"`` instead turns each marker into a forced
  perpendicular constraint solved here, and ``"ignore"`` skips markers;
* a solution is accepted only when total violation decreases and no point
  moves beyond the pixel/relative displacement gates, otherwise the GES is
  left byte-identical. The gates use the displacement of the *written
  endpoint coordinates*, not the displacement of a cluster centre: merging
  two endpoints into one node can move an endpoint much farther than the
  centre moves;
* the reference LaTeX is never read and no LLM call is made.

The corrected coordinates are written back into the GES and traced through
``object.notes``, ``state.evidence`` and ``state.meta["constraint_repair"]``.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np

from ..cv_tools.common import normalize_point
from .rectify import (
    _build_nodes,
    _cap_height,
    _collect_right_angles,
    _coords_point,
    _segment_record,
)
from .schemas import GeometricEvidenceState

_EPS = 1e-12
_SATISFIED = 1e-6  # geom2code repair_points guard_eps
_MOVED = 1e-9
_SKIP_STATUS = ("rejected", "conflict")
_RIGHT_ANGLE_ANGLE_TOL = 12.0


# --------------------------------------------------------------------------- #
# node graph helpers (shared style with rectify.py)
# --------------------------------------------------------------------------- #
def _attach_points(
    state: GeometricEvidenceState, centres: list[np.ndarray], tol: float
) -> dict[str, int]:
    """Map point objects onto existing nodes, appending new ones when needed.

    Appending never changes existing indices, so ``seg_nodes`` stays valid.
    """
    point_nodes: dict[str, int] = {}
    for obj in sorted(state.objects.values(), key=lambda o: o.id):
        if obj.type != "point":
            continue
        px = _coords_point(obj.coords, "px", "point")
        if px is None:
            continue
        best: tuple[float, int] | None = None
        for idx, centre in enumerate(centres):
            distance = float(np.linalg.norm(centre - px))
            if best is None or distance < best[0]:
                best = (distance, idx)
        if best is not None and best[0] <= tol:
            point_nodes[obj.id] = best[1]
        else:
            centres.append(px.copy())
            point_nodes[obj.id] = len(centres) - 1
    return point_nodes


def _attach_vertices(
    accepted: list[dict[str, Any]], centres: list[np.ndarray], tol: float
) -> list[int]:
    """Map marker vertices onto nodes, appending ones with no nearby node.

    Appending never changes existing indices, so ``seg_nodes`` stays valid.
    """
    nodes: list[int] = []
    for ra in accepted:
        vertex = ra["vertex"]
        best: tuple[float, int] | None = None
        for idx, centre in enumerate(centres):
            distance = float(np.linalg.norm(centre - vertex))
            if best is None or distance < best[0]:
                best = (distance, idx)
        if best is not None and best[0] <= tol:
            nodes.append(best[1])
        else:
            centres.append(np.array(vertex, float, copy=True))
            nodes.append(len(centres) - 1)
    return nodes


def _lock_sets(
    accepted: list[dict[str, Any]],
    tol: float,
    seg_nodes: dict[str, list[int]],
    centres: list[np.ndarray],
) -> tuple[set[str], set[int]]:
    """Segments and nodes owned by CV-verified right-angle markers."""
    locked_segments: set[str] = set()
    locked_nodes: set[int] = set()
    for ra in accepted:
        for arm in ra["arms"]:
            locked_segments.add(arm["seg_id"])
            locked_nodes.update(seg_nodes.get(arm["seg_id"], ()))
        for idx, centre in enumerate(centres):
            if float(np.linalg.norm(centre - ra["vertex"])) <= tol:
                locked_nodes.add(idx)
    return locked_segments, locked_nodes


def _right_angle_relations(
    accepted: list[dict[str, Any]],
    ra_nodes: list[int],
    seg_nodes: dict[str, list[int]],
    positions: np.ndarray,
) -> list[dict[str, Any]]:
    """Marker-verified perpendiculars expressed as ordinary soft constraints.

    ``end`` arms already share the vertex node and need only a ``perp`` pair.
    A ``through`` arm has the vertex inside its span, so an extra collinear
    relation keeps the vertex on that line while the two lines become
    perpendicular.  Both are forced: marker evidence is stronger than the
    near-satisfied pixel tolerances used for the other candidates.
    """
    out: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for ra, vertex_node in zip(accepted, ra_nodes):
        arms = ra["arms"]
        if len(arms) < 2:
            continue
        first, second = arms[0], arms[1]
        nodes1, nodes2 = seg_nodes.get(first["seg_id"]), seg_nodes.get(second["seg_id"])
        if not nodes1 or not nodes2:
            continue
        key = ("perp", *sorted((tuple(sorted(nodes1)), tuple(sorted(nodes2)))))
        if key not in seen:
            seen.add(key)
            out.append({
                "type": "perp",
                "segments": [first["seg_id"], second["seg_id"]],
                "nodes": (nodes1[0], nodes1[1], nodes2[0], nodes2[1]),
                "source": "right_angle_marker",
                "forced": True,
            })
        for arm, nodes in ((first, nodes1), (second, nodes2)):
            if arm.get("kind") != "through":
                continue
            key = ("collinear", vertex_node, arm["seg_id"])
            if key in seen:
                continue
            seen.add(key)
            out.append({
                "type": "collinear",
                "segments": [arm["seg_id"]],
                "nodes": (vertex_node, nodes[0], nodes[0], nodes[1]),
                "source": "right_angle_marker",
                "forced": True,
            })
    return out


def _relation_violation(item: dict[str, Any], positions: np.ndarray) -> float:
    kind = "par" if item["type"] == "collinear" else item["type"]
    return _violation(positions, kind, *item["nodes"])


def _active_segments(
    state: GeometricEvidenceState,
    seg_nodes: dict[str, list[int]],
    positions: np.ndarray,
    min_length: float,
) -> list[tuple[str, int, int]]:
    out: list[tuple[str, int, int]] = []
    for obj in sorted(state.objects.values(), key=lambda o: o.id):
        nodes = seg_nodes.get(obj.id)
        if nodes is None or obj.status in _SKIP_STATUS:
            continue
        length = float(np.linalg.norm(positions[nodes[1]] - positions[nodes[0]]))
        if length < min_length:
            continue
        out.append((obj.id, nodes[0], nodes[1]))
    return out


# --------------------------------------------------------------------------- #
# candidate extraction (pixel geometry only, never state.relations)
# --------------------------------------------------------------------------- #
def _candidates(
    state: GeometricEvidenceState,
    seg_nodes: dict[str, list[int]],
    point_nodes: dict[str, int],
    positions: np.ndarray,
    *,
    span: float,
    locked_segments: set[str],
    locked_nodes: set[int],
    angle_tol_deg: float,
    equal_length_rel_tol: float,
    collinear_angle_tol_deg: float,
    collinear_distance_px: float,
    min_length: float,
    max_relations: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
    relations: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    satisfied: set[tuple[Any, ...]] = set()

    def involved(nodes: tuple[int, int, int, int], ids: list[str]) -> bool:
        return any(node in locked_nodes for node in set(nodes)) or any(
            seg_id in locked_segments for seg_id in ids
        )

    def relation_key(
        kind: str, ids: list[str], nodes: tuple[int, int, int, int], extra: dict[str, Any]
    ) -> tuple[Any, ...]:
        if kind == "collinear":
            return ("collinear", extra["point_node"], ids[0])
        # Canonical node pair: reversing either segment describes the same
        # constraint, and duplicate segment objects must not double-count.
        first = tuple(sorted(nodes[:2]))
        second = tuple(sorted(nodes[2:]))
        return (kind, *sorted((first, second)))

    def add(
        kind: str,
        ids: list[str],
        nodes: tuple[int, int, int, int],
        violation: float,
        **extra: Any,
    ) -> None:
        if involved(nodes, ids):
            rejected.append({"type": kind, "segments": list(ids), "reason": "locked_right_angle"})
            return
        key = relation_key(kind, ids, nodes, extra)
        if key in seen or key in satisfied:
            return
        if violation < _EPS:
            satisfied.add(key)
            return
        seen.add(key)
        relations.append(
            {
                "type": kind,
                "segments": list(ids),
                "nodes": nodes,
                "violation": float(violation),
                **extra,
            }
        )

    segments = _active_segments(state, seg_nodes, positions, min_length)
    usable = [seg for seg in segments if seg[0] not in locked_segments]
    offset_floor = max(1.0, 0.005 * span)

    # Pair detection walks locked segments too so near relations the hard
    # rectifier owns are recorded as rejected rather than silently dropped.
    for x in range(len(segments)):
        seg1, i, j = segments[x]
        for y in range(x + 1, len(segments)):
            seg2, k, l = segments[y]
            u = positions[j] - positions[i]
            v = positions[l] - positions[k]
            n1 = float(np.hypot(*u))
            n2 = float(np.hypot(*v))
            if n1 < _EPS or n2 < _EPS:
                continue
            cross = float(u[0] * v[1] - u[1] * v[0])
            dot = float(u @ v)
            theta = math.degrees(math.atan2(abs(cross), abs(dot)))
            ids, nodes = [seg1, seg2], (i, j, k, l)
            if theta <= angle_tol_deg and len({i, j, k, l}) == 4:
                offset = positions[k] - positions[i]
                distance = abs(float(u[0] * offset[1] - u[1] * offset[0])) / n1
                if distance > offset_floor:
                    add("par", ids, nodes, abs(cross) / (n1 * n2))
            if abs(90.0 - theta) <= angle_tol_deg:
                add("perp", ids, nodes, abs(dot) / (n1 * n2))
            gap = abs(n1 - n2) / max(n1, n2)
            if gap <= equal_length_rel_tol:
                add("eq", ids, nodes, gap)

    point_ids_by_node: dict[int, list[str]] = {}
    for obj_id, node in point_nodes.items():
        point_ids_by_node.setdefault(node, []).append(obj_id)
    candidate_points = set(point_nodes.values())
    for _seg_id, a, b in usable:
        candidate_points.update((a, b))

    for base_id, a_node, b_node in usable:
        a, b = positions[a_node], positions[b_node]
        edge = b - a
        den = float(edge @ edge)
        if den < _EPS:
            continue
        for node in candidate_points:
            if node in (a_node, b_node):
                continue
            q = positions[node]
            t = float((q - a) @ edge) / den
            if not (0.05 < t < 0.95):
                continue
            foot = a + t * edge
            if float(np.linalg.norm(q - foot)) > collinear_distance_px:
                continue
            u, v = q - a, b - q
            nu, nv = float(np.hypot(*u)), float(np.hypot(*v))
            if nu < _EPS or nv < _EPS:
                continue
            angle = math.degrees(
                math.atan2(abs(float(u[0] * v[1] - u[1] * v[0])), float(u @ v))
            )
            if angle > collinear_angle_tol_deg:
                continue
            v1 = a - q
            violation = abs(float(v1[0] * edge[1] - v1[1] * edge[0])) / (
                nu * float(np.hypot(*edge))
            )
            add(
                "collinear",
                [base_id],
                (node, a_node, a_node, b_node),
                violation,
                point_node=node,
                point_ids=sorted(point_ids_by_node.get(node, [])),
            )

    relations.sort(
        key=lambda r: (r["violation"], r["type"], tuple(r["segments"]), r["nodes"])
    )
    if len(relations) > max_relations:
        for item in relations[max_relations:]:
            rejected.append(
                {
                    "type": item["type"],
                    "segments": item["segments"],
                    "reason": "max_relations_exceeded",
                }
            )
        relations = relations[:max_relations]
    return relations, rejected, len(satisfied)


# --------------------------------------------------------------------------- #
# projection solver (ported from geom2code/agent/repair.py)
# --------------------------------------------------------------------------- #
def _violation(
    P: np.ndarray, kind: str, i: int, j: int, k: int, l: int
) -> float:
    v1, v2 = P[j] - P[i], P[l] - P[k]
    n1, n2 = float(np.hypot(*v1)), float(np.hypot(*v2))
    if n1 < _EPS or n2 < _EPS:
        return 0.0
    if kind == "perp":
        return abs(float(v1 @ v2)) / (n1 * n2)  # |cos theta|
    if kind == "par":
        return abs(float(v1[0] * v2[1] - v1[1] * v2[0])) / (n1 * n2)  # |sin theta|
    return abs(n1 - n2) / max(n1, n2)  # relative length gap


def total_violation(P: np.ndarray, relations: list[tuple[Any, ...]]) -> float:
    return float(sum(_violation(P, *rel) for rel in relations))


def _grad(
    P: np.ndarray, kind: str, i: int, j: int, k: int, l: int
) -> tuple[float, dict[int, np.ndarray]]:
    """Gradient of the scalar constraint e(P)=0 w.r.t. the four points."""
    v1, v2 = P[j] - P[i], P[l] - P[k]
    if kind == "perp":
        e = float(v1 @ v2)
        contributions = [(i, -v2), (j, v2), (k, -v1), (l, v1)]
    elif kind == "par":
        e = float(v1[0] * v2[1] - v1[1] * v2[0])
        contributions = [
            (i, np.array([-v2[1], v2[0]])),
            (j, np.array([v2[1], -v2[0]])),
            (k, np.array([v1[1], -v1[0]])),
            (l, np.array([-v1[1], v1[0]])),
        ]
    else:  # eq compares squared lengths for smoothness
        e = float(v1 @ v1 - v2 @ v2)
        contributions = [(i, -2 * v1), (j, 2 * v1), (k, 2 * v2), (l, -2 * v2)]
    # Adjacent segments share indices; their contributions must add, not
    # overwrite each other.
    g: dict[int, np.ndarray] = {}
    for vertex, derivative in contributions:
        g[vertex] = g.get(vertex, np.zeros(2)) + derivative
    return e, g


def _project(
    P: np.ndarray,
    relations: list[tuple[Any, ...]],
    *,
    iters: int = 40,
    damp: float = 1.0,
    fixed_nodes: frozenset[int] = frozenset(),
    tolerance: float = 1e-10,
) -> np.ndarray:
    """Gauss-Seidel minimal-displacement projection onto e(P)=0."""
    Q = np.array(P, float, copy=True)
    for _ in range(max(1, int(iters))):
        for rel in relations:
            e, g = _grad(Q, *rel)
            for node in fixed_nodes:
                if node in g:
                    g[node] = np.zeros(2)
            nrm2 = sum(float(row @ row) for row in g.values())
            if nrm2 < _EPS:
                continue
            step = (e / nrm2) * damp
            for node, row in g.items():
                Q[node] = Q[node] - step * row
        if total_violation(Q, relations) <= tolerance:
            break
    return Q


def _relation_details(
    relations: list[dict[str, Any]],
    before: np.ndarray,
    after: np.ndarray,
) -> list[dict[str, Any]]:
    details: list[dict[str, Any]] = []
    for item in relations:
        kind = "par" if item["type"] == "collinear" else item["type"]
        rel = (kind,) + tuple(item["nodes"])
        before_v = _violation(before, *rel)
        after_v = _violation(after, *rel)
        detail = {
            "type": item["type"],
            "segments": item["segments"],
            "nodes": list(item["nodes"]),
            "before_violation": round(float(before_v), 9),
            "after_violation": round(float(after_v), 9),
            "worsened": bool(after_v > before_v + _MOVED),
        }
        if "point_ids" in item:
            detail["point_ids"] = item["point_ids"]
        if item.get("forced"):
            detail["source"] = item.get("source", "right_angle_marker")
            detail["forced"] = True
        details.append(detail)
    return details


# --------------------------------------------------------------------------- #
# write-back
# --------------------------------------------------------------------------- #
def _point_target(
    old: np.ndarray,
    node: int,
    solved: np.ndarray,
    positions: np.ndarray,
    *,
    point_writeback: str,
    neighbour: np.ndarray | None,
    trust_frac: float,
) -> np.ndarray:
    """Where a labelled point object should be written.

    ``centre`` snaps it onto the solved cluster centre. ``transport`` keeps the
    point's offset and only follows the centre's displacement. ``trust`` and
    ``perp`` keep the snap but make it locally harmless to short point pairs:
    ``trust`` caps the shift at ``trust_frac * |neighbour offset|``, ``perp``
    drops the component along the nearest other point, which is the component
    that changes a short distance to first order.
    """
    centre = solved[node]
    if point_writeback == "centre":
        return centre
    if point_writeback == "transport":
        return old + (centre - positions[node])
    delta = centre - old
    if neighbour is not None:
        gap = float(np.linalg.norm(neighbour))
        if point_writeback == "perp" and gap > _EPS:
            direction = neighbour / gap
            delta = delta - float(delta @ direction) * direction
        elif point_writeback == "trust" and gap > _EPS:
            radius = trust_frac * gap
            length = float(np.linalg.norm(delta))
            if length > radius > 0.0:
                delta = delta * (radius / length)
    return old + delta


def _point_neighbours(
    state: GeometricEvidenceState, point_nodes: dict[str, int]
) -> dict[str, np.ndarray]:
    """Offset from each labelled point to its nearest other point object."""
    old: dict[str, np.ndarray] = {}
    for obj in sorted(state.objects.values(), key=lambda o: o.id):
        if obj.type != "point" or obj.id not in point_nodes:
            continue
        px = _coords_point(obj.coords, "px", "point")
        if px is not None:
            old[obj.id] = px
    out: dict[str, np.ndarray] = {}
    for obj_id, px in old.items():
        best: np.ndarray | None = None
        best_d = math.inf
        for other_id, other in old.items():
            if other_id == obj_id:
                continue
            distance = float(np.linalg.norm(other - px))
            # Duplicate point objects share a coordinate; they say nothing
            # about how far the nearest distinct vertex is.
            if distance > 0.5 and distance < best_d:
                best, best_d = other - px, distance
        if best is not None:
            out[obj_id] = best
    return out


def _note(obj: Any, text: str) -> None:
    if not any(n.startswith("constraint_repair:") for n in obj.notes):
        obj.notes.append(text)


def _planned_shift(
    state: GeometricEvidenceState,
    seg_nodes: dict[str, list[int]],
    point_nodes: dict[str, int],
    positions: np.ndarray,
    solved: np.ndarray,
    *,
    point_writeback: str = "centre",
    neighbours: dict[str, np.ndarray] | None = None,
    trust_frac: float = 0.005,
) -> float:
    """Max displacement of the coordinates that write-back would change.

    Cluster centres are means of merged endpoints, so a centre can stay put
    while an endpoint jumps several pixels to the shared centre. The gate
    must measure what the GES will actually contain.
    """
    worst = 0.0
    for obj in state.objects.values():
        nodes = seg_nodes.get(obj.id)
        if nodes is not None:
            record = _segment_record(obj)
            if record is None:
                continue
            for node, old in zip(nodes, record):
                worst = max(worst, float(np.linalg.norm(solved[node] - old)))
        elif obj.type == "point":
            node = point_nodes.get(obj.id)
            old = _coords_point(obj.coords, "px", "point")
            if node is not None and old is not None:
                target = _point_target(
                    old, node, solved, positions,
                    point_writeback=point_writeback,
                    neighbour=(neighbours or {}).get(obj.id),
                    trust_frac=trust_frac,
                )
                worst = max(worst, float(np.linalg.norm(target - old)))
    return worst


def _apply(
    state: GeometricEvidenceState,
    seg_nodes: dict[str, list[int]],
    point_nodes: dict[str, int],
    before: np.ndarray,
    solved: np.ndarray,
    *,
    point_writeback: str = "centre",
    neighbours: dict[str, np.ndarray] | None = None,
    trust_frac: float = 0.005,
) -> dict[str, Any]:
    pos = solved.reshape(-1, 2)
    displacement = np.linalg.norm(pos - before, axis=1)
    moved = {idx for idx, value in enumerate(displacement) if value > _MOVED}
    width = int(state.image_size.get("width") or 0)
    height = int(state.image_size.get("height") or 0)
    changed: set[str] = set()
    max_object_shift = 0.0

    for obj in sorted(state.objects.values(), key=lambda o: o.id):
        nodes = seg_nodes.get(obj.id)
        if nodes is None or (nodes[0] not in moved and nodes[1] not in moved):
            continue
        old = _segment_record(obj)
        a, b = pos[nodes[0]], pos[nodes[1]]
        obj.coords["a_px"] = a.tolist()
        obj.coords["b_px"] = b.tolist()
        # keep legacy keys consistent when a geometry-agent segment used them
        if "a" in obj.coords:
            obj.coords["a"] = list(obj.coords["a_px"])
        if "b" in obj.coords:
            obj.coords["b"] = list(obj.coords["b_px"])
        obj.coords["length_px"] = round(float(np.linalg.norm(b - a)), 2)
        obj.coords["angle_deg"] = round(
            math.degrees(math.atan2(b[1] - a[1], b[0] - a[0])) % 180.0, 2
        )
        if width > 0 and height > 0:
            obj.normalized["a"] = normalize_point(a[0], a[1], width, height)
            obj.normalized["b"] = normalize_point(b[0], b[1], width, height)
        shift = (
            float(max(np.linalg.norm(a - old[0]), np.linalg.norm(b - old[1])))
            if old is not None
            else float(max(displacement[nodes[0]], displacement[nodes[1]]))
        )
        _note(obj, f"constraint_repair: endpoint adjusted {shift:.2f} px")
        changed.add(obj.id)
        max_object_shift = max(max_object_shift, shift)

    for obj in sorted(state.objects.values(), key=lambda o: o.id):
        if obj.type != "point":
            continue
        node = point_nodes.get(obj.id)
        if node is None or node not in moved:
            continue
        old = _coords_point(obj.coords, "px", "point")
        if old is None:
            target = pos[node]
        else:
            target = _point_target(
                old, node, pos, before,
                point_writeback=point_writeback,
                neighbour=(neighbours or {}).get(obj.id),
                trust_frac=trust_frac,
            )
        obj.coords["px"] = target.tolist()
        if "point" in obj.coords:
            obj.coords["point"] = list(obj.coords["px"])
        shift = float(np.linalg.norm(target - old)) if old is not None else float(displacement[node])
        _note(obj, f"constraint_repair: follows vertex, moved {shift:.2f} px")
        changed.add(obj.id)
        max_object_shift = max(max_object_shift, shift)

    return {
        "moved_nodes": len(moved),
        "max_object_shift_px": round(max_object_shift, 3),
        "changed_objects": len(changed),
        "changed_object_ids": sorted(changed),
    }


def _store_report(
    state: GeometricEvidenceState, report: dict[str, Any], *, applied: bool | None = None
) -> int:
    """Persist the report in ``meta`` while preserving the revision counter."""
    if applied is None:
        applied = bool(report.get("applied"))
    previous = state.meta.get("constraint_repair") or {}
    try:
        revision = int(previous.get("revision", 0) or 0)
    except (TypeError, ValueError):
        revision = 0
    if applied:
        revision += 1
    report["revision"] = revision
    state.meta["constraint_repair"] = report
    return revision


# --------------------------------------------------------------------------- #
# public entry point
# --------------------------------------------------------------------------- #
def repair_geometry_constraints(
    state: GeometricEvidenceState,
    *,
    enabled: bool = True,
    max_relations: int = 30,
    angle_tol_deg: float = 0.5,
    equal_length_rel_tol: float = 0.002,
    collinear_angle_tol_deg: float = 0.5,
    collinear_distance_px: float = 1.0,
    tolerance_px: float | None = None,
    max_shift_px: float | None = 2.0,
    max_disp_frac: float = 0.02,
    iters: int = 40,
    damp: float = 1.0,
    right_angle_mode: str = "lock",
    point_writeback: str = "centre",
    point_trust_frac: float = 0.005,
    write_back: bool = True,
) -> dict[str, Any]:
    """Soften near-satisfied pixel relations before the hard rectifier.

    Defaults mirror geom2code: 0.5 deg for perpendicular / parallel, 0.2 % for
    equal length, 0.5 deg / 1 px for collinear (``source_collinear_relations``),
    a 2 px endpoint shift limit and a 2 % span limit. Endpoint clustering is
    deliberately tighter than the rectifier's marker tolerance: merging
    distinct vertices distorts angles, so the default is at most 2 px even on
    large figures. Mutates ``state`` in place (unless ``write_back=False``) and
    returns a compact report. Safe to call repeatedly: the second call is a
    no-op.

    ``right_angle_mode`` controls what happens to CV-verified right-angle
    markers: ``"lock"`` leaves them to the hard rectifier (default),
    ``"soft"`` turns each marker into a forced perpendicular relation solved by
    the same Gauss-Seidel projection (the caller should then skip the hard
    rectifier), and ``"ignore"`` does not read markers at all.

    ``point_writeback`` controls how a labelled point object follows its node:
    ``"centre"`` snaps it onto the (solved) cluster centre, ``"transport"``
    moves it by the cluster's displacement and keeps the small offset that CV
    produced. Snapping removes real measurement noise but also changes the
    point's distance to every other point, which leaks into length ratios;
    transport keeps that displacement purely local.
    """
    mode = str(right_angle_mode).lower()
    if mode not in ("lock", "soft", "ignore"):
        raise ValueError(f"unknown right_angle_mode: {right_angle_mode!r}")
    point_mode = str(point_writeback).lower()
    if point_mode not in ("centre", "transport", "trust", "perp"):
        raise ValueError(f"unknown point_writeback: {point_writeback!r}")
    cap_h = _cap_height(state)
    tol = float(
        tolerance_px if tolerance_px is not None else min(2.0, max(1.0, 0.15 * cap_h))
    )
    # Right-angle arms are associated with the rectifier's looser tolerance so
    # both writers agree on which strokes a marker owns.
    lock_tol = max(4.0, 0.4 * cap_h)
    shift_limit = float(max_shift_px if max_shift_px is not None else 2.0)
    min_length = max(4.0, 0.4 * cap_h)

    report: dict[str, Any] = {
        "ok": True,
        "enabled": bool(enabled),
        "applied": False,
        "reason": "",
        "constraint_mode": "soft_gauss_seidel",
        "candidate_source": "pixel_geometry",
        "llm_relations_used": False,
        "right_angle_mode": mode,
        "point_writeback": point_mode,
        "point_trust_frac": float(point_trust_frac),
        "cap_h_px": round(cap_h, 2),
        "tolerances": {
            "tolerance_px": round(tol, 2),
            "lock_tolerance_px": round(lock_tol, 2),
            "max_shift_px": round(shift_limit, 2),
            "min_segment_length_px": round(min_length, 2),
            "angle_tol_deg": float(angle_tol_deg),
            "equal_length_rel_tol": float(equal_length_rel_tol),
            "collinear_angle_tol_deg": float(collinear_angle_tol_deg),
            "collinear_distance_px": float(collinear_distance_px),
            "max_disp_frac": float(max_disp_frac),
            "max_relations": int(max_relations),
            "iters": int(iters),
            "damp": float(damp),
        },
        "candidate_count": 0,
        "relations": [],
        "rejected": [],
        "locked_segments": [],
        "locked_nodes": [],
    }
    if not enabled:
        report["reason"] = "disabled"
        _store_report(state, report)
        return report

    accepted: list[dict[str, Any]] = []
    ra_rejected: list[dict[str, Any]] = []
    if mode != "ignore":
        accepted, ra_rejected = _collect_right_angles(
            state,
            cap_h,
            lock_tol,
            min_arm=max(6.0, 0.6 * cap_h),
            angle_tol_deg=_RIGHT_ANGLE_ANGLE_TOL,
        )
    # Marker vertices are appended as their own nodes rather than merged into
    # the arm endpoints the way the hard rectifier does.  Merging anchors the
    # cluster centre on the vertex, which snaps a stroke end obscured by the
    # ink square several pixels sideways even when no relation is violated.
    # Perpendicularity only depends on segment directions, so the soft solver
    # does not need the shared corner; a through arm's vertex is kept on its
    # line by an explicit collinear relation instead.
    centres, seg_nodes, _ra_nodes, _clusters = _build_nodes(state, [], tol)
    if not seg_nodes:
        report["reason"] = "no_candidates"
        _store_report(state, report)
        return report

    point_nodes = _attach_points(state, centres, tol)
    point_neighbours = (
        _point_neighbours(state, point_nodes)
        if point_mode in ("trust", "perp")
        else None
    )
    ra_nodes = _attach_vertices(accepted, centres, tol) if mode == "soft" else []
    if mode == "lock":
        locked_segments, locked_nodes = _lock_sets(
            accepted, lock_tol, seg_nodes, centres
        )
    else:
        locked_segments, locked_nodes = set(), set()
    report["locked_segments"] = sorted(locked_segments)
    report["locked_nodes"] = sorted(locked_nodes)
    report["right_angle_markers"] = len(accepted)
    if ra_rejected:
        report["right_angle_rejected"] = ra_rejected

    positions = np.vstack(centres)
    span = float(np.linalg.norm(np.ptp(positions, axis=0))) or 1.0
    report["span_px"] = round(span, 2)

    relations, rejected, satisfied = _candidates(
        state,
        seg_nodes,
        point_nodes,
        positions,
        span=span,
        locked_segments=locked_segments,
        locked_nodes=locked_nodes,
        angle_tol_deg=float(angle_tol_deg),
        equal_length_rel_tol=float(equal_length_rel_tol),
        collinear_angle_tol_deg=float(collinear_angle_tol_deg),
        collinear_distance_px=float(collinear_distance_px),
        min_length=min_length,
        max_relations=int(max_relations),
    )
    report["rejected"] = rejected
    report["satisfied_count"] = satisfied

    forced_count = added_count = 0
    if mode == "soft" and accepted:
        forced = _right_angle_relations(accepted, ra_nodes, seg_nodes, positions)
        existing = {
            (item["type"], tuple(sorted(item["nodes"]))) for item in relations
        }
        fresh = [
            item
            for item in forced
            if (item["type"], tuple(sorted(item["nodes"]))) not in existing
        ]
        # Marker evidence outranks pixel-tolerance candidates and is exempt
        # from the max_relations cap: dropping a verified right angle would
        # silently undo the hard rectifier this mode replaces.
        forced_count, added_count = len(forced), len(fresh)
        relations = fresh + relations
    report["right_angle_relations"] = forced_count
    report["right_angle_relations_added"] = added_count

    if not relations:
        # Near relations existed but were already within tolerance, versus no
        # relation-shaped geometry at all.
        report["reason"] = "already_satisfied" if satisfied else "no_candidates"
        report["total_violation_before"] = 0.0
        report["total_violation_after"] = 0.0
        report["max_shift_px"] = 0.0
        report["max_node_shift_px"] = 0.0
        report["rms_shift_px"] = 0.0
        report["max_relation_worsening"] = 0.0
        _store_report(state, report)
        return report

    report["candidate_count"] = len(relations)
    solver_relations = [
        ("par" if item["type"] == "collinear" else item["type"],) + tuple(item["nodes"])
        for item in relations
    ]
    before = total_violation(positions, solver_relations)
    report["total_violation_before"] = float(before)
    details = _relation_details(relations, positions, positions)

    if before <= _SATISFIED:
        report["reason"] = "already_satisfied"
        report["total_violation_after"] = float(before)
        report["relations"] = details
        report["max_shift_px"] = 0.0
        report["max_node_shift_px"] = 0.0
        report["rms_shift_px"] = 0.0
        report["max_relation_worsening"] = 0.0
        _store_report(state, report)
        return report

    solved = _project(positions, solver_relations, iters=int(iters), damp=float(damp))
    if not np.all(np.isfinite(solved)):
        report["reason"] = "solver_failed"
        report["total_violation_after"] = float(before)
        report["relations"] = details
        _store_report(state, report)
        return report

    after = total_violation(solved, solver_relations)
    displacement = np.linalg.norm(solved - positions, axis=1)
    max_node_disp = float(displacement.max()) if len(displacement) else 0.0
    max_disp = _planned_shift(
        state, seg_nodes, point_nodes, positions, solved,
        point_writeback=point_mode,
        neighbours=point_neighbours,
        trust_frac=float(point_trust_frac),
    )
    details = _relation_details(relations, positions, solved)
    report.update(
        {
            "total_violation_after": float(after),
            "relations": details,
            "max_shift_px": round(max_disp, 4),
            "max_node_shift_px": round(max_node_disp, 4),
            "rms_shift_px": round(float(np.sqrt(np.mean(displacement ** 2))), 4),
            "max_relation_worsening": round(
                max(0.0, max((d["after_violation"] - d["before_violation"] for d in details), default=0.0)),
                6,
            ),
        }
    )

    reason = ""
    if after >= before:
        reason = "no_improvement"
    elif max_disp > shift_limit + 1e-9:
        reason = "max_shift_exceeded"
    elif max_disp > max_disp_frac * span + 1e-9:
        reason = "max_shift_exceeded"
    if reason:
        report["reason"] = reason
        _store_report(state, report)
        return report

    if not write_back:
        report["applied"] = True
        report["reason"] = "dry_run"
        _store_report(state, report, applied=False)
        return report

    write = _apply(
        state, seg_nodes, point_nodes, positions, solved,
        point_writeback=point_mode,
        neighbours=point_neighbours,
        trust_frac=float(point_trust_frac),
    )
    report.update(
        {
            "applied": True,
            "reason": "applied",
            "moved_nodes": write["moved_nodes"],
            "max_object_shift_px": write["max_object_shift_px"],
            "changed_objects": write["changed_objects"],
            "changed_object_ids": write["changed_object_ids"],
        }
    )
    _store_report(state, report)
    state.add_evidence(
        source="geometry_constraint_repair",
        method=(
            "deterministic Gauss-Seidel projection of pixel-extracted "
            "perpendicular/parallel/equal-length/collinear candidates"
        ),
        summary=(
            f"{len(details)} relation(s), violation {before:.3e}->{after:.3e}, "
            f"max shift {write['max_object_shift_px']:.2f} px"
        ),
        payload=report,
    )
    return report
