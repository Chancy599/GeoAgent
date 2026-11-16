# GeoAgent · 几何图形到可编译 TikZ

GeoAgent 先从原图测量图元和标签。Geometry Agent 在生成前整理点位、连接、线型及角标方向。Code Agent 据此编写 TikZ，经坐标后修复和编译渲染后，由 Critic 对照原图检查成品并给出修订意见。生成和修复不读取参考代码。

- [150 图基准汇总](results/extended_hybrid/report.md)
- [消融实验](#消融实验)
- [整图通过率口径](#整图通过率)
- [论文实验与编辑原型](deliverables/geoagent_research_report.md)
- [本轮几何异常复核](results/latest/geometry_case_audit.md)
- [高误差样本审计](results/latest/reference_quality_audit.md)
- [流程与评测规则](docs/pipeline.md)

## 五种方法的 150 图评测

五种方法使用同一批 150 张图片。GeoAgent（ours）的结果按下方复验命令中的 `extended_hybrid` 修复模式统计。视觉相似度用 SSIM、CLIP 和 DINO 比较原图与渲染图，几何指标衡量角度、长度比、线段连接和对齐后的点位误差。

<!-- benchmark:start -->

| 方法 | SSIM ×100 ↑ | CLIP ×100 ↑ | DINO ×100 ↑ | 角度 MAE（共同可测，°）↓ | 比例 MRE（共同可测，%）↓ | **线段 F1（%）↑** | **对齐后点位误差（%）↓** | **整图通过率（1° / 2%）↑** |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| haiku-5.5 | 90.5368 | 97.4663 | 96.8133 | 1.958559 | 5.494337 | 95.6761 | 1.8604 | 57/150（38.00%） |
| gpt-5.4 | 90.5708 | 97.2459 | 96.2508 | 2.539270 | 7.415228 | 90.0352 | 2.3993 | 6/150（4.00%） |
| qwen3.5-plus | 90.3925 | 96.8428 | 95.3246 | 5.700388 | 18.012649 | 96.4916 | 5.9289 | 6/150（4.00%） |
| glm-5.3-flash | 90.2170 | 97.8734 | 97.0237 | 4.007424 | 16.067963 | 93.9367 | 3.4618 | 4/150（2.67%） |
| ours | 94.3554 | 99.3702 | 98.9812 | 0.100519 | 0.315609 | 99.9733 | 0.0935 | 129/150（86.00%） |

MAE 使用 149 张图的 2,585 个共同可测角度，MRE 使用 149 张图的 3,124 个共同可测长度比。先在每张图内平均，再对有共同项的图等权平均。缺测项不计入，误差不封顶。
其他列基于全部 150 张图。

<!-- benchmark:end -->

视觉指标按图等权平均并乘以 100。SSIM 比较统一画布上的灰度图，CLIP 和 DINO 比较整图特征的余弦相似度。

这批图已用于开发。GeoAgent 从归档的 Code Agent 输出重放后修复，四组基线沿用同批输出。[评测汇总与逐图输入哈希](results/extended_hybrid/comparison.json) · [整图通过率明细](results/extended_hybrid/reference_constraints.json)

## 消融实验

两项消融均使用同一批 150 张图，并采用主表的指标和计分规则。关闭几何约束修复时，两组共享同一份生成代码、坐标契约和编译渲染设置。[几何修复消融统计](results/extended_hybrid/ablation.json)

关闭 Critic 时，取同一运行中首次评审前通过编译和基础校验的版本，保留评审前的编译纠错。从经校验的修复前 TikZ 重放与完整方法相同的几何修复。完整方法取评审和后续修订后选出的版本，因此两项消融共享同一行完整方法作为对照。[Critic 消融统计](results/ablation/critic.json)

<!-- ablation:start -->

| 设置 | SSIM ×100 ↑ | CLIP ×100 ↑ | DINO ×100 ↑ | 角度 MAE（共同可测，°）↓ | 比例 MRE（共同可测，%）↓ | **线段 F1（%）↑** | **对齐后点位误差（%）↓** | **整图通过率（1° / 2%）↑** |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 完整方法 | 94.3554 | 99.3702 | 98.9812 | 0.104973 | 0.368299 | 99.9733 | 0.0935 | 129/150（86.00%） |
| 关闭几何约束修复 | 94.2784 | 99.3698 | 98.9869 | 0.121325 | 0.388483 | 99.8673 | 0.0991 | 125/150（83.33%） |
| 关闭 Critic | 94.2453 | 99.2107 | 98.7866 | 0.216081 | 0.646271 | 99.4810 | 0.1826 | 121/150（80.67%） |

消融表的 MAE 和 MRE 用三组共同可测的 4,317 个角度和 5,285 个长度比，分别覆盖 150 张和 150 张图。主表和消融表各自在本表的共同项上计算。[消融共同项汇总](results/ablation/common_geometry.json)

<!-- ablation:end -->

## 整图通过率

**整图几何通过率**沿用主表的冻结参考几何。一张图通过时，TikZ 能成功编译，具名线段集合完全匹配，且每个参考角度和参考长度比均可测。角度绝对误差须至多 **1°**，长度比相对误差须至多 **2%**。通过率为满足全部条件的图数除以 150。

## 几何与参考核验

新增指标借鉴平面几何图解析按图元和关系报告精确率、召回率和 F1 的做法，以及线框解析直接评估向量连接的思路。GeoAgent 用可见标签识别顶点，以此匹配线段两端。图像到 TikZ 的原始基准另报告编译、图像相似度、代码相似度和人工准确率。[Plane Geometry Diagram Parsing](https://arxiv.org/html/2205.09363) · [End-to-End Wireframe Parsing](https://arxiv.org/html/1905.03246) · [TriGeoBench](https://arxiv.org/html/2610.27626v1)

**线段 F1** 比较预测和参考的具名线段集合。线段须有至少 95% 的长度得到笔画支撑，等价的共线分段合并处理。

当前 150 张图中，GeoAgent 匹配了 1,709/1,709 条参考具名线段，共计 1 个额外端点对和 0 个缺失端点对。149 张图的线段 F1 为 100%。[差异清单](results/extended_hybrid/cohort_update.json)

**对齐后点位误差**衡量生成图和参考图中同名点的相对位置有多接近。评测从 TikZ 解析标签绑定的几何点，按标签配对，再用最小二乘拟合平移、旋转和等比缩放，把生成图对齐到参考图。对齐吸收整图在位置、朝向和尺寸上的差异。

以 $D$ 表示参考图中最远两个具名点的距离，$N$ 表示参考具名点数，$d_i$ 表示第 $i$ 个点对齐后到参考位置的直线距离。单图误差为 $\frac{100\%}{N}\sum_{i=1}^{N}\min(1,d_i/D)$。缺失点按 100% 误差计入。若同名点不足以拟合有效对齐，整张图计 100%。例如，图中最远两点相距 100 个单位，点 A 对齐后偏离 1 个单位，则 A 的点位误差为 1%。最终对 150 张图的单图误差等权平均，数值越低表示形状越接近参考图。[指标测试](tests/test_structure_geometry.py)

在 `399_q_fig5` 中，五种方法都恢复了全部 7 条参考连接，点位误差进一步区分了它们对形状的还原程度。线段指标按标签对去重，圆弧、无标签边、实虚线样式和重复描边仍需结合渲染核对。[逐图指标](.cache/extended_hybrid/scores/structure.json)

- `6983`参考O修正为(0,0)，E沿原极角投影至半径2的圆周，得到(-1.937327732, -0.496750701)。`6986`参考E使用BC与上半圆的第二交点。相关目标值和构造记录保存在`data/test/geometry_reference`。
- `1269_s_fig2` 的参考解析按编译核验后的 PC 路径顺序选取 E，再重算 M。原始参考 TeX 保持原样。
- `1489_s_fig1` 的参考 J 采用注释指定的交点坐标。`1296_q_fig3` 的参考 D 取 AF 与 CB 的交点。两条修订均记录在参考清单的 `corrections.json` 中。
- `1489_s_fig1` 的参考 P、Q 取过 C 的水平线与 ED、BH 的交点。`1270_q_fig2` 的 P 使用 BC 中点。`1479_q_fig4` 的 C 取 AD 与过 E 的竖线交点，并随之重算 F。[参考修订清单](data/test/geometry_reference/corrections.json)
- `1630`按源码实际坐标评测，不因直角符号改坐标；`411`保留原代码。
- 其他误差与诊断见[17图审计](results/latest/reference_quality_audit.md)和[参考编译坐标核验](results/latest/reference_execution_audit.json)。缺边和错误点位仍需结合覆盖率分析。

## 使用

```powershell
python -m pip install -r requirements.txt
python main.py check-env
python main.py run --image data/test/image/1035_q_fig1.png
python -m streamlit run app.py
```

模型接口由 `.env` 配置。默认开启严格几何修复。被选中的垂直、平行、共线约束须在编译后全部严格成立，同时通过已有直线关系和拓扑检查。无法验证时保留原始 TikZ。使用 `--geometry-repair-mode extended_hybrid` 可运行主表对应的修复模式，使用 `--no-geometry-repair` 可关闭后修复。编译器为 `tool/tectonic/tectonic.exe`。

## 评测与复验

参考清单在 `data/test/geometry_reference` 中按图保存标签坐标、1709 条直线段、4461 个角度和 5459 个比例。线段、角度、长度比与点位评测读取这份冻结清单，沿用其中的可见标签绑定与参考修订。独立参考约束评测读取参考 TeX 的源码几何。

```powershell
python scripts/replay_extended_pipeline.py --mode extended_hybrid --out .cache/extended_hybrid/replay --workers 8
python scripts/evaluate_structure_ab.py `
  --group haiku-5.5=outputs/baseline/haiku-5.5 `
  --group gpt-5.4=outputs/baseline/gpt-5.4 `
  --group qwen3.5-plus=outputs/baseline/qwen3.5-plus `
  --group glm-5.3-flash=outputs/baseline/glm-5.3-flash `
  --group ours=.cache/extended_hybrid/replay `
  --workers 8 --out .cache/extended_hybrid/scores/structure.json
python scripts/evaluate_visual_cached.py `
  --group haiku-5.5=outputs/baseline/haiku-5.5/image `
  --group gpt-5.4=outputs/baseline/gpt-5.4/image `
  --group qwen3.5-plus=outputs/baseline/qwen3.5-plus/image `
  --group glm-5.3-flash=outputs/baseline/glm-5.3-flash/image `
  --group ours=.cache/extended_hybrid/replay/image `
  --out .cache/extended_hybrid/scores/visual.json
```

`merge_evaluation_results.py` 核验参考清单与输入哈希，按冻结参考清单汇总。单独汇总几何时可加 `--geometry-only`。几何解析依赖本地 `geom2code`，可通过 `GEOAGENT_GEOM2CODE` 指定。

```powershell
python scripts/evaluate_reference_constraints.py `
  --group haiku-5.5=outputs/baseline/haiku-5.5/latex `
  --group gpt-5.4=outputs/baseline/gpt-5.4/latex `
  --group qwen3.5-plus=outputs/baseline/qwen3.5-plus/latex `
  --group glm-5.3-flash=outputs/baseline/glm-5.3-flash/latex `
  --group ours=.cache/extended_hybrid/replay/latex `
  --group ours-no-repair=results/latest/ablation/raw/latex `
  --out .cache/extended_hybrid/scores/reference_constraints.json `
  --details .cache/extended_hybrid/scores/reference_constraints_details.json
python scripts/merge_evaluation_results.py --results .cache/extended_hybrid/scores --ours .cache/extended_hybrid/replay --no-readme
```

Critic 消融可在完成上述完整方法重放后复验。脚本按归档哈希校验修复前源码，再用相同的修复模式生成关闭 Critic 的输出。

```powershell
python scripts/replay_critic_ablation.py --first-inputs results/ablation/critic_inputs.zip --full-replay .cache/extended_hybrid/replay --out .cache/critic_extended_ablation --summary results/ablation/critic.json --workers 12
python scripts/evaluate_structure_ab.py `
  --group ours=.cache/extended_hybrid/replay `
  --group no_repair=results/latest/ablation/raw `
  --group critic_off=.cache/critic_extended_ablation/critic_off `
  --workers 8 --out .cache/extended_hybrid/scores/structure_combined_ablation.json
```

消融表使用 `structure_combined_ablation.json` 的 `paired_geometry`。

## 当前目录

```text
outputs/
  ours/
    image/                          # 归档 PNG
    latex/                          # 归档 TikZ
    stem/                           # PDF、修复前源码与执行档案
  baseline/
    haiku-5.5/{image,latex}/         # e2e baseline
    gpt-5.4/{image,latex}/           # e2e baseline
    qwen3.5-plus/{image,latex}/     # e2e baseline
    glm-5.3-flash/{image,latex}/    # e2e baseline
results/latest/
  comparison.json, comparison.md   # 历史评测对照
  structure.json                   # 五种方法的逐图几何结果
  visual.json                      # 五种方法的逐图视觉结果
  baselines_geometry.json          # 四个端到端基线的逐项几何结果
  geometry_case_audit.md           # 本轮异常图复核与折弯定位
  reference_quality_audit.*        # 高误差参考质量审计
  report.md, result.json           # 历史评测汇总与核验
  ablation/                        # 配对指标、逐图哈希和关闭修复的 PNG/TikZ
results/extended_hybrid/
  report.md, comparison.json       # 本页主表与逐图输入哈希
  ablation.json                    # 消融与修复验收汇总
  reference_constraints.json      # 参考约束与整图指标
results/ablation/
  critic.json                      # Critic 消融汇总
  critic_inputs.zip                # 经哈希核验的首次评审前、修复前 TikZ
  common_geometry.json             # 消融表的三组共同可测 MAE 与 MRE
.cache/extended_hybrid/
  replay/                         # 后修复的 PNG、TikZ 和逐图修复记录
  scores/                         # 主表的逐图视觉与几何指标
```

归档 GeoAgent 批次用 20 个 worker 生成。主表用 8 个 worker 重放后修复。参考 TeX 来自 TriGeoBench。
