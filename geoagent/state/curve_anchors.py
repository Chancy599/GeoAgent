"""Identify immutable curve definitions and their geometric dependencies.

Only numeric circles and circular arcs are supported. Unknown expressions
raise ValueError so the caller can retain the whole original program.
"""
from __future__ import annotations

import math
import re
import numpy as np

from .tikz_geometry import NAME, clean

NUMBER = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"
COORD = r"\((?:" + NAME + r"|\s*" + NUMBER + r"\s*,\s*" + NUMBER + r"\s*)\)"


def curve_anchors(tex, geometry, *, tolerance_rel=0.005):
    text=clean(tex)
    definitions=dict(re.findall(r"\\coordinate\s*\(("+NAME+r")\)\s*at\s*(.*?);",text,re.S))
    dependencies=set();circles=[];commands=[]
    def point(expr):
        name=re.fullmatch(r"\(("+NAME+r")\)",expr.strip())
        if name:
            name=name[1];dependencies.add(name)
            if name not in definitions:raise ValueError(f"unknown curve dependency {name}")
            expr=definitions[name].strip()
        cart=re.fullmatch(r"\(\s*("+NUMBER+r")\s*,\s*("+NUMBER+r")\s*\)",expr)
        if cart:return np.asarray(list(map(float,cart.groups())))
        polar=re.fullmatch(r"\(\s*("+NUMBER+r")\s*:\s*("+NUMBER+r")\s*\)",expr)
        if polar:
            a,r=map(float,polar.groups());return r*np.array([math.cos(math.radians(a)),math.sin(math.radians(a))])
        raise ValueError(f"unsupported curve point {expr}")
    for command in re.findall(r"\\(?:draw|path|filldraw)\b[^;]*;",text,re.S):
        if not re.search(r"\b(?:circle|arc|ellipse|controls)\b",command):continue
        if re.search(r"\b(?:ellipse|controls)\b",command):raise ValueError("unsupported noncircular curve")
        commands.append(command)
        dependencies.update(re.findall(r"\(("+NAME+r")\)",command))
        shift=np.zeros(2)
        shift_match=re.search(r"shift\s*=\s*\{\s*("+COORD+r")\s*\}",command)
        if shift_match:shift=point(shift_match[1])
        if re.search(r"(?:rotate|scale|xscale|yscale|xshift|yshift)\s*=",command):
            raise ValueError("unsupported local curve transform")
        circle=re.search(r"("+COORD+r")\s*circle\s*(?:\[\s*radius\s*=\s*("+NUMBER+r")(?:cm)?\s*\]|\(\s*("+NUMBER+r")(?:cm)?\s*\))",command)
        if circle:
            center=point(circle[1])+shift;radius=float(circle[2] or circle[3])
        else:
            arc=re.search(r"("+COORD+r")\s*arc\s*(\[[^\]]+\]|\([^\)]+\))",command)
            if not arc:raise ValueError("unsupported curve syntax")
            start=point(arc[1])+shift
            options=arc[2]
            if options.startswith("["):
                values=dict(re.findall(r"(start angle|end angle|delta angle|radius)\s*=\s*("+NUMBER+r")(?:cm)?",options))
                if "start angle" not in values or "radius" not in values:
                    raise ValueError("unsupported arc parameters")
                angle=float(values["start angle"]);radius=float(values["radius"])
            else:
                values=re.fullmatch(r"\(\s*("+NUMBER+r")\s*:\s*("+NUMBER+r")\s*:\s*("+NUMBER+r")\s*\)",options)
                if not values:raise ValueError("unsupported arc parameters")
                angle,_,radius=map(float,values.groups())
            center=start-radius*np.array([math.cos(math.radians(angle)),math.sin(math.radians(angle))])
        if radius<=0 or not np.all(np.isfinite(center)):raise ValueError("invalid curve")
        circles.append((center,radius))
    if not commands:raise ValueError("no supported curve commands")
    points={name:np.asarray(p,float) for name,p in geometry["points"].items()}
    span=float(np.linalg.norm(np.ptp(list(points.values()),axis=0)))
    tolerance=tolerance_rel*span
    fixed=set(dependencies)&set(points)
    for center,radius in circles:
        fixed.update(name for name,p in points.items() if float(np.linalg.norm(p-center))<=tolerance)
        fixed.update(name for name,p in points.items() if abs(float(np.linalg.norm(p-center))-radius)<=tolerance)
        # Preserve existing near-tangents conservatively by freezing their
        # endpoints. A free external point must not rotate a tangent away.
        for a,b in geometry["segments"].values():
            u=points[b]-points[a];length=float(np.linalg.norm(u))
            if length<=1e-12:continue
            offset=center-points[a]
            distance=abs(float(u[0]*offset[1]-u[1]*offset[0]))/length
            if abs(distance-radius)<=tolerance and (a in fixed or b in fixed):fixed.update((a,b))
    return {"fixed_points":sorted(fixed),"dependencies":sorted(dependencies),
            "circles":[{"center":c.tolist(),"radius":r} for c,r in circles]}


def rewrite_with_frozen_curves(tex, before, after, anchors, rewrite):
    """Transport straight annotations while preserving curve source verbatim."""
    protected=[]
    def shield(match):
        command=match[0]
        if re.search(r"\b(?:circle|arc|ellipse|controls)\b",command):
            token=f"GEOFROZENCURVE{len(protected)}TOKEN"
            protected.append((token,command));return token
        return command
    masked=re.sub(r"\\(?:draw|path|filldraw)\b[^;]*;",shield,tex,flags=re.S)
    for name in anchors["dependencies"]:
        pattern=r"\\coordinate\s*\("+re.escape(name)+r"\)\s*at\s*.*?;"
        def coordinate(match):
            token=f"GEOFROZENCURVE{len(protected)}TOKEN"
            protected.append((token,match[0]));return token
        masked=re.sub(pattern,coordinate,masked,flags=re.S)
    emitted=rewrite(masked,before,after)
    for token,command in protected:emitted=emitted.replace(token,command)
    return emitted
