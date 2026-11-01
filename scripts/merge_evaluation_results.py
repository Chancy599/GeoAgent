"""Reuse frozen scores to compare the two e2e baselines and current ours."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.evaluate_structure_ab import _paired_geometry


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_ablation(structure):
    """Pool matched items once each; never select items by repair outcome."""
    metrics = {}
    for metric, key in [('angle', 'angle_checks'), ('ratio', 'ratio_checks')]:
        errors = {'raw': [], 'post': []}
        images = 0
        for stem in structure['shared_stems']:
            raw, post = (structure['groups'][n]['per_stem'][stem] for n in errors)
            if not raw['compiled'] or not post['compiled']:
                continue
            assert len(raw[key]) == len(post[key]), f'Item count mismatch: {stem}'
            count = 0
            for a, b in zip(raw[key], post[key]):
                assert a['labels'] == b['labels'] and a['target'] == b['target'], f'Item identity mismatch: {stem}'
                if a['error'] is not None and b['error'] is not None:
                    assert all(np.isfinite(v) and v >= 0 for v in (a['error'], b['error']))
                    errors['raw'].append(a['error'])
                    errors['post'].append(b['error'])
                    count += 1
            images += bool(count)
        arrays = {name: np.asarray(values, dtype=float) for name, values in errors.items()}
        assert len(arrays['raw']), f'No common {metric} items'
        stats = {name: {'mean': float(v.mean()), 'median': float(np.median(v)),
                        'p90': float(np.percentile(v, 90)), 'p95': float(np.percentile(v, 95)),
                        'rmse': float(np.sqrt(np.mean(v*v)))} for name, v in arrays.items()}
        delta = arrays['raw'] - arrays['post']
        tolerance = 1e-8 / (100 if metric == 'ratio' else 1)
        metrics[metric] = {'n_images': images, 'n_items': len(delta), 'groups': stats,
                           'relative_reduction': {stat: (stats['raw'][stat]-stats['post'][stat])/stats['raw'][stat]
                                                   if stats['raw'][stat] else None for stat in stats['raw']},
                           'improved': int(np.sum(delta > tolerance)),
                           'worsened': int(np.sum(delta < -tolerance)),
                           'unchanged': int(np.sum(np.abs(delta) <= tolerance)),
                           'tie_tolerance': tolerance}
    result = {'schema': 'pooled-common-item-ablation.v1', 'count': len(structure['shared_stems']),
              'aggregation': 'Each common available reference item has equal weight, pooled across images; no per-image averaging or outcome-based filtering.',
              'units': {'angle': 'degrees', 'ratio': 'relative error, fraction'}, 'metrics': metrics}
    columns = [('angle', 'mean', 1), ('ratio', 'mean', 100)]
    lines = ['| 方案 | 整体角度 MAE（°）↓ | 整体比例 MRE（%）↓ |',
             '|---|---:|---:|']
    for name, label in [('raw', '不修复'), ('post', '完整方法 ours')]:
        lines.append('| '+label+' | '+' | '.join(f"{metrics[m]['groups'][name][stat]*scale:.6f}" for m, stat, scale in columns)+' |')
    reductions = [metrics[m]['relative_reduction'][stat] for m, stat, _ in columns]
    lines.append('| 相对下降 | '+' | '.join(f'{v*100:.2f}%' if v is not None else '—' for v in reductions)+' |')
    angle, ratio = metrics['angle'], metrics['ratio']
    lines += ['', f"同一{result['count']}图、同一所选TikZ版本，关闭或开启确定性后修复。两组共同可测项：{angle['n_items']}个角度、{ratio['n_items']}个比例。所有共同项直接合并，每项等权，不先逐图平均，也不按是否修复或改善筛选条目。", '',
              '整体角度MAE = Σ角度绝对误差 / 共同角度数；整体比例MRE = 100 × Σ比例相对误差 / 共同比例数。相对下降 =（不修复−修复后）/不修复。', '',
              f"逐项配对：角度改善{angle['improved']}项、变差{angle['worsened']}项、不变{angle['unchanged']}项；比例改善{ratio['improved']}项、变差{ratio['worsened']}项、不变{ratio['unchanged']}项。不变容差为角度10⁻⁸°、比例相对误差10⁻⁸个百分点。", '',
              '比例误差的均值小幅改善，但P90、P95及均方根误差未改善，完整分布统计见[ablation.json](results/latest/ablation.json)。不能据此声称所有比例误差均下降。', '',
              '三种方法主表仍按图平均，且使用三组共同项；本消融按条目汇总并使用两组共同项，因此两表的ours数值不同。', '']
    return result, lines


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--results', type=Path, default=ROOT/'results/latest')
    args = parser.parse_args()
    out = args.results
    paths = {n:out/f for n,f in [('baseline_geometry','baselines_geometry.json'),('baseline_visual','baselines_visual.json'),('ours_geometry','structure.json'),('ours_visual','visual.json')]}
    data = {n:read(p) for n,p in paths.items()}
    bg,og = data['baseline_geometry'],data['ours_geometry']
    manifest = ROOT/'data/test/geometry_reference/manifest.json'
    assert bg['reference_manifest_sha256'] == og['reference_manifest_sha256'] == sha(manifest), 'Geometry reference mismatch; rescore first'
    names = ['haiku-5.5','gpt-5.4','ours']
    stems = og['shared_stems']
    assert len(stems) == 100 and set(stems) == set(bg['shared_stems'])
    rows = {n:bg['groups'][n]['per_stem'] for n in names[:2]}
    rows['ours'] = og['groups']['post']['per_stem']
    geometry = _paired_geometry(rows,names,stems)
    values = {}
    for name in names:
        if name == 'ours':
            v = data['ours_visual']
            assert set(v['shared_stems']) == set(stems)
            summary = v['groups']['post']['summary']
            visual_rows = v['groups']['post']['per_stem']
            g = og['groups']['post']
            archive = ROOT/'outputs/ours'
        else:
            v = data['baseline_visual']['groups'][name]['shared']
            assert v['count'] == 100
            visual_rows = v['per_image']
            assert {r['stem'] for r in visual_rows} == set(stems)
            summary = v['aggregate']
            g = bg['groups'][name]
            archive = ROOT/'outputs/baselines'/name
        # Inputs are immutable; retaining their hashes makes score reuse auditable.
        hashes = {'images':{s:sha(archive/'image'/f'{s}.png') for s in stems},
                  'programs':{s:sha(archive/'latex'/f'{s}.tex') for s in stems}}
        protected = read(out/'protected_inputs.json')
        for kind,folder,extension in [('images','image','png'),('programs','latex','tex')]:
            for stem,digest in hashes[kind].items():
                path = (archive/folder/f'{stem}.{extension}').relative_to(ROOT).as_posix()
                assert protected[path] == digest, f'Input changed: {path}'
        values[name] = {'ssim':summary['ssim'],'clip':summary['clip'],'dino':summary['dino'],
                        'angle_mae_deg':geometry['angle']['means'][name],
                        'ratio_mre':geometry['ratio']['means'][name],
                        'coverage':{k:g['summary'][k] for k in ('coverage','angle_coverage','ratio_coverage')},
                        'input_sha256':hashes}
    result = {'schema':'three-model-five-metrics.v1','count':len(stems),'shared_stems':stems,
              'reference_manifest_sha256':sha(manifest),'geometry_common_items':geometry,
              'groups':values,'reused_scores':True,'new_model_or_metric_inference':False,
              'source_sha256':{n:sha(p) for n,p in paths.items()},
              'visual_caveat':'Baseline visual aggregates were previously stored to six decimal places; retained unchanged.',
              'geometry_aggregation':'Same items available in all three groups, mean within image then across images; coverage uses the full reference.'}
    (out/'comparison.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    lines = ['| 方法 | SSIM ×100 ↑ | CLIP ×100 ↑ | DINO ×100 ↑ | MAE（°）↓ | MRE（%）↓ |',
             '|---|---:|---:|---:|---:|---:|']
    for name in names:
        v = values[name]
        lines.append(f"| {name} | {v['ssim']*100:.4f} | {v['clip']*100:.4f} | {v['dino']*100:.4f} | {v['angle_mae_deg']:.6f} | {v['ratio_mre']*100:.6f} |")
    lines += ['', f"同一100图；几何采用三组共同可测项：{geometry['angle']['n_items']}个角度、{geometry['ratio']['n_items']}个比例，均覆盖{geometry['angle']['n_images']}图。先按图平均，再跨图平均。", '',
              '主表几何使用三组共同可测项，与不修复消融的两组均值不同。', '',
              '| 方法 | 线段覆盖率（%）↑ | 角度覆盖率（%）↑ | 比例覆盖率（%）↑ |', '|---|---:|---:|---:|']
    for name in names:
        c=values[name]['coverage']
        lines.append(f"| {name} | {c['coverage']*100:.4f} | {c['angle_coverage']*100:.4f} | {c['ratio_coverage']*100:.4f} |")
    (out/'comparison.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    ablation_result, ablation = build_ablation(og)
    ablation_result['source_sha256'] = sha(paths['ours_geometry'])
    ablation_result['reference_manifest_sha256'] = sha(manifest)
    ablation_result['implementation_sha256'] = sha(Path(__file__))
    (out/'ablation.json').write_text(json.dumps(ablation_result,ensure_ascii=False,indent=2),encoding='utf-8')
    (out/'ablation.md').write_text('\n'.join(ablation).replace('(results/latest/ablation.json)', '(ablation.json)'),encoding='utf-8')
    readme=ROOT/'README.md'
    text=readme.read_text(encoding='utf-8')
    start,end='<!-- benchmark:start -->','<!-- benchmark:end -->'
    if start in text and end in text:
        before,tail=text.split(start,1)
        _,after=tail.split(end,1)
        text=before+start+'\n\n'+'\n'.join(lines)+'\n\n'+end+after
    start,end='<!-- ablation:start -->','<!-- ablation:end -->'
    if start in text and end in text:
        before,tail=text.split(start,1);_,after=tail.split(end,1)
        text=before+start+'\n\n'+'\n'.join(ablation)+'\n'+end+after
    readme.write_text(text,encoding='utf-8')
    print('\n'.join(lines))


if __name__ == '__main__':
    main()
