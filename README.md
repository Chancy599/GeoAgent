# GeoAgent · 几何图形到可编译 TikZ

GeoAgent 从原图测量图元和标签，生成TikZ，再做确定性坐标后修复、编译渲染与Critic检查。生成和修复不读取参考代码。直角符号笔画与专用辅助点不进入后修复候选；主体关系仍可修复。

- [当前100图结果](results/latest/report.md)
- [高误差样本审计](results/latest/reference_quality_audit.md)
- [流程与评测规则](docs/pipeline.md)

## 五种方法的五项指标

使用相同100张图片；三项视觉指标为SSIM、CLIP、DINO，两项几何指标为计入缺测的角度 MAE 与封顶的线段比例 MRE。视觉越高越好，MAE/MRE越低越好。

<!-- benchmark:start -->

| 方法 | SSIM ×100 ↑ | CLIP ×100 ↑ | DINO ×100 ↑ | 角度 MAE（含缺测，°）↓ | 比例 MRE（含缺测及封顶，%）↓ |
|---|---:|---:|---:|---:|---:|
| haiku-5.5 | 90.6932 | 97.4596 | 96.6482 | 11.901429 | 10.399914 |
| gpt-5.4 | 90.7124 | 96.9177 | 95.8915 | 33.274714 | 23.914681 |
| qwen3.5-plus | 90.5849 | 96.8610 | 95.4079 | 14.913185 | 20.919235 |
| glm-5.3-flash | 90.4386 | 97.7041 | 96.7128 | 21.412785 | 19.711658 |
| ours | 94.1265 | 99.2623 | 98.8637 | 2.755464 | 2.033783 |

几何指标纳入全部 100 张图、2371 个参考角度和 2915 个参考比例。缺测角度计 180°，缺测比例计 100%，可测比例误差同样封顶 100%。先在各图内平均，再等权平均 100 张图。

| 方法 | 线段覆盖率（%）↑ | 角度覆盖率（%）↑ | 比例覆盖率（%）↑ |
|---|---:|---:|---:|
| haiku-5.5 | 96.4537 | 91.1430 | 90.9091 |
| gpt-5.4 | 89.2726 | 74.1459 | 73.4820 |
| qwen3.5-plus | 96.1325 | 93.8001 | 92.8645 |
| glm-5.3-flash | 93.6508 | 83.2982 | 82.2298 |
| ours | 98.9392 | 98.3973 | 98.2161 |

<!-- benchmark:end -->

完整数值与输入哈希见[comparison.json](results/latest/comparison.json)。当前100图已经用于开发，不能当作独立泛化测试。缺标签、缺边或无法解析的条目按主表规则计分，同时报告实际覆盖率。

## 几何与参考核验

- `6983`参考O修正为(0,0)，E沿原极角投影至半径2的圆周，得到(-1.937327732, -0.496750701)。`6986`参考E使用BC与上半圆的第二交点。相关目标值和构造记录保存在`data/test/geometry_reference`。
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

参考清单在`data/test/geometry_reference`中按图保存标签坐标、1009条直线段、2371个角度和2915个比例。评测按可见标签的代码绑定取坐标，不做最近点匹配，不评测无标签顶点。构建清单读取参考TeX，评测仅读JSON与预测程序。

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

`merge_evaluation_results.py`核验参考清单与输入哈希，按固定 100 图汇总并更新本页。解析依赖本地`geom2code`，可通过`GEOAGENT_GEOM2CODE`指定。

## 当前目录

```text
outputs/
  ours/
    image/                          # 当前100张PNG
    latex/                          # 当前100份TikZ
    stem/                           # PDF、修复前源码与执行档案
  baseline/
    haiku-5.5/{image,latex}/         # e2e baseline
    gpt-5.4/{image,latex}/           # e2e baseline
    qwen3.5-plus/{image,latex}/     # e2e baseline
    glm-5.3-flash/{image,latex}/    # e2e baseline
results/latest/
  comparison.json, comparison.md   # 五种方法、五项指标与覆盖率
  structure.json, visual.json      # 五种方法的逐图结果
  baselines_geometry.json          # 四个端到端基线的逐项几何结果
  baselines_visual.json            # 四个端到端基线的视觉结果
  reference_quality_audit.*        # 高误差参考质量审计
  report.md, result.json           # 当前方法汇总与核验
```

本批 GeoAgent、Qwen3.5-Plus 和 GLM-5.3-Flash 均使用 20 个 worker。参考清单沿用固定的 100 图，运行中间文件和编码缓存位于 `.cache/`。
