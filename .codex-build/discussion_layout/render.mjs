import fs from 'node:fs/promises';
import {PresentationFile,FileBlob} from '@oai/artifact-tool';
const d='D:/Users/18217/Desktop/我的文件/GeoAgent/.codex-build/discussion_layout';
const p=await PresentationFile.importPptx(await FileBlob.load(d+'/candidate.pptx'));
for(let i=0;i<p.slides.items.length;i++){const b=await p.export({slide:p.slides.items[i],format:'png',scale:1});await fs.writeFile(d+`/after-${i+1}.png`,new Uint8Array(await b.arrayBuffer()));}
