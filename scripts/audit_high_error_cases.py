"""Audit high errors using frozen source bindings, constructions and run traces."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from geoagent.evaluation.structure import backend


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out',type=Path,default=ROOT/'results/latest')
    args=ap.parse_args();out=args.out
    rows=read(out/'structure.json')['groups']['post']['per_stem']
    top=lambda field:sorted(rows,key=lambda n:rows[n][field] if rows[n][field] is not None else -1,reverse=True)[:10]
    stems=sorted(['1250_q_fig1','1266_s_fig1','1630_s_fig1','396_q_fig2','403_q_fig1','411_q_fig1','50_q_fig1','6983_q_fig1','6986_q_fig1','698_q_fig1','6991_q_fig1','7017_q_fig1','7107_q_fig2','915_q_fig1','971_q_fig1','1615_s_fig1','6987_q_fig1'])
    refreshed=read(out/'regeneration.json')['selected_stems'] if (out/'regeneration.json').exists() else []
    angle=backend()[1].angle
    notes={
        '403_q_fig1':('generated_point_error','D在生成图中偏低；AD/AB参考0.5，生成约0.4309。原图与生成图可见D位置差异，未发现E式绑定冲突。'),
        '50_q_fig1':('confirmed_model_omission','P/Q被CV识别，但没有绑定到端点；Supervisor裁剪漏掉两端并错误驳回Critic，最终partial。详见diagnosis_50.md。'),
        '6983_q_fig1':('reviewed_correction_present','O已修正到实际圆心(0,0)，E已保持原极角投影到半径2的圆周；A/B/C/D保留原坐标。相关角度和比例均重算。'),
        '1630_s_fig1':('actual_coordinate_reference','按源码实际坐标评测，AQH=88.5354°，不使用直角符号推断90°；不作参考修正。'),
        '411_q_fig1':('original_reference_retained','按原代码保留全部坐标与目标；ADE=177.5940°是实际坐标值，不进行共线化修正。'),
        '6986_q_fig1':('reviewed_correction_present','E已按审核构造修正；其余角度按实际坐标计算，不因直角符号改成90°。'),
        '7017_q_fig1':('generated_extent_difference','生成AM射线的末端延伸偏长；AD/DM参考2，生成1.6763，影响多条涉及M的比例。不是标签配错点。'),
        '698_q_fig1':('no_same_type_binding_error_found','E绑定的是AC上的点；参考AE/CE=1，生成1.1631。未发现像6986那样绑定到错误构造的明确证据。'),
        '1615_s_fig1':('confirmed_generated_endpoint_error','虚线使用独立字面端点而非共享命名顶点，GN末端距N约13.4px，EN末端距N约8.1px；三次Critic未发现残留越界，后修复未执行。'),
        '6987_q_fig1':('confirmed_generated_topology_error','原图及参考是A-E-C折线，AEC=172.385°，模型却画直线AC，遗漏AE和EC；E坐标接近原拐点，导致垂线与直角标记脱离所画AC。'),
    }
    if refreshed:
        notes.update({
          '50_q_fig1':('resolved_model_omission','已重生成：P/Q齐全；端点补全仅用于未绑定标签，保留原有交点绑定。修复前原因见diagnosis_50.md。'),
          '1615_s_fig1':('resolved_generated_endpoint_error','已重生成：EC/EN/GN使用共享命名端点；保留E-G-B的真实浅折线，避免将G拉直。'),
          '6987_q_fig1':('resolved_generated_topology_error','已重生成：保留A-E-C折线，BE连接E，直角pic绑定A--E--B，不使用CE的延长点。'),
        })
    cases={}
    for stem in stems:
        row=rows[stem];reference=read(ROOT/'data/test/geometry_reference'/f'{stem}.json')
        points={n:np.array(d['xy']) for n,d in reference['points'].items()}
        checks={}
        if stem=='1630_s_fig1':checks['reference_AQH_deg']=angle(points['A'],points['Q'],points['H'])
        if stem=='411_q_fig1':checks['reference_ADE_deg']=angle(points['A'],points['D'],points['E'])
        if stem=='6983_q_fig1':checks.update(reference_O=points['O'].tolist(),circle_center=[0,0],circle_radius=2.,reference_E_radius=float(np.linalg.norm(points['E'])))
        if stem=='6987_q_fig1':checks.update(reference_AEC_deg=angle(points['A'],points['E'],points['C']),reference_AEB_deg=angle(points['A'],points['E'],points['B']))
        verdict,note=notes.get(stem,('no_same_type_binding_error_found','已对照原图、生成图及参考绑定；未发现明确的6986式标签/构造错配。参考预设参数和像素拟合差异仍可能影响误差。'))
        cases[stem]={'angle_mae_deg':row['angle_mae'],'ratio_mre':row['ratio_mre'],
                     'verdict':verdict,'review_note':note,'construction_checks':checks,
                     'missing_labels':row.get('missing_labels',[]),
                     'reference_binding_conflicts':reference['audit']['same_name_coordinate_conflicts'],
                     'largest_ratio_errors':sorted([c for c in row['ratio_checks'] if c['error'] is not None],key=lambda c:c['error'],reverse=True)[:3],
                     'reference_source_sha256':reference['source_sha256']}
    # Scan all references for near-center O bindings displaced from actual circles.
    center_warnings=[];binding_conflicts={}
    parser=backend()[0]
    for path in sorted((ROOT/'data/test/latex').glob('*.tex')):
        drawing=parser.parse_drawing(path)
        cache=read(ROOT/'data/test/geometry_reference'/f'{path.stem}.json')
        if cache['audit']['same_name_coordinate_conflicts']:
            binding_conflicts[path.stem]=cache['audit']['same_name_coordinate_conflicts']
        circles=[c for c in drawing.curves if c.get('full')]
        if not circles:continue
        radius=max(c['radius'] for c in circles)
        circles=[c for c in circles if c['radius']>=.25*radius]
        for label in drawing.labels:
            if label['text']!='O':continue
            circle=min(circles,key=lambda c:np.linalg.norm(np.asarray(c['center'])-label['position']))
            offset=float(np.linalg.norm(np.asarray(circle['center'])-label['position']))
            if 1e-7*circle['radius']<offset<=.05*circle['radius']:
                center_warnings.append({'stem':path.stem,'label_O':label['position'].tolist(),
                                        'circle_center':np.asarray(circle['center']).tolist(),'radius':circle['radius'],
                                        'relative_offset':offset/circle['radius'],
                                        'corrected_reference_O':cache['points'].get('O',{}).get('xy'),
                                        'resolved_in_reference':any(c['label']=='O' for c in cache['audit'].get('reviewed_reference_corrections',[]))})
    # Trace the confirmed omission instead of inferring fault from metric size.
    state=read(ROOT/'outputs/ablations/no_post_repair/stem/50_q_fig1/state.json')
    critic=read(ROOT/'outputs/ablations/no_post_repair/stem/50_q_fig1/critic_report.json')
    labels={v['label']:v for v in state['objects'].values() if v['type']=='label' and v.get('label') in ('P','Q')}
    inspect=next((a for a in state['action_history'] if a['action']=='inspect_image'),None)
    finishes=[a for a in state['action_history'] if a['action']=='finish']
    trace={'recognized_labels':labels,'bound_point_labels':state['label_bindings'],
           'inspection':inspect,'critic_missing_labels':critic['labels']['missing'],
           'critic_must_repair':critic['must_repair'],'finish_attempts':finishes,
           'post_repair_reason':read(ROOT/'outputs/ours/stem/50_q_fig1/constraint_repair.json')['reason'],
           'root_cause':'Point derivation creates line intersections and circle-related points but not free line endpoints; P/Q were recognized but unbound. Inspection excluded both ends; supervisor dismissed correct critic feedback without new evidence. Finish gate blocked once, then allowed partial.',
           'frozen_output_changed':False}
    if refreshed and (out/'diagnosis_50.json').exists():
        trace=read(out/'diagnosis_50.json')
        trace['evidence_phase']='original failure before regeneration'
        trace['current_validation']={'regenerated':True,'missing_labels':rows['50_q_fig1'].get('missing_labels',[]),'coverage':rows['50_q_fig1']['coverage']}
    (out/'diagnosis_50.json').write_text(json.dumps(trace,ensure_ascii=False,indent=2),encoding='utf-8')
    diagnostic='''# 50_q_fig1：模型遗漏P/Q的定位

原图确有P、Q。CV已识别：P框[38,360,58,379]、Q框[463,359,483,384]，模板匹配分数分别0.9307和0.9195（启发式分数，不是校准概率）。`label_detection._derive_points`只添加线线交点、可靠圆心和线圆交点，没有把单独的线段端点加入候选，因此基线两端没有可供P/Q绑定的点。它们未进入label_bindings，Supervisor只把A–E传给Code Agent，并要求不添加其他元素。

随后inspect_image只看[100,30,420,390]，完整排除了P、Q。Critic正确报告缺P/Q、must_repair=true；Supervisor没有再看对应区域，就把意见当成幻觉。第一次finish被门控拦截，第二次以partial结束；门控对同一问题只拦截一次，允许带未解决问题交付。

后修复记录为already_satisfied，点位移为零，因此这不是后修复删除了标签。Code Agent按不完整指令生成，主要故障是Supervisor未处理未绑定标签、证据覆盖不足和错误驳回反馈。框架已如实标为partial，并非成功修复。

D坐标来自CV的(186.97,349.25)，代码约为(0.808,0)，未被后修复移动。比例误差与P/Q遗漏是两件事：缺标签按覆盖率记为不可用，不会作为零误差。

后续改进应让未绑定的可见标签显式进入待核验清单；驳回缺标签意见前，必须复查覆盖其bbox的区域；对未解决分歧保留partial状态。此次只诊断，不重新生成或手工补改冻结图，以保持三组指标可复用。
'''
    if refreshed:diagnostic='当前已重新生成，P/Q齐全。以下保留修复前问题与优化依据。\n\n'+diagnostic
    (out/'diagnosis_50.md').write_text(diagnostic,encoding='utf-8')
    # User-identified failures can have low conditional errors but missing edges.
    for stem in ['1615_s_fig1','6987_q_fig1']:
        folder=ROOT/'outputs/ablations/no_post_repair/stem'/stem
        state=read(folder/'state.json')
        repair=read(ROOT/'outputs/ours/stem'/stem/'constraint_repair.json')
        detail={'stem':stem,'frozen_output_changed':False,'post_repair_applied':repair['applied'],
                'post_repair_reason':repair['reason'],'actions':[a for a in state['action_history'] if a['action'] in ('run_tikz_agent','run_critic','finish')],
                'critics':state['critic_reports'],'metric_coverage':rows[stem]['coverage'],
                'missing_edges':rows[stem].get('missing_edges',[])}
        if stem=='1615_s_fig1':
            detail.update(GN_literal_endpoint=[152,40],N_coordinate=[158,52],GN_endpoint_error_px=float(np.hypot(6,12)),EN_endpoint_error_px=float(np.hypot(4,7)))
            text='''# 1615_s_fig1：虚线越过命名点

生成代码为G、N分别声明(195,123)、(158,52)，但GN虚线写成(202,136)--(152,40)，两端没有复用G/N。其末端到N为13.4164像素，低于底边12像素；EN的末端(162,45)到N为8.0623像素。EC还被拆为有重叠的独立字面片段。

Supervisor把CV的碎片拟合端点直接传给Code Agent，没有归并成EC、EN、GN等共享顶点的边。后续修复只把DB合成完整虚线，并增加线宽，明确要求其他几何不变；Critic从0.8、0.82升至0.9，仍漏掉了越界。加粗后尾部更显眼，但错误端点在加粗前已存在。

当前确定性后修复因picture的x/y坐标基返回unsupported_transform_or_scope，完全没有移动这张图。根因是生成时没有把笔画像素端点与命名顶点绑定，并被局部风格修复与视觉审查漏检。后续应将已确认的虚线边写为(E)--(N)、(G)--(N)、(E)--(C)，同时检查尾端是否越过应连接的顶点。
'''
        else:
            bindings=rows[stem]['extraction']['label_bindings'];p={n:np.array(v['xy']) for n,v in bindings.items()}
            detail.update(reference_AEC_deg=cases[stem]['construction_checks']['reference_AEC_deg'],
                          generated_AEC_label_angle_deg=angle(p['A'],p['E'],p['C']),generated_AEB_label_angle_deg=angle(p['A'],p['E'],p['B']))
            text='''# 6987_q_fig1：把A-E-C折线误当对角线

原图A、E、C不共线，参考AEC=172.3851°，AEB=90°；这是在E转折的A-E-C折线，BE垂直的是AE。当前E的坐标也保持这种形状：AEB=89.7722°、AEC=172.0772°。

错误出在Supervisor生成指令：它要求画“diagonal AC”，同时保留测量得到的E=(138,107)附近坐标。Code Agent因此画(A)--(C)和(B)--(E)，却没有画(A)--(E)--(C)。E仍在折线拐点附近，所以BE和直角符号与实际画出的AC脱开。Critic以0.92分通过，错误声称AC经过E且BE垂直AC。

后修复返回unsupported_literal_edge，没有改变程序。正确结构应是A--E--C及B--E；若强行把E投影到AC，会进一步抹去原图拐折。后续需要核验图像/GES中的点边关联与折线拓扑，不能仅凭“矩形里看似对角线”简化。

当前评测已将AE、EC记录为缺失，线段覆盖率仅71.43%；剩余可测项的MAE/MRE较低不能代表这张图正确。此次只定位原因，未手改冻结输出或重新调用生成模型。
'''
        old_diagnostic=out/f'diagnosis_{stem.split("_")[0]}.json'
        if refreshed and old_diagnostic.exists():
            detail=read(old_diagnostic)
            detail['evidence_phase']='original failure before regeneration'
            detail['current_validation']={'regenerated':True,'coverage':rows[stem]['coverage'],'missing_edges':rows[stem].get('missing_edges',[])}
            text='当前已重生成并核验共享端点与浅折线。以下保留修复前问题与优化依据。\n\n'+text
        (out/f'diagnosis_{stem.split("_")[0]}.json').write_text(json.dumps(detail,ensure_ascii=False,indent=2),encoding='utf-8')
        (out/f'diagnosis_{stem.split("_")[0]}.md').write_text(text,encoding='utf-8')
    result={'schema':'reference-quality-audit.v1','selection':'fixed reviewed set: initial top angle/ratio errors plus user-identified cases; current scores refreshed',
            'selected_count':len(stems),'all_references_scanned':100,'cases':cases,
            'all_reference_center_warnings':center_warnings,'all_reference_binding_conflicts':binding_conflicts,
            'review':'Reviewed constructions are recorded separately; marks do not impose exact angles. 1630 uses actual coordinates and 411 retains original code.',
            'active_reference_corrections':read(ROOT/'data/test/geometry_reference/manifest.json')['reviewed_corrections'],
            'current_top_errors':{'angle':top('angle_mae'),'ratio':top('ratio_mre')},
            'lowest_coverage_cases':[{'stem':s,'coverage':rows[s]['coverage'],'missing_edges':rows[s].get('missing_edges',[])} for s in sorted(rows,key=lambda s:rows[s]['coverage'] if rows[s]['coverage'] is not None else 0)[:10]],
            'structure_sha256':hashlib.sha256((out/'structure.json').read_bytes()).hexdigest()}
    (out/'reference_quality_audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    lines=['# 高误差与用户指出样本审计','','保留最初高误差与用户指定的17图审计集合，更新当前结果；另扫描全部100份参考的绑定冲突和近圆心偏移。','','| 图片 | MAE（°） | MRE（%） | 判断与证据 |','|---|---:|---:|---|']
    for stem,c in cases.items():lines.append(f"| {stem} | {c['angle_mae_deg']:.4f} | {c['ratio_mre']*100:.4f} | {c['review_note']} |")
    lines += ['', '6983的O与E已按审核构造修正。1630忽略直角符号，按源码实际坐标评测；411维持原代码。403仍有生成点D偏差。50、1615、6987已按诊断优化并重生成。当前五项指标统一使用更新后的参考清单。', '',
              '[50的详细定位](diagnosis_50.md)、[1615虚线越界](diagnosis_1615.md)、[6987折线拓扑错误](diagnosis_6987.md)。诊断保留修复前证据，并附当前核验状态。', '']
    (out/'reference_quality_audit.md').write_text('\n'.join(lines),encoding='utf-8')
    print(f'High-error audit: {len(stems)} reviewed; all 100 references scanned; 50 model omission traced; no new truth edits.')


if __name__=='__main__':
    main()
