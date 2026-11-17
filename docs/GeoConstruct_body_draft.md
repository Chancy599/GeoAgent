# GeoConstruct 正文草稿备份（第 III–V 节）

> 本文件保存从 GeoConstruct.md 暂时移出的第 III（Method）、IV（Experiments）、V（Conclusion）节中英文内容，以及仅在实验章节引用的三条指标文献（SSIM / CLIP / DINOv2，当前编号 [12]–[14]，恢复正文时请与主文件参考文献重新对齐编号）。主文件当前仅保留摘要、引言、相关工作与参考文献四部分。

# III. Method

## A. Overview and Problem Statement

Given a raster image I of a geometric figure, GeoConstruct produces a parameterized TikZ program C whose rendering matches I visually and whose geometry matches the intended construction: angles, length ratios, incidences, and marked relations such as right angles should hold in C, not merely appear to hold in the rendering. Because the ultimate goal is editing and reuse, C must also be structured (named points shared across draw commands, measured coordinates, and explicit relations) so that local edits stay local.

Three design decisions define the system: (i) a persistent Geometric Evidence State as the single source of truth (Sec. III-B); (ii) a supervisor-worker orchestration in which a Supervisor delegates to specialized sub-agents and deterministic tools (Sec. III-C, III-D); and (iii) a deterministic geometric constraint-repair stage that finalizes the geometry before delivery (Sec. III-E). Sec. III-F describes how the output supports editing and reuse.

## B. Geometric Evidence State

The GES is a typed, persistent store shared by all components. It contains five kinds of records. **Geometry objects** (points, segments, lines, circles, arcs, right-angle markers, labels, polygons) carry coordinates, style, a provenance field naming the tool or agent that produced them, and a lifecycle status (candidate, confirmed, rejected, conflict). **Relations** (incidence, perpendicular, parallel, collinear, midpoint, center, etc.) link objects and record their supporting evidence. **Evidence records** log each measurement or verification with its method and payload, so any coordinate can be traced back to the strokes that support it. **Conflict records** keep unresolved contradictions explicit instead of silently overwriting them. **Version records** store every TikZ version with its compilation result, topology check, and critic report.

The GES is checkpointed after every step and summarized into the Supervisor's context. This design serves three purposes. First, it decouples agents: the Code Agent consumes the Geometry Agent's conclusions as structured data, not as chat history. Second, it makes the run auditable and replayable: any later decision can be justified by the evidence that was present when it was made. Third, it separates confidence from appearance: a relation is promoted to confirmed only when programmatic verification (e.g., stroke support under a threshold) succeeds, which is exactly the property that one-shot generation lacks.

## C. Supervisor-Worker Orchestration

A Supervisor drives the run through a tool-calling loop under explicit budgets (at most 24 steps, 48 tool calls, 24 visual calls, and 400k tokens). The Supervisor never measures or writes code itself; it delegates. Its tool set has four groups:

1) **CV tools.** Ten deterministic operators provide pixel-level measurement: line detection, collinear-segment merging, line-style analysis, circle detection, arc fitting, visible-arc extraction, right-angle-marker detection, label-candidate extraction, label-template matching, and point-label binding. Their outputs are ingested into the GES as measured evidence.

2) **Visual inspection.** A budgeted inspect_image tool lets the Supervisor look at the original figure or a crop. It is used for disambiguation, not measurement; the prompt explicitly forbids using it to read coordinates.

3) **Sub-agents.** run_geometry_agent, run_code_agent, and run_critic invoke the three sub-agents described below.

4) **finish.** Terminates the run with a status of success, partial, or blocked; the finish call can be rejected if mandatory checks have not run.

Because the Supervisor sees a fresh GES summary at every step, orchestration is dynamic rather than scripted: it can request additional measurements for a region the Critic flagged, send the Code Agent back to repair mode with compiler errors attached, or stop early when the figure verifies. Runs that exhaust the budget with unresolved mandatory issues are recorded as partial rather than silently accepted.

## D. Specialized Agents

**Geometry Agent.** Before any code is written, the Geometry Agent consolidates fragmented CV measurements into a construction plan: which measured points the labels bind to, which points are connected, which edges are dashed, and where right-angle markers sit, including the two rays of each marker. Its proposals are not taken on trust: a program verifies them against the original strokes and keeps only those with evidence. When dashed gaps truncate fitted segments, intersections of neighboring lines supply endpoint candidates. The verified plan, together with the measured coordinates, enters the GES as the construction contract for code generation.

**Code Agent.** The Code Agent writes parameterized TikZ from the construction contract. Two mechanisms tie it to the evidence. First, a *coordinate contract*: points with verified label bindings receive their CV-measured coordinates, uniformly scaled, translated, and y-flipped into TikZ space, and managed labels must reference same-named coordinates: redefining them, transforming the coordinate system, or translating a path locally triggers a retry. The model therefore decides connectivity, style, and auxiliary construction, but not the numerically error-prone placement of named points. Second, the agent examines candidate geometric relations (initially parallelism and perpendicularity) that the measured coordinates satisfy within a tolerance of 0.5°, and proposes the small coordinate corrections that would make them exact. These proposals, with their tolerances, are recorded in the GES and handed to the repair stage.

**Critic Agent.** After every successfully rendered version, the Critic compares the rendering with the original figure: missing or spurious elements, wrong connections, dashed-edge endpoints, marker orientation, labels, and line widths. It returns concrete, executable revision requests, and it may abstain on ambiguous cases rather than guess. Confirmed corrections are written back to the GES and trigger re-verification of existing versions, so a late discovery can repair earlier decisions.

## E. Geometric Constraint Repair

CV measurements carry a few pixels of fitting noise, so relations that hold in the true figure often hold only approximately in the recovered coordinates. The repair stage turns such near-satisfied relations into exactly satisfied ones without trusting the model's judgment. Fig. 2 illustrates the pipeline.

> [FIGURE 2: The constraint-repair pipeline: candidate extraction from near-satisfied relations, evidence gating against the original strokes, minimal-movement solving under budgets, and compile-time acceptance with rollback.]

**Candidate extraction.** Candidates come from the numeric geometry alone: pairs of drawn edges within 0.5° of parallel or perpendicular, and collinearity candidates formed by two drawn edges sharing an endpoint with a turning angle below 8°, each verified against stroke support in the original image. Relations asserted by agents but unsupported by pixels are not repaired toward.

**Constrained solving.** A Gauss-Seidel-style solver projects the coordinates onto the accepted constraints while minimizing movement. Hard budgets bound the edit: no point may move more than 1.3% of the figure's diagonal, and no existing edge may change length by more than 3.5%. Verified right-angle markers, incidence structure, collinear ordering, and intersections are protected during the solve. Curve branches are frozen together with their defining points.

**Strict acceptance and rollback.** In strict mode, the solved layout is realized on TeX's integer grid and read back from the compiled output; every selected perpendicular, parallel, and collinear relation must then hold exactly (zero integer dot or cross product). If search, verification, or compilation fails at any point, the system delivers the pre-repair code unchanged. Repair is thus a strict improvement operator: it can only accept solutions that are verifiably closer to the intended construction.

## F. Editing and Reuse Interface

The output program is built for reuse. Named points with measured coordinates are shared across draw commands, labels bind to coordinates rather than absolute offsets, and accepted relations hold exactly, so local edits stay local and the program remains consistent after them. On top of this representation we implement three verified atomic edit operators: label replacement, midpoint insertion (defined through TikZ interpolation expressions and checked after compilation), and solid/dashed restyling, each of which rejects the edit when the target cannot be located unambiguously. Sec. IV-E evaluates how this reuse capability compares across reconstruction methods.

## 中文翻译

**A. 总览与问题定义。** 给定几何图形的栅格图像 I，GeoConstruct 生成参数化 TikZ 程序 C：其渲染结果与 I 视觉一致，其几何与预期构造一致：角度、长度比、关联关系以及直角标记等标记关系应在 C 中成立，而不仅是在渲染中看似成立。由于最终目标是编辑与复用，C 还必须是结构化的（命名点在各绘图命令间共享、坐标来自实测、关系显式），使局部编辑保持局部。

三项设计决策定义了本系统：（i）以持久化几何证据状态作为唯一事实来源（第 III-B 节）；（ii）Supervisor-Worker 式编排，由 Supervisor 调度专用子智能体与确定性工具（第 III-C、III-D 节）；（iii）确定性的几何约束修复阶段，在交付前完成几何定稿（第 III-E 节）。第 III-F 节说明输出如何支持编辑与复用。

**B. 几何证据状态（GES）。** GES 是所有组件共享的带类型持久存储，包含五类记录。**几何对象**（点、线段、直线、圆、弧、直角标记、标签、多边形）携带坐标、样式、标明产生者的来源字段，以及生命周期状态（候选、已确认、已拒绝、冲突）。**关系**（关联、垂直、平行、共线、中点、圆心等）连接对象并记录其支撑证据。**证据记录**登记每次测量或核验的方法与载荷，使任何坐标都可追溯到支持它的笔画。**冲突记录**把未解决的矛盾显式保留，而非静默覆盖。**版本记录**保存每个 TikZ 版本及其编译结果、拓扑检查与 Critic 报告。

GES 每一步都会存档，并以摘要形式进入 Supervisor 的上下文。这一设计有三个目的：第一，解耦智能体：Code Agent 以结构化数据而非聊天记录消费 Geometry Agent 的结论；第二，使运行可审计、可重放：任何后续决策都可由当时已有的证据来解释；第三，把置信度与外观分离：关系只有在程序化核验（如阈值下的笔画支撑）成功后才提升为已确认，这正是一次性生成所不具备的性质。

**C. Supervisor-Worker 式编排。** Supervisor 在显式预算（至多 24 步、48 次工具调用、24 次视觉调用、40 万 token）下通过工具调用循环驱动运行。Supervisor 自身不测量、不写代码，只做调度。其工具集分为四组：

1）**CV 工具**。十个确定性算子提供像素级测量：线段检测、共线段合并、线型分析、圆检测、圆弧拟合、可见弧提取、直角标记检测、标签候选提取、标签模板匹配，以及点-标签绑定。其结果作为实测证据汇入 GES。

2）**视觉检查**。受预算约束的 inspect_image 工具允许 Supervisor 查看原图或局部裁剪，仅用于歧义消解而非测量；提示词明确禁止用它读取坐标。

3）**子智能体**。run_geometry_agent、run_code_agent 与 run_critic 分别调用下文所述的三个子智能体。

4）**finish**。以 success、partial 或 blocked 状态结束运行；若必做检查尚未执行，finish 调用会被拒绝。

由于 Supervisor 每一步都看到最新的 GES 摘要，编排是动态而非脚本化的：它可以针对 Critic 标记的区域请求补充测量，可以让 Code Agent 带着编译错误进入修复模式，也可以在图形验证通过后提前结束。预算耗尽且仍有未解决的必修复问题时，运行记为 partial 而非静默接受。

**D. 专用子智能体。** **Geometry Agent**：在编写任何代码之前，Geometry Agent 把碎片化的 CV 测量整合为构造计划：标签绑定到哪些实测点、哪些点相连、哪些边是虚线、直角标记位于何处（含每个标记的两条射线）。其提议不会被直接采信：程序会对照原图笔画验证，只保留有证据支撑的部分。当虚线间隙使拟合线段截短时，邻近直线的交点可补充端点候选。经核验的计划与实测坐标一起作为构造契约写入 GES，供代码生成使用。

**Code Agent**：Code Agent 根据构造契约编写参数化 TikZ。两项机制把它与证据绑定。第一是**坐标契约**：具有已验证标签绑定的点，其 CV 实测坐标经统一缩放、平移与 y 轴翻转后写入 TikZ 空间，受管理标签必须引用同名坐标：重定义坐标、变换坐标系或局部平移路径都会触发重试。因此模型负责连接、样式与辅助构造，而不负责数值上最易出错的命名点定位。第二是**候选约束检查**：智能体检查实测坐标在 0.5° 容差内满足的候选几何关系（初期为平行与垂直），并提出使其严格成立的小幅坐标修正。这些提议连同容差被记入 GES，交给修复阶段。

**Critic Agent**：每个成功渲染的版本之后，Critic 将渲染结果与原图比对：漏画或多画的元素、错误连接、虚线端点、角标方向、标签与线宽。它返回具体、可执行的修改意见；对歧义情形可以弃权，而不是猜测。经确认的纠正回写 GES，并触发对已有版本的复验，因此后期发现也能修复早期决策。

**E. 几何约束修复。** CV 测量带有数像素的拟合噪声，因此真实图形中成立的关系在还原坐标中往往只近似成立。修复阶段在不依赖模型判断的前提下，把这类近似满足的关系变为严格满足。图 2 展示了该流程。

**候选提取**：候选只来自数值几何本身：与平行或垂直相差 0.5° 以内的已绘制边对；以及共享端点、转折角小于 8° 的两条已绘制边构成的共线候选，且每条候选都须经原图笔画支撑核验。智能体断言但像素不支持的关系不会被作为修复目标。

**约束求解**：采用 Gauss-Seidel 式求解器，在最小化移动量的同时把坐标投影到已接受约束上。硬性预算约束编辑幅度：任何点的移动不得超过图形对角线的 1.3%，任何已有边的长度变化不得超过 3.5%。已验证的直角标记、点线关联结构、共线顺序与交叉关系在求解过程中受到保护。曲线分支与其定义点一起冻结。

**严格验收与回滚**：严格模式下，求解得到的布局在 TeX 的整数网格上实现，并从编译输出中回读；每条被选中的垂直、平行、共线关系都必须严格成立（整数点积或叉积为零）。若搜索、核验或编译在任一环节失败，系统交付修复前的原始代码。因此修复是一个严格改进算子：它只接受可验证地更接近预期构造的解。

**F. 编辑与复用接口。** 输出程序为复用而建。带实测坐标的命名点在各绘图命令间共享，标签绑定到坐标而非绝对偏移，已接受的关系严格成立，因此局部编辑保持局部，编辑后程序仍保持一致。在此表示之上，我们实现了三个经验证的原子编辑算子：标签替换、中点插入（用 TikZ 插值表达式定义并在编译后核验）、实虚线切换；当目标无法唯一确定时，编辑器会拒绝编辑。第 IV-E 节评估了不同重建方法在这一复用能力上的差异。

---

# IV. Experiments

## A. Setup

**Dataset and reference.** We evaluate on 150 figures sampled from the TriGeoBench test split [[1\]](https://arxiv.org/abs/2610.27626). Because TriGeoBench ships human-authored TikZ for every figure, we build a frozen reference manifest from the source code alone: visible labels and their bound coordinates, drawn segments whose endpoints are both labeled (1,709 segments), and the angles (4,602) and ordered length ratios (5,603) defined by labeled segments. A small number of verified reference corrections are recorded separately with source hashes; the manifest is fixed before evaluation and never adapted to any prediction.

**Baselines.** We compare against four closed-source end-to-end image-to-TikZ models: haiku-5.5, gpt-5.4, qwen3.5-plus, and glm-5.3-flash, each prompted to produce compilable TikZ in one shot. GeoConstruct uses the same backbone MLLM as the strongest baseline (haiku-5.5) for its Supervisor and sub-agents, so the comparison isolates the contribution of the architecture rather than model choice.

**Implementation.** Figures are compiled with a local Tectonic engine. Default budgets are 24 steps, 48 tool calls, and 24 visual calls per figure; repair runs in strict mode. Generation and repair never read the reference code.

## B. Metrics

**Visual similarity.** Following the image-to-TikZ probe in [[1\]](https://arxiv.org/abs/2610.27626), we render all outputs on a fixed 1000 px white canvas and report grayscale SSIM [[12\]](https://doi.org/10.1109/TIP.2003.819861) and cosine similarity of CLIP ViT-L/14 [[13\]](https://arxiv.org/abs/2103.00020) and DINOv2-base [[14\]](https://arxiv.org/abs/2304.07193) features, averaged over the 150 figures.

**Geometric fidelity.** For each reference item we locate same-named points in the generated code and report: angle MAE over commonly measurable angles; ratio MRE over commonly measurable length ratios; segment F1 between predicted and reference labeled segment sets; aligned point error, the mean relative displacement of same-named points after fitting translation, rotation, and uniform scale; and a whole-figure pass rate, where a figure passes only if it compiles, its labeled segment set matches exactly, and every reference angle (resp. ratio) is measurable within 1° (resp. 2%). Missing or degenerate items count against the method and are never substituted with zero error.

## C. Main Results

Table 1 lists the main results.

> [TABLE 1: Main comparison on 150 TriGeoBench figures: three visual-similarity metrics and five geometry-level metrics for four end-to-end baselines and GeoConstruct.]

Three observations stand out. First, visual similarity saturates but geometric fidelity does not. All methods reach SSIM around 90, and the strongest baseline matches the overall layout well (segment F1 of 95.7%), yet its angle MAE is 1.96°, its ratio MRE 5.49%, and only 38.0% of its figures pass the 1°/2% whole-figure check. The other baselines are visually comparable (SSIM 90.2–90.6) but geometrically much worse, with ratio MRE up to 18.0% and pass rates below 5%, which is direct evidence that image-level metrics reward figures whose geometry is broken.

Second, GeoConstruct improves every geometric metric by an order of magnitude: angle MAE 0.10°, ratio MRE 0.32%, point error 0.09%, segment F1 99.97%, and an 86.0% pass rate. Since GeoConstruct and the strongest baseline share the same backbone MLLM, the gap reflects the architecture (measured grounding, evidence accumulation, and constraint repair) rather than model capability.

Third, the visual metrics also improve (SSIM 94.36 vs. 90.57; CLIP 99.37; DINO 98.98), showing that enforcing geometric correctness does not trade off appearance; it improves it, because many visually visible defects (misconnected edges, misplaced labels) are geometric defects.

## D. Ablation Study

We ablate the two mechanisms that act after the first draft, using the same 150 figures, the same frozen reference, and paired scoring. Table 2 lists the results.

> [TABLE 2: Ablation on the same 150 figures: the full system versus variants without constraint repair and without the Critic.]

**Constraint repair.** Removing repair (both variants share the same generated code and coordinate contract) degrades every geometry metric, with segment F1 dropping from 99.97% to 99.87% and the pass rate from 86.0% to 83.3%, and, more importantly, removes exactness: with repair, 429 of 525 accepted relations hold exactly after compilation (maximum residual 0.003°), against 129 of 525 with the plain three-decimal realization. Repair is the component that converts "visually perpendicular" into "perpendicular".

**Critic.** Removing the Critic (the first version passing compilation and basic checks, then repaired identically) roughly doubles the angle MAE (0.105° → 0.216°) and ratio MRE (0.368% → 0.646%), and drops the pass rate to 80.7%. The Critic contributes most where deterministic checks are blind: wrong connections, missing elements, and marker orientation.

## E. Editability and Reuse

The motivation for recovering code is reuse, so we probe it directly. For **editing**, we issue the same three atomic commands (replace a label, insert a verified midpoint on a supported edge, toggle an edge between solid and dashed) to the programs of every method, using one shared, verification-gated editor; an edit counts only if the target is unambiguous, the change verifies, and unrelated content is preserved. For **querying**, we answer questions with definite numeric criteria from the generated code alone: classifying reference angles into four categories and deciding which of two labeled edges is longer. Table 3 lists the results.

> [TABLE 3: Reuse probes: acceptance counts for the three atomic edit operations (source-level over 150 figures / compile-verified over a 30-figure sample), and query accuracy for angle classification and edge-length comparison.]

GeoConstruct achieves the best edit acceptance on all three operations (e.g., 131/150 dashed-toggle edits pass source-level checks, versus at most 89 for baselines) and answers 99.69% of angle-classification queries and 100% of length-comparison queries correctly. Baseline programs often encode the same visual figure with fragmented paths, locally shifted coordinates, or approximate positions, which breaks both targeted edits and numeric queries.

## F. Planned Comparison with Open-Source Backbones

The present evaluation covers closed-source models, because their end-to-end image-to-TikZ quality is currently the strongest available. A comparison with open-source MLLMs, run under the identical protocol (the same 150 figures, frozen reference manifest, prompting template, and metric implementations), is in preparation, covering both open-source end-to-end baselines and GeoConstruct instantiated with open-source backbones. Table 4 reserves the structure for these results.

> [TABLE 4: (Reserved) Open-source model comparison under the identical protocol: end-to-end open-source baselines and GeoConstruct with open-source backbones, on the same visual and geometric metrics as Table 1.]

The reserved comparison is designed to answer two questions without altering the present narrative: whether the visual-similarity/geometric-fidelity gap observed for closed-source models widens for open-source ones, and how much of GeoConstruct's gain transfers when its Supervisor and sub-agents are backed by open-source models.

## 中文翻译

**A. 实验设置。** **数据集与参考**：我们在 TriGeoBench 测试集中抽取的 150 张图上评估 [[1\]](https://arxiv.org/abs/2610.27626)。TriGeoBench 为每张图提供人工编写的 TikZ，我们据此仅从源代码构建冻结参考清单：可见标签及其绑定坐标、两端均有标签的已绘制线段（1,709 条），以及由具名线段定义的角度（4,602 个）与有序长度比（5,603 个）。少量经核验的参考修正连同源码哈希单独记录；清单在评测前固定，从不根据任何预测结果调整。

**基线**：我们与四个闭源端到端图像到 TikZ 模型比较：haiku-5.5、gpt-5.4、qwen3.5-plus 与 glm-5.3-flash，均通过提示一次性生成可编译 TikZ。GeoConstruct 的 Supervisor 与子智能体使用与最强基线（haiku-5.5）相同的骨干 MLLM，因此该比较隔离的是架构而非模型选择的贡献。

**实现**：图形使用本地 Tectonic 引擎编译。默认预算为每张图 24 步、48 次工具调用、24 次视觉调用；修复以严格模式运行。生成与修复全程不读取参考代码。

**B. 评估指标。** **视觉相似度**：沿用 [[1\]](https://arxiv.org/abs/2610.27626) 的图像到 TikZ 探针，我们将所有输出渲染在 1000 px 白底画布上，报告灰度 SSIM [[12\]](https://doi.org/10.1109/TIP.2003.819861) 以及 CLIP ViT-L/14 [[13\]](https://arxiv.org/abs/2103.00020) 与 DINOv2-base [[14\]](https://arxiv.org/abs/2304.07193) 特征的余弦相似度，对 150 张图取平均。

**几何保真度**：对每条参考测量项，我们在生成代码中定位同名点，并报告：共同可测角度上的角度 MAE；共同可测长度比上的比例 MRE；预测与参考具名线段集合之间的线段 F1；对齐后点位误差，即拟合平移、旋转与等比缩放后同名点的平均相对位移；以及整图通过率：一张图只有在能编译、具名线段集合完全匹配、且每个参考角度（比例）可测且误差在 1°（2%）以内时才算通过。缺失或退化项计入分母，从不以零误差替代。

**C. 主要结果。** 表 1 列出主要结果。

三点观察尤为突出。第一，视觉相似度趋于饱和，几何保真度却没有。所有方法的 SSIM 都在 90 左右，最强基线的整体布局还原也不错（线段 F1 为 95.7%），但其角度 MAE 为 1.96°、比例 MRE 为 5.49%，且只有 38.0% 的图能通过 1°/2% 的整图检查。其余基线在视觉上相当（SSIM 90.2–90.6），几何上却差得多，比例 MRE 最高达 18.0%，通过率不足 5%，这直接证明图像级指标会奖励几何已被破坏的图形。

第二，GeoConstruct 把每项几何指标都提升了一个数量级：角度 MAE 0.10°、比例 MRE 0.32%、点位误差 0.09%、线段 F1 99.97%、通过率 86.0%。由于 GeoConstruct 与最强基线使用同一骨干 MLLM，差距来自架构（实测锚定、证据累积与约束修复）而非模型能力。

第三，视觉指标同样提升（SSIM 94.36 对 90.57；CLIP 99.37；DINO 98.98），说明强制几何正确并不牺牲外观，反而改善外观，因为许多肉眼可见的缺陷（错接的边、错位的标签）本身就是几何缺陷。

**D. 消融实验。** 我们对首稿之后起作用的两个机制做消融，使用同一批 150 张图、同一份冻结参考与配对计分。表 2 列出结果。

**约束修复**：关闭修复后（两个变体共享同一份生成代码与坐标契约），每项几何指标都变差（线段 F1 从 99.97% 降至 99.87%，通过率从 86.0% 降至 83.3%），更重要的是失去了严格性：开启修复时，525 条已接受约束中有 429 条在编译后严格成立（最大残差 0.003°），而普通三位小数方案只有 129 条。修复正是把"看着垂直"变成"垂直"的组件。

**Critic**：关闭 Critic 后（取首个通过编译与基础检查的版本，再以相同方式修复），角度 MAE（0.105° → 0.216°）与比例 MRE（0.368% → 0.646%）约翻倍，通过率降至 80.7%。Critic 的贡献集中在确定性检查的盲区：错误连接、缺失元素与角标方向。

**E. 可编辑性与复用。** 还原代码的动机是复用，因此我们直接探查复用能力。**编辑**方面，我们向各方法生成的程序发出相同的三条原子命令（替换标签、在有支撑的边上插入经验证的中点、切换实虚线），使用同一个带验证门控的编辑器；只有目标无歧义、修改通过验证且无关内容得以保留时才算成功。**查询**方面，我们仅凭生成代码回答有明确数值判据的问题：把参考角度分入四个类别，以及判断两条具名边孰长。表 3 列出结果。

GeoConstruct 在全部三项编辑操作上取得最高验收数（如实虚线切换 131/150 通过源码级检查，基线最多 89），并答对了 99.69% 的角度分类查询与 100% 的边长比较查询。基线程序常用碎片化路径、局部偏移坐标或近似位置编码同一视觉图形，这会同时破坏定向编辑与数值查询。

**F. 开源骨干模型对比（预留）。** 当前评估覆盖闭源模型，因为它们的端到端图像到 TikZ 质量目前最强。与开源 MLLM 的对比正在准备中，将采用完全相同的协议：同一批 150 张图、同一份冻结参考清单、相同的提示模板与指标实现，覆盖开源端到端基线以及以开源模型为骨干的 GeoConstruct。表 4 为这些结果预留了结构。

这组预留的对比旨在不改变现有叙事的前提下回答两个问题：闭源模型上观察到的"视觉相似度/几何保真度"差距在开源模型上是否会扩大；以及当 Supervisor 与子智能体由开源模型承担时，GeoConstruct 的收益能保留多少。

---

# V. Conclusion

We presented GeoConstruct, a system that converts raster geometric figures into editable, compilable TikZ code. Its design rests on three pieces: a persistent Geometric Evidence State that records every measurement and decision with provenance; a supervisor-worker architecture in which a Supervisor orchestrates CV tools and specialized agents over that state; and a deterministic constraint-repair stage that turns evidence-backed, near-satisfied relations into exactly satisfied ones under strict movement budgets, with rollback on failure. On 150 TriGeoBench figures, GeoConstruct improves both visual similarity and, by an order of magnitude, geometric fidelity over closed-source end-to-end baselines, and the recovered programs support verified local edits and accurate geometric queries. Future work includes the open-source backbone comparison outlined in Sec. IV-F, richer constraint families (equal lengths, midpoints, tangency) in the repair stage, and natural-language editing built on the reuse interface.

## 中文翻译

我们提出了 GeoConstruct，一个把栅格几何图形转换为可编辑、可编译 TikZ 代码的系统。其设计基于三部分：以持久化几何证据状态记录每条测量与决策的来源；由 Supervisor 在该状态之上统一编排 CV 工具与专用智能体的 Supervisor-Worker 架构；以及确定性的约束修复阶段，它在严格位移预算内把有证据支撑、近似满足的关系变为严格满足，失败则回滚。在 TriGeoBench 测试集上，GeoConstruct 在视觉相似性与几何保真度两方面均优于其他基线，且还原出的程序支持经验证的局部编辑与准确的几何查询。

---

# 附：仅实验章节引用的三条指标文献（恢复正文时并入主文件 References）

[12] Z. Wang, A. C. Bovik, H. R. Sheikh, and E. P. Simoncelli, "Image quality assessment: From error visibility to structural similarity," IEEE Trans. Image Process., vol. 13, no. 4, pp. 600–612, 2004. [Online]. Available: https://doi.org/10.1109/TIP.2003.819861

[13] A. Radford, J. W. Kim, C. Hallacy, A. Ramesh, G. Goh, S. Agarwal, G. Sastry, A. Askell, P. Mishkin, J. Clark, G. Krueger, and I. Sutskever, "Learning transferable visual models from natural language supervision," in Proc. Int. Conf. Mach. Learn. (ICML), 2021. [Online]. Available: https://arxiv.org/abs/2103.00020

[14] M. Oquab, T. Darcet, T. Moutakanni, H. Vo, M. Szafraniec, V. Khalidov, P. Fernandez, D. Haziza, F. Massa, A. El-Nouby, et al., "DINOv2: Learning robust visual features without supervision," Trans. Mach. Learn. Res. (TMLR), 2024. [Online]. Available: https://arxiv.org/abs/2304.07193
