"""Label-bound source geometry. Unlabelled points never enter the metric."""
from __future__ import annotations

from collections import defaultdict
from functools import lru_cache
import itertools
import hashlib
import json
import importlib
import os
from pathlib import Path
import sys
from types import SimpleNamespace

import numpy as np

PROTOCOL = "label-bound-v1"
CORE_POLICY = {
    "schema": PROTOCOL,
    "vertex_matching": "exact visible label identity; explicit code anchor; no spatial matching",
    "glyphs": "small orthogonal paths supported by two longer body directions; protected labelled corners",
    "text_anchors": "resolve visible label binding; presentation offsets are ignored; no nearest-point snap",
    "unused_coordinates": "all unlabelled points excluded, including implicit crossings",
    "scope": "drawn straight segments between labelled anchors; all supported labelled pairs, including composite segments",
    "ratios": "one ordered ratio per unordered pair of incident segments, sorted by visible label",
    "drawn_coverage": .95,
    "minimum_angle_degrees": 5.,
    "duplicate_labels": "same-anchor repeats deduplicated; conflicting anchors unresolved",
    "glyph_max_diagonal_fraction": .20,
    "glyph_max_side_ratio": 1.4,
    "glyph_turn_tolerance_degrees": 5,
    "body_min_length_fraction": .12,
    "body_min_glyph_side_multiple": 3,
    "same_protocol_required": True,
}


@lru_cache(maxsize=1)
def backend():
    root = Path(__file__).resolve().parents[2]
    location = Path(os.environ.get("GEOAGENT_GEOM2CODE", root.parents[1] / "geom2code"))
    if not (location / "agent/structural_geometry.py").is_file():
        raise RuntimeError("Geometry parser unavailable; set GEOAGENT_GEOM2CODE to the geom2code checkout")
    if str(location) not in sys.path:
        sys.path.append(str(location))
    evaluator = importlib.import_module("agent.eval_structure")
    return importlib.import_module("geoagent.evaluation.bounded_tikz"), evaluator


def _distance(point, a, b):
    v = b - a
    t = np.clip(float((point - a) @ v) / max(float(v @ v), 1e-24), 0., 1.)
    return float(np.linalg.norm(point - a - t * v))


def _marker_anchor(chain, others, labels, span):
    """A small square/elbow must sit on two substantially longer body rays.

    A label explicitly attached to any non-anchor corner protects the path:
    a labelled small polygon is not silently reclassified as a glyph.
    """
    if not 2 <= len(chain) <= 4 or span <= 0 or any(s.dashed for s in chain):
        return None
    points = [chain[0].a] + [s.b for s in chain]
    if any(np.linalg.norm(a.b - b.a) > 1e-7 * span for a, b in zip(chain, chain[1:])):
        return None
    lengths = [s.length for s in chain]
    if min(lengths) <= 1e-10 or max(lengths) / min(lengths) > CORE_POLICY["glyph_max_side_ratio"]:
        return None
    if np.linalg.norm(np.ptp(points, axis=0)) > CORE_POLICY["glyph_max_diagonal_fraction"] * span:
        return None
    axes = [(s.b - s.a) / s.length for s in chain]
    if any(abs(float(a @ b)) > np.sin(np.deg2rad(CORE_POLICY["glyph_turn_tolerance_degrees"])) for a, b in zip(axes, axes[1:])):
        return None
    anchors = [points[0] + points[2] - points[1]] if len(chain) == 2 else points
    tolerance = .15 * min(lengths)
    long = [s for s in others if s.length >= max(CORE_POLICY["body_min_glyph_side_multiple"] * max(lengths),
                                               CORE_POLICY["body_min_length_fraction"] * span)]
    for anchor in anchors:
        if any(np.linalg.norm(label["position"] - p) < 1e-7 * span
               and np.linalg.norm(p - anchor) > tolerance
               for label in labels for p in points):
            continue
        rays = [(s.b - s.a) / s.length for s in long if _distance(anchor, s.a, s.b) <= tolerance]
        aligned = [u for u in rays if max(abs(float(u @ a)) for a in axes) >= np.cos(np.deg2rad(8))]
        if any(abs(float(a @ b)) <= np.sin(np.deg2rad(10))
               for i, a in enumerate(aligned) for b in aligned[i + 1:]):
            return np.asarray(anchor)
    return None


def core_drawing(drawing):
    """Return a new drawing view, with an auditable list of excluded paths."""
    strokes = [s for s in drawing.strokes if s.length > 1e-10]
    coords = [p for s in strokes for p in (s.a, s.b)]
    span = float(np.linalg.norm(np.ptp(coords, axis=0))) if coords else 0.
    groups = defaultdict(list)
    for index, stroke in enumerate(strokes):
        groups[stroke.source].append(index)
    removed, exclusions = set(), []
    for source, indices in groups.items():
        selected = set(indices)
        chain = [strokes[i] for i in indices]
        anchor = _marker_anchor(chain, [s for i, s in enumerate(strokes) if i not in selected], drawing.labels, span)
        if anchor is not None:
            removed.update(indices)
            exclusions.append({"reason": "right_angle_glyph_on_body_rays", "path": source,
                               "anchor": anchor.tolist(), "stroke_count": len(indices)})
    # The same elbow can be written as two separate named draw commands.
    singles = [indices[0] for indices in groups.values() if len(indices) == 1
               and indices[0] not in removed and strokes[indices[0]].length <= .08 * span]
    for offset, i in enumerate(singles):
        if i in removed:
            continue
        for j in singles[offset + 1:]:
            if j in removed:
                continue
            left, right = strokes[i], strokes[j]
            candidates = []
            for a, b in ((left, right), (right, left)):
                for reverse_a in (False, True):
                    for reverse_b in (False, True):
                        # Views only: leave original parser objects untouched.
                        def orient(s, reverse):
                            return SimpleNamespace(a=s.b if reverse else s.a, b=s.a if reverse else s.b,
                                                   length=s.length, dashed=s.dashed)
                        candidates.append([orient(a, reverse_a), orient(b, reverse_b)])
            others = [s for k, s in enumerate(strokes) if k not in (i, j) and k not in removed]
            anchor = next((a for chain in candidates if (a := _marker_anchor(chain, others, drawing.labels, span)) is not None), None)
            if anchor is not None:
                removed.update((i, j))
                exclusions.append({"reason": "split_right_angle_glyph_on_body_rays",
                                   "paths": [left.source, right.source], "anchor": anchor.tolist(), "stroke_count": 2})
                break
    kept = [s for i, s in enumerate(strokes) if i not in removed]
    endpoints = [p for s in kept for p in (s.a, s.b)]
    positions = [np.asarray(l["position"]) for l in drawing.labels]
    tolerance = 1e-7 * max(span, 1e-9)
    # Declared coordinates remain meaningful if used by a body path or an
    # actual label attachment. Unused helper aliases cannot split body edges.
    points = {name: p for name, p in drawing.points.items()
              if any(np.linalg.norm(p - q) <= tolerance for q in endpoints + positions)}
    result = SimpleNamespace(points=points, strokes=kept, labels=[], curves=list(drawing.curves),
                             unsupported=list(drawing.unsupported), excluded=list(drawing.excluded) + exclusions)
    audit = {"protocol": PROTOCOL, "excluded_glyphs": exclusions,
             "removed_strokes": len(removed), "ignored_coordinate_names": sorted(set(drawing.points) - set(points)),
             "literal_label_anchors_create_vertices": True,
             "scope": "label-bound straight segments; unlabelled crossings excluded"}
    return result, audit


def make_graph(drawing):
    filtered, audit = core_drawing(drawing)
    by_label = defaultdict(list)
    for entry in drawing.labels:
        by_label[entry['text']].append(entry)
    extent = [p for s in filtered.strokes for p in (s.a, s.b)]
    extent += [e['position'] for e in drawing.labels]
    span = float(np.linalg.norm(np.ptp(extent, axis=0))) if extent else 0.
    tolerance = 1e-7 * max(span, 1e-9)
    bindings, ambiguous, conflicts = {}, {}, []
    for name, entries in sorted(by_label.items()):
        xy = np.asarray(entries[0]['position'], float)
        if any(np.linalg.norm(np.asarray(e['position']) - xy) > tolerance for e in entries[1:]):
            ambiguous[name] = [np.asarray(e['position']).tolist() for e in entries]
            continue
        aliases = sorted(k for k, v in drawing.points.items() if np.linalg.norm(v-xy) <= tolerance)
        bindings[name] = {'xy': xy.tolist(), 'coordinate_aliases': aliases,
                          'expressions': [e.get('anchor_expression') for e in entries],
                          'occurrences': len(entries)}
        if name in drawing.points and np.linalg.norm(drawing.points[name]-xy) > tolerance:
            conflicts.append({'label': name, 'bound_xy': xy.tolist(),
                              'same_name_coordinate_xy': drawing.points[name].tolist(),
                              'resolution': 'visible label binding wins'})
    names = sorted(bindings)
    points = np.asarray([bindings[n]['xy'] for n in names], float).reshape(-1, 2)
    audit.update(label_bindings=bindings, ambiguous_labels=ambiguous,
                 same_name_coordinate_conflicts=conflicts, labelled_vertices=len(names),
                 unlabelled_vertices_evaluated=0, label_matching='exact visible label',
                 off_body_labels=[n for n in names if not any(_distance(np.asarray(bindings[n]['xy']), s.a, s.b) <= tolerance for s in filtered.strokes)])
    return SimpleNamespace(points=points, label_names=names, bindings=bindings,
                           strokes=filtered.strokes, span=max(span, 1e-12),
                           labels=list(drawing.labels), curves=drawing.curves,
                           extraction_audit=audit)


def _drawing(path):
    drawing = backend()[0].parse_drawing(str(path))
    if drawing.unsupported:
        raise ValueError('Unsupported source geometry: ' + str(drawing.unsupported))
    return drawing


def prediction(path):
    return make_graph(_drawing(path))


def label_mapping(gt, pred):
    lookup = {name: i for i, name in enumerate(pred.label_names)}
    return {i: lookup[name] for i, name in enumerate(gt.label_names) if name in lookup}


def reference_items(graph):
    evaluator = backend()[1]
    edges = []
    for a, b in itertools.combinations(range(len(graph.points)), 2):
        p, q = graph.points[a], graph.points[b]
        if np.linalg.norm(p-q) > 1e-10 * graph.span and evaluator.support(p, q, graph.strokes, graph.span) >= CORE_POLICY['drawn_coverage']:
            edges.append([a, b])
    angles, ratios = [], []
    for x, y in itertools.combinations(edges, 2):
        shared = set(x) & set(y)
        if len(shared) != 1:
            continue
        v = next(iter(shared))
        a, b = next(i for i in x if i != v), next(i for i in y if i != v)
        value = evaluator.angle(graph.points[a], graph.points[v], graph.points[b])
        if value >= CORE_POLICY['minimum_angle_degrees']:
            angles.append({'points': [a, v, b], 'labels': [graph.label_names[i] for i in (a, v, b)], 'edges': [x, y], 'target': value})
        lengths = [float(np.linalg.norm(graph.points[e[1]]-graph.points[e[0]])) for e in (x, y)]
        ratios.append({'edges': [x, y], 'labels': [[graph.label_names[i] for i in e] for e in (x, y)], 'target': lengths[0]/lengths[1]})
    return {'edges': edges, 'angles': angles, 'ratios': ratios}


def source_geometry(path):
    graph = prediction(path)
    items = reference_items(graph)
    catalog = {'points': [{'id': f'P{i:03d}', 'label': name, 'xy': graph.points[i].tolist(),
                            'names': [name], 'binding': graph.bindings[name]}
                           for i, name in enumerate(graph.label_names)],
               'edges': items['edges'], 'extraction': graph.extraction_audit}
    return graph, catalog, items


def score(gt, pred, reference, **kwargs):
    if any(getattr(g, 'extraction_audit', {}).get('protocol') != PROTOCOL for g in (gt, pred)):
        raise ValueError('Reference and prediction must use ' + PROTOCOL)
    evaluator = backend()[1]
    mapping = label_mapping(gt, pred)
    edge_ok, edge_reasons = {}, {}
    for edge in reference['edges']:
        a, b = edge
        key = tuple(edge)
        reason = None
        if a not in mapping or b not in mapping:
            reason = 'missing_or_ambiguous_label'
        else:
            p, q = pred.points[mapping[a]], pred.points[mapping[b]]
            if np.linalg.norm(p-q) <= 1e-10 * pred.span:
                reason = 'degenerate_segment'
            elif evaluator.support(p, q, pred.strokes, pred.span) < CORE_POLICY['drawn_coverage']:
                reason = 'segment_not_drawn'
        edge_ok[key] = reason is None
        edge_reasons[key] = reason
    results = {}
    for key in ('angles', 'ratios'):
        checks = []
        for item in reference[key]:
            ok = all(edge_ok[tuple(e)] for e in item['edges'])
            row = dict(item, available=ok, error=None,
                       unavailable_reasons=sorted({edge_reasons[tuple(e)] for e in item['edges'] if not edge_ok[tuple(e)]}))
            if ok:
                if key == 'angles':
                    value = evaluator.angle(*(pred.points[mapping[i]] for i in item['points']))
                    error = abs(value-item['target'])
                else:
                    lengths = [float(np.linalg.norm(pred.points[mapping[a]]-pred.points[mapping[b]])) for a, b in item['edges']]
                    value = lengths[0]/lengths[1]
                    error = abs(value/item['target']-1)
                row.update(predicted=value, error=error)
            checks.append(row)
        results[key] = checks
    def summary(checks):
        errors = [c['error'] for c in checks if c['error'] is not None]
        return {'mean': float(np.mean(errors)) if errors else None, 'n_reference': len(checks),
                'n_available': len(errors), 'coverage': len(errors)/len(checks) if checks else None}
    return {'compiled': True, 'alignment': {'matched': len(mapping), 'method': 'exact_visible_label'},
            'angle': summary(results['angles']), 'length_ratio': summary(results['ratios']),
            'line_coverage': sum(edge_ok.values())/len(edge_ok) if edge_ok else None,
            'angle_checks': results['angles'], 'ratio_checks': results['ratios'],
            'missing_labels': sorted(set(gt.label_names)-set(pred.label_names)),
            'missing_edges': [{'labels': [gt.label_names[i] for i in e], 'reason': edge_reasons[e]} for e, ok in edge_ok.items() if not ok]}


def implementation_hash():
    files = [Path(__file__), Path(backend()[0].__file__), Path(backend()[1].__file__)]
    return hashlib.sha256(b''.join(p.read_bytes() for p in files)).hexdigest()


def apply_reference_corrections(graph, spec, source_hash):
    """Apply reviewed reference-only constructions before freezing all items."""
    if not spec:
        return
    if spec['source_sha256'] != source_hash:
        raise ValueError('Reference correction source hash changed; review correction')
    corrections = []
    for label, construction in spec['labels'].items():
        names = graph.label_names
        get = lambda n: graph.points[names.index(n)]
        old = dict(graph.bindings[label])
        kind=construction['type']
        if kind == 'line_circle_other_intersection':
            a,b = (get(n) for n in construction['line'])
            center = get(construction['center'])
            radius_point = get(construction['radius_point'])
            radius = float(np.linalg.norm(radius_point-center))
            if not np.allclose(a, radius_point, atol=1e-10):
                raise ValueError('The first line point must be the known circle intersection')
            direction = b-a
            t = -2*float((a-center)@direction)/float(direction@direction)
            point = a+t*direction
            if t <= 1e-10 or point[1] < center[1]-1e-10:
                raise ValueError('Correction does not select the upper second intersection')
        elif kind in ('parsed_circle_center','project_to_parsed_circle'):
            circles=[c for c in graph.curves if c.get('full') and c['radius']>0]
            if not circles or construction.get('selection')!='largest':
                raise ValueError('Correction requires an explicitly selected parsed circle')
            circle=max(circles,key=lambda c:c['radius']);center=np.asarray(circle['center'],float);radius=float(circle['radius'])
            if kind=='parsed_circle_center':point=center.copy()
            else:
                direction=np.asarray(old['xy'])-center
                if np.linalg.norm(direction)<1e-10:raise ValueError('No polar direction for radial projection')
                point=center+radius*direction/np.linalg.norm(direction)
        else:
            raise ValueError('Unsupported reviewed reference construction')
        graph.points[names.index(label)] = point
        # A reviewed move of a declared edge endpoint also moves its incident
        # strokes. An interior label such as 6986 E does not alter the body ray.
        transported=0;strokes=[]
        for stroke in graph.strokes:
            ends=[]
            for endpoint in (stroke.a,stroke.b):
                attached=np.linalg.norm(endpoint-np.asarray(old['xy']))<1e-9
                ends.append(point.copy() if attached else endpoint)
                transported+=int(attached)
            strokes.append(SimpleNamespace(a=ends[0],b=ends[1],length=float(np.linalg.norm(ends[1]-ends[0])),dashed=stroke.dashed,source=stroke.source))
        graph.strokes=strokes
        binding = dict(old, xy=point.tolist(), source_xy=old['xy'],
                       coordinate_aliases=[], reviewed_construction=construction)
        graph.bindings[label] = binding
        graph.extraction_audit['label_bindings'][label] = binding
        for conflict in graph.extraction_audit.get('same_name_coordinate_conflicts', []):
            if conflict['label'] == label:
                conflict.update(corrected_reference_xy=point.tolist(), resolution='reviewed construction; original source conflict retained')
        residual=float(np.linalg.norm(point-center)) if kind=='parsed_circle_center' else abs(float(np.linalg.norm(point-center))-radius)
        corrections.append({'label': label, 'source_xy': old['xy'], 'corrected_xy': point.tolist(),
                            'construction': construction, 'reason': spec['reason'],
                            'radius': radius, 'construction_residual':residual,
                            'circle_residual':residual if kind!='parsed_circle_center' else None,
                            'transported_incident_endpoints':transported})
    graph.extraction_audit['reviewed_reference_corrections'] = corrections


def freeze_reference(path, corrections=None):
    path = Path(path)
    graph = prediction(path)
    source_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    spec = (corrections or {}).get(path.stem)
    apply_reference_corrections(graph, spec, source_hash)
    items = reference_items(graph)
    identity = score(graph, graph, items)
    names = graph.label_names
    def named(item):
        result = dict(item)
        result['edges'] = [[names[i] for i in e] for e in item['edges']]
        if 'points' in item:
            result['points'] = [names[i] for i in item['points']]
        return result
    return {'schema': PROTOCOL, 'stem': path.stem, 'source_sha256': source_hash,
            'implementation_sha256': implementation_hash(), 'policy': CORE_POLICY,
            'self_check': {'angle_mae': identity['angle']['mean'], 'ratio_mre': identity['length_ratio']['mean'], 'coverage': identity['line_coverage']},
            'points': {n: graph.bindings[n] for n in names}, 'audit': graph.extraction_audit,
            'edges': [[names[i] for i in e] for e in items['edges']],
            'angles': [named(i) for i in items['angles']], 'ratios': [named(i) for i in items['ratios']]}


def load_reference(path):
    """Load only the frozen JSON. Reference TeX is never opened by evaluation."""
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    if data['schema'] != PROTOCOL or data['policy'] != CORE_POLICY or data['implementation_sha256'] != implementation_hash():
        raise ValueError('Reference cache is stale; run build_geometry_reference.py')
    names = sorted(data['points'])
    ids = {n: i for i, n in enumerate(names)}
    def indexed(item):
        result = dict(item)
        result['edges'] = [[ids[n] for n in e] for e in item['edges']]
        if 'points' in item:
            result['points'] = [ids[n] for n in item['points']]
        return result
    graph = SimpleNamespace(points=np.asarray([data['points'][n]['xy'] for n in names], float).reshape(-1, 2),
                            label_names=names, bindings=data['points'], extraction_audit=data['audit'])
    items = {'edges': [[ids[n] for n in e] for e in data['edges']],
             'angles': [indexed(i) for i in data['angles']], 'ratios': [indexed(i) for i in data['ratios']]}
    return graph, items


