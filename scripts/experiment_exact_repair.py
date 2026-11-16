"""Compare the archived repair with finer decimals and exact TeX dimensions.

The archived candidate sets, reference manifest and generation outputs stay frozen.
Experimental exports and compilation probes go to a separate directory.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
from time import perf_counter

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from geoagent.config import load_settings
from geoagent.state.exact_layout import (
    SP_PER_CM, adaptive_layout, exact_layout, float_solution, measures, pt_literal,
    rank, validate_layout, write_coordinates,
)
from geoagent.state.tikz_geometry import NAME, extract_geometry
from geoagent.tools.compiler import security_scan
from geoagent.tools.renderer import frame_like_original, render_pdf


GROUPS = ("current", "decimal6", "decimal9", "exact_tight", "exact_wide")
PROBE = re.compile(r"GEOINT:(" + NAME + r"):(-?\d+):(-?\d+)")


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def compile_probe(tex, names, tectonic, image=None, original=None):
    probe = ["\\makeatletter"]
    for name in sorted(names):
        probe.append(rf"\pgfpointanchor{{{name}}}{{center}}\typeout{{GEOINT:{name}:\number\pgf@x:\number\pgf@y}}")
    probe.append("\\makeatother")
    instrumented = tex.replace(r"\end{tikzpicture}", "\n" + "\n".join(probe) + "\n" + r"\end{tikzpicture}", 1)
    if instrumented == tex or security_scan(instrumented):
        raise ValueError("unprobeable TeX source")
    with TemporaryDirectory(prefix="geoagent_exact_") as temporary:
        work = Path(temporary)
        (work / "figure.tex").write_text(instrumented, encoding="utf-8")
        process = subprocess.run([str(tectonic), "--keep-logs", "--untrusted", "figure.tex"],
                                 cwd=work, capture_output=True, timeout=120)
        log = (work / "figure.log").read_text(encoding="utf-8", errors="replace")
        points = {n: (int(x), int(y)) for n, x, y in PROBE.findall(log)}
        if process.returncode or set(points) != set(names):
            raise ValueError(f"compilation/probe failed ({process.returncode}, {len(points)}/{len(names)})")
        if image is not None:
            rendered = render_pdf(work / "figure.pdf", image, dpi=200)
            if not rendered["ok"] or not frame_like_original(image, original)["ok"]:
                raise ValueError("render or framing failed")
        return points


def one_image(stem, archive, out, tectonic, render):
    start = perf_counter()
    folder = archive / "stem" / stem
    tex_path = archive / "latex" / f"{stem}.tex"
    current = tex_path.read_text(encoding="utf-8")
    original = ROOT / "data/test/image" / f"{stem}.png"
    report = read(folder / "constraint_repair.json")
    data = {"stem": stem, "baseline_tex_sha256": hashlib.sha256(tex_path.read_bytes()).hexdigest(),
            "archive_repair_applied": report["applied"], "groups": {}}
    variants = {}
    baseline_image = archive / "image" / f"{stem}.png"
    if report["applied"] or report["reason"] == "already_satisfied":
        raw = (folder / "unrepaired.tex").read_text(encoding="utf-8")
        if hashlib.sha256(raw.encode()).hexdigest() != report["input_sha256"]:
            raise ValueError(f"repair input hash mismatch for {stem}")
        after = extract_geometry(current)
        relations = report["accepted"]
        fixed = set(report["fixed_points"])
        current_engine = compile_probe(current, after["points"], tectonic)
        baseline = measures(after["points"], current_engine, after["segments"], relations)
        data["groups"]["current"] = {"relations": baseline, "mode": "archive"}
        if not report["applied"]:
            # These relations were already satisfied by the floating solver.
            # Keep them in the denominator and use the archived coordinates.
            for name in GROUPS[1:]:
                data["groups"][name] = {"relations": baseline, "mode": "already_satisfied"}
        else:
            before, after, solved = float_solution(raw, current, report)
            for decimals in (6, 9):
                literals = {n: [f"{v:.{decimals}f}" for v in xy] for n, xy in solved.items() if n not in fixed}
                points = {**after["points"], **{n: list(map(float, xy)) for n, xy in literals.items()}}
                variants[f"decimal{decimals}"] = (literals, points, None)
            # Match the engine's exact fixed anchors and the unrounded solver elsewhere.
            target = {n: np.asarray(xy) * SP_PER_CM for n, xy in solved.items()}
            target.update({n: np.asarray(current_engine[n]) for n in fixed})
            best_exact, best_extra = None, None
            for group, max_extra in (("exact_tight", .00035), ("exact_wide", .003)):
                exact, extra = exact_layout(target, fixed, after["segments"], relations, max_extra)
                if best_exact is not None and (exact is None or best_extra < extra):
                    exact, extra = best_exact, best_extra
                if exact is None:
                    data["groups"][group] = {"relations": baseline, "mode": "fallback_no_lattice_solution"}
                    continue
                best_exact, best_extra = exact, extra
                literals = {n: [pt_literal(v) for v in xy] for n, xy in exact.items()}
                points = {**after["points"], **{n: (xy / SP_PER_CM).tolist() for n, xy in exact.items()}}
                variants[group] = (literals, points, extra)
            for group, (literals, points, extra) in variants.items():
                image = out / group / "image" / f"{stem}.png"
                try:
                    validate_layout(before, after, points, report)
                    tex = write_coordinates(current, literals)
                    engine = compile_probe(tex, after["points"], tectonic, image if render else None, original)
                    rows = measures(points, engine, after["segments"], relations)
                    if extra is not None and not all(r["engine_integer_exact"] for r in rows):
                        raise ValueError("Tectonic did not preserve an exact directional relation")
                    data["groups"][group] = {"relations": rows, "mode": "candidate",
                                             "max_lattice_adjustment_cm": extra}
                    tex_out = out / group / "latex" / f"{stem}.tex"
                    tex_out.write_text(tex, encoding="utf-8")
                except (ValueError, OSError, subprocess.SubprocessError) as exc:
                    data["groups"][group] = {"relations": baseline, "mode": "fallback_guard",
                                             "reason": str(exc)}
    for group in GROUPS[1:]:
        row = data["groups"].setdefault(group, {"relations": [], "mode": "no_archived_relations"})
        if row["mode"] != "candidate":
            shutil.copyfile(tex_path, out / group / "latex" / f"{stem}.tex")
            if render:
                shutil.copyfile(baseline_image, out / group / "image" / f"{stem}.png")
    data["elapsed_s"] = perf_counter() - start
    return data


def hybrid_image(case, archive, out, tectonic, *, prior=None):
    stem = case["stem"]
    groups = case["groups"]
    decimal = groups["decimal6"]["relations"]
    candidates = ["decimal6"] + [name for name in ("exact_tight", "exact_wide")
                                 if groups[name]["mode"] == "candidate"]
    variant = max(candidates,
                  key=lambda name: rank(groups[name]["relations"]))
    best = {"mode": variant, "relations": groups[variant]["relations"],
            "max_lattice_adjustment_cm": groups[variant].get("max_lattice_adjustment_cm")}
    budgets = (.00035, .001, .003)
    destination = out / "hybrid"
    if prior is not None:
        variant = "hybrid"
        best = {**prior, "mode": "hybrid"}
        budgets = (.006, .012)
        destination = out / "extended"
    tex_out = destination / "latex" / f"{stem}.tex"
    image_out = destination / "image" / f"{stem}.png"
    start = perf_counter()
    if case["archive_repair_applied"] and rank(best["relations"])[0] < len(decimal):
        folder = archive / "stem" / stem
        report = read(folder / "constraint_repair.json")
        raw = (folder / "unrepaired.tex").read_text(encoding="utf-8")
        current = (archive / "latex" / f"{stem}.tex").read_text(encoding="utf-8")
        before, after, solved = float_solution(raw, current, report)
        relations = report["accepted"]
        fixed = set(report["fixed_points"])
        target = {n: np.asarray(xy) * SP_PER_CM for n, xy in solved.items()}
        if fixed:
            fixed_engine = compile_probe(current, fixed, tectonic)
            target.update({n: np.asarray(xy) for n, xy in fixed_engine.items()})
        selected = None
        selected_rank = rank(best["relations"])
        for budget in budgets:
            exact, extra = adaptive_layout(target, fixed, after["segments"], relations, budget)
            if exact is None:
                continue
            points = {**after["points"], **{n: (xy / SP_PER_CM).tolist() for n, xy in exact.items()}}
            rows = measures(points, exact, after["segments"], relations)
            score = rank(rows)
            if score <= selected_rank or any(
                    a["engine_error_deg"] > max(.003, b["engine_error_deg"]) + 1e-9
                    for a, b in zip(rows, decimal)):
                continue
            if prior is not None and score[0] == selected_rank[0]:
                continue
            try:
                validate_layout(before, after, points, report)
            except ValueError:
                continue
            selected = exact, extra, points
            selected_rank = score
            if score[0] == len(rows):
                break
        if selected is not None:
            exact, extra, points = selected
            tex = write_coordinates(current, {n: [pt_literal(v) for v in xy] for n, xy in exact.items()})
            try:
                engine = compile_probe(tex, after["points"], tectonic, image_out,
                                       ROOT / "data/test/image" / f"{stem}.png")
                if any(tuple(xy) != engine[name] for name, xy in exact.items()):
                    raise ValueError("compiled coordinates differ from integer layout")
                rows = measures(points, engine, after["segments"], relations)
                tex_out.write_text(tex, encoding="utf-8")
                return {"stem": stem, "mode": "adaptive", "relations": rows,
                        "max_lattice_adjustment_cm": extra, "elapsed_s": perf_counter() - start}
            except (ValueError, OSError, subprocess.SubprocessError) as exc:
                best["adaptive_fallback"] = str(exc)
    shutil.copyfile(out / variant / "latex" / f"{stem}.tex", tex_out)
    shutil.copyfile(out / variant / "image" / f"{stem}.png", image_out)
    best.update(stem=stem, elapsed_s=perf_counter() - start)
    return best


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--archive", type=Path, default=ROOT / "outputs/ours")
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--stems", nargs="+")
    parser.add_argument("--no-render", action="store_true")
    parser.add_argument("--hybrid", action="store_true", help="refine a completed rendered experiment")
    parser.add_argument("--extended", action="store_true", help="test a wider movement budget after hybrid")
    args = parser.parse_args()
    out = args.out.resolve()
    archive = args.archive.resolve()
    if out == archive or archive in out.parents:
        parser.error("choose an experiment directory outside the archive")
    manifest = ROOT / "data/test/geometry_reference/manifest.json"
    tectonic = load_settings().paths.tectonic
    if args.hybrid or args.extended:
        if args.hybrid and args.extended:
            parser.error("run --hybrid before --extended")
        name = "extended" if args.extended else "hybrid"
        for kind in ("image", "latex"):
            (out / name / kind).mkdir(parents=True, exist_ok=True)
        cases = read(out / "audit.json")["cases"]
        prior = {row["stem"]: row for row in read(out / "hybrid.json")} if args.extended else {}
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            rows = list(pool.map(lambda case: hybrid_image(case, archive, out, tectonic,
                                                           prior=prior.get(case["stem"])), cases))
        save(out / f"{name}.json", rows)
        return
    stems = sorted(args.stems or read(manifest)["files"])
    for name in GROUPS[1:]:
        for kind in ("image", "latex"):
            (out / name / kind).mkdir(parents=True, exist_ok=True)
    def run(stem):
        result = one_image(stem, archive, out, tectonic, not args.no_render)
        save(out / "cases" / f"{stem}.json", result)
        return result

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        rows = []
        for row in pool.map(run, stems):
            rows.append(row)
            if len(rows) % 10 == 0 or len(rows) == len(stems):
                print(f"Completed {len(rows)}/{len(stems)} images", flush=True)
    save(out / "audit.json", {"reference_manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
                              "cases": rows})


if __name__ == "__main__":
    main()
