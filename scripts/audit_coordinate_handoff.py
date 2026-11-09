"""Offline CV-to-code precision audit; no reference geometry or model calls."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from geoagent.state.coordinate_contract import build_coordinate_contract, apply_coordinate_contract
from geoagent.state.schemas import GeometricEvidenceState
from geoagent.state.tikz_geometry import extract_geometry
from geoagent.tools import compile_tikz


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stems', nargs='+', default=['50_q_fig1', '1615_s_fig1', '6987_q_fig1'])
    args = parser.parse_args()
    records = []
    for stem in args.stems:
        archive = ROOT/'outputs/ours/stem'/stem
        state_path = archive/'state.json'
        state = GeometricEvidenceState.model_validate_json(state_path.read_text(encoding='utf-8'))
        contract = build_coordinate_contract(state)
        raw_path = archive/'unrepaired.tex'
        raw = extract_geometry(raw_path.read_text(encoding='utf-8'))
        labels = sorted(set(contract['points']) & set(raw['points']))
        assert len(labels) >= 3, stem
        measured = np.array([contract['points'][n]['px'] for n in labels])
        generated = np.array([raw['points'][n] for n in labels])
        # Eliminate harmless global translation and uniform scale, assuming the
        # documented x-right/y-up conversion. This is not a ground-truth metric.
        xy = measured * [1, -1]
        matrix = np.zeros((2*len(labels), 3))
        matrix[::2, 0] = xy[:, 0]; matrix[1::2, 0] = xy[:, 1]
        matrix[::2, 1] = 1; matrix[1::2, 2] = 1
        scale, tx, ty = np.linalg.lstsq(matrix, generated.ravel(), rcond=None)[0]
        assert scale > 0
        residual = (generated-(xy*scale+[tx, ty]))/scale
        old_drift = np.linalg.norm(residual, axis=1)
        agent_drift = []
        for obj in state.objects.values():
            if obj.source == 'geometry_agent' and obj.type == 'point' and obj.label in labels and 'px' in obj.coords:
                agent_drift.append(float(np.linalg.norm(np.subtract(obj.coords['px'], contract['points'][obj.label]['px']))))
        edges = [pair for pair in raw['segments'].values() if all(n in contract['points'] for n in pair)]
        body = '\n'.join(r'\draw ('+a+')--('+b+');' for a, b in edges)
        body += '\n'+'\n'.join(r'\node[above] at ('+n+') {$'+n+'$};' for n in labels)
        source = r'\documentclass[tikz]{standalone}\begin{document}\begin{tikzpicture}'+body+r'\end{tikzpicture}\end{document}'
        emitted, _ = apply_coordinate_contract(source, contract)
        geometry = extract_geometry(emitted)
        recovered = np.array([geometry['points'][n] for n in labels])/contract['scale']
        recovered[:, 0] += contract['origin_px'][0]
        recovered[:, 1] = contract['origin_px'][1]-recovered[:, 1]
        new_drift = np.linalg.norm(recovered-measured, axis=1)
        assert max(new_drift) <= np.sqrt(2)*.0005/contract['scale']+1e-10
        assert sorted(geometry['segments'].values()) == sorted(edges)
        compiled = compile_tikz(emitted, out_dir=ROOT/'.cache/coordinate_handoff'/stem, stem='measurement_export')
        assert compiled['ok'], compiled.get('errors')
        records.append({'stem': stem, 'n_points': len(labels), 'n_edges': len(edges),
                        'state_sha256': hashlib.sha256(state_path.read_bytes()).hexdigest(),
                        'old_raw_tex_sha256': hashlib.sha256(raw_path.read_bytes()).hexdigest(),
                        'old_raw_fitted_drift_rms_px': float(np.sqrt(np.mean(old_drift**2))),
                        'old_raw_fitted_drift_max_px': float(max(old_drift)),
                        'agent_rewrite_max_px': max(agent_drift, default=0),
                        'deterministic_export_max_px': float(max(new_drift)), 'compiled': True})
    out = ROOT/'results/latest'
    report = {'schema': 'cv-handoff-audit.v1', 'reference_used': False, 'model_calls': 0,
              'scope': 'Coordinate transport only: old generated topology reused in a minimal straight-line document. Not a regenerated end-to-end or ground-truth geometry comparison.',
              'old_drift_definition': 'Best x-right/y-flipped uniform scale and translation fit to current CV bindings; residual in pixels, not an error against source-code ground truth.',
              'cases': records}
    (out/'coordinate_handoff_audit.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    lines = ['# CV坐标传递核验', '',
             '只核验测量坐标的传递精度，不读取参考清单，不调用模型。复用旧代码中受支持的命名直线边，生成简化核验文档；三张均编译通过。这不是重新生成的e2e结果，也不是MAE/MRE评测。', '',
             '| 图片 | 点数 | Geometry Agent最大改写（px） | 旧生成代码拟合后RMS偏移（px） | 程序导出最大偏移（px） |',
             '|---|---:|---:|---:|---:|']
    for r in records:
        lines.append(f"| {r['stem']} | {r['n_points']} | {r['agent_rewrite_max_px']:.6f} | {r['old_raw_fitted_drift_rms_px']:.6f} | {r['deterministic_export_max_px']:.3g} |")
    lines += ['', '旧代码偏移使用最佳统一缩放和平移拟合消除无害坐标系差异，并按约定翻转y轴。它衡量相对CV测量的偏移，不代表CV本身比参考真值准确。程序坐标统一三位小数，每轴舍入误差不超过0.0005个TikZ单位；约束推断与曲线参数正确性需另行验证。', '']
    (out/'coordinate_handoff_audit.md').write_text('\n'.join(lines), encoding='utf-8')
    print('\n'.join(lines))


if __name__ == '__main__':
    main()
