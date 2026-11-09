import fs from 'node:fs/promises';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
import {Presentation, PresentationFile} from '@oai/artifact-tool';

const root='D:/Users/18217/Desktop/我的文件/GeoAgent';
const build=path.join(root,'.codex-build/pipeline928');
const skill='C:/Users/18217/.codex/plugins/cache/openai-primary-runtime/presentations/26.1026.10807/skills/presentations';
const presentation=Presentation.create({slideSize:{width:1600,height:900}});
const slide=presentation.slides.add();
slide.background.fill='#FFFFFF';
function text(name,value,x,y,w,h,size=26,color='#243447',bold=false){
 const s=slide.shapes.add({geometry:'textbox',name,position:{left:x,top:y,width:w,height:h},fill:'none',line:{fill:'none',width:0}});
 s.text=value;s.text.style={typeface:'Microsoft YaHei',fontSize:size,color,bold,insets:0,autoFit:'none',verticalAlignment:'top'};return s;
}
text('title','928：几何重建与约束后修复',55,35,1480,65,46,'#102B46',true);
text('subtitle','七个标签点 · 八条直线 · 两版 TikZ；先修正标签位置，再核验几何约束',58,108,1480,38,25,'#526575');
slide.images.add({blob:new Uint8Array(await fs.readFile(path.join(root,'data/test/image/928_q_fig4.png'))),contentType:'image/png',alt:'928原图：六边形F-E-D-C-B-A，EA与FC相交于K',fit:'contain',position:{left:65,top:165,width:450,height:402}});
text('image-caption','原图 928_q_fig4',60,574,470,35,23,'#526575');
text('steps-heading','处理流程',580,165,920,42,30,'#116778',true);
text('step1','01  CV 测量 → GES',580,220,940,38,27,'#102B46',true);
text('step1detail','圆候选 0 个、线段 8 条；绑定 A–F、K，整理外框与交点关系。',580,261,940,43,24);
text('step2','02  TikZ 生成 → 编译 → Critic → 局部修图',580,320,950,40,27,'#102B46',true);
text('step2detail','v1 主体正确；Critic 指出 K 在交点左下方，修至右下方。\nv2 再次编译并复核，评分 0.93；仍有轻微标签偏移。',580,364,950,78,24);
text('step3','03  所选 v2 → 确定性后修复 → 导出复验',580,458,950,40,27,'#102B46',true);
text('step3detail','联合处理 8 组近平行／近垂直关系，保护 K 的在线关系。\nBC∥EF 偏差：0.4831° → 0.0025°；最大点位移动为对角线的 0.097%。',580,502,955,80,24);
text('metrics-heading','同一批测量项的参考误差 ↓',60,625,490,38,25,'#116778',true);
const tab=slide.tables.add({rows:3,columns:3,left:60,top:675,width:475,height:135,columnWidths:[210,132,133],values:[['指标','修复前','修复后'],['角度 MAE（°）','0.1340','0.0939'],['比例 MRE（%）','0.4547','0.2746']]});
tab.borders.assign({fill:'#D8E2E9',width:1,style:'solid'});
for(let r=0;r<3;r++)for(let c=0;c<3;c++){const cell=tab.getCell(r,c);cell.text.style={typeface:'Microsoft YaHei',fontSize:23,color:r===0?'#FFFFFF':'#243447',bold:r===0,alignment:c===0?'left':'center'};cell.fill=r===0?'#116778':'#FFFFFF';}
text('formula-heading','两项误差的计算',580,615,940,42,28,'#116778',true);
text('angle-formula','MAEθ = (1/Nθ) ∑ᵢ |θ̂ᵢ − θᵢ|    （单位：度）',580,665,950,43,29,'#102B46');
text('angle-definition','θ = arccos[(u·v)/(‖u‖‖v‖)] × 180/π；u、v 为共顶点边向量。',580,711,960,38,22);
text('ratio-formula','MREᵣ = (100/Nᵣ) ∑ⱼ |r̂ⱼ/rⱼ − 1|    （单位：%）',580,759,960,43,29,'#102B46');
text('ratio-definition','r = ‖pₐ − pᵦ‖ / ‖p𝒸 − p𝒹‖；带帽值为预测，未带帽值为参考。',580,805,965,36,22);
text('footnote','28 个角度、32 个比例，前后均完整可测。流程据历史日志；后修复为当前同批 v2 的离线复验，未重新调用模型。',60,856,1470,28,19,'#637483');
slide.speakerNotes.text=`来源均为项目本地档案。原图：data/test/image/928_q_fig4.png；历史调度：outputs/ablations/no_post_repair/stem/928_q_fig4/state.json；当前修复：outputs/ours/stem/928_q_fig4/constraint_repair.json；参考评测：results/latest/structure.json（groups.raw/post.per_stem.928_q_fig4）。\n历史：9步，2版TikZ；CV检测8条线、无圆，Geometry提交15对象/13关系/1冲突。Critic指出K标签左右位置问题，第二版仍有约5px排版偏移，评分保持0.93，不能声称分数上升。\n当前后修复对同批所选v2处理8组关系；最大位移0.0009676288×对角线，最大边长相对变化0.0027605539。MAE由0.1339839314降至0.0938887479度，MRE由0.4546906808%降至0.2745565501%。同样28角度与32比例，覆盖率100%。\n修复不读取参考数据；公式中的参考坐标仅供离线评测。候选关系方向偏差不等同于相对于参考的角度MAE。当前坐标契约功能不在这份历史生成记录中，不能据此宣称新CV直接传递机制的效果。`;
await fs.writeFile(path.join(build,'slide-1.png'),new Uint8Array(await (await presentation.export({slide,format:'png',scale:1})).arrayBuffer()));
const candidate=path.join(build,'candidate.pptx');
await (await PresentationFile.exportPptx(presentation)).save(candidate);
const {finalizePresentation}=await import(pathToFileURL(path.join(skill,'container_tools/artifact_tool_utils.mjs')).href);
const result=await finalizePresentation({workspaceDir:root,candidatePath:candidate,finalPath:path.join(root,'deliverables/pipeline928/GeoAgent_928_pipeline.pptx'),pythonExecutable:'C:/Users/18217/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe',integrityValidatorPath:path.join(skill,'container_tools/inspect_presentation_package_integrity.py'),layoutValidatorPath:path.join(skill,'container_tools/inspect_presentation_layout_geometry.py'),layoutArgs:['--expected-slide-size-emu','15240000,8572500','--validate-heading-fit','--require-native-table-slide','1'],explicitTotalSlideCount:1,requiredNativeTableOwnerSlides:[1],fontPolicy:{basis:'design',families:['Microsoft YaHei']},verifyArtifactToolImport:true,receiptPath:path.join(build,'validation.json')});
console.log(JSON.stringify(result));
