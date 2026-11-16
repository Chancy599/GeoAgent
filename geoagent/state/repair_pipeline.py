"""Run post-TikZ repair and verify extended hybrid exports in the TeX engine."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
import subprocess
from tempfile import TemporaryDirectory
from time import perf_counter

import numpy as np

from ..tools import compile_tikz
from .angle_glyphs import marker_paths
from .exact_layout import (
    SP_PER_CM, adaptive_layout, exact_layout, float_solution, measures,
    pt_literal, rank, relation_key, relation_value, validate_layout, write_coordinates,
)
from .strict_relations import protected_directions, validate_relations
from .tikz_geometry import NAME, clean, extract_geometry
from .tikz_repair import repair_tikz_constraints
from .topology import check_topology


@dataclass
class PostRepair:
    tex: str
    report: dict
    legacy_tex: str
    legacy_report: dict


def read_compiled_points(tex, names, settings, *, physical=False):
    if physical:
        tex = tex.replace(r"\end{tikzpicture}", "\n\\pgftransformreset\n" + r"\end{tikzpicture}")
    with TemporaryDirectory(prefix="geoagent_probe_") as directory:
        result = compile_tikz(tex, out_dir=directory, paths=settings.paths,
                              timeout=settings.budget.compile_timeout_seconds,
                              probe_names=tuple(sorted(names)))
    points = result.get("points_sp", {})
    if not result.get("ok") or set(points) != set(names):
        raise ValueError("compiler did not return every requested point")
    return points


def extended_hybrid(raw, legacy, report, probe):
    """Choose a validated integer layout with a six-decimal fallback."""
    start = perf_counter()
    probes = 0
    probe_cache = {}
    failures = []

    def verify(tex):
        nonlocal probes
        if tex not in probe_cache:
            probes += 1
            probe_cache[tex] = probe(tex, after["points"])
        return probe_cache[tex]

    def record(tex, mode, adjustment=None, integers=None):
        exported = extract_geometry(tex)
        if exported["segments"] != after["segments"]:
            raise ValueError("export changed the supported segments")
        shift, length_change = validate_layout(before, after, exported["points"], report)
        engine = verify(tex)
        if integers is not None and any(tuple(xy) != engine[name] for name, xy in integers.items()):
            raise ValueError("compiled coordinates differ from integer layout")
        rows = measures(exported["points"], engine, after["segments"], relations)
        return tex, rows, mode, adjustment, shift, length_change

    def integer_record(points, extra, mode):
        literals = {name: [pt_literal(v) for v in xy] for name, xy in points.items()}
        try:
            return record(write_coordinates(legacy, literals), mode, extra, points)
        except (ValueError, OSError, subprocess.SubprocessError) as exc:
            failures.append(f"{mode}: {exc}")
            return None

    try:
        before, after, solved = float_solution(raw, legacy, report)
        fixed = set(report["fixed_points"])
        relations = report["accepted"]
        literals = {n: [f"{v:.6f}" for v in xy] for n, xy in solved.items() if n not in fixed}
        decimal = record(write_coordinates(legacy, literals), "decimal6")
        best = decimal
        target = {n: np.asarray(xy) * SP_PER_CM for n, xy in solved.items()}
        if fixed:
            current_engine = verify(legacy)
            target.update({n: np.asarray(current_engine[n]) for n in fixed})
        edges = after["segments"]
        best_exact, best_extra = None, None
        for mode, budget in (("exact_tight", .00035), ("exact_wide", .003)):
            exact, extra = exact_layout(target, fixed, edges, relations, budget)
            if best_exact is not None and (exact is None or best_extra <= extra):
                continue
            if exact is None:
                continue
            best_exact, best_extra = exact, extra
            candidate = integer_record(exact, extra, mode)
            if candidate and all(row["engine_integer_exact"] for row in candidate[1]):
                if rank(candidate[1]) > rank(best[1]) or (best[3] is not None and extra < best[3]):
                    best = candidate

        for mode, budgets in (("adaptive", (.00035, .001, .003)), ("extended", (.006, .012))):
            prior_count = rank(best[1])[0]
            selected = None
            selected_rank = rank(best[1])
            for budget in budgets:
                if selected_rank[0] == len(relations):
                    break
                points, extra = adaptive_layout(target, fixed, edges, relations, budget)
                if points is None:
                    continue
                values = {**after["points"], **{n: (xy / SP_PER_CM).tolist() for n, xy in points.items()}}
                rows = measures(values, points, edges, relations)
                score = rank(rows)
                if score <= selected_rank or (mode == "extended" and score[0] <= prior_count):
                    continue
                if any(a["engine_error_deg"] > max(.003, b["engine_error_deg"]) + 1e-9
                       for a, b in zip(rows, decimal[1])):
                    continue
                try:
                    validate_layout(before, after, values, report)
                except ValueError:
                    continue
                selected = points, extra
                selected_rank = score
            if selected is not None:
                candidate = integer_record(*selected, mode)
                if candidate is not None:
                    best = candidate
        tex, rows, mode, extra, shift, length_change = best
        diagnostics = {"mode": mode, "relations": rows, "exact": rank(rows)[0],
                       "max_engine_error_deg": -rank(rows)[1], "extra_shift_cm": extra,
                       "probe_count": probes, "seconds": perf_counter() - start, "failed_exports": failures}
        accepted = []
        for old, row in zip(relations, rows):
            accepted.append({**old, "after_error_deg": row["source_error_deg"],
                             "engine_error_deg": row["engine_error_deg"],
                             "engine_integer_exact": row["engine_integer_exact"]})
            accepted[-1].pop("export_tolerance_deg", None)
        max_source_error = max(row["source_error_deg"] for row in rows)
        marker = hashlib.sha256(tex.strip().encode()).hexdigest()
        tex = tex.strip() + f"\n% GEOAGENT_EXTENDED_HYBRID {marker}\n"
        updated = {**report, "algorithm": "post_tikz.extended_hybrid.v1", "extended_hybrid": diagnostics,
                   "coordinate_decimals": 6 if mode == "decimal6" else None,
                   "max_shift_rel": shift, "max_length_change_rel": length_change, "accepted": accepted,
                   "max_after_error_deg": max_source_error, "max_export_error_deg": max_source_error,
                   "output_sha256": hashlib.sha256(tex.encode()).hexdigest()}
        return tex, updated
    except (OSError, ValueError, KeyError, TypeError, np.linalg.LinAlgError, subprocess.SubprocessError) as exc:
        return legacy, {**report, "extended_hybrid": {"mode": "legacy_fallback", "reason": str(exc),
                                                       "probe_count": probes, "seconds": perf_counter() - start}}


def strict_rollback(report, reason, **details):
    """Archive the attempted relations without treating them as accepted repairs."""
    return {**report, "algorithm": "post_tikz.strict.v1", "applied": False, "reason": reason,
            "accepted": [], "export_verified": False, "max_shift_rel": 0.0, "rms_shift_rel": 0.0,
            "max_length_change_rel": 0.0,
            "max_after_error_deg": None, "max_export_error_deg": None, "coordinate_decimals": None,
            "output_sha256": report["input_sha256"],
            "strict": {"attempted": report.get("accepted", []), **details}}


def topology_issues(source, plan):
    return {json.dumps([key, value], sort_keys=True)
            for key, values in check_topology(source, plan).items() if key != "passed"
            for value in values}


def verify_straight_paths(tex, points):
    """Reject strokes whose geometry the preservation checks cannot model."""
    source = clean(tex)
    if re.search(r"\\(?:path|filldraw|clip|shade)\b", source):
        raise ValueError("unsupported body path in strict mode")
    marks, _, _ = marker_paths(source)
    vertex = rf"\(({NAME})\)"
    chain = rf"{vertex}(?:\s*--\s*{vertex})+(?:\s*--\s*cycle)?"
    for draw in re.findall(r"\\draw\b([^;]*);", source):
        if draw in marks or re.fullmatch(
            rf"\s*pic\s*(?:\[[^\[\]]*\]\s*)?\{{\s*(?:right angle|angle)\s*=\s*{NAME}\s*--\s*{NAME}\s*--\s*{NAME}\s*\}}\s*",
            draw,
        ):
            continue
        options = re.match(r"\s*(?:\[([^\[\]]*)\]\s*)?", draw)
        if (not re.fullmatch(chain, draw[options.end():].strip())
                or not set(re.findall(vertex, draw[options.end():])) <= points.keys()
                or re.search(r"\b(?:shift|[xy]shift|scale|rotate|transform\s+canvas|shorten\s*[<>])\s*=",
                             options[1] or "")):
            raise ValueError("unverified straight stroke in strict mode")


def strict_repair(raw, legacy, report, probe, plan):
    targets = report["accepted"]
    start = perf_counter()
    failures = []

    try:
        if report.get("curve_anchors"):
            raise ValueError("cannot certify every relationship to curved strokes")
        if report["applied"]:
            before, _, solved = float_solution(raw, legacy, report)
        else:
            before = extract_geometry(raw)
            solved = before["points"]
        verify_straight_paths(raw, before["points"])
        edges = before["segments"]
        original = probe(raw, before["points"])
        if all(relation_value(original, edges, relation) == 0 for relation in targets):
            rows = measures(before["points"], original, edges, targets)
            return raw, {**report, "algorithm": "post_tikz.strict.v1", "applied": False,
                         "reason": "already_exact", "output_sha256": report["input_sha256"],
                         "export_verified": True, "coordinate_decimals": None,
                         "max_shift_rel": 0.0, "rms_shift_rel": 0.0, "max_length_change_rel": 0.0,
                         "max_after_error_deg": max(row["source_error_deg"] for row in rows),
                         "max_export_error_deg": max(row["source_error_deg"] for row in rows),
                         "accepted": [{**old, **row} for old, row in zip(targets, rows, strict=True)],
                         "strict": {"relations": rows, "exact": len(rows), "seconds": perf_counter() - start}}

        fixed = set(report["fixed_points"])
        relations = {relation_key(r): r for r in protected_directions(original, edges)}
        relations.update({relation_key(r): r for r in targets})
        required = list(relations.values())
        target = {name: np.asarray(xy) * SP_PER_CM for name, xy in solved.items()}
        target.update({name: np.asarray(original[name]) for name in fixed})
        # Keep original coordinates for vertices outside the constraints.
        participating = {name for r in required for sid in r["segments"] for name in edges[sid]}
        before_issues = topology_issues(raw, plan) if plan else set()
        seen = set()
        attempts = [(None, None), (exact_layout, .00035), (exact_layout, .003),
                    (adaptive_layout, .003), (adaptive_layout, .006), (adaptive_layout, .012)]
        for search, budget in attempts:
            if search is None:
                layout = {name: np.rint(target[name]).astype(np.int64) for name in participating}
            else:
                layout, _ = search(target, fixed, edges, required, budget)
            if layout is None:
                continue
            candidate = {**original, **{name: tuple(map(int, xy)) for name, xy in layout.items()}}
            key = tuple(sorted(candidate.items()))
            if key in seen:
                continue
            seen.add(key)
            try:
                if any(relation_value(candidate, edges, relation) for relation in required):
                    continue
                validate_relations(original, candidate, edges, targets, report["limits"]["topology_tol_rel"])
                literals = {name: [pt_literal(v) for v in xy] for name, xy in candidate.items()
                            if xy != original[name]}
                tex = write_coordinates(raw, literals)
                exported = extract_geometry(tex)
                if exported["segments"] != edges:
                    raise ValueError("export changed the segment inventory")
                validate_layout(before, before, exported["points"], report)
                if plan and topology_issues(tex, plan) - before_issues:
                    raise ValueError("export added a topology issue")
                engine = probe(tex, before["points"])
                if engine != candidate:
                    raise ValueError("compiled coordinates differ from the certified layout")
                engine_before = {"points": {n: [v / SP_PER_CM for v in xy] for n, xy in original.items()},
                                 "segments": edges}
                shift, length_change = validate_layout(
                    engine_before, engine_before,
                    {n: [v / SP_PER_CM for v in xy] for n, xy in engine.items()}, report,
                )
                rows = measures(exported["points"], engine, edges, targets)
            except ValueError as exc:
                failures.append(str(exc))
                continue
            marker = hashlib.sha256(tex.strip().encode()).hexdigest()
            tex = tex.strip() + f"\n% GEOAGENT_STRICT {marker}\n"
            accepted = [{**old, **row} for old, row in zip(targets, rows, strict=True)]
            for row in accepted:
                row.pop("export_tolerance_deg", None)
                row["after_error_deg"] = row["source_error_deg"]
            max_source_error = max(row["source_error_deg"] for row in rows)
            original_xy = np.asarray(list(original.values()), dtype=float)
            displacement = np.asarray([engine[name] for name in original], dtype=float) - original_xy
            rms_shift = np.sqrt(np.mean(np.sum(displacement ** 2, axis=1))) / np.linalg.norm(np.ptp(original_xy, axis=0))
            return tex, {**report, "algorithm": "post_tikz.strict.v1", "applied": True, "reason": "applied",
                         "accepted": accepted, "export_verified": True, "coordinate_decimals": None,
                         "max_shift_rel": shift, "rms_shift_rel": float(rms_shift), "max_length_change_rel": length_change,
                         "max_after_error_deg": max_source_error, "max_export_error_deg": max_source_error,
                         "output_sha256": hashlib.sha256(tex.encode()).hexdigest(),
                         "strict": {"relations": rows, "exact": len(rows), "seconds": perf_counter() - start}}
    except (ValueError, OSError, KeyError, TypeError, np.linalg.LinAlgError, subprocess.SubprocessError) as exc:
        failures.append(str(exc))
    return raw, strict_rollback(report, "strict_repair_unverified",
                                failures=list(dict.fromkeys(failures)), seconds=perf_counter() - start)


def repair_generated_tikz(raw, settings, *, source_image=None, source_coordinates=None, plan=None, probe=None):
    geometry = settings.geometry
    digest = hashlib.sha256(raw.encode()).hexdigest()
    marker = "GEOAGENT_STRICT" if geometry.post_repair_mode == "strict" else "GEOAGENT_EXTENDED_HYBRID"
    body, _, tail = raw.rpartition(f"\n% {marker} ")
    if geometry.enabled and body and tail.strip() == hashlib.sha256(body.strip().encode()).hexdigest():
        report = {"ok": True, "applied": False, "reason": "already_processed", "accepted": [], "rejected": [],
                  "input_sha256": digest, "output_sha256": digest}
        return PostRepair(raw, report, raw, report)
    legacy, base = repair_tikz_constraints(
        raw, enabled=geometry.enabled, angle_tol_deg=geometry.angle_tol_deg,
        max_shift_rel=geometry.post_max_shift_rel, max_length_change_rel=geometry.post_max_length_change_rel,
        topology_tol_rel=geometry.post_topology_tol_rel, incidence_mode=geometry.post_incidence_mode,
        length_weight=geometry.post_length_weight, length_scope=geometry.post_length_scope,
        curve_policy=geometry.post_curve_policy, incidence_strength=geometry.post_incidence_strength,
        relation_types=geometry.post_relation_types, relaxation=geometry.post_relaxation,
        curve_options=geometry.post_curve_options, collinear_max_turn_deg=geometry.post_collinear_max_turn_deg,
        source_image=source_image, source_coordinates=source_coordinates,
    )
    tex, report = legacy, base
    if geometry.post_repair_mode == "strict":
        if base["accepted"] and (base["applied"] or base["reason"] == "already_satisfied"):
            if base["limits"]["relaxation"] != 1.0:
                return PostRepair(raw, strict_rollback(base, "strict_requires_full_projection"), legacy, base)
            tex, report = strict_repair(raw, legacy, base, probe or (
                lambda source, names: read_compiled_points(source, names, settings, physical=True)
            ), plan)
        elif base["accepted"] or legacy != raw:
            return PostRepair(raw, strict_rollback(base, "strict_repair_unverified"), legacy, base)
        return PostRepair(tex, report, legacy, base)
    if (geometry.post_repair_mode == "extended_hybrid" and base["applied"] and base.get("accepted")
            and base["limits"]["relaxation"] == 1.0):
        tex, report = extended_hybrid(raw, legacy, base, probe or (
            lambda candidate, names: read_compiled_points(candidate, names, settings)
        ))
        if plan and tex != legacy:
            if topology_issues(tex, plan) - topology_issues(legacy, plan):
                report = {**base, "extended_hybrid": {"mode": "legacy_fallback",
                          "reason": "new_topology_issue", "seconds": report["extended_hybrid"]["seconds"],
                          "probe_count": report["extended_hybrid"]["probe_count"]}}
                tex = legacy
    return PostRepair(tex, report, legacy, base)
