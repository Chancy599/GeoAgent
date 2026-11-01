"""Conservative parser and coordinate exporter for generated straight-line TikZ.

This is deliberately a supported subset, not a general TeX interpreter.
No reference programs or evaluation data are read here.
"""
from __future__ import annotations

import math
import re
import numpy as np
from .angle_glyphs import marker_paths

NAME = r"[A-Za-z][A-Za-z0-9_']*"

def clean(tex):
    return re.sub(r"(?<!\\)%[^\n]*","",tex)


def extract_geometry(tex, *, annotation_audit=None):
    tex = clean(tex)
    excluded_paths, helper_points, glyph_audit = marker_paths(tex)
    if annotation_audit is not None:
        annotation_audit.update(glyph_audit)
    labels = set(re.findall(r"\\node\b[^;]*?\bat\s*\(("+NAME+r")\)",tex,re.S))
    definitions = re.findall(r"\\coordinate\s*\(("+NAME+r")\)\s*at\s*(.*?);",tex,re.S)
    points = {}
    for name,expr in definitions:
        if name in helper_points:
            continue
        if not (re.fullmatch(r"[A-Z]",name) or name in labels):
            continue  # exclude marker helpers and unlabelled stubs
        cart = re.fullmatch(r"\s*\(\s*([-+\d.eE]+)\s*,\s*([-+\d.eE]+)\s*\)\s*",expr)
        polar = re.fullmatch(r"\s*\(\s*([-+\d.eE]+)\s*:\s*([-+\d.eE]+)\s*\)\s*",expr)
        if cart:
            xy = [float(x) for x in cart.groups()]
        elif polar:
            angle,radius = map(float,polar.groups())
            xy = [radius*math.cos(math.radians(angle)),radius*math.sin(math.radians(angle))]
        else:
            raise ValueError(f"unsupported coordinate {name}: {expr}")
        if not all(math.isfinite(x) for x in xy):
            raise ValueError("nonfinite coordinates")
        points[name] = xy
    segments = {}
    for draw in re.findall(r"\\draw\b(.*?);",tex,re.S):
        if draw in excluded_paths:
            continue
        pairs = re.findall(r"(?=\(("+NAME+r")\)\s*--\s*\(("+NAME+r")\))",draw)
        names = re.findall(r"\(("+NAME+r")\)",draw)
        if re.search(r"--\s*cycle\b",draw) and len(names)>=3:
            pairs.append((names[-1],names[0]))
        for a,b in pairs:
            if a in points and b in points and a!=b:
                a,b = sorted((a,b))
                segments[f"{a}--{b}"] = [a,b]
    if len(points)<2 or not segments:
        raise ValueError("no supported labelled line segments")
    return {"points":points,"segments":segments}


def has_curves(tex):
    return any(re.search(r"\b(?:circle|arc|ellipse)\s*(?:\[|\()",draw)
               for draw in re.findall(r"\\draw\b(.*?);",clean(tex),re.S))


def local_map(point, before, after):
    """Transport tiny annotation strokes in a nearby vertex's local line frame."""
    nearest=min(before["points"],key=lambda n:np.linalg.norm(np.asarray(before["points"][n])-point))
    vertex=np.asarray(before["points"][nearest]);new_vertex=np.asarray(after["points"][nearest])
    span=float(np.linalg.norm(np.ptp(list(before["points"].values()),axis=0)))
    if np.linalg.norm(point-vertex)>0.08*span:
        return point
    frames=[]
    for sid,(a,b) in before["segments"].items():
        u=np.subtract(before["points"][b],before["points"][a])
        length=float(np.linalg.norm(u))
        if length<1e-12:
            continue
        offset=vertex-before["points"][a]
        t=float(offset@u)/(length*length)
        distance=abs(float(u[0]*offset[1]-u[1]*offset[0]))/length
        if -0.01<t<1.01 and distance<0.005*span:
            v=np.subtract(after["points"][b],after["points"][a])
            frames.append((u/length,v/np.linalg.norm(v)))
    best=None
    for i,left in enumerate(frames):
        for right in frames[i+1:]:
            matrix=np.column_stack([left[0],right[0]])
            determinant=abs(float(np.linalg.det(matrix)))
            if best is None or determinant>best[0]:
                best=(determinant,matrix,np.column_stack([left[1],right[1]]))
    if best and best[0]>0.2:
        return new_vertex+best[2]@np.linalg.solve(best[1],point-vertex)
    return point+(new_vertex-vertex)


def rewrite_tex(tex,before,after):
    """Keep original drawing commands; replace named coordinates at full precision.

    Small explicit marker coordinates follow a local vertex frame. This is a
    limited exporter for the generated sources, not a general TikZ AST rewriter.
    """
    def number(x):
        # Shortest round-trip double, expanded without scientific notation
        # because TikZ dimension parsing is not a Python float parser.
        return np.format_float_positional(float(x),unique=True,trim="-")
    def replacement(match):
        name=match[1]
        if name in after["points"]:
            xy=after["points"][name]
        else:
            literal=re.fullmatch(r"\s*\(\s*([-+\d.eE]+)\s*,\s*([-+\d.eE]+)\s*\)\s*",match[2])
            if not literal:
                return match[0]
            xy=local_map(np.array(list(map(float,literal.groups()))),before,after)
        return rf"\coordinate ({name}) at ({number(xy[0])},{number(xy[1])});"
    tex=re.sub(r"\\coordinate\s*\(("+NAME+r")\)\s*at\s*(.*?);",replacement,tex,flags=re.S)
    literal_pattern=r"\(\s*([-+\d.eE]+)\s*,\s*([-+\d.eE]+)\s*\)"
    span=float(np.linalg.norm(np.ptp(list(before["points"].values()),axis=0)))
    def marker(match):
        command=match[0]
        literal=list(re.finditer(literal_pattern,command))
        # Named-coordinate expressions and relative offsets require other rules.
        if "$" in command or "++" in command or not literal or re.search(r"\(("+NAME+r")\)",command):
            return command
        points=np.array([[float(m[1]),float(m[2])] for m in literal])
        if len(points)<2 or np.linalg.norm(np.ptp(points,axis=0))>0.08*span:
            return command
        return re.sub(literal_pattern,lambda m:"("+",".join(number(x) for x in local_map(np.array([float(m[1]),float(m[2])]),before,after))+")",command)
    tex=re.sub(r"\\draw\b[^;]*;",marker,tex,flags=re.S)
    # Offset coordinates around a named vertex, e.g. $(Q)+(-.188,.068)$.
    offset_pattern=r"\$\(("+NAME+r")\)\+\(\s*([-+\d.eE]+)\s*,\s*([-+\d.eE]+)\s*\)\$"
    def offset(match):
        name=match[1]
        if name not in before["points"]:
            return match[0]
        old_vertex=np.asarray(before["points"][name]);new_vertex=np.asarray(after["points"][name])
        moved=local_map(old_vertex+np.array([float(match[2]),float(match[3])]),before,after)-new_vertex
        return f"$({name})+({number(moved[0])},{number(moved[1])})$"
    return re.sub(offset_pattern,offset,tex)
