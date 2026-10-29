"""Compilation validation: structural checks + artefacts + rendered geometry."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import cv2
import numpy as np

from ..state.schemas import ValidationCheck, ValidationResult
from .compiler import normalise_document, security_scan


def _balance_ok(text: str, env: str) -> bool:
    begin = text.count(f"\\begin{{{env}}}")
    end = text.count(f"\\end{{{env}}}")
    return begin == end and begin > 0


def _render_stats(png_path: str | Path | None) -> dict[str, Any] | None:
    if not png_path or not Path(png_path).exists():
        return None
    data = np.frombuffer(Path(png_path).read_bytes(), dtype=np.uint8)
    image = cv2.imdecode(data, cv2.IMREAD_GRAYSCALE)
    if image is None:
        return None
    ink = (image < 200).astype(np.uint8)
    ys, xs = np.where(ink > 0)
    if not len(ys):
        return {"size": [int(image.shape[1]), int(image.shape[0])], "ink_ratio": 0.0, "bbox": None}
    return {
        "size": [int(image.shape[1]), int(image.shape[0])],
        "ink_ratio": round(float(ink.mean()), 4),
        "bbox": [int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1],
    }


def validate_compilation(
    tex: str,
    compile_result: dict[str, Any],
    *,
    version: int | None = None,
    reference_size: tuple[int, int] | None = None,
) -> ValidationResult:
    """Check the document structure, artefacts, and rendered content."""
    document, wrap_notes = normalise_document(tex)
    checks: list[ValidationCheck] = []

    def add(name: str, passed: bool, detail: str = "") -> None:
        checks.append(ValidationCheck(name=name, passed=bool(passed), detail=detail))

    add("documentclass", "\\documentclass" in document, "documentclass present")
    add(
        "document_environment",
        _balance_ok(document, "document"),
        f"begin={document.count(chr(92) + 'begin{document}')} end={document.count(chr(92) + 'end{document}')}",
    )
    add("tikzpicture", _balance_ok(document, "tikzpicture"), "one balanced tikzpicture")
    add("no_shell_escape", not security_scan(document), "no \\write18/\\openout primitives")
    add("compiler_ok", bool(compile_result.get("ok")), f"returncode={compile_result.get('returncode')}")

    pdf_path = compile_result.get("pdf_path")
    png_path = compile_result.get("png_path")
    add("pdf_created", bool(pdf_path and Path(pdf_path).exists()), str(pdf_path or "missing"))
    add("png_rendered", bool(png_path and Path(png_path).exists()), str(png_path or "missing"))

    stats = _render_stats(png_path)
    has_ink = bool(stats and stats["ink_ratio"] >= 0.002)
    add("render_not_blank", has_ink, f"ink_ratio={stats['ink_ratio'] if stats else 'n/a'}")

    if reference_size and stats:
        ref_w, ref_h = reference_size
        ref_ratio = ref_w / max(1, ref_h)
        out_ratio = stats["size"][0] / max(1, stats["size"][1])
        ratio_delta = abs(out_ratio - ref_ratio) / max(ref_ratio, 1e-6)
        add(
            "aspect_ratio",
            ratio_delta <= 0.35,
            f"reference {ref_ratio:.2f} vs render {out_ratio:.2f} (delta {ratio_delta:.2f})",
        )
        if ref_w * ref_h and stats["bbox"]:
            bx0, by0, bx1, by1 = stats["bbox"]
            fig_ratio = (bx1 - bx0) / max(1, by1 - by0)
            add(
                "figure_extent_ratio",
                abs(fig_ratio - ref_ratio) / max(ref_ratio, 1e-6) <= 0.5,
                f"figure bbox ratio {fig_ratio:.2f}",
            )

    passed = all(check.passed for check in checks)
    return ValidationResult(version=version, passed=passed, checks=checks)
