"""Compare archived pre-review and final versions with the same extended repair."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import json
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from geoagent.config import load_settings
from geoagent.state.repair_pipeline import repair_generated_tikz
from geoagent.state.tikz_geometry import extract_geometry
from geoagent.tools import compile_tikz, frame_like_original, render_pdf
from scripts.evaluate_reference_constraints import DIAGRAM_THRESHOLDS, all_within
from scripts.evaluate_structure_ab import paired_geometry


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def select_checkpoints(state):
    first = next(v for v in state["tikz_versions"] if v["compiled"] and v["ok"] and v["png_path"])
    best = next(v for v in state["tikz_versions"] if v["version"] == state["best_version"])
    if first["version"] != state["critic_reports"][0]["version"]:
        raise ValueError("First usable version does not match the first Critic review")
    if not best["compiled"] or not best["ok"]:
        raise ValueError("Invalid final selection in archive")
    reports = state["meta"]["tikz_constraint_repairs"]
    before, after = (reports[str(v["version"])] for v in (first, best))
    if any(before.get(key) != after.get(key) for key in ("algorithm", "enabled", "limits", "curve_options_applied")):
        raise ValueError("The two checkpoints use different geometry repair settings")
    return {"critic_off": first, "critic_on": best}


def export(stem, archive, out, settings, raw_inputs, full_replay, full_cases):
    state_path = archive / "stem" / stem / "state.json"
    state = read(state_path)
    archived_tex = archive / "latex" / f"{stem}.tex"
    archived_png = archive / "image" / f"{stem}.png"
    archived_source = archived_tex.read_text(encoding="utf-8").strip()
    original = settings.paths.image_dir / f"{stem}.png"
    row = {"state_sha256": digest(state_path), "original_image_sha256": digest(original)}
    selected = select_checkpoints(state)
    best_source = state_path.with_name("best.tex").read_text(encoding="utf-8").strip()
    if selected["critic_on"]["tex"].strip() != best_source:
        raise ValueError(f"{stem}: archived best.tex differs from the recorded best version")
    first, best = (selected[g] for g in ("critic_off", "critic_on"))
    meta = state["meta"]
    first_report = meta["tikz_constraint_repairs"][str(first["version"])]
    raw = raw_inputs[stem]
    if sha256(raw.encode()).hexdigest() != first_report["input_sha256"]:
        raise ValueError(f"{stem}: first checkpoint source does not match the archive")

    final_raw = (state_path.parent / "unrepaired.tex").read_text(encoding="utf-8")
    final_report = read(state_path.with_name("constraint_repair.json"))
    full_case = full_cases[stem]
    final_tex = full_replay / "latex" / f"{stem}.tex"
    final_png = full_replay / "image" / f"{stem}.png"
    final_source = final_tex.read_text(encoding="utf-8")
    if (sha256(final_raw.encode()).hexdigest() != final_report["input_sha256"]
            or final_report["input_sha256"] != meta["tikz_constraint_repairs"][str(best["version"])]["input_sha256"]
            or full_case["input_sha256"] != digest(state_path.with_name("unrepaired.tex"))
            or full_case["program_sha256"] != digest(final_tex)
            or full_case["image_sha256"] != digest(final_png)
            or full_case["original_image_sha256"] != row["original_image_sha256"]):
        raise ValueError(f"{stem}: complete method replay does not match this archive")

    if first["version"] == best["version"]:
        if raw != final_raw:
            raise ValueError(f"{stem}: the shared checkpoint has two different sources")
        first_tex = final_source
        repair_report = full_case["report"]
    else:
        coordinates = meta["tikz_coordinate_contracts"].get(str(first["version"]), {}).get("coordinates")
        # The final Supervisor plan can contain post-Critic observations.
        # Guard the inventory in the first checkpoint's own source instead.
        try:
            edges = extract_geometry(raw)["segments"]
        except ValueError:
            plan = None
        else:
            plan = {"required_edges": list(edges.values())}
        repair = repair_generated_tikz(raw, settings, plan=plan, source_coordinates=coordinates,
                                       source_image=original if coordinates else None)
        first_tex, repair_report = repair.tex, repair.report
    for group, version in selected.items():
        path = out / group / "latex" / f"{stem}.tex"
        png = out / group / "image" / f"{stem}.png"
        tex = first_tex if group == "critic_off" else final_source
        if group == "critic_on" or tex == final_source:
            shutil.copyfile(final_tex, path)
            shutil.copyfile(final_png, png)
        elif tex.strip() == archived_source:
            shutil.copyfile(archived_png, png)
            path.write_text(tex, encoding="utf-8")
        else:
            with TemporaryDirectory(prefix="geoagent_critic_ablation_") as directory:
                compiled = compile_tikz(tex, out_dir=directory, paths=settings.paths,
                                        timeout=settings.budget.compile_timeout_seconds)
                if not compiled["ok"]:
                    raise RuntimeError(f"{group}/{stem}: {compiled['errors']}")
                if not render_pdf(compiled["pdf_path"], png, dpi=200)["ok"]:
                    raise RuntimeError(f"{group}/{stem}: render failed")
                if not frame_like_original(png, original)["ok"]:
                    raise RuntimeError(f"{group}/{stem}: framing failed")
            path.write_text(tex, encoding="utf-8")
        row[group] = {"version": version["version"], "program_sha256": digest(path),
                      "image_sha256": digest(png)}
    row["critic_off"]["input_sha256"] = first_report["input_sha256"]
    row["critic_off"]["repair_reason"] = repair_report["reason"]
    row["critic_off"]["export_mode"] = repair_report.get("extended_hybrid", {}).get("mode")
    row["critic_on"]["input_sha256"] = final_report["input_sha256"]
    return row


def evaluate(out, stems, workers, cases):
    groups = ("critic_off", "critic_on")
    structure_path, visual_path = out / "structure.json", out / "visual.json"
    structure = [sys.executable, str(ROOT / "scripts/evaluate_structure_ab.py"),
                 "--workers", str(workers), "--out", str(structure_path)]
    visual = [sys.executable, str(ROOT / "scripts/evaluate_visual_cached.py"),
              "--out", str(visual_path)]
    for group in groups:
        structure += ["--group", f"{group}={out / group}"]
        visual += ["--group", f"{group}={out / group / 'image'}"]
    with ThreadPoolExecutor(max_workers=2) as pool:
        jobs = [pool.submit(subprocess.run, command, check=True) for command in (structure, visual)]
        for job in jobs:
            job.result()
    structured, pixels = read(structure_path), read(visual_path)
    if structured["shared_stems"] != stems or pixels["shared_stems"] != stems:
        raise ValueError("Both evaluations must cover every frozen image")
    per_group = {group: structured["groups"][group]["per_stem"] for group in groups}
    geometry = paired_geometry(per_group, list(groups), stems)
    summaries = {}
    for group, rows in per_group.items():
        passed = [0] * len(DIAGRAM_THRESHOLDS)
        for stem, row in rows.items():
            expected = cases[stem][group]
            if (row["program_sha256"] != expected["program_sha256"]
                    or pixels["evaluated_image_sha256"][group][stem] != expected["image_sha256"]
                    or pixels["evaluated_image_sha256"]["reference"][stem] != cases[stem]["original_image_sha256"]):
                raise ValueError(f"Evaluation input mismatch: {group}/{stem}")
            edges = row["geometry_quality"]["edges"]
            expected["diagram_pass"] = [
                row["compiled"] and edges["matched"] == edges["reference"] == edges["predicted"]
                and all_within(row["angle_checks"], a) and all_within(row["ratio_checks"], r)
                for a, r in DIAGRAM_THRESHOLDS
            ]
            for index, result in enumerate(expected["diagram_pass"]):
                passed[index] += result
        quality = structured["groups"][group]["summary"]["geometry_quality"]
        summaries[group] = {
            **pixels["groups"][group]["summary"],
            "angle_mae_common_deg": geometry["angle"]["means"][group],
            "ratio_mre_common": geometry["ratio"]["means"][group],
            "edge_f1": quality["edge_f1"],
            "point_error": quality["point_error"],
            "diagram_pass": passed,
        }
    return summaries, geometry, structure_path, visual_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, default=ROOT / "outputs/ours")
    parser.add_argument("--first-inputs", type=Path, required=True, help="ZIP of hash-verified pre-repair inputs")
    parser.add_argument("--full-replay", type=Path, required=True, help="Completed extended_hybrid replay")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=12)
    args = parser.parse_args()
    archive, out, summary = args.archive.resolve(), args.out.resolve(), args.summary.resolve()
    if args.workers < 1 or any(p == archive or archive in p.parents for p in (out, summary)):
        parser.error("use a positive worker count and output paths outside the archive")
    manifest = ROOT / "data/test/geometry_reference/manifest.json"
    stems = sorted(read(manifest)["files"])
    full_replay = args.full_replay.resolve()
    full = read(full_replay / "replay.json")
    if (full["reference_manifest_sha256"] != digest(manifest)
            or full["geometry_settings"]["post_repair_mode"] != "extended_hybrid"
            or not full["geometry_settings"]["enabled"]):
        parser.error("expected a complete extended_hybrid replay on the frozen reference set")
    full_cases = {case["stem"]: case for case in full["cases"]}
    if set(full_cases) != set(stems):
        parser.error("full replay does not cover all images")
    settings = load_settings({"post_repair_mode": "extended_hybrid", "geometry_repair": True})
    if json.loads(json.dumps(settings.geometry.to_dict())) != full["geometry_settings"]:
        parser.error("current geometry settings differ from the full replay")
    with ZipFile(args.first_inputs) as bundle:
        raw_inputs = {stem: bundle.read(f"{stem}.tex").decode("utf-8") for stem in stems}
    for group in ("critic_off", "critic_on"):
        for directory in ("latex", "image"):
            (out / group / directory).mkdir(parents=True, exist_ok=True)
    cases = {}
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        jobs = pool.map(lambda stem: export(stem, archive, out, settings, raw_inputs, full_replay, full_cases), stems)
        for stem, row in zip(stems, jobs, strict=True):
            cases[stem] = row
            if len(cases) % 25 == 0:
                print(f"Exported {len(cases)}/{len(stems)} pairs", flush=True)
    groups, geometry, structure, visual = evaluate(out, stems, args.workers, cases)
    replay = out / "replay.json"
    write_json(replay, cases)
    write_json(summary, {
        "schema": "geoagent-critic-checkpoint-ablation-v3",
        "images": len(stems),
        "protocol": "Paired archive replay at the first usable version before Critic and at the final selected version.",
        "geometry_repair": "extended_hybrid",
        "first_inputs_sha256": digest(args.first_inputs),
        "full_replay_sha256": digest(full_replay / "replay.json"),
        "reference_manifest_sha256": digest(manifest),
        "diagram_thresholds": [{"angle_deg": a, "ratio_relative": r} for a, r in DIAGRAM_THRESHOLDS],
        "groups": groups,
        "geometry_common": geometry,
        "changed_programs": sum(c["critic_off"]["program_sha256"] != c["critic_on"]["program_sha256"] for c in cases.values()),
        "scores_sha256": {p.name: digest(p) for p in (replay, structure, visual)},
    })
    print(json.dumps(groups, indent=2), flush=True)


if __name__ == "__main__":
    main()
