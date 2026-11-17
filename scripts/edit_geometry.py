"""Apply and verify one local edit to a copy of a reconstructed TikZ figure."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from geoagent.config import load_settings
from geoagent.editing import LABEL, OPERATIONS, EditError, compile_edit, drawing, edit, parse_instruction
from geoagent.tools import render_pdf


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("operation", nargs="?", choices=OPERATIONS)
    parser.add_argument("labels", nargs="*")
    parser.add_argument("--instruction", help="one supported Chinese edit instruction")
    parser.add_argument("--new-label")
    parser.add_argument("--label-placement", choices=("above", "below", "left", "right"),
                        help="placement of a new point label")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--report", action="store_true", help="save verification as a JSON file alongside the result")
    args = parser.parse_args()
    if args.instruction is None and args.operation is None:
        parser.error("provide --instruction or an operation with its point labels")
    if args.instruction is not None and (args.operation is not None or args.labels or args.new_label):
        parser.error("--instruction cannot be combined with an operation or --new-label")
    outputs = [args.out, args.out.with_suffix(".pdf"), args.out.with_suffix(".png")]
    if args.report:
        outputs.append(args.out.with_suffix(".json"))
    if args.out.suffix != ".tex" or any(path.exists() for path in outputs):
        parser.error("choose a new .tex output path with unused preview and report paths")
    try:
        operation, labels, new_label = (
            parse_instruction(args.instruction) if args.instruction is not None
            else (args.operation, args.labels, args.new_label)
        )
        tex, evidence = edit(args.source.read_text(encoding="utf-8"), operation, labels,
                             new_label=new_label, label_placement=args.label_placement)
        with TemporaryDirectory(prefix="geoagent_edit_") as temporary:
            compiled = compile_edit(tex, evidence, load_settings(), temporary)
            png = Path(temporary) / "edited.png"
            if not render_pdf(compiled["pdf_path"], png, dpi=200)["ok"]:
                raise EditError("edited_preview_failed")
            payloads = [tex.encode("utf-8"), Path(compiled["pdf_path"]).read_bytes(), png.read_bytes()]
            if args.report:
                report = {
                    "instruction": args.instruction,
                    "source": str(args.source.resolve()),
                    **evidence,
                    "source_verified": True,
                    "compiled": True,
                    "points_sp": compiled["points_sp"],
                    **compiled["edit_verification"],
                }
                payloads.append((json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
            args.out.parent.mkdir(parents=True, exist_ok=True)
            created = []
            try:
                for path, payload in zip(outputs, payloads, strict=True):
                    with path.open("xb") as output:
                        created.append(path)
                        output.write(payload)
            except OSError:
                for path in created:
                    path.unlink(missing_ok=True)
                raise
    except (ValueError, OSError) as exc:
        parser.exit(1, f"Edit rejected: {exc}\n")
    print(args.out.resolve())


if __name__ == "__main__":
    main()
