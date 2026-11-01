"""Evaluate frozen labelled reference items against generated TikZ by label.

Reads reference JSON only. Every manifest image is retained, even when a
prediction is missing or unparseable. Missing items have no numeric error;
coverage uses the full fixed reference denominator. Paired errors use common
available items, averaged per image then across images.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from geoagent.evaluation.structure import CORE_POLICY, PROTOCOL, backend, prediction, score, load_reference
import hashlib

def _mean_of(values: list) -> float | None:
    values = [float(v) for v in values if v is not None]
    return float(np.mean(values)) if values else None


def _archive_programs(root: Path) -> dict[str, Path]:
    return {path.stem: path for path in sorted((root / "latex").glob("*.tex"))}


def _evaluate_group(programs: dict[str, Path], references: dict[str, tuple], shared: list[str],
                    *, workers=20) -> dict[str, dict]:
    rows: dict[str, dict] = {}
    def evaluate(stem):
        gt, items = references[stem]
        try:
            tex = programs[stem]
            pred = prediction(tex)
            result = score(gt, pred, items)
        except Exception as exc:  # noqa: BLE001 - experiment harness
            return stem, {
                "compiled": False,
                "error": f"{type(exc).__name__}: {exc}",
                "angle_mae": None,
                "angle_available": 0,
                "angle_reference": len(items["angles"]),
                "ratio_mre": None,
                "ratio_available": 0,
                "ratio_reference": len(items["ratios"]),
                "coverage": 0. if items['edges'] else None,
                "matched": 0,
                "angle_checks": [dict(i, error=None, available=False, unavailable_reasons=['program_missing_or_unparseable']) for i in items['angles']],
                "ratio_checks": [dict(i, error=None, available=False, unavailable_reasons=['program_missing_or_unparseable']) for i in items['ratios']],
            }
        angle = result["angle"]
        ratio = result["length_ratio"]
        return stem, {
            "compiled": True,
            "error": None,
            "angle_mae": angle["mean"],
            "angle_available": angle["n_available"],
            "angle_reference": angle["n_reference"],
            "ratio_mre": ratio["mean"],
            "ratio_available": ratio["n_available"],
            "ratio_reference": ratio["n_reference"],
            "coverage": result["line_coverage"],
            "matched": result["alignment"].get("matched"),
            "angle_checks": result["angle_checks"],
            "ratio_checks": result["ratio_checks"],
            "extraction": pred.extraction_audit,
            "reference_extraction": gt.extraction_audit,
            "missing_labels": result['missing_labels'],
            "missing_edges": result['missing_edges'],
            "program_sha256": hashlib.sha256(tex.read_bytes()).hexdigest(),
        }
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return dict(pool.map(evaluate, shared))


def _group_summary(per_stem: dict[str, dict]) -> dict:
    compiled = {stem: row for stem, row in per_stem.items() if row["compiled"]}
    return {
        "n_images": len(compiled),
        "n_unparseable": len(per_stem) - len(compiled),
        "coverage": _mean_of([row["coverage"] for row in per_stem.values()]),
        "angle_mae_deg": _mean_of([row["angle_mae"] for row in compiled.values()]),
        "angle_images": sum(row["angle_mae"] is not None for row in compiled.values()),
        "ratio_mre": _mean_of([row["ratio_mre"] for row in compiled.values()]),
        "ratio_images": sum(row["ratio_mre"] is not None for row in compiled.values()),
        "angle_items": sum(row["angle_available"] for row in compiled.values()),
        "ratio_items": sum(row["ratio_available"] for row in compiled.values()),
        "angle_reference": sum(row["angle_reference"] for row in per_stem.values()),
        "ratio_reference": sum(row["ratio_reference"] for row in per_stem.values()),
        "angle_coverage": sum(r['angle_available'] for r in per_stem.values()) / max(1, sum(r['angle_reference'] for r in per_stem.values())),
        "ratio_coverage": sum(r['ratio_available'] for r in per_stem.values()) / max(1, sum(r['ratio_reference'] for r in per_stem.values())),
    }


def _paired_geometry(per_group: dict[str, dict[str, dict]], names: list[str], shared: list[str]) -> dict:
    """geom2code ``paired_geometry``: common items only, image mean then image average."""
    result: dict[str, dict] = {}
    for key, label in (("angle_checks", "angle"), ("ratio_checks", "ratio")):
        totals: dict[str, list[float]] = {name: [] for name in names}
        item_count = 0
        for stem in shared:
            if any(not per_group[name][stem]["compiled"] for name in names):
                continue
            groups = [per_group[name][stem][key] for name in names]
            assert len({len(group) for group in groups}) == 1
            common = []
            for items in zip(*groups):
                assert all(item["target"] == items[0]["target"] for item in items)
                if all(item["error"] is not None for item in items):
                    common.append([item["error"] for item in items])
            if common:
                item_count += len(common)
                for i, name in enumerate(names):
                    totals[name].append(float(np.mean([row[i] for row in common])))
        result[label] = {
            "n_images": len(next(iter(totals.values()))),
            "n_items": item_count,
            "means": {name: _mean_of(values) for name, values in totals.items()},
        }
    return result


def _item_deltas(per_group: dict[str, dict[str, dict]], baseline: str, other: str, key: str) -> list[float]:
    deltas: list[float] = []
    for stem, base in per_group[baseline].items():
        peer = per_group[other].get(stem)
        if peer is None or not base["compiled"] or not peer["compiled"]:
            continue
        if len(base[key]) != len(peer[key]):
            continue
        for item, match in zip(base[key], peer[key]):
            if item["error"] is None or match["error"] is None:
                continue
            deltas.append(match["error"] - item["error"])
    return deltas


def _delta_summary(deltas: list[float]) -> dict | None:
    if not deltas:
        return None
    return {
        "n": len(deltas),
        "mean": float(np.mean(deltas)),
        "median": float(np.median(deltas)),
        "improved": int(sum(d < -1e-9 for d in deltas)),
        "worse": int(sum(d > 1e-9 for d in deltas)),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--group", action="append", required=True, metavar="NAME=ARCHIVE_DIR")
    parser.add_argument("--baseline", help="group name used as the paired baseline (default: first)")
    parser.add_argument("--reference-dir", type=Path, default=ROOT/'data/test/geometry_reference')
    parser.add_argument("--out", default="results/latest/structure.json")
    parser.add_argument("--workers", type=int, default=20)
    args = parser.parse_args()
    if args.workers < 1:
        parser.error("--workers must be positive")
    backend()  # Resolve the dependency before starting worker threads.

    specs: list[tuple[str, Path]] = []
    for spec in args.group:
        if "=" not in spec:
            raise SystemExit(f"bad --group {spec!r}; expected NAME=ARCHIVE_DIR")
        name, directory = spec.split("=", 1)
        specs.append((name, Path(directory)))
    baseline = args.baseline or specs[0][0]
    names = [name for name, _ in specs]
    if len(set(names)) != len(names):
        parser.error('group names must be unique')
    if baseline not in names:
        raise SystemExit(f"--baseline {baseline!r} is not one of {names}")

    programs = {name: _archive_programs(directory) for name, directory in specs}
    manifest = json.loads((args.reference_dir/'manifest.json').read_text(encoding='utf-8'))
    if manifest['schema'] != PROTOCOL:
        raise ValueError('Incorrect reference manifest')
    shared = sorted(manifest['files'])
    missing = {name: sorted(set(shared) - set(found)) for name, found in programs.items()}
    print(f"shared generated programs: {len(shared)}")
    for name, found in programs.items():
        print(f"  {name:<12s} programs={len(found):3d}")

    references: dict[str, tuple] = {}
    for stem in shared:
        path = args.reference_dir/f'{stem}.json'
        if hashlib.sha256(path.read_bytes()).hexdigest() != manifest['files'][stem]:
            raise ValueError(f'Reference cache changed: {stem}')
        references[stem] = load_reference(path)

    per_group: dict[str, dict[str, dict]] = {}
    for name, _directory in specs:
        rows = _evaluate_group(programs[name], references, shared, workers=args.workers)
        per_group[name] = rows
        bad = [stem for stem, row in rows.items() if not row["compiled"]]
        print(f"[{name}] evaluated {len(rows)} programs, unparseable {len(bad)}")
        for stem in bad[:5]:
            print(f"  ! {stem}: {rows[stem]['error']}")
        if len(bad) > 5:
            print(f"  ... {len(bad) - 5} more")

    print("\nper-image conditional means (generated TikZ; conditional on >=1 available item):")
    summaries = {name: _group_summary(rows) for name, rows in per_group.items()}
    print(f"{'group':<12} {'N':>4} {'bad':>4} {'coverage':>9} {'angle_MAE':>10} {'imgs':>5} {'ratio_MRE':>11} {'imgs':>5}")
    for name in names:
        s = summaries[name]
        print(
            f"{name:<12} {s['n_images']:>4} {s['n_unparseable']:>4} {s['coverage']:>9.3f} "
            f"{s['angle_mae_deg']:>9.4f}° {s['angle_images']:>5} "
            f"{100 * s['ratio_mre']:>10.4f}% {s['ratio_images']:>5}"
        )

    paired = _paired_geometry(per_group, names, shared)
    print("\npaired (common items available in every group; image mean then image average):")
    for key, label in (("angle", "angle MAE (deg)"), ("ratio", "ratio MRE (pp)")):
        entry = paired[key]
        scale = 1.0 if key == "angle" else 100.0
        means = " ".join(f"{name}={scale * value:.4f}" for name, value in entry["means"].items())
        print(f"  {label:<18s} images={entry['n_images']:3d} items={entry['n_items']:5d} {means}")

    item_paired: dict[str, dict] = {}
    for name in names:
        if name == baseline:
            continue
        entry = {
            "angle": _delta_summary(_item_deltas(per_group, baseline, name, "angle_checks")),
            "ratio": _delta_summary(_item_deltas(per_group, baseline, name, "ratio_checks")),
        }
        item_paired[f"{name}_minus_{baseline}"] = entry
        print(f"\nitem-level {name} - {baseline} (same reference item, both available):")
        for key, label, scale in (("angle", "angle (deg)", 1.0), ("ratio", "ratio (pp)", 100.0)):
            d = entry[key]
            if d:
                print(
                    f"  {label:<14s} n={d['n']:5d} mean={scale * d['mean']:+.4f} "
                    f"median={scale * d['median']:+.4f} improved={d['improved']:4d} worse={d['worse']:4d}"
                )

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    result = {
        "schema": PROTOCOL,
        "geometry_protocol": PROTOCOL,
        "protocol_details": CORE_POLICY,
        "workers": args.workers,
        "prediction_source": "generated_tikz",
        "reference_source": "frozen_labelled_reference_json",
        "reference_dir": str(args.reference_dir),
        "reference_manifest_sha256": hashlib.sha256((args.reference_dir/'manifest.json').read_bytes()).hexdigest(),
        "shared_stems": shared,
        "groups": {
            name: {
                "archive_dir": str(dict(specs)[name]),
                "program_count": len(programs[name]),
                "missing_programs": missing[name],
                "summary": summaries[name],
                "per_stem": per_group[name],
            }
            for name in names
        },
        "paired_geometry": paired,
        "item_paired": item_paired,
    }
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
