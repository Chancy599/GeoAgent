"""Critic subagent: compare the original figure with the latest render.

The two figures are composed into one side-by-side image with identically
sized panels, so the model compares shapes at the same scale instead of
guessing across different resolutions.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Iterable

from PIL import Image, ImageDraw

from ..llm.client import LLMClient
from ..state.schemas import GeometricEvidenceState
from .base import compact_json
from .prompts import CRITIC_SYSTEM
from ..state.measured_topology import topology_block

# Two 620 px panels + 12 px separator = 1252 px, inside the default 1280 px
# image_max_dim, so the client does not downscale the composite again.
PANEL_PX = 620
GAP_PX = 12
_PANEL_CONTENT = 0.9  # keep 5% padding around the ink on each side
_SEPARATOR = (225, 225, 225)

ISSUE_TYPES = {
    "missing_element",
    "wrong_position",
    "wrong_style",
    "label_error",
    "arc_error",
    "layout_error",
    "other",
}
SEVERITIES = {"high", "medium", "low"}

# Directional style/size claims that mean the opposite of each other. A critic
# report that flips one of these on the same element between two versions is
# usually noise, so it is marked flaky instead of driving another repair.
_DIRECTION_GROUPS = (
    (
        ("too thick", "thicker", "too heavy", "heavier", "too bold", "bolder", "too wide", "wider", "too dark", "darker"),
        ("too thin", "thinner", "too light", "lighter", "too faint", "fainter", "too narrow", "narrower", "too pale", "paler"),
    ),
    (("too far", "farther", "further"), ("too close", "closer", "too near")),
    (("too large", "larger", "too big", "bigger"), ("too small", "smaller")),
)
_DIRECTION_PATTERNS = tuple(
    tuple(tuple((phrase, re.compile(rf"\b{re.escape(phrase)}\b")) for phrase in side) for side in group)
    for group in _DIRECTION_GROUPS
)
_WEIGHT_TOPIC = {"stroke", "line", "width", "thickness", "weight", "arc", "diameter"}
# Low-severity remarks about panel normalisation are not fixable in TikZ.
_INFORMATIONAL = re.compile(
    r"(aspect ratio|scaled, not warped|only scaled|scaled rather than warped|"
    r"scaled (?:up|down) relative to the original|panel is scaled|overall scale)",
    re.IGNORECASE,
)
_STOPWORDS = frozenset(
    "the and are for from with that this which have has been being than then but not its "
    "was were was in on at to of as by an or all both more most very slightly noticeably "
    "too should would could appears appear figure original render rendered rendering".split()
)

# Checklist-driven review: the critic must return one status per GES object.
CHECK_STATUS = {"present", "missing", "wrong", "unclear"}
_STATUS_CREDIT = {"present": 1.0, "wrong": 0.5}  # unclear is excluded, missing scores 0
_CHECKLIST_PRIORITY = {
    "segment": 0,
    "arc": 0,
    "circle": 0,
    "line": 0,
    "right_angle": 1,
    "polygon": 1,
    "point": 2,
}
# Deterministic TikZ-source label check. Only single-letter labels (optionally
# primed) are checked; subscripts and multi-letter words are left to the VLM.
_LABEL_OK = re.compile(r"^[A-Za-z](?:['′])?$")
_MATH_SPAN = re.compile(r"\$([^$]+)\$|\\\((.+?)\\\)", re.S)
_LABEL_TOKEN = re.compile(r"(?<![A-Za-z])([A-Za-z])(′)?(?![A-Za-z])")


def _words(text: str) -> set[str]:
    out = set()
    for word in re.findall(r"[a-z]{3,}", str(text).lower()):
        if word in _STOPWORDS:
            continue
        if word.endswith("s") and not word.endswith("ss"):
            word = word[:-1]
        out.add(word)
    return out


def _directions(text: str) -> set[tuple[int, int]]:
    """Return (group, side) for unambiguous directional claims in ``text``."""
    low = str(text).lower()
    found: set[tuple[int, int]] = set()
    for group_index, group in enumerate(_DIRECTION_PATTERNS):
        sides = [
            side_index
            for side_index, patterns in enumerate(group)
            if any(pattern.search(low) for _, pattern in patterns)
        ]
        if len(sides) == 1:
            found.add((group_index, sides[0]))
    return found


def _same_topic(new: dict[str, Any], old: dict[str, Any]) -> bool:
    new_ids = set(new.get("object_ids") or [])
    old_ids = set(old.get("object_ids") or [])
    if new_ids and old_ids:
        return bool(new_ids & old_ids)
    new_words = _words(new.get("description", ""))
    old_words = _words(old.get("description", ""))
    if not new_words or not old_words:
        return False
    if (new_words & _WEIGHT_TOPIC) and (old_words & _WEIGHT_TOPIC):
        return True
    shared = new_words & old_words
    return bool(shared) and len(shared) / len(new_words | old_words) >= 0.2


def _mark_flaky(issues: list[dict[str, Any]], prior_reports: Iterable[dict[str, Any]]) -> int:
    """Flag issues whose direction contradicts the latest prior verdict."""
    prior: tuple[Any, list[dict[str, Any]]] | None = None
    for report in reversed(list(prior_reports)):
        if not isinstance(report, dict):
            continue
        candidates = [
            issue
            for issue in report.get("issues") or []
            if isinstance(issue, dict) and not issue.get("flaky")
        ]
        if candidates:
            prior = (report.get("version"), candidates)
            break
    if prior is None:
        return 0
    prior_version, prior_issues = prior
    marked = 0
    for issue in issues:
        # Only the diagnosis carries a direction; the suggestion usually names
        # the opposite direction ("use a heavier stroke") and would cancel it.
        directions = _directions(issue.get("description", ""))
        if not directions:
            continue
        for old in prior_issues:
            if old.get("type") != issue.get("type"):
                continue
            old_directions = _directions(old.get("description", ""))
            contradiction = any(
                group == old_group and side != old_side
                for group, side in directions
                for old_group, old_side in old_directions
            )
            if not contradiction or not _same_topic(issue, old):
                continue
            issue["flaky"] = True
            issue["flaky_reason"] = (
                f"opposite verdict in v{prior_version}: {str(old.get('description', ''))[:160]}"
            )
            marked += 1
            break
    return marked


def _actionable_counts(issues: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"high": 0, "medium": 0, "low": 0}
    for issue in issues:
        if issue.get("flaky"):
            continue
        description = str(issue.get("description", ""))
        suggestion = str(issue.get("suggestion", ""))
        if not description.strip() and not suggestion.strip():
            continue
        if issue.get("severity") == "low" and _INFORMATIONAL.search(description):
            continue
        counts[issue["severity"]] += 1
    return counts


def _clean_bbox(value: Any) -> list[float] | None:
    """Validate a normalised [x0, y0, x1, y1] box from the critic."""
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    try:
        coords = [float(item) for item in value]
    except (TypeError, ValueError):
        return None
    if any(item < -0.05 or item > 1.05 for item in coords):
        return None
    return [round(min(1.0, max(0.0, item)), 3) for item in coords]


def _build_checklist(
    state: GeometricEvidenceState, max_items: int = 24
) -> list[dict[str, str]]:
    """List the GES objects the critic must assign a status to.

    Structural elements come first; unlabelled points are skipped because they
    are not individually identifiable in the render. ``label`` objects are
    handled by the deterministic source check instead.
    """
    objects = [
        obj
        for obj in state.objects.values()
        if obj.type in _CHECKLIST_PRIORITY
        and obj.status != "rejected"
        and (obj.type != "point" or obj.label)
    ]
    objects.sort(key=lambda obj: (_CHECKLIST_PRIORITY[obj.type], obj.id))
    items = []
    for obj in objects[:max_items]:
        hint = obj.type
        if obj.label:
            hint += f" labelled {obj.label}"
        items.append({"object_id": obj.id, "kind": obj.type, "hint": hint})
    return items


def _sanitise_checks(raw: Any, allowed_ids: set[str]) -> list[dict[str, str]]:
    checks: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        object_id = str(item.get("object_id", ""))[:64]
        status = str(item.get("status", "")).lower()
        if object_id not in allowed_ids or object_id in seen or status not in CHECK_STATUS:
            continue
        seen.add(object_id)
        checks.append(
            {
                "object_id": object_id,
                "status": status,
                "note": str(item.get("note", ""))[:200],
            }
        )
    return checks


def _checklist_score(checks: list[dict[str, str]]) -> float | None:
    """Deterministic share of checklist objects confirmed present.

    ``present`` scores 1, ``wrong`` 0.5, ``missing`` 0; ``unclear`` is dropped
    from both numerator and denominator so vagueness neither helps nor hurts.
    """
    counted = [check for check in checks if check["status"] != "unclear"]
    if not counted:
        return None
    credit = sum(_STATUS_CREDIT.get(check["status"], 0.0) for check in counted)
    return round(credit / len(counted), 3)


def _object_bbox(obj: Any, image_size: dict[str, int]) -> list[float] | None:
    """Approximate a normalised bbox for an object from its pixel coords."""
    try:
        width = float(image_size.get("width") or 0)
        height = float(image_size.get("height") or 0)
    except (TypeError, ValueError):
        return None
    if width <= 0 or height <= 0:
        return None
    coords = obj.coords if isinstance(getattr(obj, "coords", None), dict) else {}
    xs: list[float] = []
    ys: list[float] = []

    def add(point: Any) -> None:
        try:
            x, y = float(point[0]), float(point[1])
        except (TypeError, ValueError, IndexError, KeyError):
            return
        xs.append(x)
        ys.append(y)

    if obj.type == "point":
        add(coords.get("px"))
    elif obj.type in ("segment", "line"):
        add(coords.get("a_px"))
        add(coords.get("b_px"))
    elif obj.type in ("circle", "arc"):
        center = coords.get("center_px")
        try:
            radius = float(coords.get("radius_px"))
        except (TypeError, ValueError):
            radius = 0.0
        if isinstance(center, (list, tuple)) and len(center) == 2 and radius > 0:
            try:
                cx, cy = float(center[0]), float(center[1])
            except (TypeError, ValueError):
                return None
            add([cx - radius, cy - radius])
            add([cx + radius, cy + radius])
    elif obj.type == "right_angle":
        add(coords.get("vertex_px"))
    elif obj.type == "polygon":
        for point in coords.get("vertices_px") or []:
            add(point)
    if not xs or not ys:
        return None
    # Full circles often extend past the image edge; clamp to the visible panel.
    x0 = min(1.0, max(0.0, min(xs) / width))
    x1 = min(1.0, max(0.0, max(xs) / width))
    y0 = min(1.0, max(0.0, min(ys) / height))
    y1 = min(1.0, max(0.0, max(ys) / height))
    if x1 - x0 < 0.04:
        mid = (x0 + x1) / 2
        x0, x1 = mid - 0.02, mid + 0.02
    if y1 - y0 < 0.04:
        mid = (y0 + y1) / 2
        y0, y1 = mid - 0.02, mid + 0.02
    return _clean_bbox([x0, y0, x1, y1])


def _issues_from_checks(
    checks: list[dict[str, str]],
    state: GeometricEvidenceState,
    reported_ids: set[str],
    *,
    max_issues: int = 6,
) -> list[dict[str, Any]]:
    """Turn missing/wrong checklist statuses into issues the VLM did not raise.

    A missing segment/arc/circle/line is high severity; a missing point is
    medium; a present-but-misplaced object is low.  An ``unclear`` status is
    normally dropped (it neither helps nor hurts the checklist score), but a
    mark that CV *verified* on the original and that the VLM could not locate in
    the render is almost always undrawn, so it becomes a medium missing-element
    issue.  Geometry-agent inference alone is not enough: a mark invented at a
    spurious vertex would otherwise nag the repair loop forever.
    """
    issues: list[dict[str, Any]] = []
    for check in checks:
        status = check["status"]
        if status not in ("missing", "wrong", "unclear"):
            continue
        object_id = check["object_id"]
        if object_id in reported_ids:
            continue
        obj = state.objects.get(object_id)
        if obj is None:
            continue
        if status == "unclear":
            if (
                obj.type != "right_angle"
                or obj.status != "confirmed"
                or not str(obj.source).startswith("cv:")
            ):
                continue
            severity = "medium"
            issue_type = "missing_element"
            description = (
                f"Checklist: right-angle mark {object_id} is verified by CV on the "
                "original but was not located in the render."
            )
            suggestion = "Draw the right-angle square mark at this vertex."
        elif status == "missing":
            severity = "medium" if obj.type == "point" else "high"
            issue_type = "missing_element"
            description = f"Checklist: {obj.type} {object_id} is not visible in the render."
            suggestion = "Add this element back in the TikZ source."
        else:
            severity = "low"
            issue_type = "wrong_position"
            description = f"Checklist: {obj.type} {object_id} is visible but misplaced."
            suggestion = "Move this element to match the original."
        issues.append(
            {
                "type": issue_type,
                "severity": severity,
                "object_ids": [object_id],
                "bbox": _object_bbox(obj, state.image_size),
                "flaky": False,
                "source": "checklist",
                "description": description,
                "suggestion": suggestion,
            }
        )
        if len(issues) >= max_issues:
            break
    return issues


def _normalise_label(text: Any) -> str:
    value = str(text or "").strip()
    value = value.replace("\\prime", "′").replace("'", "′")
    value = value.replace("^", "").replace("{", "").replace("}", "")
    return value.strip()


def _tex_labels(tex: str) -> set[str]:
    """Collect labels drawn in math-mode spans, normalising primes to ′."""
    labels: set[str] = set()
    for match in _MATH_SPAN.finditer(tex or ""):
        body = _normalise_label(match.group(1) or match.group(2) or "")
        for token in _LABEL_TOKEN.finditer(body):
            labels.add(token.group(1) + ("′" if token.group(2) else ""))
    return labels


def _expected_labels(state: GeometricEvidenceState) -> dict[str, tuple[str, str]]:
    """Labels the source should draw, with severity (bound labels are trusted)."""
    expected: dict[str, tuple[str, str]] = {}
    for label, object_id in state.label_bindings.items():
        norm = _normalise_label(label)
        if _LABEL_OK.match(norm):
            expected[norm] = (str(object_id), "high")
    for obj in state.objects.values():
        norm = _normalise_label(obj.label)
        if norm and _LABEL_OK.match(norm) and norm not in expected:
            expected[norm] = (obj.id, "medium")
    return expected


def _mentions_label(text: str, label: str) -> bool:
    base = label.rstrip("′")
    return bool(re.search(rf"(?<![A-Za-z]){re.escape(base)}(?![A-Za-z])", str(text)))


def _label_source_issues(
    issues: list[dict[str, Any]],
    state: GeometricEvidenceState,
    tex: str,
    missing_labels: Iterable[str] = (),
    *,
    max_issues: int = 5,
) -> list[dict[str, Any]]:
    """Confirm labels the VLM says are missing by checking the TikZ source.

    The check is deliberately corroboration-gated. CV label text is OCR and
    does misread glyphs (e.g. ``G`` bound as ``U``), so a CV-only mismatch
    would send the repair agent chasing a ghost label. A label becomes an
    issue only when the VLM already listed it in ``labels.missing`` and the
    source really never draws it. Skipped when the tex is empty.
    """
    if not str(tex or "").strip():
        return []
    corroborated = {_normalise_label(label) for label in missing_labels}
    if not corroborated:
        return []
    drawn = _tex_labels(tex)
    expected = _expected_labels(state)
    if not expected:
        return []
    texts = [str(issue.get("description", "")) for issue in issues]
    out: list[dict[str, Any]] = []
    ordered = sorted(expected.items(), key=lambda item: (item[1][1] != "high", item[0]))
    for label, (object_id, severity) in ordered:
        if label not in corroborated or label in drawn:
            continue
        if any(_mentions_label(text, label) for text in texts):
            continue
        latex_label = label.replace("′", "'")
        out.append(
            {
                "type": "label_error",
                "severity": severity,
                "object_ids": [object_id] if object_id else [],
                "bbox": None,
                "flaky": False,
                "source": "tikz_source_check",
                "description": (
                    f"TikZ source check: label {label} is expected but never drawn in the .tex."
                ),
                "suggestion": (
                    f"Add a node with {{\\({latex_label}\\)}} at the correct vertex."
                ),
            }
        )
        if len(out) >= max_issues:
            break
    return out


def _sanitise(
    report: dict[str, Any],
    prior_reports: Iterable[dict[str, Any]] = (),
    *,
    state: GeometricEvidenceState | None = None,
    tex: str = "",
) -> dict[str, Any]:
    try:
        score = float(report.get("assessment_score", 0.0))
    except (TypeError, ValueError):
        score = 0.0
    score = max(0.0, min(1.0, score))
    issues = []
    for raw in (report.get("issues") or [])[:12]:
        if not isinstance(raw, dict):
            continue
        issue_type = str(raw.get("type", "other"))
        severity = str(raw.get("severity", "medium"))
        raw_ids = raw.get("object_ids")
        object_ids = (
            [str(value)[:64] for value in raw_ids if isinstance(value, (str, int))][:8]
            if isinstance(raw_ids, (list, tuple))
            else []
        )
        bbox = _clean_bbox(raw.get("bbox"))
        issues.append(
            {
                "type": issue_type if issue_type in ISSUE_TYPES else "other",
                "severity": severity if severity in SEVERITIES else "medium",
                "object_ids": object_ids,
                "bbox": bbox,
                "flaky": False,
                "source": "vlm",
                "description": str(raw.get("description", ""))[:500],
                "suggestion": str(raw.get("suggestion", ""))[:500],
            }
        )
    checks: list[dict[str, str]] = []
    checklist_score: float | None = None
    if state is not None:
        checks = _sanitise_checks(report.get("checks"), set(state.objects))
        checklist_score = _checklist_score(checks)
    flaky_count = _mark_flaky(issues, prior_reports)
    labels = report.get("labels") if isinstance(report.get("labels"), dict) else {}
    if state is not None:
        reported_ids = {
            object_id for issue in issues for object_id in issue.get("object_ids") or []
        }
        issues.extend(_issues_from_checks(checks, state, reported_ids))
        issues.extend(
            _label_source_issues(issues, state, tex, labels.get("missing") or [])
        )
    counts = _actionable_counts(issues)
    return {
        "assessment_score": round(score, 3),
        "score_kind": "heuristic visual similarity (not a calibrated probability)",
        "verdict": str(report.get("verdict", ""))[:300],
        "figure_type": report.get("figure_type") if isinstance(report.get("figure_type"), dict) else {},
        "issues": issues,
        "checks": checks,
        "checklist_score": checklist_score,
        "actionable_counts": counts,
        "flaky_count": flaky_count,
        "must_repair": bool(counts["high"] or counts["medium"] or counts["low"] >= 2),
        "matches": [str(m)[:200] for m in (report.get("matches") or [])[:12]],
        "labels": {
            "present": [str(x) for x in (labels.get("present") or [])][:20],
            "missing": [str(x) for x in (labels.get("missing") or [])][:20],
            "extra": [str(x) for x in (labels.get("extra") or [])][:20],
        },
    }


def _content_crop(image: Image.Image, threshold: int = 245) -> Image.Image:
    """Crop to the drawn content so unequal white margins do not skew scale."""
    grey = image.convert("L")
    mask = grey.point(lambda value: 255 if value < threshold else 0)
    bbox = mask.getbbox()
    if not bbox or bbox == (0, 0, image.width, image.height):
        return image
    return image.crop(bbox)


def build_comparison_image(
    original: str | Path,
    render: str | Path,
    out_path: str | Path,
    *,
    panel_px: int = PANEL_PX,
    gap_px: int = GAP_PX,
) -> Path:
    """Compose LEFT=original, RIGHT=render into equally sized square panels.

    Both images are first cropped to their ink bounding box, then scaled so the
    longest side fills the same content box and centred.  Source images keep
    their own white margins while renders are tightly cropped, so scaling the
    full canvases (instead of the drawn content) made the render look larger
    and its strokes heavier.  Content-normalised panels compare at the same
    drawing scale.
    """
    panel_px = max(64, int(panel_px))
    gap_px = max(2, int(gap_px))
    content_px = max(32, round(panel_px * _PANEL_CONTENT))
    canvas = Image.new("RGB", (2 * panel_px + gap_px, panel_px), (255, 255, 255))
    ImageDraw.Draw(canvas).rectangle(
        [panel_px, 0, panel_px + gap_px - 1, panel_px - 1], fill=_SEPARATOR
    )
    for index, path in enumerate((original, render)):
        with Image.open(path) as im:
            im = im.convert("RGB")
            im = _content_crop(im)
            scale = min(content_px / im.width, content_px / im.height)
            size = (max(1, round(im.width * scale)), max(1, round(im.height * scale)))
            scaled = im.resize(size, Image.Resampling.LANCZOS)
        x0 = index * (panel_px + gap_px) + (panel_px - size[0]) // 2
        y0 = (panel_px - size[1]) // 2
        canvas.paste(scaled, (x0, y0))
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out, format="PNG")
    return out


class CriticAgent:
    def __init__(
        self,
        client: LLMClient,
        state: GeometricEvidenceState,
        out_dir: str | Path | None = None,
    ):
        self.client = client
        self.state = state
        self.out_dir = Path(out_dir) if out_dir else None

    def _tex_for(self, render_png: str | Path) -> str:
        """Return the source that produced ``render_png`` (latest as fallback)."""
        try:
            target = Path(render_png).resolve()
        except OSError:
            target = None
        for version in reversed(self.state.tikz_versions):
            if not version.png_path:
                continue
            try:
                if target is not None and Path(version.png_path).resolve() == target:
                    return version.tex
            except OSError:
                continue
        latest = self.state.latest_version()
        return latest.tex if latest is not None else (self.state.current_tikz or "")

    def run(
        self,
        original_image: str | Path,
        render_png: str | Path,
        *,
        focus: str = "",
        version: int | None = None,
    ) -> dict[str, Any]:
        comparison: Path | None = None
        if self.out_dir is not None:
            try:
                comparison = build_comparison_image(
                    original_image,
                    render_png,
                    self.out_dir / "critic" / f"compare_v{version or 0}.png",
                )
            except Exception:
                comparison = None
        if comparison is not None:
            images = [comparison]
            layout = (
                "SINGLE IMAGE: a side-by-side comparison. The LEFT panel is the "
                "ORIGINAL figure; the RIGHT panel is the RENDERED TIKZ output. "
                "Both panels have the same pixel size and the same scale."
            )
        else:
            images = [original_image, render_png]
            layout = "ORIGINAL IMAGE is the first image; RENDERED TIKZ is the second image."

        checklist = _build_checklist(self.state)
        checklist_text = ""
        if checklist:
            items = "\n".join(f"- {item['object_id']}: {item['hint']}" for item in checklist)
            checklist_text = (
                "CHECKLIST (return one item in \"checks\" for every id):\n"
                f"{items}\n\n"
            )
        summary = self.state.summary(max_objects=30, max_chars=5000)
        user = (
            f"{layout}\n"
            f"FOCUS: {focus or 'overall faithfulness'}\n"
            f"VERSION: {version}\n"
            f"{topology_block(self.state)}\n"
            f"GENERATED TIKZ SOURCE (verify actual paths and shared endpoints):\n{self._tex_for(render_png)[:7000]}\n\n"
            f"GEOMETRY STATE (for reference):\n{summary}\n\n"
            f"{checklist_text}"
            "Return only the JSON critique."
        )
        report = self.client.complete_json(
            CRITIC_SYSTEM,
            user,
            images=images,
            tag="critic_agent",
            max_tokens=8192,
        )
        clean = _sanitise(
            report,
            self.state.critic_reports,
            state=self.state,
            tex=self._tex_for(render_png),
        )
        labels = clean["labels"]
        if (
            not clean["verdict"]
            and not clean["checks"]
            and not clean["issues"]
            and not (labels["present"] or labels["missing"] or labels["extra"])
        ):
            raise ValueError(
                "critic returned an empty critique (no verdict, issues, checks, or labels)"
            )
        clean["version"] = version
        clean["raw_meta"] = compact_json(
            {k: v for k, v in report.items() if k not in clean}, 1000
        )
        return clean
