import fs from 'node:fs/promises';
import {PresentationFile,FileBlob} from '@oai/artifact-tool';
const d='D:/Users/18217/Desktop/我的文件/GeoAgent/.codex-build/discussion_layout';
const p=await PresentationFile.importPptx(await FileBlob.load(d+'/original.pptx'));
for(let i=0;i<p.slides.items.length;i++){
 const s=p.slides.items[i];
 const b=await p.export({slide:s,format:'png',scale:1});await fs.writeFile(d+`/before-${i+1}.png`,new Uint8Array(await b.arrayBuffer()));
 console.log(i+1,JSON.stringify({shapes:s.shapes.items.map(x=>({id:x.id,name:x.name,position:x.position,text:x.text.toString()})),images:s.images.items.map(x=>({id:x.id,frame:x.frame}))}));
}
