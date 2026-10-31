from pathlib import Path
import json
import shutil
import re
from collections import Counter

root = Path('D:/Users/18217/Desktop/我的文件/GeoAgent')
dest = root / 'outputs/presentations/1031汇报.md'
case_dir = root / 'outputs/case_studies/1260_q_fig2'
archive = root / 'outputs/ours100/stem/1260_q_fig2'
s = json.loads((archive / 'state.json').read_text(encoding='utf-8-sig'))
case = json.loads((case_dir / 'case.json').read_text(encoding='utf-8-sig'))
logs = [json.loads(line) for line in (archive / 'llm_calls.jsonl').read_text(encoding='utf-8-sig').splitlines() if line.strip()]
assets = dest.parent / '1031汇报_images'
assets.mkdir(exist_ok=True)
image_names = ['00_input.png','s02_lines.png','s03_labels.png','s04_right_angle.png','s05_line_style.png','ges.png','compare_v1.png','compare_v2.png']
for name in image_names:
    shutil.copy2(case_dir / name, assets / name)

parts=[]
def add(t): parts.append(t.strip()+'\n')
def code(obj,language='json'):
    text = json.dumps(obj,ensure_ascii=False,indent=2) if language=='json' else obj
    add('```'+language+'\n'+text+'\n```')
def picture(name,alt): add(f'![{alt}]({(assets/name).as_posix()})')
def params(n):
    add('**实际动作与传入参数**（摘自 `action_history`，`null` 表示该记录未提供有效值）：')
    a=s['action_history'][n-1]
    code({'action':a['action'].split(':')[0],'params':a['params']})

add('''# 1031 汇报：GeoAgent 架构与 1260_q_fig2 完整处理案例

日期：2026 年 10 月 31 日

GeoAgent 输入一张几何图片，由 Supervisor 主智能体选择工具或子智能体，逐步获取几何证据，生成 TikZ 源码，再通过实际编译与视觉评审修复遗漏。本报告用 `1260_q_fig2` 的已归档运行说明各模块传递了什么信息。

文中的“实际参数”和 JSON 数据来自归档文件；中文说明是对记录的解释。归档中的 GES 对象已经过程序校验、合并和补充字段，不能当成大模型原始回复的逐字副本。参考 LaTeX 不提供给运行中的 Agent。

## 一、先理解各模块的分工

| 模块 | 做什么 | 是否调用大模型 |
|---|---|---|
| Supervisor 主智能体 | 根据当前信息选择下一步，给子智能体下达具体任务 | 是 |
| 本地 CV 工具 | 检测线段、字母、顶点、直角标记、虚实线等 | 工具本身不调用大模型 |
| Geometry Agent | 基于检测结果分析对象与关系，必要时继续调用 CV，提交结构化几何结果 | 是 |
| TikZ Agent（代码 Agent） | 根据几何结构编写或修复完整 TikZ 文档 | 是 |
| 编译、渲染、校验模块 | 将代码编译为 PDF，渲染 PNG，检查产物是否有效 | 否 |
| Critic Agent | 对照原图与渲染图，指出遗漏、错误和修复建议 | 是 |
| GES | 保存整个系统共享的结构化几何证据和处理状态 | 它是数据，不是一个 Agent |

### GES 是不是主智能体的记忆？

可以把 GES（Geometric Evidence State）理解为整个系统共享的“结构化工作笔记”，它承担一部分记忆功能。它记录的内容包括：

- 图中有哪些点、线、圆弧，它们的坐标和样式。
- 点在线上、线段相连等几何关系，以及标签绑定。
- 每项判断来自哪个工具或 Agent，有哪些证据、冲突和未决项。
- 已生成的 TikZ 版本、编译结果、Critic 报告，以及动作和预算记录。

它与对话历史共同支持后续处理。主智能体通过工具反馈和必要的状态摘要获得信息，子智能体按各自实现读取 GES 摘要或对象、关系。并非每一轮都把完整 GES 重新发送给主智能体，也不能把 GES 中的每条候选记录都当成事实。

### Geometry 的“整理几何”具体是什么意思？

CV 可能告诉系统：“从像素位置 P 到 Q 有一条线，附近有字母 A 和 F。”Geometry 则结合点坐标、标签绑定与其他线段，判断它是否可以记录为 AF、F 是否在线上、是否与其他检测结果矛盾。

它的工作不是只给 JSON 改格式，而是让大模型基于测量证据分析对象与关系，并记录仍然不能确认的部分。代码中的合并程序负责字段校验和写入 GES，不会自动证明大模型判断正确。

## 二、案例原图和整体顺序

输入：`data/test/image/1260_q_fig2.png`，尺寸 705 × 320 像素。原图包含 A～G 标签，AF 在 F 之后以虚线继续延伸至底边的 G。
''')
picture('00_input.png','1260_q_fig2 原图，注意 F 至 G 的虚线及 G 标签')
add('''本次实际执行了 8 个 Supervisor 步骤：

| 步骤 | 主智能体选择的动作 | 执行者 | 主要结果 |
|---:|---|---|---|
| 1 | `call_cv_tool:detect_lines` | 本地 CV | 检出 8 条线段 |
| 2 | `call_cv_tool:bind_point_labels` | 本地 CV | 绑定 A～F，G 未绑定 |
| 3 | `run_geometry_agent` | Geometry，内部再调用两个 CV 工具 | 合并 14 个对象、5 条关系、2 个冲突 |
| 4 | `run_tikz_agent(generate)` | TikZ 与自动编译模块 | v1 可编译，但遗漏 FG 和 G |
| 5 | `run_critic` | Critic | 发现 FG 和 G 缺失，要求修复 |
| 6 | `run_tikz_agent(repair)` | TikZ 与自动编译模块 | 补画 FG 和 G，得到 v2 |
| 7 | `run_critic` | Critic | 确认补齐，选择 v2 为最佳版本 |
| 8 | `finish` | Runner 收尾 | 返回 success，归档产物和日志 |

## 三、逐步还原信息传递

### 起点：Supervisor 收到什么？

程序构造的初始消息包含任务描述、图片路径、705 × 320 的尺寸、初始 GES 摘要，并说明参考 LaTeX 不可用。初始消息没有直接附上图片。本次 Supervisor 后续也没有调用 `inspect_image`。

### 第 1 步：检测线段
''')
params(1)
add('''`tool_name` 选择具体算法，`params` 是工具自身的参数。此处为空，使用默认设置；图片路径由 Runner 自动注入，主智能体不需要在参数中重复传入。

工具返回 8 条线段。以下是其中两条写入 GES 后的真实对象节选，保留端点、长度、方向与线型：''')
code({'objects':[ {k:s['objects'][i][k] for k in ['id','type','coords','source','status']} | {'style': {'line':s['objects'][i]['style'].get('line')}} for i in ['seg_01','seg_06']]})
add('''字段说明：`a_px`、`b_px` 是图片像素坐标中的线段端点，原点在左上，x 向右、y 向下；`length_px` 是长度，`angle_deg` 是检测方向；`style.line` 表示线型；`source` 记录来源；`candidate` 表示候选结果。

完整结果先经 `ingest_cv_result` 写入 GES，再压缩为适合模型阅读的工具反馈。此时获得的是“哪里有线”，还没有完整确定每条线与 A～G 的对应关系。''')
picture('s02_lines.png','第 1 步：线段检测叠加图')
add('### 第 2 步：将字母绑定到顶点')
params(2)
add('''这个工具内部使用标签识别和顶点候选，尝试建立字母与几何点的对应关系。根据返回结果，Supervisor 在后续指令中列出了这些点：

| 字母 | 像素坐标 |
|---|---|
| A | (68.5, 65) |
| B | (68.5, 254) |
| C | (635.5, 254) |
| D | (352, 65) |
| E | (162.9, 254) |
| F | (238.3, 149.6) |
| G | 检测到了字母，但没有匹配到对应顶点 |

检测到 G 的字形不等于确定了几何点 G。字母 G 大约位于 (446,273)，它下方标签的位置与应在底边上的顶点位置不是同一件事。''')
picture('s03_labels.png','第 2 步：标签绑定叠加图，G 字母被识别但未绑定顶点')
add('### 第 3 步：委派 Geometry Agent 分析几何')
params(3)
add('''主智能体的指令明确传入了 A～F 坐标、检测出的各条线段和待核查问题。程序还自动提供 GES 摘要。`use_image` 与 `roi` 在记录中均为 `null`，本次没有给 Geometry 的大模型附原图。

Geometry 首次调用大模型后，继续调用了两个本地工具。下面是 `cv_runs` 中对应的实际工具参数：''')
code([{'tool':x['tool'],'params':x['params'],'ok':x['ok'],'count':x['count']} for x in s['cv_runs'][2:]])
add('''`roi=[0,0,1,1]` 表示整张图片。直角检测返回 0，表示没有检测到经过验证的方块直角标记，不能解释为“图中没有垂直关系”。`segments` 传入三组待检查线段，覆盖 AB、BE 附近及较长底边。`count=3` 表示记录了三段检查，不能解释为三个分类都已可靠完成，底边的线型仍有争议。''')
picture('s04_right_angle.png','Geometry 内部调用：直角标记检查，未检出方块标记')
picture('s05_line_style.png','Geometry 内部调用：虚实线检查')
add('''Geometry 再次调用大模型，读取补充工具结果，并提交几何 JSON。`submit_geometry` 的接口参数 `json` 是一个字符串，字符串内部才是包含 `objects`、`relations`、`conflicts`、`unresolved`、`summary` 等字段的 JSON 对象。

程序将提交内容校验、合并进 GES。本次合并计数为 14 个对象、5 条关系、2 个冲突。以下是落盘后的真实节选，保留完整对象字段；顶层使用的是 GES 字段名 `unresolved_issues`，不是原始提交接口的字段名：''')
geometry_excerpt={
 'objects':[s['objects'][i] for i in ['point_F','seg_AF']],
 'relations':[s['relations']['rel_008'],s['relations']['rel_011']],
 'conflicts':s['conflicts'],
 'unresolved_issues':[x for x in s['unresolved_issues'] if x['source']=='geometry_agent']
}
code(geometry_excerpt)
add('''几何 JSON 字段说明：

| 字段 | 含义及本例中的读法 |
|---|---|
| `objects` | 几何对象集合，包含点、线段等 |
| `id` | 对象标识，例如 `point_F`、`seg_AF`，供关系和问题引用 |
| `type` / `label` | 对象类型与标签，例如点 F、线段 AF |
| `coords.px` | 点的像素坐标 |
| `coords.a_px` / `coords.b_px` | 线段两端的像素坐标 |
| `normalized` | 可用来保存归一化坐标，本例这两个对象为空 |
| `style.line` / `style.note` | 实线或虚线，以及对检测跨度等细节的说明 |
| `source` | 来源，此处为 Geometry Agent |
| `status` | `confirmed` 为记录中标记确认，`candidate` 为候选，`rejected` 为否定的判断 |
| `confidence` / `confidence_kind` | 置信信息。本例未给数值，并注明不是经过校准的概率 |
| `notes` / `attributes` | 补充备注和扩展属性，本例为空 |
| `relations` | 对象之间的关系集合 |
| `subject` / `relation` / `object` | 关系的主语、类型与宾语。例如 F、`on_segment`、AF，即 F 在 AF 上 |
| `evidence` | 关系的判断依据 |
| `conflicts.claims` | 对同一问题的不同说法和来源，保留争议而非抹去历史 |
| `conflicts.status` / `resolution` | 冲突是否解决及解决说明。本例仍是 `unresolved` / `null` |
| `unresolved_issues` | 尚未确认的问题，本例包括 G 未绑定、直角标记和线型问题 |

两个容易误解的细节：

1. `seg_AF` 检测跨度比 F 多伸出约 12 像素，所以线段端点与 F 点坐标不完全相同，Geometry 将这个差异记录在 `style.note`。
2. `relation="parallel"` 但 `status="rejected"` 表示否定 AE 与 FE 平行，读取关系时必须同时查看状态。

Geometry 关于“F 不在 AE 上”的判断依据是 AE 斜率约 2.0、AF 斜率约 0.5。它输出了不同线段和关系，但相关历史冲突条目没有自动清除。这说明 GES 不是保证全部一致的标准答案库。

完整的 Geometry 来源对象、关系和未决项见同目录的 [几何 JSON](./1260_q_fig2_geometry_stored.json)。''')
picture('ges.png','GES 对象和关系的可视化叠加图')
add('### 第 4 步：TikZ Agent 生成首版代码')
params(4)
add('''显式参数中，`mode="generate"` 表示首次生成；`instruction` 指定点坐标、实线、虚线和标签位置；本次 `use_image=null`，大模型不直接看原图。

程序自动补充给 TikZ 大模型的上下文包括：GES 对象和关系、图片尺寸，以及本地 CV 测得的线宽、标签高度和建议坐标尺度。本例最终采用 0.012719 cm/px、1.0pt 线宽和 10/12 字号。坐标从图片的 y 向下转换成 TikZ 的 y 向上。

TikZ 调用大模型后通过 `submit_tikz` 提交 `tex`（完整文档源码）和 `notes`（绘制决策说明）。Runner 自动保存版本，调用 Tectonic 编译，渲染 PNG，并检查编译及产物。返回的关键状态是：''')
code({'ok':True,'version':1,'mode':'generate','compile_ok':True,'validation_passed':True,'best_version':1})
add('''上面仅摘出返回状态的关键字段，省略产物路径等字段。编译通过只说明代码和产物可用，尚未证明图形完整。

首版为什么漏画？生成指令只要求 A～F，并且明确写了 `A-F (A to F only)`，没有要求补 G 或 FG；Geometry 也没有建立 G 点。这次 TikZ 主要按已有结构和指令画图，所以得到的 v1 没有 FG 和 G。''')
add('### 第 5 步：Critic 检查原图与 v1')
params(5)
add('''`focus` 表示检查重点：线段延伸范围、虚线和标签位置。程序自动获取原图、最新成功渲染、GES 摘要和对象核对清单，构造内容等尺度的对比图交给 Critic 大模型。''')
picture('compare_v1.png','首轮视觉评审：左侧原图，右侧 v1，缺少 FG 虚线和 G 标签')
r1=s['critic_reports'][0]
add('Critic 报告的实际关键字段如下（`checks` 只节选 AF 一项，其余所列字段保持实际值）：')
code({k:r1[k] for k in ['version','assessment_score','verdict','issues']} | {'checks':[x for x in r1['checks'] if x['object_id']=='seg_AF']} | {k:r1[k] for k in ['checklist_score','actionable_counts','flaky_count','must_repair','labels']})
add('''评审 JSON 字段说明：

| 字段 | 含义 |
|---|---|
| `version` | 当前评审的代码版本 |
| `assessment_score` | Critic 的整图启发式相似度，本轮 0.85，不是准确率或外部评测指标 |
| `issues` | 可定位、可修复的问题列表 |
| `type` / `severity` | 问题类型及严重程度，本轮有 high 与 medium 的遗漏 |
| `object_ids` | 涉及的 GES 对象。FG 问题引用已有的 `seg_AF`，G 标签问题没有可用对象 id |
| `bbox` | 归一化的问题区域定位框，不是精确的顶点坐标 |
| `description` / `suggestion` | 发现的问题和建议如何修复 |
| `source` / `flaky` | 问题来源及是否属于与上一版方向相反的矛盾反馈 |
| `checks` | 按对象逐项检查的结果，`wrong` 表示该对象存在偏差 |
| `checklist_score` | 根据清单状态确定性聚合的分数，本轮 0.979 |
| `actionable_counts` | 排除矛盾反馈和信息项后的有效问题计数 |
| `must_repair` | 是否需要修复。本轮 high=1、medium=1，因此为 true |
| `labels` | 已出现、缺失及多出的标签，本轮缺 G |

即使清单分接近 1，也不能忽略一条关键线和一个标签的遗漏。修复门控依据有效问题严重度，而不是只看整图分数。报告保存到 GES，并将关键问题返回主智能体。

### 第 6 步：Supervisor 指定修复，TikZ 生成 v2

Supervisor 根据 A 与 F 的坐标，将 AF 延长到 y=254 的底边。其推导约为：

```text
m = (149.6 - 65) / (238.3 - 68.5) ≈ 0.498
x_G = 68.5 + (254 - 65) / m ≈ 448
G ≈ (448, 254) px
```

这一步不是调用新的坐标测量工具，而是主智能体在修复指令中给出几何外推位置。
''')
params(6)
add('''`mode="repair"` 切换到修复模式。程序自动给 TikZ 大模型附加旧版完整源码、编译错误和警告、上一版 Critic 问题，同时继续提供对象、关系和风格参数。大模型提交完整修订文档，而不是只提交一小段补丁。

v2 实际源码新增了以下关键内容：''')
code('''\\coordinate (G) at (1.221,-1.202);
\\draw[dash pattern=on 3pt off 2pt] (F) -- (G);
\\node[below] at (G) {$G$};''','latex')
add('''这里是转换后的 TikZ 厘米坐标，不是原始像素。v2 沿用以墨迹框中心 (352,159.5) 为原点的坐标变换和原线宽字号。

程序再次自动编译、渲染和校验，结果：''')
code({'ok':True,'version':2,'mode':'repair','compile_ok':True,'validation_passed':True,'best_version':1})
add('注意这时最佳版本仍为 1，因为 v2 尚未完成视觉评审。新版本编译成功，并不意味着它立即替换已评审的最佳版本。')
add('### 第 7 步：Critic 再次检查 v2')
params(7)
add('程序再次给 Critic 大模型提供原图与新渲染图的对比，重点核查 FG 延长虚线和 G 标签。')
picture('compare_v2.png','第二轮视觉评审：左侧原图，右侧修复后的 v2')
r2=s['critic_reports'][1]
code({k:r2[k] for k in ['version','assessment_score','verdict','issues','checklist_score','actionable_counts','must_repair','labels']})
add('''本轮未发现需要修复的问题，整图内部评分为 0.93，清单分为 1.0。Runner 关联报告并重新选择最佳版本，此时 `best_version` 更新为 2。

### 第 8 步：finish 收尾并归档
''')
params(8)
add('''`summary` 说明完成情况，`status` 表示结束状态，`unresolved` 明确保留未独立复核的部分。Runner 处理收尾门控、记录结论，运行结束后归档最佳 tex、PDF、PNG、状态和调用日志。

这里的 `success` 表示产出了本次接受的结果，并不表示所有历史冲突和未决项都已清零。本例最终仍有 2 条冲突和 6 条未决项。G 点是在修复指令和源码中补入的，也不能据此假定 GES 已通过 Geometry 的结构化提交补齐了对应对象。

## 四、到底调用了几次大模型？谁真正看了图片？

以下统计直接来自 `llm_calls.jsonl`，一次主智能体动作内部可能包含多次大模型调用：
''')
counts=Counter(x['tag'] for x in logs)
add('| 调用角色 | 次数 | 是否附图 |\n|---|---:|---|\n'+ '\n'.join(f"| `{tag}` | {counts[tag]} | {'是' if any(x['has_images'] for x in logs if x['tag']==tag) else '否'} |" for tag in counts))
add(f'''本次共有 **{len(logs)} 次大模型调用**。日志中均使用 `claude-haiku-5-5`，角色通过不同提示词、输入上下文和可用工具区分，不代表四套独立训练的模型。

只有两轮 Critic 调用实际附图。Supervisor、Geometry、TikZ 通过坐标、文本证据、几何 JSON、代码与评审反馈协作。图片仍然供本地 CV 和风格测量程序使用，所以“这些大模型请求没有附图”不等于“系统没用图片”。

记录中的 4 次显式 CV 调用分别是线段检测、标签绑定、直角标记检测、线型检查。TikZ 前另有本地风格测量等自动处理，不应把这 4 条工具记录理解为全部底层图像算法调用次数。

## 五、这个案例说明了什么？

- CV 给出测量证据，Geometry 负责基于证据分析、组织对象和关系，并暴露无法确定的部分。
- TikZ Agent 使用结构与具体指令生成代码。本次 G 未绑定，首版指令也没有 FG，因此首版遗漏了它们。
- 编译校验解决的是代码能否产生有效产物。Critic 对照原图补充检查视觉内容，发现漏画后把具体问题交回主智能体。
- 主智能体把问题转为可执行的修复指令，TikZ 再生成，Critic 再检查。GES 和对话记录支撑整个过程的信息传递，但仍需区分候选判断、已拒绝关系和历史未决项。

## 六、项目中的核对入口

| 资料 | 项目相对路径 | 用途 |
|---|---|---|
| 归档状态 | `outputs/ours100/stem/1260_q_fig2/state.json` | 动作参数、CV 调用、对象、关系、冲突、两轮评审 |
| 大模型调用日志 | `outputs/ours100/stem/1260_q_fig2/llm_calls.jsonl` | 调用角色、次数、模型、是否附图 |
| 案例整理 | `outputs/case_studies/1260_q_fig2/case.json` | 案例阶段、版本、指标、统计 |
| 修复源码 | `outputs/case_studies/1260_q_fig2/tikz/v2/v2.tex` | G 坐标、FG 虚线和标签的实际代码 |
| 主智能体初始消息 | `geoagent/agents/supervisor.py` | 起始任务、尺寸和 GES 摘要的构造 |
| 调度与自动处理 | `geoagent/orchestration/runner.py` | 动作分发、工具反馈、编译、渲染、评审及收尾 |
| Geometry 实现 | `geoagent/agents/geometry_agent.py` | 大模型调用、内部 CV 调用、提交与合并 |
| TikZ 实现 | `geoagent/agents/tikz_agent.py` | 生成/修复上下文、风格测量、代码提交 |

本报告使用的图片已复制到同目录 `1031汇报_images`，Markdown 图片标签使用本机绝对路径。若将文档与图片一起移动到其他电脑，需要将图片路径调整为新位置。
''')

geometry_full={
 'objects':[x for x in s['objects'].values() if x['source']=='geometry_agent'],
 'relations':[x for x in s['relations'].values() if x['source']=='geometry_agent'],
 'conflicts':s['conflicts'],
 'unresolved_issues':[x for x in s['unresolved_issues'] if x['source']=='geometry_agent']
}
(dest.parent/'1260_q_fig2_geometry_stored.json').write_text(json.dumps(geometry_full,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
dest.write_text('\n'.join(parts),encoding='utf-8')

# Verify every embedded image and every JSON code block in the final document.
text=dest.read_text(encoding='utf-8')
for target in re.findall(r'!\[[^\]]*\]\(([^)]+)\)',text):
    assert Path(target).is_file(), target
blocks=re.findall(r'```json\n(.*?)\n```',text,re.S)
for block in blocks: json.loads(block)
assert len(s['action_history'])==8 and len(logs)==14
print(json.dumps({'document':str(dest),'characters':len(text),'json_blocks':len(blocks),'images':len(image_names)},ensure_ascii=False))
