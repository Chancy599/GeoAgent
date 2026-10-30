from __future__ import annotations

from geoagent.agents.tikz_agent import _complete_document

DOC = (
    "\\documentclass[tikz]{standalone}\n"
    "\\begin{document}\n"
    "\\begin{tikzpicture}\n\\draw (0,0)--(1,0);\n\\end{tikzpicture}\n"
    "\\end{document}"
)


def test_complete_document_accepts_standalone() -> None:
    assert _complete_document(DOC)


def test_complete_document_rejects_snippets_and_prose() -> None:
    assert not _complete_document("\\begin{tikzpicture}\\draw (0,0)--(1,0);\\end{tikzpicture}")
    assert not _complete_document("\\documentclass[tikz]{standalone}\n\\begin{document}hello\\end{document}")
    assert not _complete_document("Here is the figure you asked for.")
