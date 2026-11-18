# 论文重建与编辑对照图

- [八组图像到代码渲染对照](../reconstruction_comparison_8.png)
- [四类各两组的单步图像编辑对照](../editing_comparison_8.png)
- [样本、完整指令、图片校验和及诊断](manifest.json)

八个案例横向并列，每个模型占一行。编辑图按 Label Editing、Segment Editing、Geometric Construction、Line-style Editing 分组，每类两例。图内无样本编号、错误说明或标记。

展示案例按可见差异筛选，仅作定性展示，不代表总体性能。所有模型格均为成功编译的原始 TikZ 输出的渲染结果。e2e 模型输入为原图和指令；GeoConstruct 编辑已有重建代码后渲染。每个编辑目录保留输入图、TikZ、PDF、PNG 和运行记录，未人工修改 baseline 图元。

本次替换线段编辑右例、几何构造左例及线型编辑左例。几何构造包含平行线和垂线；线型编辑包含虚线转实线和实线转虚线。

7107_q_fig2 的 GPT-5.4 初始输出编译失败，之前使用相同输入和指令、以 medium 推理设置重跑成功。1316_s_fig1 虚线改实线的 Qwen 初次输出编译失败，使用相同输入和指令重跑成功；原始失败记录保留于实验缓存。

| 编辑类别 | 样本 | 完整指令 |
|---|---|---|
| Labels | [1269_s_fig2](editing/01-focus-swap-1269_s_fig2/original.png) | 只交换点 H 与点 M 的可见标签：原来标 H 的位置改标 M，原来标 M 的位置改标 H。两个点的位置、线段和其他标签保持不变。 |
| Labels | [7125_q_fig1](editing/02-rename-7125_q_fig1/original.png) | 把图中点 D 的标签改为 H，保留点的位置和所有原有笔画。 |
| Segment Editing | [1540_s_fig2](editing/03-delete-segment-1540_s_fig2/original.png) | 只删除线段 AM 的笔画，保留点 A、M 的位置和标签。 |
| Segment Editing | [1540_s_fig2](editing/04-new-add-anchor-BG-1540_s_fig2/original.png) | 连接点 B 和点 G，画出实线线段 BG。只添加这一条线段，保留其余笔画、标签和布局。 |
| Geometric Construction | [5804_q_fig1](editing/05-new-parallel-5804_q_fig1/original.png) | 过点 O 作一条平行于 AB 的直线，与线段 AC 相交于新点 H。画出实线段 OH 并标出 H，保留原图其余图元、标签和布局。 |
| Geometric Construction | [5804_q_fig1](editing/06-perpendicular-5804_q_fig1/original.png) | 从点 B 向线段 AC 作垂线，画出线段 BH，把垂足标记为 H，并在 H 处标出直角。 |
| Line style | [1316_s_fig1](editing/07-new-solid-1316_s_fig1/original.png) | 只把虚线线段 AO 改为实线，保留其他线段的实虚线样式、标签、位置和所有原有图元。 |
| Line style | [7107_q_fig2](editing/08-toggle-dash-7107_q_fig2/original.png) | 只把线段 DF 改为虚线，共线的 GD 和 FB 保持实线。 |
