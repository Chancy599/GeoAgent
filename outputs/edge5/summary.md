# 边界样例批次（5 图，优化后最终结果）

运行命令（按需复现）：

```powershell
python main.py batch --only 1266_s_fig1 1270_q_fig2 1467_q_fig5 971_q_fig2 6220_s_fig2 `
  --out-dir outputs/batch_edge --report outputs/batch_edge/report.json
```

其中 1266 与 971 在最后一轮 CV/Agent 修复后重跑，结果取自 `outputs/batch_edge2`；其余三张取自 `outputs/batch_edge`。每张图仅保留 `best.tex/pdf/png`、`result.json`、`state.json`、`events.jsonl`、`llm_calls.jsonl`（Critic 报告见 `state.json` 的 `critic_reports`）。

| 图片 | 状态 | 最佳版本 | Critic | 耗时 | tokens | 视觉调用 | 步数 |
|---|---|---|---|---|---|---|---|
| 1266_s_fig1 | success | v1 | 0.90 | 113.4s | 89,896 | 5 | 8 |
| 971_q_fig2 | success | v2 | 0.95 | 124.3s | 188,047 | 8 | 10 |
| 1270_q_fig2 | success | v1 | 0.93 | 143.9s | 92,237 | 5 | 9 |
| 1467_q_fig5 | success | v1 | 0.95 | 92.5s | 158,213 | 1 | 8 |
| 6220_s_fig2 | success | v2 | 0.96 | 188.4s | 149,047 | 8 | 11 |

平均 Critic 0.938，平均 135k tokens/图。

## 各图要点

- **1266_s_fig1**（双圆、弦、虚线）：两圆、AB 直径、F–E 割线、EB/CB 虚线、7 个标签均正确。Critic 剩余两条低严重度问题：渲染在每个点上画了小圆点（原图没有），标签偏移略有差异。
- **971_q_fig2**（缺陷文件名 + 弧上同名字母 C/C'）：CV 读出 C'（带撇），Supervisor 用一次 `inspect_image` 复核后交给几何 Agent；v1 标签位置问题经一次整图修复后 0.90 → 0.95。
- **1270_q_fig2**（内切小圆、中心双点、虚线）：一次生成即 0.93，无具体问题；A/B/C/M/O/P 标签齐全。
- **1467_q_fig5**（直角标记、虚线 C–N）：`detect_right_angle_marker` 验证到 N 处小方块，虚线 C–N 与六个标签全部还原，0.95。
- **6220_s_fig2**（1080px 大图、多弦交点、直角 G）：E/G 交点、直角标记、A–H 标签正确；v1 仅 G 标签位置偏左，修复后 0.96。

## 本批次带出的系统修复

1. 数据集配对：`data/test/image/,971_q_fig2.png` 的前导逗号在扫描时归一化为 `971_q_fig2`（数据文件不动），100/100 图-参考对全部配对；`main.py batch --only ...` 不再被 `--limit` 截断。
2. 标签识别：虚线图会让大量 2×9 px 划线碎片进入文本掩膜，旧的“连通域高度中位数”把 cap height 估成 10 px，导致真字母全部被过滤。现改为只在“字形尺寸合理”的连通域上估计 cap height，并按 0.62·cap 过滤划线碎片；低 NCC（<0.45）一律返回 `?`，不再输出 `1`/`3`/`U` 等误读；新增撇号检测（C → C'）。
3. 截断保护：`finish_reason=length` 的回复即使携带 tool call 也整段丢弃；空几何提交（无 objects/relations）会被拒绝并提示重新提交。
4. TikZ 提交校验：只接受完整 standalone 文档（documentclass + document + tikzpicture 成对），prose/片段会在子 Agent 内部被退回重交，不再浪费一个编译版本。
5. Supervisor 提示：明确仅允许 6 个动作名（拒绝 Bash/ToolSearch/Glob 等幻觉工具），并在 CV 标签低置信/缺失时用 `inspect_image` 复核后再交给几何 Agent。
