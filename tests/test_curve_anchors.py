import numpy as np
import pytest

from geoagent.state.curve_anchors import curve_anchors
from geoagent.state.optimize_relations import optimize_coordinates
from geoagent.state.tikz_geometry import extract_geometry
from geoagent.state.tikz_repair import repair_tikz_constraints


DOC=r"""\begin{tikzpicture}
\coordinate (O) at (0,0);
\coordinate (A) at (1,0);
\coordinate (B) at (3,1);
\coordinate (C) at (3.004,3);
\coordinate (D) at (5,1.002);
\draw (O) circle (1);
\draw (B)--(C);\draw (B)--(D);
\end{tikzpicture}"""


def test_curve_center_and_boundary_are_fixed_but_free_points_move():
    emitted,report=repair_tikz_constraints(DOC,curve_policy="freeze")
    assert report["applied"]
    before=extract_geometry(DOC);after=extract_geometry(emitted)
    assert after["points"]["O"] == before["points"]["O"]
    assert after["points"]["A"] == before["points"]["A"]
    assert after["points"]["B"] != before["points"]["B"]
    assert r"\draw (O) circle (1);" in emitted
    assert report["fixed_points"] == ["A","O"]


def test_arc_derived_center_is_also_frozen():
    tex=DOC.replace(r"\coordinate (A) at (1,0);",r"\coordinate (A) at (-1,0);")
    tex=tex.replace(r"\draw (O) circle (1);",r"\draw (A) arc[start angle=180,end angle=0,radius=1];")
    result=curve_anchors(tex,extract_geometry(tex))
    assert "O" in result["fixed_points"] and "A" in result["fixed_points"]


def test_tangent_other_endpoint_does_not_rotate():
    tex=DOC.replace(r"\draw (B)--(D);",r"\coordinate (T) at (1,4);\draw (A)--(T);\draw (B)--(D);")
    anchors=curve_anchors(tex,extract_geometry(tex))
    assert "T" in anchors["fixed_points"]


def test_unknown_curve_expressions_return_original_source():
    tex=DOC.replace("circle (1)",r"circle (\radius)")
    emitted,report=repair_tikz_constraints(tex,curve_policy="freeze")
    assert emitted==tex and not report["applied"]


def test_fixed_points_survive_weighted_projection_exactly():
    geometry={"points":{"A":[0,0],"B":[3,.01],"C":[.005,2]},"segments":{"AB":["A","B"],"AC":["A","C"]}}
    optimized,report=optimize_coordinates(geometry,fixed_points=["A"],length_weight=1,length_scope="all_pairs")
    assert report["applied"] and report["max_after_error_deg"]<1e-7
    assert optimized["points"]["A"]==[0,0]


def test_length_metric_reduces_relative_length_drift():
    geometry={"points":{"A":[0,0],"B":[4,.005],"C":[.0002,.1]},
        "segments":{"AB":["A","B"],"AC":["A","C"]}}
    unweighted,a=optimize_coordinates(geometry)
    weighted,b=optimize_coordinates(geometry,length_weight=10)
    def cost(result):
        return sum(np.log(np.linalg.norm(np.subtract(result["points"][v],result["points"][u]))/
            np.linalg.norm(np.subtract(geometry["points"][v],geometry["points"][u])))**2
            for u,v in geometry["segments"].values())
    assert a["applied"] and b["applied"]
    assert cost(weighted)<cost(unweighted)


def test_partial_solver_cannot_move_all_fixed_geometry():
    g=extract_geometry(DOC)
    after,report=optimize_coordinates(g,fixed_points=g["points"])
    assert after==g and report["reason"]=="all_points_fixed"
