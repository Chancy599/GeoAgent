"""Compare several e2e baselines with the three TriGeoBench visual metrics.

Each ``--group name=/path/to/image`` is scored on the shared valid subset
(intersection of stems that were compiled for every group), so SSIM / CLIP /
DINO are directly comparable.  Per-group valid-set metrics are also
reported when a group covers more images than the shared subset.

    python scripts/compare_e2e_visual.py \
        --group haiku-5.5=outputs/baselines/haiku-5.5/image \
        --group qwen3.5-plus=outputs/baselines/qwen3.5-plus/image \
        --group gpt-5.4=outputs/baselines/gpt-5.4/image \
        --ref-dir data/test/image --out outputs/metrics/e2e-compare.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from geoagent.datasets.trigeobench import normalise_stem  # noqa: E402
from geoagent.evaluation.visual_metrics import evaluate  # noqa: E402


def _ref_stems(ref_root: Path) -> set[str]:
    return {
        normalise_stem(path.stem)
        for path in ref_root.iterdir()
        if path.is_file() and path.suffix.lower() in (".png", ".jpg", ".jpeg")
    }


def _row(name: str, report: dict) -> str:
    aggregate = report["aggregate"]
    return (
        f"{name:<16} {report['count']:>4} "
        f"{aggregate['ssim'] * 100:>9.4f} {aggregate['clip'] * 100:>9.4f} "
        f"{aggregate['dino'] * 100:>9.4f}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--group", action="append", required=True, metavar="NAME=IMAGE_DIR")
    parser.add_argument("--ref-dir", default="data/test/image")
    parser.add_argument("--out", default="outputs/metrics/e2e-compare.json")
    parser.add_argument("--no-per-group", action="store_true", help="score only the shared subset")
    args = parser.parse_args()

    ref_root = Path(args.ref_dir)
    refs = _ref_stems(ref_root)
    groups: list[tuple[str, Path]] = []
    for spec in args.group:
        if "=" not in spec:
            raise SystemExit(f"bad --group {spec!r}; expected NAME=IMAGE_DIR")
        name, directory = spec.split("=", 1)
        groups.append((name, Path(directory)))

    valid = {
        name: sorted({normalise_stem(path.stem) for path in directory.glob("*.png")} & refs)
        for name, directory in groups
    }
    empty = [name for name, stems in valid.items() if not stems]
    if empty:
        raise SystemExit(f"no matching predictions for: {empty}")
    common = sorted(set.intersection(*(set(stems) for stems in valid.values())))

    print(f"shared valid set: {len(common)} / {len(refs)}")
    print(f"{'group':<16} {'N':>4} {'SSIMx100':>9} {'CLIPx100':>9} {'DINOx100':>9}")
    result: dict = {
        "schema": "e2e-visual-compare.v1",
        "ref_dir": str(ref_root),
        "shared_stems": common,
        "groups": {},
    }
    for name, directory in groups:
        shared = evaluate(directory, ref_root, stems=common)
        if args.no_per_group or set(valid[name]) == set(common):
            own = shared
        else:
            own = evaluate(directory, ref_root, stems=valid[name])
        result["groups"][name] = {
            "pred_dir": str(directory),
            "valid_count": len(valid[name]),
            "missing_vs_ref": len(refs) - len(valid[name]),
            "shared": shared,
            "valid": own,
        }
        print(_row(name, shared))

    if not args.no_per_group:
        print("\nper-group valid set (not mutually comparable):")
        print(f"{'group':<16} {'N':>4} {'SSIMx100':>9} {'CLIPx100':>9} {'DINOx100':>9}")
        for name, _ in groups:
            print(_row(name, result["groups"][name]["valid"]))

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nreport: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
