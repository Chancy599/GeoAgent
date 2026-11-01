"""Refresh affected rows, retain all other measurements, and recompute summaries."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from geoagent.evaluation.structure import load_reference
from geoagent.evaluation.visual_metrics import ssim_pair,_cosine
from scripts.evaluate_structure_ab import _evaluate_group,_group_summary,_paired_geometry,_item_deltas,_delta_summary


def read(path):return json.loads(path.read_text(encoding='utf-8'))
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def save(path,data):path.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')


def update_geometry(path,stems,groups,workers):
    report=read(path);refs={s:load_reference(ROOT/'data/test/geometry_reference'/f'{s}.json') for s in stems}
    for name,archive in groups.items():
        programs={s:archive/'latex'/f'{s}.tex' for s in stems}
        report['groups'][name]['per_stem'].update(_evaluate_group(programs,refs,stems,workers=workers))
        report['groups'][name]['summary']=_group_summary(report['groups'][name]['per_stem'])
    rows={n:g['per_stem'] for n,g in report['groups'].items()};names=list(rows);baseline=names[0]
    report['paired_geometry']=_paired_geometry(rows,names,report['shared_stems'])
    report['item_paired']={f'{n}_minus_{baseline}':{k:_delta_summary(_item_deltas(rows,baseline,n,f)) for k,f in [('angle','angle_checks'),('ratio','ratio_checks')]} for n in names if n!=baseline}
    report['reference_manifest_sha256']=sha(ROOT/'data/test/geometry_reference/manifest.json')
    report['last_updated_stems']=stems
    save(path,report)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--generated-stems',nargs='+',required=True)
    p.add_argument('--reference-stems',nargs='+',required=True)
    p.add_argument('--workers',type=int,default=20)
    args=p.parse_args();out=ROOT/'results/latest'
    stems=sorted(set(args.generated_stems+args.reference_stems))
    update_geometry(out/'structure.json',stems,{'raw':ROOT/'outputs/ablations/no_post_repair','post':ROOT/'outputs/ours'},args.workers)
    update_geometry(out/'baselines_geometry.json',sorted(set(args.reference_stems)),{n:ROOT/'outputs/baselines'/n for n in ['haiku-5.5','gpt-5.4']},args.workers)
    visual=read(out/'visual.json');cache=ROOT/'.cache/visual_evaluation'
    fingerprints={n:hashlib.sha256(json.dumps(c,sort_keys=True).encode()).hexdigest()[:16] for n,c in visual['encoder_configs'].items()}
    for name,archive in [('raw',ROOT/'outputs/ablations/no_post_repair'),('post',ROOT/'outputs/ours')]:
        rows={r['stem']:r for r in visual['groups'][name]['per_stem']}
        for stem in args.generated_stems:
            predicted=archive/'image'/f'{stem}.png';reference=ROOT/'data/test/image'/f'{stem}.png'
            row={'stem':stem,'ssim':ssim_pair(predicted,reference)}
            for metric in ['clip','dino']:
                a=np.load(cache/metric/fingerprints[metric]/f'{sha(predicted)}.npy',allow_pickle=False)
                b=np.load(cache/metric/fingerprints[metric]/f'{sha(reference)}.npy',allow_pickle=False)
                row[metric]=float(_cosine(a[None,:],b[None,:])[0])
            rows[stem]=row
        visual['groups'][name]['per_stem']=[rows[s] for s in visual['shared_stems']]
        visual['groups'][name]['summary']={k:float(np.mean([r[k] for r in rows.values()])) for k in ['ssim','clip','dino']}
    visual['last_updated_stems']=args.generated_stems
    save(out/'visual.json',visual)
    save(out/'metric_refresh.json',{'geometry_updated_stems':stems,'baseline_geometry_updated_stems':sorted(set(args.reference_stems)),
                                  'visual_updated_stems':args.generated_stems,'reference_manifest_sha256':sha(ROOT/'data/test/geometry_reference/manifest.json')})
    print('Affected geometry and visual rows refreshed; summaries recomputed.')


if __name__=='__main__':main()
