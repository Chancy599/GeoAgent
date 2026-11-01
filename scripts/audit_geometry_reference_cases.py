"""Inspect explicit visible-label bindings and per-item failures."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from geoagent.evaluation.structure import PROTOCOL, load_reference, prediction, score


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--stems', nargs='+', default=['6986_q_fig1', '403_q_fig1'])
    ap.add_argument('--out', type=Path, default=ROOT/'results/latest/regressions')
    args = ap.parse_args()
    records = {}
    for stem in args.stems:
        gt, items = load_reference(ROOT/'data/test/geometry_reference'/f'{stem}.json')
        pred = prediction(ROOT/'outputs/ours/latex'/f'{stem}.tex')
        result = score(gt, pred, items)
        records[stem] = {'reference_bindings': gt.bindings, 'prediction_bindings': pred.bindings,
                         'reference_audit': gt.extraction_audit, 'prediction_audit': pred.extraction_audit,
                         'score': result}
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out/'item_audit.json').write_text(json.dumps({'protocol': PROTOCOL, 'cases': records}, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'Label binding audit: {len(records)} cases')


if __name__ == '__main__':
    main()
