import pytest
from geoagent.state.schemas import GeometricEvidenceState,GeometryObject
from geoagent.state.measured_topology import measured_topology


def test_source_measured_shallow_bend_is_preserved_as_evidence():
    state=GeometricEvidenceState(image_path='source.png',image_size={'width':100,'height':100})
    for n,p in {'A':[0,0],'E':[10,4],'C':[40,22]}.items():
        state.add_object(GeometryObject(id=n,type='point',label=n,coords={'px':p},source='cv:bind_point_labels'))
    for name,a,b in [('AE',[0,0],[10,4]),('EC',[10,4],[40,22])]:
        state.add_object(GeometryObject(id=name,type='segment',coords={'a_px':a,'b_px':b},source='cv:detect_lines'))
    evidence=measured_topology(state)
    assert evidence['supported_shallow_bends'][0]['labels']==['A','E','C']
    assert evidence['supported_shallow_bends'][0]['turn_deg']>5
    # An inferred symbolic edge alone cannot certify a bend in the source image.
    state.objects['EC'].source='geometry_agent'
    assert not measured_topology(state)['supported_shallow_bends']


def test_free_endpoint_candidates_do_not_steal_a_nearby_true_junction():
    from pathlib import Path
    from geoagent.cv_tools.label_detection import bind_point_labels
    root=Path(__file__).resolve().parents[1]
    result=bind_point_labels(root/'data/test/image/6987_q_fig1.png',visualize=False)
    points={b['char']:b['point_px'] for b in result['results']['bindings']}
    assert points['C']==pytest.approx([440.09,300.17],abs=1)
    assert points['B']==pytest.approx([48.46,299.58],abs=1)


def test_dashed_span_ends_cannot_steal_existing_interior_label_bindings():
    from pathlib import Path
    from geoagent.cv_tools.label_detection import bind_point_labels
    root=Path(__file__).resolve().parents[1]
    result=bind_point_labels(root/'data/test/image/1615_s_fig1.png',visualize=False)
    points={b['char']:b['point_px'] for b in result['results']['bindings']}
    assert points['G']==pytest.approx([194.57,216.94],abs=1)
    assert points['N']==pytest.approx([158.39,287.6],abs=1)
    assert points['E']==pytest.approx([106.01,181.24],abs=1)
    assert result['params']['recovered_endpoint_bindings']==0
