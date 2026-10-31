from __future__ import annotations

import copy
import importlib.util
from pathlib import Path

import numpy as np
import pytest

from geoagent.state.optimize_relations import optimize_coordinates
from geoagent.state.relation_candidates import numeric_candidates

spec=importlib.util.spec_from_file_location("optimize_pilot",Path(__file__).resolve().parents[1]/"scripts/test_optimize_relations.py")
pilot=importlib.util.module_from_spec(spec)
spec.loader.exec_module(pilot)


def rectangle():
    return {"points":{"A":[0,0],"B":[4,0.01],"C":[4.01,3],"D":[0.01,3.01]},
            "segments":{"AB":["A","B"],"BC":["B","C"],"CD":["C","D"],"AD":["A","D"]}}


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
    with pytest.raises(ValueError,match="Only parallel/perpendicular"):
        optimize_coordinates(rectangle(),[{"type":"equal_length","segments":["AB","CD"]}])


def test_export_round_trips_optimized_coordinates():
    before=rectangle();after,report=optimize_coordinates(before)
    tex="\n".join(rf"\coordinate ({name}) at ({xy[0]},{xy[1]});" for name,xy in before["points"].items())
    tex+=r"\draw(A)--(B)--(C)--(D)--cycle;"
    emitted=pilot.rewrite_tex(tex,before,after)
    parsed=pilot.extract_geometry(emitted)
    assert parsed["points"]==after["points"]
    assert "e-" not in emitted


def test_curves_are_deferred_but_vertex_dots_are_not():
    assert pilot.has_curves(r"\draw(O) circle(2);")
    assert not pilot.has_curves(r"\draw(A)--(B);\fill(A) circle(1pt);")
