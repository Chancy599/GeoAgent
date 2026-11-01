from types import SimpleNamespace

from scripts.compare_post_tikz import repair_one, sha, paired_distributions


def test_paired_comparison_keeps_skipped_program_and_baseline_bytes(tmp_path):
    source = tmp_path / "raw/latex/example.tex"
    source.parent.mkdir(parents=True)
    # Unsupported curve must be retained in both groups, including CRLF bytes.
    original = b"% untouched\r\n\\begin{tikzpicture}\\draw (0,0) circle(2);\\end{tikzpicture}\r\n"
    source.write_bytes(original)
    artifacts = tmp_path / "raw/stem/example"
    artifacts.mkdir(parents=True)
    for suffix in ("pdf", "png"):
        (artifacts / f"best.{suffix}").write_bytes(suffix.encode())
    settings = SimpleNamespace(geometry=SimpleNamespace(angle_tol_deg=.5,post_max_shift_rel=.005,post_max_length_change_rel=.01))
    report = repair_one(source, tmp_path / "comparison", None, settings)
    assert report["reason"] == "deferred_curves"
    output = tmp_path / "comparison/post/latex/example.tex"
    assert output.read_bytes() == original == source.read_bytes()
    assert sha(output) == report["source_file_sha256"] == report["final_file_sha256"]


def test_common_item_pairing_does_not_compare_different_available_sets():
    def row(a,b):
        return {"compiled":True,"angle_checks":[{"error":a},{"error":b}],
                "ratio_checks":[{"error":a},{"error":b}]}
    groups={"raw":{"sample":row(1,100)},"post":{"sample":row(.5,None)}}
    result=paired_distributions(groups,["sample"])
    assert result["angle"]["per_image"]["sample"] == {"raw":1,"post":.5,"delta":-.5,"n_items":1}
    assert result["angle"]["image_bootstrap95_delta"] == [-.5,-.5]


def test_compile_fallback_remains_in_both_groups(tmp_path, monkeypatch):
    import scripts.compare_post_tikz as module
    source=tmp_path/"raw/latex/example.tex";source.parent.mkdir(parents=True)
    source.write_bytes(b"original source\r\n")
    folder=tmp_path/"raw/stem/example";folder.mkdir(parents=True)
    for suffix in ("pdf","png"):
        (folder/f"best.{suffix}").write_bytes(suffix.encode())
    monkeypatch.setattr(module,"repair_tikz_constraints",lambda *a,**k:("changed",{
        "applied":True,"reason":"applied","input_sha256":"input","output_sha256":"changed","accepted":[]}))
    monkeypatch.setattr(module,"compile_tikz",lambda *a,**k:{"ok":False,"errors":["bad export"]})
    settings=SimpleNamespace(paths=None,geometry=SimpleNamespace(angle_tol_deg=.5,post_max_shift_rel=.005,post_max_length_change_rel=.01))
    report=repair_one(source,tmp_path/"comparison",None,settings)
    assert not report["applied"] and report["reason"]=="compile_fallback"
    assert report["output_sha256"]=="input"
    assert (tmp_path/"comparison/post/latex/example.tex").read_bytes()==source.read_bytes()
