import fs from 'node:fs/promises';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
import {Presentation,PresentationFile} from '@oai/artifact-tool';
const root='D:/Users/18217/Desktop/我的文件/GeoAgent';
const out=root+'/outputs/presentation_build';
const skill='C:/Users/18217/.codex/plugins/cache/openai-primary-runtime/presentations/26.1026.10807/skills/presentations';
const p=Presentation.create({slideSize:{width:1600,height:900}});
const C={ink:'#162A40',muted:'#526479',blue:'#205EAB',teal:'#117F78',light:'#EBF3FA',rule:'#CFDAE4',orange:'#AF5B22'};
const font='Microsoft YaHei';
p.theme.defaultFont=font;
function txt(s,t,x,y,w,h,size=24,color=C.ink,bold=false){let q=s.shapes.add({geometry:'textbox',position:{left:x,top:y,width:w,height:h},fill:'none',line:{fill:'none',width:0}});q.text=t;q.text.style={typeface:font,fontSize:size,color,bold};q.text.insets=0;return q;}
function line(s,x,y,w,color=C.rule){return s.shapes.add({geometry:'line',position:{left:x,top:y,width:w,height:0},line:{fill:color,width:1.4}});}
function base(title,n,sub){let s=p.slides.add();s.background.fill='#FFFFFF';txt(s,title,64,42,1450,62,42,C.ink,true);txt(s,sub,66,116,1460,44,23,C.muted);line(s,64,168,1472);txt(s,'GeoAgent',64,855,300,25,17,C.muted);txt(s,String(n).padStart(2,'0')+' / 03',1430,855,100,25,17,C.muted);return s;}
function box(s,title,desc,x,y,w,h,color=C.blue){let q=s.shapes.add({geometry:'rect',position:{left:x,top:y,width:w,height:h},fill:color===C.ink?C.ink:C.light,line:{fill:color,width:1.6}});txt(s,title,x+18,y+15,w-36,38,27,color===C.ink?'#FFFFFF':color,true);if(desc)txt(s,desc,x+18,y+61,w-36,h-65,22,color===C.ink?'#E2EAF3':C.muted);return q;}
function conn(s,a,b,from='right',to='left',color=C.blue,dashed=false){s.shapes.connect(a,b,{kind:'elbow',fromSide:from,toSide:to,line:{fill:color,width:2,style:dashed?'dashed':'solid'},tail:{type:'triangle',width:'sm',length:'sm'}});}
async function img(s,name,x,y,w,h){let b=await fs.readFile(root+'/outputs/case_studies/1260_q_fig2/'+name);return s.images.add({blob:b.buffer.slice(b.byteOffset,b.byteOffset+b.byteLength),contentType:'image/png',alt:name,fit:'contain',position:{left:x,top:y,width:w,height:h}});}
// 1. Native, editable architecture diagram.
{
let s=base('GeoAgent 系统架构',1,'输入几何图像，逐步提取证据并生成 TikZ，经编译和视觉评审后保留最佳版本');
let input=box(s,'输入图像','TriGeoBench / 上传图',64,219,285,120);
let sup=box(s,'Supervisor 主 Agent','每步一个动作，依据 GES 与工具反馈选择下一步',451,208,680,138,C.ink);
let output=box(s,'最佳版本归档','best.tex / PDF / PNG\n评审报告与运行轨迹',1232,215,304,132,C.teal);
conn(s,input,sup);conn(s,sup,output);
let cv=box(s,'本地 CV 工具','线段、圆弧、标签绑定\n直角标记、虚实线',64,444,310,130);
let geo=box(s,'Geometry Agent','补充 CV 并整合几何\n对象、关系与冲突',451,444,310,130);
let tikz=box(s,'TikZ Agent','generate / repair\n输出完整 LaTeX 源码',839,444,310,130);
let critic=box(s,'Critic Agent','原图与渲染图对照\n输出问题与修复建议',1226,444,310,130);
for(let q of [cv,geo,tikz,critic])conn(s,sup,q,'bottom','top',C.blue);
txt(s,'动作调度与结果回传',574,371,430,32,21,C.muted);
let ges=box(s,'GES 共享几何证据状态','对象 / 关系 / 证据 / 标签 / 冲突 / 版本 / 编译结果 / Critic 报告',64,662,1085,120,C.teal);
for(let q of [cv,geo,tikz])conn(s,q,ges,'bottom','top',C.teal,true);
let compile=box(s,'自动编译与校验','Tectonic 编译、PNG 渲染\n结构检查后交 Critic',1226,662,310,120);
conn(s,tikz,compile,'bottom','left');conn(s,compile,critic,'top','bottom');conn(s,critic,ges,'left','right',C.teal,true);
txt(s,'GES 摘要随每轮提示回到 Supervisor；Critic 的具体问题驱动 repair',66,806,1100,30,21,C.muted);
txt(s,'预算约束：步数、工具、视觉、token、超时',1120,806,440,30,18,C.muted);
s.speakerNotes.text='来源：README.md §2；docs/pipeline.md §1–3；geoagent/orchestration/runner.py；geoagent/agents/schemas.py。实线表示调用/处理，虚线表示结果写入 GES。图中省略底层 LLMClient、VisualContextManager、EvidenceStore。inspect_image 由 VisualContextManager 提供原图或 ROI 并在下一条 user 消息附图。Geometry 可自行调用 CV。TikZ 生成前测量风格并对已验证的直角正交化。Supervisor 每轮读取 GES 摘要。参考 LaTeX 全程对 Agent 隔离。编译成功只是结构可用，视觉一致性还需 Critic。';
}
// 2. Six-action input/output contract as a real PowerPoint table.
{
let s=base('主 Agent 的六类动作空间',2,'Supervisor 每轮只执行一个动作，返回结果用于更新 GES 或下一轮上下文');
const vals=[['动作','输入','输出 / 状态变化','作用'],
['call_cv_tool','tool_name、params、purpose\n如 detect_lines、ROI 等参数','检测结果、坐标、置信证据\n自动写入 GES，返回压缩摘要','获取可量化的\n局部几何证据'],
['inspect_image','question、可选 region\n查看原图或指定局部','原图 / ROI 附到下一条用户消息\n返回 region_id、裁剪范围等','补充视觉理解\n消耗视觉预算'],
['run_geometry_agent','instruction、可选 use_image / roi\n自动读取 GES 摘要','submit_geometry：对象、关系、\n冲突、未决项，合并到 GES','整合证据与几何\n可继续调用 CV'],
['run_tikz_agent','mode、instruction、可选 use_image\nGES，修复时含旧源码与反馈','完整 tex；自动编译 / 渲染 / 校验\n返回版本号、PNG、错误与状态','生成首版或修复\n落实为可编译代码'],
['run_critic','可选 focus\n自动取原图、最新成功渲染与 GES','issues、checks、assessment_score\nmust_repair，更新最佳版本','定位遗漏与偏差\n决定是否需修复'],
['finish','summary、可选 unresolved / status\nstatus: success / partial / blocked','best_version、best_score、status\n记录总结与未决项，结束运行','提交最终结果\n经过收尾门控']];
let t=s.tables.add({rows:7,columns:4,left:64,top:203,width:1472,height:568,columnWidths:[292,406,490,284],values:vals});
t.borders.assign({fill:C.rule,width:1,style:'solid'});
t.cells.block({row:0,column:0,rowCount:7,columnCount:4}).assign({textStyle:{typeface:font,fontSize:22,color:C.ink},margins:{left:15,right:12,top:4,bottom:4},anchor:'center'});
for(let r=0;r<7;r++){t.rows[r].height=r===0?52:86;for(let c=0;c<4;c++){let cell=t.getCell(r,c);cell.fill=r===0?C.ink:(r%2===0?'#F1F5F8':'#FFFFFF');if(r===0)cell.text.style={typeface:font,fontSize:23,bold:true,color:'#FFFFFF'};if(c===0&&r>0)cell.text.style={typeface:font,fontSize:21,bold:true,color:C.blue};}}
txt(s,'修复门控：有效问题出现任一 high / medium，或至少 2 条 low 时，must_repair=true',66,795,1460,34,22,C.teal,true);
s.speakerNotes.text='来源：geoagent/agents/schemas.py 的 SUPERVISOR_TOOLS（CV_TOOL_SCHEMAS 中 call_cv_tool 加其余五项）；geoagent/cv_tools/registry.py；geoagent/orchestration/runner.py 的 _do_*；geoagent/agents/geometry_agent.py；geoagent/agents/tikz_agent.py；geoagent/agents/critic_agent.py。表格输入同时区分显式调用参数和自动提供的上下文。inspect_image 本身返回元数据，图片通过追加 user 消息注入，供下一轮 Supervisor 查看，不是工具返回文字描述。run_tikz_agent 自动进行 style metrics 和已验证直角的正交化。finish 门控在预算允许时，对未评审/需修复情况做有限次数拦截，并非永久禁止停止。must_repair 排除 flaky 和信息项。assessment_score 是内部启发式评分，不是外部评测指标。';
}
// 3. An actual recorded case, preserving all eight Supervisor steps.
{
let s=base('1260_q_fig2 的处理 Pipeline',3,'8 个 Supervisor 步骤，2 次生成与编译，2 轮 Critic 评审；核心修复是补回 FG 虚线和 G 标签');
const xs=[64,444,824,1204],w=332;
const caps=['原始输入（705 × 320）','CV 标签绑定（G 未绑定）','v1：缺少 FG 和 G','v2：补全并复评'];
for(let i=0;i<4;i++){txt(s,caps[i],xs[i],201,w,33,24,i===2?C.orange:C.blue,true);}
const ims=['00_input.png','s03_labels.png','v1.png','v2.png'];
for(let i=0;i<4;i++)await img(s,ims[i],xs[i],247,w,170);
for(let i=0;i<3;i++){s.shapes.add({geometry:'connector',kind:'straight',position:{left:xs[i]+w+9,top:331,width:28,height:0},line:{fill:C.blue,width:2},tail:{type:'triangle'}});}
line(s,64,443,1472);
txt(s,'1–2  提取局部证据',xs[0],466,w,36,27,C.blue,true);
txt(s,'detect_lines 检出 8 条线段。\nbind_point_labels 绑定标签，\nG 因缺少附近顶点而未绑定。\n\nCV 结果经 ingest 写入 GES，\nSupervisor 读取结果后委派\nGeometry Agent。',xs[0],517,w,236,22);
txt(s,'3  整合几何状态',xs[1],466,w,36,27,C.blue,true);
txt(s,'Geometry 再检查直角与线型。\n未检出方块直角标记。\n\n合并 14 个对象、5 条关系，\n保留 G 未绑定与虚实线争议。\n\nGES 将结构化证据提供给\nTikZ Agent。',xs[1],517,w,253,22);
txt(s,'4–5  生成与首轮评审',xs[2],466,w,36,27,C.blue,true);
txt(s,'④ TikZ 依据 GES 与指令生成\nv1，翻转像素 y 轴并统一尺度，\n自动编译、渲染与校验通过。\n\n⑤ Critic 对照原图与渲染图，\n指出 FG 虚线缺失（high）、\nG 标签缺失（medium）。',xs[2],517,w,236,22);
txt(s,'6–8  修复与归档',xs[3],466,w,36,27,C.blue,true);
txt(s,'⑥ Supervisor 沿 AF 外推，\n得到 G≈(448,254) px，委派\nTikZ 补画虚线和标签，编译 v2。\n\n⑦ Critic 确认补全，选择 v2。\n⑧ finish 返回 success，归档\n最佳 tex / PDF / PNG 与日志。',xs[3],517,w,236,22);
txt(s,'Critic 内部评分：v1 0.85 → v2 0.93',824,786,712,35,25,C.teal,true);
txt(s,'G 坐标来自几何外推，未经独立 CV 复核；最终仍保留历史冲突与未决项',64,814,1460,28,19,C.muted);
s.speakerNotes.text='来源：outputs/case_studies/1260_q_fig2/case.json 和 timeline.md；四张图片均直接引用同目录 00_input.png、s03_labels.png、v1.png、v2.png。动作实际顺序：1 call_cv_tool detect_lines；2 call_cv_tool bind_point_labels；3 run_geometry_agent（内部调用 detect_right_angle_marker ROI 全图、analyze_line_style 检查三段）；4 run_tikz_agent generate；5 run_critic；6 run_tikz_agent repair；7 run_critic；8 finish。Geometry 合并 14 objects / 5 relations / 2 conflicts，最终 GES 共35 objects / 11 relations，包含原 CV 对象与合并对象，不能解释成35个独立几何实体。首版指令仅要求 A-F 到 F，没有包含 G，因此漏画。第一次 Critic assessment_score=0.85，两项 missing_element，high FG 与 medium G；修复后 score=0.93。G 的像素外推来自 A(68.5,65)、F(238.3,149.6) 与底边 y=254，相交 x≈448。修复沿用 v1 尺度 0.012719 cm/px 和 bbox 中心。注意这不是新的独立 CV 检测。2 conflicts 和6 unresolved 仍在归档中，因此 success 不等于证据状态全部清零。内部 Critic 分数不等同 SSIM/CLIP/DINO。该归档样例的外部指标为 SSIM .968837，CLIP .997470，DINO .994287。';
}
await fs.mkdir(out,{recursive:true});
for(let i=0;i<p.slides.items.length;i++){let s=p.slides.items[i];let b=await p.export({slide:s,format:'png',scale:1});await fs.writeFile(out+`/slide-${i+1}.png`,new Uint8Array(await b.arrayBuffer()));await fs.writeFile(out+`/slide-${i+1}.layout.json`,await (await s.export({format:'layout'})).text());}
await (await PresentationFile.exportPptx(p)).save(out+'/candidate.pptx');
const {finalizePresentation}=await import(pathToFileURL(skill+'/container_tools/artifact_tool_utils.mjs').href);
let result=await finalizePresentation({workspaceDir:root,candidatePath:out+'/candidate.pptx',finalPath:root+'/outputs/presentations/GeoAgent_三页汇报.pptx',pythonExecutable:'C:/Users/18217/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe',integrityValidatorPath:skill+'/container_tools/inspect_presentation_package_integrity.py',layoutValidatorPath:skill+'/container_tools/inspect_presentation_layout_geometry.py',layoutArgs:['--expected-slide-size-emu','15240000,8572500','--validate-bullet-geometry','--validate-heading-fit','--require-native-table-slide','2'],explicitTotalSlideCount:3,requiredNativeTableOwnerSlides:[2],fontPolicy:{basis:'design',families:[font]},verifyArtifactToolImport:true,receiptPath:out+'/validation-final.json'});
console.log(JSON.stringify(result));



