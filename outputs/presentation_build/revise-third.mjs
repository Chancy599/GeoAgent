import fs from 'node:fs/promises';
import {Presentation,PresentationFile} from '@oai/artifact-tool';
const root='D:/Users/18217/Desktop/我的文件/GeoAgent';
const out=root+'/outputs/presentation_build/revision';
await fs.mkdir(out,{recursive:true});
const p=Presentation.create({slideSize:{width:1600,height:900}});
p.theme.defaultFont='Microsoft YaHei';
const s=p.slides.add();s.background.fill='#FFFFFF';
const C={ink:'#162A40',muted:'#526479',blue:'#205EAB',teal:'#117F78',rule:'#CFDAE4',orange:'#AF5B22'};
function txt(t,x,y,w,h,size=22,color=C.ink,bold=false){let q=s.shapes.add({geometry:'textbox',position:{left:x,top:y,width:w,height:h},fill:'none',line:{fill:'none',width:0}});q.text=t;q.text.style={typeface:'Microsoft YaHei',fontSize:size,color,bold};q.text.insets=0;return q;}
function line(x,y,w){s.shapes.add({geometry:'line',position:{left:x,top:y,width:w,height:0},line:{fill:C.rule,width:1.4}});}
async function img(name,x,y,w,h){let b=await fs.readFile(root+'/outputs/case_studies/1260_q_fig2/'+name);s.images.add({blob:b.buffer.slice(b.byteOffset,b.byteOffset+b.byteLength),contentType:'image/png',alt:name,fit:'contain',position:{left:x,top:y,width:w,height:h}});}
txt('1260_q_fig2：模块调用与信息传递',64,42,1470,62,42,C.ink,true);
txt('Supervisor 逐步调度，GES 保存共享证据；表中“传入”同时包含调用参数和程序自动提供的上下文',66,116,1470,38,22,C.muted);
line(64,168,1472);
const vals=[['步骤','调用对象','传入什么','返回什么 / 如何进入下一步'],
['1–2','Supervisor 调 CV\ndetect_lines\nbind_point_labels','当前原图（工具自动读取）\n两次调用 params={}','8 条线段及坐标、A～F 标签绑定\nG 未绑定；结果写入 GES\n摘要返回 Supervisor'],
['3','Supervisor 委派\nGeometry Agent','整理结构的指令 + 点线坐标 + GES\n内部再调 detect_right_angle_marker\n及 analyze_line_style（检查 3 段）','submit_geometry 提交几何 JSON\n合并 14 对象、5 关系、2 冲突\n记录 F 在 AF 上，G 仍未绑定'],
['4','Supervisor 委派\nTikZ Agent\nmode=generate','点线与标签绘制指令 + GES + 风格参数\n指定实线 AD、DC、CB、AE、FE、AF\n虚线 AB、BE；未要求绘制 FG 与 G','submit_tikz 提交完整 tex\n自动编译、渲染、校验，产出 v1\n编译通过，但仍有视觉遗漏'],
['5','Supervisor 委派\nCritic Agent','原图与 v1 的等尺度对比图\nGES + 对象清单\nfocus：线段延伸、虚线、标签位置','FG 虚线缺失 high，G 标签缺失 medium\n内部评分 0.85，must_repair=true\n问题写入 GES，返回 Supervisor'],
['6','Supervisor 委派\nTikZ Agent\nmode=repair','沿 AF 外推 G≈(448,254) px\n修复指令 + v1 源码 + GES\n编译信息 + Critic 的两项遗漏','补画 FG 虚线与 G 标签\n再次自动编译、渲染、校验，产出 v2\n待评审时 best_version 仍为 v1'],
['7–8','Supervisor 调\nCritic，再 finish','Critic：原图与 v2 + GES，重点查 FG/G\nfinish：summary、status、unresolved','Critic 确认补全，评分 0.93，选 v2\nfinish 返回 success，保留未决项\n归档最佳 tex / PDF / PNG 与日志']];
let t=s.tables.add({rows:7,columns:4,left:64,top:203,width:1056,height:588,columnWidths:[64,216,372,404],values:vals});
t.borders.assign({fill:C.rule,width:1,style:'solid'});
t.cells.block({row:0,column:0,rowCount:7,columnCount:4}).assign({textStyle:{typeface:'Microsoft YaHei',fontSize:19.5,color:C.ink},margins:{left:10,right:8,top:4,bottom:4},anchor:'center'});
for(let r=0;r<7;r++){t.rows[r].height=r===0?48:90;for(let c=0;c<4;c++){let cell=t.getCell(r,c);cell.fill=r===0?C.ink:(r%2===0?'#F1F5F8':'#FFFFFF');if(r===0)cell.text.style={typeface:'Microsoft YaHei',fontSize:21,bold:true,color:'#FFFFFF'};if(c===0&&r>0)cell.text.style={typeface:'Microsoft YaHei',fontSize:21,bold:true,color:C.blue};}}
txt('v1：FG 虚线和 G 标签缺失',1150,204,386,34,24,C.orange,true);
await img('v1.png',1150,249,386,176);
line(1150,443,386);
txt('v2：补齐后，Critic 复评通过',1150,466,386,34,24,C.teal,true);
await img('v2.png',1150,511,386,176);
txt('本次仅 Critic 的大模型调用附图\nSupervisor、Geometry、TikZ\n依据坐标、GES 与文字反馈协作',1150,720,386,84,21,C.muted);
txt('GES = 共享的结构化工作记录；G 的坐标由外推得到，未经独立 CV 复核，最终仍保留历史冲突与未决项',64,813,1472,30,19,C.muted);
txt('GeoAgent',64,855,300,25,17,C.muted);txt('03 / 03',1430,855,100,25,17,C.muted);
const state=JSON.parse(await fs.readFile(root+'/outputs/ours100/stem/1260_q_fig2/state.json','utf8'));
s.speakerNotes.text='来源：outputs/ours100/stem/1260_q_fig2/state.json 的 action_history、cv_runs；同目录 llm_calls.jsonl；geoagent/orchestration/runner.py；geometry_agent.py；tikz_agent.py；critic_agent.py。图片为案例归档 v1.png / v2.png。表格中的输入区分显式参数与自动上下文，指令为中文概括。初始输入为原图路径、705×320 尺寸、任务与初始 GES，未附图。CV 为本地算法；Geometry、TikZ、Critic 与 Supervisor 均调用大模型。实际大模型14次：Supervisor8、Geometry2、TikZ2、Critic2。只有Critic两次has_images=true。步骤3：直角工具ROI=[0,0,1,1]、count=0；线型工具输入AB、BE与长底边三段，不能据count=3理解为所有争议均解决。Geometry提交14对象、5关系、2冲突，其中F在AF上。步骤4的generate指令明确AF只到F，没有要求G与FG。程序测量风格，建议尺度0.012719cm/px，并自动执行compile_tikz/render_pdf/validate_compilation。步骤5出现high FG与medium G。步骤6 Supervisor基于A(68.5,65)、F(238.3,149.6)与底边y=254外推G≈(448,254)，修复沿用v1尺度。步骤7评审后才更新best_version为2。0.85/0.93是内部assessment_score，不是SSIM等外部指标。finish成功不意味着未决项清零。\n\n以下是实际主智能体调用参数与CV内部调用记录，未经改写：\n'+JSON.stringify({action_history:state.action_history,cv_runs:state.cv_runs},null,2);
await fs.writeFile(out+'/slide-3.png',new Uint8Array(await(await p.export({slide:s,format:'png',scale:1})).arrayBuffer()));
await(await PresentationFile.exportPptx(p)).save(out+'/third-only.pptx');
console.log(out);
