"""Replay a recorded v1 failure: direct TikZ repair vs evidence-based routing.

python scripts/test_repair_routing.py --prepare-only
python scripts/test_repair_routing.py --stem 1260_q_fig2

This is a single-case pilot, not a matched-cost benchmark. Only the v1 source,
v1 critic and pre-repair geometry fields are exposed to the experiment. Final
v2 source/instructions and reference LaTeX are never used. Outputs are isolated.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from geoagent.agents.critic_agent import _tex_labels
from geoagent.config import load_settings
from geoagent.cv_tools.line_detection import analyze_line_style
from geoagent.evaluation.visual_metrics import ssim_pair
from geoagent.orchestration.runner import GeoAgentRunner
from geoagent.state.schemas import GeometricEvidenceState, GeometryObject, Relation


def save(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def prepare_seed(stem: str, destination: Path) -> GeometricEvidenceState:
    """Reconstruct a replay seed, not an exact checkpoint or a fresh E2E run."""
    case_dir = ROOT / "outputs" / "case_studies" / stem
    case_path = case_dir / "case.json"
    if not case_path.exists():
        return prepare_archive_seed(stem, destination)
    case = json.loads(case_path.read_text(encoding="utf-8"))
    # Deliberate whitelist. Do NOT copy actions, final metrics, v2 or supervisor
    # unresolved notes, which include the historical repair answer.
    from PIL import Image
    original = ROOT / "data" / "test" / "image" / f"{stem}.png"
    with Image.open(original) as im:
        width, height = im.size
    state = GeometricEvidenceState(image_path=str(original.resolve()),
                                  image_size={"width": width, "height": height})
    for obj in case["objects"]:
        state.add_object(GeometryObject.model_validate(obj))
    for rel in case["relations"]:
        state.add_relation(Relation.model_validate(rel))
    for item in case.get("unresolved", []):
        if item.get("source") == "geometry_agent":
            state.add_unresolved(item)
    # Only bindings backed by the already archived pre-repair relations.
    for rel in state.relations.values():
        if rel.relation == "labels_point" and rel.subject in state.objects:
            obj = state.objects[rel.subject]
            if obj.label and rel.object:
                state.label_bindings[obj.label] = rel.object
    tex = (case_dir / "tikz" / "v1" / "v1.tex").read_text(encoding="utf-8")
    version = state.add_tikz_version(tex, mode="generate", notes="Archived v1 replay seed")
    critic = next(c for c in case["critics"] if c.get("version") == 1)
    state.attach_critic(version.version, critic, critic.get("assessment_score"))
    state.meta["replay"] = {"stem": stem, "source_sha256": hashlib.sha256(tex.encode()).hexdigest(),
        "protocol": "reconstructed geometry + archived v1 source and critic; no v2/reference input"}
    save(destination / "seed.json", state.model_dump())
    return state


def prepare_archive_seed(stem: str, destination: Path) -> GeometricEvidenceState:
    """Use frozen core geometry only if the archived run never revisited it.

    Post-generation evidence, instructions, versions and supervisor notes are
    deliberately excluded. Reject archives with later CV/Geometry actions:
    their final geometry cannot safely reconstruct the initial input.
    """
    archive = ROOT / "outputs" / "ours100" / "stem" / stem / "state.json"
    raw = json.loads(archive.read_text(encoding="utf-8"))
    actions = raw["action_history"]
    first = next(i for i, a in enumerate(actions) if a["action"] == "run_tikz_agent")
    if any(a["action"] == "run_geometry_agent" or a["action"].startswith("call_cv_tool")
           for a in actions[first + 1:]):
        raise ValueError("Archive revisited geometry after v1; exact checkpoint required")
    version = raw["tikz_versions"][0]
    if version["version"] != 1 or not version.get("critic_report"):
        raise ValueError("A reviewed archived v1 is required")
    original = ROOT / "data" / "test" / "image" / f"{stem}.png"
    state = GeometricEvidenceState(image_path=str(original.resolve()), image_size=raw["image_size"],
        objects=raw["objects"], relations=raw["relations"], label_bindings=raw["label_bindings"],
        conflicts=raw["conflicts"],
        unresolved_issues=[i for i in raw["unresolved_issues"] if i.get("source") == "geometry_agent"],
        evidence={k: e for k, e in raw["evidence"].items()
                  if e["created_at"] <= version["created_at"] and e["source"] in {"cv_tool", "geometry_agent"}})
    state.add_tikz_version(version["tex"], mode="generate", notes="Archived v1 replay seed")
    state.attach_critic(1, version["critic_report"], version.get("critic_score"))
    state.meta["replay"] = {"stem": stem,
        "source_sha256": hashlib.sha256(version["tex"].encode()).hexdigest(),
        "archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
        "protocol": "frozen core geometry from archive with no post-v1 CV/Geometry actions; v1 only",
        "limitation": "Reconstructed state, not exact checkpoint. Existing rectification is assumed idempotent."}
    save(destination / "seed.json", state.model_dump())
    return state


def audit(state: GeometricEvidenceState) -> dict:
    """Source/state correspondence audit, not a general TikZ parser."""
    latest = state.latest_version()
    labels = _tex_labels(latest.tex if latest else "")
    points = {o.label: o.id for o in state.objects.values()
              if o.type == "point" and o.label and o.status != "rejected"}
    # A point can legitimately be unnamed while a separate label object binds
    # to it. Count both representations; requiring point.label alone gives
    # false negatives for Geometry's labels_point submissions.
    for label, key in state.label_bindings.items():
        obj = state.objects.get(key)
        if obj and obj.type == "point" and obj.status != "rejected":
            points[label] = key
    for rel in state.relations.values():
        if rel.relation != "labels_point" or rel.status == "rejected":
            continue
        label, point = state.objects.get(rel.subject), state.objects.get(rel.object)
        if label and point and label.label and point.type == "point" and point.status != "rejected" and label.status != "rejected":
            points[label.label] = point.id
    return {"drawn_labels": sorted(labels), "ges_point_labels": sorted(points),
            "drawn_labels_without_ges_point": sorted(labels - points.keys()),
            "ges_point_labels_not_drawn": sorted(points.keys() - labels),
            "point_ids": points,
            "audit_version": "2: point labels or valid bindings/labels_point relations",
            "limitation": "Math-label extraction is heuristic; no full TikZ semantic parsing."}


def serious(report: dict) -> int:
    return sum(i.get("severity") in ("high", "medium")
               for i in report.get("issues", []) if not i.get("flaky"))


def diagnose(runner: GeoAgentRunner) -> dict:
    state = runner.state
    latest = state.latest_version()
    system = """Diagnose a geometric image-to-TikZ reconstruction failure.
The critic provides symptoms, not established causes. Compare GES, source and
the critic. Select ONE route: perception, geometry, code, review, or no_change.
Use geometry when evidence exists but the GES lacks objects/relations. Use code
only when GES already describes the required structure. Use perception if new
image evidence is needed; review if the critic may be wrong. Never assume a
computed intersection proves a visible stroke. Do not invent measurements.
Return JSON: {route, hypotheses:[{cause,evidence}], missing_evidence:[],
instruction, verification_checks:[]}. Give precise instructions without an
invented numeric repair answer. Do not solve by editing code at this stage."""
    user = json.dumps({"ges": state.summary(max_objects=80, max_chars=18000),
                       "audit": audit(state), "tex": latest.tex,
                       "critic": latest.critic_report}, ensure_ascii=False)
    result = runner.client.complete_json(system, user, tag="repair_diagnosis", max_tokens=3000)
    if result.get("route") not in {"perception", "geometry", "code", "review", "no_change"}:
        raise ValueError("Diagnosis returned an invalid route")
    return result


def verify_geometry(before: GeometricEvidenceState, after: GeometricEvidenceState,
                    out_dir: Path) -> dict:
    """Check new segment ink against the ORIGINAL image, independently of VLM."""
    # This pilot permits additions only. ROI CV reruns can reuse seg_01, seg_02,
    # etc. and overwrite global detections during ingest. Restore those records
    # before accepting the candidate, retaining a visible audit of collisions.
    restored = []
    for key, old in before.objects.items():
        new = after.objects.get(key)
        if new and old.type != "point" and any(
            getattr(old, field) != getattr(new, field)
            for field in ("type", "coords", "style", "label", "status")
        ):
            restored.append({"object_id": key, "candidate": new.model_dump(),
                             "reason": "Existing object frozen in this additions-only pilot"})
            after.objects[key] = old.model_copy(deep=True)
    # Geometry submissions can contain plausible names for objects that were
    # never declared. Quarantine such relations rather than accepting a broken graph.
    quarantined = []
    for key, relation in after.relations.items():
        if key in before.relations or relation.status == "rejected":
            continue
        missing = [ref for ref in (relation.subject, relation.object)
                   if ref and ref not in after.objects]
        if missing:
            relation.status = "rejected"
            relation.evidence = (relation.evidence or "") + " [Quarantined: undeclared object reference]"
            quarantined.append({"relation_id": key, "missing_object_ids": missing})
    changes = [o for key, o in after.objects.items()
               if key not in before.objects or o.model_dump() != before.objects[key].model_dump()]
    moved = []
    for key, old in before.objects.items():
        new = after.objects.get(key)
        if new and old.type == "point" and old.coords != new.coords:
            moved.append(key)
    checks = []
    for obj in changes:
        if obj.type != "segment" or obj.status == "rejected":
            continue
        a, b = obj.coords.get("a_px"), obj.coords.get("b_px")
        if a is None or b is None:
            checks.append({"object_id": obj.id, "supported": False, "error": "missing endpoints"})
            continue
        result = analyze_line_style(before.image_path, a=a, b=b, out_dir=out_dir / obj.id)
        styles = result.get("results", {}).get("styles", [])
        observed = styles[0].get("style") if styles else None
        expected = obj.style.get("line")
        supported = observed in {"solid", "dashed"} and (not expected or expected == observed)
        checks.append({"object_id": obj.id, "expected_style": expected,
                       "observed_style": observed, "supported": supported, "cv_result": result})
        if supported:
            after.add_evidence(source="routing_experiment", method="original-image segment ink check",
                               summary=f"{obj.id}: observed={observed}", payload=checks[-1])
    return {"changed_objects": [o.id for o in changes], "moved_existing_points": moved,
            "quarantined_relations": quarantined,
            "restored_existing_objects": restored,
            "segment_checks": checks,
            "passed": bool(changes) and not moved and all(c["supported"] for c in checks),
            "limitation": "Conservative gate: freezes existing points; segment CV is heuristic. "
                          "Point-only additions have no independent ink check."}


def bind_new_labels(state: GeometricEvidenceState, ids: list[str]) -> None:
    for key in ids:
        obj = state.objects[key]
        if obj.type == "point" and obj.label and obj.status != "rejected":
            state.label_bindings[obj.label] = obj.id


def run_arm(seed: GeometricEvidenceState, directory: Path, routed: bool) -> dict:
    directory.mkdir(parents=True, exist_ok=False)
    settings = load_settings()
    settings.model.max_retries = 1
    runner = GeoAgentRunner(seed.image_path, settings=settings, run_dir=directory)
    runner.state = seed.model_copy(deep=True)
    for agent in (runner.geometry_agent, runner.tikz_agent, runner.critic_agent):
        agent.state = runner.state
    started = time.perf_counter()
    result = {"arm": "routed" if routed else "direct", "events": [],
              "initial_score": seed.latest_version().critic_score,
              "initial_serious_issues": serious(seed.latest_version().critic_report or {})}
    def event(stage, data):
        result["events"].append({"stage": stage, "result": data})
        save(directory / "progress.json", result)
        print(f"[{result['arm']}] {stage}", flush=True)
    try:
        # Recompile the shared seed under the same renderer before either repair.
        event("compile_seed", runner._compile_version(1))
        save(directory / "state_before.json", runner.state.model_dump())
        event("audit_before", audit(runner.state))
        instruction = "Fix the actionable issues in the supplied critic report. Preserve all correct elements, coordinate scale, stroke weight and label size. Return the full document."
        route = "code"
        if routed:
            observation = None
            diagnosis = diagnose(runner)
            save(directory / "diagnosis.json", diagnosis)
            event("diagnose", diagnosis)
            route = diagnosis["route"]
            if route in {"perception", "review"}:
                observation = runner.client.complete_json(
                    "Verify reported image discrepancies against the original. Return JSON {confirmed:bool, evidence:[], instruction}. Do not infer invisible strokes from geometry alone.",
                    json.dumps({"diagnosis": diagnosis, "critic": seed.latest_version().critic_report}),
                    images=[seed.image_path], tag="routing_reobserve", max_tokens=2000)
                event("reobserve", observation)
                runner.state.add_evidence(source="routing_reobserve", method="original-image VLM observation",
                    summary="Independent visual check of the critic's symptom", payload=observation)
                route = "geometry" if observation.get("confirmed") is True else "no_change"
            if route == "geometry":
                before = runner.state.model_copy(deep=True)
                geometry = runner.geometry_agent.run(
                    "Repair the GES only for the critic discrepancies. Verify the original IMAGE for actual visible strokes and labels before adding anything. "
                    "Use existing pixel coordinates to derive intersections when justified, and explain the derivation. "
                    "Keep established objects unchanged. Use NEW ids for missing objects, include endpoints in a_px/b_px for segments, "
                    "line style, point label and relations. No right-angle inference from shape alone. "
                    "Every relation endpoint must name an existing or explicitly submitted object ID. "
                    "Submit only the necessary additions and their evidence.\nDIAGNOSIS: " + json.dumps(diagnosis, ensure_ascii=False)
                    + "\nORIGINAL IMAGE OBSERVATION (approximate visual coordinates are NOT precise measurements): "
                    + json.dumps(observation, ensure_ascii=False)
                    + "\nCRITIC: " + json.dumps(seed.latest_version().critic_report, ensure_ascii=False),
                    cv_calls_left=2, image_path=seed.image_path)
                event("geometry", geometry)
                if not geometry.get("ok"):
                    raise RuntimeError("Geometry agent failed to submit")
                verified = verify_geometry(before, runner.state, directory / "verify_cv")
                save(directory / "geometry_verification.json", verified)
                event("verify_geometry", verified)
                if not verified["passed"]:
                    # Branch terminates without code repair; candidate remains available for inspection.
                    save(directory / "rejected_geometry_state.json", runner.state.model_dump())
                    runner.state = before
                    for agent in (runner.geometry_agent, runner.tikz_agent, runner.critic_agent):
                        agent.state = runner.state
                    raise RuntimeError("Geometry verification failed; state rolled back")
                bind_new_labels(runner.state, verified["changed_objects"])
                save(directory / "state_after_geometry.json", runner.state.model_dump())
                instruction += " The GES has been repaired and source-image CV checked. Implement the new geometry and preserve unaffected contents.\n" + json.dumps(verified["changed_objects"])
            elif route == "code":
                instruction += "\nDIAGNOSIS: " + json.dumps(diagnosis, ensure_ascii=False)
        if route != "no_change":
            event("repair_tikz", runner._do_tikz_agent({"mode": "repair", "instruction": instruction}))
        event("critic_after", runner._do_critic({"focus": "Verify the originally reported discrepancies are fixed, and check for any regressions elsewhere."}))
        latest = runner.state.latest_version()
        report = latest.critic_report or {}
        result.update({"status": "completed", "selected_route": route,
            "compile_ok": latest.ok, "critic_score": report.get("assessment_score"),
            "must_repair": report.get("must_repair"), "serious_issues": serious(report),
            "not_worse_by_critic": serious(report) <= serious(seed.latest_version().critic_report or {}),
            "ssim": ssim_pair(latest.png_path, seed.image_path) if latest.ok else None,
            "png_path": latest.png_path, "tex_path": latest.tex_path,
            "audit_after": audit(runner.state)})
    except Exception as exc:
        # Exception types only: provider exception messages can contain sensitive data.
        result.update({"status": "failed", "error_type": type(exc).__name__})
        event("failed", {"type": type(exc).__name__})
    finally:
        result["elapsed_s"] = round(time.perf_counter() - started, 2)
        result["usage"] = runner.client.usage_summary()
        save(directory / "state_after.json", runner.state.model_dump())
        save(directory / "result.json", result)
    return result


def write_report(directory: Path, seed: GeometricEvidenceState, results: list[dict]) -> None:
    rows = ["# " + seed.meta["replay"]["stem"] + " 修复路由试验", "", "同一归档 v1 与首轮报告开始，各执行至多一次 TikZ 修复。",
            "这是重建状态的单样本回放，非完整端到端重跑，也非等成本对照。未使用 v2 或参考 LaTeX。", "",
            "| 方案 | 状态 | 编译 | Critic | 必须继续修复 | SSIM | token | 视觉调用 | 秒 |",
            "|---|---|---|---|---|---|---|---|---|"]
    for r in results:
        u = r["usage"]["totals"]
        rows.append(f"| {r['arm']} | {r['status']} | {r.get('compile_ok')} | {r.get('critic_score')} | {r.get('must_repair')} | {r.get('ssim')} | {u['total_tokens']} | {u['visual_calls']} | {r['elapsed_s']} |")
    rows += ["", "Critic 为内部启发式评审，SSIM 为现有整图协议，两者均不能替代独立结构标注。",
             "路由组额外消耗诊断、视觉取证和 Geometry 调用，不能据此单次试验宣称优于基线。", ""]
    for r in results:
        rows += [f"## {r['arm']}", "", "```json", json.dumps(r.get("audit_after", {}), ensure_ascii=False, indent=2), "```", ""]
        if r.get("png_path"):
            relative = Path(r["png_path"]).resolve().relative_to(directory.resolve()).as_posix()
            rows += [f"![{r['arm']}]({relative})", ""]
    (directory / "report.md").write_text("\n".join(rows), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stem", default="1260_q_fig2")
    parser.add_argument("--prepare-only", action="store_true", help="No API calls")
    parser.add_argument("--out-dir", type=Path)
    args = parser.parse_args()
    directory = args.out_dir or ROOT / "outputs" / "repair_routing" / (datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + args.stem)
    directory.mkdir(parents=True, exist_ok=False)
    seed = prepare_seed(args.stem, directory)
    print(f"Output: {directory}", flush=True)
    if args.prepare_only:
        print(json.dumps(audit(seed), ensure_ascii=False), flush=True)
        return
    results = []
    for arm in ("direct", "routed"):
        results.append(run_arm(seed, directory / arm, arm == "routed"))
        save(directory / "summary.json", results)
    write_report(directory, seed, results)
    print(json.dumps([{k: r.get(k) for k in ("arm", "status", "critic_score", "ssim", "selected_route")} for r in results]), flush=True)
    if any(r["status"] == "failed" for r in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
