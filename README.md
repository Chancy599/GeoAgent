# GeoAgent · 几何图形到可编译 TikZ

GeoAgent 从原图测量图元和标签，生成TikZ，再做确定性坐标后修复、编译渲染与Critic检查。生成和修复不读取参考代码。直角符号笔画与专用辅助点不进入后修复候选；主体关系仍可修复。

- [当前结果与不修复消融](results/latest/report.md)
- [高误差样本审计](results/latest/reference_quality_audit.md)
- [50图的问题与修复依据](results/latest/diagnosis_50.md)
- [流程与评测规则](docs/pipeline.md)；[免训练论文路线](docs/research-roadmap-20261101.md)

## 三种方法的五项指标

使用相同100张图片；三项视觉指标为SSIM、CLIP、DINO，两项几何指标为角度MAE与线段比例MRE。视觉越高越好，MAE/MRE越低越好。

<!-- benchmark:start -->

| 方法 | SSIM ×100 ↑ | CLIP ×100 ↑ | DINO ×100 ↑ | MAE（°）↓ | MRE（%）↓ |
|---|---:|---:|---:|---:|---:|
| haiku-5.5 | 90.6932 | 97.4596 | 96.6482 | 1.731102 | 4.558524 |
| gpt-5.4 | 90.7124 | 96.9177 | 95.8915 | 2.429555 | 7.142669 |
| ours | 93.8341 | 99.1293 | 98.7979 | 0.154443 | 0.462558 |

同一100图；几何采用三组共同可测项：1711个角度、2086个比例，均覆盖100图。先按图平均，再跨图平均。

主表几何使用三组共同可测项，与不修复消融的两组均值不同。

| 方法 | 线段覆盖率（%）↑ | 角度覆盖率（%）↑ | 比例覆盖率（%）↑ |
|---|---:|---:|---:|
| haiku-5.5 | 96.4537 | 91.1430 | 90.9091 |
| gpt-5.4 | 89.2726 | 74.1459 | 73.4820 |
| ours | 99.2549 | 98.5238 | 98.4563 |

<!-- benchmark:end -->

完整数值、输入哈希与复用来源见[comparison.json](results/latest/comparison.json)。当前100图已经用于开发，不能当作独立泛化测试。缺标签、缺边或无法解析的条目记为不可用，不能作为零误差，因此同时报告覆盖率。

## 最新消融实验

<!-- ablation:start -->

| 方案 | 整体角度 MAE（°）↓ | 整体比例 MRE（%）↓ |
|---|---:|---:|
| 不修复 | 0.151423 | 0.480863 |
| 完整方法 ours | 0.129238 | 0.475866 |
| 相对下降 | 14.65% | 1.04% |

同一100图、同一所选TikZ版本，关闭或开启确定性后修复。两组共同可测项：2269个角度、2789个比例。所有共同项直接合并，每项等权，不先逐图平均，也不按是否修复或改善筛选条目。

整体角度MAE = Σ角度绝对误差 / 共同角度数；整体比例MRE = 100 × Σ比例相对误差 / 共同比例数。相对下降 =（不修复−修复后）/不修复。

逐项配对：角度改善663项、变差364项、不变1242项；比例改善779项、变差640项、不变1370项。不变容差为角度10⁻⁸°、比例相对误差10⁻⁸个百分点。

比例误差的均值小幅改善，但P90、P95及均方根误差未改善，完整分布统计见[ablation.json](results/latest/ablation.json)。不能据此声称所有比例误差均下降。

三种方法主表仍按图平均，且使用三组共同项；本消融按条目汇总并使用两组共同项，因此两表的ours数值不同。

<!-- ablation:end -->

## 几何与参考核验

- `6983`参考O修正为(0,0)，E沿原极角投影至半径2的圆周，得到(-1.937327732, -0.496750701)。`6986`参考E使用BC与上半圆的第二交点。相关目标值和构造记录保存在`data/test/geometry_reference`。
- `1630`按源码实际坐标评测，不因直角符号改坐标；`411`保留原代码。
- `50`已补齐P/Q；`1615`的虚线复用命名端点并保留E–G–B折线；`6987`保留A–E–C折线，直角标记连接EA/EB。
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

参考清单在`data/test/geometry_reference`中按图保存标签坐标、1009条直线段、2371个角度和2915个比例。评测按可见标签的代码绑定取坐标，不做最近点匹配，不评测无标签顶点。构建清单读取参考TeX，评测仅读JSON与预测程序。

```powershell
python scripts/build_geometry_reference.py --workers 20
python scripts/evaluate_structure_ab.py `
  --group raw=outputs/ablations/no_post_repair `
  --group post=outputs/ours --workers 20 --out results/latest/structure.json
python scripts/evaluate_structure_ab.py `
  --group haiku-5.5=outputs/baselines/haiku-5.5 `
  --group gpt-5.4=outputs/baselines/gpt-5.4 --workers 20 `
  --out results/latest/baselines_geometry.json
python scripts/evaluate_visual_cached.py `
  --group raw=outputs/ablations/no_post_repair/image --group post=outputs/ours/image `
  --out results/latest/visual.json
python scripts/report_core_geometry.py
python scripts/audit_high_error_cases.py
python scripts/merge_evaluation_results.py
python -m pytest -q
```

`merge_evaluation_results.py`核验参考清单与输入哈希，按三组共同可测项汇总并更新本页。解析依赖本地`geom2code`，可通过`GEOAGENT_GEOM2CODE`指定。

## 当前目录

```text
outputs/
  ours/
    image/                          # 当前100张PNG
    latex/                          # 当前100份TikZ
    stem/                           # PDF、修复前源码与执行档案
  baselines/
    haiku-5.5/{image,latex}/         # e2e baseline
    gpt-5.4/{image,latex}/           # e2e baseline
  ablations/
    no_post_repair/                  # 最新版本同批的不修复消融
  case_studies/                     # 保留案例
results/latest/
  comparison.json, comparison.md   # 三种方法、五项指标与覆盖率
  structure.json, visual.json      # 当前方法与最新消融的逐图结果
  baselines_geometry.json          # 两个e2e的逐项几何结果
  baselines_visual.json            # 两个e2e的视觉结果
  reference_quality_audit.*        # 高误差参考质量审计
  diagnosis_50.*                   # 50图生成链路诊断
  report.md, result.json           # 当前方法汇总与核验
```

旧版直角符号过滤消融已移除，只保留当前同批不修复消融。源码和图片内容保持不变；编码缓存位于`.cache/visual_evaluation`。
