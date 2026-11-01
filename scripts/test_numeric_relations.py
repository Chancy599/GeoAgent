"""Run pure numerical relation selection on all archived generated figures.

python scripts/test_numeric_relations.py
python scripts/test_numeric_relations.py --stems 1260_q_fig2 1630_s_fig1
python scripts/test_numeric_relations.py --phase evaluate
python scripts/test_numeric_relations.py --preset broad --out-dir outputs/relation_candidates/numeric100_broad

All candidate files are frozen before the first evaluation-only reference read.
No LLM client is created or called. Original sources and archives are unchanged.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import csv
import hashlib
import itertools
import json
import math
from pathlib import Path
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from geoagent.config import load_settings
from geoagent.state.tikz_geometry import clean, extract_geometry
from geoagent.state.relation_candidates import RELATION_TYPES, DEFAULT_LIMITS, accepts, pair_metrics, numeric_candidates

REFERENCE_LIMITS = {"angle_deg":0.1,"relative_length":0.001,"relative_distance":0.0005}
PRESETS = {"tight":DEFAULT_LIMITS,
           "medium":{"angle_deg":1.0,"relative_distance":0.005},
           "broad":{"angle_deg":2.0,"relative_distance":0.005}}
NAME = r"[A-Za-z][A-Za-z0-9_']*"


def save(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding="utf-8")






def prepare(stem,out,limits=DEFAULT_LIMITS):
    source = ROOT/"outputs/ablations/no_post_repair/latex"/f"{stem}.tex"
    geometry = extract_geometry(source.read_text(encoding="utf-8"))
    candidates = numeric_candidates(geometry,limits)
    save(out/stem/"input.json",geometry)
    save(out/stem/"candidates.json",{"candidates":candidates,"limits":limits,
         "reference_used":False,"llm_calls":0,"source_sha256":hashlib.sha256(source.read_bytes()).hexdigest()})
    return len(candidates)


def reference_points(stem,out,geometry,settings):
    source = settings.paths.latex_dir/f"{stem}.tex"
    raw = source.read_bytes()
    # Normalize line endings before Windows write_text translates them, or
    # CRLF bytes would become CRCRLF and introduce paragraphs inside TeX macros.
    tex = source.read_text(encoding="utf-8")
    # Support named coordinates on paths too, e.g. (0,0) coordinate (M2).
    declared = set(re.findall(r"(?<![A-Za-z])coordinate\s*(?:\[[^\]]*\]\s*)?\(("+NAME+r")\)",clean(tex)))
    names = sorted(set(geometry["points"])&declared)
    if len(names)<2:
        raise ValueError("fewer than two matching named reference points")
    dest = out/stem/"evaluation"
    dest.mkdir(parents=True,exist_ok=True)
    cache = dest/"reference_points.json"
    digest = hashlib.sha256(raw).hexdigest()
    if cache.exists():
        data = json.loads(cache.read_text(encoding="utf-8"))
        if data["reference_sha256"]==digest and set(names)==set(data["points"]):
            return data["points"]
    probe = "\n"+"\n".join(
        rf"\pgfpointanchor{{{name}}}{{center}}\pgfgetlastxy{{\geox}}{{\geoy}}\typeout{{GEOEVAL:{name}:\geox:\geoy}}"
        for name in names)+"\n"
    if r"\end{tikzpicture}" not in tex:
        raise ValueError("reference has no tikzpicture end")
    instrumented = tex.replace(r"\end{tikzpicture}",probe+r"\end{tikzpicture}",1)
    with tempfile.TemporaryDirectory(prefix="geo_numeric_eval_") as temporary:
        work = Path(temporary)
        (work/"figure.tex").write_text(instrumented,encoding="utf-8")
        proc = subprocess.run([str(settings.paths.tectonic),"--keep-logs","--untrusted","figure.tex"],cwd=work,
             capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=90)
        log = (work/"figure.log").read_text(encoding="utf-8",errors="replace") if (work/"figure.log").exists() else ""
        (dest/"reference_compile.log").write_text(log+proc.stdout+proc.stderr,encoding="utf-8")
        if proc.returncode:
            raise ValueError("reference compile failed; see reference_compile.log")
        pattern = r"GEOEVAL:("+NAME+r"):\s*([-+\d.]+)pt:\s*([-+\d.]+)pt"
        points = {n:[float(x),float(y)] for n,x,y in re.findall(pattern,log)}
    if set(points)!=set(names):
        raise ValueError(f"reference probe incomplete: {len(points)}/{len(names)}")
    save(cache,{"points":points,"reference_sha256":digest,"requested_names":names,
                "missing_names":sorted(set(geometry["points"])-set(points))})
    return points


def score(tp,fp,fn):
    return {"tp":tp,"fp":fp,"fn":fn,"predicted":tp+fp,"true":tp+fn,
            "precision":tp/(tp+fp) if tp+fp else None,"recall":tp/(tp+fn) if tp+fn else None}


def evaluate(stem,out,settings):
    geometry = json.loads((out/stem/"input.json").read_text(encoding="utf-8"))
    frozen = json.loads((out/stem/"candidates.json").read_text(encoding="utf-8"))
    selection_limits=frozen["limits"]
    ref = reference_points(stem,out,geometry,settings)
    rows = []
    unevaluable = []
    for first,second in itertools.combinations(sorted(geometry["segments"]),2):
        endpoints = [geometry["segments"][first],geometry["segments"][second]]
        try:
            observed = pair_metrics(geometry["points"],*endpoints)
            expected = pair_metrics(ref,*endpoints)
        except (KeyError,ValueError) as exc:
            unevaluable.append({"segments":[first,second],"reason":str(exc)})
            continue
        for kind in RELATION_TYPES:
            truth = accepts(kind,expected,REFERENCE_LIMITS)
            predicted = accepts(kind,observed,selection_limits)
            rows.append({"type":kind,"segments":[first,second],"observed":observed,
                         "reference":expected,"reference_pass":truth,"selected":predicted})
    by_preset = {}
    for name,limits in PRESETS.items():
        by_preset[name] = {}
        for kind in RELATION_TYPES:
            subset = [r for r in rows if r["type"]==kind]
            pairs = [(accepts(kind,r["observed"],limits),r["reference_pass"]) for r in subset]
            by_preset[name][kind] = score(sum(p and t for p,t in pairs),sum(p and not t for p,t in pairs),sum(not p and t for p,t in pairs))
    report = {"stem":stem,"candidate_count":len(frozen["candidates"]),"scored_pairs":len(rows)//len(RELATION_TYPES),
              "selected_preset":next(name for name,setting in PRESETS.items() if setting==selection_limits),
              "unscored_pairs":unevaluable,"by_preset":by_preset,
              "selected":[r for r in rows if r["selected"]],
              "missed":[r for r in rows if r["reference_pass"] and not r["selected"]]}
    save(out/stem/"evaluation.json",report)
    return report


def summarize(out,stems,prepared,reports,errors):
    selected_preset=reports[0]["selected_preset"] if reports else "tight"
    if any(r["selected_preset"]!=selected_preset for r in reports):
        raise ValueError("Mixed selection presets in one output directory")
    aggregate = {}
    for preset in PRESETS:
        aggregate[preset] = {}
        for kind in RELATION_TYPES:
            totals = {k:sum(r["by_preset"][preset][kind][k] for r in reports) for k in ("tp","fp","fn")}
            aggregate[preset][kind] = score(**totals)
        totals = {k:sum(aggregate[preset][kind][k] for kind in RELATION_TYPES) for k in ("tp","fp","fn")}
        aggregate[preset]["all"] = score(**totals)
    summary = {"attempted_images":len(stems),"prepared_images":len(prepared),"evaluated_images":len(reports),
        "llm_calls":0,"reference_used_for_selection":False,"candidate_count":sum(r["candidate_count"] for r in reports),
        "unscored_pair_count":sum(len(r["unscored_pairs"]) for r in reports),"errors":errors,
        "presets":PRESETS,"selected_preset":selected_preset,"reference_limits":REFERENCE_LIMITS,"aggregate":aggregate,
        "unscored_candidate_count":sum(r["candidate_count"]-len(r["selected"]) for r in reports),
        "cases":[{k:r[k] for k in ("stem","candidate_count","scored_pairs","by_preset")} for r in reports]}
    save(out/"summary.json",summary)
    with (out/"candidates.csv").open("w",encoding="utf-8-sig",newline="") as handle:
        fields=["stem","type","segment_1","segment_2","reference_pass","parallel_error_deg","perpendicular_error_deg","relative_length_error",
                "reference_parallel_error_deg","reference_perpendicular_error_deg","reference_relative_length_error"]
        writer=csv.DictWriter(handle,fieldnames=fields)
        writer.writeheader()
        for report in reports:
            for row in report["selected"]:
                writer.writerow({"stem":report["stem"],"type":row["type"],"segment_1":row["segments"][0],"segment_2":row["segments"][1],
                     "reference_pass":row["reference_pass"],**{k:row["observed"][k] for k in fields[5:8]},
                     **{"reference_"+k:row["reference"][k] for k in fields[5:8]}})
    pct=lambda value: "—" if value is None else f"{value:.1%}"
    lines=["# 平行与垂直数值筛选：100图实验","",
      "输入为 outputs/ablations/no_post_repair/latex 已生成代码的命名点和已绘制线段。先完成全部图片的数值候选筛选，再读取参考代码，仅评估、不反向修改候选。没有调用LLM，也没有修改已有TikZ。", "",
      f"尝试 {len(stems)} 图，成功提取 {len(prepared)} 图，成功完成参考评估 {len(reports)} 图。", "",
      f"主设置 {selected_preset}：平行/垂直角度误差≤{PRESETS[selected_preset]['angle_deg']}°。平行排除共享端点及同一直线的片段。参考支持门限：角度≤0.1°，同线区分容差为图形跨度0.05%。不筛选等长或共线关系。", "",
      "| 类型 | 候选数（可评估） | 参考坐标支持 | 不支持 | 漏检 | 精确率 | 召回率 |","|---|---:|---:|---:|---:|---:|---:|"]
    for kind in (*RELATION_TYPES,"all"):
        s=aggregate[selected_preset][kind]
        lines.append(f"| {kind} | {s['predicted']} | {s['tp']} | {s['fp']} | {s['fn']} | {pct(s['precision'])} | {pct(s['recall'])} |")
    lines += ["","## 门限对比（相同图片和参考标准）","","| 预设 | 角度 | 候选数 | 精确率 | 召回率 |","|---|---:|---:|---:|---:|---:|"]
    for name,limits in PRESETS.items():
        s=aggregate[name]["all"]
        lines.append(f"| {name} | {limits['angle_deg']}° | {s['predicted']} | {pct(s['precision'])} | {pct(s['recall'])} |")
    lines += ["","## 覆盖范围与限制","",
      "统计只覆盖已提取线段对中、四个端点均在参考代码中有同名坐标的组合。缺失标签、线段或对象不计入此召回率。圆弧和圆不参与。近似关系是候选，不自动成为硬约束。参考直角标记不覆盖坐标计算结果。", "",
      "三组门限在大批评估前已设定；看到本批结果后，将tight选为默认。此处是同批数据上的门限选择结果，并非独立留出集验证。", "",
      f"无法评估的线段对：{summary['unscored_pair_count']}，其中选出的未评分候选为{summary['unscored_candidate_count']}个。所有未评分候选仍保存在各图 candidates.json 中。", "",
      "## 未完成案例","","```json",json.dumps(errors,ensure_ascii=False,indent=2),"```","",
      "## 逐图结果","","| 案例 | 正确/候选 | 漏检 |","|---|---:|---:|"]
    for report in reports:
        s={k:sum(report["by_preset"][selected_preset][kind][k] for kind in RELATION_TYPES) for k in ("tp","predicted","fn")}
        lines.append(f"| {report['stem']} | {s['tp']}/{s['predicted']} | {s['fn']} |")
    (out/"report.md").write_text("\n".join(lines)+"\n",encoding="utf-8")
    print(json.dumps({k:summary[k] for k in ("attempted_images","prepared_images","evaluated_images","unscored_pair_count","aggregate")},ensure_ascii=False),flush=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stems",nargs="+")
    parser.add_argument("--out-dir",type=Path,default=ROOT/"outputs/relation_candidates/numeric100_angles")
    parser.add_argument("--phase",choices=["all","select","evaluate"],default="all")
    parser.add_argument("--workers",type=int,default=4)
    parser.add_argument("--preset",choices=list(PRESETS),default="tight")
    args=parser.parse_args()
    stems=args.stems or [p.stem for p in sorted((ROOT/"outputs/ablations/no_post_repair/latex").glob("*.tex"))]
    out=args.out_dir.resolve()
    out.mkdir(parents=True,exist_ok=True)
    errors,prepared,reports=[],[],[]
    for stem in stems:
        try:
            if args.phase!="evaluate":
                prepare(stem,out,PRESETS[args.preset])
            elif not (out/stem/"candidates.json").exists():
                raise ValueError("frozen candidates missing")
            prepared.append(stem)
        except Exception as exc:
            errors.append({"stem":stem,"phase":"select","error":str(exc)})
    save(out/"selection_manifest.json",{"prepared":prepared,"errors":errors,"presets":PRESETS,
         "reference_limits":REFERENCE_LIMITS,"reference_used":False,"llm_calls":0})
    print(f"Selection complete: {len(prepared)}/{len(stems)} images; 0 reference reads, 0 LLM calls.",flush=True)
    if args.phase!="select":
        settings=load_settings()
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures={pool.submit(evaluate,stem,out,settings):stem for stem in prepared}
            for n,future in enumerate(as_completed(futures),1):
                stem=futures[future]
                try:
                    reports.append(future.result())
                except Exception as exc:
                    errors.append({"stem":stem,"phase":"evaluate","error":str(exc)})
                    print(f"SKIP {stem}: {exc}",flush=True)
                if n%10==0:
                    print(f"Evaluated {n}/{len(prepared)}",flush=True)
    reports.sort(key=lambda r:r["stem"])
    summarize(out,stems,prepared,reports,errors)


if __name__=="__main__":
    main()
