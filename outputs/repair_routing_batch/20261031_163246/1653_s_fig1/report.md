# 1653_s_fig1 修复路由试验

同一归档 v1 与首轮报告开始，各执行至多一次 TikZ 修复。
这是重建状态的单样本回放，非完整端到端重跑，也非等成本对照。未使用 v2 或参考 LaTeX。

| 方案 | 状态 | 编译 | Critic | 必须继续修复 | SSIM | token | 视觉调用 | 秒 |
|---|---|---|---|---|---|---|---|---|
| direct | completed | True | 0.9 | True | 0.9629785458254355 | 19042 | 1 | 40.24 |
| routed | completed | True | 0.9 | True | 0.9646735174665412 | 63176 | 3 | 110.66 |

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
    "M",
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
  "drawn_labels_without_ges_point": [
    "M"
  ],
  "ges_point_labels_not_drawn": [],
  "point_ids": {
    "A": "point_01",
    "F": "point_02",
    "P": "point_03",
    "D": "point_04",
    "E": "point_05",
    "C": "point_06",
    "B": "point_07"
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
    "M",
    "P"
  ],
  "ges_point_labels": [
    "A",
    "B",
    "C",
    "D",
    "E",
    "F",
    "M",
    "P"
  ],
  "drawn_labels_without_ges_point": [],
  "ges_point_labels_not_drawn": [],
  "point_ids": {
    "A": "point_01",
    "F": "point_02",
    "P": "point_03",
    "D": "point_04",
    "E": "point_05",
    "C": "point_06",
    "B": "point_07",
    "M": "point_M"
  },
  "audit_version": "2: point labels or valid bindings/labels_point relations",
  "limitation": "Math-label extraction is heuristic; no full TikZ semantic parsing."
}
```

![routed](routed/tikz/v2/v2.png)
