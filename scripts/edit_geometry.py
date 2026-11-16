"""Apply and verify one local edit to a copy of a reconstructed TikZ figure."""
from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
import re
import sys
from tempfile import TemporaryDirectory

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from geoagent.config import load_settings
from geoagent.evaluation.structure import backend, CORE_POLICY, make_graph
from geoagent.tools import compile_tikz, render_pdf


LABEL = r"[A-Z](?:_?\d+)?"
NAME = r"[A-Za-z][A-Za-z0-9_']*"
NODE = re.compile(r"\\node\b[^;]*;", re.S)
PATH = re.compile(r"\\draw\s*(?:\[([^\[\]]*)\])?\s*([^;]+);", re.S)
CHAIN = re.compile(rf"\({NAME}\)(?:\s*--\s*\({NAME}\))+(?:\s*--\s*cycle)?")
COMMENTS = re.compile(r"(?<!\\)%[^\n]*")


class EditError(ValueError):
    pass


def drawing(tex):
    parsed = backend()[0].parse_drawing(Path("edit.tex"), source_text=tex)
    if parsed.unsupported:
        raise EditError("source_has_unsupported_geometry")
    return parsed


def anchor(parsed, label):
    candidates = [row for row in parsed.labels if row["text"] == label]
    if len(candidates) != 1:
        raise EditError("missing_or_ambiguous_visible_label")
    name = candidates[0]["anchor_expression"]
    if not isinstance(name, str) or not re.fullmatch(NAME, name) or name not in parsed.points:
        raise EditError("label_has_no_simple_named_anchor")
    return name


def stroke_key(a, b, dashed):
    return tuple(sorted((tuple(np.round(a, 9)), tuple(np.round(b, 9))))), dashed


def stroke_counts(parsed):
    return Counter(stroke_key(stroke.a, stroke.b, stroke.dashed) for stroke in parsed.strokes)


def curve_key(curve):
    return tuple(np.round(curve["center"], 9)), round(curve["radius"], 9), curve["full"]


def same_labels(before, after):
    return before.keys() == after.keys() and all(
        np.allclose(before[name], after[name], atol=1e-9, rtol=0) for name in before
    )


def replace_span(tex, span, replacement):
    a, b = span
    return tex[:a] + replacement + tex[b:]


def toggle_dash(tex, visible, parsed, names, expected_strokes):
    paths = {}
    edges = []
    for match in PATH.finditer(visible):
        if not CHAIN.fullmatch(match[2].strip()):
            continue
        chain = re.findall(r"\((" + NAME + r")\)", match[2])
        if match[2].strip().endswith("cycle"):
            chain.append(chain[0])
        paths[match.start()] = match, chain
        edges.extend((match.start(), index, a, b) for index, (a, b) in
                     enumerate(zip(chain, chain[1:])) if a in parsed.points and b in parsed.points)

    selected = [edge for edge in edges if set(edge[2:]) == set(names)]
    if not selected:
        start, end = (parsed.points[name] for name in names)
        offset = end - start
        length = float(np.linalg.norm(offset))
        if length <= 1e-12:
            raise EditError("target_points_coincide")
        unit = offset / length
        extent = max(float(np.linalg.norm(np.ptp(list(parsed.points.values()), axis=0))), length)
        tolerance = 0.0002 * extent
        projected = {}
        for name, point in parsed.points.items():
            delta = point - start
            t = float(delta @ unit)
            if -1e-9 <= t <= length + 1e-9 and np.linalg.norm(delta - t * unit) <= tolerance:
                projected[name] = t
        intervals = []
        for edge in edges:
            left, right = edge[2:]
            if left in projected and right in projected:
                if projected[right] < projected[left]:
                    left, right = right, left
                if projected[right] - projected[left] > 1e-9:
                    intervals.append((projected[left], projected[right], left, right, edge))
        intervals.sort()
        current = names[0]
        for _, _, left, right, edge in intervals:
            if left != current:
                raise EditError("target_has_no_unique_collinear_path")
            selected.append(edge)
            current = right
        if current != names[1]:
            raise EditError("target_has_no_unique_collinear_path")
    if not selected or (len(selected) > 1 and all(set(edge[2:]) == set(names) for edge in selected)):
        raise EditError("target_has_no_unique_collinear_path")

    edits = {}
    styles = set()
    for path, index, a, b in selected:
        solid = stroke_key(parsed.points[a], parsed.points[b], False)
        dashed = stroke_key(parsed.points[a], parsed.points[b], True)
        if expected_strokes[solid] + expected_strokes[dashed] != 1:
            raise EditError("target_stroke_is_ambiguous")
        original_style = bool(expected_strokes[dashed])
        styles.add(original_style)
        edits.setdefault(path, set()).add(index)
        expected_strokes[dashed if original_style else solid] -= 1
        expected_strokes[solid if original_style else dashed] += 1
    if len(styles) != 1:
        raise EditError("target_has_mixed_line_styles")
    original_style = styles.pop()
    for path, indices in sorted(edits.items(), reverse=True):
        match, chain = paths[path]
        style = match[1] or ""
        if re.search(r"->|<-|rounded|shorten|decorat|dotted|\bfill\b|\bclip\b|\bpattern\b(?!\s*=\s*on)", style):
            raise EditError("target_path_has_unsupported_style")
        options = [part.strip() for part in style.split(",") if part.strip()]
        modified = [part for part in options if not re.match(r"(?:densely |loosely )?dashed$|solid$|dash pattern\s*=", part)]
        modified.append("solid" if original_style else "dashed")
        commands = []
        first = 0
        for end in range(1, len(chain)):
            targeted = first in indices
            if end < len(chain) - 1 and (end in indices) == targeted:
                continue
            opts = modified if targeted else options
            commands.append(r"\draw" + ("[" + ", ".join(opts) + "]" if opts else "") + " " +
                            " -- ".join(f"({name})" for name in chain[first:end+1]) + ";")
            first = end
        tex = replace_span(tex, match.span(), "\n".join(commands))
    return tex, not original_style, len(selected)


def edit(tex, operation, labels, *, new_label=None, parsed=None, label_placement="above"):
    """Return the edited source and a postcondition report, or reject the edit."""
    parsed = parsed or drawing(tex)
    if any(not re.fullmatch(LABEL, label) for label in (*labels, *((new_label,) if new_label else ()))):
        raise EditError("unsupported_label_spelling")
    names = [anchor(parsed, label) for label in labels]
    if len(set(names)) != len(names):
        raise EditError("target_points_coincide")
    if new_label and any(row["text"] == new_label for row in parsed.labels):
        raise EditError("new_label_already_exists")
    visible = COMMENTS.sub(lambda m: " " * len(m[0]), tex)
    expected_labels = dict(parsed.labelled)
    expected_strokes = stroke_counts(parsed)
    expected_curves = Counter(map(curve_key, parsed.curves))
    evidence = {"operation": operation, "labels": labels, "anchors": names, "new_label": new_label}

    if operation == "rename":
        rows = [row for row in parsed.labels if row["text"] == labels[0]]
        raw = rows[0]["raw"]
        math_tokens = list(re.finditer(r"\$[^$\n]+\$|\\\([^\n]*?\\\)", raw))
        # Match the existing label in its own node, preserving font and placement.
        spellings = [match for match in NODE.finditer(visible) if
                     re.search(r"\bat\s*\(" + re.escape(names[0]) + r"\)", match[0]) and raw in match[0]]
        if len(spellings) != 1 or spellings[0][0].count(raw) != 1 or len(math_tokens) != 1:
            raise EditError("label_node_not_safely_addressable")
        node = spellings[0]
        token = math_tokens[0]
        start = node.start() + node[0].index(raw) + token.start()
        suffix = re.sub(r"^(\D)_(\d+)$", r"\1_{\2}", new_label)
        edited = replace_span(tex, (start, start + len(token[0])), f"${suffix}$")
        expected_labels[new_label] = expected_labels.pop(labels[0])
    elif operation == "midpoint":
        if label_placement not in ("above", "below", "left", "right"):
            raise EditError("unsupported_label_placement")
        a, b = names
        graph = make_graph(parsed)
        if backend()[1].support(parsed.points[a], parsed.points[b], graph.strokes, graph.span) < CORE_POLICY["drawn_coverage"]:
            raise EditError("target_segment_not_drawn")
        midpoint = (parsed.points[a] + parsed.points[b]) / 2
        if any(np.linalg.norm(midpoint - position) <= 0.012 * graph.span
               for position in parsed.labelled.values()):
            raise EditError("midpoint_near_existing_label")
        fresh = "GeoEdit" + new_label.replace("_", "")
        if fresh in parsed.points or re.search(r"\(" + re.escape(fresh) + r"\)", visible):
            raise EditError("new_coordinate_already_exists")
        if visible.count(r"\end{tikzpicture}") != 1:
            raise EditError("requires_one_tikzpicture")
        suffix = re.sub(r"^(\D)_(\d+)$", r"\1_{\2}", new_label)
        addition = (rf"\coordinate ({fresh}) at ($({a})!0.5!({b})$);" + "\n" +
                    rf"\node[circle,fill,inner sep=1.1pt] at ({fresh}) {{}};" + "\n" +
                    rf"\node[{label_placement}] at ({fresh}) {{${suffix}$}};" + "\n")
        end = visible.index(r"\end{tikzpicture}")
        edited = tex[:end] + addition + tex[end:]
        if not re.search(r"\\usetikzlibrary\{[^}]*\bcalc\b", visible):
            start = visible.find(r"\begin{document}")
            if start < 0:
                raise EditError("missing_document_preamble")
            edited = edited[:start] + "\\usetikzlibrary{calc}\n" + edited[start:]
        expected_labels[new_label] = midpoint
        evidence["new_anchor"] = fresh
    elif operation == "toggle-dash":
        edited, evidence["dashed"], evidence["edited_segments"] = toggle_dash(
            tex, visible, parsed, names, expected_strokes
        )
    else:
        raise EditError("unsupported_edit")

    after = drawing(edited)
    if not same_labels(expected_labels, after.labelled) or expected_strokes != stroke_counts(after):
        raise EditError("edit_postcondition_failed")
    if expected_curves != Counter(map(curve_key, after.curves)):
        raise EditError("edit_changed_curve_geometry")
    return edited, evidence


def compile_edit(tex, evidence, settings, out, *, stem="edited"):
    names = evidence["anchors"] + ([evidence["new_anchor"]] if evidence.get("new_anchor") else [])
    compiled = compile_tikz(tex, out_dir=out, stem=stem, paths=settings.paths,
                            timeout=settings.budget.compile_timeout_seconds, probe_names=tuple(names))
    if not compiled["ok"] or set(compiled.get("points_sp", {})) != set(names):
        raise EditError("edited_program_failed_compilation_or_readback")
    if evidence["operation"] == "midpoint":
        a, b, mid = (compiled["points_sp"][name] for name in names)
        if any(abs(2 * m - x - y) > 4 for x, y, m in zip(a, b, mid)):
            raise EditError("compiled_midpoint_failed")
    return compiled


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("operation", choices=("rename", "midpoint", "toggle-dash"))
    parser.add_argument("labels", nargs="+")
    parser.add_argument("--new-label")
    parser.add_argument("--label-placement", choices=("above", "below", "left", "right"), default="above",
                        help="placement of a new midpoint label")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if (len(args.labels) != (1 if args.operation == "rename" else 2)
            or bool(args.new_label) != (args.operation != "toggle-dash")):
        parser.error("use one label for rename, two for midpoint or toggle-dash, and --new-label for rename/midpoint")
    if args.out.suffix != ".tex" or args.out.resolve() == args.source.resolve() or args.out.exists():
        parser.error("choose a new .tex output path")
    try:
        tex, evidence = edit(args.source.read_text(encoding="utf-8"), args.operation,
                             args.labels, new_label=args.new_label, label_placement=args.label_placement)
        with TemporaryDirectory(prefix="geoagent_edit_") as temporary:
            compiled = compile_edit(tex, evidence, load_settings(), temporary)
            png = Path(temporary) / "edited.png"
            if not render_pdf(compiled["pdf_path"], png, dpi=200)["ok"]:
                raise EditError("edited_preview_failed")
            if args.out.with_suffix(".png").exists() or args.out.with_suffix(".pdf").exists():
                raise EditError("preview_path_already_exists")
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(tex, encoding="utf-8")
            args.out.with_suffix(".pdf").write_bytes(Path(compiled["pdf_path"]).read_bytes())
            args.out.with_suffix(".png").write_bytes(png.read_bytes())
    except (EditError, ValueError) as exc:
        parser.exit(1, f"Edit rejected: {exc}\n")
    print(args.out.resolve())


if __name__ == "__main__":
    main()
