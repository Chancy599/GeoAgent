"""Freeze one generated batch, repair copies, and evaluate paired geometry.

No generation occurs in this script. Reference code is first accessed after
every output and its hash have been frozen. All skipped cases remain in both
groups. Example:
python scripts/compare_post_tikz.py --source outputs/ablations/no_post_repair --out results/latest --workers 20
"""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import itertools
import json
from pathlib import Path
import shutil
import sys
from types import SimpleNamespace

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from geoagent.config import load_settings
from geoagent.evaluation.structure import PROTOCOL
from geoagent.datasets import scan_dataset
from geoagent.state.relation_candidates import pair_metrics
from geoagent.state.tikz_geometry import extract_geometry
from geoagent.state.tikz_repair import repair_tikz_constraints
from geoagent.tools.compiler import compile_tikz
from geoagent.tools.renderer import frame_like_original, render_pdf


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def repair_one(source, out, image, settings):
    stem = source.stem
    folder = out / "post" / "stem" / stem
    folder.mkdir(parents=True, exist_ok=True)
    original = source.read_text(encoding="utf-8")
    tex, report = repair_tikz_constraints(
        original, angle_tol_deg=settings.geometry.angle_tol_deg,
        max_shift_rel=settings.geometry.post_max_shift_rel,
        max_length_change_rel=settings.geometry.post_max_length_change_rel,
        topology_tol_rel=getattr(settings.geometry,"post_topology_tol_rel",.002),
        incidence_mode=getattr(settings.geometry,"post_incidence_mode","snap"),
        length_weight=getattr(settings.geometry,"post_length_weight",0.0),
        length_scope=getattr(settings.geometry,"post_length_scope","edges"),
        curve_policy=getattr(settings.geometry,"post_curve_policy","defer"),
        incidence_strength=getattr(settings.geometry,"post_incidence_strength",1.0),
        relation_types=tuple(getattr(settings.geometry,"post_relation_types",("parallel","perpendicular"))),
        relaxation=getattr(settings.geometry,"post_relaxation",1.0),
        curve_options=getattr(settings.geometry,"post_curve_options",None),
    )
    # Keep immutable baseline and attempted export for audit and fallback.
    shutil.copyfile(source, folder / "unrepaired.tex")
    if report["applied"]:
        (folder / "attempted_repaired.tex").write_text(tex, encoding="utf-8")
        compiled = compile_tikz(tex, out_dir=folder / "compile", paths=settings.paths)
        if compiled["ok"]:
            shutil.copyfile(compiled["tex_path"], folder / "best.tex")
            shutil.copyfile(compiled["pdf_path"], folder / "best.pdf")
            rendered = render_pdf(folder / "best.pdf", folder / "best.png", dpi=200)
            if rendered["ok"]:
                frame_like_original(folder / "best.png", image)
            else:
                raise RuntimeError(rendered["error"])
        else:
            report.update(applied=False, reason="compile_fallback", compile_errors=compiled["errors"],
                          output_sha256=report["input_sha256"])
    if not report["applied"]:
        shutil.copyfile(source, folder / "best.tex")
        for suffix in ("png", "pdf"):
            shutil.copyfile(source.parent.parent / "stem" / stem / f"best.{suffix}", folder / f"best.{suffix}")
    for subdir, filename in (("latex", "best.tex"), ("image", "best.png")):
        target = out / "post" / subdir / f"{stem}{Path(filename).suffix}"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(folder / filename, target)
    report.update(stem=stem, compiled=True, source_file_sha256=sha(source),
                  final_file_sha256=sha(folder / "best.tex"))
    save(folder / "constraint_repair.json", report)
    return report


def relation_checks(gt, pred, items):
    from geoagent.evaluation.structure import backend, label_mapping
    evaluator=backend()[1]
    support,POLICY=evaluator.support,evaluator.POLICY
    mapping = label_mapping(gt, pred)
    available = {}
    for edge in items["edges"]:
        a, b = edge
        available[tuple(edge)] = (a in mapping and b in mapping and
            np.linalg.norm(pred.points[mapping[b]]-pred.points[mapping[a]]) > 1e-12 and
            support(pred.points[mapping[a]], pred.points[mapping[b]], pred.strokes, pred.span) >= POLICY["drawn_coverage"])
    rows = []
    points = {str(i): p for i, p in enumerate(gt.points)}
    for first, second in itertools.combinations(items["edges"], 2):
        metric = pair_metrics(points, [str(i) for i in first], [str(i) for i in second])
        for kind in ("parallel", "perpendicular"):
            if metric[kind+"_error_deg"] > 0.1:
                continue
            if kind == "parallel" and (set(first)&set(second) or metric["relative_line_offset"] <= 0.0005):
                continue
            error = None
            if available[tuple(first)] and available[tuple(second)]:
                named = {str(i): pred.points[j] for i,j in mapping.items()}
                error = pair_metrics(named, [str(i) for i in first], [str(i) for i in second])[kind+"_error_deg"]
            rows.append({"type":kind, "edges":[first,second], "error_deg":error})
    return rows


def evaluate_one(stem, source, out, reference):
    from geoagent.evaluation.structure import source_geometry, score, load_reference
    gt, items = load_reference(ROOT/'data/test/geometry_reference'/f'{stem}.json')
    rows = {}
    for name, folder in (("raw", source), ("post", out / "post")):
        try:
            pred, _, _ = source_geometry(str(folder / "latex" / f"{stem}.tex"))
            result = score(gt, pred, items)
            rows[name] = {
                "compiled":True, "error":None,
                "angle_mae":result["angle"]["mean"], "angle_available":result["angle"]["n_available"],
                "angle_reference":len(items["angles"]), "ratio_mre":result["length_ratio"]["mean"],
                "ratio_available":result["length_ratio"]["n_available"], "ratio_reference":len(items["ratios"]),
                "coverage":result["line_coverage"], "matched":result["alignment"].get("matched"),
                "angle_checks":result["angle_checks"], "ratio_checks":result["ratio_checks"],
                "relation_checks":relation_checks(gt, pred, items),
                "extraction":pred.extraction_audit,"reference_extraction":gt.extraction_audit,
            }
        except Exception as exc:
            rows[name] = dict(compiled=False, error=f"{type(exc).__name__}: {exc}", angle_mae=None,
                angle_available=0, angle_reference=len(items["angles"]), ratio_mre=None, ratio_available=0,
                ratio_reference=len(items["ratios"]), coverage=None, matched=None,
                angle_checks=[], ratio_checks=[], relation_checks=[])
    return stem, rows


def paired_relations(groups, stems):
    result = {}
    for kind in ("parallel", "perpendicular"):
        values = {name:[] for name in groups}
        for stem in stems:
            raw, post = (groups[n][stem] for n in ("raw", "post"))
            if not raw["compiled"] or not post["compiled"]:
                continue
            assert len(raw["relation_checks"]) == len(post["relation_checks"])
            for a,b in zip(raw["relation_checks"], post["relation_checks"]):
                assert a["type"] == b["type"] and a["edges"] == b["edges"]
                if a["type"]==kind and a["error_deg"] is not None and b["error_deg"] is not None:
                    values["raw"].append(a["error_deg"]);values["post"].append(b["error_deg"])
        result[kind] = {"n_common":len(values["raw"]), "groups":{
            name:{"mean_residual_deg":float(np.mean(v)) if v else None,
                  "satisfied":{str(t):sum(e<=t for e in v) for t in (0.1,0.01,0.001)}}
            for name,v in values.items()}}
    return result


def paired_distributions(groups, stems):
    """Common-item tails and image-level bootstrap; never treat items as IID."""
    result={}
    rng=np.random.default_rng(20261101)
    for metric,field in (("angle","angle_checks"),("ratio","ratio_checks")):
        per_image={};items={"raw":[],"post":[]}
        for stem in stems:
            raw,post=(groups[n][stem] for n in ("raw","post"))
            if not raw["compiled"] or not post["compiled"]:
                continue
            common=[(a["error"],b["error"]) for a,b in zip(raw[field],post[field])
                    if a["error"] is not None and b["error"] is not None]
            if not common:
                continue
            values=np.asarray(common)
            a,b=values.mean(axis=0)
            per_image[stem]={"raw":float(a),"post":float(b),"delta":float(b-a),"n_items":len(common)}
            items["raw"].extend(values[:,0]);items["post"].extend(values[:,1])
        deltas=np.asarray([r["delta"] for r in per_image.values()])
        bootstrap=rng.choice(deltas,size=(10000,len(deltas))).mean(axis=1) if len(deltas) else []
        result[metric]={"per_image":per_image,
            "image_improved":int(np.sum(deltas < -1e-9)),"image_worse":int(np.sum(deltas > 1e-9)),
            "image_same":int(np.sum(np.abs(deltas)<=1e-9)),
            "image_bootstrap95_delta":np.quantile(bootstrap,[.025,.975]).tolist() if len(bootstrap) else None,
            "common_item_error_percentiles":{name:dict(zip(("p50","p90","p95","max"),
                map(float,np.quantile(v,[.5,.9,.95,1])))) if v else {} for name,v in items.items()}}
    return result


def availability_audit(groups, stems):
    rows=[]
    for stem in stems:
        raw,post=(groups[n][stem] for n in ("raw","post"))
        if not raw["compiled"] or not post["compiled"]:
            rows.append({"stem":stem,"unparseable":{"raw":raw["error"],"post":post["error"]}})
            continue
        changes={}
        for key in ("angle_checks","ratio_checks"):
            lost=[];gained=[]
            for i,(a,b) in enumerate(zip(raw[key],post[key])):
                if a["error"] is not None and b["error"] is None:lost.append(i)
                if a["error"] is None and b["error"] is not None:gained.append(i)
            if lost or gained:changes[key]={"lost_indices":lost,"gained_indices":gained}
        if changes:
            rows.append({"stem":stem,"raw_coverage":raw["coverage"],"post_coverage":post["coverage"],"changes":changes})
    return rows


def verify_engine(report, out, settings):
    # The probe executes ONLY the frozen generated output, never reference code.
    from scripts.test_numeric_relations import reference_points
    stem=report["stem"]
    tex=(out/"post/latex"/f"{stem}.tex").read_text(encoding="utf-8")
    geometry=extract_geometry(tex)
    probe_settings=SimpleNamespace(paths=SimpleNamespace(latex_dir=out/"post/latex",tectonic=settings.paths.tectonic))
    executed=reference_points(stem,out/"engine_verification",geometry,probe_settings)
    rows=[]
    for c in report["accepted"]:
        error=pair_metrics(executed,*(geometry["segments"][s] for s in c["segments"]))[c["type"]+"_error_deg"]
        rows.append({"type":c["type"],"segments":c["segments"],"error_deg":error})
    result={"stem":stem,"relations":rows,"max_engine_error_deg":max((r["error_deg"] for r in rows),default=0)}
    save(out/"post/stem"/stem/"engine_verification.json",result)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source",type=Path,required=True)
    parser.add_argument("--out",type=Path,required=True)
    parser.add_argument("--workers",type=int,default=20)
    parser.add_argument("--expected",type=int,default=100)
    args=parser.parse_args()
    settings=load_settings();source=args.source.resolve();out=args.out.resolve()
    items={i.stem:i for i in scan_dataset(settings.paths.image_dir,settings.paths.latex_dir)}
    programs=sorted((source/"latex").glob("*.tex"));stems=[p.stem for p in programs]
    if len(programs)!=args.expected:
        raise SystemExit(f"Expected {args.expected} frozen programs, found {len(programs)}")
    frozen={p.stem:sha(p) for p in programs}
    generation_statuses=Counter()
    for stem in stems:
        folder=source/"stem"/stem
        if (folder/"result.json").exists():
            generation_statuses[json.loads((folder/"result.json").read_text(encoding="utf-8"))["status"]]+=1
        if (folder/"state.json").exists():
            state=json.loads((folder/"state.json").read_text(encoding="utf-8"))
            assert not any(e.get("source") in ("geometry_constraint_repair","right_angle_rectifier")
                for e in state.get("evidence",{}).values()),f"{stem}: baseline includes pre-generation repair"
    save(out/"input_manifest.json",{"programs":frozen,"workers":args.workers,"generation_repair_enabled":False,
        "settings":settings.geometry.to_dict(),"generation_model":settings.model.public_dict(),
        "generation_budget":settings.budget.to_dict(),
        "repair_implementation_sha256":{name:sha(ROOT/"geoagent/state"/name) for name in
            ("tikz_repair.py","tikz_geometry.py","angle_glyphs.py","optimize_relations.py","relation_candidates.py","curve_anchors.py")},
        "protocol":"one generated best program per image; fixed baseline selection; paired copies; no post-repair reselection"})
    reports=[]
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures={pool.submit(repair_one,p,out,items[p.stem].image_path,settings):p.stem for p in programs}
        for n,future in enumerate(as_completed(futures),1):
            reports.append(future.result())
            if n%10==0:print(f"Repaired/compiled {n}/{len(stems)}",flush=True)
    reports.sort(key=lambda r:r["stem"])
    assert frozen=={p.stem:sha(p) for p in programs},"baseline changed during repair"
    save(out/"repair_manifest.json",{"reports":reports,"reference_used_for_repair":False})
    print("All output programs frozen. Starting evaluation-only reference access.",flush=True)
    # This local parser and scorer never call an LLM.
    from scripts.evaluate_structure_ab import (_group_summary,_paired_geometry,_item_deltas,_delta_summary)
    groups={"raw":{},"post":{}}
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures={pool.submit(evaluate_one,s,source,out,items[s].latex_path):s for s in stems}
        for n,future in enumerate(as_completed(futures),1):
            stem,rows=future.result()
            for name,row in rows.items():groups[name][stem]=row
            if n%10==0:print(f"Geometry evaluated {n}/{len(stems)}",flush=True)
    structure={"geometry_protocol":PROTOCOL,
        "groups":{name:{"summary":_group_summary(rows),"per_stem":rows} for name,rows in groups.items()},
        "paired_geometry":_paired_geometry(groups,["raw","post"],stems),
        "item_paired":{key:_delta_summary(_item_deltas(groups,"raw","post",field)) for key,field in (("angle","angle_checks"),("ratio","ratio_checks"))},
        "paired_relations":paired_relations(groups,stems),
        "paired_distributions":paired_distributions(groups,stems)}
    save(out/"structure.json",structure)
    save(out/"availability_audit.json",availability_audit(groups,stems))
    engine=[];engine_errors=[]
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures={pool.submit(verify_engine,r,out,settings):r["stem"] for r in reports if r["applied"]}
        for future in as_completed(futures):
            try:engine.append(future.result())
            except Exception as exc:engine_errors.append({"stem":futures[future],"error":str(exc)})
    save(out/"engine_verification.json",{"results":engine,"errors":engine_errors})
    # SSIM is a secondary visual guard; keep its memory-intensive workers bounded.
    from geoagent.evaluation.visual_metrics import ssim_pair
    def visual_one(stem):
        reference=items[stem].image_path
        return {"stem":stem, **{name:ssim_pair(folder/"image"/f"{stem}.png",reference)
            for name,folder in (("raw",source),("post",out/"post"))}}
    with ThreadPoolExecutor(max_workers=min(args.workers,4)) as pool:
        visual=list(pool.map(visual_one,stems))
    save(out/"visual_ssim.json",visual)
    summary={"geometry_protocol":PROTOCOL,"images":len(stems),"workers":args.workers,"applied_images":sum(r["applied"] for r in reports),
        "repair_settings":settings.geometry.to_dict(),
        "generation_statuses":dict(generation_statuses),
        "reasons":dict(Counter(r["reason"] for r in reports)),"accepted_relations":sum(len(r["accepted"]) for r in reports if r["applied"]),
        "compiled":{"raw":len(programs),"post":sum(r["compiled"] for r in reports)},
        "groups":{n:r["summary"] for n,r in structure["groups"].items()},
        "paired_geometry":structure["paired_geometry"],"item_paired":structure["item_paired"],
        "paired_relations":structure["paired_relations"],"engine_verified_images":len(engine),"engine_errors":engine_errors,
        "paired_distributions":{k:{n:v for n,v in r.items() if n!="per_image"} for k,r in structure["paired_distributions"].items()},
        "max_engine_error_deg":max((r["max_engine_error_deg"] for r in engine),default=0),
        "ssim":{n:float(np.mean([r[n] for r in visual])) for n in ("raw","post")},
        "reference_used_for_repair":False,"baseline_hashes_unchanged":True}
    save(out/"summary.json",summary)
    write_report(out,summary,structure)
    print(json.dumps(summary,ensure_ascii=False,indent=2),flush=True)


def write_report(out,summary,structure):
    lines=["# 同批 TikZ：不修复与生成后修复（100 图）", "",
        "每张图只跑一条生成流程，关闭前置几何修复与直角正交化。冻结该流程选出的 best.tex，原始组与后修复组共用它；后修复后不重新选择版本、不再调用模型。生成、编译和几何评测使用 20 个 worker。", "",
        "后修复仅从生成坐标提取候选，按配置联合投影并限制位移及边长变化，不推断等长。曲线方案冻结曲线定义依赖、关联点和已有切线端点；其余点可以调整。未知曲线表达式、局部/非均匀变换及不支持语法保留原样。参考 LaTeX 仅用于输出冻结后的评测。完整配置见 summary.json 的 repair_settings。", "",
        f"几何协议：{summary['geometry_protocol']}。参考原子边及邻接边对在真值侧独立冻结，几何匹配不使用标签；两组共同可测条目先按图平均，再对图平均。比例误差以百分数显示。排除经主体射线验证的直角符号，并禁止文字锚点单独创建几何点。", "",
        "| 指标 | 不修复 | 生成后修复 | 差值（后−前） |", "|---|---:|---:|---:|"]
    for key,label,scale in (("angle","角度 MAE（°）",1),("ratio","长度比例 MRE（%）",100)):
        row=summary["paired_geometry"][key];a=row["means"]["raw"]*scale;b=row["means"]["post"]*scale
        lines.append(f"| {label} | {a:.6f} | {b:.6f} | {b-a:+.6f} |")
    a,b=(summary["ssim"][n]*100 for n in ("raw","post"))
    c,d=(summary["groups"][n]["coverage"]*100 for n in ("raw","post"))
    lines += [f"| 线段覆盖率（%） | {c:.4f} | {d:.4f} | {d-c:+.4f} |",
        f"| SSIM ×100 | {a:.4f} | {b:.4f} | {b-a:+.4f} |", "",
        f"实际修改 {summary['applied_images']}/{summary['images']} 图；保留并修复 {summary['accepted_relations']} 条候选。原因计数：`{summary['reasons']}`。", "",
        f"编译：原始 {summary['compiled']['raw']}/100，后修复 {summary['compiled']['post']}/100。TeX 引擎坐标核验 {summary['engine_verified_images']} 图，错误 {len(summary['engine_errors'])} 个，已接受关系最大引擎残差 {summary['max_engine_error_deg']:.8f}°。源码浮点精度不等于 TeX 执行精度。", "",
        "参考真值约束满足率在两组共同可测的参考平行/垂直边对上统计，满足门限分别为 0.1°、0.01°、0.001°；原始文件、逐图报告、跳过原因及哈希全部保留。", "",
        "共同条目均值不能替代覆盖率：不可测条目未按零误差计入。`availability_audit.json` 单独记录从可测变成不可测或反向变化的条目。逐图改善/退化、误差分位数及按图 bootstrap 区间均在下方摘要；区间只描述本批数据的重采样不确定性，不代表独立数据上的泛化结论。", "",
        "| 参考真值约束（残差 ≤0.01°） | 共同可测关系数 | 不修复满足率 | 生成后修复满足率 |",
        "|---|---:|---:|---:|"]
    for kind,label in (("parallel","平行"),("perpendicular","垂直")):
        r=summary["paired_relations"][kind];n=r["n_common"]
        a,b=(r["groups"][name]["satisfied"]["0.01"] for name in ("raw","post"))
        lines.append(f"| {label} | {n} | {a}/{n} ({a/n:.2%}) | {b}/{n} ({b/n:.2%}) |" if n else f"| {label} | 0 | 不可测 | 不可测 |")
    angle=summary["paired_geometry"]["angle"];ratio=summary["paired_geometry"]["ratio"]
    lines += ["",f"角度共同可测 {angle['n_images']} 图、{angle['n_items']} 条；比例共同可测 {ratio['n_images']} 图、{ratio['n_items']} 条。",
        "", "```json",json.dumps(summary,ensure_ascii=False,indent=2),"```", "",
        "## 逐图差值", "", "| 图 | 角度 MAE Δ（°） | 比例 MRE Δ（百分点） |", "|---|---:|---:|"]
    for stem in sorted(structure["groups"]["raw"]["per_stem"]):
        def delta(key,scale):
            row=structure["paired_distributions"][key]["per_image"].get(stem)
            return f"{row['delta']*scale:+.6f}" if row else "不可测"
        lines.append(f"| {stem} | {delta('angle',1)} | {delta('ratio',100)} |")
    groups={n:r["per_stem"] for n,r in structure["groups"].items()}
    audit=availability_audit(groups,sorted(groups["raw"]))
    lines += ["", "## 可测性与覆盖率变化", "", "```json",json.dumps(audit,ensure_ascii=False,indent=2),"```"]
    (out/"report.md").write_text("\n".join(lines)+"\n",encoding="utf-8")


if __name__=="__main__":
    main()
