"""CLI: score a directory of rendered figures with the TriGeoBench visual metrics.

    python scripts/evaluate_visual.py --pred-dir outputs/ablations/no_post_repair/image --out outputs/metrics/ab100_none.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from geoagent.evaluation.visual_metrics import evaluate  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="TriGeoBench SSIM / CLIP / DINO")
    parser.add_argument("--pred-dir", default="outputs/ablations/no_post_repair/image", help="rendered PNGs named <stem>.png")
    parser.add_argument("--ref-dir", default="data/test/image", help="reference dataset images")
    parser.add_argument("--out", default="outputs/metrics/ab100_none.json", help="JSON report path")
    parser.add_argument("--limit", type=int, default=None, help="evaluate only the first N stems")
    args = parser.parse_args(argv)

    report = evaluate(args.pred_dir, args.ref_dir, limit=args.limit)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    agg = report["aggregate"]
    print(f"images: {report['count']} (missing: {len(report['missing'])})")
    print(f"SSIM x10^2 : {agg['ssim'] * 100:.2f}")
    print(f"CLIP x10^2 : {agg['clip'] * 100:.2f}")
    print(f"DINO x10^2 : {agg['dino'] * 100:.2f}")
    print(f"report: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
