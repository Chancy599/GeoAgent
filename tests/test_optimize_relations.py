from __future__ import annotations

import copy
import importlib.util
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw

from geoagent.state.optimize_relations import optimize_coordinates
from geoagent.state.relation_candidates import numeric_candidates
from geoagent.state.tikz_repair import repair_tikz_constraints

spec=importlib.util.spec_from_file_location("optimize_pilot",Path(__file__).resolve().parents[1]/"scripts/test_optimize_relations.py")
pilot=importlib.util.module_from_spec(spec)
spec.loader.exec_module(pilot)


def rectangle():
    return {"points":{"A":[0,0],"B":[4,0.01],"C":[4.01,3],"D":[0.01,3.01]},
            "segments":{"AB":["A","B"],"BC":["B","C"],"CD":["C","D"],"AD":["A","D"]}}


@pytest.mark.parametrize('source_bends', [False, True])
def test_collinear_repair_uses_source_ink_and_preserves_a_real_bend(tmp_path, source_bends):
    image = Image.new('L', (200, 130), 255)
    middle = (90, 64 if source_bends else 60)
    draw = ImageDraw.Draw(image)
    draw.line([(20, 60), middle], fill=0, width=2)
    for start in range(90, 160, 12):
        end = min(start + 7, 160)
        y = lambda x: middle[1] + (60-middle[1])*(x-90)/70
        draw.line([(start, y(start)), (end, y(end))], fill=0, width=2)
    path = tmp_path / 'source.png'
    image.save(path)
    tex = r'''
\begin{tikzpicture}
\coordinate (A) at (.800,-2.400);
\coordinate (B) at (3.600,-2.560);
\coordinate (C) at (6.400,-2.400);
\draw (A)--(B);
\draw[dashed] (B)--(C);
\end{tikzpicture}
'''
    options = dict(source_image=path, source_coordinates={'origin_px': [0, 0], 'scale': .04},
                   max_shift_rel=.025, collinear_max_turn_deg=8, relation_types=())
    assert repair_tikz_constraints(tex, enabled=False, **options)[0] == tex
    output, report = repair_tikz_constraints(tex, **options)
    if source_bends:
        assert output == tex and not report['source_collinear_candidates']
    else:
        assert report['applied']
        assert report['accepted'][0]['type'] == 'collinear'
        assert report['accepted'][0]['after_error_deg'] < .05
        assert r'\draw[dashed] (B)--(C);' in output


def test_joint_rectangle_and_redundant_constraints():
    geometry=rectangle();before=copy.deepcopy(geometry)
    after,report=optimize_coordinates(geometry)
    assert report["applied"]
    assert len(report["accepted"])==6
    assert report["max_after_error_deg"]<1e-8
    assert report["max_shift_rel"]<0.005
    assert geometry==before
    # One named vertex is shared across all incident edges by construction.
    assert np.linalg.norm(np.asarray(after["points"]["A"])-before["points"]["A"])>0


def test_foot_stays_on_base_and_does_not_cross_ends():
    geometry={"points":{"B":[0,0],"C":[4,0.03],"H":[2,0.015],"A":[1.99,3]},
              "segments":{"BC":["B","C"],"AH":["A","H"]}}
    after,report=optimize_coordinates(geometry)
    assert report["applied"]
    assert report["preserved_incidence_count"]==1
    b,c,h=(np.array(after["points"][n]) for n in ("B","C","H"))
    u,v=c-b,h-b
    assert abs(u[0]*v[1]-u[1]*v[0])<1e-10
    assert 0<float(v@u)/float(u@u)<1


def test_strict_movement_gate_returns_original():
    geometry=rectangle()
    after,report=optimize_coordinates(geometry,max_shift_rel=0)
    assert not report["applied"]
    assert after==geometry
    assert report["rejected"]


def test_conflicting_candidates_reject_weaker_hypothesis():
    geometry={"points":{"A":[0,0],"B":[3,0],"C":[0,2],"D":[3,2.01]},
              "segments":{"AB":["A","B"],"CD":["C","D"]}}
    candidates=[{"type":kind,"segments":["AB","CD"]} for kind in ("parallel","perpendicular")]
    after,report=optimize_coordinates(geometry,candidates)
    assert report["applied"]
    assert [r["type"] for r in report["accepted"]]==["parallel"]
    assert len(report["rejected"])==1
    assert report["max_length_change_rel"]<0.01


def test_equal_length_is_not_accepted():
    with pytest.raises(ValueError,match="Unknown directional constraint"):
        optimize_coordinates(rectangle(),[{"type":"equal_length","segments":["AB","CD"]}])


def test_export_round_trips_optimized_coordinates():
    before=rectangle();after,report=optimize_coordinates(before)
    tex="\n".join(rf"\coordinate ({name}) at ({xy[0]},{xy[1]});" for name,xy in before["points"].items())
    tex+=r"\draw(A)--(B)--(C)--(D)--cycle;"
    emitted=pilot.rewrite_tex(tex,before,after)
    parsed=pilot.extract_geometry(emitted)
    assert parsed['points']=={name:[float(f'{v:.3f}') for v in xy] for name,xy in after['points'].items()}
    assert "e-" not in emitted


def test_curves_are_deferred_but_vertex_dots_are_not():
    assert pilot.has_curves(r"\draw(O) circle(2);")
    assert not pilot.has_curves(r"\draw(A)--(B);\fill(A) circle(1pt);")
