import fs from 'node:fs/promises';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
import {PresentationFile,FileBlob} from '@oai/artifact-tool';
const root='D:/Users/18217/Desktop/我的文件/GeoAgent';
const build=path.join(root,'.codex-build/pipeline_cases_explained');
const skill='C:/Users/18217/.codex/plugins/cache/openai-primary-runtime/presentations/26.1026.10807/skills/presentations';
const presentation=await PresentationFile.importPptx(await FileBlob.load(path.join(root,'deliverables/pipeline_cases/GeoAgent_2108_repair_772_pipeline.pptx')));
const [s1,s2]=presentation.slides.items;
function tx(slide,name,value,x,y,w,h,size=24,color='#243447',bold=false){
 let s=slide.shapes.items.find(z=>z.name===name);
 if(!s)s=slide.shapes.add({geometry:'textbox',name,position:{left:x,top:y,width:w,height:h},fill:'none',line:{fill:'none',width:0}});
 s.position={left:x,top:y,width:w,height:h};s.text=value;
 s.text.style={typeface:'Microsoft YaHei',fontSize:size,color,bold,insets:0,autoFit:'none',verticalAlignment:'top'};return s;
}
const one=(...a)=>tx(s1,...a),two=(...a)=>tx(s2,...a);
one('step2','02  约束下的最小位移优化',580,336,950,38,27,'#102B46',true);
one('step2detail','按对角线归一化坐标 q；约束 c(q)=0：两组 u·v=0，D∈AB、EC。',580,378,970,38,23);
one('opt-objective','min ΔqᵀMΔq   s.t. c(qₖ)+Jc(qₖ)(q₀+Δq−qₖ)=0',580,418,970,38,26,'#102B46');
one('opt-definition','Δq 为相对输入 q₀ 的位移；M 含全点对长度保护（λ=0.01）。',580,459,970,34,23);
one('opt-iteration','逐轮线性化 → SVD 最小二乘 → 更新点位，最多 60 轮。',580,494,970,35,23);
one('step3','03  用结构限制筛选解，再写回代码',580,541,970,38,27,'#102B46',true);
one('step3detail','单点位移≤对角线 0.5%，已有边长变化≤1%，保持点在线段内的顺序。\n若冲突或超限，移除较弱候选重解；导出统一保留 3 位小数。',580,582,970,64,23);
one('step4','04  回读实际导出坐标并复验',580,654,970,38,27,'#102B46',true);
one('step4detail','AB⊥AC：0.2188° → 0.00001°；EB⊥EC：0.1518° → 0.00758°。\n检查位移与边长，失败回退；本例最大位移 0.065%，边长变化 0.099%。',580,695,970,60,22);
s1.speakerNotes.append('\n新增优化说明：q为按图形对角线归一化后的坐标，q0为原始坐标，qk为当前迭代坐标，Δq定义为下一解相对q0的总位移。每轮最小化Δq^T M Δq，满足当前非线性约束的一阶近似c(qk)+Jc(qk)(q0+Δq-qk)=0。M=I+λ(n/m)Jl^T Jl，λ=0.01，n为点数、m为非退化点对数量，Jl为在初始坐标处相对长度变化的雅可比；固定度量保护短边。通过Cholesky变换和numpy.linalg.lstsq的SVD最小二乘求解，最多60轮，直到约束残差和更新足够小。约束包含两个点积为零及D在线上的叉积残差。不是通过参考坐标或LLM调整，也不是梯度下降。');

two('phase1','01  识别圆轨迹，整理几何证据',55,164,520,42,28,'#116778',true);
const cir=s2.images.items[0];
cir.replace({blob:new Uint8Array(await fs.readFile(path.join(root,'.codex-build/pipeline_cases_v2/assets/cv/detect_circles.png'))),contentType:'image/png',alt:'772真实圆弧检测叠图：主圆circle_01和未采用的局部圆弧候选circle_02'});
two('origcap','圆／弧候选叠图',55,428,240,31,22,'#526575');
two('cvdetail','二值化 → 骨架化 → RANSAC 三点拟圆，\nKasa 最小二乘重拟合，Hough 作补充。\n沿 360 个角度检查圆周笔画支持。\n主圆覆盖率 100%：O≈(271.8,302.2)，\nr≈118.4 px；原图核验仅保留完整圆，\n另一局部圆弧候选不绘制。',55,476,520,178,23);
two('gesdetail','圆参数与标签写入 GES，附来源和冲突；\nGeometry 整理三角形、圆与内部线段关系。\n输出 14 个对象、10 条关系，供 TikZ 使用。',55,657,520,85,23);
two('effect','Critic 修正圆线连接细节：\n端点径向偏差约 4.5–6.1 px\n→ 约 0–0.013 px（按源码复算）。',55,763,520,90,24,'#102B46',true);
two('v1detail','TikZ 统一缩放并翻转 y 轴：\n圆心同框转换，半径 rₜ=s·r，绘制完整圆。\n本例后修复无候选；编译和校验通过。\n得到 v1，交给 Critic 检查圆线接合。',590,571,480,120,23);
two('v2detail','Critic 指出越界，TikZ 按圆参数重设端点：\nP′ = O + r·(cosφ, sinφ)。\n保持主体，重编译后再次 Critic 检查。\n0.90 → 0.93，无剩余问题，选择 v2。',1100,571,465,120,23);
s2.speakerNotes.append('\n新增圆轨迹识别和后续处理。来源：geoagent/cv_tools/circle_detection.py及当前确定性重跑.codox-build/pipeline_cases_v2/assets/circles.json（实际路径为.codex-build/pipeline_cases_v2/assets/circles.json）。主检测：二值化灰度<128、细化骨架，随机3点RANSAC默认500次，径向内点判定，再Kasa最小二乘重拟合；角度可见性按360方向在半径邻域采样，Hough补充，按圆心/半径相近去重。772两个输出均来自skeleton RANSAC+Kasa：circle_01中心(271.78,302.15)，半径118.38，coverage=1.0，full_circle=true；circle_02中心(271.75,218.06)，半径78.01，coverage=.631，full_circle=false，227度局部范围。第二候选中心和半径显著不同，不能断言是同一圆的重复检测。历史Supervisor查看原图，Geometry和TikZ只使用完整主圆；另一个候选不进入最终绘制。\n像素坐标统一变换：x_t=(x-cx)s，y_t=(cy-y)s，r_t=s*r；本例v1/v2坐标系以487翻转y、s=.017021，O=(4.626,3.145)，radius=2.015 TikZ单位。Critic看到微小端点越界，v2按圆心半径和30/150/210/330度等方向构造P=O+r(cosφ,sinφ)，顶部取90度，底部保留基线连接T。并非确定性后修复算法投影端点，而是Critic反馈给TikZ Agent修改。此前的主要误差指标和v1/v2局部放大保持。');
for(let i=0;i<2;i++){const b=await presentation.export({slide:presentation.slides.items[i],format:'png',scale:1});await fs.writeFile(path.join(build,`slide-${i+1}.png`),new Uint8Array(await b.arrayBuffer()));}
const candidate=path.join(build,'candidate.pptx');await(await PresentationFile.exportPptx(presentation)).save(candidate);
const {finalizePresentation}=await import(pathToFileURL(path.join(skill,'container_tools/artifact_tool_utils.mjs')).href);
const r=await finalizePresentation({workspaceDir:root,candidatePath:candidate,finalPath:path.join(root,'deliverables/pipeline_cases/GeoAgent_optimization_circle_pipeline.pptx'),pythonExecutable:'C:/Users/18217/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe',integrityValidatorPath:path.join(skill,'container_tools/inspect_presentation_package_integrity.py'),layoutValidatorPath:path.join(skill,'container_tools/inspect_presentation_layout_geometry.py'),layoutArgs:['--expected-slide-size-emu','15240000,8572500','--validate-heading-fit','--require-native-table-slide','1'],explicitTotalSlideCount:2,requiredNativeTableOwnerSlides:[1],fontPolicy:{basis:'design',families:['Microsoft YaHei']},verifyArtifactToolImport:true,receiptPath:path.join(build,'validation.json')});
console.log(JSON.stringify({path:r.finalPath,status:r.packageIntegrity.status,slides:r.presentationLayout.slide_count,warnings:r.presentationLayout.warning_count}));
