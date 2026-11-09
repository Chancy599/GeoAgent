"""Quantize the same selected 100 programs, repair copies and publish both groups.

No model or reference geometry is used. Rendering is refreshed for consistency;
visual metrics are explicitly retained as measurements of the previous renders.
"""
from concurrent.futures import ThreadPoolExecutor
from collections import Counter
import hashlib
import json
from pathlib import Path
import shutil
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from geoagent.config import load_settings
from geoagent.state.coordinate_precision import quantize_tex
from geoagent.state.tikz_repair import repair_tikz_constraints
from geoagent.tools import compile_tikz, render_pdf, frame_like_original


def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def read(path): return json.loads(path.read_text(encoding='utf-8'))
def save(path,data): path.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')


def main():
    workers=20
    cache=ROOT/'.cache/three_decimal';cache.mkdir(parents=True,exist_ok=True)
    out=ROOT/'results/latest'
    archives={'raw':ROOT/'outputs/ablations/no_post_repair','post':ROOT/'outputs/ours'}
    originals={p.stem:p.read_text(encoding='utf-8') for p in sorted((archives['raw']/'latex').glob('*.tex'))}
    assert len(originals)==100
    protected=read(out/'protected_inputs.json')
    assert all(sha(ROOT/n)==digest for n,digest in protected.items()), 'Inputs changed before quantization'
    snapshot=cache/'before'; snapshot.mkdir(exist_ok=True)
    for name in ['structure.json','summary.json','repair_manifest.json','comparison.json','visual.json','protected_inputs.json','engine_verification.json','regeneration.json']:
        if (out/name).exists():shutil.copyfile(out/name,snapshot/name)
    settings=load_settings();g=settings.geometry
    def process(item):
        stem,source=item
        raw=quantize_tex(source)
        post,report=repair_tikz_constraints(raw, angle_tol_deg=g.angle_tol_deg,
            max_shift_rel=g.post_max_shift_rel,max_length_change_rel=g.post_max_length_change_rel,
            topology_tol_rel=g.post_topology_tol_rel,incidence_mode=g.post_incidence_mode,
            length_weight=g.post_length_weight,length_scope=g.post_length_scope,curve_policy=g.post_curve_policy,
            incidence_strength=g.post_incidence_strength,relation_types=tuple(g.post_relation_types),
            relaxation=g.post_relaxation,curve_options=g.post_curve_options)
        assert post==quantize_tex(post),stem
        assert report['ok'], (stem,report)
        for name,tex in [('raw',raw),('post',post)]:
            folder=cache/name/stem;folder.mkdir(parents=True,exist_ok=True)
            if name=='raw':(folder/'pre_quantization.tex').write_text(source,encoding='utf-8')
            compiled=compile_tikz(tex,out_dir=folder,stem='best',paths=settings.paths)
            assert compiled['ok'],(stem,name,compiled.get('errors'))
            rendered=render_pdf(folder/'best.pdf',folder/'best.png',dpi=200)
            assert rendered['ok'],(stem,name,rendered)
            frame_like_original(folder/'best.png',ROOT/'data/test/image'/f'{stem}.png')
            (folder/'unrepaired.tex').write_text(raw,encoding='utf-8')
            record=report if name=='post' else {'enabled':False,'applied':False,'reason':'no_post_repair','coordinate_decimals':3}
            save(folder/'constraint_repair.json',record)
        report.update(stem=stem,compiled=True)
        return report
    reports=[]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for i,report in enumerate(pool.map(process,originals.items()),1):
            reports.append(report)
            if i%10==0:print(f'Rounded, repaired and compiled {i}/100 pairs',flush=True)
    # Publish only after all 200 programs compile successfully.
    for name,archive in archives.items():
        for stem in originals:
            folder=cache/name/stem;target=archive/'stem'/stem
            for file in ['best.tex','best.pdf','best.png','unrepaired.tex','constraint_repair.json']:
                shutil.copyfile(folder/file,target/file)
            shutil.copyfile(folder/'best.tex',archive/'latex'/f'{stem}.tex')
            shutil.copyfile(folder/'best.png',archive/'image'/f'{stem}.png')
    old_visual=read(out/'visual.json')
    old_visual['stale_for_current_geometry']=True
    old_visual['evaluated_image_sha256']={name:{stem:protected[(archive/'image'/f'{stem}.png').relative_to(ROOT).as_posix()] for stem in originals} for name,archive in archives.items()}
    old_visual['retention_reason']='Visual metrics are from pre-three-decimal renders; only geometry was reevaluated.'
    save(out/'visual.json',old_visual)
    # Original data, baselines and case studies must remain byte-identical.
    for path,digest in list(protected.items()):
        if path.startswith(('outputs/ours/','outputs/ablations/no_post_repair/')):
            protected[path]=sha(ROOT/path)
        else: assert sha(ROOT/path)==digest,path
    save(out/'protected_inputs.json',protected)
    save(out/'repair_manifest.json',{'reports':reports,'reference_used_for_repair':False,'coordinate_decimals':3})
    summary=read(out/'summary.json')
    summary.update(workers=workers,coordinate_decimals=3,applied_images=sum(r['applied'] for r in reports),
        repair_settings=g.to_dict(),reasons=dict(Counter(r['reason'] for r in reports)),
        accepted_relations=sum(len(r['accepted']) for r in reports if r['applied']),compiled={'raw':100,'post':100},
        engine_verified_images=0,engine_errors=[],max_engine_error_deg=None)
    save(out/'summary.json',summary)
    save(out/'three_decimal_refresh.json',{'workers':workers,'count':100,'coordinate_decimals':3,
        'reference_used_for_repair':False,'model_calls':0,'compiled':{'raw':100,'post':100},
        'visual_metrics_retested':False,'source':'same selected unrepaired TikZ; normalized before repair',
        'source_sha256':{s:hashlib.sha256(t.encode()).hexdigest() for s,t in originals.items()},
        'output_sha256':{n:{s:sha(a/'latex'/f'{s}.tex') for s in originals} for n,a in archives.items()}})
    print('Published 100 three-decimal pairs; ready for geometry evaluation.',flush=True)


if __name__=='__main__':main()
