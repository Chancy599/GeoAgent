import fs from 'node:fs/promises';
import {PresentationFile,FileBlob} from '@oai/artifact-tool';
const root='D:/Users/18217/Desktop/我的文件/GeoAgent';
const dir=root+'/.codex-build/discussion_agents_framework';
await fs.copyFile(root+'/1102讨论.pptx',dir+'/original.pptx');
const p=await PresentationFile.importPptx(await FileBlob.load(dir+'/original.pptx'));
for(let i=0;i<2;i++){const b=await p.export({slide:p.slides.items[i],format:'png',scale:1});await fs.writeFile(dir+`/before-${i+1}.png`,new Uint8Array(await b.arrayBuffer()));}
const [a,b]=p.slides.items;
function text(slide,name,value,x,y,w,h,size=24,color='#243447',bold=false){
 let s=slide.shapes.items.find(s=>s.name===name);
 if(!s)s=slide.shapes.add({geometry:'textbox',name,position:{left:x,top:y,width:w,height:h},fill:'none',line:{fill:'none',width:0}});
 s.position={left:x,top:y,width:w,height:h};s.text=value;s.text.style={typeface:'Microsoft YaHei',fontSize:size,color,bold,insets:0,autoFit:'none',verticalAlignment:'top'};return s;
}
text(a,'step1','01  解析主体几何，筛选数值候选',783,202,760,38,27,'#102B46',true);
text(a,'step1detail','识别出 5 条线段以及 5 个顶点\n按 0.5° 容差筛出 AB⊥AC、EB⊥EC 两组近垂直候选。',783,247,760,75,23);
text(a,'step2','02  用约束投影，一起微调顶点',580,336,970,38,27,'#102B46',true);
text(a,'step2detail','采用约束投影（最小二乘求解），让接近垂直的边更规整。\n保留 D 与 AB、EC 的相交关系；D 的坐标也允许小幅调整。',580,380,970,75,23);
text(a,'step3','03  限制改动，避免破坏原图',580,487,970,38,27,'#102B46',true);
text(a,'step3detail','对比调整前后的点位和边长，限制移动和长度变化，\n同时检查交点是否仍在线段内；超出范围就撤回这次调整。',580,530,970,75,23);
text(a,'step4','04  写回代码，再核对一次',580,620,970,38,27,'#102B46',true);
text(a,'step4detail','把修改后的坐标写回代码，再读回来检查。\n确认垂直关系、交点连接和整体形状都符合要求后保留结果。',580,663,970,75,23);
text(a,'metrics-heading','两角变化与整体误差 ↓',60,485,475,35,25,'#116778',true);
const table=a.tables.items[0];table.insertRows({index:1,count:2});table.position={left:60,top:528,width:475,height:198};
const values=[['指标','修复前','修复后'],['角 A（°）','90.21884','89.99999'],['角 E（°）','90.15180','89.99242'],['角度 MAE（°）','0.1081','0.0114'],['比例 MRE（%）','0.1251','0.0458']];
for(let r=0;r<5;r++){table.rows[r].height=39.6;for(let c=0;c<3;c++){const cell=table.getCell(r,c);cell.value=values[r][c];cell.fill=r===0?'#116778':'#FFFFFF';cell.text.style={typeface:'Microsoft YaHei',fontSize:22,color:r===0?'#FFFFFF':'#243447',bold:r===0,alignment:c===0?'left':'center'};}}
table.borders.assign({style:'solid',fill:'#D8E2E9',width:1});

text(b,'role-summary','Supervisor 是主 Agent；Geometry、TikZ、Critic 是三个子 Agent；CV Tools 提供测量。',55,96,1490,30,23,'#526575');
text(b,'phase1','01  主 Agent 调度测量与整理',55,135,520,40,28,'#116778',true);
text(b,'phase2','02  TikZ 生成，Critic 检查',590,135,480,40,28,'#116778',true);
text(b,'phase3','03  主 Agent 安排修图与复核',1100,135,465,40,28,'#116778',true);
text(b,'cvdetail','Supervisor 调用 CV Tools 测量圆、线段\n和标签，并查看原图核验圆候选。\n主圆有完整圆周笔画；另一候选只贴合\n局部片段，原图无对应圆弧，因此不绘制。',55,440,520,120,23);
text(b,'gesdetail','Geometry 子 Agent 整理圆心、半径、\n顶点和点线关系，并记录不确定之处。\n这些信息写入 GES，供后续生成使用。',55,612,520,95,23);
text(b,'v1detail','TikZ 子 Agent 根据 GES 生成图形代码。\n程序完成后修复、编译和渲染，\n再交给 Critic 子 Agent 对照原图检查。\n本例后修复未改坐标，主体已画对。',590,535,480,125,23);
text(b,'v2detail','Critic 子 Agent 发现端点伸出了圆周。\nSupervisor 将意见交给 TikZ 子 Agent。\n按圆心、半径及选定方向重设端点，\n让线段收在圆周上；重新编译后，\n再由 Critic 检查，确认问题已解决。',1100,535,465,135,22);

const s=p.slides.add();s.background.fill='#FFFFFF';
text(s,'title','GeoAgent 框架与处理闭环',55,35,1490,65,46,'#102B46',true);
text(s,'subtitle','一个主 Agent 负责调度，三个子 Agent 分工；CV Tools 提供测量，程序负责修复与编译。',55,107,1490,35,25,'#526575');
function box(name,value,x,y,w,h,fill='#F2F7F8',color='#102B46',size=27){const z=s.shapes.add({geometry:'rect',name,position:{left:x,top:y,width:w,height:h},fill,line:{fill:'#AFC6CD',width:1.5}});z.text=value;z.text.style={typeface:'Microsoft YaHei',fontSize:size,color,bold:false,alignment:'center',verticalAlignment:'middle',insets:12};return z;}
function line(x1,y1,x2,y2,arrow=false,color='#708996',dash=false){let x=Math.min(x1,x2),y=Math.min(y1,y2);const rev=(x2<x1)||(y2<y1);return s.shapes.add({geometry:'connector',kind:'straight',position:{left:x,top:y,width:Math.abs(x2-x1),height:Math.abs(y2-y1)},line:{fill:color,width:2,style:dash?'dashed':'solid'},...(arrow?{[rev?'head':'tail']:{type:'triangle',width:'med',length:'med'}}:{})});}
const input=box('input','输入几何图片',55,177,250,85,'#FFFFFF');
const supervisor=box('supervisor','Supervisor｜主 Agent\n选择下一步，分派任务，汇总结果',550,165,500,110,'#116778','#FFFFFF',28);
const output=box('output','输出最佳版本\nTikZ · PDF · PNG',1280,177,265,85,'#FFFFFF','#102B46',25);
line(305,220,550,220,true);text(s,'inputlabel','读取原图',355,185,160,30,21,'#526575');
line(1050,220,1280,220,true);text(s,'outputlabel','选择并归档',1090,185,170,30,21,'#526575');
const cv=box('cv','CV Tools\n线段、圆弧、标签\n本地测量',55,420,260,130,'#FFFFFF','#102B46',24);
const geo=box('geo','Geometry Agent\n子 Agent：几何整理',365,420,260,130,'#EAF4F5','#102B46',24);
const tikz=box('tikz','TikZ Agent\n子 Agent：生成 / 修图',675,420,260,130,'#EAF4F5','#102B46',24);
const program=box('program','程序处理\n约束后修复\n编译 / 渲染',985,420,260,130,'#FFFFFF','#102B46',24);
const critic=box('critic','Critic Agent\n子 Agent：图像检查',1295,420,250,130,'#EAF4F5','#102B46',24);
for(const [x1,x2]of [[315,365],[625,675],[935,985],[1245,1295]])line(x1,485,x2,485,true,'#116778');
line(800,275,800,335);line(185,335,1420,335);for(const x of [185,495,805,1420])line(x,335,x,420,true);
text(s,'dispatchlabel','调度 CV 工具与三个子 Agent，并接收结果',340,359,700,34,23,'#526575').fill='#FFFFFF';
line(1545,485,1570,485,false,'#B36746');line(1570,485,1570,300,false,'#B36746');line(1050,300,1570,300,false,'#B36746');line(1050,300,1050,275,true,'#B36746');
text(s,'feedbacklabel','有问题：反馈主 Agent，安排修图或重测',1090,268,450,28,20,'#A34E32');
const ges=box('ges','GES｜共享几何证据状态\n坐标、标签、点线关系、冲突与版本记录',55,670,1490,100,'#F4F7FA','#102B46',27);
for(const x of [185,495,805,1420])line(x,550,x,670,true,'#AFC0CB',true);
text(s,'geslabel','测量、整理、生成和检查结果写入共享状态，供后续步骤读取',385,601,900,35,23,'#526575').fill='#FFFFFF';
text(s,'legend','实线：主要处理与调度流程     虚线：共享状态读写     橙线：检查后的反馈闭环',55,825,1490,35,23,'#526575');
s.speakerNotes.text='依据geoagent/orchestration/runner.py、agents/supervisor.py、agents/geometry_agent.py、agents/tikz_agent.py、agents/critic_agent.py和cv_tools/registry.py绘制概略框架。一个Supervisor主Agent调用本地CV工具、Geometry、TikZ、Critic子Agent；共享GES持有测量、标签关系、冲突、代码版本和检查。TikZ生成代码后，Runner自动处理坐标契约和确定性后修复，再编译/渲染；Critic比较原图与结果，Supervisor决定是否重测/修图及选择最佳版本。框图横向箭头表示主要逻辑次序，实际由Supervisor动态调度。坐标契约未单列，包含在程序处理。';
await(await PresentationFile.exportPptx(p)).save(dir+'/authored.pptx');
console.log('authored three slides');
