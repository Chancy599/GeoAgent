"""Tectonic/LaTeX compilation such as described in docs/init.md.

Key guarantees:
* the compiler is *discovered* (never assumed to be on PATH);
* every compile runs in its own throw-away directory;
* output paths are copied back with Unicode-safe file APIs;
* shell-escape is never enabled;
* stderr/stdout are parsed into human-readable errors for the repair agent.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from ..config import PROJECT_ROOT, PathSettings

STANDALONE_PREAMBLE = r"""\documentclass[tikz,border=10pt]{standalone}
\usetikzlibrary{calc,angles,quotes,intersections}
\begin{document}
"""
STANDALONE_POSTAMBLE = "\n\\end{document}\n"

_FENCE_RE = re.compile(r"^\s*```(?:latex|tex)?\s*|\s*```\s*$", re.MULTILINE)
_DOC_RE = re.compile(r"\\documentclass", re.IGNORECASE)
_TIKZ_DOC_RE = re.compile(r"\\begin\{document\}", re.IGNORECASE)
_DANGEROUS = ("\\write18", "\\immediate\\write", "\\openout", "\\read", "\\csname")

# The PDF/PNG artefacts live next to the venv-independent system temp root.
_COMPILER_CACHE: dict[str, dict[str, Any]] = {}


def discover_compiler(paths: PathSettings | None = None) -> dict[str, Any]:
    """Find the first working TeX compiler and report how it was found."""
    cached = _COMPILER_CACHE.get("info")
    if cached:
        return cached

    candidates: list[tuple[str, Path]] = []
    if paths is not None:
        candidates.append(("configured", Path(paths.tectonic)))
    candidates.extend(
        [
            ("project_tool", PROJECT_ROOT / "tool" / "tectonic" / "tectonic.exe"),
            ("project_tool", PROJECT_ROOT / "tool" / "tectonic.exe"),
        ]
    )
    for exe in ("tectonic", "tectonic.exe", "pdflatex", "xelatex", "lualatex"):
        found = shutil.which(exe)
        if found:
            candidates.append(("PATH", Path(found)))

    tried: list[str] = []
    for origin, path in candidates:
        if not path.exists():
            tried.append(f"{path} (missing)")
            continue
        try:
            proc = subprocess.run(
                [str(path), "--version"],
                capture_output=True,
                text=True,
                timeout=20,
                encoding="utf-8",
                errors="replace",
            )
            version = (proc.stdout or proc.stderr or "").strip().splitlines()
            info = {
                "found": True,
                "path": str(path),
                "origin": origin,
                "version": version[0] if version else "unknown",
                "kind": "tectonic" if "tectonic" in path.name.lower() else path.stem,
            }
            _COMPILER_CACHE["info"] = info
            return info
        except Exception as exc:  # pragma: no cover - environment specific
            tried.append(f"{path} ({type(exc).__name__}: {exc})")

    info = {"found": False, "path": None, "origin": None, "version": None, "kind": None, "tried": tried}
    _COMPILER_CACHE["info"] = info
    return info


def normalise_document(tex: str) -> tuple[str, list[str]]:
    """Strip fences; wrap bare tikzpictures in a standalone document."""
    notes: list[str] = []
    text = _FENCE_RE.sub("", tex or "").strip()
    if not text:
        return "", ["empty TikZ source"]
    text = re.sub(r"^\s*%+\s*(begin|end)?\s*source.*$", "", text, flags=re.IGNORECASE)
    has_documentclass = bool(_DOC_RE.search(text))
    has_document = bool(_TIKZ_DOC_RE.search(text))
    has_tikzpicture = "\\begin{tikzpicture}" in text
    if not has_documentclass and not has_document:
        if not has_tikzpicture:
            notes.append("source contains neither \\documentclass nor tikzpicture")
        body = text if has_tikzpicture else "\\begin{tikzpicture}\n" + text + "\n\\end{tikzpicture}"
        text = STANDALONE_PREAMBLE + body + STANDALONE_POSTAMBLE
        notes.append("wrapped in standalone document preamble")
    elif has_documentclass and not has_document:
        notes.append("\\documentclass without document environment")
    elif has_document and not has_documentclass:
        notes.append("document environment without \\documentclass")
    return text, notes


def security_scan(tex: str) -> list[str]:
    lowered = tex.lower()
    return [token for token in _DANGEROUS if token in lowered]


def extract_compiler_errors(log: str) -> tuple[list[str], list[str]]:
    """Parse LaTeX/Tectonic output into (errors, warnings)."""
    errors: list[str] = []
    warnings: list[str] = []
    lines = (log or "").splitlines()
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("error:") or stripped.startswith("! "):
            context = ""
            for follow in lines[index + 1: index + 4]:
                if follow.strip():
                    context = follow.strip()
                    break
            errors.append(f"{stripped} {context}".strip())
        elif stripped.startswith("warning:") or "LaTeX Warning" in stripped:
            warnings.append(stripped)
        elif re.search(r"^l\.\d+", stripped):
            errors.append(stripped)
    # de-duplicate while keeping order
    errors = list(dict.fromkeys(errors))
    warnings = list(dict.fromkeys(warnings))
    return errors[:40], warnings[:40]


def _safe_copy(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dst)


def compile_tikz(
    tex: str,
    *,
    out_dir: str | Path,
    stem: str = "figure",
    timeout: float = 120.0,
    paths: PathSettings | None = None,
) -> dict[str, Any]:
    """Compile ``tex`` to PDF (and leave the .tex next to it)."""
    out_root = Path(out_dir)
    out_root.mkdir(parents=True, exist_ok=True)
    document, notes = normalise_document(tex)
    if not document:
        return {
            "ok": False,
            "returncode": None,
            "errors": notes or ["empty document"],
            "warnings": [],
            "notes": notes,
            "tex_path": None,
            "pdf_path": None,
            "seconds": 0.0,
        }

    unsafe = security_scan(document)
    if unsafe:
        return {
            "ok": False,
            "returncode": None,
            "errors": [f"refusing to compile forbidden TeX primitives: {unsafe}"],
            "warnings": [],
            "notes": notes,
            "tex_path": None,
            "pdf_path": None,
            "seconds": 0.0,
        }

    compiler = discover_compiler(paths)
    if not compiler.get("found"):
        return {
            "ok": False,
            "returncode": None,
            "errors": ["no TeX compiler found (install tectonic or set GEOAGENT_TECTONIC)"],
            "warnings": [],
            "notes": notes,
            "compiler": compiler,
            "tex_path": None,
            "pdf_path": None,
            "seconds": 0.0,
        }

    # Always compile in an ASCII temp directory: the project path contains CJK
    # characters that some TeX binaries mishandle.
    work = Path(tempfile.mkdtemp(prefix="geoagent_tex_"))
    started = time.perf_counter()
    try:
        tex_file = work / "figure.tex"
        tex_file.write_text(document, encoding="utf-8")
        cmd = [compiler["path"]]
        if compiler.get("kind") == "tectonic":
            cmd += ["--keep-logs", "--untrusted", "figure.tex"]
        else:
            cmd += ["-interaction=nonstopmode", "-halt-on-error", "-output-directory=.", "figure.tex"]
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(work),
                capture_output=True,
                text=True,
                timeout=max(10.0, float(timeout)),
                encoding="utf-8",
                errors="replace",
                # Keep Tectonic's persistent bundle cache: a fresh cache dir
                # forces a ~80 MB re-download on every compile.
                env={**os.environ},
            )
            returncode = proc.returncode
            combined = (proc.stdout or "") + "\n" + (proc.stderr or "")
        except subprocess.TimeoutExpired as exc:
            returncode = -1
            combined = f"error: compiler timed out after {timeout}s\n{exc}"
        seconds = round(time.perf_counter() - started, 3)

        pdf_src = work / "figure.pdf"
        log_path = work / "figure.log"
        log_text = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else ""

        final_tex = out_root / f"{stem}.tex"
        final_pdf = out_root / f"{stem}.pdf"
        _safe_copy(tex_file, final_tex)
        pdf_ok = pdf_src.exists() and pdf_src.stat().st_size > 0
        if pdf_ok:
            _safe_copy(pdf_src, final_pdf)

        errors, warnings = extract_compiler_errors(combined + "\n" + log_text)
        if not pdf_ok and not errors:
            tail = [ln for ln in (combined or log_text).splitlines() if ln.strip()][-8:]
            errors = ["compilation produced no PDF"] + tail
        tail_text = "\n".join((combined or log_text).splitlines()[-40:])
        return {
            "ok": bool(pdf_ok and returncode == 0),
            "returncode": returncode,
            "seconds": seconds,
            "errors": errors,
            "warnings": warnings,
            "notes": notes,
            "compiler": compiler,
            "tex_path": str(final_tex),
            "pdf_path": str(final_pdf) if pdf_ok else None,
            "log_tail": tail_text[-4000:],
        }
    finally:
        shutil.rmtree(work, ignore_errors=True)
