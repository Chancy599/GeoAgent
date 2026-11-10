"""Geometry Agent decisions backed by measurements of the original raster."""
from __future__ import annotations

from itertools import combinations
import math
import re

import numpy as np

from ..cv_tools.common import load_ink
from ..cv_tools.right_angle import locate_foot_square
from .coordinate_contract import MEASURED_POINT_SOURCES, apply_reviewed_bindings
from .schemas import GeometryObject


_LETTER = re.compile(r'[A-Z]')


def _rows(submission, key):
    rows = submission.get(key)
    return rows if isinstance(rows, list) else []


def _lines(state):
    for key, obj in state.objects.items():
        if obj.type in ('segment', 'line') and obj.source == 'cv:detect_lines':
            a, b = (np.asarray(obj.coords.get(k), float) for k in ('a_px', 'b_px'))
            if a.shape == b.shape == (2,) and np.isfinite([a, b]).all() and np.linalg.norm(b-a) >= 15:
                yield key, a, b, obj.style.get('line')


def add_construction_candidates(state):
    """Intersect nearby fitted strokes, keeping the original CV points intact."""
    lines = list(_lines(state))
    if len(lines) < 2:
        return
    mask, _ = load_ink(state.image_path)
    h, w = mask.shape
    margin = min(36., .065 * math.hypot(w, h))
    existing = [np.asarray(o.coords['px']) for o in state.objects.values()
                if o.type == 'point' and o.source in MEASURED_POINT_SOURCES and 'px' in o.coords]
    for (left, a, b, _), (right, c, d, _) in combinations(lines, 2):
        vectors = np.column_stack((b-a, c-d))
        lengths = np.linalg.norm(vectors, axis=0)
        if abs(np.linalg.det(vectors)) < .15 * math.prod(lengths):
            continue
        t, u = np.linalg.solve(vectors, c-a)
        if any(not -margin <= p*length <= length+margin for p, length in zip((t, u), lengths)):
            continue
        point = a + t*(b-a)
        x, y = np.rint(point).astype(int)
        if not (0 <= x < w and 0 <= y < h and mask[max(0,y-3):y+4,max(0,x-3):x+4].any()):
            continue
        if any(np.linalg.norm(p-point) <= 4 for p in existing):
            continue
        key = f'junction_{left}_{right}'
        state.add_object(GeometryObject(id=key, type='point', coords={'px': point.round(2).tolist()},
                                       source='cv:construction_intersection', status='candidate',
                                       attributes={'strokes': [left, right]}))
        existing.append(point)


def _supported_stroke(a, b, style, lines, mask):
    vector = b-a
    length = np.linalg.norm(vector)
    if length < 10:
        return False
    direction = vector/length
    normal = np.array([-direction[1], direction[0]])
    if style == 'solid':
        samples = a + np.linspace(.05,.95,max(16,int(length)))[:, None]*vector
        x, y = np.rint(samples[:, None, :] + np.arange(-2,3)[None,:,None]*normal).astype(int).transpose(2,0,1)
        h, w = mask.shape
        inside = (x >= 0) & (x < w) & (y >= 0) & (y < h)
        hits = np.zeros_like(inside)
        hits[inside] = mask[y[inside],x[inside]] > 0
        return bool(hits.any(axis=1).mean() >= .93)
    for _, left, right, detected in lines:
        if detected != 'dashed' or max(abs((left-a)@normal),abs((right-a)@normal)) > 6:
            continue
        lo, hi = sorted(((left-a)@direction, (right-a)@direction))
        if lo <= .32*length and hi >= .68*length:
            return True
    return False


def _verified_marks(state, rows, points):
    confirmed = [obj for obj in state.objects.values() if obj.type == 'right_angle'
                 and obj.source == 'cv:detect_right_angle_marker' and obj.status == 'confirmed']
    marks = {}
    for triple in rows[:12]:
        if not isinstance(triple,list) or len(triple)!=3 or not all(isinstance(n,str) and n in points for n in triple):
            continue
        a, v, b = triple
        rays = np.asarray([points[a]-points[v], points[b]-points[v]])
        lengths = np.linalg.norm(rays, axis=1)
        if min(lengths) <= 3:
            continue
        rays /= lengths[:,None]
        for mark in confirmed:
            origin = np.asarray(mark.coords['vertex_px'])
            if np.linalg.norm(origin-points[v]) > 8:
                continue
            corners = mark.coords['mark_points_px']
            measured = np.asarray([corners[0],corners[-1]])-origin
            measured /= np.linalg.norm(measured,axis=1)[:,None]
            similarity = rays@measured.T
            if max(min(similarity[0,0],similarity[1,1]),min(similarity[0,1],similarity[1,0])) >= .94:
                marks[v] = {'arms': sorted((a,b)), 'side_px':mark.coords['side_length_px']}
                break
    return marks


def merge_construction_plan(state, submission):
    """Record the proposed source construction and promote supported requirements."""
    apply_reviewed_bindings(state, submission.get('bindings'), source='geometry_agent')
    points = {n: np.asarray(state.objects[key].coords['px'],float) for n,key in state.label_bindings.items()
              if _LETTER.fullmatch(n) and key in state.objects and 'px' in state.objects[key].coords}
    if not points:
        return
    lines = list(_lines(state))
    mask, _ = load_ink(state.image_path)
    prior = state.meta.get('source_construction', {})
    paths = []
    for row in (_rows(submission, 'strokes') + prior.get('strokes', []))[:50]:
        if not isinstance(row,dict):
            continue
        edge,style = row.get('edge'),row.get('style')
        if (not isinstance(edge,list) or len(edge)!=2 or not all(isinstance(n,str) and n in points for n in edge)
                or style not in ('solid','dashed')):
            continue
        if _supported_stroke(*(points[n] for n in edge), style, lines, mask):
            requirement = {'edge':sorted(edge), 'style':style}
            if not any(path['edge'] == requirement['edge'] for path in paths):
                paths.append(requirement)
    proposed_marks = _rows(submission, 'angle_marks') + [
        [mark['arms'][0], v, mark['arms'][1]] for v, mark in prior.get('marks', {}).items()
    ]
    marks = _verified_marks(state, proposed_marks, points)
    feet = []
    for row in (_rows(submission, 'feet') + prior.get('feet', []))[:12]:
        if not isinstance(row,list) or len(row)!=4 or not all(isinstance(n,str) and n in points for n in row):
            continue
        p, foot, a, b = row
        vector = points[b]-points[a]
        length_sq = float(vector@vector)
        if length_sq <= 100:
            continue
        fraction = float((points[p]-points[a])@vector)/length_sq
        projected = points[a] + vector*fraction
        if (foot not in {accepted[1] for accepted in feet}
                and 0 <= fraction <= 1 and np.linalg.norm(projected-points[foot]) <= 6
                and any(req['edge']==sorted((p,foot)) for req in paths)
                and _supported_stroke(points[a],points[b],'solid',lines,mask)):
            feet.append(row)
            if foot not in marks:
                square = locate_foot_square(mask, points[p], projected, points[a], points[b])
                if square is not None:
                    side, size = square
                    marks[foot] = {'arms': sorted((p, (a, b)[side])), 'side_px': size}
    state.meta['source_construction'] = {'summary':str(submission.get('summary') or prior.get('summary',''))[:1500],
                                        'strokes':paths,'marks':marks,'feet':feet}
