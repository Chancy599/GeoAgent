"""Local edits and geometric checks for reconstructed TikZ figures."""
from __future__ import annotations

from collections import Counter
from pathlib import Path
import re

import numpy as np

from geoagent.evaluation.structure import backend, CORE_POLICY, make_graph
from geoagent.tools import compile_tikz


LABEL = r"[A-Z](?:_?\d+)?"
NAME = r"[A-Za-z][A-Za-z0-9_']*"
NODE = re.compile(r"\\node\b[^;]*;", re.S)
PATH = re.compile(r"\\draw\s*(?:\[([^\[\]]*)\])?\s*([^;]+);", re.S)
CHAIN = re.compile(rf"\({NAME}\)(?:\s*--\s*\({NAME}\))+(?:\s*--\s*cycle)?")
COMMENTS = re.compile(r"(?<!\\)%[^\n]*")
OPERATIONS = {
    "rename": (1, True),
    "midpoint": (2, True),
    "toggle-dash": (2, False),
    "add-segment": (2, False),
    "delete-segment": (2, False),
    "perpendicular": (3, True),
}
INSTRUCTIONS = (
    ("add-segment", rf"连接点(?P<a>{LABEL})和点(?P<b>{LABEL})画出实线线段(?P=a)(?P=b)"),
    ("delete-segment", rf"删除线段(?P<a>{LABEL})(?P<b>{LABEL})的笔画保留点(?P=a)点(?P=b)及其标签"),
    ("midpoint", rf"在线段({LABEL})({LABEL})的中点添加一个实心点并标记为({LABEL})"),
    ("perpendicular", rf"从点(?P<a>{LABEL})向线段({LABEL})({LABEL})作垂线画出线段(?P=a)(?P<h>{LABEL})把垂足标记为(?P=h)并在(?P=h)处标出直角"),
    ("rename", rf"把点({LABEL})的标签改为({LABEL})保留该点的位置和与它相连的线段"),
)


class EditError(ValueError):
    pass


def parse_instruction(instruction):
    """Bind a supported Chinese instruction to one explicit edit operation."""
    normalized = re.sub(r'[\s，。、“”「」,.]+', '', instruction).removesuffix("保留其余图元标签和布局")
    for operation, pattern in INSTRUCTIONS:
        match = re.fullmatch(pattern, normalized)
        if match:
            count, has_new_label = OPERATIONS[operation]
            return operation, match.groups()[:count], match[count + 1] if has_new_label else None
    raise EditError("unsupported_instruction")


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


def rewrite_segment(tex, visible, parsed, names, expected_strokes, *, delete=False):
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
        if not delete:
            expected_strokes[solid if original_style else dashed] += 1
    if not delete and len(styles) != 1:
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
            if not (targeted and delete):
                opts = modified if targeted else options
                commands.append(r"\draw" + ("[" + ", ".join(opts) + "]" if opts else "") + " " +
                                " -- ".join(f"({name})" for name in chain[first:end+1]) + ";")
            first = end
        tex = replace_span(tex, match.span(), "\n".join(commands))
    return tex, not original_style, len(selected)


def append_to_picture(tex, visible, commands, *, libraries=()):
    if visible.count(r"\end{tikzpicture}") != 1:
        raise EditError("requires_one_tikzpicture")
    end = visible.index(r"\end{tikzpicture}")
    tex = tex[:end] + "\n".join(commands) + "\n" + tex[end:]
    loaded = {name.strip() for options in re.findall(r"\\usetikzlibrary\{([^}]+)\}", visible)
              for name in options.split(",")}
    missing = [name for name in libraries if name not in loaded]
    if missing:
        start = visible.find(r"\begin{document}")
        if start < 0:
            raise EditError("missing_document_preamble")
        tex = tex[:start] + r"\usetikzlibrary{" + ",".join(missing) + "}\n" + tex[start:]
    return tex


def segment_support(start, end, parsed, span):
    return backend()[1].support(start, end, parsed.strokes, span)


def edit(tex, operation, labels, *, new_label=None, parsed=None, label_placement=None):
    """Return the edited source and a postcondition report, or reject the edit."""
    if operation not in OPERATIONS:
        raise EditError("unsupported_edit")
    count, has_new_label = OPERATIONS[operation]
    if len(labels) != count or bool(new_label) != has_new_label:
        raise EditError("invalid_edit_arguments")
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
    elif operation in ("midpoint", "perpendicular"):
        if label_placement not in (None, "above", "below", "left", "right"):
            raise EditError("unsupported_label_placement")
        a, b = names[-2:]
        start, end = parsed.points[a], parsed.points[b]
        graph = make_graph(parsed)
        if segment_support(start, end, parsed, graph.span) < CORE_POLICY["drawn_coverage"]:
            raise EditError("target_segment_not_drawn")

        if operation == "midpoint":
            point = (start + end) / 2
            modifier = "0.5"
            label_placement = label_placement or "above"
        else:
            vertex = parsed.points[names[0]]
            direction = end - start
            fraction = float((vertex - start) @ direction / (direction @ direction))
            if not 0 < fraction < 1:
                raise EditError("perpendicular_foot_outside_segment")
            point = start + fraction * direction
            modifier = f"({names[0]})"
            if segment_support(vertex, point, parsed, graph.span) > 0:
                raise EditError("perpendicular_overlaps_existing_stroke")
            if label_placement is None:
                # Put the label on the side opposite the perpendicular segment.
                dx, dy = vertex - point
                if abs(dy) >= abs(dx):
                    label_placement = "below" if dy > 0 else "above"
                else:
                    label_placement = "left" if dx > 0 else "right"
        if any(np.linalg.norm(point - position) <= 0.012 * graph.span
               for position in parsed.labelled.values()):
            raise EditError(f"{operation}_near_existing_label")
        fresh = "GeoEdit" + new_label.replace("_", "")
        if fresh in parsed.points or re.search(r"\(" + re.escape(fresh) + r"\)", visible):
            raise EditError("new_coordinate_already_exists")
        suffix = re.sub(r"^(\D)_(\d+)$", r"\1_{\2}", new_label)
        commands = [rf"\coordinate ({fresh}) at ($({a})!{modifier}!({b})$);"]
        if operation == "midpoint":
            commands.append(rf"\node[circle,fill,inner sep=2pt] at ({fresh}) {{}};")
            libraries = ("calc",)
        else:
            vertex_name = names[0]
            commands.extend((
                rf"\draw[solid] ({vertex_name}) -- ({fresh});",
                rf"\draw pic[draw, solid, angle radius=7pt] {{right angle={vertex_name}--{fresh}--{b}}};",
            ))
            libraries = ("calc", "angles")
            expected_strokes[stroke_key(vertex, point, False)] += 1
            evidence["right_angle_marker"] = True
        commands.append(rf"\node[{label_placement}] at ({fresh}) {{${suffix}$}};")
        edited = append_to_picture(tex, visible, commands, libraries=libraries)
        expected_labels[new_label] = point
        evidence["new_anchor"] = fresh
    elif operation == "add-segment":
        a, b = names
        start, end = parsed.points[a], parsed.points[b]
        if np.linalg.norm(end - start) <= 1e-9:
            raise EditError("target_points_coincide")
        if segment_support(start, end, parsed, make_graph(parsed).span) > 0:
            raise EditError("target_overlaps_existing_stroke")
        edited = append_to_picture(tex, visible, [rf"\draw[solid] ({a}) -- ({b});"])
        expected_strokes[stroke_key(start, end, False)] += 1
        evidence["edited_segments"] = 1
    else:
        deleting = operation == "delete-segment"
        edited, dashed, evidence["edited_segments"] = rewrite_segment(
            tex, visible, parsed, names, expected_strokes, delete=deleting
        )
        if not deleting:
            evidence["dashed"] = dashed

    after = drawing(edited)
    if not same_labels(expected_labels, after.labelled) or expected_strokes != stroke_counts(after):
        raise EditError("edit_postcondition_failed")
    if expected_curves != Counter(map(curve_key, after.curves)):
        raise EditError("edit_changed_curve_geometry")
    if operation == "delete-segment":
        start, end = (parsed.points[name] for name in names)
        if segment_support(start, end, after, make_graph(parsed).span) > 0:
            raise EditError("target_segment_still_drawn")
    return edited, evidence


def compiled_perpendicular(points):
    vertex, start, end, foot = np.asarray(points, dtype=float)
    base = end - start
    height = vertex - foot
    length = float(np.linalg.norm(base))
    height_length = float(np.linalg.norm(height))
    if min(length, height_length) <= 0:
        raise EditError("compiled_perpendicular_is_degenerate")
    direction = base / length
    relative = foot - start
    fraction = float(relative @ direction / length)
    distance = float(abs(relative[0] * direction[1] - relative[1] * direction[0]))
    angle_error = float(np.degrees(np.arcsin(np.clip(abs(height @ direction) / height_length, 0, 1))))
    if not 0 < fraction < 1 or distance > max(4.0, 1e-5 * length) or angle_error > 0.01:
        raise EditError("compiled_perpendicular_failed")
    return {"foot_fraction": fraction, "foot_distance_sp": distance, "angle_error_deg": angle_error}


def compile_edit(tex, evidence, settings, out, *, stem="edited"):
    names = [*evidence["anchors"]]
    if evidence.get("new_anchor"):
        names.append(evidence["new_anchor"])
    compiled = compile_tikz(tex, out_dir=out, stem=stem, paths=settings.paths,
                            timeout=settings.budget.compile_timeout_seconds, probe_names=tuple(names))
    if not compiled["ok"] or set(compiled.get("points_sp", {})) != set(names):
        detail = "; ".join(compiled.get("errors", [])[:2])
        raise EditError(f"edited_program_failed_compilation_or_readback: {detail}" if detail
                        else "edited_program_failed_compilation_or_readback")
    points = [compiled["points_sp"][name] for name in names]
    verification = {}
    if evidence["operation"] == "midpoint":
        a, b, mid = points
        axis_error = max(abs(2 * m - x - y) / 2 for x, y, m in zip(a, b, mid))
        if axis_error > 2:
            raise EditError("compiled_midpoint_failed")
        verification["max_midpoint_axis_error_sp"] = axis_error
    elif evidence["operation"] == "perpendicular":
        verification = compiled_perpendicular(points)
    compiled["edit_verification"] = verification
    return compiled
