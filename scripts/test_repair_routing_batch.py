"""Preselected multi-case replication of the additions-only routing pilot."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.test_repair_routing import prepare_seed, run_arm, save, write_report, audit
from geoagent.state.schemas import GeometricEvidenceState

DEFAULT_STEMS = ["1653_s_fig1", "795_q_fig2", "6215_s_fig1", "3379_q_fig1"]
REASONS = {
    "1653_s_fig1": "PC 与 EF 交点的 M 标签缺失",
    "795_q_fig2": "PF 与 AB 交点的 E 标签缺失",
    "6215_s_fig1": "BI 与 AD 交点的 I 圆点和标签缺失",
    "3379_q_fig1": "直径左端的 M 标签缺失",
}
TARGET_LABELS = {"1653_s_fig1": "M", "795_q_fig2": "E", "6215_s_fig1": "I", "3379_q_fig1": "M"}


def case_run(stem: str, directory: Path) -> dict:
    directory.mkdir()
    seed = prepare_seed(stem, directory)
    results = []
    for arm in ("direct", "routed"):
        print(f"CASE {stem}: {arm}", flush=True)
        results.append(run_arm(seed, directory / arm, arm == "routed"))
        save(directory / "summary.json", results)
    write_report(directory, seed, results)
    return {"stem": stem, "reason": REASONS.get(stem, "user-selected"), "results": results}


def batch_report(directory: Path, cases: list[dict], stems: list[str]) -> None:
    rows = ["# 漏画元素与标签：多样本修复路由对照", "",
        "预先按首轮 high/medium 漏标签或漏点问题选定四例，不按本次运行结果筛选。",
        "每例共用归档 v1 与首轮评审，各组至多一次代码修复。原型与 1260 试验相同，未修改正式主流程。",
        "输入为无后续 CV/Geometry 重访的归档核心状态重建，不是完整端到端重跑。未向模型提供历史后续版本或参考 LaTeX。",
        "路由组有额外调用，非等预算实验。Critic 是内部信号，标签审计也不是完整结构评测。", "",
        "| 图片 | 组别 | 状态 | 路线 | Critic前/后 | 严重问题前/后 | must_repair | SSIM | 无GES点的已画标签 | token | 秒 |",
        "|---|---|---|---|---|---|---|---|---|---|---|"]
    for stem in stems:
        c = next((c for c in cases if c["stem"] == stem), None)
        if c is None:
            continue
        if "error" in c:
            rows.append(f"| {stem} | - | {c['error']} | | | | | | | | |")
        for r in c.get("results", []):
            missing = r.get("audit_after", {}).get("drawn_labels_without_ges_point")
            score = r.get("ssim")
            rows.append(f"| [{stem}]({stem}/report.md) | {r['arm']} | {r['status']} | {r.get('selected_route','-')} | {r.get('initial_score')}/{r.get('critic_score')} | {r.get('initial_serious_issues')}/{r.get('serious_issues')} | {r.get('must_repair')} | {score if score is None else round(score,6)} | {missing} | {r['usage']['totals']['total_tokens']} | {r['elapsed_s']} |")
    rows += ["", "## 预选问题", ""]
    rows += [f"- {stem}：{REASONS.get(stem,'user-selected')}" for stem in stems]
    rows += ["", "每例诊断、取证、几何增量、CV验证、回退与最终源码均保留在对应目录。",
        "失败组保留失败阶段和候选状态，不按成功样本补跑替换。"]
    (directory / "report.md").write_text("\n".join(rows), encoding="utf-8")


def refresh_audits(directory: Path) -> dict:
    """Apply the same source/graph audit to every arm without new model calls.

    Version 2 recognizes separate labels_point bindings, avoiding a false
    negative when the geometry point exists but has no point.label field.
    """
    selection = json.loads((directory / "selection.json").read_text(encoding="utf-8"))
    cases = json.loads((directory / "summary.json").read_text(encoding="utf-8"))
    for c in cases:
        for r in c.get("results", []):
            folder = directory / c["stem"] / r["arm"]
            state = GeometricEvidenceState.model_validate_json((folder / "state_after.json").read_text(encoding="utf-8"))
            r["audit_after"] = audit(state)
            r["audit_refresh"] = "Uniform offline v2 audit; no changes to model results, state or render"
            target = TARGET_LABELS.get(c["stem"])
            r["target_label"] = target
            r["target_label_drawn"] = bool(r.get("compile_ok")) and target in r["audit_after"]["drawn_labels"]
            r["target_label_has_ges_point"] = target in r["audit_after"]["ges_point_labels"]
            save(folder / "result.json", r)
        if c.get("results"):
            save(directory / c["stem"] / "summary.json", c["results"])
            seed = GeometricEvidenceState.model_validate_json((directory / c["stem"] / "seed.json").read_text(encoding="utf-8"))
            write_report(directory / c["stem"], seed, c["results"])
    save(directory / "summary.json", cases)
    batch_report(directory, cases, selection["stems"])
    aggregates = {}
    rows = ["", "## 固定目标标签核对", "",
            "所有组统一采用审计 v2：接受点标签、有效标签绑定和 labels_point 关系。仅重算审计，不改模型输出、图像或状态。",
            "标签存在采用源码检查，不能独立证明视觉位置或圆点绘制正确。", "",
            "| 图片 | 目标 | direct 已画/有GES点 | routed 已画/有GES点 |", "|---|---|---|---|"]
    for c in cases:
        pairs = {r["arm"]: r for r in c.get("results", [])}
        cells = []
        for arm in ("direct", "routed"):
            r = pairs.get(arm, {})
            cells.append(f"{r.get('target_label_drawn')}/{r.get('target_label_has_ges_point')}")
        rows.append(f"| {c['stem']} | {TARGET_LABELS.get(c['stem'])} | {cells[0]} | {cells[1]} |")
    for arm in ("direct", "routed"):
        values = [r for c in cases for r in c.get("results", []) if r["arm"] == arm]
        aggregates[arm] = {"planned_cases": len(selection["stems"]), "recorded_cases": len(values),
            "compiled": sum(r.get("compile_ok") is True for r in values),
            "target_label_drawn": sum(r.get("target_label_drawn") is True for r in values),
            "target_label_has_ges_point": sum(r.get("target_label_has_ges_point") is True for r in values),
            "must_repair_false": sum(r.get("must_repair") is False for r in values),
            "total_tokens": sum(r["usage"]["totals"]["total_tokens"] for r in values),
            "sum_elapsed_s": round(sum(r["elapsed_s"] for r in values),2)}
    save(directory / "aggregate.json", aggregates)
    with (directory / "report.md").open("a", encoding="utf-8") as stream:
        stream.write("\n".join(rows))
    return aggregates


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stems", nargs="+", default=DEFAULT_STEMS)
    parser.add_argument("--jobs", type=int, choices=(1, 2), default=2)
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--refresh-dir", type=Path, help="Recompute audits/reports only, no API calls")
    args = parser.parse_args()
    if args.refresh_dir:
        print(json.dumps(refresh_audits(args.refresh_dir), ensure_ascii=False, indent=2))
        return
    directory = ROOT / "outputs" / "repair_routing_batch" / datetime.now().strftime("%Y%m%d_%H%M%S")
    directory.mkdir(parents=True, exist_ok=False)
    save(directory / "selection.json", {"stems": args.stems, "reasons": REASONS,
        "selection": "archived v1 high/medium missing labels or points, before running either arm",
        "model_and_budget": "same environment settings; routed arm uses extra diagnosis/geometry calls",
        "script_sha256": __import__('hashlib').sha256((ROOT / 'scripts/test_repair_routing.py').read_bytes()).hexdigest()})
    print(f"BATCH OUTPUT: {directory}", flush=True)
    if args.prepare_only:
        for stem in args.stems:
            p = directory / stem
            p.mkdir()
            prepare_seed(stem, p)
            print(f"prepared {stem}", flush=True)
        return
    cases = []
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        tasks = {pool.submit(case_run, stem, directory / stem): stem for stem in args.stems}
        for task in as_completed(tasks):
            stem = tasks[task]
            try:
                cases.append(task.result())
            except Exception as exc:
                cases.append({"stem": stem, "error": type(exc).__name__})
            save(directory / "summary.json", cases)
            batch_report(directory, cases, args.stems)
            print(f"FINISHED {stem}", flush=True)
    refresh_audits(directory)
    print(f"REPORT: {directory / 'report.md'}", flush=True)


if __name__ == "__main__":
    main()
