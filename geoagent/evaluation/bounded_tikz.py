"""Code geometry extraction shared by reference and prediction structural scoring.

This is a deliberately bounded parser, not a TeX interpreter. Unsupported
straight paths make a drawing unscoreable instead of silently disappearing.
Circles, arcs, fills and small angle glyphs are outside the straight-line metric.
"""
from dataclasses import dataclass, field
from pathlib import Path
import math
import re

import numpy as np

# Adapted from geom2code/agent/structural_geometry.py. Kept locally so label
# binding semantics are versioned with the evaluation, without global patches.
from agent import rootpaths  # noqa: F401
import demo
import extract_points as cv


@dataclass
class Stroke:
    a: np.ndarray
    b: np.ndarray
    dashed: bool = False
    source: str = ""

    @property
    def length(self):
        return float(np.linalg.norm(self.b - self.a))


@dataclass
class Drawing:
    points: dict = field(default_factory=dict)
    labelled: dict = field(default_factory=dict)
    strokes: list = field(default_factory=list)
    unsupported: list = field(default_factory=list)
    excluded: list = field(default_factory=list)
    labels: list = field(default_factory=list)
    curves: list = field(default_factory=list)


def _balanced(s, start, opening="(", closing=")"):
    if start >= len(s) or s[start] != opening:
        raise ValueError("expected " + opening)
    depth = 0
    for i in range(start, len(s)):
        if s[i] == opening:
            depth += 1
        elif s[i] == closing:
            depth -= 1
            if depth == 0:
                return s[start + 1:i], i + 1
    raise ValueError("unclosed " + opening)


def _number(s, env):
    # TikZ trigonometry uses degrees, as does the existing bounded GT parser.
    for _ in range(8):
        old = s
        for name, value in env.items():
            s = re.sub(r"\\" + re.escape(name) + r"\b", lambda m: "(" + str(value) + ")", s)
        if old == s:
            break
    for m in list(re.finditer(r"atan2\(([^()]*)\)", s)):
        args = cv._split_top(m[1])
        if len(args) == 2:
            y, x = (cv._eval_expr(v, {}) for v in args)
            if y is not None and x is not None:
                s = s.replace(m[0], str(math.degrees(math.atan2(y, x))))
    while m := re.search(r"veclen\(", s):
        inside, end = _balanced(s, m.end()-1)
        args = cv._split_top(inside)
        if len(args) == 2:
            values = [cv._eval_expr(a, {}) for a in args]
            if all(v is not None for v in values):
                s = s[:m.start()]+str(math.hypot(*values))+s[end:]
                continue
        return None
    # The bounded picture parser uses the default cm coordinate basis. Picture
    # transforms with custom x/y bases are already rejected by _matrix.
    s = re.sub(r'(?<=\d)\s*cm\b', '', s)
    s = re.sub(r'(?<=[\d)])\s*pt\b', '*(2.54/72.27)', s)
    return cv._eval_expr(s, {})


def _point(token, points, env):
    """Local point expression: named, Cartesian, polar, calc and projection."""
    token = token.strip()
    if token.startswith("(") and _balanced(token, 0)[1] == len(token):
        token = token[1:-1].strip()
    if token.startswith("$") and token.endswith("$"):
        token = token[1:-1].strip()
    cartesian = cv._split_top(token, ',')
    if len(cartesian) == 2:
        xy = [_number(value, env) for value in cartesian]
        if all(value is not None for value in xy):
            return np.asarray(xy, float)
    factors = cv._split_top(token, '*')
    if len(factors) == 2:
        for scalar, vector in (factors, factors[::-1]):
            n = _number(scalar, env)
            if n is not None:
                p = _point(vector, points, env)
                if p is not None:
                    return n*p
    if token in points:
        return np.array(points[token], float)
    if token.startswith('intersection of '):
        halves = token[len('intersection of '):].split(' and ')
        if len(halves) == 2:
            endpoints = [x.strip().strip('{}') for half in halves for x in cv._split_dashes(half)]
            if len(endpoints) == 4:
                values = [_point(x, points, env) for x in endpoints]
                if all(p is not None for p in values):
                    solutions = cv._isect_lines(*values)
                    return np.asarray(solutions[0]) if solutions else None
    if token.startswith("barycentric cs:"):
        weighted = []
        for term in cv._split_top(token.partition(":")[2]):
            name, separator, value = term.partition("=")
            weight = _number(value, env) if separator else None
            if name.strip() not in points or weight is None:
                return None
            weighted.append((points[name.strip()], weight))
        total = sum(w for _, w in weighted)
        if abs(total) > 1e-12:
            return sum(np.asarray(p) * w for p, w in weighted) / total
        return None
    for sep in ("+", "-"):
        terms = cv._split_top(token, sep)
        if len(terms) > 1 and all(t.strip() for t in terms):
            values = [_point(t, points, env) for t in terms]
            if all(v is not None for v in values):
                return values[0] + sum(values[1:]) if sep == "+" else values[0] - sum(values[1:])
    m = re.fullmatch(r"([\w\x27]+)\s*(\|-|-\|)\s*([\w\x27]+)", token)
    if m and m[1] in points and m[3] in points:
        a, b = points[m[1]], points[m[3]]
        return np.array([a[0], b[1]] if m[2] == "|-" else [b[0], a[1]])
    m = re.fullmatch(r"intersection of\s+([\w\x27]+)--([\w\x27]+)\s+and\s+([\w\x27]+)--([\w\x27]+)", token)
    if m and all(k in points for k in m.groups()):
        sol = cv._isect_lines(*(points[k] for k in m.groups()))
        return np.array(sol[0]) if sol else None
    m = re.fullmatch(r"\(([\w\x27]+)\)\s*!\s*([^!]+)!\s*([^:]+):\s*\(([\w\x27]+)\)", token)
    if m and m[1] in points and m[4] in points:
        fraction, angle = _number(m[2], env), _number(m[3], env)
        if fraction is not None and angle is not None:
            t = math.radians(angle)
            rot = np.array([[math.cos(t), -math.sin(t)], [math.sin(t), math.cos(t)]])
            a, b = np.asarray(points[m[1]]), np.asarray(points[m[4]])
            return a + fraction * (rot @ (b - a))
    m = re.fullmatch(r"\(([\w\x27]+)\)!\(([\w\x27]+)\)!\(([\w\x27]+)\)", token)
    if m and all(k in points for k in m.groups()):
        a, p, b = (np.asarray(points[k], float) for k in m.groups())
        v = b - a
        den = float(v @ v)
        return a + v * float((p - a) @ v) / den if den else None
    m = re.fullmatch(r"\(([\w\x27]+)\)!\s*([^!]+)!\(([\w\x27]+)\)", token)
    if m and m[1] in points and m[3] in points:
        t = _number(m[2], env)
        if t is not None:
            a, b = np.asarray(points[m[1]]), np.asarray(points[m[3]])
            return a + t * (b - a)
    parts = cv._split_top(token, ",")
    if len(parts) == 2:
        xy = [_number(p, env) for p in parts]
        if all(v is not None for v in xy):
            return np.array(xy)
    parts = cv._split_top(token, ":")
    if len(parts) == 2:
        angle, radius = (_number(p, env) for p in parts)
        if angle is not None and radius is not None:
            return radius * np.array([math.cos(math.radians(angle)),
                                      math.sin(math.radians(angle))])
    return None


def _style(options, inherited, aliases):
    dashed = inherited
    for option in cv._split_top(options):
        option = option.strip()
        if option in aliases:
            dashed = _style(aliases[option], dashed, {})
        elif option in ("dashed", "densely dashed", "loosely dashed"):
            dashed = True
        elif option == "solid":
            dashed = False
        elif "dotted" in option or option.startswith("dash dot"):
            raise ValueError("dotted/dash-dot style is outside solid/dashed evaluation")
        elif option.startswith("dash pattern="):
            dashed = option != "dash pattern="
    return dashed


def _matrix(options, points, env):
    out = np.eye(3)
    for opt in cv._split_top(options):
        key, _, value = opt.strip().partition("=")
        key, value = key.strip(), value.strip()
        m = np.eye(3)
        if key in ("scale", "xscale", "yscale"):
            n = _number(value, env)
            if n is None:
                raise ValueError("unresolved transform: " + opt)
            if key != "yscale":
                m[0, 0] = n
            if key != "xscale":
                m[1, 1] = n
        elif key in ("shift", "xshift", "yshift"):
            if key == "shift":
                v = _point(value.strip("{}"), points, env)
            else:
                # TikZ default coordinate units are cm.
                unit = re.fullmatch(r"([-+\d.]+)(cm|mm|pt)?", value)
                n = float(unit[1]) * {None: 1, "cm": 1, "mm": .1,
                                      "pt": 2.54 / 72.27}[unit[2]] if unit else None
                v = None if n is None else np.array([n, 0] if key == "xshift" else [0, n])
            if v is None:
                raise ValueError("unresolved shift: " + opt)
            m[:2, 2] = v
        elif key in ("rotate", "rotate around"):
            pivot = np.zeros(2)
            if key == "rotate around":
                angle, pivot_s = value.strip("{}").split(":", 1)
                pivot = _point(pivot_s, points, env)
            else:
                angle = value
            n = _number(angle, env)
            if n is None or pivot is None:
                raise ValueError("unresolved rotation: " + opt)
            t = math.radians(n)
            m[:2, :2] = [[math.cos(t), -math.sin(t)], [math.sin(t), math.cos(t)]]
            m[:2, 2] = pivot - m[:2, :2] @ pivot
        elif key in ("x", "y"):
            unit = re.fullmatch(r"([-+\d.]+)\s*(cm|mm|pt)?", value)
            if unit:
                n = float(unit[1]) * {None: 1, "cm": 1, "mm": .1, "pt": 2.54/72.27}[unit[2]]
                vector = np.array([n, 0] if key == "x" else [0, n])
            else:
                vector = _point(value.strip('{}'), points, env)
            if vector is None:
                raise ValueError("unresolved coordinate basis: " + opt)
            m[:2, 0 if key == "x" else 1] = vector
        elif key in ("cm", "transform canvas", "slant", "xslant", "yslant"):
            raise ValueError("unsupported transform: " + opt)
        out = out @ m
    return out


def _apply(matrix, point):
    return (matrix @ np.r_[point, 1])[:2]


def _angle_glyph(strokes, names, span):
    if not 2 <= len(strokes) <= 4 or len(set(names)) > 1 or span <= 0:
        return False
    coords = np.array([p for s in strokes for p in (s.a, s.b)])
    if np.linalg.norm(np.ptp(coords, axis=0)) > .10 * span:
        return False
    for a, b in zip(strokes, strokes[1:]):
        if np.linalg.norm(a.b - b.a) > 1e-8:
            return False
        u, v = a.b - a.a, b.b - b.a
        if abs(float(u @ v)) > math.sin(math.radians(3)) * np.linalg.norm(u) * np.linalg.norm(v):
            return False
    return True


def _remove_marker_fragments(strokes, markers, points, span):
    """Recognize an elbow even when its two legs use separate draw commands.

    Its inferred fourth corner must be an existing named point. Nearby duplicate
    fragments of an already identified marker are excluded as well.
    """
    tolerance = max(.015 * span, 1e-9)
    anchors = list(points.values())
    short = []
    for s in strokes:
        named_ends = sum(any(np.linalg.norm(p - a) < 1e-7 * max(span, 1)
                             for a in anchors) for p in (s.a, s.b))
        if s.length <= .08 * span and named_ends < 2 and not s.dashed:
            short.append(s)
    for i, a in enumerate(short):
        for b in short[i + 1:]:
            u, v = (a.b - a.a) / a.length, (b.b - b.a) / b.length
            if abs(float(u @ v)) > math.sin(math.radians(5)):
                continue
            ends = [(float(np.linalg.norm(p - q)), p, q, ap, bp)
                    for p, ap in ((a.a, a.b), (a.b, a.a))
                    for q, bp in ((b.a, b.b), (b.b, b.a))]
            distance, p, q, ap, bp = min(ends, key=lambda x: x[0])
            corner = ap + bp - (p + q) / 2
            if distance <= tolerance and any(np.linalg.norm(corner - anchor) <= .03 * span for anchor in anchors):
                markers.extend([a, b])
    kept, removed = [], []
    for s in strokes:
        matched = False
        if any(s is candidate for candidate in short):
            for marker in markers:
                u = (marker.b - marker.a) / marker.length
                v = (s.b - s.a) / s.length
                if abs(float(u @ v)) < math.cos(math.radians(5)):
                    continue
                delta = [s.a - marker.a, s.b - marker.a]
                if max(abs(float(u[0] * p[1] - u[1] * p[0])) for p in delta) > tolerance:
                    continue
                lo, hi = sorted(float(p @ u) for p in delta)
                overlap = max(0., min(hi, marker.length) - max(lo, 0.))
                if overlap / s.length >= .8:
                    matched = True
                    break
        (removed if matched else kept).append(s)
    return kept, removed


def _resolve_named_paths(text, points, env):
    """Resolve intersections when name path is not the first draw option."""
    paths = {}
    for opts, body in re.findall(r"\\(?:draw|path|filldraw)\b\s*\[([^\]]*)\]\s*([^;]*);", text, re.S):
        name = re.search(r"(?:^|,)\s*name path\s*=\s*([\w\x27]+)", opts)
        if not name:
            continue
        circle = re.fullmatch(r"\s*(\([^;]*?\))\s*circle\s*\(([^)]*)\)\s*", body, re.S)
        if circle:
            center, radius = _point(circle[1], points, env), _number(circle[2], env)
            if center is not None and radius is not None:
                paths[name[1]] = ("circle", center, radius)
            continue
        ends = cv._split_dashes(body)
        if len(ends) == 2:
            a, b = (_point(t, points, env) for t in ends)
            if a is not None and b is not None:
                paths[name[1]] = ("line", a, b)
    pattern = r"name intersections\s*=\s*\{\s*of\s*=\s*([\w\x27]+)\s+and\s+([\w\x27]+)\s*,\s*by\s*=\s*(?:\{([^}]*)\}|([\w\x27]+))"
    for a, b, group, single in re.findall(pattern, text):
        if a not in paths or b not in paths:
            continue
        ga, gb = paths[a], paths[b]
        if ga[0] == gb[0] == "line":
            solutions = cv._isect_lines(ga[1], ga[2], gb[1], gb[2])
        elif ga[0] == gb[0] == "circle":
            solutions = cv._isect_circles(ga[1], ga[2], gb[1], gb[2])
        elif ga[0] == "line":
            solutions = cv._isect_line_circle(ga[1], ga[2], gb[1], gb[2])
        else:
            solutions = cv._isect_line_circle(gb[1], gb[2], ga[1], ga[2])
        if ga[0] == "circle":
            solutions.sort(key=lambda p: math.atan2(p[1] - ga[1][1], p[0] - ga[1][0]) % (2 * math.pi))
        else:
            solutions.sort(key=lambda p: float((np.asarray(p) - ga[1]) @ (ga[2] - ga[1])))
        for name, value in zip((n.strip() for n in (group or single).split(",")), solutions):
            points[name] = np.asarray(value, float)


def canonical_label(text):
    """Visible vertex text, with markup normalized but case/subscript/prime retained."""
    s = text.strip().replace('$', '').replace(r'\prime', "'").replace('′', "'")
    s = re.sub(r'\\fontsize\s*\{[^{}]*\}\s*\{[^{}]*\}', '', s)
    s = re.sub(r'\\(?:selectfont|tiny|scriptsize|footnotesize|small|normalsize|large|Large|LARGE|huge|Huge|bfseries|itshape)\b', '', s)
    for _ in range(8):
        normalized = re.sub(r'\\(?:mathrm|mathbf|mathit|mathsf|mathtt|mathnormal|mathbb|mathcal|boldsymbol|bm|text|textbf|textit|textrm|textsf|texttt|textnormal|textsc|emph|ensuremath|mbox)\s*\{([^{}]*)\}', r'\1', s)
        if normalized == s:
            break
        s = normalized
    for digit, plain in demo._SUB_DIGITS.items():
        s = s.replace(digit, '_'+plain)
    s = re.sub(r'[{}\s]', '', s)
    return s if re.fullmatch(r"[A-Za-z](?:_?\d+)?'*", s) else ''


def add_label(result, text, position, expression=None):
    label = canonical_label(text)
    if label and position is not None:
        result.labels.append({'text': label, 'position': np.asarray(position, float), 'raw': text,
                              'anchor_expression': expression})
    elif text.strip():
        result.excluded.append({'reason': 'non-vertex text', 'text': text})


def capture_node(result, body, points, env, matrix):
    match = re.search(r'\bat\s*\(', body)
    if not match:
        result.unsupported.append({'reason': 'node without explicit position', 'path': body})
        return
    token, end = _balanced(body, match.end()-1)
    local = {k: _apply(np.linalg.inv(matrix), v) for k, v in points.items()}
    anchor = _point(token, local, env)
    rest = body[end:].strip()
    if rest.startswith('['):
        _, end = _balanced(rest, 0, '[', ']')
        rest = rest[end:].strip()
    if rest.startswith('{') and anchor is not None:
        text, _ = _balanced(rest, 0, '{', '}')
        add_label(result, text, _apply(matrix, anchor), token)
    else:
        result.unsupported.append({'reason': 'unresolved node', 'path': body, 'names': [token]})


def capture_inline_node(result, body, points, env, matrix):
    match = re.search(r'\bnode\s*(?:\[[^\]]*\])?\s*\{', body)
    if not match:
        return
    first = body.find('(')
    if first < 0:
        return
    token, _ = _balanced(body, first)
    local = {k: _apply(np.linalg.inv(matrix), v) for k, v in points.items()}
    p = _point(token, local, env)
    text, _ = _balanced(body, match.end()-1, '{', '}')
    if p is None:
        result.unsupported.append({'reason': 'unresolved inline label', 'path': body})
    else:
        add_label(result, text, _apply(matrix, p), token)


def capture_curve(result, body, points, env, matrix):
    """Retain curve bounds/anchors for alignment; curves never enter line errors."""
    first = body.find('(')
    if first < 0:
        return
    token, end = _balanced(body, first)
    local = {k: _apply(np.linalg.inv(matrix), v) for k, v in points.items()}
    center = _point(token, local, env)
    circle = re.search(r'\bcircle\s*\(([^)]*)\)', body[end:])
    if center is not None and circle:
        radius = _number(circle[1], env)
        if radius is not None:
            result.curves.append({'center': _apply(matrix, center),
                                  'radius': radius*float(np.linalg.norm(matrix[:2, 0])),
                                  'full': True})


def prepare_source(text):
    """Expand bounded foreach/let syntax generically, without modifying input TeX."""
    pattern = re.compile(r'\\foreach\s+\\(\w+)\s*(?:\[count\s*=\s*\\(\w+)\])?\s+in\s*\{([^{}]*)\}\s*\{')
    for _ in range(10):
        match = pattern.search(text)
        if not match:
            break
        body, end = _balanced(text, match.end()-1, '{', '}')
        tokens = [x.strip() for x in match[3].split(',')]
        if '...' in tokens:
            start, step, stop = float(tokens[0]), float(tokens[1])-float(tokens[0]), float(tokens[-1])
            tokens = [format(start+k*step, '.12g') for k in range(round((stop-start)/step)+1)]
        expanded = []
        for i, token in enumerate(tokens, 1):
            part = re.sub(r'\\'+match[1]+r'\b', lambda _: token, body)
            if match[2]:
                part = re.sub(r'\\'+match[2]+r'\b', lambda _: str(i), part)
            expanded.append(part)
        text = text[:match.start()]+'\n'.join(expanded)+text[end:]
    env = dict(re.findall(r'\\def\\(\w+)\s*\{([^{}]*)\}', text))
    env.update(re.findall(r'\\pgfmathsetmacro\s*\{\\(\w+)\}\s*\{([^{}]*)\}', text))
    points = {}
    for _ in range(10):
        for name, expr in re.findall(r"\\coordinate\s*\(([\w']+)\)\s*at\s*(\([^;]*\))\s*;", text):
            p = _point(expr, points, env)
            if p is not None:
                points[name] = p
        _resolve_named_paths(text, points, env)
    for match in list(re.finditer(r'\\path\s+let\b(.*?)\bin\b(.*?);', text, re.S))[::-1]:
        local_env = dict(env)
        for binding in cv._split_top(match[1]):
            m = re.fullmatch(r'\s*\\([pn])(\d+)\s*=\s*(.*?)\s*', binding, re.S)
            if not m:
                raise ValueError('Unsupported let binding: '+binding)
            if m[1] == 'p':
                p = _point(m[3], points, local_env)
                if p is None:
                    raise ValueError('Unresolved let vector')
                local_env['x'+m[2]], local_env['y'+m[2]] = map(str, p)
            else:
                n = _number(m[3], local_env)
                if n is None:
                    raise ValueError('Unresolved let number')
                local_env['n'+m[2]] = str(n)
        tail = match[2].strip()
        commands = []
        if tail.startswith(r'\pgfextra'):
            macro = re.search(r'\\pgfmathsetmacro\s*\{\\(\w+)\}\s*\{(.*?)\}', tail)
            if not macro:
                raise ValueError('Unsupported pgfextra computation')
            n = _number(macro[2], local_env)
            if n is None:
                raise ValueError('Unresolved pgfextra computation')
            local_env[macro[1]] = str(n*72.27/2.54)
            commands.append('\\def\\'+macro[1]+'{'+local_env[macro[1]]+'}')
            for name, alias in re.findall(r'\\xdef\\(\w+)\s*\{\\(\w+)\}', tail):
                commands.append('\\def\\'+name+'{'+local_env[alias]+'}')
            text = text[:match.start()]+'\n'.join(commands)+text[match.end():]
            continue
        definitions = re.findall(r"coordinate\s*\(([\w']+)\)\s*at\s*(.*?)(?=\s+coordinate\b|$)", tail, re.S)
        if definitions:
            for name, expr in definitions:
                p = _point(expr.strip(), points, local_env)
                if p is None:
                    raise ValueError('Unresolved let coordinate '+name)
                points[name] = p
                commands.append(f'\\coordinate ({name}) at ({p[0]:.12g},{p[1]:.12g});')
        else:
            m = re.fullmatch(r"(.*?)\s+coordinate\s*\(([\w']+)\)", tail, re.S)
            p = _point(m[1], points, local_env) if m else None
            if p is None:
                raise ValueError('Unsupported let path')
            commands.append(f'\\coordinate ({m[2]}) at ({p[0]:.12g},{p[1]:.12g});')
        text = text[:match.start()]+'\n'.join(commands)+text[match.end():]
    return text


def parse_drawing(tex_path):
    text = Path(tex_path).read_text(encoding="utf-8", errors="replace")
    text = re.sub(r"(?<!\\)%[^\n]*", "", text)
    text = prepare_source(text)
    result = Drawing()
    env = dict(re.findall(r"\\def\\([\w\x27]+)\s*\{([^{}]*)\}", text))
    env.update(re.findall(r"\\pgfmathsetmacro\s*\{\\([\w\x27]+)\}\s*\{([^{}]*)\}", text))
    aliases = {k.strip(): v for k, v in re.findall(r"([\w ]+)/\.style\s*=\s*\{([^{}]*)\}", text)}
    # Reuse the existing intersection solver, then resolve further point forms
    # below. Parsing is read-only and never changes the reconstruction detector.
    try:
        initial = cv.parse_gt(tex_path, labelled_only=False, source_text=text)
    except ValueError:
        # The legacy seed parser cannot split nested polar calc expressions.
        # Resolve them below; unresolved endpoints/labels still fail explicitly.
        initial = {}
    points = {k: np.asarray(v, float) for k, v in initial.items()}
    definitions = re.findall(r"\\coordinate\s*\(([\w\x27]+)\)\s*at\s*(\([^;]*\))\s*;", text)
    for _ in range(8):
        for name, expression in definitions:
            p = _point(expression, points, env)
            if p is not None:
                points[name] = p
        _resolve_named_paths(text, points, env)
    picture = re.search(r"\\begin\{tikzpicture\}\s*", text)
    if not picture:
        result.unsupported.append("missing tikzpicture")
        return result
    start = picture.end()
    options = ""
    if start < len(text) and text[start] == "[":
        options, start = _balanced(text, start, "[", "]")
    # Named style declarations must not themselves switch on a dashed default.
    options = re.sub(r"[\w ]+/\.style\s*=\s*\{[^{}]*\}", "", options)
    try:
        matrix = _matrix(options, points, env)
        default_style = _style(options, False, aliases)
    except ValueError as e:
        result.unsupported.append(str(e))
        return result
    # The seed coordinates are local to the picture; account for its transform.
    points = {k: _apply(matrix, v) for k, v in points.items()}
    frames = [(matrix, default_style)]
    groups = []
    inline_labels, radius_tokens = set(), set()
    command_re = re.compile(r"\\(begin\{scope\}|end\{scope\}|coordinate\b|node\b|draw\b|filldraw\b|fill\b|path\b)")
    pos = start
    while match := command_re.search(text, pos):
        kind = match[1]
        pos = match.end()
        while pos < len(text) and text[pos].isspace():
            pos += 1
        if kind == "end{scope}":
            if len(frames) > 1:
                frames.pop()
            continue
        opts = ""
        if pos < len(text) and text[pos] == "[":
            opts, pos = _balanced(text, pos, "[", "]")
        matrix, inherited_style = frames[-1]
        inv = np.linalg.inv(matrix)
        local = {k: _apply(inv, v) for k, v in points.items()}
        if kind == "begin{scope}":
            try:
                frames.append((matrix @ _matrix(opts, local, env),
                               _style(opts, inherited_style, aliases)))
            except ValueError as e:
                result.unsupported.append(str(e))
                frames.append(frames[-1])
            continue
        end = text.find(";", pos)
        if end < 0:
            result.unsupported.append("unterminated " + kind)
            break
        body, pos = text[pos:end].strip(), end + 1
        marker_label = re.fullmatch(r'(\([^()]*\))\s*circle\s*\(([^)]*)\)\s*node\s*'
                                    r'(?:\[[^\]]*\])?\s*\{\s*\$?\s*([A-Za-z]\w*)\s*\$?\s*\}', body)
        if kind == "node":
            capture_node(result, body, points, env, matrix)
            continue
        if marker_label and kind in ('fill', 'filldraw', 'draw'):
            anchor = _point(marker_label[1], local, env)
            if anchor is not None:
                name = marker_label[3]
                inline_labels.add(name)
                radius_tokens.add(marker_label[2])
        if kind == 'fill':
            capture_inline_node(result, body, points, env, matrix)
            capture_curve(result, body, points, env, matrix)
            continue  # Filled regions are outside the straight-stroke metric.
        if kind == "coordinate":
            definition = re.fullmatch(r"\(([\w\x27]+)\)\s*at\s*(.*)", body, re.S)
            if definition:
                p = _point(definition[2], local, env)
                if p is not None:
                    points[definition[1]] = _apply(matrix, p)
            continue
        closed_arc = re.fullmatch(r'(\([^()]*\))\s+arc\s*\(([^()]*)\)\s*--\s*cycle', body)
        if closed_arc and (kind != 'path' or re.search(r'(?:^|,)\s*draw(?:\s*[,=]|\s*$)', opts)):
            arc = cv._split_top(closed_arc[2], ':')
            origin = _point(closed_arc[1], local, env)
            values = [_number(v, env) for v in arc]
            if origin is not None and len(values) == 3 and all(v is not None for v in values):
                start_angle, end_angle, radius = values
                unit = lambda angle: np.array([math.cos(math.radians(angle)), math.sin(math.radians(angle))])
                endpoint = origin + radius * (unit(end_angle) - unit(start_angle))
                result.excluded.append({'reason': 'arc curve; retain straight closing chord', 'path': body})
                groups.append(([Stroke(_apply(matrix, endpoint), _apply(matrix, origin),
                                       _style(opts, inherited_style, aliases), body)], [], body))
                continue
        visible = kind != "path" or bool(re.search(r"(?:^|,)\s*draw(?:\s*[,=]|\s*$)", opts))
        is_line = any(t in body for t in ("--", "- -", "rectangle", "|-", "-|", " to", ".."))
        if not is_line and "coordinate" not in body:
            capture_inline_node(result, body, points, env, matrix)
            capture_curve(result, body, points, env, matrix)
            result.excluded.append({"reason": "curve or non-line path", "path": body})
            continue
        # Physical-distance calc expressions used for angle glyphs in the GT;
        # the two malformed '- -' source paths are excluded explicitly too.
        if re.search(r"!\s*[\d.]+\s*(?:pt|cm|mm)\s*!", body) and body.count("!") >= 4:
            result.excluded.append({"reason": "physical-distance angle glyph", "path": body})
            continue
        strokes, named, current, origin, relative_base = [], [], None, None, None
        pending = None
        try:
            style = _style(opts, inherited_style, aliases)
            if re.search(r"(?:scale|rotate|shift|cm)\s*=", opts):
                raise ValueError("path-local transforms are not supported")
            i = 0
            while i < len(body):
                if body[i].isspace():
                    i += 1
                    continue
                if body.startswith("--", i):
                    pending, i = "line", i + 2
                    continue
                if body.startswith("rectangle", i):
                    pending, i = "rectangle", i + 9
                    continue
                if body.startswith("cycle", i):
                    if current is not None and origin is not None:
                        strokes.append(Stroke(current.copy(), origin.copy(), style, body))
                        current = origin.copy()
                    pending, i = None, i + 5
                    continue
                if not is_line and re.match(r"(?:circle|arc)\b", body[i:]):
                    result.excluded.append({"reason": "curve after coordinate alias", "path": body})
                    break
                # Node text and coordinate aliases are not new path endpoints.
                word = re.match(r"(node|coordinate)\b", body[i:])
                if word:
                    j = i + word.end()
                    while j < len(body) and body[j].isspace():
                        j += 1
                    node_options = ''
                    if j < len(body) and body[j] == "[":
                        node_options, j = _balanced(body, j, "[", "]")
                    while j < len(body) and body[j].isspace():
                        j += 1
                    if word[1] == "node":
                        label_text, i = _balanced(body, j, "{", "}")
                        if canonical_label(label_text) and re.search(r'(?:^|,)\s*(?:pos\s*=|midway|near start|near end|at start|at end)', node_options):
                            raise ValueError('positioned path label requires explicit at binding')
                        add_label(result, label_text, current)
                    else:
                        name, i = _balanced(body, j)
                        if current is not None:
                            points[name] = current.copy()
                    continue
                relative = ""
                if body.startswith("++", i):
                    relative, i = "++", i + 2
                elif body[i] == "+":
                    relative, i = "+", i + 1
                while i < len(body) and body[i].isspace():
                    i += 1
                if i >= len(body) or body[i] != "(":
                    raise ValueError("unsupported path syntax near " + body[i:i + 45])
                token, i = _balanced(body, i)
                if re.fullmatch(r"\w+", token.strip()):
                    named.append(token.strip())
                inv = np.linalg.inv(matrix)
                local = {k: _apply(inv, v) for k, v in points.items()}
                p = _point("(" + token + ")", local, env)
                if p is None:
                    raise ValueError("unresolved endpoint: " + token)
                if relative:
                    if relative_base is None:
                        raise ValueError("relative endpoint without a base")
                    target = relative_base + matrix[:2, :2] @ p
                else:
                    target = _apply(matrix, p)
                if pending and current is not None:
                    if pending == "rectangle":
                        corners = [current, np.array([target[0], current[1]]), target,
                                   np.array([current[0], target[1]]), current]
                        strokes.extend(Stroke(a.copy(), b.copy(), style, body)
                                       for a, b in zip(corners, corners[1:]))
                    else:
                        strokes.append(Stroke(current.copy(), target.copy(), style, body))
                current, pending = target, None
                if origin is None:
                    origin = target.copy()
                if relative != "+":
                    relative_base = target.copy()
            if pending:
                raise ValueError("unfinished line path")
            if visible:
                groups.append((strokes, named, body))
                if 'circle' in body:
                    capture_curve(result, body, points, env, matrix)
        except (ValueError, np.linalg.LinAlgError) as e:
            result.unsupported.append({"reason": str(e), "path": body})
    # Use actual stroke extent, not off-path text positions, for marker filtering.
    xy = [p for ss, _, _ in groups for s in ss for p in (s.a, s.b)]
    span = float(np.linalg.norm(np.ptp(np.array(xy), axis=0))) if xy else 0
    markers = []
    for strokes, named, body in groups:
        strokes = [s for s in strokes if s.length > 1e-10]
        if _angle_glyph(strokes, named, span):
            result.excluded.append({"reason": "small orthogonal angle glyph", "path": body})
            markers.extend(strokes)
        else:
            result.strokes.extend(strokes)
    result.strokes, fragments = _remove_marker_fragments(result.strokes, markers, points, span)
    result.excluded.extend({"reason": "fragment of small angle glyph", "path": s.source} for s in fragments)
    result.points = {k: np.asarray(v, float) for k, v in points.items()}
    result.labelled = {entry['text']: entry['position'] for entry in result.labels}
    return result
