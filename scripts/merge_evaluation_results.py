"""Validate and report the model comparison on the frozen 100-image set."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
FULL_COHORT_ERROR_CAPS = {'angle': 180., 'ratio': 1.}


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def full_cohort_geometry(per_group, stems):
    """Average each image's reference items, including unavailable predictions."""
    geometry = {}
    for kind, cap in FULL_COHORT_ERROR_CAPS.items():
        key = f'{kind}_checks'
        reference_counts = [len(next(iter(per_group.values()))[stem][key]) for stem in stems]
        if not all(reference_counts):
            raise ValueError(f'Every benchmark image must have reference {kind} items')
        means = {}
        for name, rows in per_group.items():
            image_errors = []
            for stem, expected in zip(stems, reference_counts):
                checks = rows[stem][key]
                if len(checks) != expected:
                    raise ValueError(f'Incomplete reference {kind} checks: {name}/{stem}')
                errors = [cap if item['error'] is None else min(item['error'], cap) for item in checks]
                image_errors.append(sum(errors) / expected)
            means[name] = sum(image_errors) / len(stems)
        geometry[kind] = {'n_images': len(stems), 'n_items': sum(reference_counts),
                          'missing_error': cap, 'error_cap': cap, 'means': means}
    return geometry


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
              '完整分布统计见[ablation.json](results/latest/ablation.json)。整体均值的下降不代表每个条目都改善。', '',
              '三种方法主表仍按图平均，且使用三组共同项；本消融按条目汇总并使用两组共同项，因此两表的ours数值不同。', '']
    return result, lines


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--results', type=Path, default=ROOT/'results/latest')
    parser.add_argument('--ours', type=Path, default=ROOT/'outputs/ours')
    parser.add_argument('--qwen', type=Path, default=ROOT/'outputs/baseline/qwen3.5-plus')
    parser.add_argument('--glm', type=Path, default=ROOT/'outputs/baseline/glm-5.3-flash')
    parser.add_argument('--reference-dir', type=Path, default=ROOT/'data/test/geometry_reference')
    parser.add_argument('--no-readme', action='store_true', help='stage reports without editing README')
    args = parser.parse_args()
    out = args.results
    paths = {name: out/f'{name}.json' for name in ('structure', 'visual')}
    structure, visual = (read(paths[name]) for name in paths)
    manifest_path = args.reference_dir/'manifest.json'
    manifest = read(manifest_path)
    stems = sorted(manifest['files'])
    if len(stems) != 100 or structure['reference_manifest_sha256'] != sha(manifest_path):
        raise ValueError('Expected the current frozen 100-image reference manifest')
    if any(data['shared_stems'] != stems for data in (structure, visual)):
        raise ValueError('Geometry and visual results must cover the complete manifest in order')

    archives = {
        'haiku-5.5': ROOT/'outputs/baseline/haiku-5.5',
        'gpt-5.4': ROOT/'outputs/baseline/gpt-5.4',
        'qwen3.5-plus': args.qwen,
    }
    if 'glm-5.3-flash' in structure['groups']:
        archives['glm-5.3-flash'] = args.glm
    baseline_count = len(archives)
    archives['ours'] = args.ours
    if any(set(data['groups']) != set(archives) for data in (structure, visual)):
        raise ValueError('Geometry and visual results must contain the same supported methods')
    per_group = {name: group['per_stem'] for name, group in structure['groups'].items()}
    geometry = full_cohort_geometry(per_group, stems)
    visual_hashes = visual['evaluated_image_sha256']
    protected = {}
    for stem in stems:
        image = ROOT/'data/test/image'/f'{stem}.png'
        tex = ROOT/'data/test/latex'/f'{stem}.tex'
        image_hash, tex_hash = sha(image), sha(tex)
        if visual_hashes['reference'][stem] != image_hash or manifest['source_hashes'][stem] != tex_hash:
            raise ValueError(f'Reference input changed: {stem}')
        protected[image.relative_to(ROOT).as_posix()] = image_hash
        protected[tex.relative_to(ROOT).as_posix()] = tex_hash

    values = {}
    for name, archive in archives.items():
        visual_group = visual['groups'][name]
        visual_stems = [row['stem'] for row in visual_group['per_stem']]
        if visual_stems != stems or set(per_group[name]) != set(stems):
            raise ValueError(f'Incomplete per-image results: {name}')
        coverage = structure['groups'][name]['summary']
        published = Path('outputs/ours') if name == 'ours' else Path('outputs/baseline')/name
        hashes = {'images': {}, 'programs': {}}
        for stem in stems:
            image_hash = sha(archive/'image'/f'{stem}.png')
            tex_hash = sha(archive/'latex'/f'{stem}.tex')
            if (visual_hashes[name][stem] != image_hash
                    or per_group[name][stem]['program_sha256'] != tex_hash):
                raise ValueError(f'Evaluated output changed: {name}/{stem}')
            hashes['images'][stem] = image_hash
            hashes['programs'][stem] = tex_hash
            protected[(published/'image'/f'{stem}.png').as_posix()] = image_hash
            protected[(published/'latex'/f'{stem}.tex').as_posix()] = tex_hash
        values[name] = {
            **visual_group['summary'],
            'angle_mae_with_missing_deg': geometry['angle']['means'][name],
            'ratio_mre_capped_with_missing': geometry['ratio']['means'][name],
            'coverage': {key: coverage[key] for key in ('coverage', 'angle_coverage', 'ratio_coverage')},
            'n_unparseable': coverage['n_unparseable'],
            'input_sha256': hashes,
        }

    result = {
        'schema': 'model-comparison-five-metrics.v4',
        'count': len(stems),
        'shared_stems': stems,
        'reference_manifest_sha256': sha(manifest_path),
        'geometry_full_cohort': geometry,
        'groups': values,
        'source_sha256': {name: sha(path) for name, path in paths.items()},
        'geometry_aggregation': 'All reference items on the fixed 100 images. Unavailable items receive the error cap; errors are averaged within each image, then across all images.',
    }
    (out/'comparison.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    (out/'protected_inputs.json').write_text(json.dumps(protected, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')

    def metric(value, scale, digits):
        return '—' if value is None else f'{value*scale:.{digits}f}'

    lines = ['| 方法 | SSIM ×100 ↑ | CLIP ×100 ↑ | DINO ×100 ↑ | 角度 MAE（含缺测，°）↓ | 比例 MRE（含缺测及封顶，%）↓ |',
             '|---|---:|---:|---:|---:|---:|']
    for name, row in values.items():
        fields = [metric(row[key], 100, 4) for key in ('ssim', 'clip', 'dino')]
        fields.extend((metric(row['angle_mae_with_missing_deg'], 1, 6),
                       metric(row['ratio_mre_capped_with_missing'], 100, 6)))
        lines.append('| ' + ' | '.join([name, *fields]) + ' |')
    angle, ratio = geometry['angle'], geometry['ratio']
    lines += ['', f"几何指标纳入全部 {angle['n_images']} 张图、{angle['n_items']} 个参考角度和 "
              f"{ratio['n_items']} 个参考比例。缺测角度计 {angle['missing_error']:g}°，缺测比例计 "
              f"{ratio['missing_error']*100:g}%，可测比例误差同样封顶 {ratio['error_cap']*100:g}%。"
              "先在各图内平均，再等权平均 100 张图。", '',
              '| 方法 | 线段覆盖率（%）↑ | 角度覆盖率（%）↑ | 比例覆盖率（%）↑ |',
              '|---|---:|---:|---:|']
    for name, row in values.items():
        fields = [metric(row['coverage'][key], 100, 4) for key in ('coverage', 'angle_coverage', 'ratio_coverage')]
        lines.append('| ' + ' | '.join([name, *fields]) + ' |')
    (out/'comparison.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    generation_path = out/'input_manifest.json'
    generation = read(generation_path).get('groups', {}) if generation_path.is_file() else {}
    generation_lines = []
    if {'ours', 'qwen3.5-plus'} <= generation.keys():
        ours = generation['ours']
        qwen = generation['qwen3.5-plus']
        partial = ours['generation_statuses'].get('partial', 0)
        generation_lines = [
            f"GeoAgent 和 Qwen3.5-Plus 分别用 {ours['workers']} 和 {qwen['workers']} 个 worker 生成，"
            f"各有 {ours['compiled']} 和 {qwen['compiled']} 份编译产物。GeoAgent 的 {partial} 份 partial 结果也纳入评测。",
            '[GeoAgent 生成记录](ours_generation.json) · [Qwen3.5-Plus 生成记录](qwen3.5-plus_generation.json)',
        ]
        if 'glm-5.3-flash' in archives and 'glm-5.3-flash' in generation:
            glm = generation['glm-5.3-flash']
            generation_lines.extend([
                '', f"GLM-5.3-Flash 用 {glm['workers']} 个 worker 生成，编译通过 {glm['compiled']} 张。"
                '重试沿用相同提示与参数，并直接编译模型返回的 TikZ。',
                '[GLM-5.3-Flash 生成记录](glm-5.3-flash_generation.json)',
            ])
        generation_lines.append('')
    report = [
        '# GeoAgent 100图实验结果', '',
        f'当前 GeoAgent 与 {baseline_count} 个图像到 TikZ 的端到端模型在同一100图上评测。视觉采用固定的 SSIM、CLIP 和 DINO；'
        '几何按可见标签绑定计算角度和线段长度比。覆盖率以完整参考清单为分母，无法测量的项保留为缺失。', '',
        *generation_lines,
        *lines, '',
        '逐图几何见 [structure.json](structure.json)，逐图视觉见 [visual.json](visual.json)，'
        '输出和输入哈希见 [comparison.json](comparison.json)。这批图已用于项目开发。', '',
    ]
    (out/'report.md').write_text('\n'.join(report), encoding='utf-8')
    if not args.no_readme:
        readme = ROOT/'README.md'
        text = readme.read_text(encoding='utf-8')
        start, end = '<!-- benchmark:start -->', '<!-- benchmark:end -->'
        before, tail = text.split(start, 1)
        _, after = tail.split(end, 1)
        readme.write_text(before + start + '\n\n' + '\n'.join(lines) + '\n\n' + end + after, encoding='utf-8')
    print('\n'.join(lines))


if __name__ == '__main__':
    main()
