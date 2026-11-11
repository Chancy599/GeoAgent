"""Deterministic handoff of unambiguous labelled CV measurements to TikZ.

No reference geometry is read. Only current explicit CV label bindings are
eligible; inferred/rounded agent points cannot replace the measurements.
"""
from __future__ import annotations

import math
import re

import numpy as np

from .tikz_geometry import clean
from .coordinate_precision import number, quantize_tex
from .schemas import Relation

MEASURED_POINT_SOURCES = {'cv:bind_point_labels', 'cv:construction_intersection', 'cv:construction_mark_vertex'}

def binding_review_points(state):
    """Existing CV vertices and current assignments available for visual review."""
    return {
        key: {"px": obj.coords["px"], "label": obj.label}
        for key, obj in state.objects.items()
        if obj.type == "point" and obj.source in MEASURED_POINT_SOURCES
        and obj.status not in ("rejected", "conflict")
        and isinstance(obj.coords.get("px"), (list, tuple)) and len(obj.coords["px"]) == 2
    }


def _set_reviewed_binding(state, label, point_id, reason, source='critic_agent'):
    old = state.objects.get(state.label_bindings.get(label))
    if old is not None and old.label == label:
        old.label = None
    state.objects[point_id].label = label
    state.label_bindings[label] = point_id
    state.add_relation(Relation(id=f"rel_label_{label}", subject=f"label_{label}",
                                relation="labels_point", object=point_id, source=source,
                                evidence=reason, status="confirmed"))


def _remove_replaced_label(state, point_id, replaced):
    if replaced is not None and state.label_bindings.get(replaced) == point_id:
        state.label_bindings.pop(replaced)
        state.relations.pop(f"rel_label_{replaced}", None)


def restore_reviewed_bindings(state):
    """Keep a confirmed choice after identical CV measurements are ingested again."""
    for label, review in state.meta.get("reviewed_bindings", {}).items():
        point_id = review["point_id"]
        obj = state.objects.get(point_id)
        if (obj is not None and obj.coords.get("px") == review["px"]
                and all(name in (label, review.get("replaces")) or owner != point_id
                        for name, owner in state.label_bindings.items())):
            _remove_replaced_label(state, point_id, review.get("replaces"))
            _set_reviewed_binding(state, label, point_id, review["reason"], review.get('source','critic_agent'))


def apply_reviewed_bindings(state, proposals, *, source='critic_agent'):
    """Rebind verified glyphs to measured points without altering coordinates."""
    if not isinstance(proposals, list):
        return {}
    measured = binding_review_points(state)
    accepted = {}
    rows = [row for row in proposals[:8] if isinstance(row, dict)]
    rows.sort(key=lambda row: not (
        isinstance(row.get("label"), str) and row["label"] in state.label_bindings
    ))
    for row in rows:
        label, point_id, reason = (row.get(key) for key in ("label", "point_id", "reason"))
        if not all(isinstance(value, str) for value in (label, point_id, reason)):
            continue
        old = state.label_bindings.get(label)
        owner = next((name for name, key in state.label_bindings.items() if key == point_id), None)
        if (not re.fullmatch("[A-Z]", label) or old == point_id or label in accepted
                or point_id not in measured or not reason.strip()
                or (owner is not None and owner != row.get("replaces"))
                or state.objects[point_id].label not in (None, label, owner)):
            continue
        _remove_replaced_label(state, point_id, owner)
        _set_reviewed_binding(state, label, point_id, reason.strip()[:300], source)
        accepted[label] = {"point_id": point_id, "px": list(measured[point_id]["px"]),
                           "previous_point_id": old, "reason": reason.strip()[:300]}
        if source != 'critic_agent':
            accepted[label]['source'] = source
        if owner is not None:
            accepted[label]["replaces"] = owner
    if accepted:
        state.meta.setdefault("reviewed_bindings", {}).update(accepted)
        state.add_evidence(source=source, method="measured_label_rebinding",
                           summary=f"Corrected {len(accepted)} source label bindings", payload=accepted)
    return accepted


def coordinate_frame(state, metrics=None):
    scale = float((metrics or {}).get('suggested_scale') or
                  8 / max(1, state.image_size.get('width', 0), state.image_size.get('height', 0)))
    if not math.isfinite(scale) or scale <= 0:
        raise ValueError('Invalid coordinate scale')
    return scale, [state.image_size.get('width', 0) / 2, state.image_size.get('height', 0) / 2]


def build_coordinate_contract(state, metrics=None):
    points = {}
    skipped = {}
    for label, point_id in sorted(state.label_bindings.items()):
        # Restrict this first implementation to ordinary single-letter labels.
        if not re.fullmatch('[A-Z]', label):
            continue
        obj = state.objects.get(point_id)
        review = state.meta.get("reviewed_bindings", {}).get(label, {})
        verified = bool(obj and review.get("point_id") == point_id and review.get("px") == obj.coords.get("px"))
        labels = [o for o in state.objects.values() if o.type == 'label' and o.label == label
                  and o.status != 'rejected']
        if (obj is None or obj.type != 'point' or obj.label != label or obj.source not in MEASURED_POINT_SOURCES
                or obj.status in ('rejected', 'conflict')
                or (not verified and any(o.attributes.get('ambiguous') for o in labels))):
            skipped[label] = 'missing_or_ambiguous_cv_binding'
            continue
        xy = obj.coords.get('px')
        if not isinstance(xy, (list, tuple)) or len(xy) != 2:
            continue
        try:
            xy = [float(v) for v in xy]
        except (TypeError, ValueError):
            continue
        if not all(math.isfinite(v) for v in xy):
            continue
        points[label] = {'point_id': point_id, 'px': xy}
        if verified:
            points[label]['reviewed'] = True
    if not points:
        return None
    for anchor, extension in state.meta.get('source_construction', {}).get('extensions', {}).items():
        if anchor in points:
            points['GeoTail'+anchor] = {'px': extension['px'], 'point_id': extension['stroke_id'],
                                        'extension_from': anchor}
    # The same scale is used in the style block; no model arithmetic is needed.
    scale, origin = coordinate_frame(state, metrics)
    for point in points.values():
        x, y = point['px']
        point['tikz'] = [float(number((x-origin[0])*scale)), float(number((origin[1]-y)*scale))]
    for p, foot, a, b in state.meta.get('source_construction', {}).get('feet', []):
        if not all(name in points for name in (p,foot,a,b)):
            continue
        origin_xy, end, source_xy = (np.asarray(points[name]['tikz']) for name in (a,b,p))
        direction = end-origin_xy
        length_sq = float(direction@direction)
        if length_sq > 0:
            projected = origin_xy + direction*float((source_xy-origin_xy)@direction)/length_sq
            if np.linalg.norm(projected-points[foot]['tikz']) <= 6*scale:
                points[foot]['tikz'] = [float(number(v)) for v in projected]
                points[foot]['projection'] = [p,a,b]
    return {'schema': 'cv-coordinate-contract.v1', 'scale': scale, 'origin_px': origin,
            'points': points, 'skipped': skipped, 'reference_used': False, 'coordinate_decimals': 3}


def coordinate_block(contract):
    return '\n'.join(r'\coordinate ('+name+') at ('+','.join(number(v) for v in p['tikz'])+');'
                     for name, p in contract['points'].items())


def contract_prompt(contract):
    return ('PROGRAM-OWNED CV COORDINATES (authoritative over duplicate GES points):\n'
            'The program inserts the following definitions at the start of tikzpicture. '
            'DO NOT emit or redefine these coordinates. Use these names for their visible labels, '
            'edges, curves and angle marks. Do not replace measured vertices by literal endpoints '
            'or aliases. No scope, coordinate-system transforms, or local transforms on paths. '
            'Style and label placement offsets are allowed. All other positions/radii must use '
            'this same coordinate frame. If a measurement is wrong, report it in notes for '
            'remeasurement; do not silently move it.\n'+coordinate_block(contract))


def apply_coordinate_contract(tex, contract):
    if contract is None:
        return quantize_tex(tex), {'enabled': False, 'reason': 'no_unambiguous_cv_bindings', 'coordinate_decimals': 3}
    source = clean(tex)
    if (source.count(r'\begin{tikzpicture}') != 1 or r'\begin{scope}' in source
            or re.search(r'\b(?:x|y|scale|xscale|yscale|rotate|rotate around|cm|shift|transform canvas)\s*=', source)):
        raise ValueError('CV coordinate contract requires one picture without coordinate transforms/scopes')
    # Model definitions may only repeat the exact supplied measurement. Incorrect
    # frames/rounding are rejected, rather than silently changing curve radii etc.
    pattern = r'\\coordinate\s*\(([A-Z]|GeoTail[A-Z])\)\s*at\s*(.*?);'
    seen = set()
    def remove_definition(match):
        label = match[1]
        if label not in contract['points']:
            return match[0]
        literal = re.fullmatch(r'\s*\(\s*([-+\d.eE]+)\s*,\s*([-+\d.eE]+)\s*\)\s*', match[2])
        expected = contract['points'][label]['tikz']
        if label in seen or not literal or not np.allclose(list(map(float, literal.groups())), expected,
                                                          rtol=0, atol=contract['scale']*1e-7):
            raise ValueError(f'Coordinate {label} redefined: omit its definition and use the program-owned name')
        seen.add(label)
        return ''
    source = re.sub(pattern, remove_definition, source, flags=re.S)
    # Reject alternate defining constructs instead of letting a later node/path
    # overwrite a program-owned coordinate. Decorative label nodes are unnamed.
    nodes = re.findall(r'\\node\b[^;]*;', source, re.S)
    for label, point in contract['points'].items():
        # Also covers path syntax such as "... coordinate (A)" without a slash.
        if re.search(r'\b(?:coordinate|node)\s*(?:\[[^\]]*\]\s*)?\('+label+r'\)', source):
            raise ValueError(f'Coordinate {label} may not be redefined by a node/path')
        if point.get('extension_from'):
            continue
        found = False
        for node in nodes:
            text = re.sub(r'\\fontsize\s*\{[^{}]*\}\s*\{[^{}]*\}', '', node)
            text = re.sub(r'\\(?:selectfont|bfseries|itshape|rmfamily)\b', '', text)
            text = re.sub(r'\\(?:mathrm|mathit|mathbf|text)\s*\{([A-Z])\}', r'\1', text)
            if not re.search(r'\{\s*\$?'+label+r'\$?\s*\}\s*;', text):
                continue
            found = True
            if not re.search(r'\bat\s*\(\s*'+label+r'\s*\)', node):
                raise ValueError(f'Visible label {label} must use at ({label})')
        if point.get('reviewed') and not found:
            raise ValueError(f'Visually verified label {label} needs a visible node at ({label})')
    for draw in re.findall(r'\\(?:draw|path|fill|filldraw)\b[^;]*;', source, re.S):
        if re.search(r'\b(?:xshift|yshift)\s*=', draw):
            raise ValueError('Do not apply path-local shifts to program-owned vertices')
    start = re.search(r'\\begin\{tikzpicture\}(?:\s*\[[^\]]*\])?', source)
    source = source[:start.end()]+'\n'+coordinate_block(contract)+'\n'+source[start.end():]
    return quantize_tex(source), {'enabled': True, 'schema': contract['schema'], 'n_points': len(contract['points']),
                    'reference_used': False, 'coordinates': contract}
