# 795_q_fig2 修复路由试验

同一归档 v1 与首轮报告开始，各执行至多一次 TikZ 修复。
这是重建状态的单样本回放，非完整端到端重跑，也非等成本对照。未使用 v2 或参考 LaTeX。

| 方案 | 状态 | 编译 | Critic | 必须继续修复 | SSIM | token | 视觉调用 | 秒 |
|---|---|---|---|---|---|---|---|---|
| direct | completed | True | 0.93 | False | 0.9440203150770223 | 16005 | 1 | 32.07 |
| routed | completed | True | 0.93 | False | 0.9440203150770223 | 112604 | 5 | 101.34 |

Critic 为内部启发式评审，SSIM 为现有整图协议，两者均不能替代独立结构标注。
路由组额外消耗诊断、视觉取证和 Geometry 调用，不能据此单次试验宣称优于基线。

## direct

```json
{
  "drawn_labels": [
    "A",
    "B",
    "C",
    "D",
    "E",
    "F",
    "P"
  ],
  "ges_point_labels": [
    "A",
    "B",
    "C",
    "D",
    "F",
    "P"
  ],
  "drawn_labels_without_ges_point": [
    "E"
  ],
  "ges_point_labels_not_drawn": [],
  "point_ids": {
    "P": "point_01",
    "A": "point_02",
    "D": "point_03",
    "F": "point_04",
    "B": "point_05",
    "C": "point_06"
  },
  "audit_version": "2: point labels or valid bindings/labels_point relations",
  "limitation": "Math-label extraction is heuristic; no full TikZ semantic parsing."
}
```

![direct](direct/tikz/v2/v2.png)

## routed

```json
{
  "drawn_labels": [
    "A",
    "B",
    "C",
    "D",
    "E",
    "F",
    "P"
  ],
  "ges_point_labels": [
    "A",
    "B",
    "C",
    "D",
    "E",
    "F",
    "P"
  ],
  "drawn_labels_without_ges_point": [],
  "ges_point_labels_not_drawn": [],
  "point_ids": {
    "P": "point_01",
    "A": "point_02",
    "D": "point_03",
    "F": "point_04",
    "B": "point_05",
    "C": "point_06",
    "E": "point_07"
  },
  "audit_version": "2: point labels or valid bindings/labels_point relations",
  "limitation": "Math-label extraction is heuristic; no full TikZ semantic parsing."
}
```

![routed](routed/tikz/v2/v2.png)
