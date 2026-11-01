"""Read-only source-image evidence for small bends and labelled vertices."""
import itertools
import math
import numpy as np


def measured_topology(state):
    points={}
    for obj in state.objects.values():
        xy=(obj.coords or {}).get('px')
        if obj.type=='point' and obj.label and xy is not None and obj.source.startswith('cv:'):
            points.setdefault(obj.label,np.asarray(xy,float))
    segments=[]
    for obj in state.objects.values():
        if obj.type not in ('segment','line') or not obj.source.startswith('cv:'):
            continue
        a,b=(obj.coords or {}).get('a_px'),(obj.coords or {}).get('b_px')
        if a is not None and b is not None:
            segments.append((np.asarray(a,float),np.asarray(b,float)))
    edges=set()
    def supported(p,q):
        for a,b in segments:
            u=b-a;length=float(np.linalg.norm(u))
            if length<1e-8:continue
            values=[]
            for v in (p-a,q-a):
                along=float(v@u)/length
                distance=abs(float(u[0]*v[1]-u[1]*v[0]))/length
                values.append(distance<=3.5 and -12<=along<=length+12)
            if all(values):return True
        return False
    for a,b in itertools.combinations(sorted(points),2):
        if supported(points[a],points[b]):edges.add(frozenset((a,b)))
    bends=[]
    for v in sorted(points):
        neighbors=[n for n in sorted(points) if n!=v and frozenset((v,n)) in edges]
        for a,b in itertools.combinations(neighbors,2):
            u,w=points[a]-points[v],points[b]-points[v]
            if np.linalg.norm(u)*np.linalg.norm(w)<1e-10:continue
            angle=math.degrees(math.acos(float(np.clip((u@w)/(np.linalg.norm(u)*np.linalg.norm(w)),-1,1))))
            if 165<=angle<=179:
                bends.append({'labels':[a,v,b],'angle_deg':round(angle,3),'turn_deg':round(180-angle,3)})
    right_arms=[]
    for obj in state.objects.values():
        if obj.type!='right_angle' or not obj.source.startswith('cv:') or not points:continue
        vertex=(obj.coords or {}).get('vertex_px');marks=(obj.coords or {}).get('mark_points_px')
        if vertex is None or not marks:continue
        vertex=np.asarray(vertex,float)
        v=min(points,key=lambda n:np.linalg.norm(points[n]-vertex))
        if np.linalg.norm(points[v]-vertex)>6:continue
        rays=[np.asarray(m,float)-vertex for m in (marks[0],marks[-1])]
        if min(np.linalg.norm(r) for r in rays)<1e-8:continue
        rays=[r/np.linalg.norm(r) for r in rays]
        choices=[]
        neighbors=[n for n in points if n!=v and frozenset((v,n)) in edges]
        for a,b in itertools.combinations(neighbors,2):
            u,w=points[a]-vertex,points[b]-vertex
            u,w=u/np.linalg.norm(u),w/np.linalg.norm(w)
            alignment=max(min(float(u@rays[0]),float(w@rays[1])),min(float(u@rays[1]),float(w@rays[0])))
            angle=math.degrees(math.acos(float(np.clip(u@w,-1,1))))
            if alignment>.95 and abs(angle-90)<5:choices.append((abs(angle-90),a,b,angle))
        if choices:
            _,a,b,angle=min(choices)
            right_arms.append({'labels':[a,v,b],'measured_angle_deg':round(angle,3),'marker_side_px':(obj.coords or {}).get('side_length_px')})
    return {'cv_labelled_points':{n:p.tolist() for n,p in points.items()},'supported_shallow_bends':bends[:12],
            'verified_right_angle_arms':right_arms}


def topology_block(state):
    import json
    data=measured_topology(state)
    return ('SOURCE-IMAGE CV TOPOLOGY EVIDENCE (not reference data):\n'
            +json.dumps(data,ensure_ascii=False)+'\n'
            'Use these measured labelled positions ahead of noisy extended Hough endpoints. '
            'A supported shallow bend is evidence against automatic collinearity: preserve it or inspect the local image. '
            'Do not request projection onto a diagonal merely because the enclosing outline is a rectangle.\n')
