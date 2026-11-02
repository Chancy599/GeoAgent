"""Offline A/B of post-TikZ repair variants on frozen generated programs.

The reference JSON is read only after the repaired program has been produced;
the repair function never sees it.  This harness is for development-set analysis
of the deterministic post-processing stage, not for independent evaluation.

    python scripts/experiment_post_repair.py --variants current lw0
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from geoagent.config import load_settings
from geoagent.evaluation.structure import load_reference, prediction, score
from geoagent.state.tikz_repair import repair_tikz_constraints
from geoagent.state.tikz_geometry import extract_geometry

RAW = ROOT / "outputs/ablations/no_post_repair/latex"
STEM = ROOT / "outputs/ablations/no_post_repair/stem"
REFERENCE = ROOT / "data/test/geometry_reference"
CURRENT = dict(
    angle_tol_deg=0.5, max_shift_rel=0.005, max_length_change_rel=0.01,
    topology_tol_rel=0.003, incidence_mode="snap", length_weight=0.01,
    length_scope="all_pairs", curve_policy="defer", incidence_strength=1.0,
    relation_types=("parallel", "perpendicular"), relaxation=1.0,
    curve_options={
        "angle_tol_deg": 0.5, "max_shift_rel": 0.005,
        "max_length_change_rel": 0.01, "topology_tol_rel": 0.002,
        "incidence_mode": "snap", "length_weight": 0.0, "length_scope": "edges",
        "curve_policy": "freeze", "incidence_strength": 1.0,
        "relation_types": ["parallel"], "relaxation": 1.0,
    },
)
VARIANTS: dict[str, dict | None] = {
    "no_repair": None,
    "current": {},
    # Length-ratio protection (solver metric over point pairs).
    "lw0": dict(length_weight=0.0),
    "lw001": dict(length_weight=0.001),
    "lw005": dict(length_weight=0.05),
    "lw01": dict(length_weight=0.1),
    "lw05": dict(length_weight=0.5),
    "lw1": dict(length_weight=1.0),
    "lw01_edges": dict(length_weight=0.1, length_scope="edges"),
    "lw05_edges": dict(length_weight=0.5, length_scope="edges"),
    # Harder per-edge length guard.
    "lchange_005": dict(max_length_change_rel=0.005),
    "lchange_002": dict(max_length_change_rel=0.002),
    # Partial correction shrinks both the fix and the collateral.
    "relax_075": dict(relaxation=0.75),
    "relax_05": dict(relaxation=0.5),
    # Candidate tolerance.
    "angle_02": dict(angle_tol_deg=0.2),
    "angle_035": dict(angle_tol_deg=0.35),
    "angle_07": dict(angle_tol_deg=0.7),
    "angle_1": dict(angle_tol_deg=1.0),
    # Incidence handling.
    "inc_preserve": dict(incidence_mode="preserve"),
    "inc_none": dict(incidence_strength=0.0),
    # Curved figures: allow perpendicular repair inside the freeze path.
    "curve_par_perp": dict(curve_options=dict(
        CURRENT["curve_options"], relation_types=["parallel", "perpendicular"]
    )),
    "curve_defer": dict(curve_options=None),
    # Curved figures: protect pair distances inside the freeze path too.
    "curve_lw01": dict(curve_options=dict(
        CURRENT["curve_options"], length_weight=0.1, length_scope="all_pairs"
    )),
    "curve_lw05": dict(curve_options=dict(
        CURRENT["curve_options"], length_weight=0.5, length_scope="all_pairs"
    )),
    "curve_lw01_edges": dict(curve_options=dict(
        CURRENT["curve_options"], length_weight=0.1, length_scope="edges"
    )),
    "curve_lchange_005": dict(curve_options=dict(
        CURRENT["curve_options"], max_length_change_rel=0.005
    )),
    # Enforce detected near-incidence even when no angle candidate exists.
    "incidence_only": dict(incidence_only=True),
    "incidence_only_tol004": dict(
        incidence_only=True, topology_tol_rel=0.004,
        curve_options=dict(CURRENT["curve_options"], topology_tol_rel=0.004),
    ),
    # Partial incidence snap: trade exact line incidence for less collateral
    # length drift, especially when incidence is the only thing being repaired.
    "inc_strength05": dict(
        incidence_strength=0.5,
        curve_options=dict(CURRENT["curve_options"], incidence_strength=0.5),
    ),
    "inc_strength075": dict(
        incidence_strength=0.75,
        curve_options=dict(CURRENT["curve_options"], incidence_strength=0.75),
    ),
    "incidence_only_s05": dict(
        incidence_only=True, incidence_strength=0.5,
        curve_options=dict(CURRENT["curve_options"], incidence_strength=0.5),
    ),
    "incidence_only_s075": dict(
        incidence_only=True, incidence_strength=0.75,
        curve_options=dict(CURRENT["curve_options"], incidence_strength=0.75),
    ),
    # Incidence-only with a minimum measurable offset: skip sub-0.1% snaps
    # that only perturb lengths without changing any relation.
    "incidence_only_gate8": dict(
        incidence_only=True, incidence_min_offset_rel=0.0008, incidence_strength=0.5,
        curve_options=dict(CURRENT["curve_options"], incidence_strength=0.5),
    ),
    "incidence_only_gate10": dict(
        incidence_only=True, incidence_min_offset_rel=0.0010, incidence_strength=0.5,
        curve_options=dict(CURRENT["curve_options"], incidence_strength=0.5),
    ),
    "incidence_only_gate15": dict(
        incidence_only=True, incidence_min_offset_rel=0.0015, incidence_strength=0.5,
        curve_options=dict(CURRENT["curve_options"], incidence_strength=0.5),
    ),
    "incidence_only_gate10_full": dict(
        incidence_only=True, incidence_min_offset_rel=0.0010,
    ),
    "combined_lw01_inc_gate10_s05": dict(
        length_weight=0.1, incidence_only=True, incidence_min_offset_rel=0.0010,
        incidence_strength=0.5,
        curve_options=dict(
            CURRENT["curve_options"], length_weight=0.1, length_scope="all_pairs",
            incidence_strength=0.5
        ),
    ),
    # Combined low-risk settings.
    "combined_lw01": dict(
        length_weight=0.1,
        curve_options=dict(
            CURRENT["curve_options"], length_weight=0.1, length_scope="all_pairs"
        ),
    ),
    "combined_lw01_inc": dict(
        length_weight=0.1, incidence_only=True,
        curve_options=dict(
            CURRENT["curve_options"], length_weight=0.1, length_scope="all_pairs"
        ),
    ),
    "combined_lw01_inc_s05": dict(
        length_weight=0.1, incidence_only=True, incidence_strength=0.5,
        curve_options=dict(
            CURRENT["curve_options"], length_weight=0.1, length_scope="all_pairs",
            incidence_strength=0.5
        ),
    ),
    "combined_lw01_inc_s075": dict(
        length_weight=0.1, incidence_only=True, incidence_strength=0.75,
        curve_options=dict(
            CURRENT["curve_options"], length_weight=0.1, length_scope="all_pairs",
            incidence_strength=0.75
        ),
    ),
    # Widen candidate tolerance, then let original-image line measurements
    # accept or reject each candidate (roadmap A: evidence-grounded gating).
    # Curved programs are repaired through the nested curve_options, which
    # override the top-level tolerance, so widen both paths together.
    "evidence_tol2": dict(
        angle_tol_deg=2.0,
        curve_options=dict(CURRENT["curve_options"], angle_tol_deg=2.0),
        __gate__=dict(),
    ),
    "evidence_tol3": dict(
        angle_tol_deg=3.0,
        curve_options=dict(CURRENT["curve_options"], angle_tol_deg=3.0),
        __gate__=dict(),
    ),
    "evidence_tol2_strict": dict(
        angle_tol_deg=2.0,
        curve_options=dict(CURRENT["curve_options"], angle_tol_deg=2.0),
        __gate__=dict(agree_tol=1.5, reject_tol=2.5, support_px=3.0),
    ),
    "evidence_only": dict(__gate__=dict()),
    # Reject only image-contradicted candidates, never add tolerance.
    "evidence_reject_only": dict(
        __gate__=dict(agree_tol=2.0, reject_tol=3.0, support_px=4.0),
    ),
    # Widened tolerance with no generated-error fallback: every candidate
    # must be supported by a measured image line.
    "evidence_strict": dict(
        angle_tol_deg=2.0,
        curve_options=dict(CURRENT["curve_options"], angle_tol_deg=2.0),
        __gate__=dict(strict=True),
    ),
}


def _load_raw(stem: str):
    tex = (RAW / f"{stem}.tex").read_text(encoding="utf-8")
    gt, items = load_reference(REFERENCE / f"{stem}.json")
    ref_labels = set(gt.label_names)
    ref_edges = {
        frozenset(gt.label_names[i] for i in edge) for edge in items["edges"]
    }
    # Reference endpoints by label index; label_names sorts the point order.
    ref_points = {label: gt.points[i] for i, label in enumerate(gt.label_names)}
    state = json.loads((STEM / stem / "state.json").read_text(encoding="utf-8"))
    return tex, gt, items, ref_labels, ref_edges, ref_points, state


def _ref_endpoint(seg: str):
    if "--" not in seg:
        return None
    return tuple(seg.split("--"))


def _ref_error(seg1: str, seg2: str, kind: str, ref_points, ref_edges):
    p1, p2 = _ref_endpoint(seg1), _ref_endpoint(seg2)
    if not p1 or not p2:
        return None
    if not all(label in ref_points for label in (*p1, *p2)):
        return None
    if frozenset(p1) not in ref_edges or frozenset(p2) not in ref_edges:
        return None
    a, b = ref_points[p1[0]], ref_points[p1[1]]
    c, d = ref_points[p2[0]], ref_points[p2[1]]
    u, v = np.asarray(b) - a, np.asarray(d) - c
    if np.linalg.norm(u) < 1e-12 or np.linalg.norm(v) < 1e-12:
        return None
    angle = math.degrees(math.atan2(
        abs(float(u[0] * v[1] - u[1] * v[0])), abs(float(u @ v))
    ))
    return abs(angle - (90.0 if kind == "perpendicular" else 0.0))


def _bucket(error: float | None) -> str:
    if error is None:
        return "unmapped"
    if error <= 0.1:
        return "true"
    if error <= 1.0:
        return "near"
    if error <= 3.0:
        return "off"
    return "false"


def _evidence_transform(raw_tex: str, state: dict):
    """Reflected similarity from generated coordinates to measured pixels."""
    graph = extract_geometry(raw_tex)
    objs = state.get("objects") or {}
    bindings = state.get("label_bindings") or {}
    measured = {}
    for label, oid in bindings.items():
        coords = (objs.get(oid) or {}).get("coords") or {}
        xy = coords.get("px") or coords.get("point")
        if xy is not None:
            measured[label] = np.asarray(xy, float)
    points = {k: np.asarray(v, float) for k, v in graph["points"].items()}
    common = sorted(k for k in points if k in measured)
    if len(common) < 3:
        return None
    z = np.asarray([complex(*points[k]) for k in common])
    w = np.asarray([complex(*measured[k]) for k in common])
    basis = np.stack([np.conj(z), np.ones_like(z)], axis=1)
    (scale, shift), _, _, _ = np.linalg.lstsq(basis, w, rcond=None)
    fit = scale * np.conj(z) + shift
    rms = float(np.sqrt(np.mean(np.abs(fit - w) ** 2)))
    if rms > 3.0:
        return None
    segments = []
    for obj in objs.values():
        if obj.get("type") not in ("segment", "line"):
            continue
        if not str(obj.get("source", "")).startswith("cv:"):
            continue
        coords = obj.get("coords") or {}
        a, b = coords.get("a_px"), coords.get("b_px")
        if a is not None and b is not None:
            segments.append((np.asarray(a, float), np.asarray(b, float)))
    if len(segments) < 2:
        return None
    endpoints = np.vstack(segments)
    span = float(np.linalg.norm(np.ptp(endpoints, axis=0)))
    return {
        "scale": scale, "shift": shift, "rms": rms,
        "labels": len(common), "segments": segments, "span_px": span,
    }


def _image_gate(evidence: dict, *, support_px=4.0, agree_tol=2.0,
                reject_tol=3.0, fallback_tol=0.5, min_len_frac=0.05,
                strict=False):
    scale, shift = evidence["scale"], evidence["shift"]
    cv_segments = evidence["segments"]
    span = evidence["span_px"]

    def to_image(xy):
        mapped = scale * np.conj(complex(*xy)) + shift
        return np.asarray([mapped.real, mapped.imag], float)

    def support(pa, pb):
        best = None
        for ca, cb in cv_segments:
            u = cb - ca
            length = float(np.linalg.norm(u))
            if length < min_len_frac * span:
                continue
            def offset(point):
                v = point - ca
                t = float(v @ u) / (length * length)
                d = abs(float(u[0] * v[1] - u[1] * v[0])) / length
                return d, t
            d1, t1 = offset(pa)
            d2, t2 = offset(pb)
            if not (-0.12 <= t1 <= 1.12 and -0.12 <= t2 <= 1.12):
                continue
            score = max(d1, d2)
            if score <= support_px and (best is None or score < best[0]):
                best = (score, u)
        return best

    def gate(candidate, geometry):
        segments = geometry["segments"]
        points = geometry["points"]
        err = candidate["metrics"][candidate["type"] + "_error_deg"]
        supports = []
        for sid in candidate["segments"]:
            if sid not in segments or len(segments[sid]) != 2:
                return None
            pa, pb = (to_image(points[name]) for name in segments[sid])
            supports.append(support(pa, pb))
        if all(item is not None for item in supports):
            u1, u2 = supports[0][1], supports[1][1]
            acute = math.degrees(math.atan2(
                abs(float(u1[0] * u2[1] - u1[1] * u2[0])), abs(float(u1 @ u2))
            ))
            image_err = (abs(acute - 90.0) if candidate["type"] == "perpendicular"
                         else min(acute, 180.0 - acute))
            if image_err <= agree_tol:
                return True, "image_agrees"
            if image_err >= reject_tol:
                return False, "image_contradicts"
            if strict:
                return False, "image_ambiguous_strict"
            return ((True, "image_ambiguous_generated_ok") if err <= fallback_tol
                    else (False, "image_ambiguous_weak"))
        if strict:
            return False, "unsupported_strict"
        return ((True, "unsupported_generated_ok") if err <= fallback_tol
                else (False, "unsupported_weak"))

    return gate


def _one(stem: str, raw_tex: str, refs, options: dict | None, workdir: Path):
    gt, items, ref_labels, ref_edges, ref_points, state = refs
    raw_pred = prediction(RAW / f"{stem}.tex")
    raw_score = score(gt, raw_pred, items)
    if options is None:
        return stem, {
            "tex": raw_tex, "report": {"applied": False, "reason": "no_repair"},
            "raw_score": raw_score, "score": raw_score,
        }
    options = dict(options)
    gate_params = options.pop("__gate__", None)
    evidence = None
    if gate_params is not None:
        evidence = _evidence_transform(raw_tex, state)
        options["candidate_gate"] = (_image_gate(evidence, **gate_params)
                                     if evidence is not None else None)
    tex, report = repair_tikz_constraints(raw_tex, **options)
    if gate_params is not None:
        report["evidence_available"] = evidence is not None
        if evidence is not None:
            report["evidence_fit"] = {
                "rms_px": evidence["rms"], "labels": evidence["labels"]
            }
    path = workdir / f"{stem}.tex"
    path.write_text(tex, encoding="utf-8")
    try:
        pred = prediction(path)
        result = score(gt, pred, items)
    except Exception as exc:  # noqa: BLE001
        result = {"error": f"{type(exc).__name__}: {exc}", "angle_checks": [],
                  "ratio_checks": [], "line_coverage": None}
    return stem, {
        "tex": tex, "report": report, "raw_score": raw_score, "score": result,
        "refs": (ref_labels, ref_edges, ref_points),
    }


def _paired(a_checks, b_checks):
    pair = [(a["error"], b["error"]) for a, b in zip(a_checks, b_checks)
            if a["error"] is not None and b["error"] is not None]
    return pair


def _bootstrap(deltas: np.ndarray, rng, n=10000):
    if not len(deltas):
        return None
    idx = rng.integers(0, len(deltas), size=(n, len(deltas)))
    means = deltas[idx].mean(axis=1)
    return [float(np.quantile(means, .025)), float(np.quantile(means, .975))]


def summarize(rows: dict, stems: list[str], name: str):
    rng = np.random.default_rng(20261102)
    angle_img, ratio_img, angle_items, ratio_items = [], [], [], []
    applied = accepted = 0
    reasons = Counter()
    risk = Counter()
    gate_reasons = Counter()
    evidence_available = evidence_missing = 0
    coverage = []
    angle_avail = angle_ref = ratio_avail = ratio_ref = 0
    per_stem = {}
    for stem in stems:
        row = rows[stem]
        report = row["report"]
        base, post = row["raw_score"], row["score"]
        if post.get("error"):
            reasons["unparseable"] += 1
            per_stem[stem] = {"error": post["error"]}
            continue
        a_pair = _paired(base["angle_checks"], post["angle_checks"])
        r_pair = _paired(base["ratio_checks"], post["ratio_checks"])
        a_mean = float(np.mean([b - a for a, b in a_pair])) if a_pair else 0.0
        r_mean = float(np.mean([b - a for a, b in r_pair])) if r_pair else 0.0
        angle_img.append(a_mean)
        ratio_img.append(r_mean)
        angle_items.extend(b - a for a, b in a_pair)
        ratio_items.extend(b - a for a, b in r_pair)
        coverage.append(post["line_coverage"] or 0.0)
        angle_avail += sum(c["error"] is not None for c in post["angle_checks"])
        angle_ref += len(post["angle_checks"])
        ratio_avail += sum(c["error"] is not None for c in post["ratio_checks"])
        ratio_ref += len(post["ratio_checks"])
        if report.get("applied"):
            applied += 1
            refs = row.get("refs")
            for cand in report.get("accepted", []):
                accepted += 1
                if refs is None:
                    continue
                err = _ref_error(cand["segments"][0], cand["segments"][1],
                                 cand["type"], refs[2], refs[1])
                risk[_bucket(err)] += 1
        reasons[report.get("reason")] += 1
        gate = report.get("evidence_gate")
        if gate is not None:
            for item in gate.get("rejected") or []:
                gate_reasons[item.get("reason")] += 1
        if "evidence_available" in report:
            if report["evidence_available"]:
                evidence_available += 1
            else:
                evidence_missing += 1
        per_stem[stem] = {
            "angle_delta": a_mean, "ratio_delta": r_mean,
            "applied": bool(report.get("applied")),
            "reason": report.get("reason"),
            "candidates": report.get("candidate_count"),
            "accepted": len(report.get("accepted") or []),
            "max_shift_rel": report.get("max_shift_rel"),
            "max_length_change_rel": report.get("max_length_change_rel"),
        }
    angle_img = np.asarray(angle_img)
    ratio_img = np.asarray(ratio_img)
    angle_items = np.asarray(angle_items)
    ratio_items = np.asarray(ratio_items)

    def stats(values, scale):
        return {
            "mean": float(values.mean() * scale) if len(values) else None,
            "median": float(np.median(values) * scale) if len(values) else None,
            "improved": int(np.sum(values < -1e-9)),
            "worse": int(np.sum(values > 1e-9)),
            "p90_worse": float(np.quantile(values[values > 1e-9], .9) * scale)
            if np.any(values > 1e-9) else None,
        }

    return {
        "variant": name,
        "images": len(angle_img),
        "applied_images": applied,
        "accepted_relations": accepted,
        "reasons": dict(reasons),
        "coverage": float(np.mean(coverage)) if coverage else None,
        "angle_coverage": angle_avail / max(1, angle_ref),
        "ratio_coverage": ratio_avail / max(1, ratio_ref),
        "angle_paired_mean_deg": float(angle_img.mean()) if len(angle_img) else None,
        "ratio_paired_mean_pp": float(ratio_img.mean() * 100) if len(ratio_img) else None,
        "angle_bootstrap95": _bootstrap(angle_img, rng),
        "ratio_bootstrap95_pp": [x * 100 for x in _bootstrap(ratio_img, rng)]
        if len(ratio_img) else None,
        "angle_items": stats(angle_items, 1.0),
        "ratio_items": stats(ratio_items, 100.0),
        "angle_images_improved": int(np.sum(angle_img < -1e-9)),
        "angle_images_worse": int(np.sum(angle_img > 1e-9)),
        "ratio_images_improved": int(np.sum(ratio_img < -1e-9)),
        "ratio_images_worse": int(np.sum(ratio_img > 1e-9)),
        "ratio_images_worse_gt_005pp": int(np.sum(ratio_img > 0.0005)),
        "ratio_images_better_gt_005pp": int(np.sum(ratio_img < -0.0005)),
        "max_ratio_delta_pp": float(ratio_img.max() * 100) if len(ratio_img) else None,
        "max_angle_delta_deg": float(angle_img.max()) if len(angle_img) else None,
        "risk_truth": dict(risk),
        "gate_rejected_reasons": dict(gate_reasons),
        "evidence_images": {"available": evidence_available,
                            "missing": evidence_missing},
        "per_stem": per_stem,
    }


def split_summary(rows, stems, name):
    first, second = [], []
    for stem in sorted(stems, key=lambda s: hashlib.sha256(s.encode()).hexdigest()):
        (first if len(first) + len(second) < 50 else second).append(stem)
    out = {}
    for label, subset in (("splitA", first), ("splitB", second)):
        s = summarize({k: rows[k] for k in subset}, subset, name)
        out[label] = {
            "n": s["images"],
            "angle_paired_mean_deg": s["angle_paired_mean_deg"],
            "ratio_paired_mean_pp": s["ratio_paired_mean_pp"],
            "applied_images": s["applied_images"],
        }
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--variants", nargs="*", default=list(VARIANTS))
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--out", type=Path,
                        default=ROOT / "results/experiments/post_repair")
    parser.add_argument("--stems", nargs="*")
    args = parser.parse_args()
    settings = load_settings()
    stems = args.stems or sorted(p.stem for p in RAW.glob("*.tex"))
    raws, refs = {}, {}
    for stem in stems:
        tex, gt, items, labels, edges, points, state = _load_raw(stem)
        raws[stem] = tex
        refs[stem] = (gt, items, labels, edges, points, state)
    print(f"{len(stems)} frozen programs", flush=True)

    results = {}
    args.out.mkdir(parents=True, exist_ok=True)
    for name in args.variants:
        if name not in VARIANTS:
            raise SystemExit(f"unknown variant {name}")
        options = None if VARIANTS[name] is None else {**CURRENT, **VARIANTS[name]}
        rows = {}
        with tempfile.TemporaryDirectory(prefix=f"geoexp_{name}_") as tmp:
            work = Path(tmp)
            with ThreadPoolExecutor(max_workers=args.workers) as pool:
                futures = [
                    pool.submit(_one, stem, raws[stem], refs[stem], options, work)
                    for stem in stems
                ]
                for fut in futures:
                    stem, row = fut.result()
                    rows[stem] = row
            summary = summarize(rows, stems, name)
            summary["split_half"] = split_summary(rows, stems, name)
        results[name] = summary
        def f(x, digits=4, scale=1.0):
            return "—" if x is None else f"{x * scale:.{digits}f}"
        print(
            f"[{name:<16}] applied={summary['applied_images']:3d}/{summary['images']} "
            f"angle={f(summary['angle_paired_mean_deg'])}° "
            f"ratio={f(summary['ratio_paired_mean_pp'])}pp "
            f"cov={f(summary['coverage'],4)} "
            f"risk={summary['risk_truth']}",
            flush=True,
        )
    (args.out / "variants.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"wrote {args.out / 'variants.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
