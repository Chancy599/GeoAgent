import path from 'node:path';
import {pathToFileURL} from 'node:url';
const root='D:/Users/18217/Desktop/我的文件/GeoAgent';
const skill='C:/Users/18217/.codex/plugins/cache/openai-primary-runtime/presentations/26.1026.10807/skills/presentations';
const {finalizePresentation}=await import(pathToFileURL(skill+'/container_tools/artifact_tool_utils.mjs').href);
const r=await finalizePresentation({workspaceDir:root,candidatePath:root+'/outputs/presentation_build/flow/candidate.pptx',finalPath:root+'/outputs/presentations/GeoAgent_三页汇报_流程图版.pptx',pythonExecutable:'C:/Users/18217/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe',integrityValidatorPath:skill+'/container_tools/inspect_presentation_package_integrity.py',layoutValidatorPath:skill+'/container_tools/inspect_presentation_layout_geometry.py',layoutArgs:['--expected-slide-size-emu','15240000,8572500','--validate-bullet-geometry','--validate-heading-fit','--require-native-table-slide','2'],explicitTotalSlideCount:3,requiredNativeTableOwnerSlides:[2],fontPolicy:{basis:'design',families:['Microsoft YaHei','微软雅黑']},verifyArtifactToolImport:true,receiptPath:root+'/outputs/presentation_build/flow/validation.json'});
console.log(JSON.stringify({finalPath:r.finalPath,layout:r.presentationLayout}));


