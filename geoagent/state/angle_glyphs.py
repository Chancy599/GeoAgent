"""Geometric right-angle annotation recognition for generated TikZ.

Independent of reference data, evaluation parsers and coordinate spelling.
Only short orthogonal paths backed by two longer body directions are removed.
"""
from types import SimpleNamespace
import math
import re
import numpy as np

GLYPH_POLICY = {
    'glyph_max_diagonal_fraction': .20, 'glyph_max_side_ratio': 1.4,
    'glyph_turn_tolerance_degrees': 5, 'body_min_length_fraction': .12,
    'body_min_glyph_side_multiple': 3,
}
NAME = r"[A-Za-z][A-Za-z0-9_']*"
NUMBER = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"

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
    if min(lengths) <= 1e-10 or max(lengths) / min(lengths) > GLYPH_POLICY["glyph_max_side_ratio"]:
        return None
    if np.linalg.norm(np.ptp(points, axis=0)) > GLYPH_POLICY["glyph_max_diagonal_fraction"] * span:
        return None
    axes = [(s.b - s.a) / s.length for s in chain]
    if any(abs(float(a @ b)) > np.sin(np.deg2rad(GLYPH_POLICY["glyph_turn_tolerance_degrees"])) for a, b in zip(axes, axes[1:])):
        return None
    anchors = [points[0] + points[2] - points[1]] if len(chain) == 2 else points
    tolerance = .15 * min(lengths)
    long = [s for s in others if s.length >= max(GLYPH_POLICY["body_min_glyph_side_multiple"] * max(lengths),
                                               GLYPH_POLICY["body_min_length_fraction"] * span)]
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


def _balanced(text, start):
    depth = 0
    for i in range(start, len(text)):
        depth += (text[i] == '(') - (text[i] == ')')
        if depth == 0:
            return text[start+1:i], i+1
    raise ValueError('unclosed path coordinate')


def _point(token, points):
    token = token.strip().strip('$').strip()
    if token in points:
        return np.asarray(points[token], float)
    cart = re.fullmatch(r'\s*('+NUMBER+r')\s*,\s*('+NUMBER+r')\s*', token)
    if cart:
        return np.array(list(map(float, cart.groups())))
    polar = re.fullmatch(r'\s*('+NUMBER+r')\s*:\s*('+NUMBER+r')\s*', token)
    if polar:
        angle, radius = map(float, polar.groups())
        return radius*np.array([math.cos(math.radians(angle)), math.sin(math.radians(angle))])
    offset = re.fullmatch(r'\(('+NAME+r')\)\s*([+-])\s*\(('+NUMBER+r')\s*,\s*('+NUMBER+r')\)', token)
    if offset and offset[1] in points:
        return np.asarray(points[offset[1]])+(1 if offset[2] == '+' else -1)*np.array([float(offset[3]), float(offset[4])])
    return None


def _path(body, points):
    """Bounded numeric view used only to recognize annotations, never to solve."""
    text = body.lstrip()
    if text.startswith('['):
        depth, end = 0, None
        for i, c in enumerate(text):
            depth += (c == '[') - (c == ']')
            if depth == 0:
                end = i+1
                break
        if end is None:
            return []
        if re.search(r'\b(?:shift|rotate|scale|xshift|yshift|xscale|yscale|cm)\s*=', text[:end]):
            return []
        text = text[end:].strip()
    if any(re.search(r'\b'+word+r'\b', text) for word in ('arc','circle','ellipse','controls','node','rectangle','to')):
        return []
    strokes, current, origin, base = [], None, None, None
    i, line = 0, False
    while i < len(text):
        if text[i].isspace():
            i += 1
            continue
        if text.startswith('--', i):
            line, i = True, i+2
            continue
        if text.startswith('cycle', i):
            if current is None or origin is None or not line:
                return []
            strokes.append((current.copy(), origin.copy()))
            current, i, line = origin.copy(), i+5, False
            continue
        relative = ''
        if text.startswith('++', i):
            relative, i = '++', i+2
        elif text[i] == '+':
            relative, i = '+', i+1
        while i < len(text) and text[i].isspace():
            i += 1
        if i >= len(text) or text[i] != '(':
            return []
        try:
            token, i = _balanced(text, i)
        except ValueError:
            return []
        point = _point(token, points)
        if point is None:
            return []
        if relative:
            if base is None:
                return []
            point = base+point
        if line and current is not None:
            strokes.append((current.copy(), point.copy()))
        current, line = point, False
        if origin is None:
            origin = point.copy()
        if relative != '+':
            base = point.copy()
    return [SimpleNamespace(a=a, b=b, length=float(np.linalg.norm(b-a)),
                            dashed=bool(re.search(r'\bdashed\b', body)), source=body)
            for a,b in strokes if np.linalg.norm(b-a) > 1e-10]


def marker_paths(tex):
    """Return whole glyph paths and exclusively annotation-owned coordinates."""
    points = {}
    for name, expr in re.findall(r'\\coordinate\s*\(('+NAME+r')\)\s*at\s*(.*?);', tex, re.S):
        expr = expr.strip()
        if expr.startswith('(') and expr.endswith(')'):
            value = _point(expr[1:-1], points)
            if value is not None:
                points[name] = value
    labelled = set(re.findall(r'\\node\b[^;]*?\bat\s*\(('+NAME+r')\)', tex, re.S))
    labels = [{'position': points[n]} for n in labelled if n in points]
    bodies = re.findall(r'\\draw\b(.*?);', tex, re.S)
    groups = [_path(body, points) for body in bodies]
    strokes = [s for group in groups for s in group]
    extent = [p for s in strokes for p in (s.a, s.b)]
    span = float(np.linalg.norm(np.ptp(extent, axis=0))) if extent else 0.
    excluded, records = set(), []
    for i, chain in enumerate(groups):
        anchor = _marker_anchor(chain, [s for j,g in enumerate(groups) if j != i for s in g], labels, span)
        if anchor is not None:
            excluded.add(i)
            records.append({'paths': [bodies[i]], 'anchor': anchor.tolist(), 'strokes': len(chain)})
    singles = [i for i,g in enumerate(groups) if i not in excluded and len(g) == 1 and g[0].length <= .08*span]
    for k,i in enumerate(singles):
        if i in excluded:
            continue
        for j in singles[k+1:]:
            if j in excluded:
                continue
            found = None
            for left,right in ((groups[i][0],groups[j][0]),(groups[j][0],groups[i][0])):
                for flip_a in (False,True):
                    for flip_b in (False,True):
                        def orient(s, flip):
                            return SimpleNamespace(a=s.b if flip else s.a, b=s.a if flip else s.b,
                                                   length=s.length, dashed=s.dashed)
                        chain = [orient(left,flip_a),orient(right,flip_b)]
                        anchor = _marker_anchor(chain, [s for h,g in enumerate(groups) if h not in (i,j) and h not in excluded for s in g], labels, span)
                        if anchor is not None:
                            found = anchor
            if found is not None:
                excluded.update((i,j))
                records.append({'paths': [bodies[i],bodies[j]], 'anchor': found.tolist(), 'strokes': 2})
                break
    selected = {bodies[i] for i in excluded}
    names = lambda body:set(re.findall(r'\(('+NAME+r')\)', body))
    marker_names = set().union(*(names(b) for b in selected)) if selected else set()
    body_names = set().union(*(names(b) for i,b in enumerate(bodies) if i not in excluded)) if bodies else set()
    helpers = marker_names-body_names-labelled
    return selected, helpers, {'excluded_paths': records, 'excluded_helper_points': sorted(helpers),
                               'excluded_strokes': sum(r['strokes'] for r in records)}


