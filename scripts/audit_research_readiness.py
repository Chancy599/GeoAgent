"""Read-only analysis of the frozen development batch for research planning.

This is descriptive analysis of previously tuned data, not a new test set.
No API calls, generation, geometry changes, or reference changes occur.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path

import numpy as np
from scipy.stats import spearmanr

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def distribution(values):
    a = np.asarray(values, dtype=float)
    return {"n": len(a), "mean": float(a.mean()), "median": float(np.median(a)),
            "p90": float(np.percentile(a, 90)), "max": float(a.max())} if len(a) else {}


def correlation(pairs):
    if len(pairs) < 3:
        return {"n": len(pairs), "spearman_rho": None}
    x, y = np.array(pairs, dtype=float).T
    if np.ptp(x) == 0 or np.ptp(y) == 0:
        return {"n": len(pairs), "spearman_rho": None}
    return {"n": len(pairs), "spearman_rho": float(spearmanr(x, y).statistic)}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--baseline", type=Path, default=ROOT / "outputs/ablations/no_post_repair")
    ap.add_argument("--results", type=Path, default=ROOT / "results/latest")
    ap.add_argument("--out", type=Path, default=ROOT / "results/latest/research_audit.json")
    args = ap.parse_args()
    structure = read(args.results / "structure.json")
    if structure.get("geometry_protocol") != "label-bound-v1":
        raise ValueError("Research audit requires label-bound-v1 results")
    visual = read(args.results / "visual.json")
    summary = read(args.results / "summary.json")
    states = {p.parent.name: read(p) for p in sorted((args.baseline / "stem").glob("*/state.json"))}
    vis = {g: {r["stem"]: r for r in v["per_stem"]} for g, v in visual["groups"].items()}
    audit = {
        "scope": "descriptive exploratory audit of already-tuned 100 images; no generalization inference",
        "geometry_protocol": "label-bound-v1", "state_count": len(states), "geometry": {}, "critic_correlations": {},
        "inputs": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                   for p in [args.results / "structure.json", args.results / "visual.json", args.results / "summary.json"]},
    }
    for metric in ("angle", "ratio"):
        rows = structure["paired_distributions"][metric]["per_image"]
        ordered = sorted(rows.items(), key=lambda x: x[1]["post"], reverse=True)
        total = sum(r["post"] for r in rows.values())
        audit["geometry"][metric] = {
            "per_image_raw": distribution([r["raw"] for r in rows.values()]),
            "per_image_post": distribution([r["post"] for r in rows.values()]),
            "top_error_cases": [{"stem": s, **r} for s, r in ordered[:12]],
            "largest_regressions": [{"stem": s, **r} for s, r in sorted(rows.items(), key=lambda x:x[1]["delta"], reverse=True)[:10] if r["delta"] > 1e-12],
            "top1_share_of_macro_error_sum": ordered[0][1]["post"] / total,
            "top5_share_of_macro_error_sum": sum(r["post"] for _, r in ordered[:5]) / total,
            "image_improved": sum(r["delta"] < -1e-12 for r in rows.values()),
            "image_worse": sum(r["delta"] > 1e-12 for r in rows.values()),
            "image_unchanged": sum(abs(r["delta"]) <= 1e-12 for r in rows.values()),
        }
    actions, action_errors, issue_types = Counter(), Counter(), Counter()
    versions, tokens, calls, visuals, latency = [], [], [], [], []
    by_agent = defaultdict(lambda: Counter())
    post_gen_routes = Counter()
    statuses = Counter()
    obj_counts, rel_counts = Counter(), Counter()
    points, confidence_present, covariance_present = 0, 0, 0
    critic_scores = {}
    trace_rows = []
    for stem, state in states.items():
        history = state["action_history"]
        for a in history:
            actions[a["action"]] += 1
            if a.get("status") == "error":
                action_errors[a["action"]] += 1
        first = next((i for i, a in enumerate(history) if a["action"] == "run_tikz_agent"), None)
        later = history[first + 1:] if first is not None else []
        later_perception = [a for a in later if a["action"].startswith("call_cv_tool") or a["action"] in ("run_geometry_agent", "inspect_image")]
        if later_perception:
            post_gen_routes["images_with_later_perception_or_geometry"] += 1
        if any(a["action"] == "run_geometry_agent" for a in later):
            post_gen_routes["images_with_later_geometry_agent"] += 1
        if any(a["action"].startswith("call_cv_tool") for a in later):
            post_gen_routes["images_with_later_supervisor_cv"] += 1
        vs = state["tikz_versions"]
        versions.append(len(vs))
        if any(v.get("mode") == "repair" for v in vs):
            post_gen_routes["images_with_tikz_repair"] += 1
        selected = next((v for v in vs if v["version"] == state.get("best_version")), None)
        score = selected.get("critic_score") if selected else None
        if score is not None:
            critic_scores[stem] = score
        usage = state.get("token_usage", {})
        totals = usage.get("totals", {})
        tokens.append(totals.get("total_tokens", 0))
        calls.append(totals.get("calls", 0))
        visuals.append(totals.get("visual_calls", 0))
        latency.append(totals.get("latency_s", 0))
        for name, u in usage.get("by_agent", {}).items():
            for field in ("total_tokens", "calls", "visual_calls", "latency_s"):
                by_agent[name][field] += u.get(field, 0)
        for o in state["objects"].values():
            obj_counts[o["type"]] += 1
            if o["type"] == "point":
                points += 1
                confidence_present += o.get("confidence") is not None
                covariance_present += any("cov" in k.lower() for group in (o.get("coords", {}), o.get("attributes", {})) for k in group)
        rel_counts.update(r["relation"] for r in state["relations"].values())
        for report in state["critic_reports"]:
            issue_types.update(i.get("type", "unknown") for i in report.get("issues", []))
        result_path = args.baseline / "stem" / stem / "result.json"
        result = read(result_path) if result_path.exists() else {}
        statuses[result.get("status", "unknown")] += 1
        trace_rows.append({"stem": stem, "versions": len(vs), "total_tokens": totals.get("total_tokens", 0),
                           "best_critic_score": score, "later_perception_or_geometry": bool(later_perception)})
    for metric in ("angle", "ratio"):
        rows = structure["paired_distributions"][metric]["per_image"]
        # Compare critic/raw visuals to RAW geometry: all measure the same frozen program.
        audit["critic_correlations"][metric] = correlation([(critic_scores[s], r["raw"]) for s,r in rows.items() if s in critic_scores])
        for name in ("ssim", "clip", "dino"):
            audit.setdefault("visual_geometry_correlations", {}).setdefault(metric, {})[name] = correlation(
                [(vis["raw"][s][name], r["raw"]) for s,r in rows.items() if s in vis["raw"]])
    audit["traces"] = {"statuses": dict(statuses), "actions": dict(actions), "action_errors": dict(action_errors),
                       "post_generation_routes": dict(post_gen_routes), "version_count": distribution(versions),
                       "total_tokens": distribution(tokens), "total_token_sum": sum(tokens),
                       "llm_calls": distribution(calls), "visual_calls": distribution(visuals),
                       "summed_request_latency_s": distribution(latency),
                       "by_agent": {k:dict(v) for k,v in by_agent.items()}, "critic_issue_types": dict(issue_types),
                       "per_stem": trace_rows,
                       "caveats": ["latency is summed model request latency, not end-to-end wall time", "post-generation CV counts refer to supervisor actions; nested CV can occur inside Geometry Agent", "token accounting is provider reported; no pricing or dollars inferred"]}
    audit["evidence_schema"] = {"object_types": dict(obj_counts), "relation_types": dict(rel_counts),
                                "point_records": points, "points_with_non_null_confidence": confidence_present,
                                "points_with_covariance_named_fields": covariance_present,
                                "caveat": "presence of heuristic confidence does not establish calibration; covariance scan is only field-name inspection"}
    audit["repair_reasons"] = summary["reasons"]
    audit["limitations"] = ["100 images have already been used for parameter selection", "correlations are descriptive cross-image associations and do not establish within-image sensitivity or causality", "top-error shares describe macro-averaged reported errors, not manually confirmed failure causes", "no new external benchmark or LLM experiment was run"]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    concise = {k:v for k,v in audit.items() if k not in ("inputs", "traces")}
    concise["traces"] = {k:v for k,v in audit["traces"].items() if k != "per_stem"}
    print(json.dumps(concise, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
