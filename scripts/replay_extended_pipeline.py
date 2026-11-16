"""Replay the production repair on archived Code Agent outputs."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import shutil
import sys
from tempfile import TemporaryDirectory
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from geoagent.config import load_settings
from geoagent.state.exact_layout import measures
from geoagent.state.repair_pipeline import read_compiled_points, repair_generated_tikz
from geoagent.state.tikz_geometry import extract_geometry
from geoagent.state.topology import check_topology
from geoagent.tools import compile_tikz, frame_like_original, render_pdf


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def replay(stem, archive, out, settings):
    folder = archive / "stem" / stem
    source = folder / "unrepaired.tex"
    raw = source.read_text(encoding="utf-8")
    expected = read(folder / "constraint_repair.json")
    if hashlib.sha256(raw.encode()).hexdigest() != expected["input_sha256"]:
        raise ValueError(f"repair input changed for {stem}")
    contract = read(folder / "coordinate_contract.json").get("coordinates")
    plan = read(folder / "state.json")["meta"].get("topology_plan")
    original = settings.paths.image_dir / f"{stem}.png"
    baseline_tex = archive / "latex" / f"{stem}.tex"
    baseline_png = archive / "image" / f"{stem}.png"
    tex_path = out / "latex" / f"{stem}.tex"
    png_path = out / "image" / f"{stem}.png"
    start = perf_counter()
    repair = repair_generated_tikz(raw, settings, source_image=original if contract else None,
                                   source_coordinates=contract, plan=plan)
    seconds = perf_counter() - start
    tex, report = repair.tex, repair.report
    baseline = baseline_tex.read_text(encoding="utf-8")
    if tex.strip() == baseline.strip():
        shutil.copyfile(baseline_tex, tex_path)
        shutil.copyfile(baseline_png, png_path)
    else:
        with TemporaryDirectory(prefix="geoagent_replay_") as directory:
            compiled = compile_tikz(tex, out_dir=directory, paths=settings.paths,
                                    timeout=settings.budget.compile_timeout_seconds)
            if not compiled["ok"]:
                raise RuntimeError(f"{stem}: {compiled['errors']}")
            if not render_pdf(compiled["pdf_path"], png_path, dpi=200)["ok"]:
                raise RuntimeError(f"{stem}: render failed")
            if not frame_like_original(png_path, original)["ok"]:
                raise RuntimeError(f"{stem}: framing failed")
        tex_path.write_text(tex, encoding="utf-8")
    rows = report.get("strict", {}).get("relations") or report.get("extended_hybrid", {}).get("relations")
    if rows is None and report.get("accepted") and (report.get("applied") or report["reason"] == "already_satisfied"):
        geometry = extract_geometry(tex)
        points = read_compiled_points(tex, geometry["points"], settings)
        rows = measures(geometry["points"], points, geometry["segments"], report["accepted"])
    return {"stem": stem, "input_sha256": sha(source), "legacy_sha256": sha(baseline_tex),
            "legacy_replayed": repair.legacy_tex.strip() == baseline.strip(),
            "program_sha256": sha(tex_path), "image_sha256": sha(png_path),
            "original_image_sha256": sha(original), "repair_s": seconds,
            "legacy_topology": check_topology(repair.legacy_tex, plan) if plan else None,
            "topology": check_topology(tex, plan) if plan else None,
            "relations": rows or [], "report": report}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--archive", type=Path, default=ROOT / "outputs/ours")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--mode", choices=("strict", "extended_hybrid", "legacy"), default="extended_hybrid")
    parser.add_argument("--stems", nargs="+")
    args = parser.parse_args()
    archive, out = args.archive.resolve(), args.out.resolve()
    if out == archive or archive in out.parents:
        parser.error("replay outputs must be separate from the input archive")
    manifest = ROOT / "data/test/geometry_reference/manifest.json"
    stems = sorted(args.stems or read(manifest)["files"])
    settings = load_settings({"post_repair_mode": args.mode, "geometry_repair": True})
    for name in ("latex", "image"):
        (out / name).mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        cases = []
        for case in pool.map(lambda stem: replay(stem, archive, out, settings), stems):
            cases.append(case)
            if len(cases) % 10 == 0 or len(cases) == len(stems):
                print(f"Replayed {len(cases)}/{len(stems)}", flush=True)
    (out / "replay.json").write_text(json.dumps({"reference_manifest_sha256": sha(manifest),
        "geometry_settings": settings.geometry.to_dict(), "cases": cases}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")


if __name__ == "__main__":
    main()
