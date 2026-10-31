import fs from 'node:fs/promises';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
import {FileBlob,PresentationFile} from '@oai/artifact-tool';
const root='D:/Users/18217/Desktop/我的文件/GeoAgent';
const out=path.join(root,'outputs/presentation/GeoAgent_架构与案例Pipeline.pptx');
const build=path.join(root,'.codex-ppt-build/cases'); await fs.mkdir(build,{recursive:true});
const source=path.join(root,'outputs/presentation/GeoAgent_系统架构.pptx');
const p=await PresentationFile.importPptx(await FileBlob.load(source));
const C={ink:'#12253F',muted:'#596A80',blue:'#3367AD',teal:'#147C80',orange:'#C36C30',rule:'#C5CEDA'};
let s;
function txt(t,x,y,w,h,size=25,color=C.ink,bold=false){const a=s.shapes.add({geometry:'textbox',name:t,position:{left:x,top:y,width:w,height:h},fill:'none',line:{fill:'none',width:0}}); a.text=t;a.text.style={typeface:'Microsoft YaHei',fontSize:size,color,bold,verticalAlignment:'middle',insets:0};return a;}
function line(x,y,w,color=C.rule,arrow=false){s.shapes.add({geometry:'connector',kind:'straight',position:{left:x,top:y,width:w,height:0},line:{fill:color,width:2},...(arrow?{tail:{type:'triangle'}}:{})});}
async function pic(id,file,x,y,w,h){s.images.add({blob:new Uint8Array(await fs.readFile(path.join(root,'outputs/case_studies',id,file))),contentType:'image/png',alt:id+' '+file,position:{left:x,top:y,width:w,height:h},fit:'contain'});}
function page(title,sub,id,n){s=p.slides.add();s.background.fill='#F8FAFC';txt(title,55,35,1490,68,43,C.ink,true);txt(sub,55,112,1490,54,26,C.muted);txt(id,55,843,500,28,21,C.muted);txt('Critic 分数为内部评审信号，不是外部准确率',830,843,690,28,21,C.muted);txt(String(n).padStart(2,'0'),1530,843,50,28,21,C.muted);}
function flow(labels){for(let i=0;i<labels.length;i++){txt(labels[i],55+i*310,184,270,42,27,C.blue,true);if(i<4)line(330+i*310,207,28,C.blue,true);}}
function notes(id,body){s.speakerNotes.text=`来源：${root}/outputs/case_studies/${id}/timeline.md、case.json，以及同目录原始阶段图。${body} 所有图像为该案例真实输入、CV 叠加或 TikZ 编译渲染产物。图中 GES 对象/关系数为素材归档状态的汇总，不表示每个阶段当时数量。每个 TikZ 版本均编译成功；生成与修复后都先编译、渲染，再由 Critic 对比原图。Critic 分数 assessment_score 为内部启发式信号。参考 LaTeX 运行期间对 Agent 隔离。`;}
// Case 1: the full evidence-to-render loop.
page('案例一｜圆与弦：从几何证据到样式修复','6984：CV 提取几何结构，Geometry 汇总证据；Critic 再校正标签与笔画样式','6984_q_fig1',2);
flow(['输入图像','CV 检测','GES / Geometry','生成 v1','修复后 v3']);
const x=[55,365,675,985,1295];
for(const [i,f] of ['00_input.png','s03_circles.png','ges.png','v1.png','v3.png'].entries())await pic('6984_q_fig1',f,x[i],240,255,290);
const caps=['整圆、直径与弦\nF 处有直角标记','4 段线、1 个圆\n直角与 8 个字母','35 对象 / 25 关系\n统一几何与证据','编译成功，分数 0.90\nF 标签偏侧、线偏细','编译成功，分数 0.95\n标签与笔画更接近原图'];
caps.forEach((v,i)=>txt(v,x[i],548,270,82,23,i===4?C.teal:C.muted));
line(55,662,1490);
txt('v1 → v2｜修正标签',55,684,455,42,28,C.orange,true);
txt('Critic 指出 F 在弦 DG 的错误一侧；\n将 F 标签移到点的右下方。',55,735,460,75,25,C.ink);
txt('v2 → v3｜修正线宽',565,684,470,42,28,C.orange,true);
txt('v2 仍为 0.90；圆与 AB 加粗至 1.4 pt，\n弦保持 0.6 pt，再次编译与评审。',565,735,480,75,25,C.ink);
txt('输出｜保留 v3',1090,684,450,42,28,C.teal,true);
txt('14 个调度步骤，3 次生成 / 编译 / 评审；\n最终 Critic 未提出样式问题。',1090,735,450,75,25,C.ink);
notes('6984_q_fig1','版本分数：v1=0.90，v2=0.90，v3=0.95；best_version=3。CV 检测与原图视觉检查后提交几何，修复主要针对 F 标签侧别与圆/AB 线宽。v2 将圆和 AB 设为 0.8pt，仍偏细；v3 设为 1.4pt，弦为 0.6pt。共14 steps。');
// Case 2: evidence can be wrong; visual review repairs it.
page('案例二｜误检圆弧：Critic 纠正错误几何','403：CV 检测出假圆弧并影响首次生成；原图复核后删弧补线，再调整局部细节','403_q_fig1',3);
flow(['输入图像','CV 假阳性','首次生成 v1','结构修复 v2','最终版本 v5']);
for(const [i,f] of ['00_input.png','s03_circles.png','v1.png','v2.png','v5.png'].entries())await pic('403_q_fig1',f,x[i],235,255,300);
const caps2=['原图没有圆弧\n仅线段、虚线与直角','8 段线、1 个直角\n圆检测误报 1 条弧','分数 0.45\n多余圆弧，CD 未到 D','分数 0.88\n删去圆弧，CD 补到 D','分数 0.90\n调整 E 上方虚线延伸'];
caps2.forEach((v,i)=>txt(v,x[i],548,270,82,23,[1,2].includes(i)?C.orange:(i===4?C.teal:C.muted)));
line(55,662,1490);
txt('证据进入 GES',55,684,455,42,28,C.blue,true);
txt('Geometry 汇总后，归档状态为\n44 个对象、21 条关系；CV 仍可能误检。',55,735,465,75,25,C.ink);
txt('Critic → 原图复核 → 修复',565,684,480,42,28,C.orange,true);
txt('v1 被指出假弧与断线；Supervisor\n调用 inspect_image，随后指示删弧补线。',565,735,485,75,25,C.ink);
txt('继续迭代与结束门控',1090,684,450,42,28,C.teal,true);
txt('v4 尚有中度问题，finish 被拦截；\nv5 仍有轻微延伸偏长，最终保留 v5。',1090,735,455,75,25,C.ink);
notes('403_q_fig1','完整分数轨迹：v1=0.45→v2=0.88→v3=0.88→v4=0.86→v5=0.90。共18步、5次编译/评审。step8 inspect_image复核原图是否存在圆弧；step9删除全部圆弧并补齐CD；之后调整E上方虚线延伸。step15 finish因中度问题被拒绝，之后生成v5。v5仍有一条low问题（E上方虚线稍长），没有宣称零误差。best_version=5。');
// Case 3: a wide geometry input needs room to make the missing segment visible.
page('案例三｜遗漏 FG 虚线：从差异定位到完整补绘','1260：标签绑定阶段 G 未绑定；首次渲染遗漏 FG 与 G，Critic 指定位置后一次修复','1260_q_fig2',4);
const xx=[55,565,1075];
const hs=['原图｜应有 FG 与 G','生成 v1｜0.85','修复 v2｜0.93'];
for(let i=0;i<3;i++){txt(hs[i],xx[i],190,470,44,29,i===2?C.teal:C.blue,true);if(i<2)line(xx[i]+475,212,25,C.blue,true);}
for(const [i,f] of ['00_input.png','v1.png','v2.png'].entries())await pic('1260_q_fig2',f,xx[i],253,470,260);
txt('AF 的方向从 F 继续延伸至底边 G；\nFG 使用虚线，并标出 G。',55,540,470,76,25,C.muted);
txt('文档编译通过，但 AF 停在 F；\nFG 虚线与底边上的 G 标签均缺失。',565,540,470,76,25,C.orange);
txt('延长至底边 G，补画 FG 虚线；\n保留其余几何、样式与标签。',1075,540,470,76,25,C.teal);
line(55,658,1490);
txt('① CV → Geometry / GES',55,680,470,44,28,C.blue,true);
txt('检测 8 段线并绑定标签，G 未绑定；\n几何归档状态：35 对象 / 11 关系。',55,735,470,75,25,C.ink);
txt('② 编译渲染 → Critic',565,680,470,44,28,C.orange,true);
txt('与原图对比，定位两项遗漏：\nFG 虚线为高严重度，G 标签为中度。',565,735,470,75,25,C.ink);
txt('③ 修复 → 重评 → 输出',1075,680,470,44,28,C.teal,true);
txt('补绘后重新编译与评审，保留 v2；\n共 8 个调度步骤、2 次编译 / 评审。',1075,735,470,75,25,C.ink);
notes('1260_q_fig2','v1分数0.85，Critic发现FG虚线(high)及G标签(medium)缺失。Supervisor让TikZ把AF方向延长到BC上G点；v2补画虚线FG及G标签，再编译、评审，分数0.93，best_version=2。最终报告未列问题。所有图片使用case_studies中的00_input.png、v1.png、v2.png。');
for(let i=0;i<p.slides.items.length;i++){const blob=await p.export({slide:p.slides.items[i],format:'png',scale:1});await fs.writeFile(path.join(build,`slide-${i+1}.png`),new Uint8Array(await blob.arrayBuffer()));}
const candidate=path.join(build,'candidate.pptx');await(await PresentationFile.exportPptx(p)).save(candidate);
const skill='C:/Users/18217/.codex/plugins/cache/openai-primary-runtime/presentations/26.1026.10807/skills/presentations';
const {finalizePresentation}=await import(pathToFileURL(path.join(skill,'container_tools/artifact_tool_utils.mjs')).href);
console.log(await finalizePresentation({workspaceDir:root,candidatePath:candidate,finalPath:out,pythonExecutable:'C:/Users/18217/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe',integrityValidatorPath:path.join(skill,'container_tools/inspect_presentation_package_integrity.py'),layoutValidatorPath:path.join(skill,'container_tools/inspect_presentation_layout_geometry.py'),layoutArgs:['--expected-slide-size-emu','15240000,8572500','--validate-bullet-geometry','--validate-heading-fit'],explicitTotalSlideCount:4,fontPolicy:{basis:'design',families:['Microsoft YaHei']},verifyArtifactToolImport:true,receiptPath:path.join(build,'validation.json')}));
