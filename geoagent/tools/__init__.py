"""Execution toolbox: LaTeX compilation, rendering, validation."""
from .compiler import compile_tikz, discover_compiler, extract_compiler_errors
from .renderer import frame_like_original, render_pdf
from .verifier import validate_compilation

__all__ = [
    "compile_tikz",
    "discover_compiler",
    "extract_compiler_errors",
    "frame_like_original",
    "render_pdf",
    "validate_compilation",
]
