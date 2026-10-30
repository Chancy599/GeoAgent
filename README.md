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
- 建议流程（Prompt 中给出，但由模型按证据自行决定）：`detect_circles`/`detect_lines` → `bind_point_labels` → `run_geometry_agent` → `run_tikz_agent(generate)` → `run_critic` → 如有具体问题则 `run_tikz_agent(repair)` → 再 `run_critic`；若最新 Critic 仍列出具体可修项（含低严重度），预算允许时再做一轮 repair + critic 再 `finish`。
- 预算是硬约束：最大步数、工具调用数、视觉调用数、总 token、总超时；耗尽即停止。
- 图像通过 `inspect_image` 以用户消息附件形式注入（tool 消息不能携带图片），视觉调用计入预算。

### 2.2 三个子 Agent

| Agent | 职责 | 输入 | 输出 |
|---|---|---|---|
| Geometry | 运行必要 CV 工具，合并/推断对象与关系 | GES 摘要 + 指令 | `submit_geometry` JSON |
| TikZ | 生成或整体修复 standalone 文档 | GES 摘要、上一版 tex、编译错误、Critic 问题 | `submit_tikz` 完整源码 |
| Critic | 对比原图与渲染图，定位具体差异 | 等尺寸左右对比图 | JSON：0–1 启发式分数 + issues |

Critic 不会直接发两张不同分辨率的图：`build_comparison_image` 把原图（左）与渲染图（右）各自等比缩放进 620×620 的白色面板并居中，中间留 12px 分隔，拼成一张 1252×620 的对比图（默认 `image_max_dim=1280` 内，不会再被二次缩放）。这样两图按最长边归一化到同一尺度，线宽、字号、比例可以直接比较。没有 `out_dir` 时回退为发送两张独立图片。

几何 Agent 的回复若因 `max_tokens` 被截断，不会被当作提交；会收到“压缩后重新提交”的提示，最后一轮强制 `tool_choice=submit_geometry`。

### 2.3 CV 工具（真实算法，无伪造）

| 工具 | 方法要点 |
|---|---|
| `detect_lines` | 形态学骨架 + 概率 Hough + 合并共线 + 实线/虚线判定 |
| `analyze_line_style` | 沿中心线采样，统计 ink support / gap 游程，区分 solid/dashed/dotted |
| `detect_circles` | RANSAC 圆拟合 + 角度分箱 ink coverage，得到可见圆弧范围 |
| `fit_arcs` / `extract_visible_arc` | 圆弧拟合与角度区间合并（含 0°/360° 环绕） |
| `detect_right_angle_marker` | 检测直角小方块标记：长边垂直对 + 擦除长边后的独立方块墨迹验证；虚线臂不构成长边时退回短笔画配对，并要求方块两臂在交点外侧继续延伸（避免把 L 形笔画误判为直角） |
| `separate_text_and_lines` | 按连通域尺寸/笔画宽度分离文字与长线 |
| `extract_label_candidates` | 字母连通域分组（修复 M/N 粘连、O 被割裂；按字形连通域估 cap height，过滤虚线碎片） |
| `match_label_templates` | cmmi10/cmr10 字形模板 NCC 匹配；低分（<0.45）返回 `?`，支持 C→C' 撇号检测 |
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
│   ├── archive.py              # 成功运行归档到 outputs/ours 并删除临时目录
│   └── datasets/trigeobench.py # 数据集扫描与配对
├── scripts/cv_smoke.py         # CV 工具冒烟脚本
├── tests/                      # 63 个通过 + 1 个需显式开启的在线测试
├── outputs/ours/               # 统一归档目录：stem/<stem>/（best.* + 日志）、image/、latex/ 镜像
├── outputs/final_5/            # 第一轮 5 张测试图的最终结果（best.tex/pdf/png + 日志）
│   ├── summary.md
│   └── <stem>/
├── outputs/edge5/              # 边界样例批次最终结果（5 图 + summary.md）
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

成功运行归档后的形态见 1.4：每张图的完整产物在 `outputs/ours/stem/<stem>/`（`best.tex|pdf|png` 与日志），另有 `outputs/ours/image/<stem>.png`、`outputs/ours/latex/<stem>.tex` 两个评测友好镜像目录。当前 `outputs/ours/` 已整合全部 15 张已处理图（`final_5` 5 张 + `edge5` 5 张 + 第三批 5 张），每张 8 个文件（含 `critic_report.json`）；重复运行同一 stem 时会覆盖旧产物与旧 Critic 报告。

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
- 三批共 15 张测试图真实端到端运行（见第 6 节）。
- 边界样例批次：双圆、内切圆、多弦交点、直角标记、虚线、C' 标签、1080px 大图与异常文件名全部通过（见 6.5）；虚线臂直角标记与细线图已优化（见 6.6）。

### 部分实现（可用但有边界）

- 虚线识别：基于中心线 gap 游程，交叉/文字遮挡场景可能误判。
- 标签识别：依赖 cmmi10/cmr10 单一字符模板；被线条裁掉一部分的字母（如 1266 的 E）可能提取不到，低分时返回 `?` 并由 Supervisor 用 `inspect_image` 复核；多字符下标、手写体、特殊字体仍可能 ambiguous。
- 标签放置：TikZ Agent 依赖 Critic 反馈迭代修正，个别图存在轻微偏移（低严重度时可能不修复，如 1266 的 O/E 偏移）。
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
# 63 passed, 1 skipped（在线 E2E 默认跳过）
```

覆盖：模块导入、数据集配对（含前导逗号文件名归一化）、GES 持久化、CV 结果入库、CV 工具真实输出（1035：4 条实线、半圆弧、6 个标签）、直角标记合成回归（虚线臂 + 方块应命中、裸十字不命中）、Critic 等尺寸对比图（左右面板等大、原图在左、单图发送与无 `out_dir` 回退）、归档（重复运行覆盖旧产物/清理旧 Critic 报告、`data/` 保护）、Tectonic 实际编译+渲染+校验、shell-escape 拒绝、几何提交校验（截断带 tool call / 空提交均被拒）、TikZ 完整文档校验、Streamlit 初始页与结果页。

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

最终产物已归档到 `outputs/final_5/`（每图保留 `best.tex/pdf/png`、`result.json`、`state.json`、`critic_report.json`、`events.jsonl`、`llm_calls.jsonl`），并已整合进统一归档 `outputs/ours/`；中间运行目录（batch、checkpoints、crops、CV 缓存等）已清理。

| 图片 | 状态 | 最佳版本 | Critic | 耗时 | tokens | 视觉调用 | Geometry 合并 |
|---|---|---|---|---|---|---|---|
| 1035_q_fig1 | success | v1 | 0.95 | 105.7s | 75,402 | 1 | 12 obj / 14 rel |
| 1238_q_fig1 | success | v1 | 0.93 | 39.9s | 48,477 | 1 | 未调用（简单图） |
| 1250_q_fig1 | success | v1 | 0.93 | 68.8s | 66,154 | 1 | 9 obj / 9 rel |
| 1258_q_fig1 | success | v2 | 0.96 | 81.4s | 72,186 | 2 | 未调用（修复后达标） |
| 1259_s_fig1 | success | v1 | 0.95 | 86.3s | 70,557 | 1 | 10 obj / 3 rel |

第二轮全部成功，平均 Critic 0.944，平均 66.6k tokens/图。几何合并问题已修复；1258 经一次修复从 0.93 提升到 0.96。

Demo 验证：`streamlit run app.py` 健康检查返回 `ok`，`AppTest` 无异常；侧栏 100 个样本、5 个结果标签页、TikZ 下载按钮均正常。

### 6.5 边界样例批次（最终结果：`outputs/edge5`）

针对更复杂的图专门跑的一组：1266（双圆+割线+虚线）、1270（内切圆+中心双点）、1467（直角标记+虚线）、971（异常文件名+同名字母 C/C'）、6220（1080px 大图+多弦交点）。最后一轮修复后重跑 1266/971，其余取自同一批次。

| 图片 | 状态 | 最佳版本 | Critic | 耗时 | tokens | 视觉调用 | 步数 |
|---|---|---|---|---|---|---|---|
| 1266_s_fig1 | success | v1 | 0.90 | 113.4s | 89,896 | 5 | 8 |
| 971_q_fig2 | success | v2 | 0.95 | 124.3s | 188,047 | 8 | 10 |
| 1270_q_fig2 | success | v1 | 0.93 | 143.9s | 92,237 | 5 | 9 |
| 1467_q_fig5 | success | v1 | 0.95 | 92.5s | 158,213 | 1 | 8 |
| 6220_s_fig2 | success | v2 | 0.96 | 188.4s | 149,047 | 8 | 11 |

平均 Critic 0.938，平均 135k tokens/图。六类边界（双圆、内切圆、直角标记、虚线、C'、多交点大图）全部 success；另发现并修复了以下问题：

1. **数据集文件名**：`data/test/image/,971_q_fig2.png` 前导逗号导致该图不配对；扫描时归一化 stem（保留原文件），100/100 配对。`main.py batch --only` 不再被默认 `--limit 5` 截断。
2. **虚线图标签识别**：虚线碎片主导文本掩膜，旧的 cap height 中位数被拉到 10px，真字母（19–21px）全被过滤、只剩碎片被误读成 `1/2/3/U`。现只在字形尺寸连通域上估 cap height（971 恢复到 20px），过滤 0.62·cap 以下碎片，NCC < 0.45 返回 `?`，并新增撇号检测（C → C'）。
3. **截断响应**：`finish_reason=length` 即使带 tool call 也整段丢弃重试；空几何提交（无 objects/relations）被拒绝。
4. **TikZ 提交**：只接受完整 standalone 文档，prose/片段在子 Agent 内退回重交，971 因此少了一个失败版本（v1 失败→重交）。
5. **Supervisor**：提示词限定唯一合法的 6 个动作名（模型曾幻觉出 ToolSearch/Bash），并要求 CV 标签低置信/缺失时先 `inspect_image` 复核；971 因此由视觉复核确认 C'，最终 0.95。

产物：已整合进统一归档 `outputs/ours/stem/<stem>/`（`best.tex|pdf|png` + `result.json`/`state.json`/`critic_report.json`/`events.jsonl`/`llm_calls.jsonl`），并有 `outputs/ours/image/`、`outputs/ours/latex/` 镜像；`outputs/edge5/` 保留为批次快照；中间运行日志保留在 `outputs/batch_edge/`、`outputs/batch_edge2/`（1270 的中间目录已清理，最终产物仍完整保存在 `outputs/edge5/1270_q_fig2`）。

### 6.6 第三批 5 图与针对性优化（最终结果：`outputs/ours`）

新增一组 403（标签密集小图）、1630（虚线臂 + 直角标记）、1591（多共线点 + 虚线）、766（多交点）、1656（细线 + 延长线），全部 success，结果直接归档到 `outputs/ours/stem/<stem>/`。

| 图片 | 状态 | 最佳版本 | Critic | 耗时 | tokens | 视觉调用 | 步数 |
|---|---|---|---|---|---|---|---|
| 403_q_fig1 | success | v1 | 0.93 | 92.6s | 106,561 | 5 | 8 |
| 1630_s_fig1 | success | v1 | 0.93 | 88.5s | 97,616 | 5 | 8 |
| 1591_s_fig2 | success | v2 | 0.93 | 113.2s | 195,889 | 8 | 12 |
| 766_q_fig3 | success | v1 | 0.95 | 84.5s | 83,292 | 5 | 9 |
| 1656_q_fig1 | success | v2 | 0.93 | 113.9s | 246,293 | 6 | 11 |

平均 Critic 0.934。根据结果做了三项修复并重跑验证：

1. **虚线臂直角标记漏检（1630，0.85 → 0.93）**：HQ 是虚线，不构成长边，主路径（长边垂直对）永远找不到 Q 处的直角。新增回退：在骨架上 Hough 取短笔画（0.5–1.6·cap），配对成方块的两条外边，重建方块并验证方块墨迹、内部空白、独立墨迹；再把顶点吸附到真正支撑它的长边，并要求两臂在交点外侧继续延伸（区分 L 形笔画）。同时把 cap height 估计改为“只统计字形尺寸连通域 + 75 分位”，避免虚线碎片把 cap 拉到 10px 而过滤掉 19px 方块。最终 1630 画出 Q 处直角，Critic 从 0.85 升到 0.93。合成回归：虚线臂 + 方块命中 1 个、裸十字 0 个（`tests/test_cv_tools.py`）。
2. **Critic 线宽判断来回摆动（1656，0.92 → 0.93）**：v1 用 1.2pt 被 Critic 判“过粗”，修复后改成 0.6pt 又被判“过细”，Supervisor 随即结束。现在 Critic 先把原图与渲染图拼成等尺寸左右对比图（各 620×620 面板、按最长边归一，见 2.2），线宽可直接比较，提示同时要求不得在相邻版本给出相反结论；Supervisor 提示要求最新报告仍列出具体可修项时再做一轮 repair + critic。1656 重跑保持 1.2pt，最终 Critic 无 issue，0.93；1591 也借此从 3 条低严重度问题修到 0 条。
3. **重复运行归档残留旧报告**：同一 stem 重跑时 `outputs/ours/stem/<stem>/critic_report.json` 不会被覆盖，导致 `result.json` 的分数与 Critic 报告不一致（1630/1591 重跑后出现）。归档现在总是用最佳版本的报告覆盖，重跑没有报告时删除旧文件；新增两条回归测试。

最终校验：`outputs/ours/` 下 15 个 stem，每个 8 个文件；`image/`、`latex/` 镜像与 `best.png`/`best.tex` 逐字节一致；`result.json` 的 `run_dir` 指向归档目录；`critic_report.json` 分数与 `best_score` 一致。

---

## 7. 下一阶段建议

1. 接入 `configs/evaluation/core100.json` 的离线评测（渲染相似度 + 结构/对象级指标），对 100 张图做分层统计。
2. 增加线宽感知：在 `analyze_line_style` 中估计笔画宽度，让 TikZ Agent 按原图比例选择 `line width`。
3. 扩展标签模板库（多字符、下标、希腊字母），并输出匹配置信度分布。
4. 支持失败样本的自动重试策略（不同随机种子/温度、定向修复）。
5. 批处理并发与缓存（相同图片的 CV 结果复用）。
6. 在真实浏览器中补充端到端 UI 点击回归（当前使用 Streamlit AppTest + HTTP 健康检查）。
7. 收尾策略：Critic 给出具体问题（missing_element/label_error）且分数 < 0.95 时强制修复一轮（1266 v1 0.90 仅剩低严重度标签偏移，当前直接 finish）。
8. 被线条裁断的标签（1266 的 E）：用 `inspect_image` 对未绑定点的邻域 ROI 做定向复核，替代整图视觉调用。
