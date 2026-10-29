# GeoAgent · 几何图形到可编译 TikZ

GeoAgent 是一个以 **Supervisor 为中心的多智能体系统**：输入一张平面几何图形（TriGeoBench 测试图或上传图片），输出一份可被 LaTeX 实际编译的 TikZ 源码，并渲染回图片用于对照。

- 模型：`claude-haiku-5-5`（OpenAI 兼容接口，通过 `.env` 配置）
- 编译器：Tectonic 0.17.0（本地 `tool/tectonic/tectonic.exe`）
- 数据集：`data/test/image/*.png` + `data/test/latex/*.tex`，当前 100 组配对
- 重试/预算/证据/轨迹全部落盘，参考 LaTeX 在运行期间对 Agent 完全隔离

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
```

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
- 建议流程（Prompt 中给出，但由模型按证据自行决定）：`detect_circles`/`detect_lines` → `bind_point_labels` → `run_geometry_agent` → `run_tikz_agent(generate)` → `run_critic` → 如有具体问题则 `run_tikz_agent(repair)` → 再 `run_critic` → `finish`。
- 预算是硬约束：最大步数、工具调用数、视觉调用数、总 token、总超时；耗尽即停止。
- 图像通过 `inspect_image` 以用户消息附件形式注入（tool 消息不能携带图片），视觉调用计入预算。

### 2.2 三个子 Agent

| Agent | 职责 | 输入 | 输出 |
|---|---|---|---|
| Geometry | 运行必要 CV 工具，合并/推断对象与关系 | GES 摘要 + 指令 | `submit_geometry` JSON |
| TikZ | 生成或整体修复 standalone 文档 | GES 摘要、上一版 tex、编译错误、Critic 问题 | `submit_tikz` 完整源码 |
| Critic | 对比原图与渲染图，定位具体差异 | 两张图片 | JSON：0–1 启发式分数 + issues |

几何 Agent 的回复若因 `max_tokens` 被截断，不会被当作提交；会收到“压缩后重新提交”的提示，最后一轮强制 `tool_choice=submit_geometry`。

### 2.3 CV 工具（真实算法，无伪造）

| 工具 | 方法要点 |
|---|---|
| `detect_lines` | 形态学骨架 + 概率 Hough + 合并共线 + 实线/虚线判定 |
| `analyze_line_style` | 沿中心线采样，统计 ink support / gap 游程，区分 solid/dashed/dotted |
| `detect_circles` | RANSAC 圆拟合 + 角度分箱 ink coverage，得到可见圆弧范围 |
| `fit_arcs` / `extract_visible_arc` | 圆弧拟合与角度区间合并（含 0°/360° 环绕） |
| `detect_right_angle_marker` | 检测直角小方块标记（保守验证，未验证不宣称直角） |
| `separate_text_and_lines` | 按连通域尺寸/笔画宽度分离文字与长线 |
| `extract_label_candidates` | 字母连通域分组（修复 M/N 粘连、O 被割裂） |
| `match_label_templates` | cmmi10/cmr10 字形模板 NCC 匹配，多候选时标记 ambiguous |
| `bind_point_labels` | 由线段顶点推导点集 + Hungarian 分配字母到点 |

### 2.4 GES（Geometric Evidence State）

Pydantic 模型持久化全部证据与过程：对象、关系、证据、冲突、未决问题、标签绑定、TikZ 版本、编译/校验结果、Critic 报告、动作历史、token 统计、剩余预算。每次动作后写 `state.json` 与 `checkpoints/step_NNN.json`。

### 2.5 编译 / 渲染 / 校验

- `compile_tikz`：先做安全检查（拒绝 `\write18`、`\immediate\write`、`\openout`、`\read`、`\csname`），在 ASCII 临时目录编译，产物复制回运行目录；保留 Tectonic 持久缓存（避免每次重下 ~80 MB bundle）。
- `render_pdf`：PyMuPDF 200 dpi 渲染，并裁掉白边。
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
├── configs/
│   ├── default.json            # 模型与预算默认值
│   └── evaluation/core100.json # 论文评测配置（尚未接入）
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
│   │   └── critic_agent.py     # 双图对比
│   ├── cv_tools/               # 见 2.3
│   ├── state/                  # schemas.py + evidence_store.py
│   ├── orchestration/
│   │   ├── runner.py           # 主循环、动作分发、预算、checkpoint、结果
│   │   └── ingest.py           # CV 结果 → GES 对象/关系/证据
│   ├── tools/                  # compiler.py / renderer.py / verifier.py
│   ├── vision/context.py       # 原图/ROI 裁剪，视觉调用管理
│   └── datasets/trigeobench.py # 数据集扫描与配对
├── scripts/cv_smoke.py         # CV 工具冒烟脚本
├── tests/                      # 47 个通过 + 1 个需显式开启的在线测试
├── outputs/final_5/            # 5 张测试图的最终结果（best.tex/pdf/png + 日志）
│   ├── summary.md
│   └── <stem>/
└── tool/tectonic/              # 本地 TeX 编译器
```

### 运行产物

```
outputs/.../<stem>/
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

---

## 4. 已实现 / 部分实现 / 未实现

### 已实现

- Supervisor 真实 function calling 动态决策；非固定 workflow。
- 三个子 Agent 的真实工具调用与结构化提交。
- 9 个 CV 工具，含直线/圆弧/直角标记/文字分离/标签识别与绑定。
- GES 全量持久化、checkpoint、事件与 LLM 调用日志。
- Tectonic 编译、PDF 渲染、结构/几何校验、安全检查。
- CLI 单图/批量运行与汇总报告。
- Streamlit Demo（选择、预算、运行、五个结果标签页）。
- 单元/集成测试：`python -m pytest tests -q`。
- 5 张测试图两轮真实端到端运行（见第 6 节）。

### 部分实现（可用但有边界）

- 虚线识别：基于中心线 gap 游程，交叉/文字遮挡场景可能误判。
- 标签识别：依赖 cmmi10/cmr10 单一字符模板；多字符下标、手写体、特殊字体可能 ambiguous。
- 标签放置：TikZ Agent 依赖 Critic 反馈迭代修正，个别图存在轻微偏移。
- 直角标记：只画验证通过的方块标记，宁可漏画不误画。
- Critic 分数是启发式相似度，不是校准概率。
- 线宽统一使用 `1.2pt`，与个别原图的线宽比例略有出入。

### 未实现

- 论文评测指标（SSIM/对象级 F1 等）与 `configs/evaluation/core100.json` 的接入。
- 批量并发（当前顺序执行）。
- 多页文档、含中文/复杂标注的图。
- 视觉编码器对比实验（`configs/visual-encoders/*` 未接入）。

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

### 6.2 单元/集成测试

```powershell
python -m pytest tests -q
# 47 passed, 1 skipped（在线 E2E 默认跳过）
```

覆盖：模块导入、数据集配对、GES 持久化、CV 结果入库、CV 工具真实输出（1035：4 条实线、半圆弧、6 个标签）、Tectonic 实际编译+渲染+校验、shell-escape 拒绝、几何提交校验、截断保护、Streamlit 初始页与结果页。

可选在线 E2E：

```powershell
$env:GEOAGENT_LIVE=1
python -m pytest tests/test_e2e_live.py -q
```

### 6.3 第一轮 5 图（中间运行，已清理）

| 图片 | 状态 | 最佳版本 | Critic | 耗时 | tokens | 视觉调用 |
|---|---|---|---|---|---|---|
| 1035_q_fig1 | success | v1 | 0.96 | 97.4s | 72,789 | 1 |
| 1238_q_fig1 | success | v3 | 0.93 | 91.6s | 129,929 | 3 |
| 1250_q_fig1 | success | v1 | 0.95 | 47.3s | 41,669 | 1 |
| 1258_q_fig1 | success | v1 | 0.95 | 118.9s | 61,382 | 1 |
| 1259_s_fig1 | success | v1 | 0.93 | 76.7s | 63,908 | 1 |

观察：1035 的 Geometry Agent 回复触发 4096 输出上限（`finish_reason=length`），截断前缀被误当作提交，合并对象为 0；TikZ 仍能直接从 GES 摘要生成正确图。

### 6.4 调整后第二轮 5 图（最终结果：`outputs/final_5`）

调整内容：

1. Geometry Agent `max_tokens` 4096 → 8192；`finish_reason=length` 的回复一律不接受，提示“压缩后立即提交”；最后一轮强制 `tool_choice=submit_geometry`；只有包含 `objects` 键的 JSON 才可作为文本提交。
2. TikZ 提示词要求 `line width=1.2pt, line join=round`，缓解渲染线过细的问题。
3. `finish` 参数容错：兼容 Provider 偶发的 XML 式 tool 参数，清洗摘要并恢复 `unresolved` 列表。

最终产物已归档到 `outputs/final_5/`（每图保留 `best.tex/pdf/png`、`result.json`、`state.json`、`critic_report.json`、`events.jsonl`、`llm_calls.jsonl`），中间运行目录（batch、checkpoints、crops、CV 缓存等）已清理。

| 图片 | 状态 | 最佳版本 | Critic | 耗时 | tokens | 视觉调用 | Geometry 合并 |
|---|---|---|---|---|---|---|---|
| 1035_q_fig1 | success | v1 | 0.95 | 105.7s | 75,402 | 1 | 12 obj / 14 rel |
| 1238_q_fig1 | success | v1 | 0.93 | 39.9s | 48,477 | 1 | 未调用（简单图） |
| 1250_q_fig1 | success | v1 | 0.93 | 68.8s | 66,154 | 1 | 9 obj / 9 rel |
| 1258_q_fig1 | success | v2 | 0.96 | 81.4s | 72,186 | 2 | 未调用（修复后达标） |
| 1259_s_fig1 | success | v1 | 0.95 | 86.3s | 70,557 | 1 | 10 obj / 3 rel |

第二轮全部成功，平均 Critic 0.944，平均 66.6k tokens/图。几何合并问题已修复；1258 经一次修复从 0.93 提升到 0.96。

Demo 验证：`streamlit run app.py` 健康检查返回 `ok`，`AppTest` 无异常；侧栏 100 个样本、5 个结果标签页、TikZ 下载按钮均正常。

---

## 7. 下一阶段建议

1. 接入 `configs/evaluation/core100.json` 的离线评测（渲染相似度 + 结构/对象级指标），对 100 张图做分层统计。
2. 增加线宽感知：在 `analyze_line_style` 中估计笔画宽度，让 TikZ Agent 按原图比例选择 `line width`。
3. 扩展标签模板库（多字符、下标、希腊字母），并输出匹配置信度分布。
4. 支持失败样本的自动重试策略（不同随机种子/温度、定向修复）。
5. 批处理并发与缓存（相同图片的 CV 结果复用）。
6. 在真实浏览器中补充端到端 UI 点击回归（当前使用 Streamlit AppTest + HTTP 健康检查）。
