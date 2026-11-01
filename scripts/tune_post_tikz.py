"""Source-only parameter sweep over a frozen generated batch; GT for scoring only."""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import shutil
import sys

import numpy as np
from threadpoolctl import threadpool_limits

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

from geoagent.config import load_settings
from geoagent.datasets import scan_dataset
from geoagent.state.tikz_repair import repair_tikz_constraints
from scripts.compare_post_tikz import save,sha
from geoagent.evaluation.structure import (PROTOCOL, source_geometry,
                                          prediction as graph_prediction, score)


def variants():
    result={"current":None}
    for tol in (.0005,.001,.002,.003,.005):
        for mode in ("preserve","snap"):
            result[f"top_{tol}_{mode}"]={"topology_tol_rel":tol,"incidence_mode":mode}
    for mode in ("preserve","snap"):
        for scope in ("edges","all_pairs"):
            for weight in (.01,.1,1):
                result[f"len_{mode}_{scope}_{weight}"]={"topology_tol_rel":.002,"incidence_mode":mode,
                    "length_scope":scope,"length_weight":weight}
    for angle in (.25,.75,1,1.5):
        for weight in (0,1):
            for mode in ("preserve","snap"):
                result[f"angle_{angle}_w{weight}_{mode}"]={"angle_tol_deg":angle,"topology_tol_rel":.002,
                    "length_weight":weight,"length_scope":"all_pairs","incidence_mode":mode}
    for weight in (0,.1,1):
        result[f"curve_freeze_w{weight}"]={"curve_policy":"freeze","topology_tol_rel":.002,
            "length_weight":weight,"length_scope":"all_pairs"}
    result["curve_freeze_snap"]={"curve_policy":"freeze","topology_tol_rel":.002,
        "length_weight":.1,"length_scope":"all_pairs","incidence_mode":"snap"}
    for guard in (.0025,.005,.02):
        result[f"guard_{guard}"]={"topology_tol_rel":.002,"length_weight":.1,"length_scope":"all_pairs",
            "max_length_change_rel":guard}
    defaults={"angle_tol_deg":.5,"max_shift_rel":.005,"max_length_change_rel":.01,
        "topology_tol_rel":.0005,"incidence_mode":"preserve","length_weight":0.0,
        "length_scope":"edges","curve_policy":"defer"}
    return {name:(None if params is None else defaults|params) for name,params in result.items()}


def prediction(path):
    return graph_prediction(path)


def compact(result):
    return {"angle":[i["error"] for i in result["angle_checks"]],
            "ratio":[i["error"] for i in result["ratio_checks"]],"coverage":result["line_coverage"]}


def metrics(baseline, rows, stems):
    result={"coverage":0,"lost_angle":0,"lost_ratio":0,"per_image":{}}
    for metric in ("angle","ratio"):
        values=[];original=[];improved=worse=same=0
        for stem in stems:
            a=baseline[stem];b=rows[stem]
            if a is None or b is None:continue
            pairs=[(x,y) for x,y in zip(a[metric],b[metric]) if x is not None]
            if not pairs:continue
            lost=sum(y is None for x,y in pairs)
            result[f"lost_{metric}"]+=lost
            # Missing predictions receive NO improvement credit. Report and
            # constrain availability separately; do not zero-impute errors.
            x=float(np.mean([x for x,y in pairs]));y=float(np.mean([x if y is None else y for x,y in pairs]))
            original.append(x);values.append(y)
            delta=y-x
            improved+=delta < -1e-9;worse+=delta > 1e-9;same+=abs(delta)<=1e-9
            result["per_image"].setdefault(stem,{})[metric]={"before":x,"after":y,"delta":delta,"lost":lost}
        result[metric]={"n_images":len(values),"before":float(np.mean(original)),"after":float(np.mean(values)),
            "improved":int(improved),"worse":int(worse),"same":int(same)}
    valid=[s for s in stems if baseline[s] is not None and rows[s] is not None]
    result["n_parseable_images"]=len(valid)
    result["coverage"]=float(np.mean([rows[s]["coverage"] for s in valid]))
    result["baseline_coverage"]=float(np.mean([baseline[s]["coverage"] for s in valid]))
    result["joint_relative_error"]=sum(result[k]["after"]/result[k]["before"] for k in ("angle","ratio"))/2
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source",type=Path,default=ROOT/"outputs/ablations/no_post_repair")
    p.add_argument("--out",type=Path,default=ROOT/"outputs/geometry_experiments")
    p.add_argument("--workers",type=int,default=20)
    p.add_argument("--spec",type=Path)
    p.add_argument("--current-programs",type=Path,default=ROOT/"outputs/ours")
    p.add_argument("--selection-scope",choices=("development","all"),default="development")
    args=p.parse_args();out=args.out.resolve();source=args.source.resolve()
    settings=load_settings();items={i.stem:i for i in scan_dataset(settings.paths.image_dir,settings.paths.latex_dir)}
    paths=sorted((source/"latex").glob("*.tex"));stems=[p.stem for p in paths]
    assert len(stems)==100
    split=sorted(stems,key=lambda s:hashlib.sha256(("repair-tuning-20261101:"+s).encode()).hexdigest())
    dev=sorted(split[:70]);validation=sorted(split[70:])
    specs=json.loads(args.spec.read_text(encoding="utf-8")) if args.spec else variants()
    save(out/"protocol.json",{"geometry_protocol":PROTOCOL,"source_hashes":{p.stem:sha(p) for p in paths},"variants":specs,
        "development":dev,"validation":validation,"workers":args.workers,
        "selection":f"{args.selection_scope}: prefer no lost baseline items and both errors reduced; minimize mean normalized MAE/MRE.",
        "limitation":"Internal split of a previously inspected/tuned dataset; not independent generalization evidence."})
    all_reports={}
    with threadpool_limits(limits=1),ThreadPoolExecutor(max_workers=args.workers) as pool:
        for index,(name,kwargs) in enumerate(specs.items(),1):
            folder=out/"variants"/name/"latex";folder.mkdir(parents=True,exist_ok=True)
            def repair(path):
                target=folder/path.name
                if kwargs is None:
                    current=args.current_programs/"latex"/path.name
                    shutil.copyfile(current,target)
                    report=json.loads((args.current_programs/"stem"/path.stem/"constraint_repair.json").read_text(encoding="utf-8"))
                else:
                    tex,report=repair_tikz_constraints(path.read_text(encoding="utf-8"),**kwargs)
                    target.write_text(tex,encoding="utf-8")
                return path.stem,report
            reports=dict(pool.map(repair,paths));all_reports[name]=reports
            save(out/"variants"/name/"repairs.json",reports)
            print(f"Frozen {index}/{len(specs)} {name}: {dict(Counter(r['reason'] for r in reports.values()))}",flush=True)
    print("All variants frozen. Evaluation-only reference access starts now.",flush=True)
    save(out/"output_manifest.json",{name:{s:sha(out/"variants"/name/"latex"/f"{s}.tex") for s in stems} for name in specs})
    with threadpool_limits(limits=1),ThreadPoolExecutor(max_workers=args.workers) as pool:
        def reference(stem):
            from geoagent.evaluation.structure import load_reference
            return stem,load_reference(ROOT/'data/test/geometry_reference'/f'{stem}.json')
        refs=dict(pool.map(reference,stems))
        def base(stem):
            try:return stem,compact(score(refs[stem][0],prediction(source/"latex"/f"{stem}.tex"),refs[stem][1]))
            except ValueError:return stem,None
        baseline=dict(pool.map(base,stems));save(out/"baseline.json",baseline)
        cache={(s,sha(source/"latex"/f"{s}.tex")):baseline[s] for s in stems}
        evaluations={};summaries={}
        for index,name in enumerate(specs,1):
            def evaluate(stem):
                path=out/"variants"/name/"latex"/f"{stem}.tex";key=(stem,sha(path))
                if key in cache:return stem,cache[key]
                try:value=compact(score(refs[stem][0],prediction(path),refs[stem][1]))
                except ValueError:value=None
                cache[key]=value
                return stem,value
            rows=dict(pool.map(evaluate,stems));evaluations[name]=rows
            summaries[name]={"development":metrics(baseline,rows,dev),"validation":metrics(baseline,rows,validation),
                "all":metrics(baseline,rows,stems),"applied":sum(r["applied"] for r in all_reports[name].values())}
            save(out/"variants"/name/"evaluation.json",rows)
            print(f"Evaluated {index}/{len(specs)} {name}: dev objective={summaries[name]['development']['joint_relative_error']:.6f}",flush=True)
    scope=args.selection_scope
    eligible=[name for name,s in summaries.items() if s[scope]["lost_angle"]==0 and s[scope]["lost_ratio"]==0
        and s[scope]["coverage"]>=s[scope]["baseline_coverage"]-1e-12
        and all(s[scope][k]["after"]<s[scope][k]["before"] for k in ("angle","ratio"))]
    if not eligible:eligible=list(specs)
    winner=min(eligible,key=lambda name:summaries[name][scope]["joint_relative_error"])
    selection={"geometry_protocol":PROTOCOL,"selected":winner,"parameters":specs[winner],"eligible":eligible,
        "selected_using":scope, "summary":summaries[winner]}
    save(out/"selection.json",selection);save(out/"summaries.json",summaries)
    print("SELECTED",json.dumps({"selected":winner,"parameters":specs[winner],
        "development_objective":summaries[winner]["development"]["joint_relative_error"],
        "validation_objective":summaries[winner]["validation"]["joint_relative_error"]},ensure_ascii=False),flush=True)


if __name__=="__main__":main()
