"""Coordinate-only LLM relation discovery; reference TeX is evaluation-only.

python scripts/test_relation_candidates.py --prepare-only
python scripts/test_relation_candidates.py
python scripts/test_relation_candidates.py --phase evaluate --out-dir outputs/relation_candidates/pilot

Inference uses generated ours100 coordinates and drawn segment topology, without
images, prior GES relations, or reference sources. Evaluation executes reference
TeX locally to extract its coordinates, then scores the frozen candidates.
"""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from geoagent.config import load_settings
from geoagent.llm.client import LLMClient

DEFAULT_CASES = ["1260_q_fig2", "1630_s_fig1", "2108_q_fig1", "1494_q_fig1", "1618_q_fig1", "1625_s_fig1"]
TYPES = ("parallel", "perpendicular", "equal_length", "collinear")
INPUT_LIMITS = {"angle_deg": 2.0, "relative_length": 0.03, "relative_distance": 0.005}
STRICT_REFERENCE_LIMITS = {"angle_deg": 0.1, "relative_length": 0.001, "relative_distance": 1e-5}
# PGF coordinate calculations have finite precision. Retain strict scores too,
# so tiny execution artifacts are visible rather than silently called errors.
REFERENCE_LIMITS = {**STRICT_REFERENCE_LIMITS, "relative_distance": 0.0005}
SYSTEM = """Find candidate geometric relations from the supplied named coordinates.
You receive ONLY reconstructed coordinates and a whitelist of drawn segments.
No reference diagram, reference code, or ground-truth relations are available.
Return one JSON object {"candidates":[...],"notes":"..."}.
Each candidate is either:
{"type":"parallel|perpendicular|equal_length","segments":["AB","CD"],
 "confidence":"high|medium|low","reason":"short explanation"}
or {"type":"collinear","points":["A","B","C"],"confidence":"...","reason":"..."}.
Use the supplied segment IDs exactly. Collinearity uses exactly three distinct
named points. Do not invent points, coordinates or segments. Do not change coordinates.
Find ALL plausible candidates of all four types, including nonadjacent segments.
Parallel means distinct supporting lines, not two collinear portions of one line.
Treat coordinates as noisy observations: use the supplied numeric tolerances.
Exclude degenerate segments. Do not infer relations solely from familiar labels.
No duplicate or reversed candidates. At most 100 candidates. JSON only."""


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def uncomment(tex):
    return re.sub(r"(?<!\\)%[^\n]*", "", tex)


def extract_input(tex):
    """Small explicit parser for this pilot's generated numeric coordinates.

    Unresolved named coordinate expressions are errors, never silently ignored.
    Single uppercase names exclude helpers such as Q1 and marker corner a1.
    """
    tex = uncomment(tex)
    definitions = re.findall(r"\\coordinate\s*\(([A-Z])\)\s*at\s*(.*?);", tex, re.S)
    points = {}
    for name, expr in definitions:
        match = re.fullmatch(r"\s*\(\s*([-+\d.eE]+)\s*,\s*([-+\d.eE]+)\s*\)\s*", expr)
        if not match:
            raise ValueError(f"Unsupported input coordinate expression for {name}: {expr}")
        xy = [float(x) for x in match.groups()]
        if not all(math.isfinite(x) for x in xy):
            raise ValueError("Non-finite input coordinate")
        points[name] = xy
    segments = {}
    for draw in re.findall(r"\\draw\b(.*?);", tex, re.S):
        # Only actual -- paths are interpreted. Curves/circles are not segments.
        # Lookahead also captures adjacent pairs in (A)--(B)--(C).
        chain = re.findall(r"(?=\(([A-Z])\)\s*--\s*\(([A-Z])\))", draw)
        names = re.findall(r"\(([A-Z])\)", draw)
        if re.search(r"--\s*cycle\b", draw) and len(names) >= 3:
            chain.append((names[-1], names[0]))
        for a, b in chain:
            if a in points and b in points and a != b:
                a, b = sorted((a, b))
                segments[a+b] = [a, b]
    if len(points) < 3 or not segments:
        raise ValueError("Insufficient parsed input geometry")
    return {"points": points, "segments": segments, "candidate_tolerances": INPUT_LIMITS}


def prepare_input(stem, out):
    # Inference boundary: this function never reads data/test/latex or GES.
    source = ROOT / "outputs/ours100/latex" / f"{stem}.tex"
    raw = source.read_bytes()
    geometry = extract_input(raw.decode("utf-8"))
    request = {"system": SYSTEM, "user": json.dumps(geometry, ensure_ascii=False)}
    save(out / stem / "input.json", geometry)
    save(out / stem / "request.json", request)
    save(out / stem / "provenance.json", {"coordinate_source": str(source),
         "sha256": hashlib.sha256(raw).hexdigest(), "reference_in_inference": False,
         "image_in_inference": False, "ges_in_inference": False})
    return request


def infer(stem, out, settings):
    request = prepare_input(stem, out)
    client = LLMClient(settings.model, out / stem / "llm_calls.jsonl")
    result = client.complete_json(request["system"], request["user"],
                                 tag="coordinate_relation_candidates", max_tokens=7000)
    if not isinstance(result.get("candidates"), list):
        raise ValueError("Model did not return a candidates list")
    save(out / stem / "candidates.json", result)
    save(out / stem / "usage.json", client.usage_summary())
    return len(result["candidates"])


def canonical(raw, geometry):
    kind = raw.get("type")
    if kind not in TYPES:
        raise ValueError("Unknown relation type")
    if kind == "collinear":
        names = raw.get("points", [])
        if len(names) != 3 or len(set(names)) != 3 or any(n not in geometry["points"] for n in names):
            raise ValueError("Invalid collinear triple")
    else:
        names = raw.get("segments", [])
        if len(names) != 2 or len(set(names)) != 2 or any(n not in geometry["segments"] for n in names):
            raise ValueError("Invalid segment pair")
    return (kind, *sorted(names))


def measure(key, points, segments):
    coords = {k: np.asarray(v, dtype=float) for k, v in points.items()}
    span = max(float(np.linalg.norm(np.ptp(list(coords.values()), axis=0))), 1e-12)
    if key[0] == "collinear":
        a, b, c = [coords[n] for n in key[1:]]
        pairs = [(a,b,c), (a,c,b), (b,c,a)]
        a, b, c = max(pairs, key=lambda row: np.linalg.norm(row[1]-row[0]))
        u, v = b-a, c-a
        length = float(np.linalg.norm(u))
        if length < span*1e-9:
            raise ValueError("Degenerate collinear points")
        distance = abs(float(u[0]*v[1]-u[1]*v[0])) / length
        return {"relative_distance": distance/span}
    a, b = [coords[n] for n in segments[key[1]]]
    c, d = [coords[n] for n in segments[key[2]]]
    u, v = b-a, d-c
    lu, lv = float(np.linalg.norm(u)), float(np.linalg.norm(v))
    if min(lu,lv) < span*1e-9:
        raise ValueError("Degenerate segment")
    angle = math.degrees(math.atan2(abs(float(u[0]*v[1]-u[1]*v[0])), abs(float(u@v))))
    offset = abs(float(u[0]*(c-a)[1]-u[1]*(c-a)[0]))/lu/span
    if key[0] == "parallel":
        return {"angle_deg": angle, "relative_offset": offset}
    if key[0] == "perpendicular":
        return {"angle_deg": 90-angle}
    return {"relative_length": abs(lu-lv)/max(lu,lv)}


def passes(key, metric, limits):
    if key[0] == "parallel" and metric["relative_offset"] <= limits["relative_distance"]:
        return False
    return all(metric[k] <= limit for k, limit in limits.items() if k in metric)


def universe(geometry):
    for kind in TYPES[:3]:
        for pair in itertools.combinations(sorted(geometry["segments"]), 2):
            yield (kind, *pair)
    for triple in itertools.combinations(sorted(geometry["points"]), 3):
        yield ("collinear", *triple)


def reference_points(stem, out, settings):
    # Called ONLY after all model responses have been frozen to disk.
    source = settings.paths.latex_dir / f"{stem}.tex"
    tex = source.read_text(encoding="utf-8")
    names = sorted(set(re.findall(r"\\coordinate\s*\(([A-Z])\)", uncomment(tex))))
    if not names:
        raise ValueError("No explicit named reference coordinates")
    probe = "\n" + "\n".join(
        rf"\pgfpointanchor{{{n}}}{{center}}\pgfgetlastxy{{\geox}}{{\geoy}}\typeout{{GEOEVAL:{n}:\geox:\geoy}}"
        for n in names) + "\n"
    instrumented = tex.replace(r"\end{tikzpicture}", probe+r"\end{tikzpicture}", 1)
    dest = out / stem / "evaluation"
    dest.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="geo_relation_eval_") as temp:
        work = Path(temp)
        (work / "figure.tex").write_text(instrumented, encoding="utf-8")
        proc = subprocess.run([str(settings.paths.tectonic), "--keep-logs", "--untrusted", "figure.tex"],
                              cwd=work, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
        log = (work / "figure.log").read_text(encoding="utf-8", errors="replace") if (work/"figure.log").exists() else ""
        (dest / "reference_compile.log").write_text(log+proc.stdout+proc.stderr, encoding="utf-8")
        if proc.returncode != 0:
            raise ValueError("Reference compilation failed; see evaluation/reference_compile.log")
        points = {name:[float(x),float(y)] for name,x,y in re.findall(
            r"GEOEVAL:([A-Z]):\s*([-+\d.]+)pt:\s*([-+\d.]+)pt", log)}
    if len(points) != len(names):
        raise ValueError(f"Incomplete reference probe: {len(points)}/{len(names)}")
    declared = re.findall(r"\\tkzMarkRightAngle(?:\[[^\]]*\])?\(([^)]+)\)", uncomment(tex))
    save(dest / "reference_points.json", {"points_pt":points, "declared_right_angles":declared,
         "reference_sha256":hashlib.sha256(source.read_bytes()).hexdigest(),
         "evaluation_basis":"executed reference coordinate geometry; declarations recorded separately"})
    return points


def evaluate(stem, out, settings):
    geometry = json.loads((out/stem/"input.json").read_text(encoding="utf-8"))
    candidates = json.loads((out/stem/"candidates.json").read_text(encoding="utf-8"))["candidates"]
    reference = reference_points(stem, out, settings)
    truth, strict_truth, baseline = set(), set(), set()
    unevaluable = []
    for key in universe(geometry):
        try:
            observed = measure(key, geometry["points"], geometry["segments"])
            actual = measure(key, reference, geometry["segments"])
        except (KeyError, ValueError):
            unevaluable.append(key)
            continue
        if passes(key, observed, INPUT_LIMITS):
            baseline.add(key)
        if passes(key, actual, REFERENCE_LIMITS):
            truth.add(key)
        if passes(key, actual, STRICT_REFERENCE_LIMITS):
            strict_truth.add(key)
    rows, seen, predicted, validated = [], set(), set(), set()
    for raw in candidates:
        row = {"candidate":raw}
        if not isinstance(raw, dict):
            rows.append({"candidate":raw,"status":"invalid","error":"Candidate must be an object"})
            continue
        try:
            key = canonical(raw, geometry)
            if key in seen:
                row["status"] = "duplicate"
            else:
                seen.add(key)
                row["key"] = key
                row["observed_error"] = measure(key, geometry["points"], geometry["segments"])
                row["numeric_pass"] = passes(key,row["observed_error"],INPUT_LIMITS)
                try:
                    row["reference_error"] = measure(key,reference,geometry["segments"])
                    row["reference_pass"] = passes(key,row["reference_error"],REFERENCE_LIMITS)
                    row["status"] = "scored"
                    predicted.add(key)
                    if row["numeric_pass"]:
                        validated.add(key)
                except (KeyError, ValueError) as exc:
                    row.update(status="reference_unavailable",error=str(exc))
        except (ValueError, TypeError) as exc:
            row.update(status="invalid",error=str(exc))
        rows.append(row)
    def score(pred, target):
        tp = len(pred & target)
        return {"predicted":len(pred),"true":len(target),"tp":tp,"fp":len(pred-target),"fn":len(target-pred),
                "precision":tp/len(pred) if pred else None,"recall":tp/len(target) if target else None}
    report = {"stem":stem,"llm":score(predicted,truth),"llm_numeric_filtered":score(validated,truth),
        "numeric_baseline":score(baseline,truth),"by_type":{},"rows":rows,
        "strict_reference_scores":{name:score(pred,strict_truth) for name,pred in
            [("llm",predicted),("llm_numeric_filtered",validated),("numeric_baseline",baseline)]},
        "missing_llm":sorted(truth-predicted),"unevaluable_universe_count":len(unevaluable),
        "reference_limits":REFERENCE_LIMITS,"strict_reference_limits":STRICT_REFERENCE_LIMITS,"input_limits":INPUT_LIMITS}
    for kind in TYPES:
        target = {k for k in truth if k[0]==kind}
        report["by_type"][kind] = {name:score({k for k in pred if k[0]==kind},target) for name,pred in
            [("llm",predicted),("llm_numeric_filtered",validated),("numeric_baseline",baseline)]}
    save(out/stem/"evaluation.json",report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stems", nargs="+", default=DEFAULT_CASES)
    parser.add_argument("--out-dir", type=Path, default=ROOT/"outputs/relation_candidates/pilot")
    parser.add_argument("--phase", choices=["all","infer","evaluate"], default="all")
    parser.add_argument("--prepare-only",action="store_true")
    parser.add_argument("--workers",type=int,default=2)
    args = parser.parse_args()
    out = args.out_dir.resolve()
    if args.prepare_only:
        for stem in args.stems:
            prepare_input(stem,out)
        print("Prepared coordinate-only requests; reference files were not read.")
        return
    settings = load_settings()
    settings.model.temperature = 0
    errors = []
    if args.phase in ("all","infer"):
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = {pool.submit(infer,stem,out,settings):stem for stem in args.stems}
            for future in as_completed(futures):
                stem = futures[future]
                try:
                    print(f"INFER {stem}: {future.result()} candidates",flush=True)
                except Exception as exc:
                    errors.append({"stem":stem,"phase":"infer","error":str(exc)})
                    print(f"INFER {stem}: failed: {exc}",flush=True)
    reports = []
    if args.phase in ("all","evaluate"):
        print("Inference complete. Starting evaluation-only reference access.",flush=True)
        for stem in args.stems:
            if not (out/stem/"candidates.json").exists():
                continue
            try:
                report = evaluate(stem,out,settings)
                reports.append(report)
                print(f"EVAL {stem}: {report['llm']}",flush=True)
            except Exception as exc:
                errors.append({"stem":stem,"phase":"evaluate","error":str(exc)})
                print(f"EVAL {stem}: failed: {exc}",flush=True)
    summary = {"model":settings.model.model,"coordinate_source":"ours100 generated TikZ numeric coordinates",
               "reference_in_inference":False,"images_in_inference":False,"cases":[],"errors":errors}
    for report in reports:
        summary["cases"].append({k:report[k] for k in ("stem","llm","llm_numeric_filtered","numeric_baseline","by_type")})
    summary["aggregate"] = {}
    for method in ("llm","llm_numeric_filtered","numeric_baseline"):
        totals = {k:sum(r[method][k] for r in reports) for k in ("predicted","true","tp","fp","fn")}
        totals["precision"] = totals["tp"]/totals["predicted"] if totals["predicted"] else None
        totals["recall"] = totals["tp"]/totals["true"] if totals["true"] else None
        summary["aggregate"][method] = totals
    save(out/"summary.json",summary)
    if reports:
        write_markdown(out,summary,reports)


def write_markdown(out, summary, reports):
    lines = ["# 坐标关系候选发现实验", "", "输入为 ours100 已生成 TikZ 的点坐标与实线/虚线段连接。LLM 不接收图片、GES 关系或参考代码。所有推理结束后才读取并执行参考代码，评估其实际坐标关系。", "",
      f"模型：{summary['model']}。候选门限：角度误差≤2°，等长相对差≤3%，共线距离≤图形跨度0.5%。", "",
      "参考判定门限：角度误差≤0.1°，等长相对差≤0.1%，共线距离≤跨度0.05%。parallel 排除同一直线上的线段。", "",
      "参考坐标通过实际执行 TeX 提取。初始严格共线门限0.001%会将 PGF 交点/插值的微小数值误差算作不共线，因此主表采用0.05%，每案例 evaluation.json 另保留初始严格门限结果 strict_reference_scores。本次只重新评估，没有更改候选或重跑LLM。", "",
      "注意：数值基线、LLM 采用同一线段/点组合空间。召回率仅覆盖该空间中可由参考坐标评估的关系，不代表题目全部语义关系。参考直角标注单独记录，不替代实际坐标计算。", "",
      "| 案例 | LLM正确/候选 | 参考关系总数 | LLM精确率 | LLM召回率 | 数值过滤后正确/候选 | 纯数值正确/候选 |", "|---|---:|---:|---:|---:|---:|---:|"]
    for report in reports:
        a,b,c = [report[k] for k in ("llm","llm_numeric_filtered","numeric_baseline")]
        fmt = lambda value: "—" if value is None else f"{value:.1%}"
        lines.append(f"| {report['stem']} | {a['tp']}/{a['predicted']} | {a['true']} | {fmt(a['precision'])} | {fmt(a['recall'])} | {b['tp']}/{b['predicted']} | {c['tp']}/{c['predicted']} |")
    lines += ["", "汇总：", "", "```json", json.dumps(summary["aggregate"],ensure_ascii=False,indent=2), "```"]
    lines += ["", "## 按关系类型汇总", "", "| 类型 | LLM候选 | 参考坐标支持 | 参考关系总数 | 漏检 |", "|---|---:|---:|---:|---:|"]
    for kind in TYPES:
        totals = {k:sum(r["by_type"][kind]["llm"][k] for r in reports) for k in ("predicted","tp","true","fn")}
        lines.append(f"| {kind} | {totals['predicted']} | {totals['tp']} | {totals['true']} | {totals['fn']} |")
    lines += ["", "## 结果解释", "",
      "在本次6个定向选择案例中，纯数值枚举的覆盖率高于LLM，LLM尚未表现出坐标关系枚举的优势。LLM候选均通过同一重建坐标宽松门限，因此追加该数值过滤没有减少误报。后续可测试让LLM解释与筛选工具给出的候选，而不依靠其独立枚举。", "",
      "这是参考坐标数值支持率，不是人工标注的题意准确率。例如1630_s_fig1的参考代码使用tkzMarkRightAngle(A,Q,H)，但执行后的AE与HQ夹角仍偏离90°约1.49°。该声明保存在evaluation/reference_points.json中，未用其覆盖数值结果。", ""]
    for report in reports:
        lines += ["", f"## {report['stem']}", "", "| 候选关系 | 重建坐标误差 | 参考坐标误差 | 参考支持 |", "|---|---|---|---|"]
        for row in report["rows"]:
            if row.get("status") != "scored":
                continue
            key = " ".join(row["key"])
            lines.append(f"| {key} | {json.dumps(row['observed_error'])} | {json.dumps(row['reference_error'])} | {'是' if row['reference_pass'] else '否'} |")
        lines += ["", "漏检关系："+json.dumps(report["missing_llm"],ensure_ascii=False)]
    (out/"report.md").write_text("\n".join(lines)+"\n",encoding="utf-8")


if __name__ == "__main__":
    main()
