"""Extract immutable labelled angles/ratios from reference TikZ only."""
from concurrent.futures import ThreadPoolExecutor
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from geoagent.evaluation.structure import backend, freeze_reference, PROTOCOL


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--latex-dir', type=Path, default=ROOT/'data/test/latex')
    p.add_argument('--out', type=Path, default=ROOT/'data/test/geometry_reference')
    p.add_argument('--workers', type=int, default=20)
    p.add_argument('--corrections', type=Path, default=ROOT/'data/test/geometry_reference/corrections.json')
    args = p.parse_args()
    if args.workers < 1:
        p.error('--workers must be positive')
    paths = sorted(args.latex_dir.glob('*.tex'))
    if not paths:
        raise ValueError('No reference programs')
    backend()
    corrections = json.loads(args.corrections.read_text(encoding='utf-8'))['cases'] if args.corrections.exists() else {}
    # Build everything successfully before publishing a new manifest.
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        records = list(pool.map(lambda path: freeze_reference(path, corrections), paths))
    args.out.mkdir(parents=True, exist_ok=True)
    hashes = {}
    for row in records:
        text = json.dumps(row, ensure_ascii=False, indent=2)
        target = args.out/f"{row['stem']}.json"
        target.write_text(text, encoding='utf-8')
        hashes[row['stem']] = hashlib.sha256(target.read_bytes()).hexdigest()
    manifest = {'schema': PROTOCOL, 'count': len(records), 'workers': args.workers,
                'implementation_sha256': records[0]['implementation_sha256'], 'files': hashes,
                'angles': sum(len(r['angles']) for r in records),
                'ratios': sum(len(r['ratios']) for r in records),
                'edges': sum(len(r['edges']) for r in records),
                'source_hashes': {r['stem']: r['source_sha256'] for r in records}}
    manifest['reviewed_corrections'] = {r['stem']: r['audit']['reviewed_reference_corrections'] for r in records if r['audit'].get('reviewed_reference_corrections')}
    (args.out/'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k: v for k, v in manifest.items() if k not in ('files', 'source_hashes')}, indent=2))


if __name__ == '__main__':
    main()
