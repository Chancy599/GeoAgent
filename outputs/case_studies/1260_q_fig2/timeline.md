# 1260_q_fig2 处理流程

## 概览

- 图：`data/test/image/1260_q_fig2.png`（705×320）
- 最终版本：v2，critic 分数 0.93
- 整图指标：SSIM 96.88 / CLIP 99.75 / DINO 99.43
- 统计：{'steps': 8, 'tool_calls': 9, 'objects': 35, 'relations': 11, 'tikz_versions': 2, 'compilations': 2, 'critic_reports': 2, 'conflicts': 2, 'unresolved': 6}

## 阶段图片

| 文件 | 阶段 | 说明 | 工具结果 |
| --- | --- | --- | --- |
| `00_input.png` | 输入 | 原始题图 | — |
| `s02_lines.png` | lines | Line detection (8 segments) | count=8 |
| `s03_labels.png` | labels | Label binding (G left unbound) | count=None |
| `s04_right_angle.png` | right_angle | Right-angle check (0 marks) | count=0 |
| `s05_line_style.png` | line_style | Dashed/solid classification | count=3 |
| `ges.png` | GES | 几何证据状态叠加图 | 35 objects / 11 relations |
| `v1.png` | v1 | generate | critic=0.85 |
| `v2.png` | v2 | repair | critic=0.93 |
| `final.png` | 最终 | 归档 best.png | — |

## 动作序列

| step | action | purpose | status | result |
| ---: | --- | --- | --- | --- |
| 1 | call_cv_tool:detect_lines | Find line segments in the figure | ok | ok=True; count=8 |
| 2 | call_cv_tool:bind_point_labels | Bind labels to vertices | ok | ok=True |
| 3 | run_geometry_agent | Reconcile this figure. Verified labelled points (pixel coords, origin top-left): A(68.5,65), B(68.5,254), C(635.5,254),  | ok | ok=True; merged={'objects': 14, 'relations': 5, 'conflicts': 2, 'rejected': []} |
| 4 | run_tikz_agent | Draw the figure with black thin strokes, no fills. Use TikZ y-up coordinates: flip y using y_tikz = -(y_px) scaled (scal | ok | ok=True; version=1; compile_ok=True; validation_passed=True; best_version=1 |
| 5 | run_critic | line extents, dashed segments, label placement | ok | ok=True; version=1; best_version=1; assessment_score=0.85; issues=2 |
| 6 | run_tikz_agent | Repair: extend segment A-F beyond F to point G on the base line y=254 (pixel coords). Line A(68.5,65) to F(238.3,149.6)  | ok | ok=True; version=2; compile_ok=True; validation_passed=True; best_version=1 |
| 7 | run_critic | verify dashed FG extension to G on base and G label | ok | ok=True; version=2; best_version=2; assessment_score=0.93 |
| 8 | finish | finish run | ok | ok=True; best_version=2; status=success |

## Critic 轮次

### v1 — score 0.85

The render matches the original's vertices, sides, and dashed auxiliary lines, but omits the dashed extension of AF from F to G on BC and the G label.

| type | severity | description |
| --- | --- | --- |
| missing_element | high | The original continues the line from F to G on BC as a dashed segment. The render stops AF at F and has no dashed FG. |
| missing_element | medium | The label G is missing at the foot of the dashed line on BC, to the left of C. |

### v2 — score 0.93

Render is faithful to the original: the dashed F-to-G extension ends on the base at G, and all labels are present and attached correctly.

## 建议 PPT 页

1. 标题页：原图 + 一句话说明本图的几何结构。
2. 证据页：依次放 `s02` 线检测、`s03` 圆/弧检测（如有）、`s04` 直角、`s05` 标签。
3. 状态页：`ges.png` + 右侧列 objects/relations 数量。
4. 迭代页：v1 → … → final，并在每张下标注 critic 分数。
5. 结论页：final 与 input 并排，写最终 SSIM/CLIP/DINO。

总览图：`storyboard_1260_q_fig2.png`。