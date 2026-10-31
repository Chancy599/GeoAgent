"""Conservative joint coordinate projection for parallel/perpendicular candidates.

No reference data or LLM access. A rejected solve returns the original geometry.
Coordinates are normalized by the drawing diagonal to make guards scale-invariant.
"""
from __future__ import annotations

import copy
import itertools

import numpy as np

from .relation_candidates import numeric_candidates, pair_metrics


def optimize_coordinates(geometry, candidates=None, *, max_shift_rel=0.005,
                         max_length_change_rel=0.01, topology_tol_rel=0.0005):
    original=copy.deepcopy(geometry)
    candidates=copy.deepcopy(numeric_candidates(geometry) if candidates is None else candidates)
    names=sorted(geometry["points"])
    ids={name:i for i,name in enumerate(names)}
    px=np.asarray([geometry["points"][n] for n in names],dtype=float)
    span=float(np.linalg.norm(np.ptp(px,axis=0)))
    if not np.all(np.isfinite(px)) or span<=1e-12:
        raise ValueError("invalid geometry")
    origin=px.mean(axis=0)
    initial=(px-origin)/span
    edges={k:[ids[n] for n in pair] for k,pair in geometry["segments"].items()}
    for candidate in candidates:
        if candidate["type"] not in ("parallel","perpendicular"):
            raise ValueError("Only parallel/perpendicular constraints are accepted")
        if len(candidate["segments"])!=2 or any(s not in edges for s in candidate["segments"]):
            raise ValueError("unknown segment reference")

    # Preserve existing interior point-on-line incidence (including its tiny
    # original detector/rounding offset), without discovering collinear relations.
    incidence=[]
    for segment,(a,b) in edges.items():
        edge=initial[b]-initial[a]
        length=float(np.linalg.norm(edge))
        if length<1e-9:
            continue
        for p in range(len(names)):
            if p in (a,b):
                continue
            offset=initial[p]-initial[a]
            t=float(offset@edge)/(length*length)
            cross=float(edge[0]*offset[1]-edge[1]*offset[0])/length
            if 0.001<t<0.999 and abs(cross)<=topology_tol_rel:
                incidence.append((a,b,p,length,cross))

    def system(pos,active):
        values,rows=[],[]
        for candidate in active:
            a,b=edges[candidate["segments"][0]]
            c,d=edges[candidate["segments"][1]]
            u,v=pos[b]-pos[a],pos[d]-pos[c]
            base_u,base_v=initial[b]-initial[a],initial[d]-initial[c]
            denom=float(np.sqrt(np.linalg.norm(base_u)*np.linalg.norm(base_v)))
            if denom<1e-9 or min(np.linalg.norm(u),np.linalg.norm(v))<1e-8:
                raise ValueError("degenerate constraint")
            if candidate["type"]=="perpendicular":
                value=float(u@v)/denom
                gu,gv=v/denom,u/denom
            else:
                value=float(u[0]*v[1]-u[1]*v[0])/denom
                gu=np.array([v[1],-v[0]])/denom
                gv=np.array([-u[1],u[0]])/denom
            row=np.zeros_like(pos)
            row[b]+=gu; row[a]-=gu; row[d]+=gv; row[c]-=gv
            values.append(value);rows.append(row.ravel())
        for a,b,p,length,target in incidence:
            u,v=pos[b]-pos[a],pos[p]-pos[a]
            row=np.zeros_like(pos)
            gb=np.array([v[1],-v[0]])/length
            gp=np.array([-u[1],u[0]])/length
            row[b]+=gb;row[p]+=gp;row[a]-=gb+gp
            values.append(float(u[0]*v[1]-u[1]*v[0])/length-target)
            rows.append(row.ravel())
        return np.asarray(values),np.asarray(rows)

    def solve(active):
        # A spanning forest of segment directions implies all compatible
        # transitive relations. Do not feed six dependent equations for four
        # rectangle edges to the nonlinear solve.
        parent={name:name for name in edges}
        parity={name:0 for name in edges}
        def find(name):
            if parent[name]!=name:
                root,turn=find(parent[name])
                parity[name]^=turn
                parent[name]=root
            return parent[name],parity[name]
        forest=[]
        for candidate in active:
            first,second=candidate["segments"]
            a,pa=find(first);b,pb=find(second)
            turn=int(candidate["type"]=="perpendicular")
            if a==b:
                if pa^pb!=turn:
                    raise ValueError("inconsistent direction cycle")
                continue
            parent[b]=a
            parity[b]=pa^pb^turn
            forest.append(candidate)
        pos=initial.copy()
        for iteration in range(60):
            residual,jac=system(pos,forest)
            # Closest point to the ORIGINAL coordinates on the linearized
            # constraint manifold. SVD removes redundant rectangle constraints.
            anchor=(initial-pos).ravel()
            correction=np.linalg.lstsq(jac,-residual-jac@anchor,rcond=1e-8)[0]
            delta=(anchor+correction).reshape(pos.shape)
            if not np.all(np.isfinite(delta)):
                raise ValueError("nonfinite projection")
            if np.max(np.abs(residual),initial=0)<1e-12 and np.linalg.norm(delta)<1e-10:
                return pos
            pos+=delta
        residual,_=system(pos,forest)
        if np.max(np.abs(residual),initial=0)>1e-10:
            raise ValueError("constraints did not converge")
        return pos

    def guard(pos,active):
        shift=float(np.max(np.linalg.norm(pos-initial,axis=1)))
        length_change=0.0
        for a,b in edges.values():
            before=initial[b]-initial[a];after=pos[b]-pos[a]
            length=float(np.linalg.norm(before))
            if length<1e-9:
                continue
            change=abs(float(np.linalg.norm(after))/length-1)
            length_change=max(length_change,change)
            if np.linalg.norm(after)<length*0.5 or before@after<=0:
                return "segment_degenerated",shift,length_change
        if shift>max_shift_rel:
            return "max_shift_exceeded",shift,length_change
        if length_change>max_length_change_rel:
            return "length_change_exceeded",shift,length_change
        for a,b,p,_,_ in incidence:
            edge=pos[b]-pos[a]
            t=float((pos[p]-pos[a])@edge)/float(edge@edge)
            if not 0<t<1:
                return "incidence_order_changed",shift,length_change
        return None,shift,length_change

    def error(candidate):
        metric=pair_metrics(geometry["points"],*(geometry["segments"][s] for s in candidate["segments"]))
        return metric[candidate["type"]+"_error_deg"]

    active=sorted(candidates,key=error)
    rejected=[]
    report={"applied":False,"reason":"no_candidates","input_candidates":len(candidates),
            "accepted":[],"rejected":rejected,"preserved_incidence_count":len(incidence),
            "max_shift_rel":0.0,"max_length_change_rel":0.0,"reference_used":False}
    if not active:
        return original,report
    # Reject weaker hypotheses if they conflict or require substantial distortion.
    for _ in range(len(active)+1):
        if not active:
            report["reason"]="all_candidates_rejected"
            return original,report
        try:
            pos=solve(active)
            reason,shift,length_change=guard(pos,active)
        except (ValueError,np.linalg.LinAlgError) as exc:
            reason=str(exc)
        if reason:
            candidate=active.pop()
            rejected.append({"candidate":candidate,"reason":reason})
            continue
        optimized=copy.deepcopy(geometry)
        corrected=pos*span+origin
        for name,xy in zip(names,corrected):
            optimized["points"][name]=xy.tolist()
        details=[]
        for candidate in active:
            first,second=(geometry["segments"][s] for s in candidate["segments"])
            before=pair_metrics(geometry["points"],first,second)
            after=pair_metrics(optimized["points"],first,second)
            key=candidate["type"]+"_error_deg"
            details.append({"type":candidate["type"],"segments":candidate["segments"],
                            "before_error_deg":before[key],"after_error_deg":after[key]})
        max_error=max(d["after_error_deg"] for d in details)
        if max_error>1e-7:
            rejected.append({"candidate":active.pop(),"reason":"final_angle_tolerance_exceeded"})
            continue
        report.update(applied=shift>1e-12,reason="applied" if shift>1e-12 else "already_satisfied",
                      accepted=details,max_shift_rel=shift,max_length_change_rel=length_change,
                      rms_shift_rel=float(np.sqrt(np.mean(np.sum((pos-initial)**2,axis=1)))),
                      max_after_error_deg=max_error)
        return optimized,report
    return original,report
