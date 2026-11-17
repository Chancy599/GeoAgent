# Abstract

Geometric figures in textbooks and exams are often distributed as raster images. Recovering them as executable code makes them editable and reusable. Existing approaches, including end-to-end multimodal models, specialized models fine-tuned on large-scale data, and multi-agent systems with render-and-verify loops, primarily emphasize visual similarity. However, small angular deviations and distorted segment ratios can violate geometric relationships while remaining difficult to detect with image-based similarity metrics. High visual similarity alone therefore does not ensure geometric correctness. We argue that figure-to-code conversion should target not only visual similarity but also geometric fidelity. We present **GeoConstruct**, a system centered on a persistent Geometric Evidence State (GES), over which a Supervisor dynamically orchestrates specialized sub-agents and deterministic tools. Computer-vision tools supply pixel-level measurements of primitives and labels; a Geometry Agent consolidates such measurements into geometric objects and relations; a Code Agent produces parameterized TikZ code and, against predefined tolerance thresholds, examines candidate constraints such as parallelism and perpendicularity and proposes small coordinate corrections; and a Critic Agent locates discrepancies between the original figure and the rendered output. All measurements, decisions, and findings are written back to the GES as verified evidence. GeoConstruct outperforms the evaluated baselines in both visual similarity and geometric fidelity on TriGeoBench, with the latter measured by our geometry-level evaluation protocol, which covers angular error, segment-ratio error, and point error, among other metrics.

教科书与试卷中的几何图形通常仅以栅格图像形式呈现。将其还原为可执行代码后，图形便可被编辑和复用。现有方法——包括端到端多模态模型、在大规模数据上微调的专用模型，以及带有"渲染—验证"循环的多智能体系统——主要关注视觉相似性。然而，微小的角度偏差和线段比例失真可能破坏几何关系，却难以被基于图像的相似性指标检测出来。因此，仅凭高视觉相似性并不能确保几何正确性。我们认为，图形到代码的转换不应只追求视觉相似性，还应追求几何保真度。为此，我们提出 **GeoConstruct**：系统以持久化的几何证据状态（GES）为中心，由 Supervisor 在其上动态编排各专用子智能体与确定性工具。CV 工具提供图元与标签的像素级测量；Geometry Agent 将这类测量整合为几何对象与几何关系；Code Agent 编写参数化 TikZ 代码，并依据预设容差阈值检查候选的平行、垂直等几何约束、提出小幅坐标修正；Critic Agent 定位原图与渲染结果之间的差异。所有测量、决策与结论都会回写至 GES，成为已验证的证据。GeoConstruct 在视觉相似性与几何保真度两方面均优于所评估的基线方法在 TriGeoBench 上；其中几何保真度由我们提出的几何级评估协议衡量，涵盖角度误差、长度比例误差与点位误差等多项指标。

---

# I. Introduction

Geometric figures are the visual backbone of mathematics education. In textbooks, exercise books, and examination papers, however, they are almost always stored and presented as raster images. A raster figure can be displayed, but it cannot be edited. A teacher who wants to change a label, add an auxiliary point, or add or remove a segment must redraw the figure from scratch. Recovering the figure as executable code removes this barrier: once a figure exists as a parameterized program, it can be edited, restyled, re-rendered, and reused in new material. This paper studies the conversion of raster geometric figures into editable, compilable TikZ code.

The task is harder than it looks. A geometric figure is not a generic image; it is the rendering of an underlying geometric construction. Two renderings can be almost indistinguishable to the eye while encoding different geometric relations. Fig. 1 shows a real case from our evaluation set: a triangle ABC with a segment from A to a point D on BC. A strong end-to-end baseline reproduces the drawing almost exactly, yet its code draws angle BAC as 52.56° where the true figure has 64.83°. Such errors are invisible to image-level metrics, but they change the geometric relations of the figure. Methods that optimize for visual similarity alone therefore produce code that looks right but computes wrong. Once such code is reused, queried for an angle, edited to add a construction, or repurposed in a new exercise, the hidden errors surface. We argue that figure-to-code conversion should target geometric fidelity in addition to visual similarity, and that the recovered program should remain correct under editing.

Existing approaches leave this gap open. End-to-end multimodal large language models (MLLMs) generate TikZ in one shot [[1\]](https://arxiv.org/abs/2610.27626), [[2\]](https://arxiv.org/abs/2603.22687), but coordinate regression from pixels is imprecise and errors have no chance to be corrected. Models fine-tuned on large image-code corpora, such as FigCodifier [[4\]](https://arxiv.org/abs/2505.10557), MatPlotCode [[5\]](https://arxiv.org/abs/2510.11718), and GeoTikzBridge [[2\]](https://arxiv.org/abs/2603.22687), improve visual fidelity, yet their training and selection signals, CLIP-style image similarity, still measure appearance rather than geometric relations. Multi-agent systems with render-and-verify loops, most notably Geo-Code [[3\]](https://arxiv.org/abs/2602.07749), close the loop with visual feedback, but the feedback itself is computed from pixel comparisons such as Chamfer and Hausdorff distances, so the same blind spot remains: none of these systems explicitly measures or enforces the geometric relations that make a figure mathematically valid.

We present GeoConstruct, a system that treats figure-to-code conversion as evidence-driven reconstruction rather than one-shot generation. Its center is a persistent Geometric Evidence State (GES), a structured store in which every measurement, decision, and finding is recorded with provenance and confidence status. Over this shared state, a Supervisor dynamically orchestrates specialized sub-agents and deterministic tools: classical computer-vision (CV) operators supply pixel-level measurements of primitives and labels; a Geometry Agent consolidates fragmented measurements into geometric objects and relations; a Code Agent writes parameterized TikZ code on top of the measured coordinates, examines candidate constraints such as parallelism, perpendicularity, and collinearity against predefined tolerance thresholds, and proposes small coordinate corrections; and a Critic Agent compares each rendered version with the original figure and issues actionable revision requests. On the figure in Fig. 1, GeoConstruct recovers angle BAC to its true 64.83°, using the same backbone model as the baseline.

Our contributions are as follows.

1) **Architecture.** We propose a supervisor-worker multi-agent architecture organized around a persistent Geometric Evidence State. All agents read from and write to one auditable state, which keeps measurements, decisions, and version history consistent across iterations.

2) **Geometric constraint repair.** We introduce a deterministic post-generation repair mechanism that extracts near-satisfied relations (e.g., within 0.5° of parallel or perpendicular) as candidates, verifies them against image evidence, and solves for minimal coordinate corrections under explicit displacement and length-change budgets.

3) **Evaluation and findings.** We define a geometry-level evaluation protocol covering angle error, segment-ratio error, aligned point error, segment F1, and a whole-figure pass rate. On the TriGeoBench test set [[1\]](https://arxiv.org/abs/2610.27626), GeoConstruct substantially outperforms the evaluated baselines in both visual similarity and geometric fidelity, and the recovered programs directly support editing and reuse.

## 中文翻译

几何图形是数学教育的视觉基础。然而在教材、练习册和试卷中，它们几乎总是以栅格图像的形式存储和呈现。栅格图可以展示，却无法编辑。老师若想改一个标签、添加一个辅助点或增减一条线段，只能从头重画。把图形还原为可执行代码可以消除这一障碍：图形一旦成为参数化程序，就可以编辑、改样式、重新渲染并复用到新材料中。本文研究将栅格几何图形转换为可编辑、可编译的 TikZ 代码。

这项任务比看上去更难。几何图形不是普通图像，而是底层几何构造的渲染结果。两个渲染结果在肉眼看来几乎难以区分，却可能编码着不同的几何关系。图 1 给出了评测集中的一个真实案例：三角形 ABC 带一条从顶点 A 到边 BC 上点 D 的线段。一个较强的端到端基线把图画得几乎一模一样，但其代码把角 BAC 画成 52.56°，而真实图形是 64.83°。这类误差对图像级指标不可见，却改变了图形的几何关系。因此，只优化视觉相似性的方法会产出"看着对、算着错"的代码。这类代码一旦被复用，无论是查询角度、编辑构造还是改写成新题目，隐藏的错误就会暴露。我们认为，图形到代码的转换除视觉相似性外，还应追求几何保真度，且还原出的程序应当可以正确编辑。

现有方法都存在这一缺口。端到端多模态大语言模型（MLLM）一次性生成 TikZ [[1\]](https://arxiv.org/abs/2610.27626), [[2\]](https://arxiv.org/abs/2603.22687)，但从像素回归坐标本身不精确，且错误没有机会被纠正。在大规模图像-代码语料上微调的模型（如 FigCodifier [[4\]](https://arxiv.org/abs/2505.10557)、MatPlotCode [[5\]](https://arxiv.org/abs/2510.11718) 和 GeoTikzBridge [[2\]](https://arxiv.org/abs/2603.22687)）提升了视觉保真度，但其训练与筛选信号，即 CLIP 式图像相似度，衡量的仍是外观而非几何关系。带"渲染-验证"循环的多智能体系统（以 Geo-Code [[3\]](https://arxiv.org/abs/2602.07749) 为代表）用视觉反馈闭合了环路，但反馈本身由 Chamfer、Hausdorff 距离等像素比较计算，同样的盲区依然存在：这些系统都没有显式测量或强制保证使图形在数学上成立的几何关系。

我们提出 GeoConstruct，把图形到代码的转换视为证据驱动的重建，而非一次性生成。系统的中心是持久化的几何证据状态（GES），一个结构化存储，每条测量、决策与结论都带来源与置信状态记录在案。在这一共享状态之上，Supervisor 动态编排各专用子智能体与确定性工具：经典计算机视觉（CV）算子提供图元与标签的像素级测量；Geometry Agent 把碎片化的测量整合为几何对象与几何关系；Code Agent 在实测坐标之上编写参数化 TikZ 代码，并依据预设容差阈值检查平行、垂直、共线等候选约束，提出小幅坐标修正；Critic Agent 将每个渲染版本与原图比对，给出可执行的修改意见。在图 1 这张图上，GeoConstruct 使用与该基线相同的骨干模型，把角 BAC 恢复到真实的 64.83°。

本文贡献如下：

1）**架构**：提出以持久化几何证据状态为中心的 Supervisor-Worker 多智能体架构。所有智能体读写同一份可审计的状态，使各轮迭代中的测量、决策与版本历史保持一致。

2）**几何约束修复**：提出确定性的生成后修复机制，从近似满足的关系（如与平行、垂直相差 0.5° 以内）中提取候选，经图像证据核验后，在显式的位移与边长预算下求解最小坐标修正。

3）**评估与发现**：提出几何级评估协议，涵盖角度误差、长度比例误差、对齐后点位误差、线段 F1 与整图通过率，在 TriGeoBench 测试集 [[1\]](https://arxiv.org/abs/2610.27626) 上，GeoConstruct 在视觉相似性与几何保真度两方面均显著优于其他基线，还原出的程序可直接支持编辑与复用。

---

# II. Related Work

## A. Image-to-Code Generation

Image-to-code generation translates raster images into executable programs. General-purpose MLLMs can already generate TikZ in one shot [[1\]](https://arxiv.org/abs/2610.27626), but regressing coordinates from pixels is imprecise and the errors go uncorrected. Fine-tuning on large image-code corpora improves visual fidelity [[6\]](https://arxiv.org/abs/2405.15306), [[4\]](https://arxiv.org/abs/2505.10557), [[5\]](https://arxiv.org/abs/2510.11718), [[2\]](https://arxiv.org/abs/2603.22687), yet these models still learn a pixel-to-code mapping whose training signals measure appearance rather than geometric relations. Multi-agent systems instead close the loop with render-and-verify feedback. Geo-Code [[3\]](https://arxiv.org/abs/2602.07749), the representative of this line, first anchors primitives at the pixel level and then iteratively refines the code under Chamfer- and Hausdorff-based feedback; however, the feedback still compares pixels rather than geometric relations, and the system relies on textual constraints paired with the image to resolve geometric ambiguities. Our task, in contrast, takes only the raster image as input, without any textual description of the construction.

## B. Geometric Image Editing

Geometric image editing modifies an existing figure, such as adding an auxiliary line or changing a label. Recent systems interleave such edits with the reasoning process [[7\]](https://arxiv.org/abs/2406.09403), [[8\]](https://arxiv.org/abs/2511.04460), [[9\]](https://arxiv.org/abs/2509.25866), [[10\]](https://arxiv.org/abs/2510.14958). Because edits are expressed most reliably as code, editing a raster figure first requires recovering it as a program, which makes image-to-code the enabling step for downstream editing.

## 中文翻译

**A. 图像到代码生成。** 图像到代码生成把栅格图像转换为可执行程序。通用 MLLM 已能一次性生成 TikZ [[1\]](https://arxiv.org/abs/2610.27626)，但从像素回归坐标并不精确，且错误没有机会被纠正。在大规模图像-代码语料上微调可以提升视觉保真度 [[6\]](https://arxiv.org/abs/2405.15306), [[4\]](https://arxiv.org/abs/2505.10557), [[5\]](https://arxiv.org/abs/2510.11718), [[2\]](https://arxiv.org/abs/2603.22687)，但这些模型学习的仍是像素到代码的映射，其训练与筛选信号衡量的是外观而非几何关系。多智能体系统则用反馈闭合环路。作为这一路线的代表，Geo-Code [[3\]](https://arxiv.org/abs/2602.07749) 先在像素级锚定图元，再在基于 Chamfer 与 Hausdorff 距离的"渲染-验证"反馈下迭代改进代码；然而其反馈比较的仍是像素而非几何关系，且系统依赖与图像配对的文本约束来消解几何歧义。相比之下，我们的任务只以栅格图像为输入，没有任何关于构造的文本描述。

**B. 几何图像编辑。** 几何图像编辑是对已有图形做修改，例如添加辅助线或更改标签。近期系统把这类编辑与推理过程交织进行 [[7\]](https://arxiv.org/abs/2406.09403), [[8\]](https://arxiv.org/abs/2511.04460), [[9\]](https://arxiv.org/abs/2509.25866), [[10\]](https://arxiv.org/abs/2510.14958)。由于编辑操作以代码形式表达最为可靠，编辑栅格图形的前提是先把图形还原为程序，图像到代码因此成为下游编辑应用的使能步骤。

---

# III. Method

## A. Overview

GeoConstruct treats figure-to-code conversion as evidence-driven reconstruction. Given only a raster figure, the system measures the image with classical CV operators, consolidates the measurements into a geometric construction, writes parameterized TikZ on top of the measured coordinates, repairs the coordinates deterministically, and verifies every rendered version against the original figure. Fig. 2 shows the overall architecture.

[图 2：系统架构图（待绘）]

Fig. 2 will depict the module composition of GeoConstruct and the relations among the modules: CV operators that measure segments, labels, and right-angle marks from the input image; a Geometry Agent that consolidates the measurements into a construction plan; a Code Agent that writes and revises parameterized TikZ; a deterministic constraint-repair stage followed by compilation, rendering, and topology checks; and a Critic Agent that compares each rendering with the original figure. All modules read from and write to one persistent Geometric Evidence State (GES), and a Supervisor sits above them and dynamically dispatches measurement, generation, and revision in a supervisor-worker fashion.

## B. Geometric Evidence State

The GES is the center of the system. It is a structured store in which every measurement, decision, and finding is recorded together with its provenance (which module produced it and from which image evidence) and its confidence status (proposed, verified, or rejected). Construction plans, verified edges and angle marks, and the check results of every code version are persisted in the GES, so later iterations build on verified evidence rather than on regenerated guesses. Agents propose, and deterministic tools decide: every agent claim, such as a footpoint or a right-angle mark, is accepted only after it is verified against the strokes of the source image. This design keeps all modules consistent across iterations and makes the whole reconstruction process auditable.

## C. Visual Measurement and Coordinate Contract

CV operators supply the pixel-level evidence: segment detection fits the line strokes, label detection separates text from line art and binds each visible label to its measured point, and right-angle detection locates the small square marks. The measured coordinates enter code generation through a coordinate contract: pixel coordinates are uniformly scaled, translated, and flipped along the y axis, and are written into the TikZ source with three decimals, while the original measurements keep full precision inside the GES. When a verified footpoint lies within 6 px of its projection onto the supporting line, the projected coordinate is written and the raw measurement is preserved. A managed label must reference the same-name coordinate; redefining a managed coordinate or applying a coordinate-system transform triggers a retry. The model is responsible for connectivity, line styles, label placement, and auxiliary constructions, while the numeric coordinates come from measurement.

## D. Geometry Agent: Consolidating the Construction

Before any code is written, the Geometry Agent reviews the original figure and organizes the construction: it selects the measured point that each label refers to, states which points are connected and which edges are dashed, and submits proposed footpoints together with the two rays of each right-angle mark. The program verifies these proposals against the strokes of the source image and keeps only the evidence-backed requirements. When a fitted segment is truncated by dashed gaps, intersections of nearby lines supplement the endpoint candidates; when the generic detector misses a right-angle mark at a measured footpoint, the program searches for the small square strokes near the footpoint to confirm the mark orientation.

## E. Code Agent: Writing Parameterized TikZ

The Code Agent writes or revises TikZ code from the shared points, required edges, line styles, and angle-mark rays recorded in the GES, and additionally handles auxiliary constructions that are not covered by the coordinate contract. The program checks that the produced code actually uses the shared endpoints, and accepts collinear segments of the same line style as one logical edge.

## F. Deterministic Constraint Repair

After generation, a deterministic repair stage turns evidence-backed, near-satisfied relations into exactly satisfied ones. Candidates are extracted from the generated coordinates and segments. Let $\theta(u,v)=\arccos\frac{u\cdot v}{\lVert u\rVert\,\lVert v\rVert}$ denote the angle between the direction vectors $u$ and $v$ of two segments. The segments form a perpendicular candidate if $\lvert\theta(u,v)-90^\circ\rvert\le\tau$, and a parallel candidate if $\theta(u,v)\le\tau$, with tolerance $\tau=0.5^\circ$:

$$\lvert\theta(u,v)-90^\circ\rvert\le\tau \ \text{(perpendicular)},\qquad \theta(u,v)\le\tau \ \text{(parallel)}. \tag{1}$$

Collinearity candidates come from two drawn edges that share an endpoint and turn by at most $8^\circ$, and every candidate must be verified by continuous strokes in the source image.

Given the accepted candidate set, the repair solves for minimal coordinate corrections:

$$\min_{\{p_i'\}}\ \sum_{i}\lVert p_i'-p_i\rVert_2 \quad \text{s.t.}\quad u_{ij}\cdot u_{kl}=0\ \forall\,(ij,kl)\in\mathcal{C}_{\perp},\ \ u_{ij}\times u_{kl}=0\ \forall\,(ij,kl)\in\mathcal{C}_{\parallel}\cup\mathcal{C}_{\mathrm{col}},\ \ \lVert p_i'-p_i\rVert\le 0.013\,D,\ \ \frac{\lvert\lvert e\rvert'-\lvert e\rvert\rvert}{\lvert e\rvert}\le 0.035, \tag{2}$$

where $p_i$ and $p_i'$ are the coordinates of point $i$ before and after repair, $D$ is the diagonal length of the figure, $\lvert e\rvert$ an edge length, and $\mathcal{C}_{\perp}$, $\mathcal{C}_{\parallel}$, $\mathcal{C}_{\mathrm{col}}$ the accepted perpendicular, parallel, and collinear relation sets. The single-point displacement is thus capped at 1.3% of the figure diagonal and the edge-length change at 3.5%. The solver additionally protects verified point-line relations, equal lengths, midpoints, point-on-segment incidence, collinear order, and segment crossings, and non-target direction relations already within $0.1^\circ$ must remain within that tolerance. Because TeX stores coordinates on an integer grid (1 sp = 1/65536 pt), acceptance is checked after compilation by reading back the integer point anchors: a perpendicular relation passes only if the integer dot product is exactly zero, and a parallel or collinear relation only if the integer cross product is exactly zero. If the search, the verification, or the final compilation fails, the repair rolls back to the pre-repair code, so the repair never degrades a figure.

## G. Critic Review and Supervisor Scheduling

After each successfully rendered version, the Critic Agent compares the rendering with the original figure and checks missing strokes, wrong connections, dashed endpoints, angle-mark orientation, labels, and line width. It returns actionable revision requests; when a connection or a binding is ambiguous, it may confirm one from the measurement candidates recorded in the GES, or abstain. Confirmations trigger re-verification of the code. The Supervisor reads the GES and dynamically dispatches supplementary measurement or revision where the evidence is insufficient. When the iteration budget is exhausted while must-fix issues remain open, the artifact is marked as partial rather than finished.

## 中文翻译

**A. 概述。** GeoConstruct 把图形到代码的转换视为证据驱动的重建。系统仅以栅格图为输入：先用经典 CV 算子测量图像，再把测量整合为几何构造，在实测坐标之上编写参数化 TikZ，然后进行确定性的坐标修复，并把每个渲染版本与原图核对。图 2 展示系统的总体架构。

[图 2：系统架构图（待绘）]

图 2 将展示 GeoConstruct 的模块组成及各模块间的关系：CV 算子从输入图像测量线段、标签与直角标记；Geometry Agent 把测量整合为构造计划；Code Agent 编写并修订参数化 TikZ；确定性的约束修复阶段之后是编译、渲染与拓扑检查；Critic Agent 把每个渲染版本与原图比对。所有模块读写同一份持久化的几何证据状态（GES），Supervisor 位于其上，以 Supervisor-Worker 方式动态调度测量、生成与修订。

**B. 几何证据状态。** GES 是系统的中心。它是一个结构化存储，每条测量、决策与结论都与其来源（由哪个模块、依据哪份图像证据产生）和置信状态（已提议、已验证或已拒绝）一起记录。构造计划、已验证的边与角标、以及每版代码的检查结果都持久保存在 GES 中，后续迭代建立在已验证的证据之上，而不是重新猜测。智能体负责提议，确定性工具负责裁决：垂足、直角标记等每条智能体声明，只有经原图笔画核验后才会被接受。这一设计使各模块在迭代间保持一致，并使整个重建过程可审计。

**C. 视觉测量与坐标契约。** CV 算子提供像素级证据：线段检测拟合直线笔画；标签检测把文字与线稿分离，并把每个可见标签绑定到其实测点；直角检测定位小方框标记。实测坐标通过坐标契约进入代码生成：像素坐标经统一缩放、平移并沿 y 轴翻转后，以三位小数写入 TikZ 源码，原始测量在 GES 内保留完整精度。经核验的垂足离其在支撑线上的投影不超过 6 像素时，写入投影坐标并保留原测量。受管理的标签必须引用同名坐标；重定义受管理坐标或施加坐标系变换会触发重试。模型负责连接、线型、标签排版与辅助构造，数值坐标来自测量。

**D. Geometry Agent：整合同一构造。** 在编写任何代码之前，Geometry Agent 核对原图并整理构造：为每个标签选择对应的实测点，说明哪些点相连、哪些边是虚线，并提交垂足提议及每个直角标记的两条射线。程序用原图笔画核验这些提议，只保留有证据支撑的要求。拟合线段因虚线间隙被截短时，邻近线的交点补充端点候选；通用检测在已测垂足处漏检直角标记时，程序在垂足附近搜索小方框笔画以确认标记朝向。

**E. Code Agent：编写参数化 TikZ。** Code Agent 根据 GES 中记录的共享点、必画边、线型与角标射线编写或修订 TikZ 代码，并处理坐标契约之外的辅助构造。程序检查生成的代码确实使用了共享端点，并接受同线型的共线分段作为同一条逻辑边。

**F. 确定性约束修复。** 生成之后，确定性的修复阶段把有证据支撑、近似满足的关系变为严格满足。候选从生成的坐标与线段中提取。记 $\theta(u,v)$ 为两条线段方向向量 $u$、$v$ 的夹角。夹角与 90° 之差不超过 $\tau$ 的两条线段构成垂直候选，夹角不超过 $\tau$ 的构成平行候选，容差 $\tau=0.5^\circ$，见式 (1)。共线候选来自共享端点、转折不超过 8° 的两条已绘制边，且每条候选都必须通过原图连续笔画的核验。

给定已接受的候选集合，修复按式 (2) 求解最小坐标修正，其中 $p_i$、$p_i'$ 为点 $i$ 修复前后的坐标，$D$ 为图形对角线长度，$\lvert e\rvert$ 为边长，$\mathcal{C}_{\perp}$、$\mathcal{C}_{\parallel}$、$\mathcal{C}_{\mathrm{col}}$ 为已接受的垂直、平行与共线关系集合。单点位移上限为图形对角线的 1.3%，边长变化上限为 3.5%。求解器还保护已验证的点线关系、等长、中点、点在线段内、共线顺序与线段交叉，原本在 0.1° 以内的非目标方向关系仍须保持在该容差内。由于 TeX 在整数网格上存储坐标（1 sp = 1/65536 pt），验收在编译后通过回读整数点锚进行：垂直关系仅当整数点积严格为零时通过，平行与共线关系仅当整数叉积严格为零时通过。若搜索、核验或最终编译失败，修复回滚到修复前代码，因此修复不会让图形变差。

**G. Critic 复核与 Supervisor 调度。** 每份成功渲染的新版本之后，Critic Agent 把渲染结果与原图比对，检查漏画、错接、虚线端点、角标方向、标签与线宽，并返回可执行的修改意见。遇到连接或绑定歧义时，它可以从 GES 记录的测量候选中确认一个，也可以弃权；确认结果会触发代码复验。Supervisor 读取 GES，在证据不足处动态调度补测或修订。当迭代预算耗尽而必须修复的问题仍未关闭时，产物被标记为 partial，而非视为完成。

---

# IV. Experiments

## A. Setup

We evaluate on a fixed set of 150 figures from the TriGeoBench test split [[1\]](https://arxiv.org/abs/2610.27626). Four end-to-end MLLMs serve as baselines: haiku-5.5, gpt-5.4, qwen3.5-plus, and glm-5.3-flash, each generating TikZ from the image in one shot. GeoConstruct uses haiku-5.5 as the backbone model of all its agents, so the haiku-5.5 baseline isolates the contribution of the framework from that of the backbone. All methods are evaluated on the same 150 figures under the same protocol. Fine-tuned image-to-code models [[6\]](https://arxiv.org/abs/2405.15306), [[4\]](https://arxiv.org/abs/2505.10557), [[5\]](https://arxiv.org/abs/2510.11718), [[2\]](https://arxiv.org/abs/2603.22687) will be added as further baselines, and Table I reserves rows for them.

## B. Evaluation Protocol and Metrics

**Visual similarity.** SSIM is computed between the grayscale renderings on a 1000 px white canvas; the CLIP and DINO scores are the cosine similarities of ViT-L/14@224 and DINOv2-base CLS features between the original figure and the rendering. All three are averaged over figures with equal weight and multiplied by 100.

**Geometry-level protocol.** Since no existing benchmark measures the geometric fidelity of recovered figures, we define a label-bound evaluation protocol. A frozen geometry reference is built from the benchmark source code alone: visible labels with explicitly bound coordinates become reference points; a named segment is a drawn straight segment whose two endpoints are both labeled and at least 95% of its length is supported by strokes; an angle item is recorded for two segments sharing a labeled endpoint when the angle is at least $5^\circ$; a ratio item is recorded for every non-degenerate segment pair sharing an endpoint, with the ratio direction fixed by label order. Predictions are matched to reference items by label name. Missing labels, missing or degenerate edges, and unparsable code are recorded as unavailable and are never replaced by zero error. Angle MAE and ratio MRE are computed on the items measurable by all compared methods (common measurable items), first averaged within each figure and then averaged over figures with equal weight:

$$\mathrm{MAE}=\frac{1}{\lvert F\rvert}\sum_{f\in F}\frac{1}{\lvert A_f\rvert}\sum_{a\in A_f}\lvert\hat{\theta}_a-\theta_a\rvert, \tag{3}$$

$$\mathrm{MRE}=\frac{1}{\lvert F\rvert}\sum_{f\in F}\frac{1}{\lvert R_f\rvert}\sum_{r\in R_f}\left\lvert\frac{\hat{r}_r}{r_r}-1\right\rvert\times 100\%, \tag{4}$$

where $F$ is the set of figures, $A_f$ and $R_f$ are the common measurable angle and ratio items of figure $f$, $\hat{\theta}_a$ and $\hat{r}_r$ are the values measured from the generated code, and $\theta_a$ and $r_r$ are the reference values.

Segment F1 compares the named segment set of the prediction with that of the reference, merging equivalent collinear subsegments, and computes

$$F1=\frac{2PR}{P+R}, \tag{5}$$

where $P$ and $R$ are precision and recall over the named segment sets.

The aligned point error measures shape fidelity after global differences are removed. The generated points are aligned to the reference by least-squares fitting of translation, rotation, and uniform scaling over the shared labels, and the error of figure $f$ is

$$e_f=\frac{100\%}{N_f}\sum_{i=1}^{N_f}\min\!\left(1,\frac{d_i}{D_f}\right), \tag{6}$$

where $N_f$ is the number of reference labeled points, $D_f$ the distance between the two farthest reference points, and $d_i$ the distance of point $i$ to its reference position after alignment. A missing point contributes 100%, and a figure without enough shared points for a valid alignment scores 100%.

The whole-figure pass rate counts a figure as passed only if its code compiles, the named segment set matches exactly, and every reference angle and ratio is measurable with absolute angle error at most $1^\circ$ and relative ratio error at most 2%.

## C. Main Results

Table I lists the main comparison on the 150 figures, and Fig. 3 visualizes it.

TABLE I
Comparison of figure-to-code conversion on 150 TriGeoBench figures.

| Method | SSIM ×100 ↑ | CLIP ×100 ↑ | DINO ×100 ↑ | Angle MAE (°) ↓ | Ratio MRE (%) ↓ | Segment F1 (%) ↑ | Point error (%) ↓ | Pass rate (1°/2%) ↑ |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| haiku-5.5 | 90.5368 | 97.4663 | 96.8133 | 1.958559 | 5.494337 | 95.6761 | 1.8604 | 57/150 (38.00%) |
| gpt-5.4 | 90.5708 | 97.2459 | 96.2508 | 2.539270 | 7.415228 | 90.0352 | 2.3993 | 6/150 (4.00%) |
| qwen3.5-plus | 90.3925 | 96.8428 | 95.3246 | 5.700388 | 18.012649 | 96.4916 | 5.9289 | 6/150 (4.00%) |
| glm-5.3-flash | 90.2170 | 97.8734 | 97.0237 | 4.007424 | 16.067963 | 93.9367 | 3.4618 | 4/150 (2.67%) |
| Fine-tuned model (reserved) | — | — | — | — | — | — | — | — |
| Fine-tuned model (reserved) | — | — | — | — | — | — | — | — |
| **GeoConstruct (ours)** | **94.3554** | **99.3702** | **98.9812** | **0.100519** | **0.315609** | **99.9733** | **0.0935** | **129/150 (86.00%)** |

Note: Angle MAE uses 2,585 common measurable angles from 149 figures and ratio MRE uses 3,124 common measurable ratios from 149 figures; missing items are excluded and errors are not capped. The other columns use all 150 figures. The reserved rows are placeholders to be filled with the results of fine-tuned models.

[图 3：图像转代码对比实验图（待绘）]

Fig. 3 will visualize the comparison in Table I: for each method (the four end-to-end baselines, GeoConstruct, and the fine-tuned models once available), it will place the visual scores (SSIM, CLIP, DINO) and the geometry-level results (angle MAE, ratio MRE, segment F1, aligned point error, and whole-figure pass rate) side by side, so that the gap between visual similarity and geometric fidelity is visible at a glance.

GeoConstruct achieves the best result on every metric. Compared with haiku-5.5, the strongest baseline and also our backbone model, the angle MAE drops from 1.96° to 0.10°, the ratio MRE from 5.49% to 0.32%, and the whole-figure pass rate rises from 38.00% to 86.00%. The visual scores improve at the same time, with SSIM rising from 90.54 to 94.36, which shows that the geometric gains do not come at the cost of appearance. Since GeoConstruct and the haiku-5.5 baseline share the same backbone, these gaps measure the contribution of the framework itself. The reserved rows will be filled with fine-tuned image-to-code models, whose results will be compared under the identical protocol.

## D. Ablation Study

Table II reports the ablation on the same 150 figures. Removing the constraint repair replays the identical generated code with the repair stage disabled; removing the Critic takes the version that passes compilation and basic checks before the first review, and applies the same repair to it. The haiku-5.5 row is the end-to-end baseline that uses the same backbone model as our framework.

TABLE II
Ablation on 150 figures. All settings share the same generation code and scoring rules.

| Setting | SSIM ×100 ↑ | CLIP ×100 ↑ | DINO ×100 ↑ | Angle MAE (°) ↓ | Ratio MRE (%) ↓ | Segment F1 (%) ↑ | Point error (%) ↓ | Pass rate (1°/2%) ↑ |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| **GeoConstruct (full)** | **94.3554** | **99.3702** | 98.9812 | **0.104973** | **0.368299** | **99.9733** | **0.0935** | **129/150 (86.00%)** |
| w/o constraint repair | 94.2784 | 99.3698 | **98.9869** | 0.121325 | 0.388483 | 99.8673 | 0.0991 | 125/150 (83.33%) |
| w/o Critic | 94.2453 | 99.2107 | 98.7866 | 0.216081 | 0.646271 | 99.4810 | 0.1826 | 121/150 (80.67%) |
| haiku-5.5 (end-to-end backbone) | 90.5368 | 97.4663 | 96.8133 | — | — | 95.6761 | 1.8604 | 57/150 (38.00%) |

Note: MAE and MRE use 4,317 angles and 5,285 ratios that are commonly measurable by the three ablation settings, covering 150 figures each; each table computes these two metrics on its own common items, so the haiku-5.5 row marks them as —. The other columns use all 150 figures under the identical protocol.

Both components contribute. Removing the Critic causes the largest geometric degradation: the angle MAE rises from 0.105° to 0.216°, the segment F1 drops from 99.97% to 99.48%, and four more figures fail the whole-figure check. Removing the constraint repair keeps the average errors close, because the coordinate contract already places points accurately, but the pass rate drops from 86.00% to 83.33%: without repair, near-satisfied relations remain approximate and fail the strict 1°/2% check. The end-to-end haiku-5.5 row confirms that the framework, rather than the backbone, accounts for most of the gap.

## E. Figure Editing

We further evaluate whether the recovered programs support verified local editing. Three edit operations are applied to the code produced by every method through one shared deterministic editor: relabeling a point, adding a midpoint on a drawn edge, and toggling an edge between solid and dashed. An edit is accepted at the source level only if its target can be located uniquely and all unrelated primitives are preserved; midpoint edits are additionally verified after compilation by reading back the coordinates and checking $2M=A+B$ within 2 sp per axis. Acceptance is measured at the source level on all 150 figures, and by compilation and coordinate read-back on a fixed sample of 30 figures. Fig. 4 will report the per-operation acceptance of each method.

[图 4：图形编辑对比实验图（待绘）]

Fig. 4 will compare, for each of the three edit operations (relabel, add midpoint, toggle solid/dashed) and each method (the four end-to-end baselines and GeoConstruct), the source-level acceptance on the 150 figures and the compile-and-readback acceptance on the 30-figure sample, showing whether each method produces code that remains correct under editing.

## 中文翻译

**A. 实验设置。** 我们在 TriGeoBench 测试划分 [[1\]](https://arxiv.org/abs/2610.27626) 的固定 150 张图上评测。四个端到端 MLLM 作为基线：haiku-5.5、gpt-5.4、qwen3.5-plus 与 glm-5.3-flash，均从图像一次性生成 TikZ。GeoConstruct 的所有智能体使用 haiku-5.5 作为骨干模型，因此 haiku-5.5 基线可以把框架的贡献与骨干模型的贡献区分开。所有方法在同一批 150 张图、同一协议下评测。微调类图像到代码模型 [[6\]](https://arxiv.org/abs/2405.15306), [[4\]](https://arxiv.org/abs/2505.10557), [[5\]](https://arxiv.org/abs/2510.11718), [[2\]](https://arxiv.org/abs/2603.22687) 将作为补充基线加入，表 I 为其预留了行。

**B. 评测协议与指标。** 视觉相似性：SSIM 在 1000 px 白底画布上的灰度渲染图之间计算；CLIP 与 DINO 分数为原图与渲染图在 ViT-L/14@224 和 DINOv2-base CLS 特征上的余弦相似度。三者均按图等权平均并乘以 100。

几何级协议：现有基准都不衡量还原图形的几何保真度，因此我们定义了按标签绑定的评测协议。冻结的几何参考仅由基准源码构建：具有显式绑定坐标的可见标签成为参考点；具名线段是两端均有标签、且至少 95% 长度有笔画支撑的实际直线段；共享带标签端点、夹角不小于 5° 的两条线段记录一个角度项；共享端点的所有非退化线段对记录长度比项，比例方向按标签顺序固定。预测按标签名与参考项匹配。缺标签、缺边、退化边与无法解析的代码记为不可用，不以零误差替代。角度 MAE 与比例 MRE 在所有对比方法共同可测的项上计算，先在每张图内平均，再按图等权平均，见式 (3)、(4)，其中 $F$ 为图的集合，$A_f$、$R_f$ 为图 $f$ 的共同可测角度项与比例项，$\hat{\theta}_a$、$\hat{r}_r$ 为从生成代码测得的值，$\theta_a$、$r_r$ 为参考值。

线段 F1 比较预测与参考的具名线段集合，等价的共线分段合并处理，按式 (5) 计算，其中 $P$、$R$ 为具名线段集合上的精确率与召回率。

对齐后点位误差在消除全局差异后衡量形状保真度。生成点按共有标签，以最小二乘拟合平移、旋转与等比缩放对齐到参考图，图 $f$ 的误差按式 (6) 计算，其中 $N_f$ 为参考具名点数，$D_f$ 为参考图中最远两个具名点的距离，$d_i$ 为点 $i$ 对齐后到参考位置的距离。缺失点按 100% 计入；同名点不足以拟合有效对齐的图计 100%。

整图通过率只在代码成功编译、具名线段集合完全匹配、且每个参考角度与比例均可测（角度绝对误差至多 1°、比例相对误差至多 2%）时计为通过。

**C. 主要结果。** 表 I 列出 150 张图上的主要对比，图 3 将其可视化。

表 I：150 张 TriGeoBench 图形上的图像到代码转换对比。

（表同英文版）

注：角度 MAE 使用 149 张图的 2,585 个共同可测角度，比例 MRE 使用 149 张图的 3,124 个共同可测长度比；缺测项不计入，误差不封顶。其余列基于全部 150 张图。预留行待微调模型结果填入。

[图 3：图像转代码对比实验图（待绘）]

图 3 将把表 I 的对比可视化：对每种方法（四个端到端基线、GeoConstruct，以及结果补齐后的微调模型），把视觉分数（SSIM、CLIP、DINO）与几何级结果（角度 MAE、比例 MRE、线段 F1、对齐后点位误差与整图通过率）并排展示，使视觉相似性与几何保真度之间的差距一目了然。

GeoConstruct 在每项指标上都取得最好结果。与最强的基线、同时也是我们骨干模型的 haiku-5.5 相比，角度 MAE 从 1.96° 降至 0.10°，比例 MRE 从 5.49% 降至 0.32%，整图通过率从 38.00% 升至 86.00%。视觉分数同时提升，SSIM 从 90.54 升至 94.36，说明几何收益并不以外观为代价。由于 GeoConstruct 与 haiku-5.5 基线使用同一骨干模型，这些差距衡量的是框架本身的贡献。预留行将填入微调类图像到代码模型的结果，并在相同协议下比较。

**D. 消融实验。** 表 II 在同一批 150 张图上报告消融结果。关闭约束修复时，用同一份生成代码重放、仅停用修复阶段；关闭 Critic 时，取首次评审前通过编译与基础校验的版本，并对其实施相同的修复。haiku-5.5 一行是使用与本框架相同骨干模型的端到端基线。

表 II：150 张图上的消融实验。各设置共享同一份生成代码与计分规则。

（表同英文版）

注：MAE 与 MRE 使用三个消融设置共同可测的 4,317 个角度与 5,285 个长度比，各覆盖 150 张图；每张表在本表共同项上计算这两项指标，因此 haiku-5.5 行记为 —。其余列在相同协议下基于全部 150 张图。

两个组件都有贡献。关闭 Critic 带来最大的几何退化：角度 MAE 从 0.105° 升至 0.216°，线段 F1 从 99.97% 降至 99.48%，另有四张图未通过整图检查。关闭约束修复后平均误差接近，因为坐标契约已把点位放得很准，但通过率从 86.00% 降至 83.33%：没有修复时，近似满足的关系保持近似，无法通过严格的 1°/2% 检查。端到端 haiku-5.5 一行证实，差距主要来自框架而非骨干模型。

**E. 图形编辑。** 我们进一步评测还原出的程序是否支持经验证的局部编辑。通过一个共享的确定性编辑器，对每种方法生成的代码施加三类编辑操作：更改点的标签、在已绘制边上添加中点、在实线与虚线之间切换一条边。编辑在源码层被接受的条件是目标可以唯一定位且所有无关图元保持不变；中点编辑还要在编译后回读坐标，检查每轴 2 sp 容差内的 $2M=A+B$。验收在全部 150 张图上按源码层统计，并在固定的 30 张图抽样上按编译与坐标回读统计。图 4 将报告每种方法在各操作上的验收情况。

[图 4：图形编辑对比实验图（待绘）]

图 4 将对三类编辑操作（换标签、加中点、切换实虚线）和每种方法（四个端到端基线与 GeoConstruct），比较 150 张图上的源码层验收数与 30 张图抽样上的编译回读验收数，展示各方法生成的代码在编辑下是否保持正确。

---

# V. Conclusion

We presented GeoConstruct, a system that converts raster geometric figures into editable, compilable TikZ code. Its design rests on three components: a persistent Geometric Evidence State that records the provenance of every measurement and decision; a supervisor-worker architecture in which the Supervisor orchestrates CV tools and specialized agents over this shared state; and a deterministic constraint-repair stage that turns evidence-backed, near-satisfied relations into exactly satisfied ones within strict displacement budgets, rolling back on failure. On the TriGeoBench test set [[1\]](https://arxiv.org/abs/2610.27626), GeoConstruct outperforms the evaluated baselines in both visual similarity and geometric fidelity, and the recovered programs support verified local edits.

## 中文翻译

我们提出了 GeoConstruct，一个把栅格几何图形转换为可编辑、可编译 TikZ 代码的系统。其设计基于三部分：持久化的几何证据状态（GES），记录每条测量与决策的来源；Supervisor-Worker 架构，由 Supervisor 在该状态之上统一编排 CV 工具与专用智能体；以及确定性的约束修复阶段，它在严格的位移预算内把有证据支撑、近似满足的关系变为严格满足，失败则回滚。在 TriGeoBench 测试集 [[1\]](https://arxiv.org/abs/2610.27626) 上，GeoConstruct 在视觉相似性与几何保真度两方面均优于其他基线，且还原出的程序支持经验证的局部编辑。

---

# References

[1] J. Wang, Y. Yang, H. Dou, Y. Wu, S. He, T. Shen, J. Wu, J. Li, and Y. Wang, "TriGeoBench: A multimodal mathematical geometry benchmark with figures and TikZ," arXiv:2610.27626, 2026. [Online]. Available: https://arxiv.org/abs/2610.27626

[2] J. Sun, C. Sun, B. Yang, H. Li, X. Chen, Y. Zhang, E. Ding, L. Li, C. Deng, and J. Feng, "GeoTikzBridge: Advancing multimodal code generation for geometric perception and reasoning," arXiv:2603.22687, 2026. [Online]. Available: https://arxiv.org/abs/2603.22687

[3] Z. Wu, Y. Long, J. Li, and H. Huang, "Geo-Code: A code framework for reverse code generation from geometric images based on two-stage multi-agent evolution," arXiv:2602.07749, 2026. [Online]. Available: https://arxiv.org/abs/2602.07749

[4] K. Wang, J. Pan, L. Wei, A. Zhou, W. Shi, Z. Lu, H. Xiao, Y. Yang, H. Ren, M. Zhan, and H. Li, "MathCoder-VL: Bridging vision and code for enhanced multimodal mathematical reasoning," in Findings of the Assoc. Comput. Linguistics (ACL), 2025. [Online]. Available: https://arxiv.org/abs/2505.10557

[5] C. Duan, K. Sun, R. Fang, M. Zhang, Y. Feng, Y. Luo, Y. Liu, K. Wang, P. Pei, X. Cai, H. Li, Y. Ma, and X. Liu, "CodePlot-CoT: Mathematical visual reasoning by thinking with code-driven images," arXiv:2510.11718, 2025. [Online]. Available: https://arxiv.org/abs/2510.11718

[6] J. Belouadi, S. P. Ponzetto, and S. Eger, "DeTikZify: Synthesizing graphics programs for scientific figures and sketches with TikZ," in Proc. Adv. Neural Inf. Process. Syst. (NeurIPS), 2024. [Online]. Available: https://arxiv.org/abs/2405.15306

[7] Y. Hu, W. Shi, X. Fu, D. Roth, M. Ostendorf, L. Zettlemoyer, N. A. Smith, and R. Krishna, "Visual Sketchpad: Sketching as a visual chain of thought for multimodal language models," in Proc. Adv. Neural Inf. Process. Syst. (NeurIPS), 2024. [Online]. Available: https://arxiv.org/abs/2406.09403

[8] R. Qiao, Q. Tan, M. Yang, G. Dong, P. Yang, S. Lang, E. Wan, X. Wang, Y. Xu, L. Yang, et al., "V-Thinker: Interactive thinking with images," arXiv:2511.04460, 2025. [Online]. Available: https://arxiv.org/abs/2511.04460

[9] C. Zhang, H. Qiu, Q. Zhang, Z. Zeng, L. Ma, and J. Zhang, "DeepSketcher: Internalizing visual manipulation for multimodal reasoning," arXiv:2509.25866, 2025. [Online]. Available: https://arxiv.org/abs/2509.25866

[10] W. Shi, A. Yu, R. Fang, H. Ren, K. Wang, A. Zhou, C. Tian, X. Fu, Y. Hu, Z. Lu, L. Huang, S. Liu, R. Liu, and H. Li, "MathCanvas: Intrinsic visual chain-of-thought for multimodal mathematical reasoning," arXiv:2510.14958, 2025. [Online]. Available: https://arxiv.org/abs/2510.14958
