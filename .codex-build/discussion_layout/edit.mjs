import fs from 'node:fs/promises';
import {PresentationFile,FileBlob} from '@oai/artifact-tool';
const d='D:/Users/18217/Desktop/我的文件/GeoAgent/.codex-build/discussion_layout';
const p=await PresentationFile.importPptx(await FileBlob.load(d+'/original.pptx'));
const [a,b,c]=p.slides.items;
const plans={};
function shape(s,id,x,y,w,h,size,color='#243447',bold=false,align='left'){
 const z=s.shapes.items.find(z=>z.id===String(id));
 z.position={left:x,top:y,width:w,height:h};
 if(size)z.text.style={typeface:'Microsoft YaHei',fontSize:size,color,bold,insets:0,autoFit:'none',verticalAlignment:'top',alignment:align};
 return z;
}
function img(s,id,x,y,w,h){s.images.items.find(z=>z.id===String(id)).frame={left:x,top:y,width:w,height:h};}
function geo(s,id,x,y,w,h){shape(s,id,x,y,w,h);}
for(const s of p.slides.items){const t=s.shapes.items.find(x=>x.name==='title');shape(s,t.id,55,35,1490,65,46,'#102B46',true);}
shape(a,2,55,107,1490,35,26,'#526575');
shape(a,25,55,316,710,32,22,'#526575');
shape(a,36,55,832,1490,34,23,'#526575',false,'center');
// Keep the native framework. Align the main flow and its vertical branches.
for(const id of [10,11,12,13,14]){const z=a.shapes.items.find(z=>z.id===String(id));geo(a,id,z.position.left,440,z.position.width,130);}
for(const id of [15,16,17,18,26]){const z=a.shapes.items.find(z=>z.id===String(id));geo(a,id,z.position.left,505,z.position.width,0);}
geo(a,19,800,305.1333333333,0,60);
for(const id of [21,22,23,24]){const z=a.shapes.items.find(z=>z.id===String(id));geo(a,id,z.position.left,365.1333333333,0,74.8666666667);}
geo(a,27,1570,330.1333333333,0,174.8666666667);
geo(a,31,55,710,1490,100);
for(const id of [32,33,34,35]){const z=a.shapes.items.find(z=>z.id===String(id));geo(a,id,z.position.left,570,0,140);}
// Evidence / generation / repair columns. Preserve all supplied wording.
shape(b,25,55,105,1490,32,24,'#526575');
for(const [id,x,w] of [[3,55,530],[4,625,440],[5,1105,440]])shape(b,id,x,163,w,38,26,'#116778',true);
for(const [id,x] of [[6,55],[7,230],[27,405]])img(b,id,x,221,165,147.25);
for(const [id,x] of [[8,55],[9,230],[26,405]])shape(b,id,x,383,165,30,21,'#526575',false,'center');
shape(b,2,55,432,530,58,22);
shape(b,14,55,511,530,146,22);
shape(b,15,55,691,530,145,22);
// Use deliberate phrase breaks without changing wording.
b.shapes.items.find(z=>z.id==='15').text='Geometry Agent\n将确认的图元整理为几何骨架：\n哪些点相连、在哪里相交，以及圆心、半径、\n标签与点的对应关系；\n把骨架写入 GES，供生成使用';
img(b,10,676,219,330,293.802);img(b,11,1156,219,330,293.802);
shape(b,12,625,527,440,34,23,'#AD4D2E',true);
shape(b,13,1105,527,440,34,23,'#116778',true);
shape(b,16,625,582,440,125,22);
shape(b,17,1105,582,440,151,22);
shape(b,19,625,745,440,30,22,'#AD4D2E',true);
shape(b,20,1105,745,440,30,22,'#116778',true);
img(b,21,665,784,330,80);img(b,22,1145,784,330,80);
// Repair example: align the steps and reserve a full formula row.
img(c,3,95,155,500,259.5628);
shape(c,6,700,175,845,40,27,'#102B46',true);
shape(c,7,700,223,845,70,23);
shape(c,8,700,315,845,40,27,'#102B46',true);
shape(c,9,700,363,845,66,23);
shape(c,29,700,436,845,40,28,'#102B46');
shape(c,10,700,506,845,40,27,'#102B46',true);
shape(c,11,700,554,845,66,23);
shape(c,21,700,643,845,40,27,'#102B46',true);
shape(c,22,700,691,845,40,23);
shape(c,12,120,458,500,35,25,'#116778',true);
shape(c,14,55,754,1490,34,23,'#116778',true);
geo(c,27,65,792,650,85);geo(c,28,820,750,690,130);
// Export authoring, while retaining the source package's math and media in the next step.
await(await PresentationFile.exportPptx(p)).save(d+'/authored.pptx');
console.log('Layout authored.');
