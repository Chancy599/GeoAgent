# GeoAgent 案例素材（PPT 用）

每个案例一个目录，包含输入、CV 阶段图、GES 叠加图、每个 TikZ 版本、并排对比图、时间线与 `case.json`。

## 案例一览

| 案例 | 版本数 | best | SSIM | CLIP | DINO | 用途 |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| 6984_q_fig1 | 3 | 0.95 | 93.25 | 98.84 | 99.03 | critic style repair |
| 403_q_fig1 | 5 | 0.9 | 92.03 | 99.17 | 98.85 | critic removes a spurious CV arc (0.45 -> 0.88 -> 0.90) |
| 1260_q_fig2 | 2 | 0.93 | 96.88 | 99.75 | 99.43 | critic restores the missing F->G dashed line (0.85 -> 0.93) |

## 建议讲法

1. **主流程页**：用 `6984_q_fig1`。输入 → 线/圆/直角/标签 → GES → v1/v2/v3，critic 从 0.90 到 0.95。
2. **Critic 实质作用页**：用 `403_q_fig1`。展示 v1（多出的假弧、CD 未到 D，0.45）→ v2（删弧补线，0.88）→ v5（0.90）。
3. **缺失元素修复页**：用 `1260_q_fig2`。v1 漏掉 F→G 虚线和 G 标签（0.85）→ v2 补上（0.93）。

## 注意事项

- 中间版本由 `state.json.tikz_versions[].tex` 重新编译，并做了与原图一致的取景（`frame_like_original`）；重编译的 best 与归档 `best.png` 逐像素一致。
- `403_q_fig1` 的圆检测阶段图是**假阳性**，正好用于说明 CV 会犯错、Critic 负责纠错。
- 原始 `s05_labels.png` 是 CV 工具的调试叠加图（含 point/label id），信息较密；如果幻灯片上显得杂乱，可用同目录的 `ges.png` 代替。
- 指标来自 `outputs/metrics/ours100.json`，均为整图指标（×100 展示）。
- 生成脚本：`outputs/case_studies/build.py`。