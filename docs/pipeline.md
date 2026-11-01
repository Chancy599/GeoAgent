# GeoAgent 流程与标签几何评测

## 生成和后修复

输入原图 → Supervisor调度CV与Geometry → 几何证据状态GES → TikZ生成 → 确定性坐标后修复 → 编译与渲染 → Critic → 必要时再次测量或修改。

后修复读取生成代码，不读取参考源码。候选提取前识别由两条主体长边支持的小正交路径，排除其笔画及专用辅助点；支持命名、字面、简单偏移、相对坐标及拆成两条命令的符号。主体关系仍可作为候选，带标签的真实短几何受保护。近平行、近垂直和近共线关系来自生成的数值坐标与绘制线段；使用小位移、长度变化限制和曲线依赖冻结保护已有结构。默认直线关系容差0.5°、单点最大位移为图形对角线0.5%、已有边长最大变化1%，所有点对长度保护权重0.01，共线范围0.3%。曲线分支冻结曲线定义依赖及圆周、切线保护点，其余点仅修复近平行关系，共线范围0.2%。

参数见`configs/default.json`与`results/latest/experiments/current_parameters.json`。符号表达式、未支持的曲线和局部变换保留原样。导出回读或编译失败回退原始代码；内容与配置哈希防止重复写回。前置GES修复仍是显式可选实验设置，默认处理发生在TikZ生成之后。

## 参考清单：先提取，单独保存

运行`python scripts/build_geometry_reference.py --workers 20`，仅从`data/test/latex`提取，输出到`data/test/geometry_reference`。不访问生成结果，不根据预测筛选参考项。

`corrections.json`保存人工审核的参考构造修正，并用原始源码哈希防止误用。已审核修正6986的E：取BC与圆心O、半径OB的上半圆的第二交点，得到(-0.161002879, 2.995676563)。不修改原始TeX；原绑定保留在source_xy，所有依赖E的目标值在构建时重算。

每图JSON包含：

- 可见标签及其显式绑定坐标、内部坐标别名和绑定表达式。
- 实际绘制、两端均有标签的直线段。
- 具有公共带标签顶点的线段对所定义的角度和有序长度比。
- 参考数值、源码哈希、解析规则哈希，以及重复标签与绑定冲突。

标签坐标按代码表达式解析，包括内部别名、字面坐标、受支持的calc和交点表达式；picture/scope变换及数值x/y坐标基会作用于坐标。字号、above/left、anchor、文字xshift/yshift属于排版，不修改at绑定。

`\coordinate (P7) at (2,3); \node[above] at (P7) {$A$};`提取A=(2,3)，不要求内部坐标名为A。同名内部坐标与可见标签绑定不同时，记录冲突，使用可见标签的实际绑定。无标签点、辅助点、曲线上的无标签点和隐式交点均不创建评测顶点。

重复标签若精确绑定同一点则合并；绑定不同点则该标签无法解析，不选择最近点。没有可见标签的命名坐标也不参与评测。无明确绑定的路径位置标签暂报告不支持，不将其误绑定到路径端点。

## 测量项的确定规则

当前协议为`label-bound-v1`，只有一套活动实现。

1. 对所有带标签点对，保留非退化且被直线笔画支持至少95%的线段；有中间标签的组合线段也保留，例如AM、MB、AB。
2. 对有一个公共端点的线段对，角度大于等于5°时记录角度，范围为0–180°；所有非退化线段对记录长度比。
3. 线段端点及线段对均按标签排序，比例方向固定，不按预测翻转分子分母。
4. 小正交注释路径经过几何过滤；圆、圆弧、填充与非顶点文字不作为直线测量项。只含曲线的图可以没有角度与比例。

角度MAE为预测与参考角度差的绝对值，单位度。比例MRE为`abs(预测比例/参考比例 - 1)`，表格乘100显示百分比。二者越低越好。

源代码可能包含近似构造或不一致的标签，清单反映源码实际写出的绑定，不自动纠正数据，不从原图猜测其意图。字面文字坐标若被作者用作排版偏移，当前规则也不会擅自吸附到附近点；可通过绑定审计发现这类样本。明确审核过的参考错误通过独立corrections.json修正，不能根据某个预测结果选择修正值。

## 评测时只读清单

`scripts/evaluate_structure_ab.py`读取manifest中固定的100个图名和对应JSON，再从每个output档案读取同名生成代码。它不会打开参考TeX，也不运行Hungarian或空间对齐。预测中的标签直接对应参考同名标签。

对每条参考测量项，取预测中的同名点，检查所需线段是否非退化且实际绘制，再计算角度或比例。缺标签、重复冲突、缺边、退化边与程序无法解析都记录不可用原因，不替代为零误差。即便某组缺少整份程序，也保留该图及全部参考测量项的分母。

MAE/MRE主表使用各组共同可测项：先按图平均，再跨图平均。线段覆盖率按图平均，角度/比例覆盖率按完整参考项计数。不可把低覆盖率下的条件误差解释为整体更优。

几何修复消融采用按条目汇总：将raw/post两组共同可测的角度及比例分别合并，每个参考项等权，直接计算整体角度MAE、比例MRE，不先按图平均。保留所有共同项，包括未执行修复、不变和变差的条目；不按修复结果筛选。相对下降为（raw−post）/raw，逐项改善/变差计数与P90、P95、均方根误差保存在`results/latest/ablation.json`。消融表仅展示几何指标，主表仍保留三项视觉指标。两表的共同项集合与加权方式不同，不能直接比较ours的数值。

## 运行与产物

```powershell
python scripts/build_geometry_reference.py --workers 20
python scripts/evaluate_structure_ab.py --group raw=outputs/ablations/no_post_repair --group post=outputs/ours --workers 20 --out results/latest/structure.json
python scripts/evaluate_visual_cached.py --group raw=outputs/ablations/no_post_repair/image --group post=outputs/ours/image --out results/latest/visual.json
python scripts/audit_geometry_reference_cases.py
python scripts/report_core_geometry.py
python scripts/audit_research_readiness.py
python -m pytest -q
```

源码或解析规则更新后应重新构建清单。manifest保存参考JSON和原始TeX哈希；评测核验JSON与规则版本，评测过程不重新读取源TeX。如需确认源TeX更新，应运行构建步骤。

视觉评测使用相同100张图片、固定预处理和本地权重：SSIM为1000px白底画布上的灰度Gaussian SSIM，CLIP为ViT-L/14@224，DINO为DINOv2-base CLS。特征缓存按图片内容与编码配置哈希区分，缓存目录为`.cache/visual_evaluation`。

结果见[100图报告](../results/latest/report.md)。`outputs/ablations/no_post_repair`与当前post同批生成，仅保留当前同批不修复消融；旧版符号过滤消融已移除。其他生成批次的旧结果已移除。保留的历史日志中的路径可能仍记录其生成时目录，不影响当前归档位置与内容哈希。

当前输出直接位于`outputs/ours/image`、`outputs/ours/latex`和`outputs/ours/stem`，评测记录集中于`results/latest`。三种方法的主表由已有逐项分数取共同项后重新汇总，覆盖率仍以完整参考清单为分母。

当前参考还修正6983的圆心O和圆周点E；1630按实际坐标、411保留原代码。符号不产生角度真值。CV端点恢复只处理未绑定标签，已有交点绑定不会与噪声端点重新竞争；浅折线和经核验的符号方向以源图测量为依据，不自动拉成对角线。
