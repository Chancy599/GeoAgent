# 坐标关系候选发现实验

输入为 ours100 已生成 TikZ 的点坐标与实线/虚线段连接。LLM 不接收图片、GES 关系或参考代码。所有推理结束后才读取并执行参考代码，评估其实际坐标关系。

模型：claude-haiku-5-5。候选门限：角度误差≤2°，等长相对差≤3%，共线距离≤图形跨度0.5%。

参考判定门限：角度误差≤0.1°，等长相对差≤0.1%，共线距离≤跨度0.05%。parallel 排除同一直线上的线段。

参考坐标通过实际执行 TeX 提取。初始严格共线门限0.001%会将 PGF 交点/插值的微小数值误差算作不共线，因此主表采用0.05%，每案例 evaluation.json 另保留初始严格门限结果 strict_reference_scores。本次只重新评估，没有更改候选或重跑LLM。

注意：数值基线、LLM 采用同一线段/点组合空间。召回率仅覆盖该空间中可由参考坐标评估的关系，不代表题目全部语义关系。参考直角标注单独记录，不替代实际坐标计算。

| 案例 | LLM正确/候选 | 参考关系总数 | LLM精确率 | LLM召回率 | 数值过滤后正确/候选 | 纯数值正确/候选 |
|---|---:|---:|---:|---:|---:|---:|
| 1260_q_fig2 | 10/11 | 10 | 90.9% | 100.0% | 10/11 | 10/11 |
| 1630_s_fig1 | 15/20 | 16 | 75.0% | 93.8% | 15/20 | 16/21 |
| 2108_q_fig1 | 6/6 | 6 | 100.0% | 100.0% | 6/6 | 6/6 |
| 1494_q_fig1 | 1/2 | 1 | 50.0% | 100.0% | 1/2 | 1/2 |
| 1618_q_fig1 | 22/22 | 24 | 100.0% | 91.7% | 22/22 | 24/24 |
| 1625_s_fig1 | 17/18 | 26 | 94.4% | 65.4% | 17/18 | 26/27 |

汇总：

```json
{
  "llm": {
    "predicted": 79,
    "true": 83,
    "tp": 71,
    "fp": 8,
    "fn": 12,
    "precision": 0.8987341772151899,
    "recall": 0.8554216867469879
  },
  "llm_numeric_filtered": {
    "predicted": 79,
    "true": 83,
    "tp": 71,
    "fp": 8,
    "fn": 12,
    "precision": 0.8987341772151899,
    "recall": 0.8554216867469879
  },
  "numeric_baseline": {
    "predicted": 91,
    "true": 83,
    "tp": 83,
    "fp": 8,
    "fn": 0,
    "precision": 0.9120879120879121,
    "recall": 1.0
  }
}
```

## 按关系类型汇总

| 类型 | LLM候选 | 参考坐标支持 | 参考关系总数 | 漏检 |
|---|---:|---:|---:|---:|
| parallel | 14 | 14 | 14 | 0 |
| perpendicular | 28 | 22 | 22 | 0 |
| equal_length | 7 | 5 | 6 | 1 |
| collinear | 30 | 30 | 41 | 11 |

## 结果解释

在本次6个定向选择案例中，纯数值枚举的覆盖率高于LLM，LLM尚未表现出坐标关系枚举的优势。LLM候选均通过同一重建坐标宽松门限，因此追加该数值过滤没有减少误报。后续可测试让LLM解释与筛选工具给出的候选，而不依靠其独立枚举。

这是参考坐标数值支持率，不是人工标注的题意准确率。例如1630_s_fig1的参考代码使用tkzMarkRightAngle(A,Q,H)，但执行后的AE与HQ夹角仍偏离90°约1.49°。该声明保存在evaluation/reference_points.json中，未用其覆盖数值结果。


## 1260_q_fig2

| 候选关系 | 重建坐标误差 | 参考坐标误差 | 参考支持 |
|---|---|---|---|
| parallel AD CE | {"angle_deg": 0.0, "relative_offset": 0.31622776601683794} | {"angle_deg": 0.0, "relative_offset": 0.3162276993448459} | 是 |
| parallel AD BE | {"angle_deg": 0.0, "relative_offset": 0.31622776601683794} | {"angle_deg": 0.0, "relative_offset": 0.3162276993448459} | 是 |
| perpendicular AB AD | {"angle_deg": 0.0} | {"angle_deg": 0.0} | 是 |
| perpendicular AB CE | {"angle_deg": 0.0} | {"angle_deg": 0.0} | 是 |
| perpendicular AB BE | {"angle_deg": 0.0} | {"angle_deg": 0.0} | 是 |
| equal_length AB AF | {"relative_length": 0.0037988305926126447} | {"relative_length": 0.006191854797830556} | 否 |
| collinear B C E | {"relative_distance": 0.0} | {"relative_distance": 0.0} | 是 |
| collinear B E G | {"relative_distance": 0.0} | {"relative_distance": 0.0} | 是 |
| collinear B C G | {"relative_distance": 0.0} | {"relative_distance": 0.0} | 是 |
| collinear C E G | {"relative_distance": 0.0} | {"relative_distance": 0.0} | 是 |
| collinear A F G | {"relative_distance": 2.956496301112727e-05} | {"relative_distance": 3.552431429888914e-05} | 是 |

漏检关系：[]

## 1630_s_fig1

| 候选关系 | 重建坐标误差 | 参考坐标误差 | 参考支持 |
|---|---|---|---|
| parallel AD BC | {"angle_deg": 0.0, "relative_offset": 0.29847879011577155} | {"angle_deg": 0.0, "relative_offset": 0.2981247814959624} | 是 |
| parallel BC FG | {"angle_deg": 0.0, "relative_offset": 0.11976076815779205} | {"angle_deg": 0.004408766000808681, "relative_offset": 0.11927088530196778} | 是 |
| parallel AD FG | {"angle_deg": 0.0, "relative_offset": 0.1787180219579795} | {"angle_deg": 0.00440876600080868, "relative_offset": 0.1788538961939946} | 是 |
| parallel CD GH | {"angle_deg": 0.25105993569893825, "relative_offset": 0.2855720828389404} | {"angle_deg": 0.006362463089487508, "relative_offset": 0.28612936083806384} | 是 |
| parallel DP GH | {"angle_deg": 0.29256397699752557, "relative_offset": 0.28557829967220705} | {"angle_deg": 0.07161172503843748, "relative_offset": 0.28611899246627753} | 是 |
| perpendicular AB CD | {"angle_deg": 1.7658850665509647} | {"angle_deg": 1.7898977229381643} | 否 |
| perpendicular AB DP | {"angle_deg": 1.7243810252523701} | {"angle_deg": 1.8551469848871136} | 否 |
| perpendicular AP CD | {"angle_deg": 1.9028907480426085} | {"angle_deg": 1.7896072761946442} | 否 |
| perpendicular AP DP | {"angle_deg": 1.861386706744014} | {"angle_deg": 1.8548565381435935} | 否 |
| perpendicular AE HQ | {"angle_deg": 1.3900709933785436} | {"angle_deg": 1.4942311081417188} | 否 |
| collinear B C H | {"relative_distance": 0.0} | {"relative_distance": 0.0} | 是 |
| collinear A B F | {"relative_distance": 4.148676685803012e-05} | {"relative_distance": 1.145239865191751e-07} | 是 |
| collinear A B P | {"relative_distance": 0.0003792721713694103} | {"relative_distance": 8.068821232920799e-07} | 是 |
| collinear A F P | {"relative_distance": 0.00032901784649582523} | {"relative_distance": 7.121547185051812e-07} | 是 |
| collinear B F P | {"relative_distance": 0.00011065020193286597} | {"relative_distance": 2.0828586793498086e-07} | 是 |
| collinear C D E | {"relative_distance": 3.701921228352794e-05} | {"relative_distance": 0.00013782060833801658} | 是 |
| collinear C E P | {"relative_distance": 8.081966330607571e-06} | {"relative_distance": 6.71138469644292e-05} | 是 |
| collinear C D P | {"relative_distance": 9.022609903491155e-05} | {"relative_distance": 0.00014146483905959071} | 是 |
| collinear D E P | {"relative_distance": 8.618537802501147e-05} | {"relative_distance": 0.00017501617502896008} | 是 |
| collinear A E Q | {"relative_distance": 0.0002081704116234727} | {"relative_distance": 7.833321219259693e-05} | 是 |

漏检关系：[["equal_length", "AD", "FG"]]

## 2108_q_fig1

| 候选关系 | 重建坐标误差 | 参考坐标误差 | 参考支持 |
|---|---|---|---|
| collinear A B D | {"relative_distance": 9.820002472874431e-05} | {"relative_distance": 9.899981435610628e-07} | 是 |
| collinear C D E | {"relative_distance": 0.00014798305789605128} | {"relative_distance": 6.029744634116661e-05} | 是 |
| perpendicular BE DE | {"angle_deg": 0.17982951090070287} | {"angle_deg": 0.01300511012864547} | 是 |
| perpendicular BE CD | {"angle_deg": 0.13456534668851816} | {"angle_deg": 0.00542336665456844} | 是 |
| perpendicular AC AD | {"angle_deg": 0.25180295317260004} | {"angle_deg": 0.00028992522044291036} | 是 |
| perpendicular AC BD | {"angle_deg": 0.22074015076204034} | {"angle_deg": 2.26144901915859e-05} | 是 |

漏检关系：[]

## 1494_q_fig1

| 候选关系 | 重建坐标误差 | 参考坐标误差 | 参考支持 |
|---|---|---|---|
| perpendicular BC CD | {"angle_deg": 0.0} | {"angle_deg": 0.0} | 是 |
| perpendicular AB AD | {"angle_deg": 0.8735669471516871} | {"angle_deg": 0.736158061174379} | 否 |

漏检关系：[]

## 1618_q_fig1

| 候选关系 | 重建坐标误差 | 参考坐标误差 | 参考支持 |
|---|---|---|---|
| parallel AD BC | {"angle_deg": 0.0, "relative_offset": 0.599973913858688} | {"angle_deg": 0.0, "relative_offset": 0.6000000224891039} | 是 |
| parallel AB CD | {"angle_deg": 0.0, "relative_offset": 0.7985755273475479} | {"angle_deg": 0.0, "relative_offset": 0.7999999831331714} | 是 |
| parallel AE MN | {"angle_deg": 0.021390214348317983, "relative_offset": 0.17966618120186847} | {"angle_deg": 0.0, "relative_offset": 0.17888541138015904} | 是 |
| perpendicular AB AD | {"angle_deg": 0.0} | {"angle_deg": 0.0} | 是 |
| perpendicular AB BC | {"angle_deg": 0.0} | {"angle_deg": 0.0} | 是 |
| perpendicular AD CD | {"angle_deg": 0.0} | {"angle_deg": 0.0} | 是 |
| perpendicular BC CD | {"angle_deg": 0.0} | {"angle_deg": 0.0} | 是 |
| perpendicular AE BF | {"angle_deg": 0.13214713612288165} | {"angle_deg": 1.3422193489986967e-06} | 是 |
| perpendicular BF MN | {"angle_deg": 0.1535373504712112} | {"angle_deg": 1.3422193489986967e-06} | 是 |
| equal_length AD BC | {"relative_length": 0.0} | {"relative_length": 0.0} | 是 |
| equal_length AB CD | {"relative_length": 0.0} | {"relative_length": 0.0} | 是 |
| equal_length AE MN | {"relative_length": 0.00022472106516498055} | {"relative_length": 0.0} | 是 |
| collinear A D M | {"relative_distance": 0.0} | {"relative_distance": 0.0} | 是 |
| collinear B C E | {"relative_distance": 0.0} | {"relative_distance": 0.0} | 是 |
| collinear B C N | {"relative_distance": 2.329091280507073e-05} | {"relative_distance": 0.0} | 是 |
| collinear B E N | {"relative_distance": 1.3942393802898598e-05} | {"relative_distance": 0.0} | 是 |
| collinear C E N | {"relative_distance": 2.3290912805070725e-05} | {"relative_distance": 0.0} | 是 |
| collinear M N O | {"relative_distance": 0.00014430754015703551} | {"relative_distance": 0.0001262626920406679} | 是 |
| collinear B F O | {"relative_distance": 0.0005314126656101998} | {"relative_distance": 2.294343063404221e-06} | 是 |
| collinear B F P | {"relative_distance": 0.0003091124810672172} | {"relative_distance": 1.4583226651456742e-06} | 是 |
| collinear F O P | {"relative_distance": 0.00031082125142702267} | {"relative_distance": 1.252856364369024e-06} | 是 |
| collinear B O P | {"relative_distance": 8.843948165898162e-06} | {"relative_distance": 8.17301742509359e-08} | 是 |

漏检关系：[["collinear", "A", "E", "P"], ["collinear", "C", "D", "F"]]

## 1625_s_fig1

| 候选关系 | 重建坐标误差 | 参考坐标误差 | 参考支持 |
|---|---|---|---|
| perpendicular AC BC | {"angle_deg": 0.0} | {"angle_deg": 0.0} | 是 |
| perpendicular AC FK | {"angle_deg": 0.19488285223862079} | {"angle_deg": 0.019003254528399793} | 是 |
| parallel BC FK | {"angle_deg": 0.19488285223861593, "relative_offset": 0.6294446682070157} | {"angle_deg": 0.01900325452839718, "relative_offset": 0.6287950205914996} | 是 |
| equal_length BC FK | {"relative_length": 0.023250163869258385} | {"relative_length": 0.023596362375003566} | 否 |
| parallel DG EF | {"angle_deg": 0.16364567495091914, "relative_offset": 0.19367501883255978} | {"angle_deg": 0.009192270358586397, "relative_offset": 0.1945981369345444} | 是 |
| equal_length DG EF | {"relative_length": 0.006973089571478674} | {"relative_length": 7.990771526378077e-08} | 是 |
| perpendicular DE DG | {"angle_deg": 0.09454740512681781} | {"angle_deg": 0.01159560558080841} | 是 |
| perpendicular DE EF | {"angle_deg": 0.25819308007773145} | {"angle_deg": 0.0207878759394049} | 是 |
| perpendicular DG FG | {"angle_deg": 0.5731742330329013} | {"angle_deg": 0.01159798302747106} | 是 |
| perpendicular EF FG | {"angle_deg": 0.7368199079838149} | {"angle_deg": 0.020790253386067548} | 是 |
| parallel DE FG | {"angle_deg": 0.47862682790608696, "relative_offset": 0.23311704371010855} | {"angle_deg": 2.3774466580440978e-06, "relative_offset": 0.23362863999931474} | 是 |
| equal_length DE FG | {"relative_length": 0.003474574651651814} | {"relative_length": 0.00019257679832785388} | 是 |
| parallel AB FG | {"angle_deg": 0.433658109963586, "relative_offset": 0.23361333519406527} | {"angle_deg": 1.905047528404588e-05, "relative_offset": 0.23369510173387048} | 是 |
| perpendicular AB DG | {"angle_deg": 0.13951612306931338} | {"angle_deg": 0.01157893255219733} | 是 |
| perpendicular AB EF | {"angle_deg": 0.30316179802024124} | {"angle_deg": 0.020771202910779607} | 是 |
| collinear A C K | {"relative_distance": 0.0} | {"relative_distance": 0.0} | 是 |
| collinear A B D | {"relative_distance": 0.0006491942295228501} | {"relative_distance": 6.640508198704805e-05} | 是 |
| collinear A B E | {"relative_distance": 0.000497187775780883} | {"relative_distance": 6.646170989930839e-05} | 是 |

漏检关系：[["collinear", "A", "B", "Q"], ["collinear", "A", "D", "E"], ["collinear", "A", "D", "Q"], ["collinear", "A", "E", "Q"], ["collinear", "B", "D", "E"], ["collinear", "B", "D", "Q"], ["collinear", "B", "E", "Q"], ["collinear", "D", "E", "Q"], ["collinear", "F", "K", "Q"]]
