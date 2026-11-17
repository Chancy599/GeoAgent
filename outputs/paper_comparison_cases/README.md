# 论文重建与编辑对照图

- [八组图像到代码渲染对照](../reconstruction_comparison_8.png)
- [四类各两组的单步图像编辑对照](../editing_comparison_8.png)
- [样本、完整指令、图片校验和及诊断](manifest.json)

八个案例横向并列，每个模型占一行。两张图采用白底、衬线字体与黑色细分隔线。编辑图在原图下方列出指令，上方将案例按四类分组。图内只保留方法名、编辑类别和必要指令。

重建图第一列已换为 7126_q_fig1。编辑图第二列已换为 7125_q_fig1 的 D 改为 H。

展示案例按可见错误和几何差异筛选。所有模型格均为成功编译的 TikZ 渲染结果。e2e 模型收到输入图和对应指令，GeoConstruct 在归档重建结果上执行编辑。每个编辑目录保留输入图、TikZ、PDF、PNG 和运行记录。

7107_q_fig2 的 GPT-5.4 初始输出编译失败，使用相同图像和指令、以 medium 推理设置重跑后直接编译成功。

| 编辑类别 | 样本 | 完整指令 |
|---|---|---|
| Labels | [1269_s_fig2](editing/01-focus-swap-1269_s_fig2/original.png) | 只交换点 H 与点 M 的可见标签：原来标 H 的位置改标 M，原来标 M 的位置改标 H。两个点的位置、线段和其他标签保持不变。 |
| Labels | [7125_q_fig1](editing/02-rename-7125_q_fig1/original.png) | 把图中点 D 的标签改为 H，保留点的位置和所有原有笔画。 |
| Delete | [1540_s_fig2](editing/03-delete-segment-1540_s_fig2/original.png) | 只删除线段 AM 的笔画，保留点 A、M 的位置和标签。 |
| Delete | [1316_s_fig1](editing/04-focus-delete-1316_s_fig1/original.png) | 只删除连续直线上位于 D 和 O 之间的子段 DO。该直线在 DO 之外的笔画都要保留，保留所有点的位置和可见标签。 |
| Perpendicular | [1540_s_fig2](editing/05-perpendicular-1540_s_fig2/original.png) | 从点 B 向线段 CM 作垂线，画出线段 BH，把垂足标记为 H，并在 H 处标出直角。 |
| Perpendicular | [5804_q_fig1](editing/06-perpendicular-5804_q_fig1/original.png) | 从点 B 向线段 AC 作垂线，画出线段 BH，把垂足标记为 H，并在 H 处标出直角。 |
| Line style | [1283_s_fig2](editing/07-toggle-dash-1283_s_fig2/original.png) | 只把线段 AO 改为虚线，共线的 EA 和 OC 保持实线。 |
| Line style | [7107_q_fig2](editing/08-toggle-dash-7107_q_fig2/original.png) | 只把线段 DF 改为虚线，共线的 GD 和 FB 保持实线。 |
