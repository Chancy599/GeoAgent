# GeoAgent · 几何图形到可编译 TikZ

GeoAgent 先从原图测量图元和标签。Geometry Agent 在生成前整理点位、连接、线型及角标方向。Code Agent 据此编写 TikZ，经坐标后修复和编译渲染后，由 Critic 对照原图检查成品并给出修订意见。生成和修复不读取参考代码。

- [当前 150 图结果](results/latest/report.md)
- [本轮几何异常复核](results/latest/geometry_case_audit.md)
- [高误差样本审计](results/latest/reference_quality_audit.md)
- [流程与评测规则](docs/pipeline.md)

## 五种方法的 150 图评测

五种方法使用同一批 150 张图片。视觉相似度用 SSIM、CLIP 和 DINO 比较原图与渲染图，几何指标衡量角度、长度比、线段连接和对齐后的点位误差。

<!-- benchmark:start -->

| 方法 | SSIM ×100 ↑ | CLIP ×100 ↑ | DINO ×100 ↑ | 角度 MAE（含缺测，°）↓ | 比例 MRE（含缺测及封顶，%）↓ |
|---|---:|---:|---:|---:|---:|
| haiku-5.5 | 90.4785 | 97.4923 | 96.8642 | 20.240006 | 14.871114 |
| gpt-5.4 | 90.4433 | 97.1431 | 96.1945 | 46.621248 | 31.509152 |
| qwen3.5-plus | 90.2731 | 96.7473 | 95.3173 | 16.779830 | 22.621238 |
| glm-5.3-flash | 90.1209 | 97.8122 | 96.9606 | 26.975837 | 23.345418 |
| ours | 93.9274 | 99.1722 | 98.8486 | 0.547309 | 0.731813 |

几何指标纳入全部 150 张图、4528 个参考角度和 5516 个参考比例。缺测角度计 180°，缺测比例计 100%，可测比例误差同样封顶 100%。先在各图内平均，再等权平均 150 张图。

| 方法 | 线段覆盖率（%）↑ | 角度覆盖率（%）↑ | 比例覆盖率（%）↑ |
|---|---:|---:|---:|
| haiku-5.5 | 93.5686 | 85.4461 | 84.8622 |
| gpt-5.4 | 84.4006 | 64.9735 | 64.1407 |
| qwen3.5-plus | 95.9081 | 92.8445 | 92.2770 |
| glm-5.3-flash | 91.7243 | 79.9028 | 78.7346 |
| ours | 99.8771 | 99.4479 | 99.3655 |

线段和点位指标同样对全部 150 张图等权平均。点位误差以参考标签点集的直径为单位，表中显示百分比。

| 方法 | 线段精确率（%）↑ | 线段 F1（%）↑ | 对齐后点位误差（%）↓ |
|---|---:|---:|---:|
| haiku-5.5 | 99.1178 | 95.8579 | 1.5789 |
| gpt-5.4 | 98.9079 | 90.0047 | 2.4453 |
| qwen3.5-plus | 95.9388 | 95.6713 | 5.9071 |
| glm-5.3-flash | 98.3490 | 94.2551 | 3.4098 |
| ours | 99.0790 | 99.4313 | 0.1156 |

<!-- benchmark:end -->

视觉指标按 150 张图等权平均，表中乘以 100。SSIM 在 1000 × 1000 白底画布上比较灰度图。CLIP 和 DINO 计算整图特征的余弦相似度。逐图视觉值和图片哈希见 [visual.json](results/latest/visual.json)。

这批图已用于系统开发。缺标签、缺边或无法解析的条目按主表规则计分，同时报告实际覆盖率。完整汇总与输入哈希见 [comparison.json](results/latest/comparison.json)。

## 几何与参考核验

新增指标借鉴平面几何图解析按图元和关系报告精确率、召回率和 F1 的做法，以及线框解析直接评估向量连接的思路。GeoAgent 用可见标签识别顶点，以此匹配线段两端。图像到 TikZ 的原始基准另报告编译、图像相似度、代码相似度和人工准确率。[Plane Geometry Diagram Parsing](https://arxiv.org/html/2205.09363) · [End-to-End Wireframe Parsing](https://arxiv.org/html/1905.03246) · [TriGeoBench](https://arxiv.org/html/2610.27626v1)

| 指标 | 定义与适用范围 |
|---|---|
| 线段精确率和 F1 | 将实际绘制的直线归为无序端点标签对，再比较预测和参考集合。沿用至少 95% 线段长度有笔画支撑的判据，等价的共线分段合并计分。精确率衡量多画边，召回率就是上表的线段覆盖率，F1 综合两者。范围限于两端有标签的直线连接。 |
| 对齐后点位误差 | 用共有标签拟合平移、旋转和统一缩放，保留镜像差异。点位残差除以参考标签点集的最大两点距离，再对每图所有参考标签取平均。残差封顶 100%，缺失标签计 100%。共有点在任一侧不足三个非共线点，或拟合会将图形缩成一点时，该图计 100%。 |

用可控 TikZ 样例校验了指标。四边形多画一条对角线时，线段精确率降到 80%，F1 降到 88.89%，点位误差仍为 0。删掉一条边时，线段召回率降到 75%，F1 降到 85.71%。把一个顶点标签改成另一个字母时，该缺失点使整图点位误差达到 25%。点位误差会随局部形变增大，并能检出镜像。整体平移、旋转和等比缩放、共线分段、标签排版偏移及直角符号写法的变化通过了等价性检查。150 份参考 TikZ 经既有参考校正后自比，线段 F1 均为 100%，最大归一化点位误差低于 10⁻¹²。[指标测试](tests/test_structure_geometry.py)

在 `399_q_fig5` 中，五种方法都恢复了全部 7 条参考连接，点位误差进一步区分了它们对形状的还原程度。线段指标按标签对去重，圆弧、无标签边、实虚线样式和重复描边仍需结合渲染核对。点位误差衡量对齐后的整体形状，拟合时一个错绑点也可能影响其他点的残差。[逐图指标](results/latest/structure.json)

- `6983`参考O修正为(0,0)，E沿原极角投影至半径2的圆周，得到(-1.937327732, -0.496750701)。`6986`参考E使用BC与上半圆的第二交点。相关目标值和构造记录保存在`data/test/geometry_reference`。
- `1269_s_fig2` 的参考解析按编译核验后的 PC 路径顺序选取 E，再重算 M。原始参考 TeX 保持原样。
- `1630`按源码实际坐标评测，不因直角符号改坐标；`411`保留原代码。
- 其他误差与诊断见[17图审计](results/latest/reference_quality_audit.md)和[参考编译坐标核验](results/latest/reference_execution_audit.json)。缺边和错误点位仍需结合覆盖率分析。

## 使用

```powershell
python -m pip install -r requirements.txt
python main.py check-env
python main.py run --image data/test/image/1035_q_fig1.png
python -m streamlit run app.py
```

模型接口由`.env`配置，参数见`configs/default.json`。`--no-geometry-repair`关闭后修复。编译器为`tool/tectonic/tectonic.exe`。

## 评测与复验

参考清单在 `data/test/geometry_reference` 中按图保存标签坐标、1731 条直线段、4528 个角度和 5516 个比例。评测按可见标签的代码绑定取坐标。构建清单读取参考 TeX，评测仅读 JSON 与预测程序。

```powershell
python scripts/evaluate_structure_ab.py `
  --group haiku-5.5=outputs/baseline/haiku-5.5 `
  --group gpt-5.4=outputs/baseline/gpt-5.4 `
  --group qwen3.5-plus=outputs/baseline/qwen3.5-plus `
  --group glm-5.3-flash=outputs/baseline/glm-5.3-flash `
  --group ours=outputs/ours `
  --workers 20 --out results/latest/structure.json
python scripts/evaluate_visual_cached.py `
  --group haiku-5.5=outputs/baseline/haiku-5.5/image `
  --group gpt-5.4=outputs/baseline/gpt-5.4/image `
  --group qwen3.5-plus=outputs/baseline/qwen3.5-plus/image `
  --group glm-5.3-flash=outputs/baseline/glm-5.3-flash/image `
  --group ours=outputs/ours/image `
  --out results/latest/visual.json
python scripts/merge_evaluation_results.py
```

`merge_evaluation_results.py` 核验参考清单与输入哈希，按固定 150 图汇总并更新本页。单独汇总几何时可加 `--geometry-only`。几何解析依赖本地 `geom2code`，可通过 `GEOAGENT_GEOM2CODE` 指定。

## 当前目录

```text
outputs/
  ours/
    image/                          # 当前150张PNG
    latex/                          # 当前150份TikZ
    stem/                           # PDF、修复前源码与执行档案
  baseline/
    haiku-5.5/{image,latex}/         # e2e baseline
    gpt-5.4/{image,latex}/           # e2e baseline
    qwen3.5-plus/{image,latex}/     # e2e baseline
    glm-5.3-flash/{image,latex}/    # e2e baseline
results/latest/
  comparison.json, comparison.md   # 五种方法的视觉、几何指标与覆盖率
  structure.json                   # 五种方法的逐图几何结果
  visual.json                      # 五种方法的逐图视觉结果
  baselines_geometry.json          # 四个端到端基线的逐项几何结果
  geometry_case_audit.md           # 本轮异常图复核与折弯定位
  reference_quality_audit.*        # 高误差参考质量审计
  report.md, result.json           # 当前方法汇总与核验
```

当前 GeoAgent 批次用 20 个 worker 生成。参考 TeX 来自 TriGeoBench。运行中间文件和视觉特征缓存位于 `.cache/`。
