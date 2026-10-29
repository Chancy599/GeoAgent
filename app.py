"""Streamlit demo for GeoAgent.

Run with:  streamlit run app.py
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from geoagent.config import load_settings
from geoagent.datasets import scan_dataset
from geoagent.orchestration import GeoAgentRunner
from geoagent.tools import discover_compiler

st.set_page_config(page_title="GeoAgent · 图形转 TikZ", page_icon="📐", layout="wide")

UPLOAD_DIR = ROOT / "outputs" / "uploads"


@st.cache_data(show_spinner=False)
def _dataset_items() -> list[dict]:
    settings = load_settings()
    items = scan_dataset(settings.paths.image_dir, settings.paths.latex_dir)
    return [item.public() for item in items]


def _load_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _read_llm_log(run_dir: Path) -> pd.DataFrame:
    path = run_dir / "llm_calls.jsonl"
    rows = []
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            usage = rec.get("usage", {})
            rows.append(
                {
                    "time": rec.get("ts"),
                    "agent": rec.get("tag"),
                    "images": rec.get("has_images"),
                    "prompt_tokens": usage.get("prompt_tokens"),
                    "completion_tokens": usage.get("completion_tokens"),
                    "total_tokens": usage.get("total_tokens"),
                    "latency_s": rec.get("latency_s"),
                    "finish": rec.get("finish_reason"),
                }
            )
    return pd.DataFrame(rows)


def _sidebar() -> tuple[str | None, dict, bool]:
    st.sidebar.title("GeoAgent")
    st.sidebar.caption("几何图形 → 可编译 TikZ 的多智能体系统")

    settings = load_settings()
    with st.sidebar.expander("环境", expanded=False):
        compiler = discover_compiler(settings.paths)
        st.write(f"模型: `{settings.model.model}`")
        st.write(f"编译: {compiler.get('version') or '未找到'}")
        st.write(f"图片目录: `{settings.paths.image_dir}`")

    items = _dataset_items()
    st.sidebar.subheader("1. 选择图片")
    mode = st.sidebar.radio("来源", ["测试集", "上传"], horizontal=True)
    image_path: str | None = None
    if mode == "测试集":
        labels = [f"{it['stem']}  ({it['width']}×{it['height']})" for it in items]
        choice = st.sidebar.selectbox("样本", labels, index=0 if labels else None)
        if choice:
            stem = choice.split("  ")[0]
            image_path = next(it["image_path"] for it in items if it["stem"] == stem)
    else:
        uploaded = st.sidebar.file_uploader("上传图片", type=["png", "jpg", "jpeg", "bmp", "webp"])
        if uploaded is not None:
            UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
            target = UPLOAD_DIR / uploaded.name
            target.write_bytes(uploaded.getbuffer())
            image_path = str(target)

    st.sidebar.subheader("2. 预算")
    max_steps = st.sidebar.number_input("最大步数", 4, 60, 16)
    max_tools = st.sidebar.number_input("最大工具调用", 8, 120, 32)
    max_visual = st.sidebar.number_input("最大视觉调用", 0, 30, 4)
    max_tokens = st.sidebar.number_input("最大 token 数", 50_000, 2_000_000, 400_000, step=10_000)
    timeout = st.sidebar.number_input("总超时（秒）", 120, 3600, 1200, step=60)
    overrides = {
        "max_steps": int(max_steps),
        "max_tool_calls": int(max_tools),
        "max_visual_calls": int(max_visual),
        "max_total_tokens": int(max_tokens),
        "timeout_seconds": int(timeout),
    }

    st.sidebar.subheader("3. 运行")
    run_clicked = st.sidebar.button("开始运行", type="primary", disabled=image_path is None)
    if st.sidebar.button("清空本次结果", disabled="run_result" not in st.session_state):
        for key in ("run_result", "ges", "run_dir", "events"):
            st.session_state.pop(key, None)
        st.rerun()
    st.sidebar.caption("参考 LaTeX 默认隔离，只有运行结束后才可在“参考”标签查看。")
    return image_path, overrides, run_clicked


def _run_agent(image_path: str, overrides: dict) -> None:
    events: list[dict] = []
    status = st.status("Agent 运行中…", expanded=True)
    trace_area = status.empty()

    def on_event(event: dict) -> None:
        events.append(event)
        kind = event.get("event")
        if kind == "step":
            budget = event.get("budget", {})
            trace_area.write(
                f"**Step {event['step']}** · 剩余 工具 {budget.get('tool_calls_left')} / 视觉 {budget.get('visual_calls_left')} / token {budget.get('tokens_left')}"
            )
        elif kind == "action":
            icon = "✅" if event.get("ok") else "⚠️" if event.get("ok") is False else "•"
            trace_area.write(f"{icon} `{event.get('action')}` — {str(event.get('summary', ''))[:180]}")

    runner = GeoAgentRunner(
        image_path,
        run_overrides=overrides,
        run_dir=ROOT / "outputs" / "runs" / f"{time.strftime('%Y%m%d_%H%M%S')}_{Path(image_path).stem}",
        on_event=on_event,
    )
    started = time.time()
    try:
        result = runner.run()
    except Exception as exc:
        status.update(label="运行失败", state="error")
        st.exception(exc)
        return
    status.update(label=f"完成（{result['status']}，{time.time() - started:.0f}s）", state="complete")
    st.session_state["run_result"] = result
    st.session_state["events"] = events
    st.session_state["run_dir"] = result["run_dir"]
    st.session_state["ges"] = _load_json(Path(result["run_dir"]) / "state.json")


def _show_image_tab(run_dir: Path, image_path: str) -> None:
    left, right = st.columns([1, 1])
    with left:
        st.subheader("原图")
        st.image(image_path, width='stretch')
    with right:
        st.subheader("CV 叠加图")
        cv_dir = run_dir / "cv"
        overlays = {
            "线段检测": cv_dir / "detect_lines.png",
            "圆/圆弧": cv_dir / "detect_circles.png",
            "标签候选": cv_dir / "extract_label_candidates.png",
            "标签识别": cv_dir / "match_label_templates.png",
            "标签绑定": cv_dir / "bind_point_labels.png",
            "直角标记": cv_dir / "detect_right_angle_marker.png",
            "文字/线条分离": cv_dir / "separate_text_and_lines.png",
        }
        available = {k: v for k, v in overlays.items() if v.exists()}
        if not available:
            st.info("本次运行没有生成 CV 可视化。")
        else:
            choice = st.selectbox("选择叠加图", list(available))
            st.image(str(available[choice]), width='stretch')


def _show_tikz_tab(ges: dict, run_dir: Path) -> None:
    versions = ges.get("tikz_versions", [])
    if not versions:
        st.info("还没有 TikZ 版本。")
        return
    best = ges.get("best_version")
    labels = [
        f"v{v['version']} · {'编译成功' if v.get('ok') else '编译失败'}"
        + (" · 当前最佳" if v['version'] == best else "")
        + (f" · critic {v.get('critic_score')}" if v.get("critic_score") is not None else "")
        for v in versions
    ]
    index = next((i for i, v in enumerate(versions) if v["version"] == best), len(versions) - 1)
    choice = st.selectbox("TikZ 版本", range(len(versions)), index=index, format_func=lambda i: labels[i])
    version = versions[choice]

    col_code, col_render = st.columns([1, 1])
    with col_code:
        st.subheader("TikZ 源码")
        st.code(version.get("tex", ""), language="latex")
        stem = f"figure_v{version['version']}"
        st.download_button("下载 .tex", version.get("tex", ""), file_name=f"{stem}.tex", mime="text/x-tex")
    with col_render:
        st.subheader("渲染图")
        png = version.get("png_path")
        if png and Path(png).exists():
            st.image(png, width='stretch')
            st.download_button("下载渲染 .png", Path(png).read_bytes(), file_name=f"{stem}.png", mime="image/png")
        else:
            st.warning("该版本没有渲染图。")
        if version.get("errors"):
            st.error("\n".join(version["errors"][:6]))
        if version.get("critic_report"):
            with st.expander("Critic 报告", expanded=True):
                report = version["critic_report"]
                st.metric("评估分（启发式）", report.get("assessment_score"))
                st.write(report.get("verdict", ""))
                for issue in report.get("issues", [])[:8]:
                    st.write(f"- **[{issue.get('severity')}] {issue.get('type')}** {issue.get('description')}")
                    if issue.get("suggestion"):
                        st.caption(f"建议: {issue['suggestion']}")
        if best and best != version["version"]:
            st.caption(f"当前最佳版本为 v{best}（按 critic 分数选择）；上方可切换查看最新版本。")


def _show_trace_tab(ges: dict, run_dir: Path) -> None:
    actions = ges.get("action_history", [])
    st.subheader("Agent 轨迹")
    if actions:
        frame = pd.DataFrame(
            [
                {
                    "step": a.get("step"),
                    "action": a.get("action"),
                    "purpose": (a.get("purpose") or "")[:100],
                    "status": a.get("status"),
                    "seconds": a.get("duration_s"),
                    "visual": a.get("visual_calls"),
                    "tokens": (a.get("token_usage") or {}).get("delta"),
                    "summary": (a.get("result_summary") or "")[:160],
                    "error": (a.get("error") or "")[:120],
                }
                for a in actions
            ]
        )
        st.dataframe(frame, width='stretch', hide_index=True)
    else:
        st.info("没有 action 记录。")

    usage = ges.get("token_usage", {})
    by_agent = usage.get("by_agent", {})
    if by_agent:
        st.subheader("各 Agent 用量")
        st.dataframe(pd.DataFrame(by_agent).T, width='stretch')

    st.subheader("LLM 调用")
    log = _read_llm_log(run_dir)
    if not log.empty:
        st.dataframe(log, width='stretch', hide_index=True)
    else:
        st.caption("没有 LLM 调用日志。")

    events_path = run_dir / "events.jsonl"
    if events_path.exists():
        with st.expander("原始事件日志"):
            st.code(events_path.read_text(encoding="utf-8")[-12000:], language="json")


def _show_ges_tab(ges: dict) -> None:
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("对象", len(ges.get("objects", {})))
    col2.metric("关系", len(ges.get("relations", {})))
    col3.metric("冲突", len(ges.get("conflicts", [])))
    col4.metric("未决问题", len(ges.get("unresolved_issues", [])))

    st.subheader("几何对象")
    objects = ges.get("objects", {})
    if objects:
        rows = [
            {
                "id": oid,
                "type": o.get("type"),
                "label": o.get("label"),
                "coords": json.dumps(o.get("coords"), ensure_ascii=False)[:120],
                "style": json.dumps(o.get("style"), ensure_ascii=False)[:80],
                "status": o.get("status"),
                "source": o.get("source"),
            }
            for oid, o in objects.items()
        ]
        st.dataframe(pd.DataFrame(rows), width='stretch', hide_index=True)
    else:
        st.info("没有对象。")

    st.subheader("关系")
    relations = ges.get("relations", {})
    if relations:
        rows = [
            {
                "id": rid,
                "subject": r.get("subject"),
                "relation": r.get("relation"),
                "object": r.get("object"),
                "status": r.get("status"),
                "source": r.get("source"),
                "evidence": (r.get("evidence") or "")[:100],
            }
            for rid, r in relations.items()
        ]
        st.dataframe(pd.DataFrame(rows), width='stretch', hide_index=True)
    else:
        st.info("没有关系。")

    if ges.get("label_bindings"):
        st.subheader("标签绑定")
        st.json(ges["label_bindings"])

    st.subheader("未决问题")
    for issue in ges.get("unresolved_issues", []):
        st.write(f"- {issue.get('issue') if isinstance(issue, dict) else issue}")

    st.subheader("冲突")
    for conflict in ges.get("conflicts", []):
        st.write(f"- **{conflict.get('topic')}** ({conflict.get('status')})")
        for claim in conflict.get("claims", [])[:4]:
            st.caption(json.dumps(claim, ensure_ascii=False)[:260])

    with st.expander("证据记录"):
        st.json(ges.get("evidence", {}))


def _show_reference_tab(image_path: str) -> None:
    st.warning("参考 LaTeX 在 Agent 运行期间完全隔离。下方内容仅供人工对照。")
    items = _dataset_items()
    stem = Path(image_path).stem
    item = next((it for it in items if it["stem"] == stem), None)
    if item is None or not item.get("has_reference"):
        st.info("该图片没有参考 LaTeX。")
        return
    settings = load_settings()
    latex_path = Path(settings.paths.latex_dir) / f"{stem}.tex"
    if not latex_path.exists():
        st.info("参考文件不存在。")
        return
    st.code(latex_path.read_text(encoding="utf-8"), language="latex")
    st.caption("参考文件只读展示，流程中从未提供给任何 Agent。")


def main() -> None:
    image_path, overrides, run_clicked = _sidebar()

    if run_clicked and image_path:
        _run_agent(image_path, overrides)
        st.rerun()

    result = st.session_state.get("run_result")
    if result is None:
        st.title("GeoAgent · 几何图形到 TikZ")
        st.markdown(
            "从左侧选择测试集图片或上传图片，设置预算后点击 **开始运行**。\n\n"
            "Supervisor 会依次调度 CV 工具、Geometry / TikZ / Critic 子 Agent，"
            "并把全部证据、编译结果与轨迹记录在 Geometric Evidence State 中。"
        )
        items = _dataset_items()
        st.caption(f"测试集共 {len(items)} 张图片。")
        return

    run_dir = Path(result["run_dir"])
    ges = st.session_state.get("ges") or _load_json(run_dir / "state.json") or {}
    st.title(f"结果 · {Path(result['image_path']).stem}")
    cols = st.columns(5)
    cols[0].metric("状态", result.get("status"))
    cols[1].metric("最佳版本", f"v{result.get('best_version')}" if result.get("best_version") else "—")
    cols[2].metric("Critic 分数（启发式）", result.get("best_score") if result.get("best_score") is not None else "—")
    cols[3].metric("Token", result.get("usage", {}).get("totals", {}).get("total_tokens"))
    cols[4].metric("耗时", f"{result.get('elapsed_s')}s")
    if result.get("summary"):
        st.info(result["summary"])

    tabs = st.tabs(["图像与 CV", "TikZ", "Agent 轨迹", "GES", "参考"])
    with tabs[0]:
        _show_image_tab(run_dir, result["image_path"])
    with tabs[1]:
        _show_tikz_tab(ges, run_dir)
    with tabs[2]:
        _show_trace_tab(ges, run_dir)
    with tabs[3]:
        _show_ges_tab(ges)
    with tabs[4]:
        _show_reference_tab(result["image_path"])


if __name__ == "__main__":
    main()
