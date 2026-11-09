import fs from 'node:fs/promises';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
import {PresentationFile,FileBlob} from '@oai/artifact-tool';
const root='D:/Users/18217/Desktop/我的文件/GeoAgent',dir=root+'/.codex-build/discussion_agents_framework';
const skill='C:/Users/18217/.codex/plugins/cache/openai-primary-runtime/presentations/26.1026.10807/skills/presentations';
const p=await PresentationFile.importPptx(await FileBlob.load(dir+'/candidate.pptx'));
for(let i=0;i<p.slides.items.length;i++){const b=await p.export({slide:p.slides.items[i],format:'png',scale:1});await fs.writeFile(dir+`/after-${i+1}.png`,new Uint8Array(await b.arrayBuffer()));}
const {finalizePresentation}=await import(pathToFileURL(path.join(skill,'container_tools/artifact_tool_utils.mjs')).href);
const r=await finalizePresentation({workspaceDir:root,candidatePath:dir+'/candidate.pptx',finalPath:root+'/deliverables/pipeline_cases/1102_discussion_agents_framework_final.pptx',pythonExecutable:'C:/Users/18217/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe',integrityValidatorPath:path.join(skill,'container_tools/inspect_presentation_package_integrity.py'),layoutValidatorPath:path.join(skill,'container_tools/inspect_presentation_layout_geometry.py'),layoutArgs:['--expected-slide-size-emu','15240000,8572500','--validate-heading-fit','--require-native-table-slide','1'],explicitTotalSlideCount:3,requiredNativeTableOwnerSlides:[1],verifyArtifactToolImport:true,receiptPath:dir+'/validation-final.json'});
console.log(JSON.stringify({path:r.finalPath,status:r.packageIntegrity.status,slides:r.presentationLayout.slide_count,warnings:r.presentationLayout.warning_count}));
