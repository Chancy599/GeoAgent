"""Read back reference label anchors from TeX; never infer truth from predictions."""
from concurrent.futures import ThreadPoolExecutor
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from geoagent.config import load_settings


def check(stem, settings):
    source=ROOT/'data/test/latex'/f'{stem}.tex'
    data=json.loads((ROOT/'data/test/geometry_reference'/f'{stem}.json').read_text(encoding='utf-8'))
    text=source.read_text(encoding='utf-8');requested={};expected={};probe=[]
    for index,(label,binding) in enumerate(data['points'].items()):
        expr=next((x for x in binding.get('expressions',[]) if x),None)
        if expr is None:
            expr=next(iter(binding.get('coordinate_aliases',[])),None)
        if expr is None:continue
        requested[str(index)]=label
        expected[label]=binding.get('source_xy',binding['xy'])
        name=f'georeference{index}'
        probe.append(rf'\path ({expr}) coordinate ({name});')
        probe.append(rf'\pgfpointanchor{{{name}}}{{center}}\pgfgetlastxy{{\geox}}{{\geoy}}\typeout{{GEOREF:{index}:\geox:\geoy}}')
    instrumented=text.replace(r'\end{tikzpicture}','\n'+'\n'.join(probe)+'\n'+r'\end{tikzpicture}',1)
    folder=ROOT/'.cache/reference_coordinate_probes'/stem;folder.mkdir(parents=True,exist_ok=True)
    digest=hashlib.sha256(instrumented.encode()).hexdigest()
    cache=folder/'result.json'
    if cache.exists():
        old=json.loads(cache.read_text(encoding='utf-8'))
        if old.get('probe_sha256')==digest:return old
    work=Path(tempfile.mkdtemp(prefix='geo_reference_probe_')).resolve()
    try:
        (work/'figure.tex').write_text(instrumented,encoding='utf-8')
        proc=subprocess.run([str(settings.paths.tectonic),'--keep-logs','--untrusted','figure.tex'],cwd=work,
                            capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=120)
        log=(work/'figure.log').read_text(encoding='utf-8',errors='replace') if (work/'figure.log').exists() else ''
        (folder/'execution.log').write_text(log+'\n'+proc.stdout+'\n'+proc.stderr,encoding='utf-8')
        actual={requested[i]:[float(x),float(y)] for i,x,y in re.findall(r'GEOREF:(\d+):\s*([-+\d.]+)pt:\s*([-+\d.]+)pt',log)}
        result={'stem':stem,'probe_sha256':digest,'source_sha256':data['source_sha256'],
                'compiled':proc.returncode==0,'requested':len(requested),'measured':len(actual),
                'actual_anchor_pt':actual,'source_anchor_xy':expected,
                'reviewed_corrections':data['audit'].get('reviewed_reference_corrections',[])}
        if proc.returncode or set(actual)!=set(expected):
            result.update(status='compile_or_probe_failed',error=(proc.stderr+log[-2000:])[-2500:])
        else:
            names=sorted(actual);a=np.array([expected[n] for n in names]);b=np.array([actual[n] for n in names])
            ac,bc=a-a.mean(0),b-b.mean(0)
            scale=float((ac*bc).sum()/(ac*ac).sum());shift=b.mean(0)-scale*a.mean(0)
            residual=np.linalg.norm(scale*a+shift-b,axis=1);span=float(np.linalg.norm(np.ptp(b,axis=0)))
            relative=float(residual.max()/span)
            result.update(status='consistent' if relative<2e-5 and scale>0 else 'coordinate_mismatch',
                          scale=scale,shift=shift.tolist(),max_relative_residual=relative,
                          residual_pt={n:float(v) for n,v in zip(names,residual)})
    except Exception as exc:
        result={'stem':stem,'probe_sha256':digest,'status':'probe_error','error':str(exc)}
    finally:
        assert work.parent==Path(tempfile.gettempdir()).resolve() and work.name.startswith('geo_reference_probe_')
        shutil.rmtree(work)
    cache.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return result


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--workers',type=int,default=20)
    ap.add_argument('--stems',nargs='+')
    args=ap.parse_args()
    audit=json.loads((ROOT/'results/latest/reference_quality_audit.json').read_text(encoding='utf-8'))
    stems=args.stems or list(audit['cases'])
    settings=load_settings()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        rows=list(pool.map(lambda s:check(s,settings),stems))
    from PIL import Image
    for row in rows:
        if 'max_relative_residual' not in row:continue
        with Image.open(ROOT/'data/test/image'/f"{row['stem']}.png") as im:width,height=im.size
        row['equivalent_source_pixel_residual']=row['max_relative_residual']*float(np.hypot(width,height))
        if row['status']=='coordinate_mismatch' and row['equivalent_source_pixel_residual']<.25:
            row['status']='subpixel_execution_difference'
    result={'schema':'reference-tex-execution.v1','count':len(rows),'workers':args.workers,
            'consistent':sum(r['status']=='consistent' for r in rows),'subpixel_differences':sum(r['status']=='subpixel_execution_difference' for r in rows),'cases':{r['stem']:r for r in rows},
            'scope':'Compare raw source anchors before reviewed corrections. This checks parsing, not diagram intent. References and predictions unchanged.'}
    (ROOT/'results/latest/reference_execution_audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'count':len(rows),'consistent':result['consistent'],'subpixel_differences':result['subpixel_differences'],
                      'problems':[{k:r.get(k) for k in ['stem','status','max_relative_residual','error']} for r in rows if r['status'] not in ('consistent','subpixel_execution_difference')]},ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
