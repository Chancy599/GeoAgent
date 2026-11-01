from __future__ import annotations

import hashlib
from types import SimpleNamespace

import pytest

from geoagent.config import load_settings
from geoagent.orchestration.runner import GeoAgentRunner
from geoagent.state.schemas import GeometricEvidenceState, GeometryObject
from geoagent.state.tikz_geometry import extract_geometry
from geoagent.state.tikz_repair import repair_tikz_constraints


DOC = r"""\documentclass[tikz]{standalone}
\begin{document}
\begin{tikzpicture}
\coordinate (A) at (0,0);
\coordinate (B) at (4,0.01);
\coordinate (C) at (4.01,3);
\coordinate (D) at (0.01,3.01);
\draw (A)--(B)--(C)--(D)--cycle;
\end{tikzpicture}
\end{document}"""


def test_exported_rectangle_constraints_and_repeat_stability():
    tex, report = repair_tikz_constraints(DOC)
    assert report["applied"] and report["export_verified"]
    assert report["max_export_error_deg"] < 1e-8
    assert len(report["accepted"]) == 6
    assert report["max_length_change_rel"] <= 0.01
    assert tex != DOC
    assert report["input_sha256"] == hashlib.sha256(DOC.encode()).hexdigest()
    again, second = repair_tikz_constraints(tex)
    assert not second["applied"]
    assert again == tex
    assert set(extract_geometry(tex)["points"]) == {"A", "B", "C", "D"}


@pytest.mark.parametrize('size', [.1, .2, .3])
def test_uppercase_marker_helpers_never_enter_solver_or_candidates(size):
    glyph = rf'\coordinate (E) at ({size},0);\coordinate (F) at ({size},{size});\coordinate (G) at (0,{size});\draw (E)--(F)--(G);'
    source = DOC.replace(r'\end{tikzpicture}', glyph+r'\end{tikzpicture}')
    emitted, report = repair_tikz_constraints(source)
    base, base_report = repair_tikz_constraints(DOC)
    assert report['applied'] and base_report['applied']
    assert extract_geometry(emitted) == extract_geometry(base)
    assert report['candidate_count'] == base_report['candidate_count']
    assert report['angle_glyph_exclusion']['excluded_helper_points'] == ['E','F','G']
    assert all(set(s) <= {'A','B','C','D','-'} for c in report['accepted'] for s in c['segments'])
    assert r'\draw (E)--(F)--(G);' in emitted


@pytest.mark.parametrize('glyph', [
    r'\draw (A)++(.2,0)--++(0,.2)--++(-.2,0);',
    r'\draw (.2,0)--(.2,.2)--(0,.2);',
    r'\draw (.2,0)--(.2,.2);\draw (.2,.2)--(0,.2);',
    r'\draw ($(A)+(.2,0)$)--($(A)+(.2,.2)$)--($(A)+(0,.2)$);',
])
def test_marker_syntax_does_not_disable_body_repair(glyph):
    source = DOC.replace(r'\end{tikzpicture}', glyph+r'\end{tikzpicture}')
    emitted, report = repair_tikz_constraints(source)
    assert report['applied'] and report['export_verified']
    assert report['angle_glyph_exclusion']['excluded_strokes'] == 2
    assert set(extract_geometry(emitted)['points']) == {'A','B','C','D'}


def test_labelled_small_polygon_is_not_reclassified_as_annotation():
    glyph = r'\coordinate (E) at (.2,0);\coordinate (F) at (.2,.2);\coordinate (G) at (0,.2);\draw (E)--(F)--(G);\node at (F) {$P$};'
    source = DOC.replace(r'\end{tikzpicture}', glyph+r'\end{tikzpicture}')
    audit = {}
    geometry = extract_geometry(source, annotation_audit=audit)
    assert audit['excluded_strokes'] == 0
    assert 'E--F' in geometry['segments']


def test_6986_glyphs_are_logged_and_excluded_without_reference_access():
    from pathlib import Path
    source = (Path(__file__).resolve().parents[1]/'outputs/ablations/no_post_repair/latex/6986_q_fig1.tex').read_text(encoding='utf-8')
    _, report = repair_tikz_constraints(source, curve_policy='freeze')
    assert report['angle_glyph_exclusion']['excluded_strokes'] == 6
    assert report['angle_glyphs_are_candidates'] is False


@pytest.mark.parametrize("extra,reason", [
    (r"\draw (0,0) circle(1);", "deferred_curves"),
    (r"\begin{scope}[xscale=2]\end{scope}", "unsupported_transform_or_scope"),
])
def test_unsupported_geometry_is_exact_noop(extra, reason):
    original = DOC.replace(r"\end{tikzpicture}", extra + r"\end{tikzpicture}")
    tex, report = repair_tikz_constraints(original)
    assert tex == original and report["reason"] == reason


def test_disabled_and_strict_gate_return_exact_source():
    assert repair_tikz_constraints(DOC, enabled=False)[0] == DOC
    tex, report = repair_tikz_constraints(DOC, max_shift_rel=0)
    assert tex == DOC and not report["applied"]
    assert report["rejected"]


@pytest.mark.parametrize("extra", [r"\draw (A)--++(2,0);", r"\draw (A)--(2,3);"])
def test_partially_parsed_edges_do_not_escape_length_guards(extra):
    original = DOC.replace(r"\end{tikzpicture}", extra + r"\end{tikzpicture}")
    tex, report = repair_tikz_constraints(original)
    assert tex == original and not report["applied"]
    assert report["reason"].startswith("unsupported_")


def test_nonfinite_limits_cannot_bypass_movement_guards():
    tex, report = repair_tikz_constraints(DOC, max_shift_rel=float("nan"))
    assert tex == DOC and report["reason"] == "invalid_limits"


def test_selected_defaults_repair_near_incidence_without_repeated_drift():
    source=DOC.replace(r"\draw (A)--(B)--(C)--(D)--cycle;",
        r"\coordinate (E) at (2,3.008);\draw (A)--(B)--(C)--(D)--cycle;\draw (A)--(E);")
    emitted,report=repair_tikz_constraints(source)
    assert report["applied"] and report["incidence_mode"]=="snap"
    points=extract_geometry(emitted)["points"]
    import numpy as np
    c,d,e=(np.asarray(points[n]) for n in ("C","D","E"))
    edge=c-d;offset=e-d
    assert abs(edge[0]*offset[1]-edge[1]*offset[0])<1e-9
    repeated,again=repair_tikz_constraints(emitted)
    assert not again["applied"] and repeated==emitted


def make_runner(tmp_path):
    runner = object.__new__(GeoAgentRunner)
    runner.run_dir = tmp_path
    runner.state = GeometricEvidenceState(image_path="original.png", image_size={"width":400,"height":300})
    runner.state.add_object(GeometryObject(id="A", type="point", coords={"px":[0,0]}))
    runner.settings = load_settings({"geometry_repair_stage":"post_tikz", "geometry_repair":True})
    runner.tikz_agent = SimpleNamespace(run=lambda *args, **kwargs: {"ok":True,"tex":DOC})
    return runner


def test_runner_repairs_after_generation_without_changing_ges(tmp_path, monkeypatch):
    import geoagent.orchestration.runner as module
    runner = make_runner(tmp_path)
    before = runner.state.objects["A"].model_dump()
    monkeypatch.setattr(module, "repair_geometry_constraints", lambda *a,**k: pytest.fail("pre-GES repair ran"))
    monkeypatch.setattr(module, "rectify_right_angles", lambda *a,**k: pytest.fail("pre-GES rectifier ran"))
    compiled=[]
    def compile_version(n):
        compiled.append(runner.state.get_version(n).tex)
        return {"compile_ok":True,"validation_passed":True,"errors":[],"warnings":[],"png_path":None}
    runner._compile_version=compile_version
    assert runner._do_tikz_agent({"use_image":False})["ok"]
    assert compiled[0] != DOC
    assert runner.state.objects["A"].model_dump() == before
    assert (tmp_path/"tikz/v1/unrepaired.tex").read_text() == DOC
    assert runner.state.meta["constraint_repair"]["stage"] == "post_tikz"


def test_failed_repaired_compile_falls_back_to_same_original(tmp_path):
    runner = make_runner(tmp_path)
    attempted=[]
    def compile_version(n):
        tex=runner.state.get_version(n).tex
        attempted.append(tex)
        ok=tex==DOC
        return {"compile_ok":ok,"validation_passed":ok,"errors":[] if ok else ["bad export"],"warnings":[],"png_path":None}
    runner._compile_version=compile_version
    assert runner._do_tikz_agent({"use_image":False})["ok"]
    assert len(attempted)==2 and attempted[-1]==DOC
    assert runner.state.latest_version().tex==DOC
    assert runner.state.meta["constraint_repair"]["reason"]=="compile_fallback"
