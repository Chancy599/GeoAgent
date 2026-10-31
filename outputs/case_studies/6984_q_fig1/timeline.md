# 6984_q_fig1 处理流程

## 概览

- 图：`data/test/image/6984_q_fig1.png`（530×485）
- 最终版本：v3，critic 分数 0.95
- 整图指标：SSIM 93.25 / CLIP 98.84 / DINO 99.03
- 统计：{'steps': 14, 'tool_calls': 12, 'objects': 35, 'relations': 25, 'tikz_versions': 3, 'compilations': 3, 'critic_reports': 3, 'conflicts': 0, 'unresolved': 4}

## 阶段图片

| 文件 | 阶段 | 说明 | 工具结果 |
| --- | --- | --- | --- |
| `00_input.png` | 输入 | 原始题图 | — |
| `s02_lines.png` | lines | Line detection (4 segments) | count=4 |
| `s03_circles.png` | circles | Circle detection (1 full circle) | count=1 |
| `s04_right_angle.png` | right_angle | Right-angle mark at F (1 verified) | count=1 |
| `s05_labels.png` | labels | Label binding (8/8 letters) | count=None |
| `ges.png` | GES | 几何证据状态叠加图 | 35 objects / 25 relations |
| `v1.png` | v1 | generate | critic=0.9 |
| `v2.png` | v2 | repair | critic=0.9 |
| `v3.png` | v3 | repair | critic=0.95 |
| `final.png` | 最终 | 归档 best.png | — |

## 动作序列

| step | action | purpose | status | result |
| ---: | --- | --- | --- | --- |
| 1 | call_cv_tool:detect_lines | Get whole-figure line segments as first evidence pass. | ok | ok=True; count=4 |
| 2 | call_cv_tool:detect_circles | Check for circles or arcs. | ok | ok=True; count=1 |
| 3 | inspect_image | Describe the figure: the circle, the labeled points (letters), and the lines. Is the circle full or a semicircle? Which  | ok | ok=True |
| 4 | call_cv_tool:detect_right_angle_marker | Verify the right-angle square mark at F between DG and AB. | ok | ok=True; count=1 |
| 5 | call_cv_tool:bind_point_labels | Bind letter labels to vertices. | ok | ok=True |
| 6 | call_cv_tool:bind_point_labels | Bind letter labels to derived geometric vertices using the default pipeline. | ok | ok=True |
| 7 | run_geometry_agent | Consolidate this figure into GES objects and relations. Image px coords origin top-left, y down.
Full circle: center O a | ok | ok=True; merged={'objects': 14, 'relations': 17, 'conflicts': 0, 'rejected': []} |
| 8 | run_tikz_agent | Draw a full circle centered at O with radius 196.7 px (scale so the figure fits, e.g. 1 px = 0.0125 cm, or use coordinat | ok | ok=True; version=1; compile_ok=True; validation_passed=True; best_version=1 |
| 9 | run_critic | labels, right-angle mark, E position, full circle | ok | ok=True; version=1; best_version=1; assessment_score=0.9; issues=2 |
| 10 | run_tikz_agent | Move the label F to below-right of point F (anchor north west, i.e. label[below right] at F) so it sits to the right of  | ok | ok=True; version=2; compile_ok=True; validation_passed=True; best_version=1 |
| 11 | run_critic | F label side relative to chord DG; stroke weight of circle and AB vs original | ok | ok=True; version=2; best_version=1; assessment_score=0.9; issues=2 |
| 12 | run_tikz_agent | Make the circle and diameter AB heavier than the chords: set the circle and the segment A--B to line width 1.4pt, and se | ok | ok=True; version=3; compile_ok=True; validation_passed=True; best_version=1 |
| 13 | run_critic | stroke weight of circle and AB vs chords; F label | ok | ok=True; version=3; best_version=3; assessment_score=0.95 |
| 14 | finish | finish run | ok | ok=True; best_version=3; status=success |

## Critic 轮次

### v1 — score 0.9

Render matches the original's construction (full circle, diameter AB, chord DG, chord AC through E, segment OE, right angle at F). The main discrepancy is the placement of the F label, and the render strokes are lighter than the original.

| type | severity | description |
| --- | --- | --- |
| label_error | medium | The F label sits below-right of the F vertex in the original (to the right of the DG line). In the render it sits below-left of F, on the other side of the chord. |
| wrong_style | low | The circle and diameter AB are drawn with a visibly heavier stroke in the original than in the render, which uses a thinner line. |

### v2 — score 0.9

Geometry, labels and F label side match the original; the render's circle and AB strokes are visibly thinner than the original's.

| type | severity | description |
| --- | --- | --- |
| wrong_style | medium | Circle stroke is too thin in the render. The original circle is noticeably heavier than the render's hairline circle. |
| wrong_style | medium | Diameter AB stroke is too thin in the render. In the original it is as heavy as the circle; in the render it matches the thin chords. |

### v3 — score 0.95

Render is faithful to the original: circle, diameter AB, chords AC and DG, segment OE, right angle at F and all eight labels match in position and style. Stroke weights of circle and AB versus the thinner chords look comparable in both panels, so no style issue is raised.

## 建议 PPT 页

1. 标题页：原图 + 一句话说明本图的几何结构。
2. 证据页：依次放 `s02` 线检测、`s03` 圆/弧检测（如有）、`s04` 直角、`s05` 标签。
3. 状态页：`ges.png` + 右侧列 objects/relations 数量。
4. 迭代页：v1 → … → final，并在每张下标注 critic 分数。
5. 结论页：final 与 input 并排，写最终 SSIM/CLIP/DINO。

总览图：`storyboard_6984_q_fig1.png`。