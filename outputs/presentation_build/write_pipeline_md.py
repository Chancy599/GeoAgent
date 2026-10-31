from pathlib import Path
from collections import Counter
import json,re

root=Path('D:/Users/18217/Desktop/我的文件/GeoAgent')
run=root/'outputs/ours100/stem/1260_q_fig2'
s=json.loads((run/'state.json').read_text(encoding='utf-8'))
r=json.loads((run/'result.json').read_text(encoding='utf-8'))
calls=[json.loads(x) for x in (run/'llm_calls.jsonl').read_text(encoding='utf-8').splitlines() if x.strip()]
actions=s['action_history']
parts=[]
def add(t):parts.append(t.strip()+'\n')
def js(v):add('```json\n'+json.dumps(v,ensure_ascii=False,indent=2)+'\n```')
def params(i):
    add('**归档中的调用参数**（`action_history.params` 原值，记录器补齐的 `null` 也保留）：')
    js(actions[i-1]['params'])
def recorded(i):
    add('**归档中的执行结果摘要**（这是动作记录，不能当成完整的原始 tool 回复）：')
    js({k:actions[i-1][k] for k in ['step','action','status','result_summary']})
def image(name,caption):add(f'![{caption}](../outputs/case_studies/1260_q_fig2/{name})')

add('''# GeoAgent：1260_q_fig2 的完整处理流程

本文按这次实际运行的 **8 个主 Agent 步骤**，解释谁调用谁、传了哪些信息、返回什么，以及 GES 如何参与。代码与记录以项目当前文件为准。

最终结果：v1 漏画了 **FG 虚线和 G 标签**。Critic 对照原图发现遗漏，Supervisor 推算 G 的位置并要求 TikZ Agent 修复，v2 再次评审后成为最佳版本。

## 0. 先说明：哪些 JSON 是原始记录

- **调用参数**来自 `state.json.action_history[*].params`。记录器会补齐一些 `null` 字段，因此它是归档参数，不保证与模型发出的原始参数字符串逐字一致。
- **几何 JSON**从 GES 中提取 `source=geometry_agent` 的对象、关系及相应冲突、未决项。它是合并、校验后的实际状态，不是 `submit_geometry` 的原始请求字符串。
- **Critic 报告**来自 `state.json.critic_reports`，是系统处理后存储的报告。
- **执行结果摘要**来自 `action_history.result_summary`。没有完整 tool 回复时，本文不会编造一个“原始返回 JSON”。
- `llm_calls.jsonl` 保存模型调用元数据、用量、是否附图等，并未保存完整请求和回复正文。
- 归档里部分路径仍指向运行时的 `outputs/batch_v2/...`。这些是历史记录；当前可读产物以本文给出的归档链接和案例图片为准。

## 1. 谁负责什么，信息怎么流动

| 模块 | 本次负责的事 |
|---|---|
| Supervisor（主 Agent） | 根据工具反馈选择下一步，委派子 Agent，决定修复和结束 |
| 本地 CV 工具 | 从原图测量线段、检测字母和绑定顶点，补充直角、线型证据 |
| Geometry Agent | 使用大模型整理对象和关系，必要时继续调用 CV，提交几何 JSON |
| TikZ Agent | 使用大模型生成或修改完整 LaTeX/TikZ 源码 |
| 编译、渲染、校验程序 | 本地执行源码，得到 PDF、PNG，并检查编译和产物是否有效 |
| Critic Agent | 使用大模型对照原图与渲染图，指出缺失或画错的位置 |
| GES | 保存共享的结构化状态：对象、关系、证据、未决项、版本和评审结果 |

下图中的步骤顺序不表示子 Agent 直接调用彼此。实际由 Supervisor 每步调度，执行结果回到 Supervisor。

```mermaid
flowchart TD
    S[Supervisor 主 Agent] -->|步骤1–2：找线、绑标签| CV[本地 CV 工具]
    CV -->|坐标、标签绑定、G 未绑定| S
    S -->|步骤3：整理指令、点线坐标、GES| G[Geometry Agent]
    G -->|补查直角、线型| CV
    G -->|几何 JSON 合并结果| S
    S -->|步骤4：绘图指令、GES、风格参数| T[TikZ Agent]
    T -->|完整 tex| C[本地编译、渲染、校验]
    C -->|版本、PNG、编译结果| S
    S -->|步骤5、7：评审 focus| R[Critic Agent]
    I[原图与最新渲染图、GES清单] --> R
    R -->|具体问题、must_repair、评分| S
    S -->|步骤6：修复指令、旧代码、问题| T
    S -->|步骤8：summary、status、unresolved| F[finish 与结果归档]
    CV -.-> E[GES 共享结构化状态]
    G -.-> E
    C -.-> E
    R -.-> E
```

### GES 会传给主 Agent 吗？

会，但当前代码的方式是：

1. 初始化时，`initial_messages()` 将 `state.summary()` 放进 **user 消息**，与任务、图片路径、尺寸一起输入主 Agent。
2. 正常执行每步后，程序更新 GES，再把该动作的结果追加为 **tool 消息**。主 Agent 通过累积的工具反馈获得新信息。
3. 主 Agent 没有发出工具调用时，`step_nudge()` 追加提醒，并再次带上最新 GES 摘要。

**当前实现没有在每一轮正常调用前重新插入完整的最新 GES 摘要。** GES 是程序内的结构化状态，模型能使用的是被放进消息中的摘要和反馈，不能自动读取所有状态。

Geometry Agent 会获得 GES 摘要。TikZ Agent 会获得从 GES 摘取的对象和关系，修复时再附旧源码、编译信息和 Critic 问题。Critic 获得 GES 摘要及对象核对清单。

## 2. 初始任务与输入图

系统初始化 Runner、GES、模型客户端、图片上下文和证据存储。主 Agent 收到任务：将这张图重建为可编译的 LaTeX/TikZ。

输入信息包括图片路径、705×320 像素尺寸和初始状态摘要。**参考 LaTeX 不提供给运行中的 Agent。**
''')
image('00_input.png','原始输入图：1260_q_fig2')
js({'image_path':s['image_path'],'image_size':s['image_size']})
add('本次 Supervisor 没有调用 `inspect_image`，也没有给 Geometry 或 TikZ 设置 `use_image=true`。因此，主 Agent、Geometry 和 TikZ 的大模型调用均未附原图。CV 本地程序仍然读取原图。')

add('''## 3. 步骤 1：Supervisor 调用 detect_lines

**谁调用谁：** Supervisor 选择 `call_cv_tool`，Runner 调用本地 `detect_lines`。不需要大模型执行检测算法。

Supervisor 只给出工具名和参数。Runner 自动提供当前图片路径与输出目录，工具读取 PNG 并检测线段。''')
params(1);recorded(1)
add('下面是实际写入 GES 的 8 条检测线段，**仅摘取 id、coords 和线型字段**。它们还不是已经完全确认的几何结构。')
js([{'id':o['id'],'coords':o['coords'],'line':o.get('style',{}).get('line')} for o in s['objects'].values() if o.get('source')=='cv:detect_lines' and o.get('type')=='segment'])
add('**信息如何进入下一步：** `ingest_cv_result` 将检测结果写入 GES；`compact_cv_result` 压缩结果，作为 tool 消息返回主 Agent。主 Agent 据此决定下一步绑定字母。')

add('''## 4. 步骤 2：Supervisor 调用 bind_point_labels

**谁调用谁：** Supervisor 再次调用 `call_cv_tool`，指定 `bind_point_labels`。

工具尝试把图上的字母和从线段推导出的顶点配对。''')
params(2);recorded(2)
add('实际存储的标签绑定如下。右侧是 CV 顶点 ID，不是像素坐标，也不是 Geometry 后续创建的 `point_A` 等 ID：')
js(s['label_bindings'])
add('A、B、C、D、E、F 均有绑定，但 **G 标签没有匹配到对应顶点**。下面是 G 标签在 GES 中的实际对象：')
glabel=next(o for o in s['objects'].values() if o.get('type')=='label' and o.get('label')=='G')
js(glabel)
image('s03_labels.png','CV 标签绑定：G 被检测到，但没有绑定顶点')
add('**信息如何进入下一步：** 标签和绑定关系写入 GES，压缩结果返回 Supervisor。主 Agent 已掌握一批点坐标和线段描述，接着要求 Geometry 做结构分析。')

add('''## 5. 步骤 3：Supervisor 委派 Geometry Agent

### 5.1 主 Agent 传了什么

实际指令包含 A～F 的坐标、8 条检测线段的描述，并要求：判断线段连接哪些点、F 是否在 AE 上、虚线代表什么，以及未绑定的 G 应如何处理。''')
params(3)
add('程序另外将 `state.summary(max_objects=60, max_chars=9000)` 自动放入 Geometry 的输入。`use_image=null` 在执行时按 false 处理，这次 Geometry 大模型不看图，而是分析文字与坐标。')
add('''### 5.2 Geometry 内部又调用了哪些工具

它补查了直角标记和虚实线。下面两段来自 `cv_runs`，保留了实际参数：''')
for cv in s['cv_runs'][2:]:js(cv)
add('`detect_right_angle_marker` 的 `roi=[0,0,1,1]` 表示整张图，结果是 0 个方块直角标记。`analyze_line_style` 检查 3 段，包括 AB、BE 和较长底边。`count=3` 不能理解成所有虚实线争议均已解决，Geometry 最后仍保留了底边争议。')
add('''### 5.3 Geometry 实际留下了什么几何 JSON

它将零散检测结果整理为点、线段和关系。例如：确认 F 的点坐标，记录 F 在 AF 上、E 在底边 BC 上，同时保留 G 未绑定的问题。

下面是**完整提取的 Geometry 状态**：14 个对象、5 条关系、2 个冲突和 Geometry 提交的 4 条未决项。对象与关系筛选 `source=geometry_agent`，冲突为这次归档中的两项。程序补充的空字段、状态和来源也保留。

注意：`candidate` 表示候选判断，`rejected` 表示被否定的关系。比如 JSON 中出现 `parallel`，如果其 `status=rejected`，含义是“否定平行”，不能读成确认平行。''')
geometry={'objects':[o for o in s['objects'].values() if o.get('source')=='geometry_agent'], 'relations':[o for o in s['relations'].values() if o.get('source')=='geometry_agent'], 'conflicts':s['conflicts'],'unresolved_issues':[u for u in s['unresolved_issues'] if u.get('source')=='geometry_agent']}
js(geometry);recorded(3)
add('**信息如何进入下一步：** `submit_geometry` 的内容经程序校验合并到 GES。子 Agent 给主 Agent 返回合并统计和摘要；并非把整份 JSON 原样塞给主 Agent。后续 TikZ Agent 则从更新后的 GES 读取对象与关系。')

add('''## 6. 步骤 4：Supervisor 委派 TikZ Agent 生成 v1

### 6.1 传入的绘图任务

主 Agent 明确指定了点、实线、虚线、标签方位和坐标翻转要求。**实际指令只要求 AF 画到 F，也没有要求画 FG 或 G。**''')
params(4)
add('''TikZ Agent 的实际上下文还自动包含：

- GES 中的几何对象、关系和图片尺寸。
- 从原图测得的线宽、标签字号和建议坐标尺度。
- `TIKZ_SYSTEM` 中的绘图规则。

本次 `use_image=null`，没有给 TikZ 大模型附图。生成采用的尺度最终是 0.012719 cm/px，并按墨迹框中心平移、翻转 y 轴，而非机械采用指令中举例的 `/100`。

### 6.2 代码如何变成图片

TikZ 大模型通过 `submit_tikz` 交出完整文档。Runner 随后自动执行：

1. `compile_tikz`：调用 Tectonic，将 tex 编译为 PDF。
2. `render_pdf`：将 PDF 渲染成 PNG。
3. `validate_compilation`：检查源码结构、编译成功、产物存在、非空白等。
4. 对渲染图做与原图相适应的画布处理，记录版本与编译结果。

这些本地步骤不需要主 Agent 再逐个发起动作。''')
recorded(4)
add('以下是 v1 编译阶段在 evidence 中保存的实际结果；它属于**内部编译信息**，不是整个 `run_tikz_agent` 的完整原始返回：')
ev=list(s['evidence'].values())
js(next(e['payload']['compile'] for e in ev if e.get('method')=='tikz generate'))
image('v1.png','首版 v1：编译成功，但漏掉 FG 虚线和 G 标签')
add('**编译通过只说明代码能执行，不代表图画完整了。** 主 Agent 接下来请求视觉评审。')

add('''## 7. 步骤 5：Supervisor 调用 Critic 评审 v1

主 Agent 要求重点看线段延伸、虚线和标签位置。''')
params(5)
add('程序自动选取最新成功渲染 v1，把原图和渲染图裁到各自墨迹范围，再等比例归一化，拼成左右对比图。同时提供 GES 摘要与对象核对清单。**这是本次第一轮向大模型附图。**')
image('compare_v1.png','Critic 实际案例对比图：左侧原图，右侧 v1')
add('下面是实际存储报告的字段节选，issues 保留完整两项：')
keys=['version','assessment_score','score_kind','verdict','issues','checklist_score','actionable_counts','must_repair','labels']
js({k:s['critic_reports'][0][k] for k in keys});recorded(5)
add('Critic 的意思是：“AF 不该在 F 就结束，后面还应该有 FG 虚线；底边上的 G 标签也漏了。”这两项分别为 high 和 medium，因此 `must_repair=true`。评审报告写入 GES，并将具体问题返回主 Agent。0.85 是内部启发式评分，不是外部 SSIM 指标。')

add('''## 8. 步骤 6：Supervisor 推算 G，要求 TikZ 修复

### 8.1 G 的位置从哪里来

Critic 指出“沿 AF 延伸到 BC 的交点是 G”。主 Agent 在修复指令中利用已有坐标进行外推：

```text
A = (68.5, 65)
F = (238.3, 149.6)
底边：y = 254

AF 斜率 = (149.6 - 65) / (238.3 - 68.5) ≈ 0.498
相交位置 x = 68.5 + (254 - 65) / 0.498 ≈ 448
所以 G ≈ (448, 254) px
```

**这个坐标来自主 Agent 的几何外推，并没有重新调用 CV 独立验证。**

### 8.2 传回 TikZ 的信息
''')
params(6)
add('除了这条修复指令，TikZ Agent 自动获得 **v1 完整源码、GES 的对象和关系、编译错误/警告、Critic 的 issues**，以及缓存的风格参数。它据此补上 FG 虚线和 G 标签，然后重新提交完整文档。')
recorded(6)
add('实际 v2 代码中新增加的关键内容如下（从已保存的 tex 原样节选）：')
tex=s['tikz_versions'][1]['tex']
newlines=[x for x in tex.splitlines() if '\\coordinate (G)' in x or '(F) -- (G)' in x or 'at (G)' in x]
add('```latex\n'+'\n'.join(newlines)+'\n```')
image('v2.png','修复版 v2：补上 FG 虚线与 G 标签')
add('Runner 再次自动编译、渲染、校验。虽然 v2 已编译通过，但此刻动作记录中 `best_version=1`：v2 尚未完成视觉评审，不能仅凭编译成功就替换已经评审的最佳版本。')

add('''## 9. 步骤 7：Supervisor 再次调用 Critic

这次 focus 更具体：检查 FG 是否延长到底边，以及 G 标签是否补上。程序改用原图与 v2 的对比图，仍提供 GES 和对象清单。''')
params(7)
js({k:s['critic_reports'][1][k] for k in keys});recorded(7)
add('这次 `issues=[]`、`must_repair=false`，内部评分 0.93。系统将最佳版本更新为 v2。Critic 的自然语言描述本身仍是模型判断，不能把每个措辞都当成已验证的几何公理；例如完整报告中关于 F 的方位描述不能覆盖 Geometry 中的实际坐标与关系。')

add('''## 10. 步骤 8：Supervisor 调用 finish

主 Agent 提交总结、状态和仍未解决的问题。''')
params(8);recorded(8)
add('最终运行结果的实际字段节选如下：')
js({k:r[k] for k in ['status','stop_reason','best_version','best_score','latest_version','counts','best_tex_path','best_png_path']})
add('''`success` 表示这次生成任务已有可用结果，**不表示 GES 的冲突和未决项全部清零**。最终保留 2 个历史冲突、6 条未决项。修复主要体现在 v2 源码、渲染图与评审记录中，不代表几何状态中已经补建并独立验证了 G 点。

最终对象数 35、关系数 11 包含 CV 与 Geometry 的记录，可能有对应同一几何元素的不同来源对象，不能解读为图中有 35 个独立几何实体。

## 11. 这次到底调用了多少次大模型

下面由 `llm_calls.jsonl` 的实际记录统计：''')
summary=[]
for tag in dict.fromkeys(c['tag'] for c in calls):
    cs=[c for c in calls if c['tag']==tag]
    summary.append({'tag':tag,'calls':len(cs),'calls_with_images':sum(bool(c['has_images']) for c in cs),'model':cs[0]['model']})
js(summary)
add('''合计 14 次大模型调用：Supervisor 8 次、Geometry 2 次、TikZ 2 次、Critic 2 次。只有 Critic 的两次调用附图。Geometry 的两轮调用用于工具调用与后续提交，不是“主 Agent 委派了两次 Geometry”。

本次显式 CV 调用共 4 次：Supervisor 发起线检测与标签绑定，Geometry 内部发起直角检查与线型分析。风格测量等辅助本地处理不属于这 4 条 `cv_runs` 动作。

归档统计 `tool_calls=9` 包含本地 CV 调用与子 Agent 委派，不等于模型调用次数。主 Agent 的 8 个步骤中，finish 不增加该工具计数，Geometry 内部的两次 CV 会计入工具预算。

第一轮 Supervisor 实际曾同时提出两个工具调用，但 Runner 按“每步只执行首个动作”的规则只执行一个，另一个明确忽略。后续仍单独执行了步骤 2，因此本文按实际执行的 action_history 还原。

## 12. 用一句话串起来

CV 先把线和字母找出来，Geometry 把它们整理成结构，TikZ 按结构与主 Agent 的指令写代码；Critic 拿渲染图和原图一比，发现 FG 与 G 漏了，主 Agent 推算 G 的位置，把旧代码和问题交回 TikZ 修，最后由 Critic 再确认一次。

## 13. 实际文件与代码依据

- [输入原图](../data/test/image/1260_q_fig2.png)
- [完整归档状态 state.json](../outputs/ours100/stem/1260_q_fig2/state.json)
- [运行结果 result.json](../outputs/ours100/stem/1260_q_fig2/result.json)
- [事件记录 events.jsonl](../outputs/ours100/stem/1260_q_fig2/events.jsonl)
- [模型调用元数据 llm_calls.jsonl](../outputs/ours100/stem/1260_q_fig2/llm_calls.jsonl)
- [最终 TikZ 源码](../outputs/ours100/stem/1260_q_fig2/best.tex)
- [最终图片](../outputs/ours100/stem/1260_q_fig2/best.png)
- [案例图片与时间线](../outputs/case_studies/1260_q_fig2/timeline.md)
- [Supervisor 提示词构造](../geoagent/agents/supervisor.py)
- [Runner 主循环与动作分发](../geoagent/orchestration/runner.py)
- [Geometry Agent 与合并逻辑](../geoagent/agents/geometry_agent.py)
- [TikZ Agent](../geoagent/agents/tikz_agent.py)
- [Critic Agent](../geoagent/agents/critic_agent.py)
- [GES 数据结构与摘要](../geoagent/state/schemas.py)
- [CV 工具注册与 schema](../geoagent/cv_tools/registry.py)
- [CV 结果写入 GES](../geoagent/orchestration/ingest.py)
''')
target=root/'docs/1260_q_fig2_完整处理流程.md'
target.write_text('\n'.join(parts),encoding='utf-8')
# Verify every JSON block is parseable and the key extracted geometry is complete.
text=target.read_text(encoding='utf-8')
blocks=re.findall(r'```json\n(.*?)\n```',text,re.S)
for block in blocks:json.loads(block)
assert len(geometry['objects'])==14 and len(geometry['relations'])==5
assert len(actions)==8
for target_link in re.findall(r'\]\((\.\./[^)]+)\)',text):
    assert (target.parent/target_link).exists(),target_link
print(json.dumps({'file':str(target),'json_blocks':len(blocks),'characters':len(text),'geometry_objects':len(geometry['objects']),'geometry_relations':len(geometry['relations'])},ensure_ascii=False))
