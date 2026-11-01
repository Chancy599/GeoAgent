"""Package the versioned geometry fix without changing frozen programs/results."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from geoagent.evaluation.structure import CORE_POLICY, PROTOCOL, backend, prediction, load_reference, score
from scripts.merge_evaluation_results import build_ablation


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def marker_probes(out, structure):
    records = []
    pattern = r"\\coordinate\s*\(([^)]+)\)\s*at\s*\(\s*([-+\d.eE]+),\s*([-+\d.eE]+)\s*\);"
    for stem, row in structure["groups"]["post"]["per_stem"].items():
        audit = row.get("extraction", {})
        if not audit.get("removed_strokes"):
            continue
        src = ROOT / "outputs/ours/latex" / f"{stem}.tex"
        text = src.read_text(encoding="utf-8")
        coords = {m[0]: np.array([float(m[1]), float(m[2])]) for m in re.findall(pattern, text)}
        centers = {}
        for glyph in audit["excluded_glyphs"]:
            names = re.findall(r"\(([^()]+)\)", glyph.get("path", " ".join(glyph.get("paths", []))))
            for name in names:
                if name in audit["ignored_coordinate_names"] and name in coords:
                    centers[name] = np.asarray(glyph["anchor"])
        if not centers:
            records.append({"stem": stem, "status": "non_numeric_probe_unavailable"})
            continue
        baseline = prediction(src)
        gt, items = load_reference(ROOT / "data/test/geometry_reference" / f"{stem}.json")
        base_score = score(gt, baseline, items)
        expected = [base_score["angle"]["mean"], base_score["length_ratio"]["mean"], base_score["line_coverage"]]
        for factor in (.5, 1., 1.5):
            def change(match):
                if match[1] not in centers:
                    return match[0]
                anchor = centers[match[1]]
                p = anchor + factor * (coords[match[1]] - anchor)
                return rf"\coordinate ({match[1]}) at ({p[0]:.14f},{p[1]:.14f});"
            target = out / "all_marker_probes" / f"{stem}_{factor}.tex"
            target.parent.mkdir(exist_ok=True)
            target.write_text(re.sub(pattern, change, text), encoding="utf-8")
            graph = prediction(target)
            result = score(gt, graph, items)
            actual = [result["angle"]["mean"], result["length_ratio"]["mean"], result["line_coverage"]]
            same = graph.points.shape == baseline.points.shape and np.allclose(graph.points, baseline.points, atol=1e-12, rtol=0)
            same_score = all(a == b or (a is not None and b is not None and abs(a-b) <= 1e-12)
                             for a, b in zip(expected, actual))
            records.append({"stem": stem, "factor": factor, "helpers": sorted(centers),
                            "same_body_vertices": bool(same), "same_geometry_scores": bool(same_score),
                            "base_vertices": len(baseline.points), "probe_vertices": len(graph.points),
                            "angle_mae": actual[0], "ratio_mre": actual[1], "coverage": actual[2]})
    save(out / "all_marker_invariance.json", records)
    if not all(r.get("same_body_vertices") and r.get("same_geometry_scores") for r in records):
        raise RuntimeError("Inspect failed or unavailable annotation invariance probes")
    return records


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out', type=Path, default=ROOT/'results/latest')
    args = ap.parse_args()
    out = args.out
    structure = read(out/'structure.json')
    assert structure['geometry_protocol'] == PROTOCOL
    protected = read(out/'protected_inputs.json')
    assert all(hashlib.sha256((ROOT/name).read_bytes()).hexdigest() == digest for name, digest in protected.items()), 'Protected source/media changed'
    from scripts.compare_post_tikz import paired_distributions, availability_audit
    groups = {name:g['per_stem'] for name,g in structure['groups'].items()}
    structure['paired_distributions'] = paired_distributions(groups, structure['shared_stems'])
    pooled_ablation, ablation_lines = build_ablation(structure)
    save(out/'structure.json', structure)
    save(out/'availability_audit.json', availability_audit(groups, structure['shared_stems']))
    probes = marker_probes(out, structure)
    identities = []
    for stem in structure['shared_stems']:
        data = read(ROOT/'data/test/geometry_reference'/f'{stem}.json')
        row = dict(stem=stem, **data['self_check'])
        assert all(row[k] is None or abs(row[k]) < 1e-10 for k in ('angle_mae','ratio_mre')), row
        assert row['coverage'] is None or row['coverage'] == 1, row
        identities.append(row)
    save(out/'reference_identity.json', identities)
    repairs = read(out/'repair_manifest.json')['reports']
    previous = read(out/'summary.json')
    mechanical_keys = ('images','workers','applied_images','repair_settings','generation_statuses','reasons','accepted_relations','compiled','engine_verified_images','engine_errors','max_engine_error_deg','reference_used_for_repair','baseline_hashes_unchanged')
    summary = {k: previous[k] for k in mechanical_keys if k in previous}
    summary.update(geometry_protocol=PROTOCOL, groups={n:g['summary'] for n,g in structure['groups'].items()},
                   paired_geometry=structure['paired_geometry'], item_paired=structure['item_paired'])
    save(out/'summary.json', summary)
    audits = {n:{s:r.get('extraction') for s,r in g['per_stem'].items()} for n,g in structure['groups'].items()}
    save(out/'extraction_audit.json', audits)
    visual = read(out/'visual.json')
    test_log = (out/'tests.log').read_text(encoding='utf-8-sig')
    status = re.search(r'(\d+) passed, (\d+) skipped', test_log)
    code = [Path(__file__), ROOT/'scripts/merge_evaluation_results.py', ROOT/'geoagent/evaluation/structure.py', ROOT/'scripts/evaluate_structure_ab.py', ROOT/'scripts/build_geometry_reference.py',
            ROOT/'geoagent/state/tikz_repair.py', ROOT/'geoagent/state/tikz_geometry.py', ROOT/'geoagent/state/angle_glyphs.py',
            ROOT/'geoagent/cv_tools/label_detection.py',ROOT/'geoagent/state/measured_topology.py',ROOT/'geoagent/agents/prompts.py',
            ROOT/'geoagent/agents/tikz_agent.py',ROOT/'geoagent/agents/critic_agent.py',ROOT/'geoagent/orchestration/runner.py',
            ROOT/'data/test/geometry_reference/corrections.json', *[Path(m.__file__) for m in backend()]]
    correction = read(out/'reference_correction_effect.json') if (out/'reference_correction_effect.json').exists() else None
    excluded_images = sum(bool(r.get('angle_glyph_exclusion',{}).get('excluded_strokes')) for r in repairs)
    result = {'schema': PROTOCOL, 'geometry': summary, 'visual': visual, 'policy': CORE_POLICY,
              'pooled_ablation': pooled_ablation,
              'parameters': read(out/'experiments/current_parameters.json'),
              'protected_files_verified': len(protected), 'marker_probes_passed': len(probes),
              'reference_self_checks_passed': len(identities),
              'repair_glyph_excluded_images': excluded_images,
              'reference_correction_effect': correction,
              'tests': {'passed': int(status[1]), 'skipped': int(status[2])} if status else None,
              'implementation_sha256': {str(p.relative_to(ROOT)) if p.is_relative_to(ROOT) else str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in code}}
    save(out/'result.json', result)
    manifest = read(ROOT/'data/test/geometry_reference/manifest.json')
    lines = ['# 标签绑定几何评测：100图结果', '',
             '只测带可见标签的点：标签名 → 代码中的绑定坐标 → 同名角度与线段比例。没有空间配准或最近点匹配，不带标签的交点与辅助点不参与评测。', '',
             f"参考清单由源代码单独提取到 `data/test/geometry_reference`：{manifest['count']}图，{manifest['edges']}条线段，{manifest['angles']}个角度，{manifest['ratios']}个比例。评测仅读取JSON，不打开参考TeX。", '',
             '同一100图，20 worker汇总；raw取各图所选版本的后处理前代码，post是当前结果。两组共用版本选择，100份编译档案均成功。', '',
             *[line.replace('(results/latest/ablation.json)', '(ablation.json)') for line in ablation_lines],
             '| 覆盖率 | 不修复 raw | 生成后修复 post |', '|---|---:|---:|']
    for field,label in (('coverage','线段覆盖率（%）↑'),('angle_coverage','角度覆盖率（%）↑'),('ratio_coverage','比例覆盖率（%）↑')):
        r = [structure['groups'][n]['summary'][field]*100 for n in ('raw','post')]
        lines.append(f'| {label} | {r[0]:.4f} | {r[1]:.4f} |')
    lines += ['', '覆盖率使用完整参考项作为分母。缺标签、冲突标签、缺线段、退化边和无法解析的程序不计为零误差。', '',
              '消融表仅展示几何指标；视觉评测结果保存在visual.json，三种方法的视觉对比仍见README主表。100图已用于方法开发，当前数据不是独立测试集。MAE和MRE均为误差，越低越好。', '',
              '## 标签和验证', '',
              '`6986`的源文字锚点E=(0, 3.165564918)不在半径3的圆上。经审核，参考清单中的E修正为BC与上半圆的第二交点(-0.161002879, 2.995676563)，所有依赖E的角度和比例已重算。源TeX及原始绑定保留，corrections.json保存构造与源文件哈希，重建清单会重放修正。', '',
              '`6983`的O修正到真实圆心(0,0)，E沿原极角投影到半径2的圆周(-1.937327732, -0.496750701)，同时更新AE的参考端点。1630仅按源码实际坐标评测，不考虑直角符号；411维持原代码。', '',
              '标签的above/left/anchor/字号与文字偏移只影响排版，显式at绑定决定测量坐标。直接写在代码中的字面坐标也作为显式绑定，不推测作者本来想指向哪一点。', '',
              f"{len(identities)}份参考数值自检、{len(probes)}组实际符号缩放探针通过；{len(protected)}个保留源码与媒体文件哈希保持一致。100图均解析成功且有共同可测角度与比例；所有缺失项仍保留在逐图结果中。", '',
              f'修复候选与求解变量排除直角符号笔画及专用辅助点；本批{excluded_images}图命中该规则，{summary.get("applied_images")}图执行修复。命名点、字面坐标、简单偏移和相对坐标的符号路径均有回归验证，带标签的真实短几何受保护。主体的近平行/近垂直关系仍可作为候选。', '',
              '消融仅保留当前版本同批生成的不修复组outputs/ablations/no_post_repair。当前产物位于outputs/ours，报告与评测记录位于results/latest。', '']
    if correction:
        before=correction['results']['uncorrected_reference']['ratio']['mean']*100
        after=correction['results']['corrected_reference']['ratio']['mean']*100
        lines += [f'同一份6986预测代码，仅修正参考E后，该图MRE由{before:.4f}%降至{after:.4f}%。这是参考修正的影响，不能计为过滤算法的收益。', '']
    lines += [
              '## 复验', '', '```powershell',
              'python scripts/build_geometry_reference.py --workers 20',
              'python scripts/evaluate_structure_ab.py --group raw=outputs/ablations/no_post_repair --group post=outputs/ours --workers 20 --out results/latest/structure.json',
              'python scripts/evaluate_visual_cached.py --group raw=outputs/ablations/no_post_repair/image --group post=outputs/ours/image --out results/latest/visual.json',
              'python scripts/report_core_geometry.py', '```', '']
    (out/'report.md').write_text('\n'.join(lines), encoding='utf-8')
    print(json.dumps({'paired_geometry': structure['paired_geometry'], 'protected': len(protected), 'marker_probes': len(probes)}, indent=2))


if __name__ == '__main__':
    main()


