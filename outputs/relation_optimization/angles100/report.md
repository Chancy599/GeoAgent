# 平行与垂直约束下的坐标优化

输入为已有生成代码的坐标。仅采用≤0.5°的平行/垂直候选。以原始点位移平方和为目标，联合迭代投影到关系等式约束上；保持已有内部点与线段的连接及原有微小偏移，不施加等长约束。

保护条件：单点位移≤图形对角线0.5%，任何原有线段长度变化≤1%，不允许线段反向、塌缩或内部点越过端点。失败时从角度误差最大的候选起剔除重解；无法接受时返回原坐标。

带圆/圆弧/椭圆的图暂不优化，因为还没有保圆约束。输出为实验副本，不修改ours100，也不接入主流水线。optimized.tex保留17位有效数字并局部搬移小型直角标记，导出器支持本批代码的常见写法，并非通用TikZ解析器。

参考代码仅在所有优化完成后用于评估，使用之前执行并经哈希核对的参考坐标。角度残差为优化坐标层的结果，TeX实际执行精度另行检查。

```json
{
  "images": 100,
  "reasons": {
    "deferred_curves": 39,
    "already_satisfied": 22,
    "applied": 34,
    "no_candidates": 5
  },
  "applied_images": 34,
  "accepted_relations": 251,
  "max_before_error_deg": 0.4939343769080591,
  "max_after_error_deg": 2.5054927352964948e-11,
  "max_shift_rel": 0.0018039817438436352,
  "max_length_change_rel": 0.007662577156089534,
  "rejected_relations": 0,
  "reference_supported": 244,
  "reference_unsupported": 1,
  "reference_unscored": 6,
  "reference_used_for_optimization": false,
  "export_verification": {
    "exported": 34,
    "compiled": 34,
    "errors": [],
    "max_engine_error_deg": 0.0005240227318665802,
    "note": "TeX fixed-point execution has finite precision even when source coordinates round-trip as doubles."
  }
}
```

| 案例 | 状态 | 保留关系 | 剔除关系 | 最大位移/对角线 | 最大优化后角误差 |
|---|---|---:|---:|---:|---:|
| 1035_q_fig1 | deferred_curves | 0 | 0 | 0.000000% | 0° |
| 1238_q_fig1 | already_satisfied | 1 | 0 | 0.000000% | 0° |
| 1250_q_fig1 | applied | 2 | 0 | 0.047261% | 2.51e-11° |
| 1258_q_fig1 | applied | 1 | 0 | 0.044714% | 1.81e-13° |
| 1259_s_fig1 | applied | 1 | 0 | 0.034027% | 3.56e-14° |
| 1260_q_fig1 | already_satisfied | 3 | 0 | 0.000000% | 0° |
| 1260_q_fig2 | already_satisfied | 5 | 0 | 0.000000% | 0° |
| 1265_s_fig1 | deferred_curves | 0 | 0 | 0.000000% | 0° |
| 1266_s_fig1 | deferred_curves | 0 | 0 | 0.000000% | 0° |
| 1270_q_fig2 | deferred_curves | 0 | 0 | 0.000000% | 0° |
| 1467_q_fig5 | applied | 2 | 0 | 0.026314% | 0° |
| 1494_q_fig1 | already_satisfied | 1 | 0 | 0.000000% | 0° |
| 1514_s_fig4 | applied | 7 | 0 | 0.034091% | 7.64e-15° |
| 1523_s_fig2 | applied | 15 | 0 | 0.032054% | 4.47e-15° |
| 1530_q_fig3 | already_satisfied | 1 | 0 | 0.000000% | 0° |
| 1552_q_fig1 | already_satisfied | 1 | 0 | 0.000000% | 0° |
| 1575_q_fig1 | already_satisfied | 6 | 0 | 0.000000% | 0° |
| 1579_s_fig1 | applied | 1 | 0 | 0.026053% | 2.13e-12° |
| 1579_s_fig2 | applied | 1 | 0 | 0.001823% | 0° |
| 1582_q_fig1 | applied | 1 | 0 | 0.044398% | 0° |
| 1591_s_fig2 | already_satisfied | 11 | 0 | 0.000000% | 0° |
| 1615_s_fig1 | applied | 3 | 0 | 0.066830% | 1.48e-14° |
| 1618_q_fig1 | applied | 9 | 0 | 0.073137% | 3.07e-15° |
| 1625_s_fig1 | applied | 10 | 0 | 0.106001% | 2.09e-14° |
| 1627_q_fig1 | deferred_curves | 0 | 0 | 0.000000% | 0° |
| 1630_s_fig1 | applied | 5 | 0 | 0.036420% | 2.41e-14° |
| 1653_s_fig1 | applied | 6 | 0 | 0.023948% | 2.27e-12° |
| 1656_q_fig1 | applied | 1 | 0 | 0.038524% | 5.34e-16° |
| 1665_s_fig1 | deferred_curves | 0 | 0 | 0.000000% | 0° |
| 1751_q_fig1 | already_satisfied | 3 | 0 | 0.000000% | 0° |
| 1763_s_fig1 | already_satisfied | 10 | 0 | 0.000000% | 0° |
| 1775_s_fig1 | applied | 10 | 0 | 0.045785% | 1.42e-14° |
| 17_q_fig1 | applied | 7 | 0 | 0.004682% | 1.14e-13° |
| 17_q_fig2 | applied | 10 | 0 | 0.000452% | 3.9e-15° |
| 1806_q_fig1 | applied | 2 | 0 | 0.065026% | 3.45e-15° |
| 2023_s_fig1 | no_candidates | 0 | 0 | 0.000000% | 0° |
| 2040_s_fig1 | applied | 3 | 0 | 0.029955% | 8.67e-13° |
| 2062_s_fig1 | already_satisfied | 1 | 0 | 0.000000% | 0° |
| 20_q_fig1 | applied | 11 | 0 | 0.053860% | 4.86e-15° |
| 2108_q_fig1 | applied | 4 | 0 | 0.066694% | 1.42e-14° |
| 2181_q_fig1 | deferred_curves | 0 | 0 | 0.000000% | 0° |
| 295_q_fig1 | already_satisfied | 3 | 0 | 0.000000% | 0° |
| 311_q_fig4 | already_satisfied | 6 | 0 | 0.000000% | 0° |
| 32_q_fig1 | no_candidates | 0 | 0 | 0.000000% | 0° |
| 3378_s_fig1 | deferred_curves | 0 | 0 | 0.000000% | 0° |
| 3379_q_fig1 | deferred_curves | 0 | 0 | 0.000000% | 0° |
| 3438_q_fig1 | deferred_curves | 0 | 0 | 0.000000% | 0° |
| 3462_s_fig1 | applied | 6 | 0 | 0.073309% | 5.88e-14° |
| 3477_q_fig1 | no_candidates | 0 | 0 | 0.000000% | 0° |
| 3480_q_fig1 | applied | 1 | 0 | 0.021931% | 1.42e-14° |
| 34_q_fig1 | already_satisfied | 1 | 0 | 0.000000% | 0° |
| 3510_q_fig1 | applied | 2 | 0 | 0.033607% | 1.68e-12° |
| 3692_q_fig1 | no_candidates | 0 | 0 | 0.000000% | 0° |
| 38_q_fig2 | no_candidates | 0 | 0 | 0.000000% | 0° |
| 396_q_fig2 | applied | 1 | 0 | 0.046859% | 1.78e-12° |
| 403_q_fig1 | applied | 3 | 0 | 0.024167% | 1.42e-14° |
| 411_q_fig1 | already_satisfied | 1 | 0 | 0.000000% | 0° |
| 420_q_fig1 | applied | 4 | 0 | 0.098976% | 1.42e-14° |
| 46_q_fig2 | deferred_curves | 0 | 0 | 0.000000% | 0° |
| 50_q_fig1 | already_satisfied | 1 | 0 | 0.000000% | 0° |
| 5341_q_fig1 | already_satisfied | 4 | 0 | 0.000000% | 0° |
| 5804_q_fig1 | deferred_curves | 0 | 0 | 0.000000% | 0° |
| 598_q_fig1 | deferred_curves | 0 | 0 | 0.000000% | 0° |
| 6211_q_fig1 | deferred_curves | 0 | 0 | 0.000000% | 0° |
| 6215_s_fig1 | deferred_curves | 0 | 0 | 0.000000% | 0° |
| 6220_s_fig2 | deferred_curves | 0 | 0 | 0.000000% | 0° |
| 6222_s_fig1 | deferred_curves | 0 | 0 | 0.000000% | 0° |
| 6961_q_fig1 | deferred_curves | 0 | 0 | 0.000000% | 0° |
| 6961_q_fig2 | deferred_curves | 0 | 0 | 0.000000% | 0° |
| 6966_q_fig1 | deferred_curves | 0 | 0 | 0.000000% | 0° |
| 6969_q_fig2 | deferred_curves | 0 | 0 | 0.000000% | 0° |
| 6982_q_fig1 | deferred_curves | 0 | 0 | 0.000000% | 0° |
| 6983_q_fig1 | deferred_curves | 0 | 0 | 0.000000% | 0° |
| 6984_q_fig1 | deferred_curves | 0 | 0 | 0.000000% | 0° |
| 6986_q_fig1 | deferred_curves | 0 | 0 | 0.000000% | 0° |
| 6987_q_fig1 | applied | 6 | 0 | 0.180398% | 1.42e-14° |
| 6988_q_fig1 | deferred_curves | 0 | 0 | 0.000000% | 0° |
| 6988_q_fig2 | deferred_curves | 0 | 0 | 0.000000% | 0° |
| 6989_q_fig1 | deferred_curves | 0 | 0 | 0.000000% | 0° |
| 698_q_fig1 | deferred_curves | 0 | 0 | 0.000000% | 0° |
| 6991_q_fig1 | deferred_curves | 0 | 0 | 0.000000% | 0° |
| 6992_q_fig2 | deferred_curves | 0 | 0 | 0.000000% | 0° |
| 6994_q_fig2 | deferred_curves | 0 | 0 | 0.000000% | 0° |
| 6995_q_fig1 | deferred_curves | 0 | 0 | 0.000000% | 0° |
| 7016_q_fig1 | deferred_curves | 0 | 0 | 0.000000% | 0° |
| 7017_q_fig1 | applied | 2 | 0 | 0.077562% | 2.28e-15° |
| 7107_q_fig1 | already_satisfied | 10 | 0 | 0.000000% | 0° |
| 7107_q_fig2 | already_satisfied | 10 | 0 | 0.000000% | 0° |
| 766_q_fig3 | deferred_curves | 0 | 0 | 0.000000% | 0° |
| 772_q_fig2 | deferred_curves | 0 | 0 | 0.000000% | 0° |
| 793_q_fig2 | already_satisfied | 3 | 0 | 0.000000% | 0° |
| 795_q_fig2 | applied | 7 | 0 | 0.075030% | 3.26e-16° |
| 915_q_fig1 | already_satisfied | 3 | 0 | 0.000000% | 0° |
| 918_q_fig2 | applied | 6 | 0 | 0.026744% | 3.47e-12° |
| 928_q_fig4 | applied | 8 | 0 | 0.102677% | 1.83e-14° |
| 931_q_fig2 | deferred_curves | 0 | 0 | 0.000000% | 0° |
| 965_q_fig1 | already_satisfied | 6 | 0 | 0.000000% | 0° |
| 969_q_fig1 | applied | 2 | 0 | 0.046173% | 5.64e-15° |
| 971_q_fig1 | deferred_curves | 0 | 0 | 0.000000% | 0° |
| 971_q_fig2 | deferred_curves | 0 | 0 | 0.000000% | 0° |

参考点位对齐误差：修改的34图中，32图降低，2图增加。该误差采用同名点做最佳旋转/平移/等比缩放对齐后的RMS，归一化到参考点包围框对角线，不能替代整图视觉指标。

数值接近不是关系真值保证。仍有参考坐标不支持的候选被优化器接受，因此目前保持独立实验，不自动覆盖生产输出。
