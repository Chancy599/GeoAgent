from __future__ import annotations

from pathlib import Path

import pytest

from geoagent.tools import compile_tikz, discover_compiler, render_pdf, validate_compilation

TEX = r"""\documentclass[tikz,border=5pt]{standalone}
\begin{document}
\begin{tikzpicture}
  \draw (-2,0) -- (2,0) -- (0,2) -- cycle;
  \node[below] at (0,1) {$A$};
\end{tikzpicture}
\end{document}
"""


@pytest.fixture(scope="module")
def compiler(settings):
    info = discover_compiler(settings.paths)
    if not info.get("found"):
        pytest.skip("no TeX compiler available")
    return info


def test_compiler_is_discovered(compiler) -> None:
    assert compiler["version"]
    assert Path(compiler["path"]).exists()


def test_document_compiles_renders_and_validates(settings, compiler, tmp_out) -> None:
    compiled = compile_tikz(TEX, out_dir=tmp_out, stem="triangle", paths=settings.paths)
    assert compiled["ok"], compiled["errors"]
    assert Path(compiled["pdf_path"]).exists()

    rendered = render_pdf(compiled["pdf_path"], tmp_out / "triangle.png")
    assert rendered["ok"], rendered.get("error")
    assert Path(rendered["png_path"]).exists()

    validation = validate_compilation(TEX, {**compiled, "png_path": rendered["png_path"]})
    assert validation.passed, [(check.name, check.detail) for check in validation.checks if not check.passed]


def test_shell_escape_is_rejected(settings, compiler, tmp_out) -> None:
    malicious = TEX.replace("\\draw", "\\immediate\\write18{echo pwned}\n  \\draw")
    compiled = compile_tikz(malicious, out_dir=tmp_out, stem="bad", paths=settings.paths)
    assert compiled["ok"] is False
    assert any("forbidden" in error or "shell" in error for error in compiled["errors"])
