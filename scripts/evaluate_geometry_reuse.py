"""Measure verified local edits and geometry queries on a frozen cohort."""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import re
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from geoagent.config import load_settings
from geoagent.evaluation.structure import backend
from scripts.edit_geometry import EditError, compile_edit, drawing, edit, LABEL


OPERATIONS = ("rename", "midpoint", "toggle-dash")


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def digest(value):
    return hashlib.sha256(value).hexdigest()


def frozen_tasks(references):
    tasks = {}
    for stem, reference in references.items():
        edges = sorted(tuple(edge) for edge in reference["edges"] if all(re.fullmatch(LABEL, label) for label in edge))
        if not edges:
            raise ValueError(f"no eligible reference edge for {stem}")
        a, b = min(edges, key=lambda edge: digest(f"edit-v1/{stem}/{edge}".encode()))
        fresh = next(letter for letter in "ZYXWVUTSRQPONMLKJIHGFEDCBA" if letter not in reference["points"])
        tasks[stem] = {"rename": ([a], fresh), "midpoint": ([a, b], fresh), "toggle-dash": ([a, b], None)}
    return tasks


def edit_group(stem, name, directory, tasks, compile_sample, settings):
    source = directory / "latex" / f"{stem}.tex"
    tex = source.read_text(encoding="utf-8")
    result = {"method": name, "stem": stem, "source_sha256": digest(source.read_bytes()), "operations": {}}
    try:
        parsed = drawing(tex)
    except ValueError as exc:
        for op in OPERATIONS:
            result["operations"][op] = {"source_ok": False, "reason": str(exc), "compiled": None}
        return result
    for op, (labels, fresh) in tasks.items():
        row = {"source_ok": False, "compiled": None}
        try:
            edited, evidence = edit(tex, op, labels, new_label=fresh, parsed=parsed)
            row.update(source_ok=True, edit=evidence)
            if compile_sample:
                try:
                    with TemporaryDirectory(prefix="geoagent_edit_eval_") as tmp:
                        compile_edit(edited, evidence, settings, tmp)
                    row["compiled"] = True
                except (EditError, OSError, ValueError) as exc:
                    row.update(compiled=False, reason=str(exc))
        except (EditError, ValueError) as exc:
            row["reason"] = str(exc)
        result["operations"][op] = row
    return result


def angle_class(value):
    if abs(value - 90) <= 1:
        return "right"
    if value >= 179:
        return "straight"
    return "acute" if value < 90 else "obtuse"


def query_summary(groups):
    summary = {}
    for name, group in groups.items():
        bins = {label: Counter() for label in ("acute", "right", "obtuse", "straight", "longer")}
        for diagram in group["per_stem"].values():
            for check in diagram["angle_checks"]:
                target, predicted = check["target"], check.get("predicted")
                if 1 < abs(target - 90) < 3 or 177 < target < 179:
                    continue
                label = angle_class(target)
                bins[label]["total"] += 1
                if predicted is not None:
                    bins[label]["available"] += 1
                    bins[label]["correct"] += angle_class(predicted) == label
            for check in diagram["ratio_checks"]:
                target, predicted = check["target"], check.get("predicted")
                if max(target, 1 / target) < 1.05:
                    continue
                bins["longer"]["total"] += 1
                if predicted is not None:
                    bins["longer"]["available"] += 1
                    bins["longer"]["correct"] += predicted != 1 and (predicted > 1) == (target > 1)
        summary[name] = {label: dict(counts) for label, counts in bins.items()}
    return summary


def summarize_edits(rows, methods, sample):
    results = {}
    for method in methods:
        rows_for_method = [row for row in rows if row["method"] == method]
        results[method] = {}
        for op in OPERATIONS:
            records = [row["operations"][op] for row in rows_for_method]
            sampled = [row["operations"][op] for row in rows_for_method if row["stem"] in sample]
            results[method][op] = {
                "total": len(records), "source_pass": sum(r["source_ok"] for r in records),
                "compile_sample": len(sampled), "compile_attempts": sum(r["compiled"] is not None for r in sampled),
                "compiled_and_verified": sum(r["compiled"] is True for r in sampled),
                "reasons": dict(Counter(r["reason"] for r in records if "reason" in r)),
            }
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--group", action="append", required=True)
    parser.add_argument("--structure", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=10)
    parser.add_argument("--compile-sample", type=int, default=30)
    args = parser.parse_args()
    methods = {name: Path(directory) for name, directory in (arg.split("=", 1) for arg in args.group)}
    structure = read(args.structure)
    stems = structure["shared_stems"]
    if not 0 <= args.compile_sample <= len(stems) or not set(methods) <= set(structure["groups"]):
        parser.error("invalid compilation sample or group missing from the structural results")
    reference_dir = ROOT / "data/test/geometry_reference"
    manifest = read(reference_dir / "manifest.json")
    references = {}
    for stem in stems:
        reference = reference_dir / f"{stem}.json"
        if digest(reference.read_bytes()) != manifest["files"][stem]:
            raise ValueError(f"reference changed for {stem}")
        references[stem] = read(reference)
    sample = set(sorted(stems, key=lambda stem: digest(f"compile-v1/{stem}".encode()))[:args.compile_sample])
    tasks = frozen_tasks(references)
    settings = load_settings()
    backend()  # Resolve the parser dependency before starting workers.

    def run(job):
        stem, name = job
        row = edit_group(stem, name, methods[name], tasks[stem], stem in sample, settings)
        if row["source_sha256"] != structure["groups"][name]["per_stem"][stem]["program_sha256"]:
            raise ValueError(f"evaluated input changed for {name}/{stem}")
        return row

    jobs = [(stem, name) for stem in stems for name in methods]
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        rows = []
        for row in pool.map(run, jobs):
            rows.append(row)
            if len(rows) % 50 == 0 or len(rows) == len(jobs):
                print(f"Checked {len(rows)}/{len(jobs)} input diagrams", flush=True)
    output = {"schema": "geometry-reuse.v1", "sample": sorted(sample), "tasks": tasks,
              "reference_manifest_sha256": digest((reference_dir / "manifest.json").read_bytes()),
              "edits": summarize_edits(rows, methods, sample),
              "queries": query_summary({name: structure["groups"][name] for name in methods}), "cases": rows}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
