"""Repair the generated program, leaving GES measurements unchanged."""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any

import numpy as np

from .optimize_relations import optimize_coordinates
from .relation_candidates import numeric_candidates, pair_metrics
from .tikz_geometry import clean, extract_geometry, has_curves, rewrite_tex
from .curve_anchors import curve_anchors, rewrite_with_frozen_curves
from .angle_glyphs import marker_paths

REPAIR_ALGORITHM = 'post_tikz.body_candidates.v2'


def repair_tikz_constraints(
    tex: str,
    *,
    enabled: bool = True,
    angle_tol_deg: float = 0.5,
    max_shift_rel: float = 0.005,
    max_length_change_rel: float = 0.01,
    topology_tol_rel: float = 0.002,
    incidence_mode: str = "snap",
    length_weight: float = 0.0,
    length_scope: str = "edges",
    curve_policy: str = "defer",
    incidence_strength: float = 1.0,
    relation_types: tuple[str, ...] = ("parallel", "perpendicular"),
    relaxation: float = 1.0,
    curve_options: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any]]:
    """Jointly project named vertices, then verify the exported coordinate table.

    Parallel/perpendicular candidates are derived only from this program.
    Existing incidence is preserved, and equal lengths are not inferred.
    Unsupported sources and failed guards return the exact original string.
    """
    digest = hashlib.sha256(tex.encode("utf-8")).hexdigest()
    report: dict[str, Any] = {
        "ok": True, "enabled": enabled, "applied": False,
        "stage": "post_tikz", "constraint_mode": "joint_coordinate_projection",
        "candidate_source": "generated_tikz", "reference_used": False,
        "algorithm": REPAIR_ALGORITHM, "angle_glyphs_are_candidates": False,
        "input_sha256": digest, "output_sha256": digest,
        "reason": "disabled", "accepted": [], "rejected": [],
        "limits": {"angle_tol_deg": angle_tol_deg, "max_shift_rel": max_shift_rel,
                   "max_length_change_rel": max_length_change_rel},
    }
    if not enabled:
        return tex, report
    limits = (angle_tol_deg, max_shift_rel, max_length_change_rel, topology_tol_rel, length_weight,
              incidence_strength, relaxation)
    if (not all(np.isfinite(value) and value >= 0 for value in limits)
            or curve_policy not in ("defer","freeze") or incidence_strength>1 or not 0<relaxation<=1
            or any(kind not in ("parallel","perpendicular") for kind in relation_types)):
        report.update(ok=False, reason="invalid_limits")
        return tex, report
    text = clean(tex)
    report["limits"].update(topology_tol_rel=topology_tol_rel,incidence_mode=incidence_mode,
        length_weight=length_weight,length_scope=length_scope,curve_policy=curve_policy,
        incidence_strength=incidence_strength,relation_types=list(relation_types),relaxation=relaxation)
    profile=hashlib.sha256(json.dumps({'algorithm': REPAIR_ALGORITHM, 'limits': report['limits']},sort_keys=True).encode()).hexdigest()[:16]
    content_hash=hashlib.sha256(text.strip().encode("utf-8")).hexdigest()
    if re.search(r"% GEOAGENT_REPAIR_V1 "+profile+" "+content_hash+r"\b",tex):
        report["reason"]="already_processed"
        return tex,report
    curved=has_curves(text) or any(re.search(r"\b(?:circle|arc|ellipse|controls)\b",c)
        for c in re.findall(r"\\(?:draw|path|filldraw)\b[^;]*;",text,re.S))
    if curved and curve_options:
        options=dict(angle_tol_deg=angle_tol_deg,max_shift_rel=max_shift_rel,
            max_length_change_rel=max_length_change_rel,topology_tol_rel=topology_tol_rel,
            incidence_mode=incidence_mode,length_weight=length_weight,length_scope=length_scope,
            curve_policy=curve_policy,incidence_strength=incidence_strength,
            relation_types=relation_types,relaxation=relaxation)
        if any(key not in options for key in curve_options):
            report.update(ok=False,reason="invalid_curve_options")
            return tex,report
        options.update(curve_options)
        emitted,nested=repair_tikz_constraints(tex,enabled=enabled,**options)
        nested["curve_options_applied"]=curve_options
        return emitted,nested
    if curved and curve_policy=="defer":
        report["reason"] = "deferred_curves"
        return tex, report
    # Local/nonuniform transformations change the metric or marker frames.
    if (text.count(r"\begin{tikzpicture}") != 1
            or r"\begin{scope}" in text
            or re.search(r"\b(?:xscale|yscale|xslant|yslant|cm|x|y)\s*=", text)):
        report["reason"] = "unsupported_transform_or_scope"
        return tex, report
    try:
        annotation_audit = {}
        before = extract_geometry(text, annotation_audit=annotation_audit)
        report['angle_glyph_exclusion'] = annotation_audit
        excluded_paths, _, _ = marker_paths(text)
        anchors=curve_anchors(text,before) if curved else None
        # Partial parsing must not silently turn a long literal/relative edge
        # into an unprotected edge while another named edge is optimized.
        span = float(np.linalg.norm(np.ptp(list(before["points"].values()), axis=0)))
        literal = r"\(\s*([-+\d.eE]+)\s*,\s*([-+\d.eE]+)\s*\)"
        for draw in re.findall(r"\\draw\b(.*?);", text, re.S):
            if draw in excluded_paths:
                continue
            if curved and re.search(r"\b(?:circle|arc|ellipse|controls)\b",draw):continue
            if "++" in draw or re.search(r"(?:--|to)\s*\+", draw):
                report["reason"] = "unsupported_relative_path"
                return tex, report
            coordinates = [list(map(float, m)) for m in re.findall(literal, draw)]
            if coordinates:
                if re.search(r"\([A-Za-z][A-Za-z0-9_']*\)\s*--\s*" + literal, draw):
                    report["reason"] = "unsupported_mixed_path"
                    return tex, report
                if len(coordinates) > 1 and np.linalg.norm(np.ptp(coordinates, axis=0)) > 0.08 * span:
                    report["reason"] = "unsupported_literal_edge"
                    return tex, report
        candidates = numeric_candidates(before, {
            "angle_deg": angle_tol_deg, "relative_distance": 0.005,
        })
        candidates=[r for r in candidates if r["type"] in relation_types]
        after, result = optimize_coordinates(
            before, candidates, max_shift_rel=max_shift_rel,
            max_length_change_rel=max_length_change_rel,
            topology_tol_rel=topology_tol_rel,incidence_mode=incidence_mode,
            length_weight=length_weight,length_scope=length_scope,
            fixed_points=anchors["fixed_points"] if anchors else (),
            incidence_strength=incidence_strength,
        )
        report.update(result)
        report["curve_policy"]=curve_policy
        if anchors:report["curve_anchors"]=anchors
        report["candidate_count"] = len(candidates)
        if not report["applied"]:
            return tex, report
        if relaxation<1:
            for name,old in before["points"].items():
                after["points"][name]=(np.asarray(old)+relaxation*(np.asarray(after["points"][name])-old)).tolist()
            report["relaxation"]=relaxation
            report["solver_max_shift_rel"]=report["max_shift_rel"]
            report["max_shift_rel"]*=relaxation
            report["rms_shift_rel"]*=relaxation
            report["constraint_mode"]="relaxed_joint_projection"
        emitted = (rewrite_with_frozen_curves(tex,before,after,anchors,rewrite_tex)
                   if anchors else rewrite_tex(tex, before, after))
        exported = extract_geometry(emitted)
        if exported != after:
            raise ValueError("exported geometry does not round-trip")
        # Check all retained relations on the actual exported source, rather
        # than reporting only the solver's internal floating-point layout.
        errors = []
        for candidate in report["accepted"]:
            metric = pair_metrics(exported["points"], *(
                exported["segments"][sid] for sid in candidate["segments"]
            ))
            errors.append(metric[candidate["type"] + "_error_deg"])
        limit=1e-7 if relaxation==1 else max((c["before_error_deg"] for c in report["accepted"]),default=0)+1e-7
        if max(errors, default=0.0) > limit:
            raise ValueError("exported constraints exceed angle tolerance")
        if relaxation<1:
            for candidate,error in zip(report["accepted"],errors):candidate["after_error_deg"]=error
            report["max_after_error_deg"]=max(errors,default=0.0)
        report["export_verified"] = True
        report["max_export_error_deg"] = max(errors, default=0.0)
        report["point_count"] = len(after["points"])
        report["segment_count"] = len(after["segments"])
        if report["applied"]:
            # A generated version owns one frozen candidate set. Re-extracting
            # from its corrected output can introduce new relations and drift.
            # Content/config changes invalidate this invisible TeX comment.
            clean_hash=hashlib.sha256(clean(emitted).strip().encode("utf-8")).hexdigest()
            emitted=emitted.rstrip()+f"\n% GEOAGENT_REPAIR_V1 {profile} {clean_hash}\n"
        report["output_sha256"] = hashlib.sha256(emitted.encode("utf-8")).hexdigest()
        return emitted, report
    except (ValueError, KeyError, TypeError, np.linalg.LinAlgError) as exc:
        report.update(ok=False, applied=False, reason="unsupported_or_failed",
                      error=f"{type(exc).__name__}: {exc}", output_sha256=digest)
        return tex, report
