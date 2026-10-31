"""Shared Geometric Evidence State (GES).

The GES is the single source of truth for every agent.  It stores geometry
candidates, provenance, conflicts, TikZ versions, compilation results, budgets
and the full action history.  It is JSON-serialisable and checkpointable.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

MAX_TEXT = 20000


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _serious_issue_count(report: dict[str, Any] | None) -> int:
    """Count non-flaky high/medium issues in a critic report."""
    if not isinstance(report, dict):
        return 0
    counts = report.get("actionable_counts")
    if isinstance(counts, dict):
        return int(counts.get("high", 0) or 0) + int(counts.get("medium", 0) or 0)
    serious = 0
    for issue in report.get("issues") or []:
        if not isinstance(issue, dict) or issue.get("flaky"):
            continue
        if str(issue.get("severity", "")).lower() in ("high", "medium"):
            serious += 1
    return serious


def _checklist_value(report: dict[str, Any] | None) -> float:
    """Deterministic checklist score for ranking; -1 when absent."""
    if not isinstance(report, dict):
        return -1.0
    try:
        return float(report.get("checklist_score"))
    except (TypeError, ValueError):
        return -1.0


def _truncate(value: Any, limit: int = MAX_TEXT) -> Any:
    if isinstance(value, str):
        return value if len(value) <= limit else value[:limit] + f"\n...[truncated {len(value) - limit} chars]"
    if isinstance(value, list):
        return [_truncate(v, limit) for v in value[:200]]
    if isinstance(value, dict):
        return {str(k): _truncate(v, limit) for k, v in list(value.items())[:200]}
    return value


class GeometryObject(BaseModel):
    id: str
    type: str  # point | segment | line | circle | arc | right_angle | label | polygon
    label: str | None = None
    coords: dict[str, Any] = Field(default_factory=dict)
    normalized: dict[str, Any] = Field(default_factory=dict)
    style: dict[str, Any] = Field(default_factory=dict)
    source: str = "unknown"
    status: str = "candidate"  # candidate | confirmed | rejected | conflict
    confidence_kind: str = "heuristic"  # explicitly not a calibrated probability
    confidence: float | None = None
    notes: list[str] = Field(default_factory=list)
    attributes: dict[str, Any] = Field(default_factory=dict)


class Relation(BaseModel):
    id: str
    subject: str
    relation: str  # on_segment | on_circle | perpendicular | parallel | collinear | midpoint | center ...
    object: str | None = None
    source: str = "unknown"
    evidence: str | None = None
    status: str = "candidate"


class EvidenceRecord(BaseModel):
    id: str
    source: str
    method: str
    summary: str
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=_now)


class ConflictRecord(BaseModel):
    id: str
    topic: str
    claims: list[dict[str, Any]] = Field(default_factory=list)
    status: str = "unresolved"  # unresolved | resolved
    resolution: str | None = None


class TikZVersion(BaseModel):
    version: int
    tex: str
    tex_path: str | None = None
    pdf_path: str | None = None
    png_path: str | None = None
    ok: bool = False
    compiled: bool = False
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=_now)
    agent: str = "tikz_agent"
    mode: str = "generate"
    notes: str = ""
    compile_seconds: float | None = None
    critic_report: dict[str, Any] | None = None
    critic_score: float | None = None


class CompilationResult(BaseModel):
    version: int
    ok: bool
    returncode: int | None = None
    seconds: float | None = None
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    log_tail: str = ""
    tex_path: str | None = None
    pdf_path: str | None = None
    png_path: str | None = None
    created_at: str = Field(default_factory=_now)


class ValidationCheck(BaseModel):
    name: str
    passed: bool
    detail: str = ""


class ValidationResult(BaseModel):
    version: int | None = None
    passed: bool
    checks: list[ValidationCheck] = Field(default_factory=list)
    created_at: str = Field(default_factory=_now)


class ActionRecord(BaseModel):
    step: int
    action: str
    purpose: str = ""
    params: dict[str, Any] = Field(default_factory=dict)
    status: str = "ok"
    result_summary: str = ""
    duration_s: float = 0.0
    token_usage: dict[str, Any] = Field(default_factory=dict)
    visual_calls: int = 0
    error: str | None = None


class GeometricEvidenceState(BaseModel):
    # image
    image_path: str
    image_size: dict[str, int] = Field(default_factory=dict)

    # core evidence
    objects: dict[str, GeometryObject] = Field(default_factory=dict)
    relations: dict[str, Relation] = Field(default_factory=dict)
    evidence: dict[str, EvidenceRecord] = Field(default_factory=dict)
    conflicts: list[ConflictRecord] = Field(default_factory=list)
    label_bindings: dict[str, str] = Field(default_factory=dict)

    # TikZ versions
    current_tikz: str | None = None
    best_tikz: str | None = None
    best_version: int | None = None
    best_score: float | None = None
    tikz_versions: list[TikZVersion] = Field(default_factory=list)
    compilation_results: list[CompilationResult] = Field(default_factory=list)
    validation_results: list[ValidationResult] = Field(default_factory=list)
    critic_reports: list[dict[str, Any]] = Field(default_factory=list)

    # process
    unresolved_issues: list[dict[str, Any]] = Field(default_factory=list)
    action_history: list[ActionRecord] = Field(default_factory=list)
    cv_runs: list[dict[str, Any]] = Field(default_factory=list)
    regions: dict[str, dict[str, Any]] = Field(default_factory=dict)

    # accounting
    token_usage: dict[str, Any] = Field(default_factory=dict)
    remaining_budget: dict[str, Any] = Field(default_factory=dict)

    meta: dict[str, Any] = Field(default_factory=dict)

    # ------------------------------------------------------------------ #
    # geometry
    # ------------------------------------------------------------------ #
    def add_object(self, obj: GeometryObject | dict[str, Any], *, dedupe_by_geometry: bool = False) -> str:
        record = obj if isinstance(obj, GeometryObject) else GeometryObject.model_validate(obj)
        if not record.id:
            record.id = _slug_id(record.type, record.label, record.coords)
        if dedupe_by_geometry and record.id in self.objects:
            existing = self.objects[record.id]
            existing.notes.extend(n for n in record.notes if n not in existing.notes)
            existing.attributes.update(record.attributes)
            if record.confidence is not None and (existing.confidence is None or record.confidence > existing.confidence):
                existing.confidence = record.confidence
            return existing.id
        self.objects[record.id] = record
        return record.id

    def add_objects(self, objects: list[GeometryObject | dict[str, Any]]) -> list[str]:
        return [self.add_object(obj) for obj in objects]

    def add_relation(self, relation: Relation | dict[str, Any]) -> str:
        record = relation if isinstance(relation, Relation) else Relation.model_validate(relation)
        if not record.id:
            record.id = f"rel_{len(self.relations) + 1:03d}"
        self.relations[record.id] = record
        return record.id

    def add_evidence(
        self, source: str, method: str, summary: str, payload: dict[str, Any] | None = None
    ) -> str:
        ev_id = f"ev_{len(self.evidence) + 1:04d}"
        self.evidence[ev_id] = EvidenceRecord(
            id=ev_id,
            source=source,
            method=method,
            summary=summary,
            payload=_truncate(payload or {}),
        )
        return ev_id

    def add_conflict(self, topic: str, claims: list[dict[str, Any]]) -> str:
        conflict = ConflictRecord(id=f"conflict_{len(self.conflicts) + 1:03d}", topic=topic, claims=claims)
        self.conflicts.append(conflict)
        return conflict.id

    def resolve_conflict(self, conflict_id: str, resolution: str) -> None:
        for conflict in self.conflicts:
            if conflict.id == conflict_id:
                conflict.status = "resolved"
                conflict.resolution = resolution
                return

    def add_cv_run(self, record: dict[str, Any]) -> None:
        self.cv_runs.append(_truncate(record))

    def set_unresolved(self, issues: list[dict[str, Any]]) -> None:
        self.unresolved_issues = _truncate(issues)

    def add_unresolved(self, issue: dict[str, Any]) -> None:
        self.unresolved_issues.append(_truncate(issue))

    # ------------------------------------------------------------------ #
    # TikZ versions
    # ------------------------------------------------------------------ #
    def add_tikz_version(
        self,
        tex: str,
        *,
        agent: str = "tikz_agent",
        mode: str = "generate",
        notes: str = "",
        tex_path: str | None = None,
        png_path: str | None = None,
    ) -> TikZVersion:
        version = TikZVersion(
            version=len(self.tikz_versions) + 1,
            tex=tex,
            agent=agent,
            mode=mode,
            notes=notes,
            tex_path=tex_path,
            png_path=png_path,
        )
        self.tikz_versions.append(version)
        self.current_tikz = tex
        return version

    def latest_version(self) -> TikZVersion | None:
        return self.tikz_versions[-1] if self.tikz_versions else None

    def mark_compilation(
        self,
        version_number: int,
        *,
        ok: bool,
        tex_path: str | None,
        pdf_path: str | None,
        png_path: str | None,
        errors: list[str],
        warnings: list[str],
        seconds: float | None,
        log_tail: str = "",
        returncode: int | None = None,
    ) -> CompilationResult:
        version = self.get_version(version_number)
        if version is not None:
            version.ok = bool(ok and pdf_path)
            version.compiled = True
            version.tex_path = tex_path or version.tex_path
            version.pdf_path = pdf_path
            version.png_path = png_path
            version.errors = list(errors)
            version.warnings = list(warnings)
            version.compile_seconds = seconds
        result = CompilationResult(
            version=version_number,
            ok=bool(ok and pdf_path),
            returncode=returncode,
            seconds=seconds,
            errors=list(errors),
            warnings=list(warnings),
            log_tail=log_tail[-4000:],
            tex_path=tex_path,
            pdf_path=pdf_path,
            png_path=png_path,
        )
        self.compilation_results.append(result)
        return result

    def get_version(self, number: int) -> TikZVersion | None:
        for version in self.tikz_versions:
            if version.version == number:
                return version
        return None

    def update_best(self, *, allow_unscored: bool = True) -> int | None:
        """Pick the best compiled version.

        Prefer versions with fewer high/medium actionable issues, then the
        deterministic checklist score, then the VLM critic score, then the
        newest version.
        """
        candidates = [v for v in self.tikz_versions if v.ok and v.png_path]
        if not candidates:
            return None
        scored = [v for v in candidates if v.critic_score is not None]
        if scored:
            best = max(
                scored,
                key=lambda v: (
                    -_serious_issue_count(v.critic_report),
                    _checklist_value(v.critic_report),
                    float(v.critic_score or 0),
                    v.version,
                ),
            )
        elif allow_unscored:
            best = max(candidates, key=lambda v: v.version)
        else:
            return self.best_version
        self.best_version = best.version
        self.best_tikz = best.tex
        self.best_score = best.critic_score
        return best.version

    def attach_critic(self, version_number: int, report: dict[str, Any], score: float | None) -> None:
        self.critic_reports.append(report)
        version = self.get_version(version_number)
        if version is not None:
            version.critic_report = report
            version.critic_score = score

    # ------------------------------------------------------------------ #
    # actions / budgets
    # ------------------------------------------------------------------ #
    def record_action(self, record: ActionRecord) -> None:
        record.params = _truncate(record.params)
        record.result_summary = _truncate(record.result_summary)
        self.action_history.append(record)

    def update_accounting(self, usage_summary: dict[str, Any], budget: dict[str, Any], counters: dict[str, int]) -> None:
        self.token_usage = usage_summary
        remaining = {}
        remaining["steps_left"] = max(0, int(budget["max_steps"]) - int(counters.get("steps", 0)))
        remaining["tool_calls_left"] = max(0, int(budget["max_tool_calls"]) - int(counters.get("tool_calls", 0)))
        remaining["visual_calls_left"] = max(0, int(budget["max_visual_calls"]) - int(counters.get("visual_calls", 0)))
        total_tokens = int(usage_summary.get("totals", {}).get("total_tokens", 0))
        remaining["tokens_left"] = max(0, int(budget["max_total_tokens"]) - total_tokens)
        remaining["max_steps"] = int(budget["max_steps"])
        remaining["max_tool_calls"] = int(budget["max_tool_calls"])
        remaining["max_visual_calls"] = int(budget["max_visual_calls"])
        remaining["max_total_tokens"] = int(budget["max_total_tokens"])
        remaining["total_tokens_used"] = total_tokens
        self.remaining_budget = remaining

    # ------------------------------------------------------------------ #
    # summaries / persistence
    # ------------------------------------------------------------------ #
    def summary(self, max_objects: int = 40, max_chars: int = 7000) -> str:
        """Compact textual state for the Supervisor."""
        lines: list[str] = []
        lines.append(f"IMAGE: {Path(self.image_path).name} size={self.image_size}")
        if self.objects:
            counts: dict[str, int] = {}
            for obj in self.objects.values():
                counts[obj.type] = counts.get(obj.type, 0) + 1
            lines.append("OBJECTS: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
            shown = 0
            for obj in self.objects.values():
                if shown >= max_objects:
                    lines.append(f"... ({len(self.objects) - max_objects} more objects)")
                    break
                bits = [f"{obj.id}:{obj.type}"]
                if obj.label:
                    bits.append(f"label={obj.label}")
                if obj.coords:
                    bits.append(f"coords={_short(obj.coords)}")
                if obj.style:
                    bits.append(f"style={_short(obj.style)}")
                if obj.notes:
                    bits.append(f"note={obj.notes[-1][:80]}")
                bits.append(f"src={obj.source}")
                lines.append("  " + " | ".join(bits))
                shown += 1
        if self.relations:
            lines.append(f"RELATIONS: {len(self.relations)}")
            for rel in list(self.relations.values())[:20]:
                lines.append(f"  {rel.subject} {rel.relation} {rel.object or ''} ({rel.status}, {rel.source})")
        if self.label_bindings:
            lines.append("LABEL_BINDINGS: " + _short(self.label_bindings))
        if self.current_tikz:
            version = self.latest_version()
            status = "uncompiled"
            if version is not None and version.compiled:
                status = "compiled OK" if version.ok else "compile FAILED"
            lines.append(f"CURRENT_TIKZ: version {version.version if version else '?'}, {status}")
        else:
            lines.append("CURRENT_TIKZ: none")
        if self.best_version is not None:
            lines.append(
                f"BEST_TIKZ: version {self.best_version}"
                + (f" critic_score={self.best_score}" if self.best_score is not None else "")
            )
        else:
            lines.append("BEST_TIKZ: none")
        if self.compilation_results:
            last = self.compilation_results[-1]
            lines.append(
                f"LAST_COMPILE: v{last.version} ok={last.ok} errors={len(last.errors)}"
                + (f" first_error={last.errors[0][:160]}" if last.errors else "")
            )
        if self.critic_reports:
            latest = self.critic_reports[-1]
            issues = latest.get("issues") or []
            checklist = latest.get("checklist_score")
            checklist_bit = f" checklist={checklist}" if checklist is not None else ""
            lines.append(
                f"CRITIC: {len(issues)} issues; latest assessment={latest.get('assessment_score')}; "
                f"must_repair={latest.get('must_repair', 'unknown')}{checklist_bit}"
            )
            for issue in issues[:6]:
                marker = " flaky" if issue.get("flaky") else ""
                lines.append(
                    f"  - [{issue.get('severity', '?')}{marker}] {str(issue.get('type', 'issue'))}: "
                    f"{str(issue.get('description', ''))[:140]}"
                )
            pending = [
                check
                for check in latest.get("checks") or []
                if isinstance(check, dict) and check.get("status") in ("missing", "wrong")
            ]
            for check in pending[:4]:
                lines.append(f"  - [check {check['status']}] {check['object_id']}")
        if self.unresolved_issues:
            lines.append("UNRESOLVED:")
            for issue in self.unresolved_issues[:8]:
                lines.append(f"  - {str(issue)[:180]}")
        if self.conflicts:
            open_conflicts = [c for c in self.conflicts if c.status == "unresolved"]
            if open_conflicts:
                lines.append("CONFLICTS:")
                for conflict in open_conflicts[:5]:
                    lines.append(f"  - {conflict.topic}")
        if self.remaining_budget:
            budget = self.remaining_budget
            lines.append(
                "BUDGET: "
                f"steps {budget.get('steps_left')}/{budget.get('max_steps')} left, "
                f"tools {budget.get('tool_calls_left')}/{budget.get('max_tool_calls')} left, "
                f"visual {budget.get('visual_calls_left')}/{budget.get('max_visual_calls')} left, "
                f"tokens {budget.get('tokens_left')}/{budget.get('max_total_tokens')} left"
            )
        text = "\n".join(lines)
        if len(text) > max_chars:
            text = text[:max_chars] + "\n...[state summary truncated]"
        return text

    def to_json(self) -> str:
        return self.model_dump_json(indent=2)

    def save(self, path: str | Path) -> Path:
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(self.to_json(), encoding="utf-8")
        return out

    @classmethod
    def load(cls, path: str | Path) -> "GeometricEvidenceState":
        return cls.model_validate_json(Path(path).read_text(encoding="utf-8"))


def _slug_id(kind: str, label: str | None, coords: dict[str, Any]) -> str:
    if label:
        safe = "".join(ch for ch in label if ch.isalnum() or ch in "_-") or "x"
        return f"{kind}_{safe}"
    payload = json.dumps(coords, sort_keys=True, ensure_ascii=False)
    digest = hashlib.sha1(payload.encode("utf-8")).hexdigest()[:8]
    return f"{kind}_{digest}"


def _short(value: Any, limit: int = 220) -> str:
    if isinstance(value, (dict, list)):
        text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    else:
        text = str(value)
    return text if len(text) <= limit else text[: limit - 3] + "..."
