from __future__ import annotations

import copy
import importlib.util
from pathlib import Path

from geoagent.state.relation_candidates import numeric_candidates, pair_metrics, accepts, DEFAULT_LIMITS

spec=importlib.util.spec_from_file_location("numeric_pilot",Path(__file__).resolve().parents[1]/"scripts/test_numeric_relations.py")
pilot=importlib.util.module_from_spec(spec)
spec.loader.exec_module(pilot)


def test_two_types_only_and_input_not_mutated():
    geometry={"points":{"A":[0,0],"B":[2,0],"C":[0,2],"D":[2,2]},
              "segments":{"AB":["A","B"],"CD":["C","D"],"AC":["A","C"]}}
    before=copy.deepcopy(geometry)
    rows=numeric_candidates(geometry)
    assert {r["type"] for r in rows}=={"parallel","perpendicular"}
    assert geometry==before
    assert any(r["type"]=="parallel" and r["segments"]==["AB","CD"] for r in rows)


def test_parallel_rejects_same_support_and_shared_vertex():
    p={"A":[0,0],"B":[2,0],"C":[4,0],"D":[4,0.02]}
    assert not accepts("parallel",pair_metrics(p,["A","B"],["B","C"]),DEFAULT_LIMITS)
    assert not accepts("parallel",pair_metrics(p,["A","D"],["B","D"]),DEFAULT_LIMITS)


def test_direction_and_scale_do_not_change_candidates():
    g={"points":{"A":[1,1],"B":[4,1],"C":[1,4],"D":[4,4]},
       "segments":{"AB":["A","B"],"CD":["C","D"],"AC":["A","C"]}}
    keys=lambda geom:{(r["type"],*r["segments"]) for r in numeric_candidates(geom)}
    other={"points":{k:[-y*123+40,x*123-17] for k,(x,y) in g["points"].items()},
           "segments":{k:list(reversed(v)) for k,v in g["segments"].items()}}
    assert keys(g)==keys(other)


def test_zero_length_segment_is_excluded():
    g={"points":{"A":[0,0],"B":[0,0],"C":[1,0]},"segments":{"AB":["A","B"],"AC":["A","C"]}}
    assert numeric_candidates(g)==[]


def test_parser_supports_subscripts_polar_and_excludes_marker_helpers():
    g=pilot.extract_geometry(r"""
    \coordinate (A1) at (0,0);\coordinate (B1) at (2,0);\coordinate (M2) at (90:2);
    \coordinate (Q1) at (0.1,0.1);
    \draw (A1)--(B1)--(M2)--cycle;
    \node at (A1) {$A_1$};\node at (B1) {$B_1$};\node at (M2) {$M_2$};
    """)
    assert set(g["points"])=={"A1","B1","M2"}
    assert len(g["segments"])==3
    assert abs(g["points"]["M2"][1]-2)<1e-12


def test_evaluation_retains_frozen_selection_preset(tmp_path,monkeypatch):
    geometry={"points":{"A":[0,0],"B":[2,0],"C":[0,2]},
              "segments":{"AB":["A","B"],"AC":["A","C"],"BC":["B","C"]}}
    pilot.save(tmp_path/"case"/"input.json",geometry)
    pilot.save(tmp_path/"case"/"candidates.json",{"limits":DEFAULT_LIMITS,"candidates":numeric_candidates(geometry)})
    monkeypatch.setattr(pilot,"reference_points",lambda *args:geometry["points"])
    report=pilot.evaluate("case",tmp_path,None)
    assert report["selected_preset"]=="tight"
    assert len(report["selected"])==report["candidate_count"]
