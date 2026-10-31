# GeoAgent · 几何图形到可编译 TikZ

GeoAgent 是一个以 **Supervisor 为中心的多智能体系统**：输入一张平面几何图形（TriGeoBench 测试图或上传图片），输出一份可被 LaTeX 实际编译的 TikZ 源码，并渲染回图片用于对照。

- 模型：`claude-haiku-5-5`（OpenAI 兼容接口，通过 `.env` 配置）
- 编译器：Tectonic 0.17.0（本地 `tool/tectonic/tectonic.exe`）
- 数据集：`data/test/image/*.png` + `data/test/latex/*.tex`，当前 100 组配对
- 重试/预算/证据/轨迹全部落盘，参考 LaTeX 在运行期间对 Agent 完全隔离
- 当前完整流水线说明见 [`docs/pipeline.md`](docs/pipeline.md)

---

## 1. 环境与启动

### 1.1 安装

```powershell
cd D:\Users\18217\Desktop\我的文件\GeoAgent

# 建议使用虚拟环境（可选）
python -m venv .venv
.\.venv\Scripts\Activate.ps1

python -m pip install -r requirements.txt
```

### 1.2 配置 `.env`

`.env` 已存在，变量名如下（**不要把真实 Key 写入仓库**）：

```dotenv
OPENAI_API_KEY=...                 # 仅存在于本机 .env
OPENAI_BASE_URL=https://api.gpt.ge/v1
# 可选覆盖：
# GEOAGENT_MODEL=claude-haiku-5-5
# GEOAGENT_MAX_STEPS=24
# GEOAGENT_MAX_VISUAL_CALLS=24
# GEOAGENT_MAX_TOTAL_TOKENS=400000
# GEOAGENT_TECTONIC=D:\...\tectonic.exe
# GEOAGENT_COMPILE_TIMEOUT=120
```

模型、预算、路径的默认值见 `configs/default.json` 与 `geoagent/config.py`。

### 1.3 检查环境

```powershell
python main.py check-env
```

会检查：模型名 / Base URL / Key 是否存在（不打印 Key）、TeX 编译器、数据集配对数量、核心依赖。

### 1.4 运行

```powershell
# 列出数据集样本
python main.py list

# 单张图片端到端运行（实时打印事件流）
python main.py run --image data/test/image/1035_q_fig1.png

# 自定义预算
python main.py run --image data/test/image/1035_q_fig1.png `
  --max-steps 16 --max-tool-calls 32 --max-visual-calls 4 `
  --max-total-tokens 400000 --timeout-seconds 1200

# 批量运行（前 5 张），生成汇总报告
python main.py batch --limit 5 --out-dir outputs/batch --report outputs/batch/report.json

# 只跑指定图片
python main.py batch --only 1035_q_fig1 1258_q_fig1

# 100 张全量运行：按 --only 分片并行，归档并合并报告
python main.py batch --only <stem...> --archive-dir outputs/ours100 --report outputs/final100/report.json

# 三项视觉指标（SSIM / CLIP / DINO）
python scripts/evaluate_visual.py --pred-dir outputs/ours100/image `
  --ref-dir data/test/image --out outputs/metrics/ours100.json
```

成功运行（有最佳版本）结束后自动归档并清理：工作目录（checkpoints、crops、CV 缓存、每个中间 TikZ 版本、渲染缓存）会被删除，只保留最佳产物与日志，统一收进 `--archive-dir`（默认 `outputs/ours`）：

```
outputs/ours/
├── stem/<stem>/                 # 每张图的完整产物
│   ├── best.tex / best.pdf / best.png
│   ├── result.json / state.json / critic_report.json
│   └── events.jsonl / llm_calls.jsonl
├── image/<stem>.png             # 评测友好镜像
└── latex/<stem>.tex
```

未产出最佳版本的失败运行会保留原工作目录以便排查；需要保留中间过程时加 `--no-archive`。

```powershell
python main.py run --image data/test/image/1035_q_fig1.png --archive-dir outputs/ours
python main.py batch --only 1035_q_fig1 --no-archive   # 调试：保留临时目录
```

Streamlit Demo 不走这条清理逻辑：结果标签页需要读取 `cv/` 叠加图与各中间 TikZ 版本，因此工作目录会保留。

### 1.5 Streamlit Demo

```powershell
python -m streamlit run app.py
```

默认打开 <http://localhost:8501>。页面功能：

- 左侧：测试集/上传选择、预算设置、开始与清空；
- `图像与 CV`：原图 + 各 CV 工具叠加图；
- `TikZ`：版本切换、源码/渲染图下载、编译错误、Critic 报告；
- `Agent 轨迹`：每步动作、耗时、token 增量、视觉调用、LLM 调用明细、原始事件日志；
- `GES`：对象、关系、标签绑定、冲突、未决问题、证据；
- `参考`：运行结束后人工对照参考 LaTeX（运行期间任何 Agent 都看不到）。

### 1.6 e2e 基线（无 Critic 单次生成）

`scripts/run_e2e.py` 迁移自 geom2code 的 e2e 方法：原图（原始 PNG，不缩放）一次性送入多模态模型，`temperature=0`、`max_tokens=8192`（GPT-5.x/6.x 改用 `max_completion_tokens` + `--reasoning-effort`）；回复直接写入 TikZ 并调用本地 Tectonic 编译为 PNG，无 Critic、无修复、无按质量重采样。唯一的重试是回复与已归档 TeX 完全相同或编译失败时按 `--attempts` 重新请求（默认 3 次，成功即停止，否则保留最后一次回复）。`--out-root` 只产生 `latex/` 与 `image/`；轨迹、批量汇总与覆盖备份写入 `--log-root`（默认 `outputs/scratch/e2e/<baseline 名>`）。

```powershell
# 只补缺失的图（已有 PNG 的自动跳过）
python scripts/run_e2e.py --out-root outputs/baselines/haiku-5.5 --missing-only

# 指定若干张；覆盖前备份到 backup_before_rerun/（--no-backup 可关闭）
python scripts/run_e2e.py --out-root outputs/baselines/haiku-5.5 `
  --only 1763_s_fig1,2062_s_fig1,295_q_fig1,3477_q_fig1,3692_q_fig1
```

两个 e2e 基线与 ours 的三项视觉指标见 6.3。

---

## 2. 架构

```
                 ┌──────────────────────────────┐
   图像 ────────►│ Supervisor (function calling) │◄──── 预算 / 超时 / 轨迹
                 └───────┬───────────┬───────────┘
         一次一步，只执行首个 tool call，其余显式忽略
        ┌────────────────┼───────────────────────────────┐
        ▼                ▼               ▼               ▼
   call_cv_tool     Geometry Agent   TikZ Agent      Critic Agent
   (本地 CV 算法)    (可再调 CV，       (生成/修复)     (原图 vs 渲染图)
                     提交统一几何)
        │                │               │               │
        └────────► ingest_cv_result ◄────┴───────────────┘
                          │
                    GES (Pydantic)
        objects / relations / evidence / conflicts / label_bindings
        tikz_versions / compilations / validations / critic_reports
        action_history / token_usage / checkpoints
                          │
                 compile_tikz → render_pdf → validate_compilation
```

### 2.1 Supervisor 循环

- 使用 OpenAI function calling，每轮只执行一个动作；额外的并行 tool call 会被拒绝并记录（“one action per step”）。
- 建议流程（Prompt 中给出，但由模型按证据自行决定）：`detect_circles`/`detect_lines` → `bind_point_labels` → `run_geometry_agent` → `run_tikz_agent(generate)` → `run_critic` → 若 `must_repair=true` 则 `run_tikz_agent(repair)` → 再 `run_critic` → `finish`。标记为 `flaky` 的问题（与上一版方向相反，如“太粗”→“太细”）不驱动修复；低严重度的缩放/长宽比提示视为信息项；`source=checklist/tikz_source_check` 的确定性 issue 与 VLM issue 同等对待。
- 预算是硬约束：最大步数、工具调用数、视觉调用数、总 token、总超时；耗尽即停止。
- 图像通过 `inspect_image` 以用户消息附件形式注入（tool 消息不能携带图片），视觉调用计入预算。

### 2.2 三个子 Agent

| Agent | 职责 | 输入 | 输出 |
|---|---|---|---|
| Geometry | 运行必要 CV 工具，合并/推断对象与关系 | GES 摘要 + 指令 | `submit_geometry` JSON |
| TikZ | 生成或整体修复 standalone 文档 | GES 摘要、上一版 tex、编译错误、Critic 问题 | `submit_tikz` 完整源码 |
| Critic | 对比原图与渲染图，定位具体差异 | 内容等尺度左右对比图 + GES 摘要 + 对象清单 | JSON：启发式分数 + issues（object_ids/bbox）+ `checks` + `must_repair` |

生成 TikZ 前，`measure_style_metrics` 从原图实测笔画宽度与字母 cap height，并按“绘制图最长边 8 cm”换算成 `line width`（pt）和标签 `\fontsize`，作为 STYLE METRICS 随指令注入 TikZ Agent；坐标尺度也用同一换算，保证线宽/字号与原图的相对比例一致，而不是固定 1.2pt / 默认 10pt。

同一位置还有一次确定性的直角正交化：原图与参考 LaTeX 严格对应，因此 CV 验证到方块墨迹的直角，其两条入射边在真实图中必然精确垂直。`rectify_right_angles` 以线段端点与直角顶点为节点做联合最小二乘（带位移闸门、初值角门与幂等），把坐标校到 90° 后写回 GES（`notes` / `evidence` / `meta["rectification"]`），再交给 TikZ Agent，避免把 1–3 px 的检测噪声带进渲染。

Critic 不会直接发两张不同分辨率的图：`build_comparison_image` 先把原图（左）与渲染图（右）各自裁剪到墨迹包围盒（排除不等量白边），再等比缩放到同一内容框（面板的 90%）并居中，中间留 12px 分隔，拼成一张 1252×620 的对比图（默认 `image_max_dim=1280` 内，不会再被二次缩放）。按“内容”而不是“画布”归一化后，两图的线宽、字号、比例可以直接比较，不会因原图留白多而把渲染图放大。没有 `out_dir` 时回退为发送两张独立图片。

每条 issue 会带 GES 对象 id 与归一化 bbox，便于 repair 定位。若同一元素的方向性风格结论与上一版相反（v1“太粗”、v2“太细”），该条标记为 `flaky`，不计入修复门控；低严重度的缩放/长宽比提示不计入 `actionable_counts`。报告汇总出 `actionable_counts` 与 `must_repair`（任一 high/medium，或 ≥2 条 low）。`finish` 在“最新渲染未评审 / 最佳版本未评审 / `must_repair=true`”且预算允许时会被拒绝一次。相同渲染图按 SHA-256 复用上一次报告，不再消耗视觉调用；最佳版本排序为“高/中危问题数少 → `checklist_score` 高 → `assessment_score` 高 → 版本新”。

**清单化评审**：`_build_checklist` 从 GES 生成最多 24 项核对清单（线段/圆弧/圆/直线优先，带标签的点其次，跳过 rejected、无标签点和 `label` 对象），随对比图一起发给 Critic，要求每个 id 返回 `present/missing/wrong/unclear`。`missing` 的语义是“原图可见、渲染缺失”，避免把 CV 幻觉对象当成漏画。`checklist_score = (present·1 + wrong·0.5) / 非 unclear 项数`，是确定性聚合，不依赖整体印象分。VLM 未点名的 missing/wrong 会生成 `source=checklist` 的 issue（结构元素 missing=high、点 missing=medium、wrong=low），bbox 由对象像素坐标换算；与 VLM issue 按 object_ids 去重。

**源码标签核对**：从 `label_bindings` 与对象标签收集期望的单字母标签（可带撇号），扫描 tex 的 `$...$` / `\(...\)` 并归一化 `'` 与 `^{\prime}`。该检查**只在 VLM 已把该标签列入 `labels.missing` 时才生成 `source=tikz_source_check` 的 issue**：CV 字形 OCR 会把 `G` 误读成 `U`（6220 实测），仅凭 CV 绑定去补标签会“补出幽灵标签”。因此它起确认与提升严重度的作用，不凭单侧证据制造 issue。

几何 Agent 的回复若因 `max_tokens` 被截断，不会被当作提交；会收到“压缩后重新提交”的提示，最后一轮强制 `tool_choice=submit_geometry`。

**术语约定（全文档统一）**

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

### 2.3 CV 工具（真实算法，无伪造）

| 工具 | 方法要点 |
|---|---|
| `detect_lines` | 形态学骨架 + 概率 Hough + 合并共线 + 实线/虚线判定；Hough 断在圆弧抑制带时按剩余墨迹沿法向回补跨度（保留越过顶点的外伸），虚线链在去字形掩膜上重建 |
| `analyze_line_style` | 沿中心线采样，统计 ink support / gap 游程，区分 solid/dashed/dotted |
| `detect_circles` | RANSAC 圆拟合 + 角度分箱 ink coverage，得到可见圆弧范围；低覆盖且无长连续可见区间的拟合判为不可靠证据（不参与弧蚀刻与点推导） |
| `fit_arcs` / `extract_visible_arc` | 圆弧拟合与角度区间合并（含 0°/360° 环绕） |
| `detect_right_angle_marker` | 检测直角小方块标记：长边垂直对 + 擦除长边后的独立方块墨迹验证；虚线臂不构成长边时退回短笔画配对，并要求方块两臂在交点外侧继续延伸（避免把 L 形笔画误判为直角）；给定 ROI 时仍在整图检测长边证据，ROI 只限制候选顶点报告范围 |
| `separate_text_and_lines` | 按连通域尺寸/笔画宽度分离文字与长线 |
| `extract_label_candidates` | 字母连通域分组（修复 M/N 粘连、O 被割裂；按字形连通域估 cap height，过滤虚线碎片）；圆心圆点按“紧凑、近方、实心”形状先与字母分离，再取字母包围盒 |
| `match_label_templates` | cmmi10/cmr10 字形模板 NCC 匹配；低分（<0.45）返回 `?`，支持 C→C' 撇号检测 |
| `bind_point_labels` | 由线段顶点推导点集 + Hungarian 分配字母到点 |

### 2.4 GES（Geometric Evidence State）

Pydantic 模型持久化全部证据与过程：对象、关系、证据、冲突、未决问题、标签绑定、TikZ 版本、编译/校验结果、Critic 报告、动作历史、token 统计、剩余预算。每次动作后写 `state.json` 与 `checkpoints/step_NNN.json`。

### 2.5 编译 / 渲染 / 校验

- `compile_tikz`：先做安全检查（拒绝 `\write18`、`\immediate\write`、`\openout`、`\read`、`\csname`），在 ASCII 临时目录编译，产物复制回运行目录；保留 Tectonic 持久缓存（避免每次重下 ~80 MB bundle）。
- `render_pdf`：PyMuPDF 200 dpi 渲染，并裁掉白边。
- `frame_like_original`：把渲染图的墨迹框等比缩放、对齐到原图的墨迹框，输出与原图同尺寸、同内容占比的画布，使 Critic 与整图指标在相同留白下比较（校验仍针对重框前的原始渲染）。
- `validate_compilation`：documentclass / 环境配对 / 无 shell escape / 编译成功 / PDF+PNG 存在 / 非空白 / 长宽比 / 图形占幅。

---

## 3. 项目结构（实际文件）

```
GeoAgent/
├── main.py                     # check-env / list / run / batch CLI
├── app.py                      # Streamlit Demo（5 个标签页）
├── pyproject.toml              # 元数据 + pytest 配置
├── requirements.txt            # 运行依赖
├── .env.example                # 变量名说明（不含真实 Key）
├── docs/
│   ├── init.md                 # 初始需求
│   └── pipeline.md             # 当前实现的完整流水线说明
├── configs/
│   ├── default.json            # 模型与预算默认值
│   ├── evaluation/core100.json # 论文评测配置（100 图清单与 SHA-256）
│   └── visual-encoders/        # CLIP ViT-L/14、DINOv2-base 权重登记（含 SHA-256）
├── data/test/{image,latex}/    # TriGeoBench 100 组图-参考对
├── geoagent/
│   ├── config.py               # .env + JSON 配置
│   ├── llm/client.py           # 重试/退避、图片编码缓存、token 统计、JSON 校验
│   ├── agents/
│   │   ├── schemas.py          # Supervisor / 子 Agent 的 function schema
│   │   ├── prompts.py          # 四类系统提示词
│   │   ├── base.py             # 消息/工具回复/CV 结果压缩
│   │   ├── supervisor.py       # 初始消息与步进提示
│   │   ├── geometry_agent.py   # 提交合并 + 截断保护
│   │   ├── tikz_agent.py       # 生成/修复
│   │   └── critic_agent.py     # 清单评审 + 等尺寸对比 + 确定性检查
│   ├── cv_tools/               # 见 2.3
│   ├── state/                  # schemas.py + evidence_store.py + rectify.py（直角正交化）
│   ├── orchestration/
│   │   ├── runner.py           # 主循环、动作分发、预算、checkpoint、结果
│   │   └── ingest.py           # CV 结果 → GES 对象/关系/证据
│   ├── tools/                  # compiler.py / renderer.py / verifier.py
│   ├── vision/context.py       # 原图/ROI 裁剪，视觉调用管理
│   ├── archive.py              # 成功运行归档（stem/<stem>/ + image/latex 镜像）并删除临时目录
│   ├── evaluation/visual_metrics.py # SSIM / CLIP / DINO（论文附录 C.2 协议）
│   └── datasets/trigeobench.py # 数据集扫描与配对
├── scripts/
│   ├── cv_smoke.py             # CV 工具冒烟脚本
│   ├── evaluate_visual.py      # 三项视觉指标 CLI
│   ├── compare_e2e_visual.py   # 多组 e2e 基线共享有效集对比
│   └── run_e2e.py              # e2e 单次生成基线（迁移自 geom2code）
├── tests/                      # 113 个通过 + 1 个需显式开启的在线测试
├── outputs/ours100/            # 100 张全量结果：stem/<stem>/、image/、latex/
├── outputs/final100/report.json # 100 次运行的合并报告
├── outputs/metrics/ours100.json # 三项视觉指标逐图与汇总
├── outputs/baselines/haiku-5.5/ # e2e 单次生成基线（仅 image/latex，各 100）
├── outputs/baselines/gpt-5.4/  # e2e 单次生成基线（仅 image/latex，各 100）
├── outputs/metrics/e2e-compare.json # 两组基线的三项视觉指标对比
└── tool/tectonic/              # 本地 TeX 编译器
```

### 运行产物

运行中的临时工作目录（成功归档后删除，失败/`--no-archive` 时保留）：

```
outputs/runs/<timestamp>_<stem>/   (或 --out-dir/<stem>)
├── state.json                  # 最终 GES
├── result.json                 # 状态/最佳版本/分数/用量/摘要
├── checkpoints/step_NNN.json
├── events.jsonl                # 事件流（step/action/supervisor_reply/done）
├── llm_calls.jsonl             # 每次调用的 tag/tokens/latency/finish_reason
├── cv/                         # CV 可视化 PNG 与字形缓存
├── crops/                      # 视觉 ROI
├── tikz/vN/vN.tex|pdf|png
└── renders/
```

成功运行归档后的形态见 1.4：每张图的完整产物在 `<archive-dir>/stem/<stem>/`（`best.tex|pdf|png`、`result.json`、`state.json`、`critic_report.json` 与两份 JSONL 日志），另有 `image/<stem>.png`、`latex/<stem>.tex` 两个评测友好镜像目录。当前 `outputs/ours100/` 保存 100 张全量运行，每张 8 个文件；重复运行同一 stem 时会覆盖旧产物与旧 Critic 报告。个别手工恢复的 stem（6987_q_fig1）额外带有 `RESTORE_NOTE.md` 与 `superseded_rerun/`。

---

## 4. 已实现 / 部分实现 / 未实现

### 已实现

- Supervisor 真实 function calling 动态决策；非固定 workflow。
- 三个子 Agent 的真实工具调用与结构化提交。
- 9 个 CV 工具，含直线/圆弧/直角标记/文字分离/标签识别与绑定。
- GES 全量持久化、checkpoint、事件与 LLM 调用日志。
- Tectonic 编译、PDF 渲染、结构/几何校验、安全检查。
- CLI 单图/批量运行与汇总报告；成功运行自动归档到 `outputs/ours` 并删除临时工作目录（`--no-archive` 可关闭）。
- Streamlit Demo（选择、预算、运行、五个结果标签页）。
- 单元/集成测试：`python -m pytest tests -q`。
- 100 张测试图真实端到端运行，100/100 产出可编译最佳版本。
- 论文附录 C.2 的三项整图视觉指标（SSIM / CLIP / DINO）已实现并在 100 张图上完整评测（见 6.3）。

### 部分实现（可用但有边界）

- 虚线识别：基于中心线 gap 游程，交叉/文字遮挡场景可能误判。
- 标签识别：依赖 cmmi10/cmr10 单一字符模板；被线条裁掉一部分的字母（如 1266 的 E）可能提取不到，低分时返回 `?` 并由 Supervisor 用 `inspect_image` 复核；多字符下标、手写体、特殊字体仍可能 ambiguous。
- 标签放置：TikZ Agent 依赖 Critic 反馈迭代修正；门控只强制处理任一 high/medium 或 ≥2 条 low，单条低严重度偏移（锚点方向、面板缩放提示）仍可能保留。
- 直角标记：只画验证通过的方块标记，宁可漏画不误画；ROI 小图与虚线臂已有回退，极端遮挡/极小标记仍可能漏检。
- Critic 的整图分数仍是启发式相似度，不是校准概率；门控看 `actionable_counts` / `must_repair` / `checklist_score` 而不是总分。`checklist_score` 与源码标签核对是确定性的，但每个对象的 `present/missing/wrong/unclear` 仍来自 VLM。
- 标签 OCR 会误读：6220 的原图 `G` 被 `bind_point_labels` 读成 `U`。因此源码标签核对必须由 VLM `labels.missing` 佐证后才生成 issue，不凭单侧 CV 结论修图。
- 清单来自 GES 对象，CV 幻觉对象也会入列；`missing` 定义为“原图可见但渲染缺失”，用于避免把幻觉对象当成漏画。
- 线宽/字号：已由 CV 实测折算（见 2.2），但全图只取一个中位笔画宽度；同一张图里主轮廓与辅助虚线本来不同粗细时，仍无法逐元素区分。

### 未实现

- 对象级评测指标（对象/关系 F1、标签准确率）与按图类型的分层统计；`configs/evaluation/core100.json` 已登记 100 图清单与 SHA-256，但尚无脚本消费它。
- 批量并发（当前顺序执行）。
- 多页文档、含中文/复杂标注的图。
- 视觉编码器对比实验（当前 CLIP / DINOv2 只用于固定协议打分，没有做多编码器消融）。

---

## 5. 参考隔离保证

- `scan_dataset` 默认 `public()` 不返回参考 tex。
- Agent 提示词中不含参考路径；运行期没有任何工具读取 `data/test/latex`。
- 参考只用于：开发时的编译器冒烟验证、以及 Demo 运行结束后的“参考”标签页人工对照。

---

## 6. 真实验证记录

### 6.1 环境

| 项 | 结果 |
|---|---|
| Python | 3.13.0 |
| 模型 | `claude-haiku-5-5` |
| Base URL | 已配置（Key 存在，未打印） |
| Tectonic | 0.17.0（`tool/tectonic/tectonic.exe`） |
| 数据集 | 100 张图片 / 100 份参考 tex |
| Streamlit | 1.66.1 |
| 评测栈 | torch 2.9.0+cpu / transformers 4.48.3 / OpenAI CLIP ViT-L/14 |

### 6.2 单元/集成测试

```powershell
python -m pytest tests -q
# 113 passed, 1 skipped（在线 E2E 默认跳过）
```

覆盖：模块导入、数据集配对（含前导逗号文件名归一化）、GES 持久化、CV 结果入库、CV 工具真实输出（1035：4 条实线、半圆弧、6 个标签）、直角标记合成回归（虚线臂 + 方块应命中、裸十字不命中）、直角正交化（简单角/矩形链/T 形垂足/端点吸附与顶点合并/假阳性与位移闸门/幂等/点标签跟随与序列化）、圆心圆点与字母分离（按形状而非面积，圆点可大于被割裂的字母块）、Critic 内容等尺度对比图（左右面板等大、原图在左、内容而非画布归一化、单图发送与无 `out_dir` 回退）、Critic 问题定位与门控（object_ids/bbox 保留、反向风格结论标记 flaky、单条 low 不强制修复而两条 low 强制、长宽比提示不计入 `actionable_counts`）、Critic 清单（结构对象优先、非法 id 丢弃、missing/wrong 生成确定性 issue、unclear 不计分、与 VLM issue 去重）、源码标签核对（撇号归一化、字体命令不误报、必须有 VLM missing 佐证、空 tex 跳过、6220 的 G/U 误读不产生幽灵 issue）、最佳版本按高/中危问题数与 `checklist_score` 排序、finish 门控（最新渲染未评审 / 未评审最佳版本 / 仍有 must_repair，且预算不足时不阻塞）、归档（重复运行覆盖旧产物/清理旧 Critic 报告、`data/` 保护）、LLM 截断保护（`finish_reason=length` 双倍预算重试一次、仍截断报错；Critic 空评审报错而不是记 0 分）、视觉指标（1000px 白画布 SSIM、余弦、白底合成）、渲染画布按原图墨迹框对齐（`frame_like_original`）、CV 风格度量换算（线宽/字号）、Tectonic 实际编译+渲染+校验、shell-escape 拒绝、几何提交校验（截断带 tool call / 空提交均被拒）、TikZ 完整文档校验、Streamlit 初始页与结果页。

可选在线 E2E：

```powershell
$env:GEOAGENT_LIVE=1
python -m pytest tests/test_e2e_live.py -q
```

### 6.3 三项视觉指标（TriGeoBench 附录 C.2）

对 100 组图像逐图评测（100/100 配对），协议与 TriGeoBench 实验代码（`geom2code/scripts/whole_visual_protocol.py`）一致：

- **SSIM**：透明图先合成到白底，整图按最长边缩放到 1000px 居中放入 1000×1000 白画布（LANCZOS），转灰度；`skimage` SSIM 使用 `gaussian_weights=True, sigma=1.5, win_size=11, use_sample_covariance=False`，不做裁剪或配准。
- **CLIP**：OpenAI CLIP ViT-L/14@224 视觉投影特征余弦；本地权重 `~/.cache/clip/ViT-L-14.pt`，SHA-256 校验后使用。
- **DINO**：`facebook/dinov2-base` CLS 特征余弦；官方 slow processor（短边 256 → 中心裁剪 224），本地快照，文件 SHA-256 校验。

最终结果（SSIM/CLIP/DINO ×100，越高越好）：

| 方法 | N | SSIM | CLIP | DINO |
| --- | ---: | ---: | ---: | ---: |
| haiku-5.5（e2e 单次生成） | 100 | 90.6932 | 97.4596 | 96.6482 |
| gpt-5.4（e2e 单次生成） | 100 | 90.7124 | 96.9177 | 95.8915 |
| **GeoAgent（ours）** | 100 | **93.8569** | **99.0857** | **98.7429** |

```powershell
# ours
python scripts/evaluate_visual.py `
  --pred-dir outputs/ours100/image --ref-dir data/test/image `
  --out outputs/metrics/ours100.json

# 两个 e2e 基线
python scripts/compare_e2e_visual.py `
  --group haiku-5.5=outputs/baselines/haiku-5.5/image `
  --group gpt-5.4=outputs/baselines/gpt-5.4/image `
  --ref-dir data/test/image --out outputs/metrics/e2e-compare.json
```

逐图数据见 `outputs/metrics/ours100.json` 与 `outputs/metrics/e2e-compare.json`。`assessment_score` 是系统内部的 VLM 启发式控制信号，不是外部指标，不纳入上表。

---

## 7. 下一阶段建议

1. 补齐对象级指标（对象/关系 F1、标签准确率）并按图类型分层统计；整图 SSIM/CLIP/DINO 已接入（见 6.3）。
2. 逐元素线宽：当前按全图中位笔画宽度换算统一 `line width`；可按对象（主轮廓/辅助线/细虚线）分别估计，并让 TikZ Agent 分层设置。
3. 扩展标签模板库（多字符、下标、希腊字母），并输出匹配置信度分布。
4. 支持失败样本的自动重试策略（不同随机种子/温度、定向修复）。
5. 批处理并发与缓存（相同图片的 CV 结果复用）。
6. 在真实浏览器中补充端到端 UI 点击回归（当前使用 Streamlit AppTest + HTTP 健康检查）。
7. 被线条裁断的标签（1266 的 E）：用 `inspect_image` 对未绑定点的邻域 ROI 做定向复核，替代整图视觉调用。
8. 对渲染图做轻量 CV 交叉验证（标签 OCR、笔画宽度、弧覆盖率），为 Critic 的 `checks` 状态提供第二证据源；当前状态仍由 VLM 判断，只有聚合与源码标签核对是确定性的。
