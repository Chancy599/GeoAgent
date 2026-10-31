from __future__ import annotations

from pathlib import Path

import pytest

from PIL import Image

from geoagent.agents.critic_agent import (
    CriticAgent,
    _build_checklist,
    _checklist_score,
    _expected_labels,
    _object_bbox,
    _tex_labels,
    build_comparison_image,
)
from geoagent.state.schemas import GeometricEvidenceState, GeometryObject


def _solid(path: Path, size: tuple[int, int], colour: tuple[int, int, int]) -> Path:
    Image.new("RGB", size, colour).save(path)
    return path


def test_comparison_panels_have_equal_size_and_original_on_the_left(tmp_path: Path) -> None:
    original = _solid(tmp_path / "original.png", (200, 100), (255, 0, 0))
    render = _solid(tmp_path / "render.png", (100, 200), (0, 0, 255))

    out = build_comparison_image(original, render, tmp_path / "compare.png", panel_px=100, gap_px=10)
    with Image.open(out) as im:
        assert im.size == (210, 100)
        assert im.getpixel((50, 50)) == (255, 0, 0)      # left panel, centred original
        assert im.getpixel((160, 50)) == (0, 0, 255)     # right panel, centred render
        assert im.getpixel((105, 50)) == (225, 225, 225)  # separator
        assert im.getpixel((50, 5)) == (255, 255, 255)   # letterbox padding


def _colour_bbox(im: Image.Image, panel_x0: int, panel_x1: int, colour: tuple[int, int, int]):
    pixels = im.load()
    xs: list[int] = []
    ys: list[int] = []
    for y in range(im.height):
        for x in range(panel_x0, panel_x1):
            if pixels[x, y] == colour:
                xs.append(x)
                ys.append(y)
    assert xs and ys
    return max(xs) - min(xs) + 1, max(ys) - min(ys) + 1


def test_comparison_scales_drawn_content_not_white_margins(tmp_path: Path) -> None:
    """Equal content must end up equally large even when canvases differ."""
    original = Image.new("RGB", (200, 200), "white")
    original.paste((255, 0, 0), (50, 50, 150, 150))  # 100x100 ink
    original_path = tmp_path / "original.png"
    original.save(original_path)

    render = Image.new("RGB", (300, 150), "white")
    render.paste((0, 0, 255), (200, 40, 250, 90))  # also 50x50, different margin
    render_path = tmp_path / "render.png"
    render.save(render_path)

    out = build_comparison_image(original_path, render_path, tmp_path / "compare.png", panel_px=200, gap_px=10)
    with Image.open(out) as im:
        red = _colour_bbox(im, 0, 200, (255, 0, 0))
        blue = _colour_bbox(im, 210, 410, (0, 0, 255))
    assert red == (180, 180)
    assert blue == (180, 180)


class _RecordingClient:
    def __init__(self, report: dict) -> None:
        self.report = report
        self.images: list[str] = []
        self.user = ""

    def complete_json(self, system, user, *, images, tag, max_tokens):
        self.user = user
        self.images = [str(p) for p in images]
        return dict(self.report)


def _state(image: Path) -> GeometricEvidenceState:
    return GeometricEvidenceState(
        image_path=str(image),
        image_size={"width": 200, "height": 100},
    )


def test_critic_sends_one_equal_size_comparison_image(tmp_path: Path) -> None:
    original = _solid(tmp_path / "original.png", (200, 100), (255, 0, 0))
    render = _solid(tmp_path / "render.png", (100, 200), (0, 0, 255))
    client = _RecordingClient({"assessment_score": 0.9, "verdict": "close"})

    agent = CriticAgent(client, _state(original), out_dir=tmp_path / "run")
    report = agent.run(original, render, version=3, focus="labels")

    assert len(client.images) == 1
    assert Path(client.images[0]).name == "compare_v3.png"
    assert Path(client.images[0]).is_file()
    assert "LEFT panel is the ORIGINAL" in client.user
    assert "RIGHT panel is the RENDERED" in client.user
    assert report["version"] == 3
    assert report["assessment_score"] == 0.9


def test_critic_falls_back_to_two_images_without_out_dir(tmp_path: Path) -> None:
    original = _solid(tmp_path / "original.png", (200, 100), (255, 0, 0))
    render = _solid(tmp_path / "render.png", (100, 200), (0, 0, 255))
    client = _RecordingClient({"assessment_score": 0.8, "verdict": "ok"})

    agent = CriticAgent(client, _state(original), out_dir=None)
    agent.run(original, render, version=1)

    assert client.images == [str(original), str(render)]
    assert "first image" in client.user


def _run_report(
    tmp_path: Path,
    report: dict,
    *,
    prior: list[dict] | None = None,
    version: int = 2,
    objects: list[dict] | None = None,
    bindings: dict[str, str] | None = None,
    tex: str = "",
) -> dict:
    original = _solid(tmp_path / "original.png", (200, 100), (255, 0, 0))
    render = _solid(tmp_path / "render.png", (200, 100), (0, 0, 255))
    state = _state(original)
    for item in objects or []:
        state.add_object(item)
    if bindings:
        state.label_bindings.update(bindings)
    if tex:
        state.add_tikz_version(tex, agent="test", mode="generate")
    for item in prior or []:
        state.critic_reports.append(item)
    agent = CriticAgent(_RecordingClient(report), state, out_dir=None)
    return agent.run(original, render, version=version)


def test_critic_keeps_issue_object_ids_and_bbox(tmp_path: Path) -> None:
    report = {
        "assessment_score": 0.9,
        "issues": [
            {
                "type": "missing_element",
                "severity": "high",
                "object_ids": ["seg_MN", "arc_MNP"],
                "bbox": [0.1, 0.2, 0.6, 0.7],
                "description": "segment MN is absent",
                "suggestion": "draw (M) -- (N);",
            }
        ],
    }
    out = _run_report(tmp_path, report)

    issue = out["issues"][0]
    assert issue["object_ids"] == ["seg_MN", "arc_MNP"]
    assert issue["bbox"] == [0.1, 0.2, 0.6, 0.7]
    assert issue["flaky"] is False
    assert out["must_repair"] is True
    assert out["actionable_counts"] == {"high": 1, "medium": 0, "low": 0}


def test_critic_drops_invalid_bbox(tmp_path: Path) -> None:
    report = {
        "issues": [
            {
                "type": "label_error",
                "severity": "low",
                "object_ids": "P",
                "bbox": [2.0, 0.1, 0.2, 0.3],
                "description": "P sits too far left",
                "suggestion": "move the node right",
            }
        ]
    }
    out = _run_report(tmp_path, report)

    issue = out["issues"][0]
    assert issue["bbox"] is None
    assert issue["object_ids"] == []  # a bare string is not an id list


def test_critic_marks_reversed_style_verdict_as_flaky(tmp_path: Path) -> None:
    prior = [
        {
            "version": 1,
            "issues": [
                {
                    "type": "wrong_style",
                    "severity": "medium",
                    "description": "All strokes are rendered noticeably thicker than the original.",
                }
            ],
        }
    ]
    report = {
        "assessment_score": 0.9,
        "issues": [
            {
                "type": "wrong_style",
                "severity": "medium",
                "description": "The strokes are too thin compared with the original.",
                "suggestion": "Use a heavier line width.",
            }
        ],
    }
    out = _run_report(tmp_path, report, prior=prior)

    issue = out["issues"][0]
    assert issue["flaky"] is True
    assert "v1" in issue["flaky_reason"]
    assert out["flaky_count"] == 1
    assert out["actionable_counts"] == {"high": 0, "medium": 0, "low": 0}
    assert out["must_repair"] is False


def test_single_low_issue_does_not_require_repair(tmp_path: Path) -> None:
    report = {
        "issues": [
            {
                "type": "label_error",
                "severity": "low",
                "description": "Label E touches segment BE.",
                "suggestion": "move E slightly away",
            }
        ]
    }
    out = _run_report(tmp_path, report)
    assert out["actionable_counts"]["low"] == 1
    assert out["must_repair"] is False


def test_two_low_issues_require_repair(tmp_path: Path) -> None:
    report = {
        "issues": [
            {"type": "label_error", "severity": "low", "description": "Label E touches BE."},
            {"type": "other", "severity": "low", "description": "Extra filled dot at O."},
        ]
    }
    out = _run_report(tmp_path, report)
    assert out["must_repair"] is True


def test_low_aspect_ratio_note_is_informational(tmp_path: Path) -> None:
    report = {
        "issues": [
            {
                "type": "other",
                "severity": "low",
                "description": "Overall aspect ratio differs: the render is wider, so the figure is scaled, not warped.",
            }
        ]
    }
    out = _run_report(tmp_path, report)
    assert out["actionable_counts"]["low"] == 0
    assert out["must_repair"] is False


def test_low_panel_scale_note_is_informational(tmp_path: Path) -> None:
    report = {
        "issues": [
            {
                "type": "layout_error",
                "severity": "low",
                "description": "Render panel is scaled up relative to the original (~10% larger).",
                "suggestion": "",
            }
        ]
    }
    out = _run_report(tmp_path, report)
    assert out["actionable_counts"]["low"] == 0
    assert out["must_repair"] is False


_SEG_MN = {"id": "seg_MN", "type": "segment", "coords": {"a_px": [10, 80], "b_px": [190, 80]}}
_POINT_A = {"id": "point_A", "type": "point", "label": "A", "coords": {"px": [100, 20]}}


def test_checklist_prioritises_structure_and_skips_unlabelled_points(tmp_path: Path) -> None:
    state = _state(tmp_path / "img.png")
    for item in (
        _POINT_A,
        _SEG_MN,
        {"id": "point_X", "type": "point", "coords": {"px": [10, 10]}},
        {"id": "point_G", "type": "point", "label": "G", "status": "rejected", "coords": {}},
        {"id": "label_B", "type": "label", "label": "B", "coords": {}},
    ):
        state.add_object(item)

    checklist = _build_checklist(state)
    assert [entry["object_id"] for entry in checklist] == ["seg_MN", "point_A"]


def test_missing_checklist_segment_becomes_high_issue(tmp_path: Path) -> None:
    report = {
        "assessment_score": 0.9,
        "checks": [
            {"object_id": "seg_MN", "status": "missing", "note": "not drawn"},
            {"object_id": "point_A", "status": "present"},
            {"object_id": "ghost_id", "status": "missing"},
        ],
    }
    out = _run_report(tmp_path, report, objects=[_SEG_MN, _POINT_A])

    assert [check["object_id"] for check in out["checks"]] == ["seg_MN", "point_A"]
    assert out["checklist_score"] == 0.5
    issue = out["issues"][0]
    assert issue["source"] == "checklist"
    assert issue["severity"] == "high"
    assert issue["object_ids"] == ["seg_MN"]
    assert issue["bbox"] is not None
    assert out["actionable_counts"]["high"] == 1
    assert out["must_repair"] is True


def test_checklist_issue_is_skipped_when_vlm_already_named_the_object(tmp_path: Path) -> None:
    report = {
        "issues": [
            {
                "type": "missing_element",
                "severity": "high",
                "object_ids": ["seg_MN"],
                "description": "The diameter MN is absent.",
            }
        ],
        "checks": [{"object_id": "seg_MN", "status": "missing"}],
    }
    out = _run_report(tmp_path, report, objects=[_SEG_MN])

    assert [issue["source"] for issue in out["issues"]] == ["vlm"]
    assert out["actionable_counts"]["high"] == 1
    assert out["checklist_score"] == 0.0


def test_wrong_checklist_object_is_low_severity(tmp_path: Path) -> None:
    report = {"checks": [{"object_id": "seg_MN", "status": "wrong"}]}
    out = _run_report(tmp_path, report, objects=[_SEG_MN])

    issue = out["issues"][0]
    assert issue["type"] == "wrong_position"
    assert issue["severity"] == "low"
    assert out["must_repair"] is False  # a single low issue is informational
    assert out["checklist_score"] == 0.5


def test_unclear_checks_are_excluded_from_score(tmp_path: Path) -> None:
    report = {
        "checks": [
            {"object_id": "seg_MN", "status": "present"},
            {"object_id": "point_A", "status": "unclear"},
        ]
    }
    out = _run_report(tmp_path, report, objects=[_SEG_MN, _POINT_A])
    assert out["checklist_score"] == 1.0


def test_tex_label_scan_normalises_primes() -> None:
    tex = r"\node at (0,0) {$A$};\node at (1,0) {$C^{\prime}$};"
    assert _tex_labels(tex) == {"A", "C′"}


def test_tex_label_scan_ignores_math_commands() -> None:
    assert _tex_labels(r"\draw (0,0) arc[start angle=90]; $90^\circ$; $\alpha$") == set()


def test_expected_labels_prefers_bound_labels() -> None:
    state = GeometricEvidenceState(image_path="x.png", image_size={"width": 10, "height": 10})
    state.add_object(_POINT_A)
    state.add_object({"id": "point_B", "type": "point", "label": "B", "coords": {}})
    state.label_bindings["B"] = "point_B"
    state.add_object({"id": "point_X2", "type": "point", "label": "A_1", "coords": {}})

    expected = _expected_labels(state)
    assert expected["B"] == ("point_B", "high")
    assert expected["A"] == ("point_A", "medium")
    assert "A_1" not in expected


def test_source_check_flags_vlm_confirmed_label_missing_from_tex(tmp_path: Path) -> None:
    report = {"assessment_score": 0.95, "labels": {"missing": ["P"]}}
    out = _run_report(
        tmp_path,
        report,
        objects=[
            {"id": "point_P", "type": "point", "label": "P", "coords": {"px": [100, 40]}},
            _POINT_A,
        ],
        bindings={"P": "point_P"},
        tex=r"\node at (0,0) {$A$};",
    )

    issue = out["issues"][0]
    assert issue["source"] == "tikz_source_check"
    assert issue["type"] == "label_error"
    assert issue["severity"] == "high"
    assert issue["object_ids"] == ["point_P"]
    assert out["must_repair"] is True


def test_source_check_accepts_prime_and_skips_empty_tex(tmp_path: Path) -> None:
    objects = [{"id": "point_C", "type": "point", "label": "C'", "coords": {"px": [50, 50]}}]
    report = {"labels": {"missing": ["C'"]}}
    drawn = _run_report(
        tmp_path,
        report,
        objects=objects,
        bindings={"C'": "point_C"},
        tex=r"\node at (0,0) {$C^{\prime}$};",
    )
    assert drawn["issues"] == []

    empty = _run_report(tmp_path, report, objects=objects, bindings={"C'": "point_C"}, tex="")
    assert empty["issues"] == []


def test_source_check_does_not_manufacture_missing_labels(tmp_path: Path) -> None:
    # Archived 6220 run: CV bound a label "U" that was really the letter G, and
    # the render was faithful. Without VLM corroboration the source check must
    # stay silent, otherwise repair would chase a ghost label.
    report = {"assessment_score": 0.96, "labels": {"missing": [], "present": ["G"]}}
    out = _run_report(
        tmp_path,
        report,
        objects=[{"id": "point_U", "type": "point", "label": "U", "coords": {"px": [100, 40]}}],
        bindings={"U": "point_U"},
        tex=r"\node at (0,0) {$G$};",
    )
    assert out["issues"] == []
    assert out["must_repair"] is False


def test_source_check_skips_label_already_mentioned_by_vlm(tmp_path: Path) -> None:
    report = {
        "issues": [
            {
                "type": "label_error",
                "severity": "high",
                "description": "Label P is missing from the render.",
                "suggestion": "add P",
            }
        ],
        "labels": {"missing": ["P"]},
    }
    out = _run_report(
        tmp_path,
        report,
        objects=[{"id": "point_P", "type": "point", "label": "P", "coords": {"px": [100, 40]}}],
        bindings={"P": "point_P"},
        tex=r"\node at (0,0) {$A$};",
    )

    assert [issue["source"] for issue in out["issues"]] == ["vlm"]


def test_object_bbox_clamps_a_circle_that_overflows_the_image() -> None:
    arc = GeometryObject(
        id="arc_01",
        type="arc",
        coords={"center_px": [100, 50], "radius_px": 60},
    )
    assert _object_bbox(arc, {"width": 200, "height": 100}) == [0.2, 0.0, 0.8, 1.0]

    segment = GeometryObject(
        id="seg_01",
        type="segment",
        coords={"a_px": [10, 80], "b_px": [190, 80]},
    )
    assert _object_bbox(segment, {"width": 200, "height": 100}) == [0.05, 0.78, 0.95, 0.82]
    assert _object_bbox(segment, {}) is None


def test_checklist_score_helper_handles_no_checks() -> None:
    assert _checklist_score([]) is None
    assert _checklist_score([{"object_id": "x", "status": "unclear", "note": ""}]) is None


def test_empty_critique_is_an_error_not_a_zero_score(tmp_path: Path) -> None:
    # A truncated reply previously sanitised into score 0.0 with no issues and
    # was accepted as a scored version; it must now surface as an error.
    with pytest.raises(ValueError, match="empty critique"):
        _run_report(tmp_path, {})
