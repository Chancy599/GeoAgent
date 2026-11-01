"""Optimize archived coordinates using only numerical parallel/perpendicular candidates.

python scripts/test_optimize_relations.py
python scripts/test_optimize_relations.py --render

Curved figures are deferred until circle/arc preservation is implemented.
All optimizations finish before any evaluation-only reference reads.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import re
import sys

import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.test_numeric_relations import extract_geometry,clean,save,NAME,REFERENCE_LIMITS
from geoagent.state.relation_candidates import numeric_candidates,pair_metrics,accepts
from geoagent.state.optimize_relations import optimize_coordinates
from geoagent.state.tikz_geometry import has_curves, local_map, rewrite_tex








def aligned_error(points,reference):
    names=sorted(set(points)&set(reference))
    if len(names)<3:
        return None
    x=np.array([points[n] for n in names]);y=np.array([reference[n] for n in names])
    x-=x.mean(axis=0);y-=y.mean(axis=0)
    u,s,vt=np.linalg.svd(x.T@y)
    sign=np.eye(2);sign[-1,-1]=np.linalg.det(u@vt)
    rotation=u@sign@vt
    scale=float(np.sum((x@rotation)*y))/float(np.sum(x*x))
    span=float(np.linalg.norm(np.ptp(y,axis=0)))
    return float(np.sqrt(np.mean(np.sum((scale*x@rotation-y)**2,axis=1))))/span


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir",type=Path,default=ROOT/"outputs/relation_optimization/angles100")
    parser.add_argument("--render",action="store_true")
    parser.add_argument("--verify-exports",action="store_true")
    args=parser.parse_args()
    out=args.out_dir.resolve();out.mkdir(parents=True,exist_ok=True)
    results=[]
    for index,source in enumerate(sorted((ROOT/"outputs/ablations/no_post_repair/latex").glob("*.tex")),1):
        stem=source.stem;tex=source.read_text(encoding="utf-8")
        before=extract_geometry(tex)
        candidates=numeric_candidates(before)
        if has_curves(tex):
            after=before
            report={"applied":False,"reason":"deferred_curves","input_candidates":len(candidates),"accepted":[],"rejected":[],"reference_used":False}
        else:
            after,report=optimize_coordinates(before,candidates)
        report["stem"]=stem
        save(out/stem/"before.json",before)
        save(out/stem/"after.json",after)
        save(out/stem/"optimization.json",report)
        if report["applied"]:
            (out/stem/"optimized.tex").write_text(rewrite_tex(tex,before,after),encoding="utf-8")
        results.append(report)
        if index%10==0:
            print(f"Optimized {index}/100",flush=True)
    print("Optimization frozen. Starting evaluation-only reference access.",flush=True)
    # Reuse the already executed, source-hashed reference probes from the
    # preceding experiment. Reference coordinates never enter the optimizer.
    for report in results:
        stem=report["stem"]
        if not report.get("accepted"):
            continue
        cache=ROOT/"outputs/relation_candidates/numeric100"/stem/"evaluation/reference_points.json"
        if not cache.exists():
            report["evaluation_error"]="reference probe cache missing"
            continue
        import hashlib
        cached=json.loads(cache.read_text(encoding="utf-8"))
        source=ROOT/"data/test/latex"/f"{stem}.tex"
        if hashlib.sha256(source.read_bytes()).hexdigest()!=cached["reference_sha256"]:
            report["evaluation_error"]="reference hash changed"
            continue
        reference=cached["points"]
        before=json.loads((out/stem/"before.json").read_text(encoding="utf-8"))
        after=json.loads((out/stem/"after.json").read_text(encoding="utf-8"))
        for candidate in report["accepted"]:
            first,second=(before["segments"][s] for s in candidate["segments"])
            try:
                metrics=pair_metrics(reference,first,second)
                candidate["reference_support"]=accepts(candidate["type"],metrics,REFERENCE_LIMITS)
            except (KeyError,ValueError):
                candidate["reference_support"]=None
        report["reference_landmark_rms_before"]=aligned_error(before["points"],reference)
        report["reference_landmark_rms_after"]=aligned_error(after["points"],reference)
        save(out/stem/"optimization.json",report)
    applied=[r for r in results if r["applied"]]
    accepted=[c for r in results for c in r.get("accepted",[])]
    from collections import Counter
    summary={"images":len(results),"reasons":dict(Counter(r["reason"] for r in results)),
             "applied_images":len(applied),"accepted_relations":len(accepted),
             "max_before_error_deg":max((c["before_error_deg"] for c in accepted),default=0),
             "max_after_error_deg":max((c["after_error_deg"] for c in accepted),default=0),
             "max_shift_rel":max((r.get("max_shift_rel",0) for r in results),default=0),
             "max_length_change_rel":max((r.get("max_length_change_rel",0) for r in results),default=0),
             "rejected_relations":sum(len(r["rejected"]) for r in results),
             "reference_supported":sum(c.get("reference_support") is True for c in accepted),
             "reference_unsupported":sum(c.get("reference_support") is False for c in accepted),
             "reference_unscored":sum(c.get("reference_support") is None for c in accepted),
             "reference_used_for_optimization":False,"cases":results}
    save(out/"summary.json",summary)
    if args.verify_exports:
        summary["export_verification"]=verify_exports(out,results)
        save(out/"summary.json",summary)
    write_report(out,summary)
    if args.render:
        render_examples(out,results)
    print(json.dumps({k:v for k,v in summary.items() if k!="cases"},ensure_ascii=False),flush=True)


def write_report(out,summary):
    lines=["# 平行与垂直约束下的坐标优化","",
      "输入为已有生成代码的坐标。仅采用≤0.5°的平行/垂直候选。以原始点位移平方和为目标，联合迭代投影到关系等式约束上；保持已有内部点与线段的连接及原有微小偏移，不施加等长约束。", "",
      "保护条件：单点位移≤图形对角线0.5%，任何原有线段长度变化≤1%，不允许线段反向、塌缩或内部点越过端点。失败时从角度误差最大的候选起剔除重解；无法接受时返回原坐标。", "",
      "带圆/圆弧/椭圆的图暂不优化，因为还没有保圆约束。输出为实验副本，不修改ours100，也不接入主流水线。optimized.tex保留17位有效数字并局部搬移小型直角标记，导出器支持本批代码的常见写法，并非通用TikZ解析器。", "",
      "参考代码仅在所有优化完成后用于评估，使用之前执行并经哈希核对的参考坐标。角度残差为优化坐标层的结果，TeX实际执行精度另行检查。", "",
      "```json",json.dumps({k:v for k,v in summary.items() if k!="cases"},ensure_ascii=False,indent=2),"```", "",
      "| 案例 | 状态 | 保留关系 | 剔除关系 | 最大位移/对角线 | 最大优化后角误差 |", "|---|---|---:|---:|---:|---:|"]
    for r in summary["cases"]:
        lines.append(f"| {r['stem']} | {r['reason']} | {len(r.get('accepted',[]))} | {len(r['rejected'])} | {r.get('max_shift_rel',0):.6%} | {r.get('max_after_error_deg',0):.3g}° |")
    eligible=[r for r in summary["cases"] if r["applied"] and r.get("reference_landmark_rms_before") is not None]
    improved=sum(r["reference_landmark_rms_after"]<r["reference_landmark_rms_before"]-1e-10 for r in eligible)
    worsened=sum(r["reference_landmark_rms_after"]>r["reference_landmark_rms_before"]+1e-10 for r in eligible)
    lines += ["",f"参考点位对齐误差：修改的{len(eligible)}图中，{improved}图降低，{worsened}图增加。该误差采用同名点做最佳旋转/平移/等比缩放对齐后的RMS，归一化到参考点包围框对角线，不能替代整图视觉指标。",
              "", "数值接近不是关系真值保证。仍有参考坐标不支持的候选被优化器接受，因此目前保持独立实验，不自动覆盖生产输出。"]
    (out/"report.md").write_text("\n".join(lines)+"\n",encoding="utf-8")


def render_examples(out,results):
    from geoagent.tools.compiler import compile_tikz
    from geoagent.tools.renderer import render_pdf
    chosen=["1260_q_fig2","2108_q_fig1","1618_q_fig1","1625_s_fig1","1630_s_fig1","1494_q_fig1"]
    for stem in chosen:
        source=out/stem/"optimized.tex"
        if not source.exists():
            continue
        result=compile_tikz(source.read_text(encoding="utf-8"),out_dir=out/stem/"render",stem="optimized")
        if result["ok"]:
            result["render"]=render_pdf(result["pdf_path"],out/stem/"optimized.png",dpi=200)
        save(out/stem/"render_result.json",result)
        print(f"Render {stem}: {result['ok']}",flush=True)


def verify_exports(out,results):
    """Compile each exported source and measure the coordinates TeX executes."""
    from types import SimpleNamespace
    from concurrent.futures import ThreadPoolExecutor,as_completed
    from geoagent.config import load_settings
    from scripts.test_numeric_relations import reference_points
    compiler=load_settings().paths.tectonic
    def check(report):
        stem=report["stem"]
        geometry=json.loads((out/stem/"after.json").read_text(encoding="utf-8"))
        text=(out/stem/"optimized.tex").read_text(encoding="utf-8")
        if extract_geometry(text)["points"]!=geometry["points"]:
            raise ValueError("exported point coordinates do not round-trip")
        folder=out/stem/"engine_source";folder.mkdir(parents=True,exist_ok=True)
        (folder/f"{stem}.tex").write_text(text,encoding="utf-8")
        settings=SimpleNamespace(paths=SimpleNamespace(latex_dir=folder,tectonic=compiler))
        executed=reference_points(stem,out/stem/"export_check",geometry,settings)
        rows=[]
        for candidate in report["accepted"]:
            metric=pair_metrics(executed,*(geometry["segments"][s] for s in candidate["segments"]))
            rows.append({"type":candidate["type"],"segments":candidate["segments"],
                         "engine_error_deg":metric[candidate["type"]+"_error_deg"]})
        result={"stem":stem,"compiled":True,"point_round_trip":True,"relations":rows,
                "max_engine_error_deg":max((r["engine_error_deg"] for r in rows),default=0)}
        save(out/stem/"export_verification.json",result)
        return result
    verified=[];errors=[]
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures={pool.submit(check,r):r["stem"] for r in results if r["applied"]}
        for future in as_completed(futures):
            try:
                verified.append(future.result())
            except Exception as exc:
                errors.append({"stem":futures[future],"error":str(exc)})
    return {"exported":sum(r["applied"] for r in results),"compiled":len(verified),"errors":errors,
            "max_engine_error_deg":max((r["max_engine_error_deg"] for r in verified),default=0),
            "note":"TeX fixed-point execution has finite precision even when source coordinates round-trip as doubles."}


if __name__=="__main__":
    main()
