from pathlib import Path
from types import SimpleNamespace
import hashlib

import numpy as np
import pytest

from geoagent.evaluation.structure import backend, core_drawing, freeze_reference, source_geometry, score


def stroke(a, b, source):
    a, b = np.array(a, float), np.array(b, float)
    return SimpleNamespace(a=a, b=b, source=source, dashed=False, length=float(np.linalg.norm(b-a)))


def drawing(strokes, points=None, labels=None):
    return SimpleNamespace(strokes=strokes, points=points or {}, labels=labels or [], curves=[],
                           unsupported=[], excluded=[])


def test_named_square_glyph_requires_body_rays_and_keeps_input_unchanged():
    body = [stroke((0, 0), (4, 0), "base"), stroke((0, 0), (0, 3), "side")]
    glyph = [stroke((0, 0), (.2, 0), "glyph"), stroke((.2, 0), (.2, .2), "glyph"),
             stroke((.2, .2), (0, .2), "glyph")]
    original = drawing(body + glyph)
    filtered, audit = core_drawing(original)
    assert filtered.strokes == body
    assert audit["removed_strokes"] == 3
    assert len(original.strokes) == 5
    isolated, isolated_audit = core_drawing(drawing(glyph))
    assert len(isolated.strokes) == 3
    assert isolated_audit["removed_strokes"] == 0


def test_visible_label_protects_small_real_geometry():
    body = [stroke((0, 0), (4, 0), "base"), stroke((0, 0), (0, 3), "side")]
    small = [stroke((0, 0), (.2, 0), "polygon"), stroke((.2, 0), (.2, .2), "polygon"),
             stroke((.2, .2), (0, .2), "polygon")]
    d = drawing(body + small, labels=[{"text": "Q", "position": np.array([.2, .2])}])
    filtered, audit = core_drawing(d)
    assert len(filtered.strokes) == 5
    assert audit["removed_strokes"] == 0


def test_split_named_elbow_is_excluded_but_real_short_branch_is_kept():
    body = [stroke((0, 0), (4, 0), "base"), stroke((0, 0), (0, 3), "side")]
    elbow = [stroke((.2, 0), (.2, .2), "first"), stroke((0, .2), (.2, .2), "second")]
    branch = stroke((2, 0), (2, .2), "real branch")
    filtered, audit = core_drawing(drawing(body + elbow + [branch]))
    assert len(filtered.strokes) == 3
    assert any(s is branch for s in filtered.strokes)
    assert audit["removed_strokes"] == 2


def test_small_nonorthogonal_path_is_not_discarded():
    body = [stroke((0, 0), (4, 0), "base"), stroke((0, 0), (0, 3), "side")]
    path = [stroke((0, 0), (.2, 0), "path"), stroke((.2, 0), (.3, .2), "path")]
    filtered, audit = core_drawing(drawing(body + path))
    assert len(filtered.strokes) == 4
    assert audit["removed_strokes"] == 0


@pytest.fixture
def parser_backend():
    try:
        return backend()
    except RuntimeError as exc:
        pytest.skip(str(exc))


def write_tex(path, body):
    path.write_text(r"\documentclass[tikz]{standalone}\begin{document}\begin{tikzpicture}" + body
                    + r"\end{tikzpicture}\end{document}", encoding="utf-8")
    return path


TRIANGLE = r"""
\coordinate (p7) at (0,0);\coordinate (q8) at (4,0);\coordinate (r9) at (0,3);
\draw (p7)--(q8)--(r9)--cycle;
\node at (p7) {$A$};\node at (q8) {$B$};\node at (r9) {$C$};
"""


def test_named_angle_pic_is_ignored_without_losing_its_host_line(tmp_path, parser_backend):
    gt, _, items = source_geometry(write_tex(tmp_path/'ref.tex', TRIANGLE))
    annotated = TRIANGLE.replace(
        r'\draw (p7)--(q8)--(r9)--cycle;',
        r'\draw (p7)--(q8)--(r9)--cycle pic[draw,angle radius=2mm] {right angle=q8--p7--r9};',
    ) + r'\draw pic[draw] {angle=r9--q8--p7};'
    pred, _, _ = source_geometry(write_tex(tmp_path/'pred.tex', annotated))
    result = score(gt, pred, items)
    assert result['line_coverage'] == 1
    assert result['angle']['mean'] == 0
    assert result['length_ratio']['mean'] == 0


def test_label_immediately_after_font_selection_keeps_its_binding(tmp_path, parser_backend):
    annotated = TRIANGLE.replace('{$A$}', r'{\fontsize{10}{12}\selectfont$A$}')
    graph, _, _ = source_geometry(write_tex(tmp_path/'font.tex', annotated))
    assert graph.bindings['A']['xy'] == [0.0, 0.0]


def test_bold_math_preserves_visible_label_binding(tmp_path, parser_backend):
    annotated = TRIANGLE.replace('{$A$}', r'{\fontsize{19}{22.8}\selectfont{\boldmath$A$}}')
    graph, _, _ = source_geometry(write_tex(tmp_path/'bold.tex', annotated))
    assert graph.bindings['A']['xy'] == [0.0, 0.0]


def test_full_cohort_includes_an_image_with_all_items_missing():
    from scripts.merge_evaluation_results import full_cohort_geometry

    rows = {'model': {
        'measured': {'angle_checks': [{'error': 10.}, {'error': 30.}], 'ratio_checks': [{'error': 2.}]},
        'missing': {'angle_checks': [{'error': None}], 'ratio_checks': [{'error': None}]},
    }}
    result = full_cohort_geometry(rows, ['measured', 'missing'])
    assert result['angle']['n_images'] == result['ratio']['n_images'] == 2
    assert result['angle']['means']['model'] == 100.
    assert result['ratio']['means']['model'] == 1.


def test_named_intersections_follow_explicit_sort_path(tmp_path, parser_backend):
    graph, _, _ = source_geometry(write_tex(tmp_path/'intersection.tex', r"""
\coordinate (L) at (-2,0);\coordinate (R) at (2,0);
\draw[name path=ring] (0,0) circle (1);
\draw[name path=axis] (R)--(L);
\path[name intersections={of=ring and axis,sort by=axis,by={P,Q}}];
\node at (P) {$A$};\node at (Q) {$B$};
"""))
    assert graph.bindings['A']['xy'] == [1.0, 0.0]
    assert graph.bindings['B']['xy'] == [-1.0, 0.0]


def test_reference_intersection_order_updates_dependent_drawn_connections(tmp_path, parser_backend):
    path = write_tex(tmp_path/'circle.tex', r"""
\path[name path=ring] (0,0) circle (1);
\draw[name path=axis] (-2,0)--(2,0);
\path[name intersections={of=ring and axis,by=E}];
\coordinate (D) at (0,-1);
\draw (E)--(D);
\node at (E) {$E$};\node at (D) {$D$};
""")
    original = path.read_bytes()
    spec = {'source_sha256': hashlib.sha256(original).hexdigest(), 'reason': 'Verified path order',
            'intersection_order': [{'paths': ['ring', 'axis'], 'sort_by': 'axis'}]}
    frozen = freeze_reference(path, {path.stem: spec})
    assert path.read_bytes() == original
    assert frozen['points']['E']['xy'] == [-1.0, 0.0]
    assert ['D', 'E'] in frozen['edges']
    assert frozen['audit']['reviewed_reference_corrections'][0]['type'] == 'intersection_order'


def test_orthogonal_path_operator_contributes_both_drawn_legs(tmp_path, parser_backend):
    graph, _, items = source_geometry(write_tex(tmp_path/'elbow.tex', r"""
\coordinate (A) at (0,0);\coordinate (B) at (3,3);\coordinate (C) at (0,3);
\draw (A) |- (B);
\node at (A) {$A$};\node at (B) {$B$};\node at (C) {$C$};
"""))
    assert {tuple(graph.label_names[i] for i in edge) for edge in items['edges']} == {('A','C'),('B','C')}


def test_calc_physical_distance_is_not_a_fraction_of_the_edge(tmp_path, parser_backend):
    graph, _, _ = source_geometry(write_tex(tmp_path/'distance.tex', TRIANGLE + r"""
\coordinate (Q) at ($(p7)!2.8mm!(q8)$);
\node at (Q) {$Q$};
"""))
    assert graph.bindings['Q']['xy'] == pytest.approx([.28, 0.])


def test_nested_rotated_calc_and_foreach_label_bindings(tmp_path, parser_backend):
    body = r"""
\coordinate (P) at (0,0);\coordinate (R) at (4,0);
\coordinate (Q) at ($($(P)!{0.5cm}!(R)$)!{0.5cm}!90:(R)$);
\draw (P)--(R)--(Q)--cycle;
\foreach \p/\anchor in {P/{above left},Q/{above},R/{right}} {
  \node[\anchor] at (\p) {$\p$};
}
"""
    graph, _, items = source_geometry(write_tex(tmp_path/'nested.tex', body))
    assert graph.bindings['Q']['xy'] == pytest.approx([.5, .5])
    assert set(graph.label_names) == {'P', 'Q', 'R'}
    assert len(items['edges']) == 3


def test_projection_arc_intersection_and_unbraced_label_loop(tmp_path, parser_backend):
    body = r"""
\coordinate (A) at (0,0);\coordinate (B) at (4,0);\coordinate (C) at (2,3);
\tkzDefPointBy[projection=onto A--B](C) \tkzGetPoint{D}
\path[name path=arm] (2,-3)--(2,3);
\path[name path=upper] (4,0) arc (0:180:2);
\path[name intersections={of=arm and upper,by=E}];
\draw (A)--(B)--(C)--cycle;
\draw (C)--(D);
\foreach \p/\pos in {A/left,B/right,C/above,D/below,E/right}
  \fill (\p) circle (.3pt) node[\pos] {$\p$};
"""
    graph, _, _ = source_geometry(write_tex(tmp_path/'constructions.tex', body))
    assert graph.bindings['D']['xy'] == pytest.approx([2, 0])
    assert graph.bindings['E']['xy'] == pytest.approx([2, 2])


def test_shifted_intersection_and_let_rotation(tmp_path, parser_backend):
    body = r"""
\coordinate (A) at (0,0);\coordinate (B) at (2,0);\coordinate (C) at (2,2);
\coordinate (K) at (intersection of A--[shift={(0,1)}]A and C--(0,2));
\path let \p1 = ($(B)-(A)$), \n1 = {atan2(\y1,\x1)+90}, \n2 = {veclen(\x1,\y1)}
  in coordinate (R) at ($(A)+(\n1:\n2)$);
\node at (K) {$K$};\node at (R) {$R$};
"""
    graph, _, _ = source_geometry(write_tex(tmp_path/'let.tex', body))
    assert graph.bindings['K']['xy'] == pytest.approx([0, 2])
    assert graph.bindings['R']['xy'] == pytest.approx([0, 2])


def test_curve_operations_keep_adjacent_straight_segments(tmp_path, parser_backend):
    body = r"""
\coordinate (A) at (0,0);\coordinate (B) at (2,0);\coordinate (C) at (3,2);
\coordinate (D) at (0,2);
\draw (A)--(B) .. controls +(1,0) and +(-1,0) .. (C) to[out=170,in=0] (D)--(A);
\draw (A) circle ({sqrt(2)});
\node at (A) {$A$};\node at (B) {$B$};\node at (C) {$C$};\node at (D) {$D$};
"""
    graph, _, items = source_geometry(write_tex(tmp_path/'curves.tex', body))
    assert {tuple(graph.label_names[i] for i in edge) for edge in items['edges']} == {('A', 'B'), ('A', 'D')}
    assert graph.curves[0]['radius'] == pytest.approx(np.sqrt(2))


def test_visible_labels_follow_aliases_not_coordinate_spelling(tmp_path, parser_backend):
    ref = write_tex(tmp_path/'ref.tex', TRIANGLE)
    gt, _, items = source_geometry(ref)
    variant = TRIANGLE.replace('(p7)', '(z)').replace('(q8)', '(A)').replace('(r9)', '(B)')
    pred, _, _ = source_geometry(write_tex(tmp_path/'pred.tex', variant))
    result = score(gt, pred, items)
    assert result['angle']['mean'] == 0
    assert result['length_ratio']['mean'] == 0
    assert pred.bindings['B']['coordinate_aliases'] == ['A']


def test_swapped_visible_labels_are_not_rescued_by_geometric_matching(tmp_path, parser_backend):
    gt, _, items = source_geometry(write_tex(tmp_path/'ref.tex', TRIANGLE))
    pred, _, _ = source_geometry(write_tex(tmp_path/'pred.tex', TRIANGLE.replace('{$B$}', '{$temp$}').replace('{$C$}', '{$B$}').replace('{$temp$}', '{$C$}')))
    result = score(gt, pred, items)
    assert result['angle']['mean'] > 10
    assert result['length_ratio']['mean'] > .1
    assert result['alignment']['method'] == 'exact_visible_label'


def test_unlabelled_intersections_and_helpers_are_excluded(tmp_path, parser_backend):
    graph, _, items = source_geometry(write_tex(tmp_path/'points.tex', TRIANGLE + r'\coordinate (helper) at (1,0);\draw (2,-1)--(2,4);'))
    assert graph.label_names == ['A', 'B', 'C']
    assert len(graph.points) == 3
    assert len(items['angles']) == 3


def test_missing_and_conflicting_labels_are_unavailable_not_snapped(tmp_path, parser_backend):
    gt, _, items = source_geometry(write_tex(tmp_path/'ref.tex', TRIANGLE))
    for i, variant in enumerate((TRIANGLE.replace(r'\node at (q8) {$B$};', ''), TRIANGLE + r'\node at (r9) {$B$};')):
        pred, _, _ = source_geometry(write_tex(tmp_path/f'pred{i}.tex', variant))
        result = score(gt, pred, items)
        assert result['missing_labels'] == ['B']
        assert all(c['error'] is None for c in result['angle_checks'])
        assert result['line_coverage'] == pytest.approx(1/3)


def test_font_markup_and_presentation_offsets_keep_binding(tmp_path, parser_backend):
    text = TRIANGLE.replace('at (q8) {$B$}', r'[above,xshift=2pt] at (q8) {\fontsize{14}{17}\selectfont $\mathbf{B}$}')
    graph, _, _ = source_geometry(write_tex(tmp_path/'font.tex', text))
    assert graph.label_names == ['A', 'B', 'C']
    assert graph.bindings['B']['xy'] == [4, 0]


def test_explicit_expression_binding_overrides_same_name_coordinate(tmp_path, parser_backend):
    text = TRIANGLE + r'\coordinate (E) at (0,3);\node at (intersection of p7--q8 and {2,-1}--{2,1}) {$E$};'
    graph, _, _ = source_geometry(write_tex(tmp_path/'binding.tex', text))
    assert np.allclose(graph.bindings['E']['xy'], [2, 0])
    assert graph.extraction_audit['same_name_coordinate_conflicts'][0]['label'] == 'E'


@pytest.mark.parametrize('markup', [r'\textbf{B}', r'\ensuremath{\mathbf{B}}', r'\textit{B}'])
def test_text_font_wrappers_preserve_visible_label(tmp_path, parser_backend, markup):
    graph, _, _ = source_geometry(write_tex(tmp_path/'font.tex', TRIANGLE.replace('$B$', markup)))
    assert graph.label_names == ['A', 'B', 'C']
    assert graph.bindings['B']['xy'] == [4, 0]


def test_6986_real_reference_uses_visible_E_binding(parser_backend):
    ref = Path(__file__).resolve().parents[1]/'data/test/latex/6986_q_fig1.tex'
    graph, _, items = source_geometry(ref)
    assert np.allclose(graph.bindings['E']['xy'], [0, 3.165564918258002])
    assert not np.allclose(graph.bindings['E']['xy'], graph.bindings['C']['xy'])
    assert graph.label_names == ['A', 'B', 'C', 'D', 'E', 'O']
    result = score(graph, graph, items)
    assert result['angle']['mean'] == 0
    assert result['length_ratio']['mean'] == 0


def test_reviewed_E_correction_rebuilds_all_dependent_measurements(parser_backend):
    import json
    from geoagent.evaluation.structure import freeze_reference
    root = Path(__file__).resolve().parents[1]
    spec = json.loads((root/'data/test/geometry_reference/corrections.json').read_text(encoding='utf-8'))['cases']
    path = root/'data/test/latex/6986_q_fig1.tex'
    original = freeze_reference(path)
    fixed = freeze_reference(path, spec)
    xy = fixed['points']['E']['xy']
    assert np.linalg.norm(xy) == pytest.approx(3, abs=1e-12)
    assert xy[1] > 0
    assert xy == pytest.approx([-.16100287861652163, 2.995676563495665])
    assert fixed['points']['E']['source_xy'] == original['points']['E']['xy']
    before = {tuple(tuple(e) for e in i['labels']):i['target'] for i in original['ratios']}
    for item in fixed['ratios']:
        key = tuple(tuple(e) for e in item['labels'])
        if any('E' in e for e in item['labels']):
            assert item['target'] != before[key]
        else:
            assert item['target'] == before[key]
    assert fixed['self_check']['ratio_mre'] == 0
    spec[path.stem]['source_sha256'] = 'wrong'
    with pytest.raises(ValueError, match='source hash changed'):
        freeze_reference(path, spec)


def test_reviewed_circle_center_and_circle_point_corrections(parser_backend):
    import json
    from geoagent.evaluation.structure import freeze_reference
    root=Path(__file__).resolve().parents[1]
    specs=json.loads((root/'data/test/geometry_reference/corrections.json').read_text(encoding='utf-8'))['cases']
    path=root/'data/test/latex/6983_q_fig1.tex'
    old=freeze_reference(path);fixed=freeze_reference(path,specs)
    assert fixed['points']['O']['xy']==[0,0]
    assert np.linalg.norm(fixed['points']['E']['xy'])==pytest.approx(2,abs=1e-12)
    a,b=old['points']['E']['xy'],fixed['points']['E']['xy']
    assert a[0]*b[1]-a[1]*b[0]==pytest.approx(0,abs=1e-12)
    for name in ('A','B','C','D'):assert fixed['points'][name]['xy']==old['points'][name]['xy']
    assert fixed['self_check']['coverage']==1
    assert fixed['self_check']['ratio_mre']==0
    assert fixed['audit']['reviewed_reference_corrections'][1]['transported_incident_endpoints']==1
    assert '1630_s_fig1' not in specs and '411_q_fig1' not in specs


def test_nonuniform_coordinate_bases_are_applied(tmp_path, parser_backend):
    path = write_tex(tmp_path/'basis.tex', TRIANGLE)
    path.write_text(path.read_text().replace(r'\begin{tikzpicture}', r'\begin{tikzpicture}[x=2cm,y=3cm]'))
    graph, _, _ = source_geometry(path)
    assert graph.bindings['B']['xy'] == [8, 0]
    assert graph.bindings['C']['xy'] == [0, 9]


def test_missing_strokes_remain_unavailable_even_if_labels_exist(tmp_path, parser_backend):
    gt, _, items = source_geometry(write_tex(tmp_path/'ref.tex', TRIANGLE))
    pred, _, _ = source_geometry(write_tex(tmp_path/'pred.tex', TRIANGLE.replace(r'\draw (p7)--(q8)--(r9)--cycle;', r'\draw (p7)--(q8);')))
    result = score(gt, pred, items)
    assert result['angle']['mean'] is None
    assert all(c['unavailable_reasons'] == ['segment_not_drawn'] for c in result['angle_checks'])


def test_composite_labelled_segments_are_kept(tmp_path, parser_backend):
    text = TRIANGLE + r'\node at (2,0) {$M$};'
    graph, _, items = source_geometry(write_tex(tmp_path/'composite.tex', text))
    edges = [[graph.label_names[i] for i in e] for e in items['edges']]
    assert ['A', 'B'] in edges
    assert ['A', 'M'] in edges
    assert ['B', 'M'] in edges


def test_reference_cache_can_score_without_reference_source(tmp_path, parser_backend):
    import json
    from geoagent.evaluation.structure import freeze_reference, load_reference
    path = write_tex(tmp_path/'ref.tex', TRIANGLE)
    data = freeze_reference(path)
    assert data['angles'][0]['points'] == ['B', 'A', 'C']
    cache = tmp_path/'ref.json'
    cache.write_text(json.dumps(data), encoding='utf-8')
    pred, _, _ = source_geometry(path)
    path.unlink()
    gt, items = load_reference(cache)
    assert score(gt, pred, items)['angle']['mean'] == 0
    data['implementation_sha256'] = 'changed'
    cache.write_text(json.dumps(data), encoding='utf-8')
    with pytest.raises(ValueError, match='stale'):
        load_reference(cache)


def test_marker_scale_does_not_change_labelled_measurements(tmp_path, parser_backend):
    gt, _, items = source_geometry(write_tex(tmp_path/'ref.tex', TRIANGLE))
    for i, size in enumerate((.1, .2, .3)):
        glyph = rf'\coordinate (x) at ({size},0);\coordinate (xy) at ({size},{size});\coordinate (y) at (0,{size});\draw (x)--(xy)--(y);'
        pred, _, _ = source_geometry(write_tex(tmp_path/f'pred{i}.tex', TRIANGLE+glyph))
        result = score(gt, pred, items)
        assert result['angle']['mean'] == 0
        assert result['length_ratio']['mean'] == 0
        assert len(pred.points) == 3


def test_missing_program_keeps_reference_denominator(tmp_path, parser_backend):
    from scripts.evaluate_structure_ab import _evaluate_group, _group_summary
    gt, _, items = source_geometry(write_tex(tmp_path/'ref.tex', TRIANGLE))
    rows = _evaluate_group({}, {'missing': (gt, items)}, ['missing'], workers=1)
    summary = _group_summary(rows)
    assert summary['n_unparseable'] == 1
    assert summary['angle_reference'] == 3
    assert summary['angle_coverage'] == 0
    assert len(rows['missing']['angle_checks']) == 3
    assert rows['missing']['angle_mae'] is None
    quality = summary['geometry_quality']
    assert (quality['edge_f1'], quality['point_error']) == (0., 1.)


QUADRILATERAL = r"""
\coordinate (A) at (0,0); \coordinate (B) at (4,0);
\coordinate (C) at (3,2); \coordinate (D) at (0,3);
\draw (A)--(B)--(C)--(D)--cycle;
\node at (A) {$A$}; \node at (B) {$B$};
\node at (C) {$C$}; \node at (D) {$D$};
"""


@pytest.fixture
def quality_probe(tmp_path, parser_backend):
    from geoagent.evaluation.geometry_quality import score_geometry_quality
    ref, _, items = source_geometry(write_tex(tmp_path/'ref.tex', QUADRILATERAL))

    def measure(body):
        pred, _, _ = source_geometry(write_tex(tmp_path/'pred.tex', body))
        return score_geometry_quality(ref, items['edges'], pred)

    return measure


def test_geometry_quality_invariant_to_similarity_and_equivalent_strokes(quality_probe):
    body = QUADRILATERAL.replace(r'\draw (A)--(B)', r'\coordinate (Mid) at (2,0); \draw (A)--(Mid)--(B)')
    body += r'\draw pic[draw] {right angle=B--A--D};'
    body = r'\begin{scope}[scale=2,rotate=31,shift={(4,-7)}]' + body + r'\end{scope}'
    body = body.replace(r'\node at (A)', r'\node[xshift=2pt,above] at (A)')
    row = quality_probe(body)
    assert row['edges']['f1'] == 1
    assert row['points']['mean'] == pytest.approx(0., abs=1e-12)


def test_geometry_quality_edge_f1_penalizes_extra_and_missing_connections(quality_probe):
    extra = quality_probe(QUADRILATERAL + r'\draw (A)--(C);')
    missing = quality_probe(QUADRILATERAL.replace('(D)--cycle', '(D)'))
    assert extra['edges']['recall'] == 1.
    assert extra['edges']['precision'] == pytest.approx(.8)
    assert extra['edges']['f1'] == pytest.approx(8/9)
    assert missing['edges']['precision'] == 1.
    assert missing['edges']['recall'] == pytest.approx(.75)
    assert missing['edges']['f1'] == pytest.approx(6/7)
    assert extra['points']['mean'] == missing['points']['mean'] == pytest.approx(0., abs=1e-12)


def test_geometry_quality_point_error_detects_deformation_and_mirror(quality_probe):
    slight, larger = [quality_probe(QUADRILATERAL.replace('(3,2)', f'({x},2)')) for x in (3.1, 3.5)]
    mirror = quality_probe(r'\begin{scope}[xscale=-1]' + QUADRILATERAL + r'\end{scope}')
    assert slight['edges']['f1'] == larger['edges']['f1'] == mirror['edges']['f1'] == 1.
    assert 0 < slight['points']['mean'] < larger['points']['mean'] < mirror['points']['mean']


def test_geometry_quality_wrong_names_and_insufficient_matches(quality_probe):
    renamed = quality_probe(QUADRILATERAL.replace('{$D$}', '{$X$}'))
    assert renamed['edges']['f1'] == pytest.approx(.5)
    assert renamed['points']['mean'] == pytest.approx(.25)
    insufficient = quality_probe(QUADRILATERAL.replace('{$D$}', '{$X$}').replace('{$C$}', '{$Y$}'))
    assert insufficient['points']['mean'] == 1.
    assert not insufficient['points']['aligned']


