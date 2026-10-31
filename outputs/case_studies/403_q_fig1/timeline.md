# 403_q_fig1 处理流程

## 概览

- 图：`data/test/image/403_q_fig1.png`（434×410）
- 最终版本：v5，critic 分数 0.9
- 整图指标：SSIM 92.03 / CLIP 99.17 / DINO 98.85
- 统计：{'steps': 18, 'tool_calls': 16, 'objects': 44, 'relations': 21, 'tikz_versions': 5, 'compilations': 5, 'critic_reports': 5, 'conflicts': 4, 'unresolved': 6}

## 阶段图片

| 文件 | 阶段 | 说明 | 工具结果 |
| --- | --- | --- | --- |
| `00_input.png` | 输入 | 原始题图 | — |
| `s02_lines.png` | lines | Line detection (8 raw segments) | count=8 |
| `s03_circles.png` | circles | Circle detection: 1 FALSE POSITIVE arc | count=1 |
| `s04_right_angle.png` | right_angle | Right-angle mark at A (1 verified) | count=1 |
| `s05_labels.png` | labels | Label binding (A-E) | count=None |
| `ges.png` | GES | 几何证据状态叠加图 | 44 objects / 21 relations |
| `v1.png` | v1 | generate | critic=0.45 |
| `v2.png` | v2 | repair | critic=0.88 |
| `v3.png` | v3 | repair | critic=0.88 |
| `v4.png` | v4 | repair | critic=0.86 |
| `v5.png` | v5 | repair | critic=0.9 |
| `final.png` | 最终 | 归档 best.png | — |

## 动作序列

| step | action | purpose | status | result |
| ---: | --- | --- | --- | --- |
| 1 | call_cv_tool:detect_lines | Detect straight segments on whole figure | ok | ok=True; count=8 |
| 2 | call_cv_tool:detect_right_angle_marker | Detect right-angle marks | ok | ok=True; count=1 |
| 3 | call_cv_tool:detect_circles | Detect circles/arcs on whole figure | ok | ok=True; count=1 |
| 4 | call_cv_tool:bind_point_labels | Install point labels via glyph extraction and binding | ok | ok=True |
| 5 | run_geometry_agent | Reconcile geometry for a figure (image 434x410, pixel origin top-left). Verified labels: A=(70,341) bottom-left; B=(384, | ok | ok=True; merged={'objects': 14, 'relations': 16, 'conflicts': 4, 'rejected': []} |
| 6 | run_tikz_agent | Draw figure in TikZ (use pixel coordinates scaled by ~0.01 and flip y, e.g. x_tikz = x_px/100, y_tikz = (410 - y_px)/100 | ok | ok=True; version=1; compile_ok=True; validation_passed=True; best_version=1 |
| 7 | run_critic | arc extent, dashed segments, labels, right-angle mark | ok | ok=True; version=1; best_version=1; assessment_score=0.45; issues=5 |
| 8 | inspect_image | Is there a circular arc in the original figure? If so, describe where it runs (which labelled points it passes near, e.g | ok | ok=True |
| 9 | run_tikz_agent | Remove ALL arc/circle drawing commands (there is no circular arc in the original). Keep only: solid segments A-B (y=341  | ok | ok=True; version=2; compile_ok=True; validation_passed=True; best_version=1 |
| 10 | run_critic | arc removed, CD reaches D, stub above E, right angle at A | ok | ok=True; version=2; best_version=2; assessment_score=0.88; issues=1 |
| 11 | run_tikz_agent | Extend the dashed vertical segment D-E upward past E so it overhangs E by a short dashed stub (about 0.08 units / ~4 px  | ok | ok=True; version=3; compile_ok=True; validation_passed=True; best_version=2 |
| 12 | run_critic | stub above E and overall match | ok | ok=True; version=3; best_version=3; assessment_score=0.88; issues=1 |
| 13 | run_tikz_agent | The dashed stub above E must be much longer: extend the dashed vertical line from E upward to about y_px=33, which is ab | ok | ok=True; version=4; compile_ok=True; validation_passed=True; best_version=3 |
| 14 | run_critic | stub above E length and overall match | ok | ok=True; version=4; best_version=4; assessment_score=0.86; issues=2 |
| 15 | finish | finish run | error | ok=False; error=finish blocked: best version 4 still has 0 high, 1 medium and 1 low action |
| 16 | run_tikz_agent | Lengthen the dashed vertical stub above E by about 0.31 units: change the top endpoint Estub from (0,6.85) to (0,7.16).  | ok | ok=True; version=5; compile_ok=True; validation_passed=True; best_version=4 |
| 17 | run_critic | stub above E length | ok | ok=True; version=5; best_version=5; assessment_score=0.9; issues=1 |
| 18 | finish | finish run | ok | ok=True; best_version=5; status=success |

## Critic 轮次

### v1 — score 0.45

Labels, dashed EC/ED, solid AB/AD/BC and the right angle at A match the original, but the render adds spurious arcs and stray marks and truncates CD before it reaches D.

| type | severity | description |
| --- | --- | --- |
| arc_error | high | The render draws a circular arc (about 159 degrees, centred near A/D) and a second arc near C that do not appear in the original figure. |
| wrong_position | medium | Segment CD stops short of vertex D (ends near the midpoint of CD), whereas in the original it runs from C all the way to D on the vertical line. |
| other | low | A stray short mark ('l'-like stroke) sits on or next to segment BC, with no counterpart in the original. |
| other | low | A short arc fragment is drawn along the base near AB, between A and B, with no counterpart in the original. |
| missing_element | low | The original extends the vertical line slightly above E as a short stub; the render stops the dashed line at E. |

### v2 — score 0.88

Render matches the original closely: arc removed, CD reaches D, and the right angle at A is present. The one discrepancy is the dashed stub above E, which the original extends past E and the render stops at E.

| type | severity | description |
| --- | --- | --- |
| wrong_position | medium | The original dashed vertical line through E overhangs above E by a short stub (about 50 px above the E label's baseline). The render's dashed segment ends exactly at E, so the stub is missing. |

### v3 — score 0.88

Render closely matches the original: same quadrilateral/triangle layout, labels, dashed auxiliary lines and right-angle mark at A. The only discrepancy is the short dashed stub that extends above E in the original.

| type | severity | description |
| --- | --- | --- |
| wrong_position | medium | The original's vertical dashed line through E continues past E upward as a short stub (ending near the top of the panel). In the render the dashed line ends exactly at E, so the overhang above E is missing. |

### v4 — score 0.86

Close match overall; the main discrepancy is that the dashed stub above E is shorter in the render than in the original.

| type | severity | description |
| --- | --- | --- |
| wrong_position | medium | The dashed vertical stub above E ends roughly 14 px lower in the render than in the original. In the original it rises to near the top edge of the panel (about 50 px above E), while in the render it stops about 37 px abo |
| wrong_position | low | Checklist: segment seg_ED is visible but misplaced. |

### v5 — score 0.9

Render closely matches the original; the only notable difference is that the dashed stub above E is somewhat longer in the render.

| type | severity | description |
| --- | --- | --- |
| wrong_position | low | The dashed stub extending above E is longer in the render (about 12-13% of figure height above E) than in the original (about 10%). The render's stub ends slightly higher than the original's. |

## 建议 PPT 页

1. 标题页：原图 + 一句话说明本图的几何结构。
2. 证据页：依次放 `s02` 线检测、`s03` 圆/弧检测（如有）、`s04` 直角、`s05` 标签。
3. 状态页：`ges.png` + 右侧列 objects/relations 数量。
4. 迭代页：v1 → … → final，并在每张下标注 critic 分数。
5. 结论页：final 与 input 并排，写最终 SSIM/CLIP/DINO。

总览图：`storyboard_403_q_fig1.png`。