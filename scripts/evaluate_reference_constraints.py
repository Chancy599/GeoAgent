"""Evaluate source-derived relations and whole-diagram geometry on a fixed image set."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from hashlib import sha256
from itertools import combinations
import json
from math import atan2, degrees, hypot, isfinite
from pathlib import Path
import re
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from geoagent.evaluation.structure import (  # noqa: E402
    _drawing, _reviewed_reference_source, backend, load_reference, make_graph,
    prediction, reference_items, score,
)
from geoagent.tools.compiler import compile_tikz, discover_compiler  # noqa: E402

SOURCE_EPSILON = 1e-6  # Degrees; absorb floating-point evaluation noise.
DIRECTION_TOLERANCE = 0.1  # Degrees.
DIAGRAM_THRESHOLDS = ((1.0, 0.02), (0.5, 0.01))
KINDS = ("perpendicular", "parallel", "collinear")
ANCHOR_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_']*")


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def file_hash(path):
    return sha256(path.read_bytes()).hexdigest()


def displacement(a, b):
    return b[0] - a[0], b[1] - a[1]


def cross(u, v):
    return u[0] * v[1] - u[1] * v[0]


def dot(u, v):
    return u[0] * v[0] + u[1] * v[1]


def relation_error(kind, edges, points, line_epsilon=0):
    """Return the zero-test value and angular error, or None for invalid geometry."""
    (a, b), (c, d) = (tuple(points[label] for label in edge) for edge in edges)
    u, v = displacement(a, b), displacement(c, d)
    if u == (0, 0) or v == (0, 0):
        return None
    product, determinant = dot(u, v), cross(u, v)
    if kind == "collinear" and product <= 0:  # Directed path A -> B -> C.
        return None
    if kind == "parallel":
        offset = max(abs(cross(u, displacement(a, p))) for p in (c, d))
        if offset <= line_epsilon * hypot(*u):
            return None
    if kind == "perpendicular":
        return product, degrees(atan2(abs(product), abs(determinant)))
    return determinant, degrees(atan2(abs(determinant), abs(product)))


def named_edges(graph, items):
    return {tuple(sorted(graph.label_names[i] for i in edge)) for edge in items["edges"]}


def direction_relations(graph):
    points = {name: tuple(map(float, xy)) for name, xy in zip(graph.label_names, graph.points)}
    edges = named_edges(graph, reference_items(graph))
    relations = []
    for first, second in combinations(sorted(edges), 2):
        kinds = ("perpendicular",)
        if not set(first).intersection(second):
            kinds += ("parallel",)
        for kind in kinds:
            result = relation_error(kind, (first, second), points, 1e-8 * graph.span)
            if result is not None and result[1] <= SOURCE_EPSILON:
                relations.append({"kind": kind, "edges": (first, second), "source_error_deg": result[1]})
    for a, b, c in combinations(sorted(points), 3):
        for left, middle, right in ((b, a, c), (a, b, c), (a, c, b)):
            pair = ((left, middle), (middle, right))
            if not all(tuple(sorted(edge)) in edges for edge in pair):
                continue
            result = relation_error("collinear", pair, points)
            if result is not None and result[1] <= SOURCE_EPSILON:
                relations.append({"kind": "collinear", "edges": pair, "source_error_deg": result[1]})
                break
    return edges, relations


def read_compiled_bindings(tex, graph, labels, out_dir):
    """Probe explicit named anchors and materialize literal label anchors."""
    aliases = {}
    definitions = []
    for index, label in enumerate(sorted(set(labels) & graph.bindings.keys())):
        binding = graph.bindings[label]
        expression = binding["expressions"][0]
        if expression in binding["coordinate_aliases"] and ANCHOR_NAME.fullmatch(expression):
            aliases[label] = expression
        elif expression is None:
            name = next((name for name in binding["coordinate_aliases"] if ANCHOR_NAME.fullmatch(name)), None)
            if name:
                aliases[label] = name
        else:
            name = f"geoagentevalprobe{index}"
            if name in tex:
                raise ValueError(f"Probe name already used: {name}")
            aliases[label] = name
            definitions.append(rf"\path ({expression}) coordinate ({name});")
    if aliases:
        # Read physical canvas coordinates, not the current picture transform's inverse.
        probes = "\n".join([*definitions, r"\pgftransformreset"])
        tex = tex.replace(r"\end{tikzpicture}", "\n" + probes + "\n" + r"\end{tikzpicture}")
    compiled = compile_tikz(tex, out_dir=out_dir, probe_names=tuple(dict.fromkeys(aliases.values())))
    anchors = compiled.get("points_sp", {}) if compiled["ok"] else {}
    return compiled, {label: anchors[name] for label, name in aliases.items() if name in anchors}


def all_within(checks, tolerance):
    return all(item["available"] and isfinite(item["error"]) and item["error"] <= tolerance for item in checks)


def evaluate(path, case, out_dir, *, is_reference=False):
    gt, items, source_graph, source_edges, relations = case
    row = {"program_sha256": None, "compiled": False,
           "diagram_pass": [False] * len(DIAGRAM_THRESHOLDS), "relations": []}
    point_labels = {label for relation in relations for edge in relation["edges"] for label in edge}
    measured = {}
    pred_edges = set()
    try:
        row["program_sha256"] = file_hash(path)
        tex = path.read_text(encoding="utf-8")
        pred = source_graph if is_reference else prediction(path)
        pred_edges = source_edges if is_reference else named_edges(pred, reference_items(pred))
        compilation, measured = read_compiled_bindings(tex, pred, point_labels, out_dir)
        row["compiled"] = compilation["ok"]
        row["missing_probes"] = sorted(point_labels.intersection(pred.bindings).difference(measured))
        if not compilation["ok"]:
            row["error"] = compilation["errors"] or compilation["log_tail"]
        if row["compiled"] and not is_reference:
            checks = score(gt, pred, items)
            row["diagram_pass"] = [
                pred_edges == named_edges(gt, items)
                and all_within(checks["angle_checks"], angle)
                and all_within(checks["ratio_checks"], ratio)
                for angle, ratio in DIAGRAM_THRESHOLDS
            ]
    except (OSError, ValueError) as exc:
        row["error"] = str(exc)

    for relation in relations:
        edges = relation["edges"]
        error = None
        if all(tuple(sorted(edge)) in pred_edges for edge in edges) and all(
            label in measured for edge in edges for label in edge
        ):
            error = relation_error(relation["kind"], edges, measured)
        row["relations"].append({
            "error_deg": None if error is None else error[1],
            "strict": error is not None and error[0] == 0,
            "within_tolerance": error is not None and error[1] <= DIRECTION_TOLERANCE,
        })
    return row


def summarize(rows, cases):
    counts = {kind: dict(total=0, measurable=0, strict=0, within_tolerance=0) for kind in KINDS}
    for stem, row in rows.items():
        for relation, result in zip(cases[stem][-1], row["relations"], strict=True):
            count = counts[relation["kind"]]
            count["total"] += 1
            count["measurable"] += result["error_deg"] is not None
            count["strict"] += result["strict"]
            count["within_tolerance"] += result["within_tolerance"]
    return {
        "compiled": sum(row["compiled"] for row in rows.values()),
        "diagram_pass": [sum(row["diagram_pass"][i] for row in rows.values())
                         for i in range(len(DIAGRAM_THRESHOLDS))],
        "relations": {"all": {k: sum(c[k] for c in counts.values()) for k in counts[KINDS[0]]}, **counts},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--group", action="append", required=True, metavar="NAME=LATEX_DIR")
    parser.add_argument("--reference-dir", type=Path, default=ROOT / "data/test/geometry_reference")
    parser.add_argument("--reference-tex", type=Path, default=ROOT / "data/test/latex")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--details", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()
    specs = [spec.partition("=") for spec in args.group]
    groups = {name: Path(path) for name, _, path in specs}
    if args.workers < 1 or any(not name or not sep or not path for name, sep, path in specs):
        parser.error("expected --group NAME=LATEX_DIR and a positive worker count")
    if len(groups) != len(specs) or "reference_tex" in groups:
        parser.error("group names must be unique and cannot include reference_tex")
    backend()
    compiler = discover_compiler()
    if not compiler["found"]:
        parser.error("a working TeX compiler is required")
    manifest_path = args.reference_dir / "manifest.json"
    manifest = read_json(manifest_path)
    corrections = read_json(args.reference_dir / "corrections.json")["cases"]
    cases, source_hashes = {}, {}
    for stem, expected in sorted(manifest["files"].items()):
        path = args.reference_dir / f"{stem}.json"
        if file_hash(path) != expected:
            raise ValueError(f"Frozen reference changed: {path}")
        gt, items = load_reference(path)
        source = args.reference_tex / f"{stem}.tex"
        source_hash = source_hashes[stem] = file_hash(source)
        if source_hash != read_json(path)["source_sha256"]:
            raise ValueError(f"Reference TeX changed: {source}")
        spec = corrections.get(stem, {})
        order_fix = {k: spec[k] for k in ("source_sha256", "intersection_order")} if "intersection_order" in spec else None
        source_graph = make_graph(_drawing(source, source_text=_reviewed_reference_source(source, order_fix, source_hash)))
        source_edges, relations = direction_relations(source_graph)
        cases[stem] = (gt, items, source_graph, source_edges, relations)
    print(f"Extracted {sum(len(case[-1]) for case in cases.values())} relations from {len(cases)} reference figures", flush=True)

    rows = {name: {} for name in ("reference_tex", *groups)}
    with TemporaryDirectory(prefix="geoagent_reference_eval_") as scratch, ThreadPoolExecutor(max_workers=args.workers) as pool:
        jobs = {}
        for index, (name, directory) in enumerate({"reference_tex": args.reference_tex, **groups}.items()):
            for stem, case in cases.items():
                future = pool.submit(evaluate, directory / f"{stem}.tex", case, Path(scratch) / str(index) / stem,
                                     is_reference=name == "reference_tex")
                jobs[future] = name, stem
        for job in as_completed(jobs):
            name, stem = jobs[job]
            rows[name][stem] = job.result()
            if len(rows[name]) == len(cases):
                print(f"{name}: {summarize(rows[name], cases)}", flush=True)

    details = {"reference_cases": {stem: {"source_sha256": source_hashes[stem], "relations": case[-1]}
                                  for stem, case in cases.items()},
               "groups": {name: dict(sorted(group.items())) for name, group in rows.items()}}
    summary = {
        "schema": "reference-direction-and-diagram-v1",
        "images": len(cases),
        "compiler": compiler["version"],
        "reference_manifest_sha256": file_hash(manifest_path),
        "reference_source": "reference TeX coordinates, with reviewed execution order for ambiguous intersections",
        "diagram_reference": "frozen reviewed geometry catalogue",
        "reference_epsilon_deg": SOURCE_EPSILON,
        "direction_tolerance_deg": DIRECTION_TOLERANCE,
        "diagram_thresholds": [{"angle_deg": a, "ratio_relative": r} for a, r in DIAGRAM_THRESHOLDS],
        "reference_image_counts_by_type": {kind: sum(any(rel["kind"] == kind for rel in case[-1])
                                                      for case in cases.values()) for kind in KINDS},
        "groups": {name: summarize(group, cases) for name, group in rows.items()},
    }
    del summary["groups"]["reference_tex"]["diagram_pass"]
    for path, data in ((args.details, details), (args.out, summary)):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
