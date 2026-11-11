"""Compile and evaluate the same selected programs with the post-TikZ solver disabled."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from geoagent.config import load_settings
from geoagent.state.tikz_repair import repair_tikz_constraints
from geoagent.tools.compiler import compile_tikz
from geoagent.tools.renderer import frame_like_original, render_pdf
from scripts.merge_evaluation_results import build_ablation, full_cohort_geometry, read, sha


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def export_unrepaired(stem, archive, raw, settings):
    folder = archive / 'stem' / stem
    source = folder / 'unrepaired.tex'
    result = read(folder / 'result.json')
    repair = read(folder / 'constraint_repair.json')
    before = source.read_text(encoding='utf-8')
    assert hashlib.sha256(before.encode('utf-8')).hexdigest() == repair['input_sha256'], stem
    disabled, disabled_report = repair_tikz_constraints(before, enabled=False)
    assert disabled == before and disabled_report['reason'] == 'disabled'
    original = Path(result['image_path'])
    final_image = archive / 'image' / f'{stem}.png'
    final_tex = archive / 'latex' / f'{stem}.tex'
    raw_tex = raw / 'latex' / f'{stem}.tex'
    raw_image = raw / 'image' / f'{stem}.png'
    shutil.copyfile(source, raw_tex)
    if before.strip() == final_tex.read_text(encoding='utf-8').strip():
        shutil.copyfile(final_image, raw_image)
    else:
        with TemporaryDirectory(prefix='geoagent_no_repair_') as directory:
            compiled = compile_tikz(disabled, out_dir=directory, paths=settings.paths,
                                    timeout=settings.budget.compile_timeout_seconds)
            if not compiled['ok']:
                raise RuntimeError(f'{stem} failed to compile with repair disabled: {compiled["errors"]}')
            candidate = Path(directory) / 'render.png'
            rendered = render_pdf(compiled['pdf_path'], candidate, dpi=200)
            if not rendered['ok']:
                raise RuntimeError(f'{stem} failed to render with repair disabled: {rendered["error"]}')
            framed = frame_like_original(candidate, original)
            if not framed['ok']:
                raise RuntimeError(f'{stem} failed to frame with repair disabled: {framed["error"]}')
            shutil.copyfile(candidate, raw_image)
    return {'stem': stem, 'selected_version': result['best_version'], 'original_image_sha256': sha(original),
            'repair_input_sha256': repair['input_sha256'], 'raw_tex_sha256': sha(raw_tex),
            'raw_image_sha256': sha(raw_image), 'post_tex_sha256': sha(final_tex),
            'post_image_sha256': sha(final_image), 'repair_applied': repair['applied'],
            'collinearity_applied': any(c['type'] == 'collinear' for c in repair['accepted']) and repair['applied']}


def summarize(structure, visual, pairs):
    stems = structure['shared_stems']
    if stems != visual['shared_stems'] or stems != [row['stem'] for row in pairs]:
        raise ValueError('The two groups must cover the same frozen image set')
    per_group = {n: g['per_stem'] for n, g in structure['groups'].items()}
    errors = full_cohort_geometry(per_group, stems)
    common, _ = build_ablation(structure)
    groups = {}
    for name, group in structure['groups'].items():
        summary = group['summary']
        if summary['n_unparseable'] or group['missing_programs']:
            raise ValueError(f'Incomplete geometry evaluation for {name}')
        for row in pairs:
            stem = row['stem']
            if (per_group[name][stem]['program_sha256'] != row[f'{name}_tex_sha256']
                    or visual['evaluated_image_sha256'][name][stem] != row[f'{name}_image_sha256']
                    or visual['evaluated_image_sha256']['reference'][stem] != row['original_image_sha256']):
                raise ValueError(f'Evaluated input changed for {name}/{stem}')
        groups[name] = {**visual['groups'][name]['summary'], **summary['geometry_quality'],
                        'angle_mae_with_missing_deg': errors['angle']['means'][name],
                        'ratio_mre_capped_with_missing': errors['ratio']['means'][name],
                        'angle_coverage': summary['angle_coverage'], 'ratio_coverage': summary['ratio_coverage']}
    return {'schema': 'paired-post-tikz-ablation.v1', 'count': len(stems),
            'reference_manifest_sha256': structure['reference_manifest_sha256'],
            'selection': 'Same selected Code Agent program and coordinate contract; toggle only the post-TikZ solver.',
            'groups': groups, 'common_available_items': common, 'pairs': pairs,
            'repair_applied_images': sum(r['repair_applied'] for r in pairs),
            'collinearity_applied_images': sum(r['collinearity_applied'] for r in pairs)}


def markdown(result):
    lines = ['# 关闭几何约束修复的配对消融', '',
             f"同一批 {result['count']} 张图使用同一份进入后修复前的 TikZ，并用相同设置编译和渲染。"
             '两组共享坐标传递和同一批选中版本。该实验估计后修复步骤的影响。', '',
             '| 设置 | SSIM ×100 ↑ | CLIP ×100 ↑ | DINO ×100 ↑ | 角度 MAE（°）↓ | 长度比 MRE（%）↓ |',
             '|---|---:|---:|---:|---:|---:|']
    quality = [('ssim', 100), ('clip', 100), ('dino', 100), ('angle_mae_with_missing_deg', 1),
               ('ratio_mre_capped_with_missing', 100)]
    coverage = [('edge_recall', 100), ('angle_coverage', 100), ('ratio_coverage', 100),
                ('edge_precision', 100), ('edge_f1', 100), ('point_error', 100)]

    def rows(metrics):
        for name, label in [('raw', '关闭几何约束修复'), ('post', '开启几何约束修复')]:
            group = result['groups'][name]
            yield '| ' + ' | '.join([label, *(f'{group[key]*scale:.4f}' for key, scale in metrics)]) + ' |'

    lines.extend(rows(quality))
    lines.extend(['', '| 设置 | 线段覆盖率（%）↑ | 角度覆盖率（%）↑ | 比例覆盖率（%）↑ | 线段精确率（%）↑ | 线段 F1（%）↑ | 点位误差（%）↓ |',
                  '|---|---:|---:|---:|---:|---:|---:|'])
    lines.extend(rows(coverage))
    lines += ['', '角度和长度比按主表口径计入缺测。逐图结果见 [structure.json](structure.json) 和 [visual.json](visual.json)。', '',
              f"后修复实际修改 {result['repair_applied_images']} 张，其中 {result['collinearity_applied_images']} 张接受了共线约束。",
              '两组共同可测项的误差、覆盖率和输入哈希见 [comparison.json](comparison.json)。', '']
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ours', type=Path, default=ROOT/'outputs/ours')
    parser.add_argument('--out', type=Path, default=ROOT/'results/latest/ablation')
    parser.add_argument('--reference-dir', type=Path, default=ROOT/'data/test/geometry_reference')
    parser.add_argument('--workers', type=int, default=20)
    args = parser.parse_args()
    ours, out = args.ours.resolve(), args.out.resolve()
    raw = out/'raw'
    for folder in ('image', 'latex'):
        (raw/folder).mkdir(parents=True, exist_ok=True)
    stems = sorted(read(args.reference_dir/'manifest.json')['files'])
    settings = load_settings()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        pairs = list(pool.map(lambda stem: export_unrepaired(stem, ours, raw, settings), stems))
    save(out/'pairs.json', pairs)
    subprocess.run([sys.executable, str(ROOT/'scripts/evaluate_structure_ab.py'), '--group', f'raw={raw}',
                    '--group', f'post={ours}', '--reference-dir', str(args.reference_dir), '--workers',
                    str(args.workers), '--out', str(out/'structure.json')], check=True)
    subprocess.run([sys.executable, str(ROOT/'scripts/evaluate_visual_cached.py'), '--group', f'raw={raw/"image"}',
                    '--group', f'post={ours/"image"}', '--ref-dir', str(settings.paths.image_dir),
                    '--out', str(out/'visual.json')], check=True)
    result = summarize(read(out/'structure.json'), read(out/'visual.json'), pairs)
    save(out/'comparison.json', result)
    (out/'report.md').write_text(markdown(result), encoding='utf-8')


if __name__ == '__main__':
    main()
