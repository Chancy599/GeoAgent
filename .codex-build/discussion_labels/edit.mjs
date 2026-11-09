import fs from 'node:fs/promises';
import {PresentationFile,FileBlob} from '@oai/artifact-tool';
const root='D:/Users/18217/Desktop/我的文件/GeoAgent',dir=root+'/.codex-build/discussion_labels';
await fs.copyFile(root+'/1102讨论.pptx',dir+'/original.pptx');
const p=await PresentationFile.importPptx(await FileBlob.load(dir+'/original.pptx'));
for(let i=0;i<3;i++){const b=await p.export({slide:p.slides.items[i],format:'png',scale:1});await fs.writeFile(dir+`/before-${i+1}.png`,new Uint8Array(await b.arrayBuffer()));}
const[a,b]=p.slides.items;
function text(slide,name,value,x,y,w,h,size=23,color='#243447',bold=false){let s=slide.shapes.items.find(s=>s.name===name);if(!s)s=slide.shapes.add({geometry:'textbox',name,position:{left:x,top:y,width:w,height:h},fill:'none',line:{fill:'none',width:0}});s.position={left:x,top:y,width:w,height:h};s.text=value;s.text.style={typeface:'Microsoft YaHei',fontSize:size,color,bold,insets:0,autoFit:'none',verticalAlignment:'top'};return s;}
text(a,'step2detail','约束投影（最小二乘求解），让接近垂直的边更规整。\n保留 D 与 AB、EC 的相交关系，允许坐标小幅调整。',745,380,800,62);
text(a,'least-squares','min ‖W(q−q₀)‖₂²    s.t. c(q)=0',745,442,800,34,26,'#102B46');
text(a,'least-squares-note','q₀ 为原始坐标；W 保护位移和长度；c 为几何约束。',745,478,800,29,21);
text(a,'step3','03  限制改动，避免破坏原图',745,514,800,38,27,'#102B46',true);
text(a,'step3detail','对比调整前后的点位和边长，限制移动和长度变化，\n同时检查交点是否仍在线段内；超出范围就撤回这次调整。',745,557,800,62);
for(const nm of ['step2','step4','step4detail']){const z=a.shapes.items.find(s=>s.name===nm);const pz=z.position;z.position={left:pz.left,top:pz.top,width:Math.min(pz.width,1545-pz.left),height:pz.height};}
// 04 remains byte-for-byte as edited by the user when merged back into the package.
b.images.items[0].frame={left:55,top:205,width:158,height:141};
b.images.items[1].frame={left:225,top:205,width:158,height:141};
b.images.add({blob:new Uint8Array(await fs.readFile(dir+'/assets/match_label_templates.png')),contentType:'image/png',alt:'772标签检测候选图（当前工具重跑）',fit:'contain',position:{left:395,top:205,width:158,height:141}});
text(b,'origcap','圆／弧候选',55,356,158,30,21,'#526575');
text(b,'cvcap','线段检测',225,356,158,30,21,'#526575');
text(b,'labelcap','标签检测',395,356,158,30,21,'#526575');
text(b,'cvdetail','CV Tools 输出圆、线段和标签候选。\nSupervisor 对照原图：主圆有完整笔画，\n保留为完整圆；另一候选只贴合局部片段，\n原图无对应圆弧，因此不绘制。\n标签有遗漏时，再结合原图补核。',55,407,520,150,23);
text(b,'gesdetail','Geometry 子 Agent 将确认的图元整理为\n几何骨架：哪些点相连、在哪里相交，\n以及圆心、半径、标签与点的对应关系。\n把骨架和未决冲突写入 GES，供生成使用。',55,590,520,125,23);
await(await PresentationFile.exportPptx(p)).save(dir+'/authored.pptx');
console.log('Authored formula and label panel; kept user 04 and framework.');
