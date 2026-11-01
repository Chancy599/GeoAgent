"""Archive final run artifacts and remove the temporary run directory.

After a successful CLI run the working directory (checkpoints, CV overlays,
crops, every intermediate TikZ version, render caches) is no longer needed.
Everything that is kept for one image goes under ``archive_root`` as::

    outputs/ours/stem/<stem>/best.tex|pdf|png
    outputs/ours/stem/<stem>/result.json, state.json, critic_report.json
    outputs/ours/stem/<stem>/events.jsonl, llm_calls.jsonl
    outputs/ours/image/<stem>.png     (benchmark-friendly mirror)
    outputs/ours/latex/<stem>.tex     (benchmark-friendly mirror)
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from .datasets.trigeobench import normalise_stem

ARCHIVE_LOGS = ("events.jsonl", "llm_calls.jsonl", "critic_report.json")


def _best_version(state: dict[str, Any], best: Any) -> dict[str, Any] | None:
    for version in state.get("tikz_versions") or []:
        if version.get("version") == best:
            return version
    return None


def _copy(source: Any, dest: Path) -> bool:
    if not source:
        return False
    path = Path(str(source))
    if not path.is_file():
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, dest)
    return True


def archive_and_clean(result: dict[str, Any], archive_root: str | Path = "outputs/ours") -> dict[str, Any]:
    """Copy best artifacts + logs to ``archive_root``, then delete the run dir."""
    root = Path(archive_root)
    run_dir = Path(str(result.get("run_dir") or ""))
    if not run_dir.is_dir():
        return result

    stem = normalise_stem(Path(str(result.get("image_path") or run_dir.name)).stem)
    target = root / "stem" / stem
    target.mkdir(parents=True, exist_ok=True)

    state_path = run_dir / "state.json"
    state: dict[str, Any] = {}
    if state_path.is_file():
        state = json.loads(state_path.read_text(encoding="utf-8"))
    best = result.get("best_version")
    version = _best_version(state, best) if best is not None else None

    tex_src = (version or {}).get("tex_path") or result.get("best_tex_path")
    pdf_src = (version or {}).get("pdf_path")
    png_src = (version or {}).get("png_path") or result.get("best_png_path")

    wrote_tex = _copy(tex_src, target / "best.tex")
    if not wrote_tex and result.get("best_tex"):
        (target / "best.tex").write_text(str(result["best_tex"]), encoding="utf-8")
        wrote_tex = True
    _copy(pdf_src, target / "best.pdf")
    _copy(png_src, target / "best.png")

    for log in ARCHIVE_LOGS:
        _copy(run_dir / log, target / log)
    if best is not None:
        version_dir = run_dir / "tikz" / f"v{best}"
        for name in ("unrepaired.tex", "constraint_repair.json"):
            if not _copy(version_dir / name, target / name) and (target / name).is_file():
                (target / name).unlink()
    # A re-run of the same stem must not keep the previous run's report.
    report = (version or {}).get("critic_report")
    if report:
        (target / "critic_report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    elif (target / "critic_report.json").is_file():
        (target / "critic_report.json").unlink()
    _copy(state_path, target / "state.json")

    # Benchmark-friendly mirrors, mirroring outputs/baselines/<model>/.
    if wrote_tex:
        mirror = root / "latex" / f"{stem}.tex"
        mirror.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target / "best.tex", mirror)
    if (target / "best.png").is_file():
        mirror = root / "image" / f"{stem}.png"
        mirror.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target / "best.png", mirror)

    # Point the archived result at its new home instead of the deleted run dir.
    archived = dict(result)
    archived["run_dir"] = str(target)
    archived["state_path"] = str(target / "state.json")
    if wrote_tex:
        archived["best_tex_path"] = str(target / "best.tex")
    if (target / "best.png").is_file():
        archived["best_png_path"] = str(target / "best.png")
    (target / "result.json").write_text(
        json.dumps(archived, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # Never delete the archive itself, the project root, a data directory, or a
    # run dir that did not actually yield a best artifact.
    resolved = run_dir.resolve()
    target_resolved = target.resolve()
    has_best = (target / "best.tex").is_file() or (target / "best.png").is_file()
    if (
        not has_best
        or resolved == target_resolved
        or resolved == root.resolve()
        or resolved == (root / "stem").resolve()
        or resolved == Path.cwd().resolve()
        or "data" in resolved.parts
    ):
        return archived
    shutil.rmtree(run_dir, ignore_errors=True)
    return archived
