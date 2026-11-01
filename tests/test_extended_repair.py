import numpy as np
import pytest

from geoagent.state.tikz_repair import repair_tikz_constraints
from geoagent.state.tikz_geometry import extract_geometry
from geoagent.state.optimize_relations import optimize_coordinates


DOC=r"""\begin{tikzpicture}
\coordinate (A) at (0,0);\coordinate (B) at (4,.01);
\coordinate (C) at (4.01,3);\coordinate (D) at (.01,3.01);
\draw (A)--(B)--(C)--(D)--cycle;
\end{tikzpicture}"""


def test_relaxation_is_between_original_and_full_projection():
    full,a=repair_tikz_constraints(DOC)
    half,b=repair_tikz_constraints(DOC,relaxation=.5)
    original=extract_geometry(DOC)['points'];f=extract_geometry(full)['points'];h=extract_geometry(half)['points']
    assert a['applied'] and b['applied']
    assert b['max_export_error_deg']>a['max_export_error_deg']
    for n in original:np.testing.assert_allclose(h[n],(np.array(original[n])+f[n])/2,atol=1e-14)


def test_relation_family_filter_is_respected():
    _,r=repair_tikz_constraints(DOC,relation_types=('parallel',))
    assert r['applied']
    assert {x['type'] for x in r['accepted']}=={'parallel'}


def test_partial_projection_does_not_compound_on_identical_source():
    half,r=repair_tikz_constraints(DOC,relaxation=.5)
    repeated,second=repair_tikz_constraints(half,relaxation=.5)
    assert r['applied'] and not second['applied']
    assert repeated==half and second['reason']=='already_processed'


def test_full_projection_marker_is_invalidated_by_configuration_change():
    full,r=repair_tikz_constraints(DOC)
    repeated,again=repair_tikz_constraints(full)
    assert r['applied'] and repeated==full and again['reason']=='already_processed'
    _,changed=repair_tikz_constraints(full,angle_tol_deg=.4)
    assert changed['reason']!='already_processed'


def test_curve_profile_does_not_change_straight_program_policy():
    options={'curve_policy':'freeze','relation_types':['parallel']}
    _,straight=repair_tikz_constraints(DOC,curve_options=options)
    assert {r['type'] for r in straight['accepted']}=={'parallel','perpendicular'}
    curved=DOC.replace(r'\begin{tikzpicture}',r'\begin{tikzpicture}\coordinate (O) at (10,10);\draw (O) circle (1);')
    _,circle=repair_tikz_constraints(curved,curve_options=options)
    assert circle['applied'] and circle['curve_options_applied']==options
    assert {r['type'] for r in circle['accepted']}=={'parallel'}


def test_fractional_incidence_has_the_requested_offset_target():
    g={'points':{'A':[0,0],'B':[4,0],'C':[2,.006],'D':[0,3],'E':[4,3]},
       'segments':{'AB':['A','B'],'DE':['D','E'],'DC':['D','C']}}
    out,r=optimize_coordinates(g,incidence_mode='snap',incidence_strength=.5,topology_tol_rel=.002)
    assert r['applied']
    a,b,c=(np.asarray(out['points'][n]) for n in ('A','B','C'))
    edge=b-a
    # Constraint uses the initial base length; this is the exact target it solves.
    assert (edge[0]*(c-a)[1]-edge[1]*(c-a)[0])/4==pytest.approx(.003,abs=1e-9)


@pytest.mark.parametrize('kwargs',[{'relaxation':0},{'relaxation':1.1},{'incidence_strength':2},{'relation_types':['equal_length']}])
def test_invalid_extended_options_are_noops(kwargs):
    tex,r=repair_tikz_constraints(DOC,**kwargs)
    assert tex==DOC and r['reason']=='invalid_limits'
