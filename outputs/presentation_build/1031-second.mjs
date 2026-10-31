import fs from 'node:fs/promises';
import {Presentation,PresentationFile} from '@oai/artifact-tool';
const root='D:/Users/18217/Desktop/我的文件/GeoAgent';
const out=root+'/outputs/presentation_build/1031';await fs.mkdir(out,{recursive:true});
const p=Presentation.create({slideSize:{width:1600,height:900}});p.theme.defaultFont='Microsoft YaHei';
const s=p.slides.add();s.background.fill='#FFFFFF';
const C={ink:'#162A40',muted:'#526479',blue:'#205EAB',teal:'#117F78',rule:'#CFDAE4',orange:'#AF5B22'};
function txt(t,x,y,w,h,size=23,color=C.ink,bold=false){let q=s.shapes.add({geometry:'textbox',position:{left:x,top:y,width:w,height:h},fill:'none',line:{fill:'none',width:0}});q.text=t;q.text.style={typeface:'Microsoft YaHei',fontSize:size,color,bold};q.text.insets=0;return q;}
function node(title,body,x,y,color=C.blue){let q=s.shapes.add({geometry:'roundRect',position:{left:x,top:y,width:392,height:132},fill:color===C.orange?'#FFF5EA':color===C.teal?'#EDF7F5':'#EBF3FA',line:{fill:color,width:1.5},borderRadius:12});txt(title,x+18,y+14,356,35,25,color,true);txt(body,x+18,y+57,356,68,21);return q;}
function arrow(a,b,from,to,color=C.blue){s.shapes.connect(a,b,{kind:'straight',fromSide:from,toSide:to,line:{fill:color,width:2.4},tail:{type:'triangle',width:'med',length:'med'}});}
async function img(name,x){let b=await fs.readFile(root+'/outputs/case_studies/1260_q_fig2/'+name);s.images.add({blob:b.buffer.slice(b.byteOffset,b.byteOffset+b.byteLength),contentType:'image/png',alt:name,fit:'contain',position:{left:x,top:709,width:392,height:137}});}
txt('1260_q_fig2：这张图是怎么处理的',64,42,1470,62,42,C.ink,true);
txt('先提取点线，再生成代码；发现漏画后，把问题交回去修一轮',66,116,1470,38,23,C.muted);
s.shapes.add({geometry:'line',position:{left:64,top:168,width:1472,height:0},line:{fill:C.rule,width:1.4}});
txt('主 Agent 串起每一步',64,201,400,37,28,C.ink,true);
txt('结果都回给主 Agent，点线、几何关系和评审问题都记进 GES',520,205,1016,34,24,C.teal);
let a=node('①–②  CV：先找线、再绑字母','找到 8 条线段，A～F 绑上了\nG 有字母，但没找到对应顶点',64,276);
let b=node('③  Geometry Agent','补查直角与虚实线，整理点线关系\n交出几何 JSON，G 先留作未决项',604,276);
let c=node('④  TikZ：照着结构画第一版','拿到几何结构、绘图指令和风格参数\n写出源码，自动编译成 v1 图片',1144,276);
let d=node('⑤  Critic：和原图对一对','看原图、v1 和对象清单\n“少了 FG 虚线，也少了 G 标签！”',1144,506,C.orange);
let e=node('⑥  主 Agent 交回 TikZ 修复','主 Agent 沿 AF 推算 G 的位置\nTikZ 补线、补标签，重新编译成 v2',604,506);
let f=node('⑦–⑧  再看一遍，保留结果','Critic：“这次补全了”\n主 Agent 收尾，保留 v2 的源码和图',64,506,C.teal);
arrow(a,b,'right','left');arrow(b,c,'right','left');arrow(c,d,'bottom','top');arrow(d,e,'left','right',C.orange);arrow(e,f,'left','right',C.teal);
txt('坐标\n标签绑定',470,282,120,65,22,C.muted);
txt('几何结构\n绘图指令',1010,282,120,65,22,C.muted);
txt('原图 + v1',1168,444,330,30,23,C.muted);
txt('问题+旧代码\n补上 G',999,510,140,65,20.5,C.orange);
txt('v2 渲染图',465,530,137,35,22,C.teal);
txt('原始输入',64,676,392,32,23,C.muted,true);
txt('v1：遗漏 FG 与 G，评分 0.85',604,676,410,32,23,C.orange,true);
txt('v2：补全后，评分 0.93',1144,676,392,32,23,C.teal,true);
await img('00_input.png',64);await img('v1.png',604);await img('v2.png',1144);
txt('G≈(448,254) 来自几何外推；本次只有 Critic 的大模型调用附图，其余主要依据坐标与文字反馈',64,859,1472,28,19,C.muted);
const state=JSON.parse(await fs.readFile(root+'/outputs/ours100/stem/1260_q_fig2/state.json','utf8'));
s.speakerNotes.text='来源：outputs/ours100/stem/1260_q_fig2/state.json、llm_calls.jsonl，以及 geoagent/orchestration/runner.py 和各 Agent 代码。图中箭头表示处理顺序和关键信息的传递，各步骤实际均由 Supervisor 调用，结果返回 Supervisor，并非子 Agent 相互直接调用。GES 为结构化共享状态。Geometry 内部调用 detect_right_angle_marker（ROI全图，检出0个直角标记）、analyze_line_style（3段），保留虚实线争议与G未绑定项。Geometry提交14个对象、5条关系、2项冲突。生成首版指令只要求AF到F，没有要求FG或G。Critic通过原图/v1对比指出FG缺失high、G缺失medium，内部评分.85。Supervisor通过A(68.5,65)、F(238.3,149.6)与底边y=254外推G≈(448,254)，修复指令明确补FG虚线与G标签，沿用v1风格/尺度。TikZ修复自动获得旧源码、GES、编译信息、Critic问题。两次TikZ提交后均自动运行compile_tikz/render_pdf/validate_compilation。v2评审后才更新最佳版本，评分.93，must_repair=false，finish成功但仍保留未决项。内部评分不是外部SSIM指标。此次只有Critic的大模型调用has_images=true。图片为实际案例原图与v1/v2。\n\n实际参数记录：\n'+JSON.stringify({action_history:state.action_history,cv_runs:state.cv_runs},null,2);
await fs.writeFile(out+'/slide-3.png',new Uint8Array(await(await p.export({slide:s,format:'png',scale:1})).arrayBuffer()));
await(await PresentationFile.exportPptx(p)).save(out+'/third-only.pptx');
console.log(out);



