"""End-to-end baseline: source PNG -> one multimodal completion -> TikZ -> PNG.

Migrated from ``geom2code/tests/demo_e2e.py`` (the ``e2e`` cohort of
``geom2code/scripts/run_whole100.py``).  The protocol is intentionally the
same as the frozen baseline:

* the model sees only the source PNG (raw PNG bytes, no downscaling);
* temperature 0, ``max_tokens`` 8192, one completed response per figure;
* a response truncated by the token limit or empty is an error;
* the TikZ source is written as-is (no repair / no quality resampling) and
  compiled with the local Tectonic binary, then rasterised to PNG;
* ``--out-root`` receives only ``latex/`` and ``image/``; traces, the batch
  summary and overwrite backups go to ``--log-root`` (default
  ``outputs/scratch/e2e/<baseline name>``).

Batch conveniences:

* ``--missing-only`` skips stems that already have a compiled PNG;
* ``--attempts N`` (default 3) retries a figure when compilation fails or the
  reply is byte-identical to the archived TeX for that stem.  The last reply
  is kept when every attempt fails; the trace records each attempt;
* ``--workers N`` runs figures concurrently;
* GPT-5.x/6.x use ``max_completion_tokens`` (+ ``--reasoning-effort``),
  other models use ``max_tokens`` + ``--temperature``.

Usage (PowerShell / bash):

    python scripts/run_e2e.py --out-root outputs/baselines/haiku-5.5 \
        --missing-only --attempts 3

    python scripts/run_e2e.py --model qwen3.5-plus \
        --out-root outputs/baselines/qwen3.5-plus --workers 4

    python scripts/run_e2e.py --model gpt-5.4 --reasoning-effort minimal \
        --out-root outputs/baselines/gpt-5.4 --workers 4
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import shutil
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from geoagent.config import load_settings  # noqa: E402
from geoagent.datasets import scan_dataset  # noqa: E402
from geoagent.tools import compile_tikz, render_pdf  # noqa: E402

E2E_PROMPT = r"""Reproduce this geometric figure as a standalone TikZ document.
Rules:
- \documentclass[tikz,border=10pt]{standalone}
- define every labelled point with \coordinate (L) at (x,y); where L is the letter
  you read from the image (keep subscripts, e.g. \coordinate (A1) ... for "$A_1$);
  choose your own numeric coordinates
- draw every edge and curve with \draw
- an edge that is dash-ed in the image must be drawn with \draw[dashed]; edges that
  are solid in the image must stay solid (do not dash them)
- wherever the image shows a right-angle mark (a small square at a vertex between
  two perpendicular sides), draw that square with \draw
- label each point with \node[...] at (L) {$L$};
Output ONLY the LaTeX source -- no prose, no markdown code fences."""

_FENCE_RE = re.compile(r"^\s*```(?:latex|tex)?\s*|\s*```\s*$", re.MULTILINE)


def _sha_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha_file(path: Path) -> str | None:
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _normalise(tex: str) -> str:
    return _FENCE_RE.sub("", tex or "").strip()


def _request(client, image_path: Path, model: str, params: dict, *, timeout: float) -> tuple[str, dict]:
    b64 = base64.b64encode(image_path.read_bytes()).decode("ascii")
    content = [
        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
        {"type": "text", "text": E2E_PROMPT},
    ]
    started = time.perf_counter()
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": content}],
        timeout=timeout,
        **params,
    )
    elapsed = round(time.perf_counter() - started, 3)
    choice = response.choices[0]
    finish_reason = getattr(choice, "finish_reason", None)
    usage_obj = getattr(response, "usage", None)
    usage = usage_obj.model_dump() if usage_obj is not None else None
    if finish_reason == "length":
        raise ValueError("e2e completion reached its token limit")
    text = _normalise(choice.message.content or "")
    if not text:
        raise ValueError("e2e returned no LaTeX text")
    meta = {
        "response_model": getattr(response, "model", None),
        "response_id": getattr(response, "id", None),
        "finish_reason": finish_reason,
        "usage": usage,
        "elapsed_seconds": elapsed,
    }
    return text, meta


def _compile(tex: str, stem: str, out_root: Path, *, dpi: int, timeout: float) -> dict:
    build = Path(tempfile.mkdtemp(prefix=f"e2e_{stem}_"))
    try:
        result = compile_tikz(tex, out_dir=build, stem=stem, timeout=timeout)
        if not result.get("ok"):
            return {"ok": False, "compile": result, "render": None}
        render = render_pdf(result["pdf_path"], out_root / "image" / f"{stem}.png", dpi=dpi, crop_white=False)
        return {"ok": bool(render.get("ok")), "compile": result, "render": render}
    finally:
        shutil.rmtree(build, ignore_errors=True)


def _run_one(
    client,
    stem: str,
    image_path: Path,
    args,
    out_root: Path,
    log_root: Path,
    existing: dict[str, str],
    target_hash: str | None,
) -> dict:
    tex_dir, image_dir = out_root / "latex", out_root / "image"
    trace_dir = log_root / "trace"
    for directory in (tex_dir, image_dir, trace_dir):
        directory.mkdir(parents=True, exist_ok=True)

    record: dict = {
        "name": stem,
        "status": "pending",
        "compiled": False,
        "model": args.model,
        "parameters": dict(args.request_params),
        "requested_at_utc": datetime.now(timezone.utc).isoformat(),
        "attempts": [],
        "duplicate": False,
    }
    started = time.perf_counter()
    chosen_tex: str | None = None
    chosen_outcome: dict | None = None
    try:
        for attempt in range(1, args.attempts + 1):
            try:
                tex, meta = _request(client, image_path, args.model, args.request_params, timeout=args.timeout)
            except Exception as exc:  # noqa: BLE001 - service errors may be transient
                record["attempts"].append(
                    {"attempt": attempt, "request_error": f"{type(exc).__name__}: {exc}"}
                )
                if attempt < args.attempts:
                    print(f"  {stem}: attempt {attempt} request failed ({type(exc).__name__}); retrying", flush=True)
                    continue
                raise
            digest = _sha_text(_normalise(tex))
            collision = target_hash if digest == target_hash else existing.get(digest)
            if collision is not None and attempt < args.attempts:
                record["attempts"].append(
                    {**meta, "attempt": attempt, "tex_sha256": digest, "duplicate_of": collision}
                )
                record["duplicate"] = True
                print(f"  {stem}: attempt {attempt} duplicated {collision}; re-requesting", flush=True)
                continue

            outcome = _compile(tex, stem, out_root, dpi=args.dpi, timeout=args.compile_timeout)
            errors = outcome["compile"].get("errors", [])
            record["attempts"].append(
                {
                    **meta,
                    "attempt": attempt,
                    "tex_sha256": digest,
                    "duplicate_of": collision,
                    "compiled": outcome["ok"],
                    "compile_errors": errors,
                }
            )
            chosen_tex, chosen_outcome = tex, outcome
            if outcome["ok"]:
                break
            if attempt < args.attempts:
                print(
                    f"  {stem}: attempt {attempt} failed to compile ({errors[:1]}); retrying",
                    flush=True,
                )

        if chosen_tex is None:
            raise RuntimeError("no usable response after all attempts")

        tex_dir.mkdir(parents=True, exist_ok=True)
        if args.backup and (tex_dir / f"{stem}.tex").exists():
            backup_dir = log_root / "backup_before_rerun"
            backup_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(tex_dir / f"{stem}.tex", backup_dir / f"{stem}.tex")
            record["backup"] = str(backup_dir / f"{stem}.tex")
        (tex_dir / f"{stem}.tex").write_text(chosen_tex + "\n", encoding="utf-8")
        record["tex_sha256"] = _sha_file(tex_dir / f"{stem}.tex")
        record["attempts_used"] = len(record["attempts"])

        assert chosen_outcome is not None
        record["compile_ok"] = chosen_outcome["ok"]
        record["compile_errors"] = chosen_outcome["compile"].get("errors", [])
        record["compile_log_tail"] = chosen_outcome["compile"].get("log_tail", "")
        record["render"] = chosen_outcome["render"]
        if chosen_outcome["ok"]:
            record.update(status="completed", compiled=True)
            record["image_sha256"] = _sha_file(image_dir / f"{stem}.png")
        else:
            record["status"] = "compile_failed"
    except Exception as exc:  # noqa: BLE001 - keep the batch alive
        record.update(status="error", error_type=type(exc).__name__, error=str(exc))
    finally:
        record["elapsed_seconds"] = round(time.perf_counter() - started, 3)
        (trace_dir / f"{stem}.json").write_text(
            json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return record


def _resolve_stems(args, out_root: Path) -> list[tuple[str, Path]]:
    """Return (normalised stem, source image) pairs, de-duplicated by stem."""
    paths = {item.stem: item.image_path for item in scan_dataset(args.image_dir)}
    wanted = None
    if args.only:
        wanted = [s.strip() for s in args.only.split(",") if s.strip()]
    stems = sorted(paths)
    if wanted is not None:
        missing = [s for s in wanted if s not in paths]
        if missing:
            raise SystemExit(f"unknown image stems: {missing}")
        stems = wanted
    if args.missing_only:
        stems = [s for s in stems if not (out_root / "image" / f"{s}.png").exists()]
    return [(stem, paths[stem]) for stem in stems]


def main() -> int:
    settings = load_settings()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--folder", default=str(settings.paths.data_root / "test"))
    parser.add_argument("--out-root", default=str(settings.paths.outputs_dir / "baselines" / "haiku-5.5"))
    parser.add_argument(
        "--log-root",
        help="trace/summary/backup directory (default: outputs/scratch/e2e/<baseline name>)",
    )
    parser.add_argument("--model", default=settings.model.model)
    parser.add_argument("--only", help="comma-separated stems")
    parser.add_argument("--missing-only", action="store_true", help="only stems without a compiled PNG")
    parser.add_argument(
        "--attempts", type=int, default=3, help="max tries per figure (compile failures and duplicate replies)"
    )
    parser.add_argument("--max-output-tokens", type=int, default=8192)
    parser.add_argument("--temperature", type=float, default=0.0, help="non-reasoning models only")
    parser.add_argument("--reasoning-effort", default="minimal", help="GPT-5.x/6.x only; empty string omits it")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--dpi", type=int, default=150)
    parser.add_argument("--timeout", type=float, default=settings.model.request_timeout)
    parser.add_argument("--compile-timeout", type=float, default=float(settings.budget.compile_timeout_seconds))
    parser.add_argument("--no-backup", dest="backup", action="store_false", help="do not back up overwritten TeX")
    args = parser.parse_args()

    if args.model.startswith(("gpt-5", "gpt-6")):
        request_params: dict = {"max_completion_tokens": args.max_output_tokens}
        if args.reasoning_effort:
            request_params["reasoning_effort"] = args.reasoning_effort
    else:
        request_params = {"max_tokens": args.max_output_tokens, "temperature": args.temperature}
    args.request_params = request_params

    args.image_dir = Path(args.folder) / "image"
    if not args.image_dir.is_absolute():
        args.image_dir = ROOT / args.image_dir
    out_root = Path(args.out_root)
    if not out_root.is_absolute():
        out_root = ROOT / out_root
    log_root = Path(args.log_root) if args.log_root else ROOT / "outputs" / "scratch" / "e2e" / out_root.name
    if not log_root.is_absolute():
        log_root = ROOT / log_root

    if not settings.model.api_key or not settings.model.base_url:
        raise SystemExit("OPENAI_API_KEY / OPENAI_BASE_URL missing from .env")
    from openai import OpenAI

    client = OpenAI(
        api_key=settings.model.api_key,
        base_url=settings.model.base_url,
        timeout=args.timeout,
        max_retries=0,
    )

    selected = _resolve_stems(args, out_root)
    if not selected:
        print("nothing to do: all selected stems already have compiled PNGs")
        return 0
    stems = [stem for stem, _ in selected]

    tex_dir = out_root / "latex"
    existing: dict[str, str] = {}
    if tex_dir.exists():
        for path in tex_dir.glob("*.tex"):
            existing[_sha_text(_normalise(path.read_text(encoding="utf-8")))] = path.stem
    target_hashes = {
        stem: _sha_text(_normalise((tex_dir / f"{stem}.tex").read_text(encoding="utf-8")))
        if (tex_dir / f"{stem}.tex").exists() else None
        for stem in stems
    }

    print(
        f"e2e: model={args.model} out={out_root} logs={log_root} figures={len(stems)} "
        f"workers={args.workers} params={request_params}",
        flush=True,
    )
    records: list[dict] = []
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = {
            pool.submit(
                _run_one, client, stem, image_path, args, out_root, log_root, existing, target_hashes[stem]
            ): stem
            for stem, image_path in selected
        }
        for done, future in enumerate(as_completed(futures), start=1):
            stem = futures[future]
            try:
                record = future.result()
            except Exception as exc:  # noqa: BLE001 - defensive: _run_one already catches
                record = {"name": stem, "status": "error", "compiled": False,
                          "error_type": type(exc).__name__, "error": str(exc), "attempts": []}
            records.append(record)
            print(
                f"[{done}/{len(stems)}] {stem} -> status={record.get('status')} "
                f"compiled={record.get('compiled')} tries={record.get('attempts_used')} "
                f"elapsed={record.get('elapsed_seconds')}s",
                flush=True,
            )
            if record.get("compile_errors"):
                print(f"     errors: {' | '.join(record['compile_errors'][:2])}", flush=True)
    records.sort(key=lambda row: row["name"])

    summary = {
        "cohort": "e2e",
        "model": args.model,
        "parameters": request_params,
        "max_attempts": args.attempts,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "requested_stems": stems,
        "compiled": sum(1 for r in records if r["compiled"]),
        "records": records,
    }
    log_root.mkdir(parents=True, exist_ok=True)
    (log_root / "e2e-run.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    failed = [r["name"] for r in records if not r["compiled"]]
    print(f"\ncompiled {summary['compiled']}/{len(records)}; failed: {failed or 'none'}")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
