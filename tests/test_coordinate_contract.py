from types import SimpleNamespace

import numpy as np
import pytest

from geoagent.agents.tikz_agent import TikZAgent, _geometry_digest
from geoagent.state.coordinate_contract import (
    apply_coordinate_contract, apply_reviewed_bindings, build_coordinate_contract, coordinate_block,
    restore_reviewed_bindings,
)
from geoagent.state.schemas import GeometricEvidenceState
from geoagent.state.tikz_geometry import extract_geometry


def state():
    s = GeometricEvidenceState(image_path='unused.png', image_size={'width': 500, 'height': 400})
    for label, xy in [('A', [47., 65.]), ('E', [138.07, 106.72]), ('C', [440.09, 300.17])]:
        s.add_object(dict(id=label, type='point', label=label, coords={'px': xy}, source='cv:bind_point_labels'))
        s.label_bindings[label] = label
        s.add_object(dict(id='agent_'+label, type='point', label=label, coords={'px': list(map(round, xy))}, source='geometry_agent'))
    return s


def doc(body):
    return r'\documentclass[tikz]{standalone}\begin{document}\begin{tikzpicture}'+body+r'\end{tikzpicture}\end{document}'


def test_measurements_survive_duplicate_rounded_agent_points_and_export():
    s = state()
    contract = build_coordinate_contract(s, {'suggested_scale': .02})
    assert contract['points']['E']['px'] == [138.07, 106.72]
    assert _geometry_digest(s, measured_labels=contract['points']) == '(no geometry objects yet)'
    tex, audit = apply_coordinate_contract(doc(r'\draw(A)--(E)--(C);\node at(E){$E$};'), contract)
    geometry = extract_geometry(tex)
    for label, point in contract['points'].items():
        x, y = geometry['points'][label]
        recovered = [x/contract['scale']+250, 200-y/contract['scale']]
        assert np.allclose(recovered, point['px'], atol=.0005/contract['scale']+1e-12, rtol=0)
    assert geometry['segments'] == {'A--E': ['A', 'E'], 'C--E': ['C', 'E']}
    assert audit['n_points'] == 3


def test_ambiguous_and_rejected_bindings_are_not_frozen():
    s = state()
    s.add_object(dict(id='glyph_E', type='label', label='E', attributes={'ambiguous': True}))
    s.objects['C'].status = 'rejected'
    contract = build_coordinate_contract(s)
    assert list(contract['points']) == ['A']


def test_reviewed_binding_can_move_a_letter_and_correct_ocr_without_moving_pixels():
    s = state()
    s.add_object(dict(id='apex', type='point', coords={'px': [250., 20.]}, source='cv:bind_point_labels'))
    rejected = apply_reviewed_bindings(s, [{'label':'B', 'point_id':'C', 'reason':'would steal C'}])
    assert not rejected and s.label_bindings['C'] == 'C'
    accepted = apply_reviewed_bindings(s, [
        {'label':'D', 'point_id':'C', 'replaces':'C', 'reason':'printed D at the right vertex'},
        {'label':'A', 'point_id':'apex', 'reason':'printed A at the apex'},
    ])
    assert set(accepted) == {'A','D'} and 'C' not in s.label_bindings
    assert s.objects['A'].coords['px'] == [47.,65.]
    contract = build_coordinate_contract(s)
    assert contract['points']['A']['px'] == [250.,20.]
    with pytest.raises(ValueError, match=r'Visible label A must use at \(A\)'):
        apply_coordinate_contract(doc(
            r'\node at(E){\fontsize{12}{14}\selectfont $A$};\node at(D){$D$};'
        ), contract)
    tex, _ = apply_coordinate_contract(doc(
        r'\node at(A){\fontsize{12}{14}\selectfont $\mathrm{A}$};\node at(D){$D$};'
    ), contract)
    assert r'\coordinate (A)' in tex
    s.label_bindings.update(A='A', C='C')
    restore_reviewed_bindings(s)
    assert s.label_bindings == {'A':'apex','E':'E','D':'C'}


@pytest.mark.parametrize('body', [
    r'\coordinate(E) at (1,2);',
    r'\coordinate(E) at (A);',
    r'\node(E) at(1,2){text};',
    r'\node at(1,2){$E$};',
    r'\begin{scope}\draw(A)--(E);\end{scope}',
    r'\draw[xscale=2](A)--(E);',
    r'\path(0,0) coordinate(E);',
    r'\draw[xshift=2pt](A)--(E);',
])
def test_incompatible_redefinitions_frames_and_label_bindings_rejected(body):
    with pytest.raises(ValueError):
        apply_coordinate_contract(doc(body), build_coordinate_contract(state()))


def test_repeated_exact_definitions_are_replaced_and_labels_can_be_offset():
    contract = build_coordinate_contract(state())
    tex, _ = apply_coordinate_contract(doc(coordinate_block(contract)+r'\node[xshift=2pt,above] at(E){$E$};'), contract)
    assert tex.count(r'\coordinate (E)') == 1
    assert 'xshift=2pt' in tex


def test_no_measurements_still_formats_coordinates():
    s = GeometricEvidenceState(image_path='unused.png')
    assert build_coordinate_contract(s) is None
    tex = doc(r'\draw(0,0)--(1,0);')
    assert r'(0.000,0.000)--(1.000,0.000)' in apply_coordinate_contract(tex, None)[0]


def test_agent_retries_coordinate_violation_and_injects_program_definitions(tmp_path):
    replies = iter([doc(r'\coordinate(E) at(0,0);'), doc(r'\draw(A)--(E)--(C);')])
    class Client:
        def build_content(self, text, images):
            assert 'PROGRAM-OWNED CV COORDINATES' in text
            return text
        def chat(self, messages, **kwargs):
            return SimpleNamespace(usage={}, tool_calls=[], text=next(replies))
    agent = TikZAgent(Client(), state(), tmp_path)
    agent._style_cache = {}
    result = agent.run('generate', 'draw')
    assert result['ok'] and result['coordinate_contract']['n_points'] == 3
    assert extract_geometry(result['tex'])['points']['E'] == build_coordinate_contract(state())['points']['E']['tikz']


def test_repair_with_new_coordinate_frame_does_not_reuse_previous_numbers(tmp_path):
    s = state()
    s.add_tikz_version(doc(r'\coordinate (A) at (99,99);'), agent='code_agent', mode='generate')
    s.meta['tikz_coordinate_contracts'] = {'1': {'enabled': False}}

    class Client:
        def build_content(self, text, images):
            assert 'SOURCE COORDINATE FRAME' in text
            assert 'Reconstruct ALL coordinates' in text
            assert '(99,99)' not in text
            return text

        def chat(self, messages, **kwargs):
            return SimpleNamespace(usage={}, tool_calls=[], text=doc(r'\draw(A)--(E)--(C);'))

    agent = TikZAgent(Client(), s, tmp_path)
    agent._style_cache = {}
    assert agent.run('repair', 'draw')['ok']


def test_coordinate_handoff_switch_is_independent_of_constraint_repair(monkeypatch):
    from geoagent.config import load_settings
    monkeypatch.setenv('GEOAGENT_PRESERVE_CV_COORDINATES', '0')
    assert load_settings().geometry.preserve_cv_coordinates is False
    settings = load_settings({'preserve_cv_coordinates': True, 'geometry_repair': False})
    assert settings.geometry.preserve_cv_coordinates is True
    assert settings.geometry.enabled is False
