"""GES-level (label-mapped) diagnostic for soft-repair variants.

This is an *algorithm-selection* harness, not the final structure metric.
Angles and length ratios are similarity-invariant, so GES pixel coordinates can
be compared directly with the reference items once points are matched by label
(``state.label_bindings``).  That removes the LLM generation variance from the
comparison and lets us see whether a repair variant moves the reconstructed
geometry closer to or farther from the reference.

Final claims still come from generated TikZ (see evaluate_structure_ab.py).

    python scripts/evaluate_repair_variants.py
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from geoagent.evaluation.structure import load_reference

from geoagent.config import load_settings  # noqa: E402
from geoagent.state.constraint_repair import repair_geometry_constraints  # noqa: E402
from geoagent.state.rectify import rectify_right_angles  # noqa: E402
from geoagent.state.schemas import GeometricEvidenceState  # noqa: E402


VARIANTS = {
    "current": dict(),
    "unified_soft": dict(right_angle_mode="soft"),
    "current_s2": dict(max_shift_px=2.0),
    "current_s3": dict(max_shift_px=3.0),
    "unified_soft_s2": dict(right_angle_mode="soft", max_shift_px=2.0),
    "unified_soft_s3": dict(right_angle_mode="soft", max_shift_px=3.0),
    "unified_soft_s2_transport": dict(
        right_angle_mode="soft", max_shift_px=2.0, point_writeback="transport"
    ),
    "unified_soft_s3_transport": dict(
        right_angle_mode="soft", max_shift_px=3.0, point_writeback="transport"
    ),
    "current_transport": dict(point_writeback="transport"),
    "unified_soft_s2_trust2": dict(
        right_angle_mode="soft", max_shift_px=2.0,
        point_writeback="trust", point_trust_frac=0.002,
    ),
    "unified_soft_s2_trust5": dict(
        right_angle_mode="soft", max_shift_px=2.0,
        point_writeback="trust", point_trust_frac=0.005,
    ),
    "unified_soft_s2_trust10": dict(
        right_angle_mode="soft", max_shift_px=2.0,
        point_writeback="trust", point_trust_frac=0.01,
    ),
    "unified_soft_s2_perp": dict(
        right_angle_mode="soft", max_shift_px=2.0, point_writeback="perp"
    ),
    "unified_soft_s2_trust1": dict(
        right_angle_mode="soft", max_shift_px=2.0,
        point_writeback="trust", point_trust_frac=0.001,
    ),
    "unified_soft_s2_trust15": dict(
        right_angle_mode="soft", max_shift_px=2.0,
        point_writeback="trust", point_trust_frac=0.0015,
    ),
    "unified_soft_s2_trust25": dict(
        right_angle_mode="soft", max_shift_px=2.0,
        point_writeback="trust", point_trust_frac=0.0025,
    ),
    "unified_soft_s2_trust30": dict(
        right_angle_mode="soft", max_shift_px=2.0,
        point_writeback="trust", point_trust_frac=0.003,
    ),
    "unified_soft_s3_trust2": dict(
        right_angle_mode="soft", max_shift_px=3.0,
        point_writeback="trust", point_trust_frac=0.002,
    ),
    "unified_soft_s3_trust25": dict(
        right_angle_mode="soft", max_shift_px=3.0,
        point_writeback="trust", point_trust_frac=0.0025,
    ),
    "current_trust2": dict(point_writeback="trust", point_trust_frac=0.002),
    "unified_soft_s2_mr20": dict(right_angle_mode="soft", max_shift_px=2.0, max_relations=20),
    "unified_soft_s2_nocol": dict(
        right_angle_mode="soft", max_shift_px=2.0,
        collinear_distance_px=0.0, collinear_angle_tol_deg=0.0,
    ),
    "unified_soft_s2_a05": dict(right_angle_mode="soft", max_shift_px=2.0, angle_tol_deg=0.5),
    "unified_soft_s2_a10": dict(right_angle_mode="soft", max_shift_px=2.0, angle_tol_deg=1.0),
    "unified_soft_s25_a05": dict(right_angle_mode="soft", max_shift_px=2.5, angle_tol_deg=0.5),
    "unified_soft_s2_a05_eq5": dict(
        right_angle_mode="soft", max_shift_px=2.0, angle_tol_deg=0.5, equal_length_rel_tol=0.005
    ),
    "unified_soft_s2_noeq": dict(right_angle_mode="soft", max_shift_px=2.0, equal_length_rel_tol=0.0),
    "no_collinear": dict(collinear_distance_px=0.0, collinear_angle_tol_deg=0.0),
    "no_eq": dict(equal_length_rel_tol=0.0),
    "par_perp_only": dict(
        collinear_distance_px=0.0,
        collinear_angle_tol_deg=0.0,
        equal_length_rel_tol=0.0,
    ),
    "tight_0p1": dict(angle_tol_deg=0.1, equal_length_rel_tol=0.001),
    "tight_par_perp": dict(
        angle_tol_deg=0.1,
        equal_length_rel_tol=0.0,
        collinear_distance_px=0.0,
        collinear_angle_tol_deg=0.0,
    ),
    "hard_only": None,
    "soft_hard": None,
}


def _angle(a, v, b):
    u, w = a - v, b - v
    return math.degrees(math.atan2(abs(float(u[0] * w[1] - u[1] * w[0])), float(u @ w)))


def _labeled_points(state: GeometricEvidenceState) -> dict[str, np.ndarray]:
    out: dict[str, np.ndarray] = {}
    for label, object_id in (state.label_bindings or {}).items():
        obj = state.objects.get(object_id)
        if obj is None:
            continue
        px = (obj.coords or {}).get("px") or (obj.coords or {}).get("point")
        if px is not None:
            out[label] = np.asarray(px, float)
    return out


def _reference_catalog(latex_dir: Path, stem: str):
    graph, items = load_reference(ROOT/'data/test/geometry_reference'/f'{stem}.json')
    names = [{name} for name in graph.label_names]

    def one(index: int) -> str | None:
        # Set iteration order varies with PYTHONHASHSEED; pick deterministically
        # so repeated scans compare the same reference items.
        return sorted(names[index])[0] if names[index] else None

    angles = []
    for item in items["angles"]:
        labels = [one(i) for i in item["points"]]
        if all(labels):
            angles.append((tuple(labels), float(item["target"])))
    ratios = []
    for item in items["ratios"]:
        pair = []
        ok = True
        for edge in item["edges"]:
            labels = [one(i) for i in edge]
            if not all(labels):
                ok = False
                break
            pair.append(tuple(labels))
        if ok:
            ratios.append((tuple(pair), float(item["target"])))
    return angles, ratios


def _scores(points: dict[str, np.ndarray], angles, ratios):
    a_err = {}
    for labels, target in angles:
        if not all(k in points for k in labels):
            continue
        a, v, b = (points[k] for k in labels)
        a_err[labels] = abs(_angle(a, v, b) - target)
    r_err = {}
    for pair, target in ratios:
        if not all(k in points for k in (pair[0][0], pair[0][1], pair[1][0], pair[1][1])):
            continue
        first, second = pair
        l1 = float(np.linalg.norm(points[first[1]] - points[first[0]]))
        l2 = float(np.linalg.norm(points[second[1]] - points[second[0]]))
        if l1 <= 1e-12 or l2 <= 1e-12:
            continue
        r_err[pair] = abs((l1 / l2) / target - 1.0)
    return a_err, r_err


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", default="outputs/ablations/no_post_repair")
    parser.add_argument("--out", default="outputs/metrics/repair-variants-ges.json")
    parser.add_argument("--variants", nargs="*", default=list(VARIANTS))
    args = parser.parse_args()

    settings = load_settings()
    latex_dir = Path(settings.paths.latex_dir)
    archive = Path(args.archive)
    stems = sorted(p.parent.name for p in (archive / "stem").glob("*/state.json"))
    print(f"{len(stems)} archived states")

    catalog = {}
    for stem in stems:
        try:
            catalog[stem] = _reference_catalog(latex_dir, stem)
        except Exception as exc:  # noqa: BLE001
            print(f"  ! reference {stem}: {type(exc).__name__}: {exc}")

    results = {}
    for name in args.variants:
        kwargs = VARIANTS[name]
        agg = {
            "angle": Counter(), "ratio": Counter(),
            "applied": 0, "reasons": Counter(), "candidates": 0,
            "kinds": Counter(), "shift": [], "images": 0,
            # Paired errors over items available before and after, plus
            # per-image means over images that have at least one paired item.
            "angle_before": [], "angle_after": [],
            "ratio_before": [], "ratio_after": [],
            "angle_img_before": [], "angle_img_after": [],
            "ratio_img_before": [], "ratio_img_after": [],
        }
        per_stem = {}
        for stem in stems:
            if stem not in catalog:
                continue
            state = GeometricEvidenceState.load(archive / "stem" / stem / "state.json")
            before = _labeled_points(state)
            angles, ratios = catalog[stem]
            a0, r0 = _scores(before, angles, ratios)
            work = state.model_copy(deep=True)
            try:
                if kwargs is None and name == "hard_only":
                    report = rectify_right_angles(work)
                elif kwargs is None:
                    soft = repair_geometry_constraints(work, enabled=True)
                    hard = rectify_right_angles(work)
                    report = dict(soft)
                    report["applied"] = bool(soft.get("applied") or hard.get("applied"))
                    report["hard_applied"] = bool(hard.get("applied"))
                else:
                    report = repair_geometry_constraints(work, enabled=True, **kwargs)
            except Exception as exc:  # noqa: BLE001
                per_stem[stem] = {"error": f"{type(exc).__name__}: {exc}"}
                continue
            after = _labeled_points(work)
            a1, r1 = _scores(after, angles, ratios)
            row = {"angle": Counter(), "ratio": Counter(), "applied": bool(report.get("applied")),
                   "reason": report.get("reason"), "candidates": report.get("candidate_count", 0),
                   "kinds": Counter(r.get("type") for r in report.get("relations") or [])}
            for key, x, y, bucket in (
                ("angle", a0, a1, agg["angle"]),
                ("ratio", r0, r1, agg["ratio"]),
            ):
                local = row[key]
                local_before, local_after = [], []
                for item in set(x) & set(y):
                    delta = y[item] - x[item]
                    label = "improved" if delta < -1e-9 else "worse" if delta > 1e-9 else "same"
                    bucket[label] += 1
                    local[label] += 1
                    agg[f"{key}_before"].append(float(x[item]))
                    agg[f"{key}_after"].append(float(y[item]))
                    local_before.append(float(x[item]))
                    local_after.append(float(y[item]))
                if local_before:
                    agg[f"{key}_img_before"].append(float(np.mean(local_before)))
                    agg[f"{key}_img_after"].append(float(np.mean(local_after)))
            per_stem[stem] = {k: (dict(v) if isinstance(v, Counter) else v) for k, v in row.items()}
            agg["images"] += 1
            if report.get("applied"):
                agg["applied"] += 1
            agg["reasons"][report.get("reason")] += 1
            agg["candidates"] += report.get("candidate_count", 0)
            agg["kinds"].update(row["kinds"])
            if report.get("max_shift_px") is not None:
                agg["shift"].append(float(report["max_shift_px"]))
        def paired(before, after, scale: float):
            if not before:
                return None
            b = np.asarray(before, float)
            a = np.asarray(after, float)
            d = a - b
            return {
                "n": int(len(b)),
                "before": round(float(b.mean()) * scale, 4),
                "after": round(float(a.mean()) * scale, 4),
                "mean_delta": round(float(d.mean()) * scale, 4),
                "median_delta": round(float(np.median(d)) * scale, 4),
            }

        summary = {
            "images": agg["images"],
            "applied": agg["applied"],
            "reasons": dict(agg["reasons"]),
            "candidates": agg["candidates"],
            "kinds": dict(agg["kinds"]),
            "angle": dict(agg["angle"]),
            "ratio": dict(agg["ratio"]),
            "angle_mae": paired(agg["angle_before"], agg["angle_after"], 1.0),
            "ratio_mre": paired(agg["ratio_before"], agg["ratio_after"], 100.0),
            "angle_mae_by_image": paired(
                agg["angle_img_before"], agg["angle_img_after"], 1.0
            ),
            "ratio_mre_by_image": paired(
                agg["ratio_img_before"], agg["ratio_img_after"], 100.0
            ),
            "shift_px": (
                {"mean": round(float(np.mean(agg["shift"])), 4),
                 "max": round(float(np.max(agg["shift"])), 4)}
                if agg["shift"] else None
            ),
        }
        results[name] = {"summary": summary, "per_stem": per_stem}
        print(f"\n[{name}] {json.dumps(summary, ensure_ascii=False)}")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"variants": results}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
