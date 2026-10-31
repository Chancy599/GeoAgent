import fs from 'node:fs/promises';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
import {Presentation,PresentationFile} from '@oai/artifact-tool';
const root=process.cwd(), build=path.join(root,'.codex-ppt-build');
const skill='C:/Users/18217/.codex/plugins/cache/openai-primary-runtime/presentations/26.1026.10807/skills/presentations';
const p=Presentation.create({slideSize:{width:1600,height:900}}),s=p.slides.add();
s.background.fill='#F8FAFC';
const C={ink:'#12253F',muted:'#596A80',blue:'#3367AD',teal:'#147C80',orange:'#C36C30',line:'#9AAABE'};
function rect(name,x,y,w,h,fill,stroke=C.line){return s.shapes.add({name,geometry:'rect',position:{left:x,top:y,width:w,height:h},fill,line:{fill:stroke,width:1.6}})}
function text(t,x,y,w,h,size=26,color=C.ink,bold=false,align='left'){let a=s.shapes.add({name:t,geometry:'textbox',position:{left:x,top:y,width:w,height:h},fill:'none',line:{fill:'none',width:0}});a.text=t;a.text.style={typeface:'Microsoft YaHei',fontSize:size,color,bold,alignment:align,verticalAlignment:'middle',insets:0};return a;}
function line(x1,y1,x2,y2,color=C.blue,arrow=false,dash=false,both=false){return s.shapes.add({geometry:'connector',kind:'straight',position:{left:Math.min(x1,x2),top:Math.min(y1,y2),width:Math.abs(x2-x1),height:Math.abs(y2-y1),horizontalFlip:x2<x1,verticalFlip:y2<y1},line:{fill:color,width:dash?1.7:2.5,style:dash?'dashed':'solid'},...(arrow?{tail:{type:'triangle'}}:{}),...(both?{head:{type:'triangle'}}:{})});}
text('GeoAgent 系统架构',55,35,1450,65,48,C.ink,true);
text('平面几何图 → 可编译 TikZ；由 Supervisor 调度，以共享证据支撑迭代修复',57,106,1480,44,27,C.muted);
rect('输入',55,185,265,105,'#FFFFFF','#C5CEDA');
text('几何图像',77,201,220,36,29,C.ink,true);text('测试集 / 上传',77,242,230,30,21,C.muted);
line(320,237,390,237,C.blue,true);
rect('Supervisor',390,175,1160,125,C.ink,C.ink);
text('Supervisor · 统一调度',420,190,700,46,34,'#FFFFFF',true);
text('按证据选择动作 · 每步一个工具调用 · 控制步数 / Token / 视觉调用 / 超时预算',420,245,1080,34,24,'#D7E3F3');
// Control bus: compilation is automatic after the TikZ Agent returns.
line(970,300,970,329,C.blue);line(180,329,1425,329,C.blue);
for(const x of [180,490,800,1425])line(x,329,x,385,C.blue,true);
text('调度',1000,304,120,30,21,C.blue);
const xs=[55,365,675,985,1295],w=255,y=385,h=135;
const names=['本地 CV 工具','Geometry Agent','TikZ Agent','编译与渲染','Critic Agent'];
const desc=['检测线 / 圆 / 标签\n提取位置与样式证据','合并几何对象与关系\n处理标签绑定与冲突','生成 / 修复 TikZ\n输出完整 LaTeX 文档','Tectonic 编译 → PDF\n渲染 PNG · 结构校验','原图 vs 渲染图\n核对对象 · 定位差异'];
for(let i=0;i<5;i++){rect(names[i],xs[i],y,w,h,i===3?'#F0F3F7':'#FFFFFF',i===3?'#A7B4C5':C.blue);text(names[i],xs[i]+15,y+12,w-30,37,i===1?23:27,C.ink,true);text(desc[i],xs[i]+15,y+58,w-30,62,22,C.muted);}
for(let i=0;i<4;i++)line(xs[i]+w,452,xs[i+1],452,C.blue,true);
// Repair feedback points back to TikZ; the Supervisor decides whether to run it.
line(1385,520,1385,572,C.orange);line(1385,572,800,572,C.orange,true);line(800,572,800,520,C.orange,true);

// Shared state bus.
for(const x of [180,490,835,1110,1500])line(x,520,x,636,C.line,false,true);
line(180,636,1500,636,C.line,false,true);line(650,636,650,690,C.line,true,true,true);
rect('feedback-label',928,552,325,39,'#F8FAFC','#F8FAFC');text('需修复：差异反馈给 TikZ',937,554,315,35,22,C.orange,true);
text('各模块共享读写',680,646,420,31,22,C.muted);
rect('GES',55,690,1130,118,'#EAF2F4','#94B7BC');
text('GES · 共享几何证据状态',78,700,1080,42,29,C.teal,true);
text('对象 / 关系 / 标签 / 证据 / 冲突  ·  TikZ 版本 / 编译结果 / 评审报告  ·  预算与执行轨迹',78,757,1080,35,23,C.muted);
line(1420,520,1420,690,C.teal,true);
rect('输出',1295,690,255,118,'#E9F4F0','#82B2A2');
text('最佳版本输出',1313,703,220,38,28,C.teal,true);text('TikZ / PDF / PNG\n状态与日志',1313,749,220,50,22,C.muted);
text('按质量与预算结束',1250,826,300,30,21,C.muted,false,'right');
text('蓝色：调度与主流程    橙色：修复反馈    灰色虚线：共享状态',55,837,1120,31,21,C.muted);
s.speakerNotes.text='依据当前仓库代码及 docs/pipeline.md 绘制。主要来源：README.md 架构章节；geoagent/orchestration/runner.py::run、_dispatch、_do_tikz_agent、_compile_version、_do_critic；geoagent/state/schemas.py。图中横向箭头表示典型信息流程，非硬编码执行顺序；CV 工具可由 Supervisor 或 Geometry Agent 调用。编译与渲染由 Runner 在 TikZ 生成后自动执行。Critic 输出问题清单，由 Supervisor 决定修复或结束；预算耗尽时也可能停止。GES 为共享状态，编译、版本、评审和轨迹均写入。参考 LaTeX 运行期间对 Agent 隔离。';
await fs.writeFile(path.join(build,'preview.png'),new Uint8Array(await (await p.export({slide:s,format:'png',scale:1})).arrayBuffer()));
await (await PresentationFile.exportPptx(p)).save(path.join(build,'candidate.pptx'));
const {finalizePresentation}=await import(pathToFileURL(path.join(skill,'container_tools/artifact_tool_utils.mjs')).href);
console.log(await finalizePresentation({workspaceDir:root,candidatePath:path.join(build,'candidate.pptx'),finalPath:path.join(root,'outputs/presentation/GeoAgent_系统架构.pptx'),pythonExecutable:'C:/Users/18217/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe',integrityValidatorPath:path.join(skill,'container_tools/inspect_presentation_package_integrity.py'),layoutValidatorPath:path.join(skill,'container_tools/inspect_presentation_layout_geometry.py'),layoutArgs:['--expected-slide-size-emu','15240000,8572500','--validate-bullet-geometry','--validate-heading-fit'],explicitTotalSlideCount:1,fontPolicy:{basis:'design',families:['Microsoft YaHei']},verifyArtifactToolImport:true,receiptPath:path.join(build,'validation.json')}));


