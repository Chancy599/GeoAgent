# GeoAgent 当前 Pipeline（As-Built）

> 本文描述**当前代码实际实现**的完整流水线，与 `README.md`（使用说明 + 验证记录）互补。
> 需求原文见 `docs/init.md`；本文以代码为准，所有路径、阈值、文件名均取自当前实现。

## 0. 一句话概括

输入一张平面几何图（TriGeoBench 图片或上传图），由 **Supervisor 驱动的 function-calling 循环**动态调用本地 CV 工具和三个子 Agent，生成可编译的 standalone TikZ，经编译、渲染、结构校验和视觉 Critic 评审后，保留最佳版本并归档。**参考 LaTeX 全程对 Agent 不可见。**

### 0.1 术语（全文档统一）

| 术语 | 含义 | 性质 |
|---|---|---|
| `assessment_score` | Critic 对整图的启发式相似度（0–1） | 系统内部控制信号，**不是**外部指标 |
| `checklist_score` | 清单聚合分：present=1、wrong=0.5、missing=0、unclear 不计分子分母 | 确定性聚合（状态判断仍来自 VLM） |
| `actionable_counts` | 非 `flaky`、非信息项的 high/medium/low 计数 | 修复门控输入 |
| `must_repair` | `high>0 或 medium>0 或 low≥2` | 修复门控 |
| `checks_pending` | 清单中 `missing`/`wrong` 的 object_id 列表 | 修复定位 |
| `flaky` | 与上一版方向相反、不计入修复门控的问题 | 矛盾抑制 |
| `best_version` | 按“高/中危问题数少 → `checklist_score` 高 → `assessment_score` 高 → 版本新”排序 | 版本选择 |
| `source` | `vlm` / `checklist` / `tikz_source_check` | 问题来源 |

## 1. 总览

```
data/test/image/*.png（或上传图）
        │  scan_dataset / normalise_stem（100/100 与参考 tex 配对）
        ▼
GeoAgentRunner（创建 run_dir，读取图像尺寸）
        │  GES + LLMClient + VisualContextManager + EvidenceStore + 预算
        ▼
┌──────────────────────────────────────────────────────────────────────┐
│ Supervisor 循环（OpenAI function calling，每步只执行 1 个 tool call） │
│                                                                      │
│  call_cv_tool ──────────► 本地 CV Toolbox（无视觉调用）              │
│                            └─ ingest_cv_result → GES 对象/关系/证据   │
│  inspect_image ─────────► VisualContextManager 裁剪（下一轮附图）    │
│  run_geometry_agent ────► GeometryAgent（CV ≤6 次，submit_geometry）  │
│                            └─ merge_geometry_submission → GES        │
│  run_tikz_agent ────────► TikZAgent（generate / repair）             │
│                            └─ compile_tikz → render_pdf → validate   │
│  run_critic ──────────► CriticAgent（左原图/右渲染，内容等尺度对比图）│
│                            └─ critic_report + assessment_score       │
│  finish ────────────────► 最终 status / summary                      │
└──────────────────────────────────────────────────────────────────────┘
        │  update_best()：高/中危问题数少 → checklist_score 高 → assessment_score 高 → 版本新
        ▼
archive_and_clean ──► outputs/ours/
                       ├── stem/<stem>/best.tex|pdf|png + 日志
                       ├── image/<stem>.png
                       └── latex/<stem>.tex
```

## 2. 入口与初始化

### 2.1 入口

| 入口 | 文件 | 说明 |
|---|---|---|
| CLI | `main.py` | `check-env` / `list` / `run` / `batch` |
| Demo | `app.py` | Streamlit，5 个标签页（图像与 CV、TikZ、轨迹、GES、参考） |
| 核心 | `geoagent/orchestration/runner.py` | `GeoAgentRunner` 单次端到端运行 |

CLI 的 `run` / `batch` 在运行成功且存在 `best_version` 时，默认调用 `archive_and_clean` 归档并删除临时目录；`--no-archive` 可保留，`--archive-dir` 可改归档位置（默认 `outputs/ours`）。

### 2.2 Runner 初始化

`GeoAgentRunner.__init__` 依次完成：

1. 解析图片绝对路径；创建 `run_dir`（默认 `outputs/runs/<timestamp>_<stem>/`，或 `--run-dir` / batch 的 `--out-dir/<stem>`）。
2. 读取图像宽高，写入 `GeometricEvidenceState.image_size`。
3. 构建共享对象：
   - `LLMClient`：统一 API 调用、重试、token 统计，日志写 `llm_calls.jsonl`；
   - `VisualContextManager`：原图、ROI 裁剪、渲染图管理；
   - `EvidenceStore`：`state.json`、`result.json`、`events.jsonl`、`trace.json`、`checkpoints/`；
   - `GeometryAgent` / `TikZAgent` / `CriticAgent`（Critic 传入 `run_dir` 以保存对比图）。
4. 初始化计数器与预算。

### 2.3 模型与图像编码

- 模型：`claude-haiku-5-5`，通过 `.env` 中的 OpenAI 兼容 Base URL 调用（默认 `max_tokens=4096`，可配置 temperature）。
- 图像编码（`LLMClient.encode_image`）：RGB、长边超过 `image_max_dim=1280` 时等比缩小、JPEG q=85、按“路径+mtime+size”缓存 data URI。
- 重试：超时/连接/限流/5xx 指数退避，默认 `max_retries=3`，单请求超时 120s。
- 结构化输出：`complete_json` 解析失败会追加一轮“只返回合法 JSON”的纠正请求。

## 3. Supervisor 循环

实现位置：`geoagent/orchestration/runner.py::run`，提示词见 `geoagent/agents/prompts.py::SUPERVISOR_SYSTEM`。

### 3.1 初始消息

`initial_messages` 只包含：

- system prompt（动作空间、推荐流程、硬性规则）；
- user task：任务描述、图片路径、图像尺寸、`state.summary()`。

**不包含参考 LaTeX 路径或内容。**

### 3.2 每一步

1. **预算检查**：总超时、总 token、工具调用数（有最佳版本后）耗尽则停止。
2. **刷新预算/用量**到 GES，发出 `step` 事件。
3. **调用模型**：`SUPERVISOR_TOOLS` + `tool_choice="auto"`，`max_tokens=4096`。
4. **无 tool call**：最多提示 2 次（`step_nudge`，附状态摘要）；仍无则停止，状态 `partial`（已有版本）或 `blocked`。
5. **有 tool call**：只执行第一个，其余显式回 `"ignored: one action per step"`。
6. **执行动作**，记录 `ActionRecord`（step、动作、参数、状态、耗时、token 增量、视觉调用增量、错误），写 checkpoint，并发出 `action` 事件。
7. `finish` 立即结束循环。

动作空间（仅这 6 个合法工具）：

| 动作 | 作用 | 计入工具预算 | 计入视觉预算 |
|---|---|---|---|
| `call_cv_tool` | 跑单个本地 CV 检测器 | 是 | 否 |
| `inspect_image` | 原图/ROI 视觉复核 | 否（但每步仍只算一次动作） | 是 |
| `run_geometry_agent` | 几何子 Agent | 是 | 仅当 `use_image` |
| `run_tikz_agent` | 生成/修复 TikZ | 是 | 仅 generate + `use_image` |
| `run_critic` | 视觉对比评审 | 是 | 是（一次调用 = 1 次） |
| `finish` | 结束 | 否 | 否 |

> 视觉调用按“是否带图片的 LLM 请求”计数；一次 Critic 请求无论带 1 张还是 2 张图都只算 1 次。

### 3.3 推荐流程（非硬编码）

Prompt 建议：`detect_circles` / `detect_lines` / `detect_right_angle_marker` → `bind_point_labels` → `run_geometry_agent` → `run_tikz_agent(generate)` → `run_critic` → 若 `must_repair=true` 则 `run_tikz_agent(repair)` → 再 `run_critic` → `finish`。`flaky` 问题（与上一版方向相反）不驱动修复；低严重度缩放/长宽比提示视为信息项；`source=checklist/tikz_source_check` 的确定性 issue 与 VLM issue 同等修复。Critic 回复还带 `checklist_score` 与 `checks_pending`。实际执行顺序由模型根据证据决定，但 finish 门控会兜底。

## 4. 子阶段细节

### 4.1 CV Toolbox（本地算法，无 LLM）

注册表：`geoagent/cv_tools/registry.py`，统一返回 `envelope(status, method, params, results, notes, visualization)`。

| 工具 | 方法要点 |
|---|---|
| `detect_lines` | 形态学骨架 + 概率 Hough + 共线合并 + 实/虚线判定；返回每段 `stroke_width_px`；Hough 断在圆弧抑制带时沿法向回补跨度（保留越过顶点的外伸），虚线链在去字形掩膜上重建 |
| `analyze_line_style` | 沿中心线采样 ink support / gap 游程，区分 solid / dashed / dotted |
| `detect_circles` | Hough + RANSAC 圆拟合 + 角度分箱 ink coverage，输出可见弧段；`arc_evidence_reliable` 过滤低覆盖且无长连续区间的拟合，弧蚀刻与点推导均不采用 |
| `fit_arcs` / `extract_visible_arc` | 圆弧拟合与可见角度区间合并（含 0°/360° 环绕） |
| `detect_right_angle_marker` | 垂直长边对 + 擦除长边后的独立方块墨迹验证；虚线臂回退到短笔画配对，并要求方块两臂越过交点继续延伸；给定 ROI 时仍在整图取长边证据，ROI 只限制候选顶点 |
| `separate_text_and_lines` | 按连通域尺寸/笔画宽度分离文字与长线 |
| `extract_label_candidates` | 字母连通域分组（修复 M/N 粘连、O 割裂；字形连通域估 cap height，过滤虚线碎片）；圆心圆点按形状（紧凑、近方、实心）先与字母分离 |
| `match_label_templates` | cmmi10/cmr10 模板 NCC；低分返回 `?`，支持 C → C' 撇号 |
| `bind_point_labels` | 线段顶点推导 + Hungarian 分配字母到点 |

每次 CV 调用后，`ingest_cv_result` 把结果机械地写入 GES（`cv_runs`、objects、relations、evidence），**确定性代码负责来源记录，几何解释交给 Geometry Agent**。

### 4.2 Geometry Agent

实现：`geoagent/agents/geometry_agent.py`。

- 输入：Supervisor 指令、`state.summary(max_objects=60, max_chars=9000)`、可用 CV 次数；可选原图/ROI（计视觉预算）。
- 限制：每个子 Agent 最多 6 次 CV 调用、最多 5 轮对话；第 5 轮强制 `tool_choice=submit_geometry`。
- `max_tokens=8192`；`finish_reason=length` 的响应整段丢弃（即使带 tool call），并提示“压缩后立即提交”。
- 文本 JSON 只有包含 `objects` 键才可作为提交。
- 空提交（既无 objects 也无 relations）被拒；连续 3 次空提交返回失败。
- 提交合并（`merge_geometry_submission`）：
  - 类型白名单：point / segment / line / circle / arc / right_angle / label / polygon；
  - 最多 40 个对象、40 条关系、10 个冲突、12 个 unresolved；
  - 非法对象记录到 `rejected`，不污染 GES；
  - 关系使用受控词表（on_segment、perpendicular、parallel、collinear、midpoint、center_of、endpoint_of、equal_length、tangent 等）。

### 4.3 TikZ Agent

实现：`geoagent/agents/tikz_agent.py`。

- **generate**：输入 GES 对象摘要（最多 60 个）、关系、图片尺寸、STYLE METRICS；可选原图（计视觉预算）。
- **repair**：额外输入上一版完整 tex、编译错误、编译警告、Critic issues；要求返回**完整文档**而非 diff。
- **STYLE METRICS**：`label_detection.measure_style_metrics` 从原图实测笔画宽度与字母 cap height，按“最长边 8 单元（cm）”折算 `line width` 与 `\fontsize`（含建议的像素→单元比例），随指令注入；避免固定 1.2pt / 默认 10pt 在不同图形尺度下比例失真。
- 提交必须是完整 standalone 文档：`\documentclass`、`\begin{document}`、`\begin{tikzpicture}`、`\end{tikzpicture}`、`\end{document}` 缺一不可；不合格会在子 Agent 内退回重交（最多 3 次）。
- Prompt 约束：命名坐标、像素→TikZ 坐标换算与 y 翻转、圆弧用 `arc`、标签用 math mode、保留实/虚线样式、验证过的直角才画、禁止 shell escape。
- 提交后由 Runner 自动编译、渲染、校验（见 4.4），结果写回 tool 回复供 Supervisor 决策。

### 4.4 编译 / 渲染 / 校验

实现：`geoagent/tools/{compiler,renderer,verifier}.py`。

1. `compile_tikz`：
   - 安全检查，拒绝 `\write18`、`\immediate\write`、`\openout`、`\read`、`\csname`；
   - 在 ASCII 临时目录编译（兼容中文路径）；
   - 使用 `tool/tectonic/tectonic.exe` 的持久缓存；
   - 默认编译超时 120s，保留 `log_tail`。
2. `render_pdf`：PyMuPDF 200 dpi 渲染第一页，裁掉四周白边，输出 PNG。校验完成后，`frame_like_original` 再把渲染图的墨迹框等比缩放、对齐到原图的墨迹框，输出与原图同尺寸、同内容占比的画布；校验仍基于重框前的原始渲染，避免重框掩盖图形比例错误。
3. `validate_compilation` 检查项：
   - `documentclass` 存在；
   - `document` 环境配平；
   - `tikzpicture` 配平且非空；
   - 无 shell escape；
   - 编译器成功（returncode / ok）；
   - PDF 与 PNG 产物存在；
   - 渲染非空白（ink ratio ≥ 0.002）；
   - 长宽比与原图差异 ≤ 35%；
   - 图形 bbox 长宽比与原图差异 ≤ 50%。
4. `state.mark_compilation` 写入产物路径、错误、警告；`update_best(allow_unscored=True)` 允许未评分版本先成为 best。

### 4.5 Critic Agent

实现：`geoagent/agents/critic_agent.py` + `prompts.py::CRITIC_SYSTEM`。

1. **选目标**：逆向遍历 `tikz_versions`，取最新一个 `ok` 且存在 PNG 的版本（不是 `best_version`）。
2. **预算**：`_visual_left() <= 0` 直接返回错误。
3. **内容等尺度对比图**（`build_comparison_image`）：
   - 左面板 = 原图，右面板 = 渲染图；
   - 两边先各自裁剪到墨迹包围盒，再按最长边等比缩放进面板 90% 的内容框并居中（排除原图与渲染图不等量的白边）；
   - 中间 12px 浅灰分隔；
   - 输出 1252×620，低于默认 1280，编码时不会二次缩放；
   - 保存到 `<run_dir>/critic/compare_vN.png`（归档后随运行目录删除）。
4. **单图输入**：一张 composite + 文字说明（LEFT=原图，RIGHT=渲染）+ FOCUS + VERSION + GES 摘要 + **CHECKLIST**；一次请求计 1 次视觉调用。清单由 `_build_checklist` 从 GES 生成（最多 24 项）：线段/圆弧/圆/直线优先，带标签的点其次；跳过 `rejected`、无标签点和 `label` 对象（标签另做源码核对）。
5. **输出契约**：`assessment_score`（0–1 启发式相似度，**不是**校准概率）、`verdict`、`figure_type`、`issues[{type, severity, object_ids, bbox, description, suggestion}]`、`checks[{object_id, status, note}]`、`matches`、`labels`。`object_ids` 引用 GES id，`bbox` 是原图面板内的归一化 `[x0,y0,x1,y1]`。`status ∈ present|missing|wrong|unclear`；`missing` 的语义是“原图可见但渲染缺失”，`unclear` 覆盖“原图里也找不到”。
6. **清洗**（`_sanitise`）：
   - 分数转 float 并 clamp 到 `[0,1]`，保留 3 位；
   - issue type 仅允许 7 类，severity 仅 high/medium/low，非法值降级；
   - `object_ids` 最多 8 个、每个 64 字符；`bbox` 必须是 4 个 0–1 的数，否则丢弃；
   - `checks` 只接受 GES 中存在的 object_id，按 id 去重，status 必须在白名单内；
   - issues/matches 各最多 12 条，description/suggestion 截断 500 字符；
   - labels 每类最多 20；
   - 未识别字段放入 `raw_meta`；
   - **截断保护**：Critic 输出上限 8192 tokens；`LLMClient.complete_json` 遇到 `finish_reason=length` 会以双倍预算（上限 16384）重试一次，仍截断则抛错。清洗后若 `verdict` / `issues` / `checks` / `labels` 全为空也抛错，Supervisor 收到 `ok=false` 而非把空评审当成 0 分写回 GES。
7. **清单聚合**：`checklist_score` 为确定性分数：present=1、wrong=0.5、missing=0；`unclear` 不计入分子分母（全部 unclear 时为 `None`）。VLM 未在 issues 中点名、但清单判为 missing/wrong 的对象会生成 `source=checklist` 的 issue：结构元素 missing=high、点 missing=medium、wrong=low；bbox 由对象像素坐标换算，并与 VLM issue 按 object_ids 去重。这样“VLM 注意到但漏写”的差异也会进入修复门控，同时分数量纲不再饱和在 0.90–0.96。
8. **源码标签核对**（`source=tikz_source_check`）：
   - 期望标签：`label_bindings`（high）+ 对象 label（medium），只取单字母、可带撇号；
   - 实际标签：扫描 tex 的 `$...$` / `\(...\)`，把 `'` 与 `^{\prime}` 归一化为 `′`；
   - **只有 VLM 已在 `labels.missing` 中列出该标签时**才生成 issue；CV 字形 OCR 会误读（实测 6220 把 `G` 读成 `U`），单靠 CV 绑定会制造幽灵标签。已在该 issue 描述中提到的标签不重复生成；tex 为空时整步跳过。
9. **矛盾抑制**：把新 issue 与**最近一份**非空报告比较；同一 type、同一方向组（粗细/远近/大小）出现相反方向且主题相同（object_ids 相交、权重词相同或词集 Jaccard ≥ 0.2）时，标记 `flaky=true` 并附 `flaky_reason`。方向只从 description 提取，避免 suggestion 里“改为更粗”误导。
10. **门控汇总**：`actionable_counts` 统计非 flaky、有文字、非信息项的 issue（含第 7/8 步生成的确定性 issue）；低严重度的缩放/长宽比提示（`aspect ratio`、`scaled, not warped`）不计入 `actionable_counts`。`must_repair = high>0 or medium>0 or low>=2`。
11. **缓存**：以渲染 PNG 的 SHA-256 为键缓存报告；repair 后渲染完全一致时直接复用，不消耗视觉调用，报告标记 `cached_from_version`。
12. **写回与 best**：
    - `attach_critic` 追加到 `critic_reports`，并写入该版本 `critic_report` / `critic_score`；
    - `update_best()` 在已评分版本中按 **高/中危问题数少 → `checklist_score` 高 → `assessment_score` 高 → 版本新** 排序（旧报告缺字段时分别回退为直接数 issue / -1）；
    - 结果返回 Supervisor：`assessment_score`、verdict、issues[:8]、`checks_pending`、`checklist_score`、`actionable_counts`、`flaky_count`、`must_repair`、labels、`best_version`、`cached`。
13. **闭环**：repair 时 TikZ Agent 自动读取 `latest_version().critic_report.issues`，放入 `CRITIC ISSUES`；issue 中的 object_ids/bbox 可用于定位。

### 4.6 Finish

`finish(status=success|partial|blocked, summary, unresolved)`：

- **门控**（`_finish_gate_problem`）：最新已编译版本未评审、最佳版本未评审、或最佳版本 `must_repair=true` 且预算足够时，首次调用返回 `ok=false`（`finish blocked: ...`），要求先 `run_critic` 或 repair；同一类门控只拦一次、整轮最多拦两次，预算不足时不拦，避免死锁。被拒绝的 finish 不会结束 Supervisor 循环（`_stops_run` 只认 `ok=true`）。
- 容错清洗 Provider 偶发的 XML 式参数；
- 写入最终 summary 与 unresolved；
- 状态缺省时按是否存在 `best_version` 判定；
- Runner 在 `finally` 中刷新用量、写 state/trace/result、发出 `done` 事件。

## 5. 状态与产物

### 5.1 GES（Geometric Evidence State）

Pydantic 模型（`geoagent/state/schemas.py`）持久化：

- 图像路径/尺寸；
- objects / relations / evidence / conflicts / label_bindings / unresolved；
- `tikz_versions`（tex、编译产物、错误、Critic 报告与分数）；
- compilation_results / validation_results / critic_reports；
- action_history / token_usage / remaining_budget / meta。

### 5.2 运行目录

```
outputs/runs/<timestamp>_<stem>/        （成功归档后删除）
├── state.json / result.json / trace.json
├── events.jsonl / llm_calls.jsonl
├── checkpoints/step_NNN.json
├── cv/                                 # CV 可视化
├── crops/                              # 视觉裁剪
├── critic/compare_vN.png               # 内容等尺度对比图
├── tikz/vN/vN.tex|pdf|png
└── renders/
```

### 5.3 归档（`geoagent/archive.py`）

仅当存在 `best_version` 且未加 `--no-archive` 时执行：

```
outputs/ours/
├── stem/<stem>/
│   ├── best.tex / best.pdf / best.png
│   ├── result.json / state.json / critic_report.json
│   └── events.jsonl / llm_calls.jsonl
├── image/<stem>.png        # best.png 的评测友好镜像
└── latex/<stem>.tex        # best.tex 的评测友好镜像
```

行为与保护：

- 同一 stem 重跑会覆盖旧产物，并用最佳版本的 Critic 报告覆盖 `critic_report.json`（无报告则删除旧文件）；
- `result.json` 中的 `run_dir` / `state_path` / `best_tex_path` / `best_png_path` 改写为归档路径；
- 删除临时目录前检查：必须已产出 best 产物；不得是归档目录本身、项目根、`data/` 下目录；
- 失败或未归档的运行保留原目录便于排查。

### 5.4 日志字段

- `events.jsonl`：`step`（预算）、`supervisor_reply`（tool_calls/text）、`action`（耗时/token 增量/视觉增量/错误）、`done`；
- `llm_calls.jsonl`：tag、model、finish_reason、has_images、latency、attempt、usage（prompt/completion/total/cached）；
- `result.json`：status、stop_reason、summary、best_version、best_score、产物路径、counts、usage、elapsed。

## 6. 预算、可靠性与安全

| 预算项 | 默认值 |
|---|---|
| `max_steps` | 24 |
| `max_tool_calls` | 48 |
| `max_visual_calls` | 24 |
| `max_total_tokens` | 400,000 |
| `timeout_seconds` | 1,200 |
| `compile_timeout_seconds` | 120 |

- 预算由 GES 实时统计（`remaining_budget`），耗尽即停止；
- 超时按墙钟时间判断；token 按 Provider 返回值累计；
- 编译安全扫描先于执行；编译器在临时目录运行；
- 日志不写 API Key；`.env` 只读取，不打印。

### 参考隔离

- `scan_dataset` 默认不返回参考 tex；
- Agent 提示词与工具回复中没有任何参考路径；
- 运行期没有任何工具读取 `data/test/latex`；
- 参考只用于开发期编译器冒烟验证和 Demo 结束后的“参考”标签页人工对照。

## 7. 当前验证状态

- 测试：`python -m pytest tests -q` → **103 passed, 1 skipped**（在线 E2E 默认跳过）。
  覆盖：数据集配对（含前导逗号文件名归一化）、GES、CV 结果入库、CV 真实输出、直角标记合成回归、圆心圆点与字母分离（按形状而非面积）、Critic 等尺寸对比图、Critic 问题定位与门控（object_ids/bbox、flaky 反向结论、单/双 low 阈值、长宽比信息项）、Critic 清单（结构对象优先、非法 id 丢弃、missing/wrong 生成确定性 issue、unclear 不计分、与 VLM issue 去重）、源码标签核对（撇号/`^{\prime}` 归一化、数学命令不误报、必须由 VLM `labels.missing` 佐证、空 tex 跳过、6220 的 G/U 误读不产生幽灵 issue）、最佳版本按高/中危问题数与 `checklist_score` 排序、finish 门控与预算兜底、归档与重跑覆盖、渲染画布按原图墨迹框对齐（`frame_like_original`）、CV 风格度量换算（线宽/字号）、Critic 对比图按内容归一化、LLM 截断保护（`finish_reason=length` 双倍预算重试一次、仍截断报错；Critic 空评审报错而非记 0 分）、视觉指标（1000px 白画布 SSIM、余弦、白底合成）、Tectonic 编译/渲染/校验、shell-escape 拒绝、几何提交截断/空提交、TikZ 完整文档、Streamlit 页面。
- 100 张全量运行（**当前 Critic 协议**：等尺寸对比图 + GES 清单 + 源码标签核对）。

  **100 张全量运行（归档 `outputs/ours100/`，合并报告 `outputs/final100/report.json`）**

  | 指标 | 结果 |
  |---|---|
  | 运行数 | 100（92 `success` / 8 `partial`） |
  | 有最佳版本 | 100 / 100 |
  | `assessment_score` | 均值 0.916，中位数 0.92，范围 0.80–0.96；92 张 ≥0.90 |
  | `checklist_score` | 均值 0.996，中位数 1.000，7 张 <1（最低 0.850；基于 99 份归档报告） |
  | `checks` 数量 | 8–24，平均 21.1（99 张） |
  | 收尾时 `must_repair=true` | 9 张（8 `partial` + 1 `success`） |
  | 含 `flaky` 问题 | 4 张 |
  | token / 耗时 / 视觉调用 | 平均 136k / 116s（中位数 112s）/ 5.37 次每图 |
  | `best_version` 分布 | v1 43 / v2 31 / v3 22 / v4 1 / v5 1 / v6 1 / v7 1 |

  - 8 张 `partial`：1258、1625、295、6211、6987、6992、7107、766；均有可编译最佳版本，仅收尾时仍满足 `must_repair`。
  - 1 张 `success` 但收尾 `must_repair=true`：50_q_fig1；最佳版本未被更差的后续修复覆盖。
  - 99 份归档报告共 72 条非 `flaky` issue（68 low / 4 medium），`source=vlm` 70 条、`source=checklist` 2 条；`flaky` 出现在 1270、3379、6961_q_fig2、7016。
  - 100/100 渲染图经 `frame_like_original` 对齐后像素尺寸与原图一致。
  - 6987_q_fig1：原图 A–E–C 在 E 处有真实折角；归档采用第一次重跑结果（0.85 `partial`），`best.*` 由其 TeX 重编译恢复，辅助日志移存 `stem/6987_q_fig1/superseded_rerun/`，故 checklist/checks/问题统计基于其余 99 张。

- 三项视觉指标（TriGeoBench 附录 C.2，100/100 配对）：

| 指标 | 结果 |
|---|---|
| SSIM | **0.938569**（93.86，越高越好） |
| CLIP | **0.990857**（99.09，越高越好） |
| DINO | **0.987429**（98.74，越高越好） |

  逐图数据：`outputs/metrics/ours100.json`。协议：SSIM 为 1000px 白画布整图（LANCZOS，灰度，`gaussian_weights=True, sigma=1.5, win_size=11`）；CLIP 为 OpenAI ViT-L/14@224 视觉投影余弦；DINO 为 `facebook/dinov2-base` CLS（slow processor，短边 256 → 中心裁剪 224）余弦。权重均做 SHA-256 校验。

## 8. 已知边界与后续方向

1. **Critic 仍是启发式**：`checklist_score` 与源码标签核对是确定性的，但 `present/missing/wrong/unclear` 与布局/风格类 issue 仍来自 VLM，不是 SSIM/对象级 F1；整图 `assessment_score` 仍会在 0.90–0.96 饱和，发布判断应看 `actionable_counts`/`must_repair`/`checklist_score`。清单覆盖的是 GES 对象，CV 幻觉对象可能进入清单，靠“missing 指原图可见”的语义约束。下一步可对渲染图做轻量 CV 交叉验证（标签 OCR、线宽/弧覆盖）来佐证 VLM 状态。
2. **线宽/字号**：已由 `measure_style_metrics` 实测并按 8 单元尺度折算，但全图只取一个中位笔画宽度；主轮廓与辅助虚线粗细不同时无法逐元素区分，可扩展为按对象估计。
3. **虚线识别**：基于 gap 游程，交叉与文字遮挡可能误判。
4. **标签识别**：依赖 cmmi10/cmr10 单字符模板；被线条裁掉一部分的字母可能丢失；低分返回 `?` 由视觉复核兜底。
5. **直角标记**：宁可漏画不误画；已支持 ROI 小图（整图取线证据）与虚线臂回退，极端遮挡/极小标记仍可能漏检。
6. **评测接入**：整图 SSIM/CLIP/DINO 已接入（`scripts/evaluate_visual.py`，见第 7 节）；对象级 F1、标签准确率与按图类型分层统计尚未实现，`configs/evaluation/core100.json` 目前只登记清单与 SHA-256，尚无脚本消费。
7. **批处理**：`main.py batch` 单进程顺序执行；全量评测通过多个 `--only` 分片进程并行完成，CLI 本身尚无并发调度。

## 9. 运行方式

```powershell
python main.py check-env
python main.py run --image data/test/image/1035_q_fig1.png
python main.py batch --limit 5 --out-dir outputs/batch --report outputs/batch/report.json
python main.py batch --only <stem...> --archive-dir outputs/ours100 --report outputs/final100/report.json
python scripts/evaluate_visual.py --pred-dir outputs/ours100/image --ref-dir data/test/image --out outputs/metrics/ours100.json
python -m streamlit run app.py
```

更完整的命令、参数与 Demo 说明见 `README.md`。
