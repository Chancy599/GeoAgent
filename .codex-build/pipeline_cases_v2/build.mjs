import fs from 'node:fs/promises';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
import {PresentationFile,FileBlob} from '@oai/artifact-tool';
const root='D:/Users/18217/Desktop/我的文件/GeoAgent';
const build=path.join(root,'.codex-build/pipeline_cases_v2');
const assets=path.join(build,'assets');
const skill='C:/Users/18217/.codex/plugins/cache/openai-primary-runtime/presentations/26.1026.10807/skills/presentations';
const presentation=await PresentationFile.importPptx(await FileBlob.load(path.join(root,'deliverables/pipeline928/GeoAgent_928_pipeline.pptx')));
const s1=presentation.slides.items[0];
function tx(slide,name,value,x,y,w,h,size=25,color='#243447',bold=false){
 let s=slide.shapes.items.find(z=>z.name===name);
 if(!s)s=slide.shapes.add({geometry:'textbox',name,position:{left:x,top:y,width:w,height:h},fill:'none',line:{fill:'none',width:0}});
 s.position={left:x,top:y,width:w,height:h};s.text=value;
 s.text.style={typeface:'Microsoft YaHei',fontSize:size,color,bold,insets:0,autoFit:'none',verticalAlignment:'top'};return s;
}
function one(...args){return tx(s1,...args);}
one('title','928：几何约束修复的四个步骤',55,35,1490,65,46,'#102B46',true);
one('subtitle','输入：已生成的 TikZ 坐标与绘制线段；输出：通过结构保护与精度复验的修复代码',58,108,1475,38,25,'#526575');
s1.images.items[0].frame={left:80,top:155,width:405,height:362};
one('image-caption','原图：六边形与交点 K',60,518,475,36,23,'#526575');
one('steps-heading','约束来自生成代码，不读取参考答案',580,158,950,40,29,'#116778',true);
one('step1','01  解析主体几何，筛选数值候选',580,211,950,38,27,'#102B46',true);
one('step1detail','提取 7 个点、8 条线段；按 0.5° 容差得到 5 组近平行、\n3 组近垂直候选，例如 BC∥EF、AF∥CD、AE⊥FC。',580,254,950,70,24);
one('step2','02  联合求解最小位移投影',580,339,950,38,27,'#102B46',true);
one('step2detail','以输入坐标为锚点迭代线性化求解：平行 u×v=0，垂直 u·v=0。\n保持 K 在 EA、FC 上，并加入点对长度保护（权重 0.01）。',580,382,960,70,24);
one('step3','03  用结构限制筛选解，再写回代码',580,468,950,38,27,'#102B46',true);
one('step3detail','单点位移≤对角线 0.5%，已有边长变化≤1%，点在线段内顺序不变；\n若冲突或超限，移除较弱候选重解；写回时统一保留 3 位小数。',580,511,965,70,24);
one('step4','04  回读实际导出坐标并复验',580,597,950,38,27,'#102B46',true);
one('step4detail','重查方向残差、位移与边长；失败则回退。此例 BC∥EF 偏差\n0.4831° → 0.0025°；最大点位移动 0.097%，边长变化 0.276%。',580,640,960,70,24);
one('metrics-heading','相同测量项的参考误差 ↓',60,571,480,38,25,'#116778',true);
const tab=s1.tables.items[0];tab.position={left:60,top:617,width:475,height:120};
one('formula-heading','离线评测公式（参考值仅用于评测）',60,755,1470,36,25,'#116778',true);
one('angle-formula','MAEθ = (1/Nθ) ∑ᵢ |θ̂ᵢ − θᵢ|    （°）',60,797,720,40,27,'#102B46');
one('angle-definition','θ = arccos[(u·v)/(‖u‖‖v‖)] × 180/π',60,839,710,29,21,'#526575');
one('ratio-formula','MREᵣ = (100/Nᵣ) ∑ⱼ |r̂ⱼ/rⱼ − 1|    （%）',810,797,735,40,27,'#102B46');
one('ratio-definition','r = ‖pₐ − pᵦ‖ / ‖p𝒸 − p𝒹‖；带帽值为预测值。',810,839,735,29,21,'#526575');
one('footnote','本例前后均测得 28 个角度、32 个比例；方向残差与相对于参考的 MAE 是不同指标。',60,877,1480,20,16,'#637483');
s1.speakerNotes.text='928仅介绍确定性几何修复。来源：outputs/ours/stem/928_q_fig4/constraint_repair.json、geoagent/state/tikz_repair.py、optimize_relations.py、relation_candidates.py，及results/latest/structure.json。\n解析生成TikZ：7命名点、8线段；5parallel+3perpendicular候选。候选仅来自程序数值几何。保护K在EA及FC上的两项incidence。将坐标按图形对角线归一化，以输入位置为锚点作最小位移投影；全点对长度保护权重0.01。迭代线性化并以最小二乘处理冗余约束，方向约束构成生成森林以去除依赖环。若求解失败或超限，按初始方向误差移除较弱候选。\n输出3位小数，实际回读后重新检验位移、边长、点序和方向残差；编译失败时也回退。实际最大位移0.09676288%对角线，边长最大变化0.27605539%。BC∥EF方向偏差0.4830698845→0.0024657504度。参考MAE：0.1339839314→0.0938887479度；MRE：0.4546906808→0.2745565501%，前后同样28角度/32比例，覆盖率100%。本页不描述其他Agent环节。';

const s2=presentation.slides.add();s2.background.fill='#FFFFFF';
const two=(...args)=>tx(s2,...args);
async function img(slide,file,alt,x,y,w,h,crop){return slide.images.add({blob:new Uint8Array(await fs.readFile(file)),contentType:'image/png',alt,fit:crop?'cover':'contain',position:{left:x,top:y,width:w,height:h},...(crop?{crop}:{})});}
two('title','772：Critic 驱动的重建与局部精修',55,35,1490,65,46,'#102B46',true);
two('flow','Supervisor 调度：CV → 几何证据状态 GES → TikZ → 后修复 → 编译／渲染 → Critic → 按需修图',58,108,1490,38,25,'#526575');
two('phase1','01  测量图元并整理几何证据',55,164,500,42,28,'#116778',true);
two('phase2','02  生成、校验，交给 Critic',590,164,455,42,28,'#116778',true);
two('phase3','03  局部修改，再次编译复核',1100,164,455,42,28,'#116778',true);
await img(s2,path.join(root,'data/test/image/772_q_fig2.png'),'772原图',55,215,230,205);
await img(s2,path.join(assets,'cv/detect_lines.png'),'当前CV工具重跑的真实线段检测叠图',310,215,230,205);
two('origcap','原图',55,428,230,30,22,'#526575');
two('cvcap','CV 线段检测叠图',310,428,250,30,22,'#526575');
await img(s2,path.join(assets,'772_v1.png'),'档案v1代码重新编译的初稿，端点越出圆周',650,212,340,303);
await img(s2,path.join(assets,'772_v2.png'),'档案v2代码重新编译的修图结果，端点回到圆周',1155,212,340,303);
two('v1cap','v1：主体正确，端点略过圆周',602,520,445,34,23,'#A34E32',true);
two('v2cap','v2：端点收回圆周，主体保持',1103,520,445,34,23,'#116778',true);
two('cvdetail','CV：检测 6 条直线、2 个圆候选；\n主圆 O≈(271.8,302.2)，r≈118.4 px。\n提取标签后查看原图，确认完整圆及线型。',55,485,500,105,24);
two('gesdetail','Geometry：整理为 14 个对象、10 条关系，\n明确三角形、圆、内部线段与标签位置。\nGES 保留来源、候选和冲突，供生成使用。',55,601,505,105,24);
two('v1detail','TikZ 根据证据生成连接、样式与坐标。\n编译和基础校验通过，得到 v1。\n本例后修复无候选，保留坐标；\n圆线连接细节交给 Critic 检查。',590,571,465,120,24);
two('v2detail','Critic 指出两条斜线及竖线上端越界。\nTikZ 按圆心、半径修改端点，再编译。\n复核：0.90 → 0.93，无剩余问题；\n选择 v2，输出源码、PDF、PNG。',1100,571,465,120,24);
two('effect','Critic 的作用：发现“主体已正确”\n之后仍存在的圆线连接瑕疵。\n端点径向偏差：约 4.5–6.1 px\n→ 约 0–0.013 px（按源码复算）。',55,727,505,128,25,'#102B46',true);
two('zoom1','圆顶局部：修复前',625,708,380,32,23,'#A34E32',true);
two('zoom2','圆顶局部：修复后',1130,708,380,32,23,'#116778',true);
const crop={left:0.42,right:0.42,top:0.32,bottom:0.58};
await img(s2,path.join(assets,'772_v1.png'),'圆顶连接处放大，v1有越界尾巴',625,745,290,110,crop);
await img(s2,path.join(assets,'772_v2.png'),'圆顶连接处放大，v2去除越界尾巴',1130,745,290,110,crop);
two('footnote','图示为历史案例回放：CV 叠图由当前工具重跑，v1/v2 由档案源码重编译；M/N 位置仍属估计，切点未独立核验。',55,875,1490,23,17,'#637483');
s2.speakerNotes.text='772历史10步流程：detect_lines(6)→detect_circles(2)→bind_point_labels→inspect_image→Geometry(14对象10关系2冲突)→TikZ generate/compile v1→Critic v1(score0.90,must_repair=true)→TikZ repair/compile v2→Critic v2(score0.93,must_repair=false,issues=[])→finish。来源：outputs/ablations/no_post_repair/stem/772_q_fig2/state.json及critic_report.json。当前后修复来源：outputs/ours/stem/772_q_fig2/constraint_repair.json，reason=no_candidates。\n两圆候选中的主圆circle_01完整圆，O=(271.78,302.15)px，r=118.38px；circle_02为局部候选，Critic认为可能重复检测。Geometry最初要求端点在圆上，但生成指令继续携带原始略长线段端点，v1保留了越界。Critic定位圆周附近端点，TikZ在v2按r=2.015 TikZ单位与O=(4.626,3.145)重写端点；主体、标签未改。\n本页CV叠图是当前detect_lines对同一原图的确定性重跑，不是历史执行截图。v1/v2图片均从档案保存的原始TeX重新编译，并用frame_like_original置于同一画布，不重新调用模型。圆顶局部为同一图的原生裁切放大。径向残差按代码坐标直接计算(|P-O|-r)/0.017021：v1各端点Vt=4.876px，D1a=6.090px,D1b=4.511px,D2a=5.019px,D2b=5.581px；v2为0或约0.013px。源码变换比例及3位小数造成微小误差。这是内部端点相对于生成圆周的残差，不是参考数据集角度/长度比指标，Critic分数为启发式。\n限制：M、N仅按标签大致位置估计为AB上的点，相切未经独立核验。当前代码额外包含可靠CV坐标程序化传递功能，但历史档案没有该机制，因此该回放不证明新机制效果。默认pipeline顺序如页首：Supervisor调度CV与Geometry，TikZ生成后执行坐标契约/确定性后修复，编译/渲染和Critic；Critic需要修复时回到TikZ或重测。';

for(let i=0;i<presentation.slides.items.length;i++){
 const b=await presentation.export({slide:presentation.slides.items[i],format:'png',scale:1});
 await fs.writeFile(path.join(build,`slide-${i+1}.png`),new Uint8Array(await b.arrayBuffer()));
}
const candidate=path.join(build,'candidate.pptx');await(await PresentationFile.exportPptx(presentation)).save(candidate);
const {finalizePresentation}=await import(pathToFileURL(path.join(skill,'container_tools/artifact_tool_utils.mjs')).href);
const result=await finalizePresentation({workspaceDir:root,candidatePath:candidate,finalPath:path.join(root,'deliverables/pipeline_cases/GeoAgent_928_repair_772_pipeline_final.pptx'),pythonExecutable:'C:/Users/18217/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe',integrityValidatorPath:path.join(skill,'container_tools/inspect_presentation_package_integrity.py'),layoutValidatorPath:path.join(skill,'container_tools/inspect_presentation_layout_geometry.py'),layoutArgs:['--expected-slide-size-emu','15240000,8572500','--validate-heading-fit','--require-native-table-slide','1'],explicitTotalSlideCount:2,requiredNativeTableOwnerSlides:[1],fontPolicy:{basis:'design',families:['Microsoft YaHei']},verifyArtifactToolImport:true,receiptPath:path.join(build,'validation-final.json')});
console.log(JSON.stringify({finalPath:result.finalPath,checks:result.packageIntegrity.status,slides:result.presentationLayout.slide_count,warnings:result.presentationLayout.warning_count}));



