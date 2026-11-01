"""GeoAgent command line entry point.

Examples (PowerShell):
    python main.py check-env
    python main.py list
    python main.py run --image data/test/image/1035_q_fig1.png
    python main.py batch --limit 5
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from geoagent.archive import archive_and_clean
from geoagent.config import load_settings
from geoagent.datasets import find_item, scan_dataset
from geoagent.orchestration import GeoAgentRunner
from geoagent.tools import discover_compiler


def _settings(args: argparse.Namespace):
    overrides = {
        "max_steps": args.max_steps,
        "max_tool_calls": args.max_tool_calls,
        "max_visual_calls": args.max_visual_calls,
        "max_total_tokens": args.max_total_tokens,
        "timeout_seconds": args.timeout_seconds,
        "geometry_repair": args.geometry_repair,
        "geometry_repair_stage": args.geometry_repair_stage,
        "rectify": args.right_angle_rectify,
        "right_angle_mode": args.right_angle_mode,
    }
    return load_settings({k: v for k, v in overrides.items() if v is not None})


def _print_events(event: dict) -> None:
    kind = event.get("event")
    if kind == "step":
        budget = event.get("budget", {})
        print(f"[step {event['step']}] steps_left={budget.get('steps_left')} tools_left={budget.get('tool_calls_left')} visual_left={budget.get('visual_calls_left')}")
    elif kind == "supervisor_reply":
        calls = ", ".join(event.get("tool_calls") or []) or "(no tool call)"
        print(f"  supervisor -> {calls}")
        if event.get("text"):
            print(f"    {event['text'][:200]}")
    elif kind == "action":
        status = "OK" if event.get("ok") else "FAIL" if event.get("ok") is not None else "-"
        print(f"  [{status}] {event.get('action')} ({event.get('duration_s')}s): {event.get('summary', '')[:200]}")
        if event.get("error"):
            print(f"      error: {event['error'][:300]}")
    elif kind == "done":
        result = event.get("result", {})
        print(f"  done: status={result.get('status')} best_version={result.get('best_version')}")


def cmd_check_env(_args: argparse.Namespace) -> int:
    settings = load_settings()
    compiler = discover_compiler(settings.paths)
    items = scan_dataset(settings.paths.image_dir, settings.paths.latex_dir)
    print("GeoAgent environment")
    print(f"  project root : {settings.paths.project_root}")
    print(f"  model        : {settings.model.model}")
    print(f"  base url     : {settings.model.base_url or '(missing)'}")
    print(f"  api key      : {'present' if settings.model.api_key else 'MISSING'}")
    print(f"  compiler     : {compiler.get('version')} @ {compiler.get('path')} ({compiler.get('origin')})")
    print(f"  images       : {len(items)} paired with {sum(1 for i in items if i.latex_path)} reference tex")
    try:
        import cv2, fitz, numpy, pydantic, scipy  # noqa: F401
        from PIL import Image  # noqa: F401

        print("  core deps    : opencv, pymupdf, numpy, pydantic, scipy, pillow OK")
    except Exception as exc:
        print(f"  core deps    : MISSING {exc}")
    try:
        import streamlit

        print(f"  streamlit    : {streamlit.__version__}")
    except Exception:
        print("  streamlit    : NOT installed (python -m pip install streamlit)")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    settings = load_settings()
    items = scan_dataset(settings.paths.image_dir, settings.paths.latex_dir, limit=args.limit)
    for item in items:
        print(f"{item.stem:24s} {item.width}x{item.height}  ref={'yes' if item.latex_path else 'no'}")
    print(f"total: {len(items)}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    image = Path(args.image)
    if not image.is_absolute():
        image = ROOT / image
    if not image.exists():
        print(f"image not found: {image}")
        return 2
    settings = _settings(args)
    runner = GeoAgentRunner(
        image,
        settings=settings,
        run_dir=args.run_dir,
        on_event=None if args.quiet else _print_events,
    )
    result = runner.run()
    if result.get("best_version") is not None and not args.no_archive:
        result = archive_and_clean(result, args.archive_dir)
    print("\n== RESULT ==")
    print(json.dumps({k: result[k] for k in (
        "status", "stop_reason", "summary", "best_version", "best_score",
        "best_tex_path", "best_png_path", "counts", "elapsed_s")}, ensure_ascii=False, indent=2))
    print(f"run dir: {result['run_dir']}")
    return 0 if result.get("best_version") else 1


def _run_batch_item(item, args: argparse.Namespace, print_lock: threading.Lock) -> dict:
    with print_lock:
        print(f"\n===== {item.stem} =====", flush=True)
    run_settings = _settings(args)
    runner = GeoAgentRunner(
        item.image_path,
        settings=run_settings,
        run_dir=Path(args.out_dir) / f"{item.stem}" if args.out_dir else None,
        on_event=None if args.quiet else _print_events,
    )
    try:
        result = runner.run()
        if result.get("best_version") is not None and not args.no_archive:
            result = archive_and_clean(result, args.archive_dir)
    except Exception as exc:  # one image must not abort the batch
        result = {
            "status": "error",
            "error": f"{type(exc).__name__}: {exc}",
            "best_version": None,
            "best_score": None,
            "usage": {"totals": {"total_tokens": 0}},
            "elapsed_s": 0.0,
        }
    with print_lock:
        print(
            f"  -> [{item.stem}] status={result['status']} best_version={result['best_version']} "
            f"score={result['best_score']} tokens={result['usage']['totals']['total_tokens']} "
            f"elapsed={result['elapsed_s']}s",
            flush=True,
        )
    return item.stem, result


def _archived_result(stem: str, archive_dir: str) -> dict | None:
    path = Path(archive_dir) / "stem" / stem / "result.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def cmd_batch(args: argparse.Namespace) -> int:
    settings = load_settings()
    items = scan_dataset(
        settings.paths.image_dir,
        settings.paths.latex_dir,
        limit=None if args.only else args.limit,
    )
    if args.start:
        items = [i for i in items if i.stem >= args.start]
    if args.only:
        order = {stem: index for index, stem in enumerate(args.only)}
        items = sorted(
            (i for i in items if i.stem in order),
            key=lambda i: order[i.stem],
        )
        for stem in args.only:
            if stem not in {i.stem for i in items}:
                print(f"warning: no dataset image matches stem {stem!r}")
    skipped: dict[str, dict] = {}
    if args.skip_existing:
        kept = []
        for item in items:
            archived = _archived_result(item.stem, args.archive_dir)
            if archived is not None:
                skipped[item.stem] = archived
            else:
                kept.append(item)
        print(f"skip-existing: {len(skipped)} archived, {len(kept)} to run")
        items = kept

    results_by_stem: dict[str, dict] = dict(skipped)
    if items:
        workers = max(1, int(args.workers))
        print(f"running {len(items)} image(s) with {workers} worker(s)", flush=True)
        print_lock = threading.Lock()
        if workers == 1:
            for item in items:
                stem, result = _run_batch_item(item, args, print_lock)
                results_by_stem[stem] = result
        else:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = [
                    pool.submit(_run_batch_item, item, args, print_lock) for item in items
                ]
                for future in as_completed(futures):
                    stem, result = future.result()
                    results_by_stem[stem] = result

    all_items = scan_dataset(
        settings.paths.image_dir,
        settings.paths.latex_dir,
        limit=None if args.only else args.limit,
    )
    if args.only:
        order = {stem: index for index, stem in enumerate(args.only)}
        all_items = [i for i in all_items if i.stem in order]
        all_items.sort(key=lambda i: order[i.stem])
    elif args.start:
        all_items = [i for i in all_items if i.stem >= args.start]
    results = [results_by_stem[i.stem] for i in all_items if i.stem in results_by_stem]
    Path(args.report).parent.mkdir(parents=True, exist_ok=True)
    Path(args.report).write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nreport: {args.report}", flush=True)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="GeoAgent: figure -> TikZ multi-agent reconstruction")
    sub = parser.add_subparsers(dest="command", required=True)

    check = sub.add_parser("check-env", help="verify model, compiler and dataset")
    check.set_defaults(func=cmd_check_env)

    listing = sub.add_parser("list", help="list dataset items")
    listing.add_argument("--limit", type=int, default=20)
    listing.set_defaults(func=cmd_list)

    run = sub.add_parser("run", help="run one image end-to-end")
    run.add_argument("--image", required=True)
    run.add_argument("--run-dir", default=None)
    run.add_argument("--quiet", action="store_true")
    run.add_argument("--max-steps", type=int, default=None)
    run.add_argument("--max-tool-calls", type=int, default=None)
    run.add_argument("--max-visual-calls", type=int, default=None)
    run.add_argument("--max-total-tokens", type=int, default=None)
    run.add_argument("--timeout-seconds", type=int, default=None)
    run.add_argument(
        "--geometry-repair",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="deterministic geometric repair after TikZ generation (default: config)",
    )
    run.add_argument(
        "--right-angle-rectify",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="hard orthogonalisation of verified right-angle markers (default: config)",
    )
    run.add_argument(
        "--right-angle-mode",
        choices=("lock", "soft", "ignore"),
        default=None,
        help="how soft repair treats verified right-angle markers (default: config)",
    )
    run.add_argument("--archive-dir", default="outputs/ours", help="where successful runs are archived")
    run.add_argument("--geometry-repair-stage", choices=("post_tikz", "pre_ges"), default=None,
                     help="repair generated TikZ (default), or replay the legacy GES experiment")
    run.add_argument("--no-archive", action="store_true", help="keep the temporary run directory")
    run.set_defaults(func=cmd_run)

    batch = sub.add_parser("batch", help="run several images and write a JSON report")
    batch.add_argument("--limit", type=int, default=5)
    batch.add_argument("--start", default=None, help="stem to start from (lexicographic)")
    batch.add_argument("--only", nargs="*", default=None, help="explicit stems")
    batch.add_argument("--out-dir", default="outputs/batch")
    batch.add_argument("--report", default="outputs/batch/report.json")
    batch.add_argument("--quiet", action="store_true")
    batch.add_argument(
        "--workers",
        type=int,
        default=4,
        help="parallel image runs (default 4; 1 = sequential)",
    )
    batch.add_argument(
        "--skip-existing",
        action="store_true",
        help="reuse stems whose archive already contains result.json",
    )
    batch.add_argument("--max-steps", type=int, default=None)
    batch.add_argument("--max-tool-calls", type=int, default=None)
    batch.add_argument("--max-visual-calls", type=int, default=None)
    batch.add_argument("--max-total-tokens", type=int, default=None)
    batch.add_argument("--timeout-seconds", type=int, default=None)
    batch.add_argument(
        "--geometry-repair",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="deterministic geometric repair after TikZ generation (default: config)",
    )
    batch.add_argument(
        "--right-angle-rectify",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="hard orthogonalisation of verified right-angle markers (default: config)",
    )
    batch.add_argument(
        "--right-angle-mode",
        choices=("lock", "soft", "ignore"),
        default=None,
        help="how soft repair treats verified right-angle markers (default: config)",
    )
    batch.add_argument("--archive-dir", default="outputs/ours", help="where successful runs are archived")
    batch.add_argument("--geometry-repair-stage", choices=("post_tikz", "pre_ges"), default=None)
    batch.add_argument("--no-archive", action="store_true", help="keep the temporary run directories")
    batch.set_defaults(func=cmd_batch)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
