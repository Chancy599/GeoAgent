"""Integer-sp layout search and exported-coordinate guards for TikZ."""
from __future__ import annotations

from decimal import Decimal
from fractions import Fraction
import math
import re

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp

from .coordinate_precision import PT_PER_CM
from .optimize_relations import optimize_coordinates
from .relation_candidates import pair_metrics
from .tikz_geometry import NAME, extract_geometry


SP_PER_PT = 65536
SP_PER_CM = PT_PER_CM * SP_PER_PT
DENOMINATORS = (16, 32, 64, 128, 256, 512, 1024, 2048, 4096)
COORD = re.compile(r"\\coordinate\s*\((" + NAME + r")\)\s*at\s*\(([^();]+)\)\s*;")



def relation_key(candidate):
    return candidate["type"], tuple(sorted(candidate["segments"]))


def write_coordinates(tex, replacements):
    seen = set()

    def replace(match):
        name = match[1]
        if name not in replacements:
            return match[0]
        if name in seen:
            raise ValueError(f"multiple coordinate declarations for {name}")
        seen.add(name)
        x, y = replacements[name]
        return rf"\coordinate ({name}) at ({x},{y});"

    tex = re.sub(r"(?m)^% GEOAGENT_REPAIR_V1 [^\n]*\n?", "", tex)
    tex = COORD.sub(replace, tex)
    if seen != set(replacements):
        raise ValueError(f"unmatched coordinate declarations {set(replacements) - seen}")
    return tex


def float_solution(raw, archived, report):
    """Recover the floating solution and verify its three-decimal round trip."""
    before = extract_geometry(raw)
    after = extract_geometry(archived)
    keys = ("max_shift_rel", "max_length_change_rel", "topology_tol_rel", "incidence_mode",
            "length_weight", "length_scope", "fixed_points", "incidence_strength")
    options = {key: report["limits"][key] if key in report["limits"] else report[key] for key in keys}
    candidates = report["accepted"] + [row["candidate"] for row in report["rejected"]]
    candidates.sort(key=lambda row: (row["type"] == "collinear", tuple(sorted(row["segments"]))))
    solution, solved = optimize_coordinates(before, candidates, **options)
    if {relation_key(row) for row in solved["accepted"]} != {relation_key(row) for row in report["accepted"]}:
        raise ValueError("floating replay changed the accepted relations")
    rounded = {name: [float(f"{v:.3f}") for v in xy] for name, xy in solution["points"].items()}
    if rounded != after["points"] or before["segments"] != after["segments"]:
        raise ValueError("floating replay did not reproduce the archived coordinates")
    return before, after, solution["points"]


def direction_components(relations, edges):
    adjacency = {}
    for relation in relations:
        a, b = relation["segments"]
        turn = int(relation["type"] == "perpendicular")
        adjacency.setdefault(a, []).append((b, turn))
        adjacency.setdefault(b, []).append((a, turn))
    seen = {}
    for root in adjacency:
        if root in seen:
            continue
        seen[root] = 0
        component = {}
        pending = [root]
        while pending:
            edge = pending.pop()
            parity = seen[edge]
            component[edge] = (edges[edge], parity)
            for neighbor, turn in adjacency[edge]:
                expected = parity ^ turn
                if neighbor in seen:
                    if seen[neighbor] != expected:
                        raise ValueError("inconsistent direction cycle")
                    continue
                seen[neighbor] = expected
                pending.append(neighbor)
        yield component


def cross(u, v):
    return int(u[0]) * int(v[1]) - int(u[1]) * int(v[0])


def vector(points, edge):
    a, b = edge
    return tuple(y - x for x, y in zip(points[a], points[b]))


def basis_direction(component, target, base, fixed, denominator):
    longest = None
    anchored = None
    for edge, turn in component.values():
        x, y = vector(target, edge)
        if longest is None or math.hypot(x, y) > math.hypot(*longest):
            longest = (y, -x) if turn else (x, y)
        if set(edge) <= fixed:
            a, b = map(int, vector(base, edge))
            candidate = (b, -a) if turn else (a, b)
            if anchored is not None and cross(anchored, candidate):
                return None
            divisor = math.gcd(*candidate)
            if not divisor:
                return None
            anchored = tuple(v // divisor for v in candidate)
    if anchored is not None:
        return anchored
    x, y = longest
    if abs(x) >= abs(y):
        slope = Fraction(float(y / x)).limit_denominator(denominator)
        return slope.denominator, slope.numerator
    slope = Fraction(float(x / y)).limit_denominator(denominator)
    return slope.numerator, slope.denominator


def relation_value(points, edges, relation):
    u, v = (vector(points, edges[edge]) for edge in relation["segments"])
    if not any(u) or not any(v):
        raise ValueError("degenerate relation")
    if relation["type"] == "perpendicular":
        return sum(int(a) * int(b) for a, b in zip(u, v))
    return cross(u, v)


def exact_layout(target, fixed, edges, relations, max_extra_cm):
    """Fit integer-sp coordinates to rational directions and certify each relation."""
    components = list(direction_components(relations, edges))
    names = sorted({n for relation in relations for edge in relation["segments"] for n in edges[edge]})
    ids = {name: 2 * i for i, name in enumerate(names)}
    base = {name: np.rint(target[name]).astype(np.int64) for name in names}
    budget = math.floor(max_extra_cm * SP_PER_CM / math.sqrt(2))
    size = 2 * len(names)
    lower = np.array([-budget] * size + [0], dtype=float)
    upper = np.array([budget] * (size + 1), dtype=float)
    for name in fixed & ids.keys():
        index = ids[name]
        lower[index:index+2] = upper[index:index+2] = 0
    maxima = np.vstack((np.eye(size), -np.eye(size)))
    cap = LinearConstraint(np.column_stack((maxima, -np.ones(2 * size))), -np.inf, 0)
    objective = np.zeros(size + 1)
    objective[-1] = 1
    best = None
    best_error = math.inf
    tried = set()
    for denominator in DENOMINATORS:
        directions = tuple(basis_direction(component, target, base, fixed, denominator)
                           for component in components)
        if None in directions or directions in tried:
            continue
        tried.add(directions)
        rows = []
        rhs = []
        for component, direction in zip(components, directions):
            x, y = direction
            for (a, b), turn in component.values():
                dx, dy = (-y, x) if turn else (x, y)
                row = np.zeros(size + 1)
                row[ids[a]:ids[a]+2] = (-dy, dx)
                row[ids[b]:ids[b]+2] = (dy, -dx)
                rows.append(row)
                rhs.append(cross((dx, dy), vector(base, (a, b))))
        result = milp(objective, integrality=np.ones(size + 1), bounds=Bounds(lower, upper),
                      constraints=(LinearConstraint(rows, rhs, rhs), cap),
                      options={"time_limit": .12, "mip_rel_gap": .01})
        if result.x is None:
            continue
        delta = np.rint(result.x[:size]).astype(np.int64).reshape(-1, 2)
        points = {name: base[name] + change for name, change in zip(names, delta)}
        if any(relation_value(points, edges, r) for r in relations):
            continue
        error = max(float(np.linalg.norm(points[name] - target[name])) for name in names)
        if error <= max_extra_cm * SP_PER_CM and error < best_error:
            best, best_error = points, error
        if best_error <= 1:
            break
    return best, best_error / SP_PER_CM if best is not None else None


def adaptive_layout(target, fixed, edges, relations, max_extra_cm):
    """Choose directions separately and maximize the number of exact relations."""
    components = list(direction_components(relations, edges))
    names = sorted({n for component in components for edge, _ in component.values() for n in edge})
    ids = {name: 2 * i for i, name in enumerate(names)}
    base = {name: np.rint(target[name]).astype(np.int64) for name in names}
    budget = math.floor(max_extra_cm * SP_PER_CM / math.sqrt(2))
    size = 2 * len(names)
    movable = np.repeat([name not in fixed for name in names], 2)
    row_pairs = []
    groups = []
    weights = []
    for component in components:
        weight = sum(relation["segments"][0] in component for relation in relations)
        directions = list(dict.fromkeys(basis_direction(component, target, base, fixed, d)
                                        for d in DENOMINATORS))
        choices = []
        for direction in directions:
            if direction is None:
                continue
            x, y = direction
            constraints = []
            for (a, b), turn in component.values():
                dx, dy = (-y, x) if turn else (x, y)
                row = np.zeros(size)
                row[ids[a]:ids[a]+2] = (-dy, dx)
                row[ids[b]:ids[b]+2] = (dy, -dx)
                rhs = cross((dx, dy), vector(base, (a, b)))
                extent = budget * np.abs(row[movable]).sum()
                if abs(rhs) > extent:
                    break
                constraints.append((row, rhs, extent + abs(rhs)))
            else:
                choices.append(len(row_pairs))
                row_pairs.append(constraints)
                weights.append(weight)
        groups.append(choices)
    if not row_pairs:
        return None, None
    variable_count = size + 1 + len(row_pairs)
    rows, bounds = [], []
    for coordinate in range(size):
        for sign in (-1, 1):
            row = np.zeros(variable_count)
            row[coordinate], row[size] = sign, -1
            rows.append(row)
            bounds.append(0)
    for group in groups:
        if group:
            row = np.zeros(variable_count)
            row[np.array(group) + size + 1] = 1
            rows.append(row)
            bounds.append(1)
    for index, pairs in enumerate(row_pairs, size + 1):
        for coefficients, rhs, big_m in pairs:
            for sign in (-1, 1):
                row = np.zeros(variable_count)
                row[:size] = sign * coefficients
                row[index] = big_m
                rows.append(row)
                bounds.append(big_m + sign * rhs)
    limit = np.where(movable, budget, 0)
    objective = np.r_[np.zeros(size), 1 / (budget + 1), -np.asarray(weights)]
    result = milp(objective, integrality=np.ones(variable_count),
                  bounds=Bounds(np.r_[-limit, 0, np.zeros(len(row_pairs))],
                                np.r_[limit, budget, np.ones(len(row_pairs))]),
                  constraints=LinearConstraint(rows, -np.inf, bounds),
                  options={"time_limit": .6, "mip_rel_gap": .002})
    if result.x is None:
        return None, None
    delta = np.rint(result.x[:size]).astype(np.int64).reshape(-1, 2)
    points = {name: base[name] + change for name, change in zip(names, delta)}
    error = max(float(np.linalg.norm(points[name] - target[name])) for name in names) / SP_PER_CM
    if error > max_extra_cm:
        return None, None
    return points, error


def pt_literal(integer):
    return f"{Decimal(int(integer)) / SP_PER_PT:f}pt"


def validate_layout(before, after, points, report):
    original = before["points"]
    span = np.linalg.norm(np.ptp(list(original.values()), axis=0))
    shift = max(np.linalg.norm(np.subtract(points[name], xy)) for name, xy in original.items()) / span
    if shift > report["limits"]["max_shift_rel"]:
        raise ValueError("experimental export exceeds movement limit")
    max_length_change = 0.0
    for a, b in before["segments"].values():
        u = np.subtract(original[b], original[a])
        v = np.subtract(points[b], points[a])
        length = np.linalg.norm(u)
        if length <= 1e-12:
            continue
        change = abs(np.linalg.norm(v) / length - 1)
        max_length_change = max(max_length_change, float(change))
        if u @ v <= 0 or change > report["limits"]["max_length_change_rel"]:
            raise ValueError("experimental export exceeds edge limit")
        # Preserve incidence and the order of existing interior points.
        for name, xy in original.items():
            offset = np.subtract(xy, original[a])
            t = float(offset @ u) / (length * length)
            distance = abs(u[0] * offset[1] - u[1] * offset[0]) / length / span
            if .001 < t < .999 and distance <= report["limits"]["topology_tol_rel"]:
                projected = float(np.subtract(points[name], points[a]) @ v) / float(v @ v)
                if not 0 < projected < 1:
                    raise ValueError("experimental export changed incidence order")
    if set(points) != set(after["points"]):
        raise ValueError("experimental export changed the point inventory")
    return float(shift), max_length_change


def measures(source_points, engine, edges, relations):
    rows = []
    for relation in relations:
        kind = relation["type"]
        pair = [edges[edge] for edge in relation["segments"]]
        rows.append({
            "type": kind, "segments": relation["segments"],
            "source_error_deg": pair_metrics(source_points, *pair)[kind + "_error_deg"],
            "engine_error_deg": pair_metrics(engine, *pair)[kind + "_error_deg"],
            "engine_integer_exact": relation_value(engine, edges, relation) == 0,
        })
    return rows


def rank(rows):
    return (sum(row["engine_integer_exact"] for row in rows),
            -max((row["engine_error_deg"] for row in rows), default=0))


