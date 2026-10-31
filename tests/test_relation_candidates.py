from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("relation_pilot", Path(__file__).resolve().parents[1] / "scripts/test_relation_candidates.py")
pilot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pilot)


def test_coordinate_only_input_ignores_comments_helpers_and_keeps_path_edges():
    geometry = pilot.extract_input(r"""
    % \coordinate (X) at (999,999);
    \coordinate (A) at (0,0); \coordinate (B) at (2,0);
    \coordinate (C) at (2,2); \coordinate (D) at (0,2);
    \coordinate (Q1) at (0.1,0.1);
    \draw (A)--(B)--(C)--(D)--cycle;
    """)
    assert set(geometry["points"]) == set("ABCD")
    assert set(geometry["segments"]) == {"AB","BC","CD","AD"}


def test_inference_preparation_needs_no_reference_file(tmp_path, monkeypatch):
    monkeypatch.setattr(pilot,"ROOT",tmp_path)
    folder = tmp_path / "outputs/ours100/latex"
    folder.mkdir(parents=True)
    (folder/"sample.tex").write_text(r"\coordinate (A) at (0,0);\coordinate (B) at (1,0);\coordinate (C) at (0,1);\draw(A)--(B)--(C)--cycle;")
    request = pilot.prepare_input("sample", tmp_path/"test-output")
    assert not (tmp_path/"data").exists()
    assert "points" in request["user"]
    assert "reference_sha256" not in request["user"]


def test_parallel_excludes_collinear_and_equal_length_is_scale_invariant():
    points = {"A":[0,0],"B":[2,0],"C":[0,2],"D":[2,2],"E":[4,0]}
    segments = {"AB":["A","B"],"CD":["C","D"],"BE":["B","E"]}
    key = ("parallel","AB","CD")
    assert pilot.passes(key,pilot.measure(key,points,segments),pilot.INPUT_LIMITS)
    key = ("parallel","AB","BE")
    assert not pilot.passes(key,pilot.measure(key,points,segments),pilot.INPUT_LIMITS)
    for scale in [0.01,100]:
        key = ("equal_length","AB","CD")
        metric = pilot.measure(key,{k:[x*scale for x in xy] for k,xy in points.items()},segments)
        assert metric["relative_length"] == 0


def test_bad_candidate_references_and_unsupported_expressions_fail():
    with pytest.raises(ValueError):
        pilot.canonical({"type":"collinear","points":["A","B","X"]},{"points":{"A":[0,0],"B":[1,1]}})
    with pytest.raises(ValueError,match="Unsupported input"):
        pilot.extract_input(r"\coordinate (A) at ($(B)!0.5!(C)$);")
