# 任务：初始化并实现 GeoAgent — Agentic Image-to-TikZ Demo

你是一名资深 Python 工程师、多智能体系统架构师、计算机视觉工程师和 AI Research Engineer。

请在当前项目目录中直接完成 **GeoAgent** 项目的初始化、核心功能开发、Demo 界面构建以及本地运行验证。

本项目未来计划用于计算机领域学术会议论文，因此不仅需要能够运行，还需要模块化、可扩展、可复现，并支持保存完整的智能体决策轨迹。

**不要只提供设计文档或伪代码，请实际创建项目文件、实现代码、安装必要依赖并尽可能运行验证。**

## 一、项目基本信息

项目名称：GeoAgent

研究任务：Mathematical Geometry Image-to-TikZ Generation

研究方向：Training-Free Agentic Multi-Agent System with Active Geometric Perception

主要数据集：TriGeoBench

实现语言：Python 3.11+

运行平台：Windows

### 已有本地资源

项目根目录：

```
D:\Users\18217\Desktop\我的文件\GeoAgent
```

API 配置：

```
D:\Users\18217\Desktop\我的文件\GeoAgent\.env
```

LaTeX 编译环境：

```
D:\Users\18217\Desktop\我的文件\GeoAgent\tool
```

测试数据集：

```
D:\Users\18217\Desktop\我的文件\GeoAgent\data
```

请首先检查上述目录、文件和已有内容，不要假设文件格式或目录结构。

**重要要求：**

1. 使用 `.env` 中已有的 API 配置。
2. 使用 `haiku-5.5` 模型。请检查 API Provider 的实际模型 ID 和调用方式，不要臆造模型名称。如果配置中的模型标识与 `haiku-5.5` 不完全一致，应优先依据已有配置和服务端支持情况确定，并在报告中说明。
3. 不要在代码中硬编码 API Key。
4. 不要修改、覆盖或泄露 `.env` 中的密钥。
5. API 客户端需要支持自定义 Base URL、API Key 和 Model ID。
6. 检查 `tool` 下已有的 LaTeX 编译工具，优先复用现有环境，不要直接假设系统已经安装 TeX Live。
7. 检查 `data` 目录，识别测试数据的实际组织方式，包括图片、Parquet、JSON 或其他格式。
8. 不要删除、修改原始数据集。
9. 路径必须兼容 Windows 中文目录和 Unicode 字符。
10. 不需要训练或微调任何模型。

如果某些外部条件无法验证，例如 API 权限、编译器依赖或网络访问，应完成其余可实现功能，并准确报告阻塞原因，不要伪造成功结果。

## 二、核心架构要求

系统采用：

**Supervisor-Centric Agentic Architecture**

架构包含：

- Supervisor Agent：主智能体
- Geometry Agent：几何理解子智能体
- TikZ Agent：TikZ 生成与修复子智能体
- Critic Agent：图像对比和错误诊断子智能体
- CV Toolbox：传统计算机视觉工具集合
- Execution Toolbox：编译、渲染、验证工具
- Geometric Evidence State（GES）：共享几何证据状态
- Visual Context Manager：视觉上下文管理器

### 关键限制：必须是真正的 Agentic 系统

不能实现为固定的：

Image → CV → Geometry Agent → TikZ Agent → Compiler → Critic → Repair

正确的实现应该是：

Supervisor 根据当前任务状态动态决定下一步调用什么工具或子智能体。

例如：

- 可以直接调用 TikZ Agent 生成代码。
- 可以首先调用 CV 工具检测线段。
- 可以针对某个区域请求 Geometry Agent。
- 可以在编译失败后直接调用 TikZ Agent 修复。
- 可以在已有证据足够时跳过额外视觉分析。
- 可以在发现错误后重新调用 CV。
- 可以自主判断任务是否结束。

请实现一个由 LLM Tool Calling 驱动的 Agent Loop。

**工具选择必须由模型的真实决策产生，不能通过硬编码条件模拟 Agent 决策。**

但允许使用确定性规则实现安全检查、调用次数限制、编译超时、状态校验和异常处理。

## 三、API 调用与成本控制

所有 Agent 可以使用同一个 `haiku-5.5` 模型，但通过不同 System Prompt 实现职责分工。

创建统一的 LLM Client，避免每个 Agent 重复实现 API 请求代码。

### 视觉调用规则

不要每轮都重新向模型发送图片。

默认：

- Supervisor 使用结构化文本状态摘要。
- CV 工具本地读取图像，不调用视觉 API。
- Geometry Agent 根据需要接收原始图像或局部裁剪图。
- TikZ Agent 初次生成可以使用原图和几何证据。
- TikZ Agent 局部修复优先使用代码与结构化错误。
- Critic Agent 仅在需要视觉对比时接收原图与渲染图。

设计 Visual Context Manager 管理图像路径、裁剪图、渲染图和缓存。

实现图像按需传输，避免每轮重复附带完整图像。

记录每次模型调用的输入输出 token、耗时和是否包含图片。如果 API 返回费用或缓存信息，也应记录。

### 调用可靠性

实现：

- 请求超时；
- 网络重试与指数退避；
- API 错误处理；
- JSON 结构化输出验证；
- Tool Calling 参数校验；
- 调用日志；
- Token 使用统计；
- 最大调用预算。

不要在日志中输出 API Key 或完整认证请求头。

## 四、CV Toolbox

请基于 OpenCV、NumPy、SciPy 等无需训练的工具实现以下功能。

所有 CV 工具必须：

1. 接收本地图像路径和可选 ROI。
2. 返回统一格式的结构化 JSON。
3. 保存可选的检测结果可视化图像。
4. 使用归一化坐标或明确的像素坐标系。
5. 记录检测方法、参数和候选证据。
6. 允许返回不确定或未检测到结果。
7. 不得将启发式置信分数伪装为真实概率。

### 4.1 实线与虚线检测

工具：

- `detect_lines`
- `merge_collinear_segments`
- `analyze_line_style`

使用：

- LSD / Hough；
- 共线聚类；
- RANSAC；
- 前景覆盖率分析；
- 连续段与间隙长度分析。

识别：

- 实线；
- 虚线；
- 候选端点；
- 共线关系。

需要考虑文字与线条接触导致的局部中断，避免直接把这些中断判定为虚线。

### 4.2 圆与圆弧检测

工具：

- `detect_circles`
- `fit_arcs`
- `extract_visible_arc`

使用：

- HoughCircles；
- 轮廓分析；
- 最小二乘圆拟合；
- 必要时使用 RANSAC。

支持完整圆和部分圆弧。

不需要恢复原始 TikZ 的精确起止角与绘制方向，但需要记录可见弧段范围或有序轮廓采样点，以便后续重建。

### 4.3 直角标记检测

工具：

- `detect_right_angle_marker`

只考虑直角标记。

基于：

- 交点引导的局部区域；
- 长线条抑制；
- 旋转归一化；
- 短折线模板与规则验证。

不能仅因为两条线在视觉上接近垂直就认定存在直角标记。

### 4.4 点标签识别

工具：

- `extract_label_candidates`
- `match_label_templates`
- `bind_point_labels`

当前只考虑几何点标签。

采用：

- 连通域分析；
- 字符区域归一化；
- 多尺度模板匹配；
- 字符形状特征；
- 标签到几何点的排他匹配。

允许返回未识别字符和未绑定标签。

当模板识别不可靠时，由 Supervisor 决定是否调用视觉模型。

### 4.5 文字与线条粘连处理

工具：

- `separate_text_and_lines`

采用：

- 长结构初检；
- 局部线条掩膜；
- 竞争分离假设；
- 字符与线条双向可识别性验证。

保留原图，不允许破坏性覆盖。

如果存在多种可能解释，返回候选假设供 Supervisor 判断。

### CV 开发优先级

优先实现可稳定运行的：

1. 直线检测；
2. 圆/圆弧检测；
3. 图像裁剪；
4. 检测结果可视化。

随后实现：

1. 虚线分类；
2. 直角标记；
3. 点标签；
4. 文字线条分离。

复杂工具可以逐步增强，但不要只返回伪造的结果或空壳。尚未完成的能力应明确标记状态，不得宣称已实现。

## 五、Geometric Evidence State

使用 Pydantic 定义统一的共享状态。

至少包含：

```
class GeometricEvidenceState:
    image_path: str

    objects: dict
    relations: dict
    evidence: dict

    current_tikz: str | None
    best_tikz: str | None

    tikz_versions: list
    compilation_results: list
    validation_results: list

    unresolved_issues: list
    action_history: list

    token_usage: dict
    remaining_budget: dict
```

需要维护：

- 几何对象 ID；
- 几何类型与坐标；
- 实线/虚线等样式；
- 标签与几何点绑定；
- 几何关系；
- 证据来源；
- 证据之间的冲突；
- 代码版本；
- 编译错误；
- Agent 决策历史。

支持状态 JSON 序列化与 checkpoint 保存。

每次工具调用后更新状态，失败时不能直接破坏此前有效的 TikZ 版本。

Supervisor 默认读取简短状态摘要，只有必要时才查询完整状态或图像。

## 六、Supervisor Agent

Supervisor 是系统的控制核心。

实现真实的模型工具调用循环：

1. 获取任务目标及当前状态。
2. 由 LLM 选择下一步 Action。
3. 校验动作和参数。
4. 调用对应工具或子智能体。
5. 将执行结果更新到 GES。
6. 再次进行自主决策。
7. 达到合理终止条件后返回最佳 TikZ。

支持以下 Action：

- `inspect_region`
- `call_cv_tool`
- `ask_geometry_agent`
- `ask_tikz_agent`
- `compile_and_render`
- `ask_critic_agent`
- `verify_constraints`
- `finish`

每次 Action 记录：

- 步骤编号；
- 工具名称；
- 简短操作目的；
- 参数；
- 执行结果；
- 耗时；
- 状态更新；
- API token 使用量。

设置可配置的：

- `max_steps`
- `max_tool_calls`
- `max_visual_calls`
- `max_total_tokens`
- `timeout_seconds`

实现重复调用检测、异常恢复和最佳有效版本保留。

当 Supervisor 选择 `finish` 时，应至少检查当前是否存在可编译 TikZ。如果不存在，返回明确的失败状态，而不是伪造成功。

## 七、三个专业子智能体

### Geometry Agent

负责：

- 解释 CV 输出；
- 理解图像中点、线、圆、圆弧等对象；
- 确认直角标记；
- 辅助点标签绑定；
- 判断几何关系；
- 解释存在冲突的候选证据。

使用结构化 JSON 输出。

### TikZ Agent

支持：

- `generate`
- `repair`

生成代码时：

- 优先使用命名坐标；
- 正确表达实线、虚线、圆与圆弧；
- 正确放置点标签；
- 允许使用常见 TikZ 库；
- 尽量生成简单、可编译、可维护的代码。

代码中尽可能使用稳定的对象标记：

```
% GEO_OBJECT: line_AB
\draw (A) -- (B);
```

修复时优先局部修改，不必要时不要全部重写。

### Critic Agent

负责：

- 对比原图和 TikZ 渲染图；
- 识别缺失或多余的几何对象；
- 识别线型不一致；
- 识别标签错位；
- 发现直角标记缺失；
- 给出结构化错误报告。

Critic 不应直接控制下一步流程，最终动作由 Supervisor 决定。

## 八、LaTeX 编译与图像渲染

请检查：

```
D:\Users\18217\Desktop\我的文件\GeoAgent\tool
```

识别其中是否存在可用的：

- pdflatex；
- lualatex；
- xelatex；
- tectonic；
- 其他可执行编译工具及其依赖。

根据实际发现配置编译器。

实现：

- `compile_tikz`
- `render_pdf`
- `validate_compilation`
- `extract_compiler_errors`

需要考虑 Windows 中文路径兼容。

所有编译任务使用临时工作目录或隔离目录。

禁止 shell escape，限制超时，尽可能限制文件系统访问和外部命令执行。

编译成功后生成 PNG，保存当前 TikZ 和渲染图。

维护代码版本，允许回滚。

如果现有 `tool` 目录不足以提供可用的编译环境，应明确报告缺失项和建议的补充方式。

## 九、TriGeoBench 数据读取

检查：

```
D:\Users\18217\Desktop\我的文件\GeoAgent\data
```

识别数据集组织方式。

如果是 Parquet 格式，应支持读取图像字节、图像路径或其他实际存储形式。

请依据真实 schema 实现适配器，不要猜测列名。

实现：

- 数据集样本列表；
- 按样本 ID 加载；
- 加载原始图像；
- 随机选择测试图片；
- 将指定样本送入 GeoAgent。

重要：测试过程中，Agent 只能使用输入图像，不得将参考 TikZ、题目答案或其他真值字段提供给模型。

参考 TikZ 可以在数据适配器中隔离保存，但不参与 Demo 生成。

## 十、Demo 界面

使用 Streamlit 构建本地 Demo。

支持：

### 输入区域

- 从 TriGeoBench 选择样本；
- 直接上传几何图片；
- 设置最大 Agent 步数；
- 设置视觉 API 调用上限；
- 点击 Run 启动生成。

### 原始图像区域

展示：

- 原图；
- CV 检测结果；
- 直线、圆、弧线、标签等可视化叠加。

### 生成结果区域

展示：

- 当前 TikZ 源代码；
- 最新渲染图；
- 最佳有效版本；
- 下载 `.tex` 文件。

### Agent Trace 区域

实时或分步展示：

- Supervisor 调用哪个工具；
- Tool Calling 参数；
- 执行结果；
- 失败原因；
- 当前步骤；
- 累计 token 使用量。

### Geometry Evidence 区域

展示：

- 几何对象；
- 几何关系；
- 证据来源；
- 未解决的问题；
- CV 与 VLM 之间的证据冲突。

界面应以演示 Agentic 决策和几何证据为重点，而不是普通聊天窗口。

## 十一、建议项目结构

```
GeoAgent/
├── .env
├── .env.example
├── configs/
├── data/
├── tool/
├── geoagent/
│   ├── agents/
│   │   ├── supervisor.py
│   │   ├── geometry_agent.py
│   │   ├── tikz_agent.py
│   │   └── critic_agent.py
│   ├── cv_tools/
│   │   ├── line_detection.py
│   │   ├── circle_detection.py
│   │   ├── right_angle.py
│   │   ├── label_detection.py
│   │   └── text_line_separation.py
│   ├── state/
│   │   ├── schemas.py
│   │   └── evidence_store.py
│   ├── orchestration/
│   │   ├── agent_loop.py
│   │   └── dispatcher.py
│   ├── tools/
│   │   ├── registry.py
│   │   ├── compiler.py
│   │   ├── renderer.py
│   │   └── verifier.py
│   ├── llm/
│   │   └── client.py
│   └── datasets/
│       └── trigeobench.py
├── outputs/
├── tests/
├── app.py
├── main.py
├── pyproject.toml
└── README.md
```

可以根据实际需要调整，但必须保持职责清晰。

## 十二、实施步骤

请按照以下顺序执行，但不要停留在规划阶段。

### Step 1：检查项目环境

- 检查目录；
- 读取 `.env` 的变量名称与非敏感配置；
- 验证 API 客户端适配方式；
- 检查编译器；
- 检查数据集；
- 检查 Python 环境；
- 记录环境发现。

不要显示密钥。

### Step 2：创建工程骨架

- 初始化 Python 项目；
- 创建虚拟环境；
- 安装依赖；
- 创建配置文件；
- 定义 GES；
- 定义工具接口；
- 实现 API 客户端。

### Step 3：实现 Agentic 主循环

先实现：

- Supervisor；
- TikZ Agent；
- Compiler；
- Renderer；
- GES。

要求至少能运行单张图片的 Image-to-TikZ 生成。

### Step 4：加入基础 CV 能力

实现直线、圆和局部图像裁剪工具。

确保 Supervisor 可以自主调用，而非强制在最开始运行全部 CV。

### Step 5：加入 Geometry Agent 和 Critic Agent

完成结构化几何理解、视觉对比及错误反馈。

### Step 6：扩展 CV 功能

加入：

- 虚线分析；
- 直角标记；
- 点标签识别与绑定；
- 文字线条分离。

这些能力应尽可能实现实际算法。确实不能完成的功能明确标注，不得用假数据伪装成功。

### Step 7：构建 Streamlit Demo

实现图像输入、运行控制、TikZ 输出、渲染结果和 Agent Trace 可视化。

### Step 8：运行验证

尽可能完成：

1. 模块导入检查；
2. API 客户端可用性检查；
3. CV 工具基础测试；
4. 编译器实际编译测试；
5. 数据集样本读取测试；
6. 单张图像端到端测试；
7. Streamlit 启动测试。

API 真实调用会产生费用。优先使用小规模测试，避免自动执行大量样本或无限重试。

## 十三、验收标准

本阶段目标是可运行 Demo，而不是完成论文实验。

最终至少应达到：

- 

  Python 项目可以正常安装和启动。

- 

  能读取现有 `.env` 并使用指定模型 API。

- 

  能读取 TriGeoBench 的实际数据文件。

- 

  Supervisor 可以通过真实 Tool Calling 动态选择动作。

- 

  能生成 TikZ 代码。

- 

  能使用现有 LaTeX 环境实际编译。

- 

  能渲染结果并展示图片。

- 

  CV 工具能产生真实几何检测结果。

- 

  GES 能持久化保存证据与执行状态。

- 

  能查看 Agent 决策轨迹。

- 

  能启动 Streamlit 本地 Demo。

- 

  至少完成一次端到端运行，或者明确记录外部阻塞条件。

所有通过状态必须有实际测试结果支持。

## 十四、最终交付要求

完成后请给出：

1. **项目结构**：实际创建了哪些关键文件。
2. **架构说明**：Supervisor、子 Agent、CV 工具与 GES 如何协作。
3. **环境检查结果**：模型 API、LaTeX 工具、数据集的实际情况。
4. **已实现功能**：明确区分已完成、部分完成、尚未完成。
5. **测试结果**：提供真实执行日志摘要。
6. **启动方法**：给出可直接在 Windows PowerShell 中执行的命令。
7. **Demo 入口**：说明 Streamlit 本地访问方式。
8. **下一阶段建议**：列出需要完善的功能，不涉及对比实验。

请把启动方式、配置说明和架构概述写入 `README.md`。

额外要求：

- 不要覆盖已有用户文件。
- 不要提交 API Key。
- 不要生成虚假的模型响应、几何结果或测试日志。
- 不要为了完成演示而绕过真实的 Agentic 决策。
- 不要把固定 Workflow 伪装成自主 Agent。
- 在遇到局部实现困难时，优先完成能够运行的核心闭环，再逐步完善高级特征。

**现在请从检查项目目录、API 配置、LaTeX 环境和数据集开始，直接开展实际实现工作。不要仅回复实施计划。**