from __future__ import annotations

from pathlib import Path

import pytest

from geoagent.tools import (
    compile_tikz,
    discover_compiler,
    frame_like_original,
    render_pdf,
    validate_compilation,
)

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


def test_frame_like_original_matches_canvas_and_content_box(tmp_path: Path) -> None:
    """A tightly cropped render must adopt the source image's canvas framing."""
    from PIL import Image

    original = Image.new("RGB", (300, 200), "white")
    original.paste("black", (50, 40, 250, 160))
    original_path = tmp_path / "original.png"
    original.save(original_path)

    render = Image.new("RGB", (100, 100), "white")
    render.paste("black", (10, 10, 90, 58))  # same 5:3 aspect as the source ink
    render_path = tmp_path / "render.png"
    render.save(render_path)

    result = frame_like_original(render_path, original_path)
    assert result["ok"], result.get("error")

    with Image.open(render_path) as framed:
        assert framed.size == (300, 200)
        ink = framed.convert("L").point(lambda value: 255 if value < 245 else 0)
        bbox = ink.getbbox()
        assert bbox is not None
        # LANCZOS edges may bleed one pixel past the ideal box.
        for got, want in zip(bbox, (50, 40, 250, 160)):
            assert abs(got - want) <= 1


def test_shell_escape_is_rejected(settings, compiler, tmp_out) -> None:
    malicious = TEX.replace("\\draw", "\\immediate\\write18{echo pwned}\n  \\draw")
    compiled = compile_tikz(malicious, out_dir=tmp_out, stem="bad", paths=settings.paths)
    assert compiled["ok"] is False
    assert any("forbidden" in error or "shell" in error for error in compiled["errors"])
