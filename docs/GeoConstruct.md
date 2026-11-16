# Abstract

Geometric figures in textbooks and exams are often distributed as raster images. Recovering them as executable code makes them editable and reusable. Existing approaches, including end-to-end multimodal models, specialized models fine-tuned on large-scale data, and multi-agent systems with render-and-verify loops, primarily emphasize visual similarity. However, small angular deviations and distorted segment ratios can violate geometric relationships while remaining difficult to detect with image-based similarity metrics. High visual similarity alone therefore does not ensure geometric correctness. We argue that figure-to-code conversion should target not only visual similarity but also geometric fidelity. We present **GeoConstruct**, a system in which a Supervisor dynamically orchestrates sub-agents and tools over a persistent Geometric Evidence State. Computer-vision tools measure primitives and labels at the pixel level. A Geometry Agent integrates these measurements into geometric objects and relations. A Code Agent then generates parameterized TikZ code, checks candidate parallelism, perpendicularity, and other geometric constraints against predefined tolerance thresholds, and proposes small coordinate corrections. After compilation and rendering, a Critic Agent locates discrepancies by comparing the original figure with the rendered output, closing the verification loop. GeoConstruct outperforms the evaluated baselines in both visual similarity and geometric fidelity on TriGeoBench, with the latter measured by our constraint-level evaluation protocol covering angular error, segment-ratio error, and geometric-relation satisfaction.

教科书与试卷中的几何图形通常仅以栅格图像形式呈现。将其还原为可执行代码后，图形便可被编辑和复用。现有方法——包括端到端多模态模型、在大规模数据上微调的专用模型，以及带有“渲染—验证”循环的多智能体系统——主要关注视觉相似性。然而，微小的角度偏差和线段比例失真可能破坏几何关系，却难以被基于图像的相似性指标检测出来。因此，仅凭高视觉相似性并不能确保几何正确性。我们认为，图形到代码的转换不应只追求视觉相似性，还应追求几何保真度。为此，我们提出 **GeoConstruct**。该系统以持久化的几何证据状态为核心，由 Supervisor 动态编排各子智能体与工具协同工作。CV工具工具在像素层面测量图元与标签；Geometry Agent 将这些测量结果整合为几何对象与几何关系；随后由 Code Agent 生成参数化的 TikZ 代码，并依据预设容差阈值检查候选的平行、垂直及其他几何约束，并提出小幅坐标修正。代码经编译与渲染后，Critic Agent 通过比对原始图形与渲染结果定位差异，从而闭合验证回路。GeoConstruct 在视觉相似性与几何保真度两方面均优于所评估的基线方法在 TriGeoBench 上；其中几何保真度由我们提出的约束级评估协议衡量，涵盖角度误差、线段比例误差与几何关系满足情况。

# Introduction

Geometric figures are a core medium of mathematical communication. In textbooks, examination papers, and teaching materials, however, they are almost always distributed as raster images. In this form a figure is a static artifact: one cannot move a vertex, restyle a dashed edge, or reuse the construction in a new problem, and downstream systems cannot query the relations the figure encodes. Recovering the figure as executable code changes this situation fundamentally. Once available as a compilable program, for example a TikZ document, a figure becomes editable, restylable, and reusable, and it can serve as structured input for multimodal reasoning systems.

Recent years have seen rapid progress on this figure-to-code task. General-purpose multimodal large language models (MLLMs) can be prompted to emit graphics code directly; specialized models fine-tuned on large image–code corpora, such as DeTikZify [`[1]`](#ref-1) and GeoTikzBridge [`[2]`](#ref-2), substantially improve fidelity; and multi-agent systems such as Geo-Code [`[3]`](#ref-3) wrap generation in a render-and-verify loop. These approaches are usually evaluated by compilability and by image-level similarity between the rendered output and the input, or with model-based judges.

This evaluation practice hides a structural problem. Geometric figures are sparse and highly structured: a small angular deviation or a distorted segment ratio can break a geometric relation while barely changing pixel-level or feature-level similarity (see Fig. 1). Recent evaluations echo this concern. Benchmark studies report that models with strong visual scores still produce structural errors in recovered figures [`[7]`](#ref-7), and pixel-level improvements do not necessarily translate into better downstream reasoning [`[3]`](#ref-3). High visual similarity alone therefore does not ensure geometric correctness. We argue that figure-to-code conversion should treat geometric fidelity as a first-class objective alongside visual similarity: the relations that make a figure mathematically meaningful, such as parallelism, perpendicularity, collinearity, angle values, and length ratios, should be measured, enforced, and reported explicitly.

We present GeoConstruct, a system built around this principle. GeoConstruct adopts a hierarchical supervisor–subagent architecture: a Supervisor dynamically orchestrates sub-agents and deterministic tools, and all parties communicate through a persistent Geometric Evidence State (GES) rather than through free-form message passing. Computer-vision tools first measure primitives and labels at the pixel level. A Geometry Agent consolidates these measurements into geometric objects and relations. A Code Agent then writes parameterized TikZ code under a coordinate contract that carries the measured coordinates into the generated program, and a deterministic constraint-repair stage checks candidate parallelism, perpendicularity, collinearity, and other relations against tolerance thresholds and applies small, bounded coordinate corrections. After compilation and rendering, a Critic Agent compares the rendered figure with the original and returns actionable discrepancies, closing the verification loop.

We evaluate GeoConstruct on plane geometry figures randomly sampled from TriGeoBench [`[7]`](#ref-7), comparing against end-to-end MLLM baselines. Beyond standard visual metrics, we construct a constraint-level evaluation protocol from the reference TikZ, covering angular error, segment-ratio error, segment coverage, aligned point error, and whole-figure relation satisfaction. GeoConstruct outperforms the baselines on both families of metrics, and the margin is much larger on geometric fidelity than on visual similarity. Moreover, the recovered programs can be reliably edited and queried, which supports the editing and reuse scenarios that motivate figure-to-code conversion in the first place.

Our contributions are as follows.

- We identify the gap between visual similarity and geometric fidelity in figure-to-code conversion, and introduce a constraint-level evaluation protocol built from reference geometry, covering angular error, segment-ratio error, segment coverage, point accuracy, and whole-figure relation satisfaction.
- We present GeoConstruct, a hierarchical agent system in which a Supervisor orchestrates specialized sub-agents and deterministic tools over a persistent Geometric Evidence State, together with a deterministic geometric constraint repair stage whose bounded corrections are verified by compilation read-back.
- Experiments on TriGeoBench show that GeoConstruct improves over strong end-to-end baselines in both visual similarity and geometric fidelity, and that the recovered programs support reliable downstream editing and querying.

几何图形是数学交流的核心媒介。然而在教科书、试卷与教学材料中，它们几乎总是以栅格图像的形式呈现。在这种形式下，图形是静态的产物：无法移动顶点、修改虚线样式，也无法把已有构造复用到新题目中；下游系统也无法查询图形所编码的几何关系。把图形还原为可执行代码从根本上改变了这一局面：一旦以可编译程序（例如 TikZ 文档）的形式存在，图形就可以被编辑、改版式和复用，并可作为多模态推理系统的结构化输入。

近年来，这一“图形到代码”任务进展迅速。通用多模态大语言模型（MLLM）可以被提示直接生成图形代码；DeTikZify [`[1]`](#ref-1)、GeoTikzBridge [`[2]`](#ref-2) 等在大规模图像—代码语料上微调的专用模型显著提升了保真度；Geo-Code [`[3]`](#ref-3) 等多智能体系统则把生成过程包裹在“渲染—验证”循环之中。这些方法通常以能否编译、以及渲染结果与输入图像之间的图像级相似度来评测，或依赖基于模型的评判。

这一评测惯例掩盖了一个结构性问题。几何图形是稀疏且高度结构化的：微小的角度偏差或线段比例失真就可能破坏几何关系，却几乎不改变像素级或特征级的相似度（见图 1）。近期的评测研究也印证了这一点：基准研究报告称，视觉得分很高的模型在还原图形时仍会产出结构性错误 [`[7]`](#ref-7)；像素级指标的提升也不一定带来下游推理的改善 [`[3]`](#ref-3)。因此，仅凭高视觉相似性并不能确保几何正确性。我们认为，图形到代码的转换应当把几何保真度与视觉相似性并列为第一等目标：那些使图形具有数学意义的关系——平行、垂直、共线、角度数值与长度比例——应当被显式地测量、强制满足并报告。

我们提出 GeoConstruct，一个围绕这一原则构建的系统。GeoConstruct 采用主从式智能体架构：Supervisor 动态编排各子智能体与确定性工具，各方不通过自由文本消息通信，而是通过持久化的几何证据状态（GES）交换信息。计算机视觉工具首先在像素层面测量图元与标签；Geometry Agent 将这些测量整合为几何对象与关系；Code Agent 随后在坐标契约下编写参数化 TikZ 代码——坐标契约把实测坐标带入生成的程序——确定性约束修复阶段再按容差阈值检查候选的平行、垂直、共线等关系，并施加小幅、有界的坐标修正。代码经编译渲染后，Critic Agent 将渲染图与原图比对并返回可执行的修改意见，闭合验证回路。

我们在从 TriGeoBench [`[7]`](#ref-7) 随机抽取的平面几何图形上评测 GeoConstruct，并与端到端 MLLM 基线对比。除标准视觉指标外，我们还从参考 TikZ 构建了约束级评测协议，涵盖角度误差、线段比例误差、线段覆盖率、对齐后点位误差与整图关系满足情况。GeoConstruct 在两类指标上均优于基线，且几何保真度上的优势远大于视觉相似度上的优势。此外，还原出的程序可以被可靠地编辑与查询，这正支撑了图形到代码转换所面向的编辑与复用场景。

我们的贡献如下。

- 我们指出图形到代码转换中视觉相似性与几何保真度之间的鸿沟，并提出由参考几何构建的约束级评测协议，涵盖角度误差、线段比例误差、线段覆盖率、点位精度与整图关系满足情况。
- 我们提出 GeoConstruct：一个主从式智能体系统，Supervisor 在持久化几何证据状态（GES）之上编排各专用子智能体与确定性工具，并配备确定性的几何约束修复阶段，其有界坐标修正由编译回读验证。
- 在 TriGeoBench 上的实验表明，GeoConstruct 在视觉相似性与几何保真度两方面均优于强端到端基线，且还原出的程序支持可靠的下游编辑与查询。

# Related Work

## Image-to-Code and Graphics Program Synthesis

Recovering executable code from visual input has been studied across several domains. For vector graphics, hierarchical generative models and layout-guided synthesis have been explored [`[8]`](#ref-8), [`[9]`](#ref-9), and unified SVG models further combine understanding, generation, and editing [`[10]`](#ref-10). For TikZ in particular, AutomaTikZ learns text-guided synthesis from large figure–code corpora [`[11]`](#ref-11), DeTikZify recovers programs from figures or sketches with simulation-based refinement [`[1]`](#ref-1), and TikZero enables zero-shot text-guided synthesis through image representations [`[12]`](#ref-12). Related conversions have been studied for webpages [`[13]`](#ref-13) and evaluated through geometric program reasoning [`[14]`](#ref-14), while LLM-based symbolic graphics programming explores drawing code as a general paradigm [`[15]`](#ref-15). In the geometric domain, GeoTikzBridge scales image–TikZ training to millions of pairs [`[2]`](#ref-2), MathCoder-VL and CodePlot-CoT connect code-driven figures with mathematical reasoning [`[16,17]`](#ref-16), and Edit2TikZ evaluates instruction-guided editing of existing programs [`[18]`](#ref-18). Despite differences in data and modeling, these works are usually evaluated with image-level or code-level similarity, and explicit geometric relations are rarely measured or enforced. Our work keeps the figure-to-code formulation but adds constraint-level measurement and enforcement of geometric relations.

从视觉输入还原可执行代码已在多个领域得到研究。矢量图形方面，已有工作探索了层次化生成模型与版式引导的合成 [`[8]`](#ref-8), [`[9]`](#ref-9)，统一的 SVG 模型进一步把理解、生成与编辑结合起来 [`[10]`](#ref-10)。TikZ 方面，AutomaTikZ 从大规模图形—代码语料学习文本引导的合成 [`[11]`](#ref-11)，DeTikZify 从图形或草图还原程序并以基于仿真的搜索精炼 [`[1]`](#ref-1)，TikZero 借助图像表示实现零样本文本引导合成 [`[12]`](#ref-12)。类似的转换在网页领域也有研究 [`[13]`](#ref-13)，并有几何程序推理的评测 [`[14]`](#ref-14)；基于 LLM 的符号化图形编程则把绘图代码作为一种通用范式 [`[15]`](#ref-15)。在几何领域，GeoTikzBridge 把图像—TikZ 训练扩展到数百万对样本 [`[2]`](#ref-2)，MathCoder-VL 与 CodePlot-CoT 把代码驱动的图形与数学推理联系起来 [`[16,17]`](#ref-16)，Edit2TikZ 评测对已有程序的指令引导编辑 [`[18]`](#ref-18)。这些工作在数据与建模上各不相同，但通常以图像级或代码级相似度来评测，显式的几何关系很少被测量或强制。我们的工作保留图形到代码的任务形式，但加入对几何关系的约束级测量与强制满足。

## Geometry Diagram Understanding and Generation

Understanding geometric diagrams has long been studied as structured prediction. Wireframe parsing vectorizes junctions and segments directly from images [`[19]`](#ref-19), and PGDPNet parses plane geometry diagrams into primitives and relations in an end-to-end model [`[20]`](#ref-20). A series of datasets pair diagrams with formal annotations to support geometry problem solving [`[21–24]`](#ref-21), and solvers range from formal-language symbolic reasoning [`[21]`](#ref-21) to neural-symbolic systems that reach olympiad-level performance [`[25]`](#ref-25); broader multimodal benchmarks evaluate diagram-based reasoning while keeping figures as rasters [`[26–28]`](#ref-26). On the generation side, declarative systems compile mathematical notation into diagrams [`[29]`](#ref-29), interactive tools rely on manual construction [`[30]`](#ref-30), and recent frameworks translate natural language into formal constraints realized by coordinate solvers [`[31]`](#ref-31) or evaluate executable construction from text, where structural hallucinations remain frequent [`[32]`](#ref-32). GeoSketch connects diagram construction with auxiliary-line reasoning [`[33]`](#ref-33). These works move from text to diagrams or from diagrams to formal propositions; we address the inverse problem of recovering executable, constraint-faithful code from a raster figure.

几何图形理解长期以来被作为结构化预测来研究。线框解析直接从图像中矢量化了连接点与线段 [`[19]`](#ref-19)，PGDPNet 则以端到端模型把平面几何图形解析为图元与关系 [`[20]`](#ref-20)。一系列数据集为图形配上形式化标注以支持几何问题求解 [`[21–24]`](#ref-21)；求解方法从形式语言符号推理 [`[21]`](#ref-21) 到达到奥赛水平的神经符号系统 [`[25]`](#ref-25) 不等，而更广义的多模态基准在评测基于图形的推理时仍以栅格形式保存图形 [`[26–28]`](#ref-26)。在生成一侧，声明式系统把数学记号编译为图形 [`[29]`](#ref-29)，交互式工具依赖手工构造 [`[30]`](#ref-30)，近期的框架把自然语言翻译为由坐标求解器实现的形式约束 [`[31]`](#ref-31)，或评测从文本出发的可执行构造——其中结构性幻觉仍然频繁出现 [`[32]`](#ref-32)。GeoSketch 把图形构造与辅助线推理联系起来 [`[33]`](#ref-33)。这些工作是从文本到图形、或从图形到形式命题；我们处理的是其逆问题：从栅格图形还原可执行且满足约束的代码。

## LLM Agents with Feedback and Verification

Our system builds on agentic uses of LLMs. Tool use and visual chain-of-thought allow models to sketch and manipulate images during reasoning [`[34]`](#ref-34), and self-feedback loops improve generation quality without retraining [`[35,36]`](#ref-35); multi-agent frameworks further study role-based collaboration [`[37,38]`](#ref-37). In the visual-math domain, several systems integrate image manipulation into the reasoning process [`[39–41]`](#ref-39), and auxiliary-line construction has been formalized through specialized training or rewards [`[42–44]`](#ref-42). Closest to our setting is Geo-Code [`[3]`](#ref-3), a two-stage multi-agent system that anchors keypoints at the pixel level and refines code through visual error projection. GeoConstruct differs from these systems in three ways. First, agents communicate through a persistent, typed evidence state with provenance and conflict tracking, rather than through conversational messages. Second, verification combines model-based critics with deterministic checks, including compilation read-back and stroke-level evidence in the source image. Third, geometric relations are not only measured but actively repaired through bounded coordinate corrections.

我们的系统建立在 LLM 的智能体化应用之上。工具使用与视觉思维链使模型能够在推理过程中绘制和操作图像 [`[34]`](#ref-34)，自反馈回路无需重新训练即可提升生成质量 [`[35,36]`](#ref-35)；多智能体框架进一步研究基于角色的协作 [`[37,38]`](#ref-37)。在视觉数学领域，若干系统把图像操作整合进推理过程 [`[39–41]`](#ref-39)，辅助线构造也通过专门训练或奖励被形式化 [`[42–44]`](#ref-42)。与本文设置最接近的是 Geo-Code [`[3]`](#ref-3)：一个两阶段多智能体系统，在像素层锚定关键点，并通过视觉误差投影精炼代码。GeoConstruct 与这些系统有三点不同：其一，智能体之间通过持久化、带类型的证据状态交换信息，具有溯源与冲突跟踪，而非通过对话消息；其二，验证把基于模型的评判与确定性检查相结合，包括编译回读与原图中的笔画级证据；其三，几何关系不仅被测量，还通过有界坐标修正被主动修复。

# References

<a id="ref-1"></a>[1] Jonas Belouadi, Simone Paolo Ponzetto, and Steffen Eger. 2024. DeTikZify: Synthesizing graphics programs for scientific figures and sketches with TikZ. In Advances in Neural Information Processing Systems (NeurIPS).

<a id="ref-2"></a>[2] Jiayin Sun, Caixia Sun, Boyu Yang, Hailin Li, Xiao Chen, Yi Zhang, Errui Ding, Liang Li, Chao Deng, and Junlan Feng. 2026. GeoTikzBridge: Advancing multimodal code generation for geometric perception and reasoning. In Proceedings of the IEEE/CVF Conference on Computer Vision and Pattern Recognition (CVPR), pages 9593–9603.

<a id="ref-3"></a>[3] Zhenyu Wu, Yanxi Long, Jian Li, and Hua Huang. 2026. Geo-Code: A code framework for reverse code generation from geometric images based on two-stage multi-agent evolution. arXiv preprint arXiv:2602.07749.

<a id="ref-4"></a>[4] Zhou Wang, Alan C. Bovik, Hamid R. Sheikh, and Eero P. Simoncelli. 2004. Image quality assessment: From error visibility to structural similarity. IEEE Transactions on Image Processing, 13(4):600–612.

<a id="ref-5"></a>[5] Alec Radford, Jong Wook Kim, Chris Hallacy, Aditya Ramesh, Gabriel Goh, Sandhini Agarwal, Girish Sastry, Amanda Askell, Pamela Mishkin, Jack Clark, Gretchen Krueger, and Ilya Sutskever. 2021. Learning transferable visual models from natural language supervision. In International Conference on Machine Learning (ICML), pages 8748–8763.

<a id="ref-6"></a>[6] Maxime Oquab, Timothée Darcet, Théo Moutakanni, Huy Vo, Marc Szafraniec, Vasil Khalidov, Pierre Fernandez, Daniel Haziza, Francisco Massa, Alaaeldin El-Nouby, et al. 2024. DINOv2: Learning robust visual features without supervision. Transactions on Machine Learning Research (TMLR).

<a id="ref-7"></a>[7] Jing Wang, Yitong Yang, Hao Dou, Yaomin Wu, Shuting He, Tingfei Shen, Jia Wu, Jiaqi Li, and Yinglin Wang. 2026. TriGeoBench: A multimodal mathematical geometry benchmark with figures and TikZ. arXiv preprint arXiv:2610.27626.

<a id="ref-8"></a>[8] Alexandre Carlier, Martin Danelljan, Alexandre Alahi, and Radu Timofte. 2020. DeepSVG: A hierarchical generative network for vector graphics animation. In Advances in Neural Information Processing Systems (NeurIPS), volume 33, pages 16351–16361.

<a id="ref-9"></a>[9] Abhay Zala, Han Lin, Jaemin Cho, and Mohit Bansal. 2024. DiagrammerGPT: Generating open-domain, open-platform diagrams via LLM planning. arXiv preprint arXiv:2410.12159.

<a id="ref-10"></a>[10] Haomin Wang, Jinhui Yin, Qi Wei, Wenguang Zeng, Lixin Gu, Shenglong Ye, Zhangwei Gao, Yaohui Wang, Yanting Zhang, Yuanqi Li, et al. 2025. InternSVG: Towards unified SVG tasks with multimodal large language models. arXiv preprint arXiv:2510.11341.

<a id="ref-11"></a>[11] Jonas Belouadi, Anne Lauscher, and Steffen Eger. 2024. AutomaTikZ: Text-guided synthesis of scientific vector graphics with TikZ. In International Conference on Learning Representations (ICLR).

<a id="ref-12"></a>[12] Jonas Belouadi, Eddy Ilg, Margret Keuper, Hideki Tanaka, Masao Utiyama, Raj Dabre, Steffen Eger, and Simone Paolo Ponzetto. 2025. TikZero: Zero-shot text-guided graphics program synthesis. In Proceedings of the IEEE/CVF International Conference on Computer Vision (ICCV), pages 17793–17806.

<a id="ref-13"></a>[13] Chenglei Si, Yanzhe Zhang, Zhengyuan Yang, Ruibo Liu, and Diyi Yang. 2024. Design2Code: How far are we from automating front-end engineering? arXiv preprint arXiv:2403.03163.

<a id="ref-14"></a>[14] Shixian Luo, Zezhou Zhu, Yu Yuan, Yuncheng Yang, Lianlei Shan, and Yong Wu. 2025. GeoGramBench: Benchmarking the geometric program reasoning in modern LLMs. arXiv preprint arXiv:2505.17653.

<a id="ref-15"></a>[15] Yamei Chen, Haoquan Zhang, Yangyi Huang, Zeju Qiu, Kaipeng Zhang, Yandong Wen, and Weiyang Liu. 2025. Symbolic graphics programming with large language models. arXiv preprint arXiv:2509.05208.

<a id="ref-16"></a>[16] Ke Wang, Junting Pan, Linda Wei, Aojun Zhou, Weijia Shi, Zhenyu Lu, Han Xiao, Yunqiao Yang, Haotian Ren, Mingjie Zhan, and Hongsheng Li. 2025. MathCoder-VL: Bridging vision and code for enhanced multimodal mathematical reasoning. arXiv preprint arXiv:2505.10557.

<a id="ref-17"></a>[17] Chengyu Duan, Kun Sun, Rongyi Fang, Muhan Zhang, Ying Feng, Yuqi Luo, Yan Liu, Ke Wang, Pingchuan Pei, Xinyu Cai, Huiqi Li, Yifan Ma, and Xiangyang Liu. 2025. CodePlot-CoT: Mathematical visual reasoning by thinking with code-driven images. arXiv preprint arXiv:2510.11718.

<a id="ref-18"></a>[18] Zongyun Zhang et al. 2026. Edit2TikZ: A comprehensive and challenging benchmark for scientific figure editing with TikZ. arXiv preprint arXiv:2608.13441.

<a id="ref-19"></a>[19] Xingyi Zhou, Rongqi Qi, and Yuexin Ma. 2019. End-to-end wireframe parsing. In Proceedings of the IEEE/CVF International Conference on Computer Vision (ICCV), pages 962–971.

<a id="ref-20"></a>[20] Ming-Liang Zhang, Fei Yin, Yi-Han Hao, and Cheng-Lin Liu. 2022. Plane geometry diagram parsing. In Proceedings of the 31st International Joint Conference on Artificial Intelligence (IJCAI), pages 1636–1643.

<a id="ref-21"></a>[21] Pan Lu, Ran Gong, Shibiao Jiang, Liang Qiu, Siyuan Huang, Xiaodan Liang, and Song-Chun Zhu. 2021. Inter-GPS: Interpretable geometry problem solving with formal language and symbolic reasoning. In Proceedings of ACL-IJCNLP 2021.

<a id="ref-22"></a>[22] Jiaqi Chen, Jianheng Tang, Jinghui Qin, Xiaodan Liang, Lingbo Liu, Eric Xing, and Liang Lin. 2021. GeoQA: A geometric question answering benchmark towards multimodal numerical reasoning. In Findings of the Association for Computational Linguistics: ACL-IJCNLP 2021, pages 513–523.

<a id="ref-23"></a>[23] Jie Cao and Jing Xiao. 2022. An augmented benchmark dataset for geometric question answering through dual parallel text encoding. In Proceedings of the 29th International Conference on Computational Linguistics (COLING), pages 1511–1520.

<a id="ref-24"></a>[24] Jiaqi Chen, Tong Li, Jinghui Qin, Pan Lu, Liang Lin, Chongyu Chen, and Xiaodan Liang. 2022. UniGeo: Unifying geometry logical reasoning via reformulating mathematical expression. In Proceedings of the 2022 Conference on Empirical Methods in Natural Language Processing (EMNLP), pages 3313–3323.

<a id="ref-25"></a>[25] Trieu H. Trinh, Yuhuai Wu, Quoc V. Le, He He, and Thang Luong. 2024. Solving olympiad geometry without human demonstrations. Nature, 625:476–482.

<a id="ref-26"></a>[26] Pan Lu, Hritik Bansal, Tony Xia, Jiacheng Liu, Chunyuan Li, Hannaneh Hajishirzi, Hao Cheng, Kai-Wei Chang, Michel Galley, and Jianfeng Gao. 2024. MathVista: Evaluating mathematical reasoning of foundation models in visual contexts. In International Conference on Learning Representations (ICLR).

<a id="ref-27"></a>[27] Ke Wang, Junting Pan, Weikang Shi, Zimu Lu, Houxing Ren, Aojun Zhou, Mingjie Zhan, and Hongsheng Li. 2024. Measuring multimodal mathematical reasoning with MATH-Vision dataset. In NeurIPS Datasets and Benchmarks Track.

<a id="ref-28"></a>[28] Renrui Zhang, Dongzhi Jiang, Yichi Zhang, Haokun Lin, Ziyu Guo, Pengshuo Qiu, Aojun Zhou, Pan Lu, Kai-Wei Chang, Yu Qiao, Peng Gao, and Hongsheng Li. 2024. MathVerse: Does your multi-modal LLM truly see the diagrams in visual math problems? In European Conference on Computer Vision (ECCV).

<a id="ref-29"></a>[29] Katherine Ye, Wode Ni, Max Krieger, Dor Ma'ayan, Jenna Wise, Jonathan Aldrich, Joshua Sunshine, and Keenan Crane. 2020. Penrose: From mathematical notation to beautiful diagrams. ACM Transactions on Graphics (SIGGRAPH), 39(4).

<a id="ref-30"></a>[30] Markus Hohenwarter and Judith Preiner. 2007. Dynamic mathematics with GeoGebra. Journal of Online Mathematics and its Applications, volume 7.

<a id="ref-31"></a>[31] Xiaojing Wei, Ting Zhang, Wei He, Jingdong Wang, and Hua Huang. 2026. GeoLoom: High-quality geometric diagram generation from textual input. In Proceedings of the 43rd International Conference on Machine Learning (ICML).

<a id="ref-32"></a>[32] Jinwoong Kim et al. 2026. GeoBuildBench: A benchmark for interactive and executable geometry construction from natural language. arXiv preprint arXiv:2605.13167.

<a id="ref-33"></a>[33] Shaofei Weng, Ziyu Wang, Yifan Zhou, Ruilin Lu, Tianbao Liu, Zhiyuan Teng, Xiao Liu, and Haitao Liu. 2025. GeoSketch: A neural-symbolic approach to geometric multimodal reasoning with auxiliary line construction and affine transformation. arXiv preprint arXiv:2509.22460.

<a id="ref-34"></a>[34] Yushi Hu, Weijia Shi, Xingyu Fu, Dan Roth, Mari Ostendorf, Luke Zettlemoyer, Noah A. Smith, and Ranjay Krishna. 2024. Visual Sketchpad: Sketching as a visual chain of thought for multimodal language models. In Advances in Neural Information Processing Systems (NeurIPS).

<a id="ref-35"></a>[35] Noah Shinn, Federico Cassano, Ashwin Gopinath, Karthik Narasimhan, and Shunyu Yao. 2023. Reflexion: Language agents with verbal reinforcement learning. In Advances in Neural Information Processing Systems (NeurIPS).

<a id="ref-36"></a>[36] Aman Madaan, Niket Tandon, Prakhar Gupta, Skyler Hallinan, Luyu Gao, Sarah Wiegreffe, Uri Alon, Nouha Dziri, Shrimai Prabhumoye, Yiming Yang, Shashank Gupta, Bodhisattwa Prasad Majumder, Katherine Hermann, Sean Welleck, Amir Yazdanbakhsh, and Peter Clark. 2023. Self-Refine: Iterative refinement with self-feedback. In Advances in Neural Information Processing Systems (NeurIPS).

<a id="ref-37"></a>[37] Guohao Li, Hasan Abed Al Kader Hammoud, Hani Itani, Dmitrii Khizbullin, and Bernard Ghanem. 2023. CAMEL: Communicative agents for "mind" exploration of large language model society. In Advances in Neural Information Processing Systems (NeurIPS).

<a id="ref-38"></a>[38] Qingyun Wu, Gagan Bansal, Jieyu Zhang, Yiran Wu, Beibin Li, Erkang Zhu, Li Jiang, Xiaoyun Zhang, Shaokun Zhang, Jiale Liu, Ahmed Hassan Awadallah, Ryen W. White, Doug Burger, and Chi Wang. 2023. AutoGen: Enabling next-gen LLM applications via multi-agent conversation. arXiv preprint arXiv:2308.08155.

<a id="ref-39"></a>[39] Rui Qiao, Qihan Tan, Ming Yang, Guanting Dong, Pin Yang, Siqi Lang, En Wan, Xiao Wang, Yiran Xu, Longyue Yang, Chong Sun, Chen Li, Jiachun Lyu, and Hongxia Zhang. 2025. V-Thinker: Interactive thinking with images. arXiv preprint arXiv:2511.04460.

<a id="ref-40"></a>[40] Chi Zhang, Han Qiu, Qizhen Zhang, Zekai Zeng, Lin Ma, and Jiajun Zhang. 2025. DeepSketcher: Internalizing visual manipulation for multimodal reasoning. arXiv preprint arXiv:2509.25866.

<a id="ref-41"></a>[41] Weijia Shi, Anqi Yu, Rongyi Fang, Haotian Ren, Ke Wang, Aojun Zhou, Chenghao Tian, Xingyu Fu, Yushi Hu, Zhenyu Lu, Liangming Huang, Shuaiyi Liu, Rui Liu, and Houqiang Li. 2025. MathCanvas: Intrinsic visual chain-of-thought for multimodal mathematical reasoning. arXiv preprint arXiv:2510.14958.

<a id="ref-42"></a>[42] Junzhe Wei, Chenghao Jia, Qiguang Chen, Hao He, Libo Sun, Chaoda He, Libo Wu, Baijuan Yu, and Chaoyou Tan. 2025. GeoInt-R1: Formalizing multimodal geometric reasoning with dynamic auxiliary constructions. arXiv preprint arXiv:2508.03173.

<a id="ref-43"></a>[43] Yiming Wang, Yu Wang, Dong Wang, Zhiyuan Peng, Quanquan Gu, Dacheng Tao, and Jiahai Wang. 2025. GeometryZero: Improving geometry solving for LLM with group contrastive policy optimization. arXiv preprint arXiv:2506.07160.

<a id="ref-44"></a>[44] Shangqing Guo, Liang Pang, Xinyu Wang, Yu Wang, Huawei Shen, and Jiajun Zhang. 2026. GeoVLMath: Enhancing geometry reasoning in vision-language models via cross-modal reward for auxiliary line creation. arXiv preprint arXiv:2510.11020.
