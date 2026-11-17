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
