from __future__ import annotations

from pathlib import Path

import pytest

from geoagent.cv_tools.registry import call_cv_tool


@pytest.fixture(scope="module")
def circles_payload(tmp_path_factory, semicircle_item):
    out = tmp_path_factory.mktemp("cv_circles")
    result = call_cv_tool("detect_circles", {}, image_path=semicircle_item.image_path, out_dir=out)
    assert result["ok"], result.get("error")
    return result["results"]


@pytest.fixture(scope="module")
def lines_payload(tmp_path_factory, semicircle_item):
    out = tmp_path_factory.mktemp("cv_lines")
    result = call_cv_tool("detect_lines", {}, image_path=semicircle_item.image_path, out_dir=out)
    assert result["ok"], result.get("error")
    return result["results"]


@pytest.fixture(scope="module")
def binding_payload(tmp_path_factory, semicircle_item):
    out = tmp_path_factory.mktemp("cv_bind")
    result = call_cv_tool("bind_point_labels", {}, image_path=semicircle_item.image_path, out_dir=out)
    assert result["ok"], result.get("error")
    return result["results"]


def test_circle_detection_finds_semicircle(circles_payload) -> None:
    circles = circles_payload["circles"]
    assert len(circles) == 1
    arc = circles[0]
    cx, cy = arc["center_px"]
    assert abs(cx - 287) < 6 and abs(cy - 301) < 6
    assert abs(arc["radius_px"] - 237) < 6
    assert arc["full_circle"] is False
    # Only the upper half is inked, with a little spill-over past 0/360 degrees.
    assert 170 <= arc["visible_span_deg"] <= 210


def test_line_detection_finds_four_solid_segments(lines_payload) -> None:
    segments = lines_payload["segments"]
    assert len(segments) == 4
    assert all(seg["style"] == "solid" for seg in segments)
    lengths = sorted(round(seg["length_px"]) for seg in segments)
    assert lengths[-1] == pytest.approx(471, abs=8)  # diameter MN
    assert lengths[0] > 150


def test_label_binding_returns_expected_letters(binding_payload) -> None:
    chars = {binding["char"] for binding in binding_payload["bindings"]}
    assert chars == {"P", "A", "B", "O", "M", "N"}
    assert len(binding_payload["points"]) == 6
    assert not binding_payload["unmatched_labels"]
    point_ids = {point["id"] for point in binding_payload["points"]}
    assert all(binding["point_id"] in point_ids for binding in binding_payload["bindings"])


def test_unknown_tool_returns_error(tmp_path) -> None:
    result = call_cv_tool("does_not_exist", {}, image_path=tmp_path / "x.png", out_dir=tmp_path)
    assert result["ok"] is False
    assert "unknown" in result["error"].lower()


def _write_dashed_perpendicular(path: Path, with_square: bool) -> None:
    """Solid horizontal line crossed by a dashed vertical arm at (180, 100)."""
    from PIL import Image, ImageDraw

    image = Image.new("L", (320, 200), 255)
    draw = ImageDraw.Draw(image)
    draw.line([(40, 100), (260, 100)], fill=0, width=3)
    for y in range(30, 174, 18):  # 11 px dashes with 7 px gaps
        draw.line([(180, y), (180, y + 11)], fill=0, width=3)
    if with_square:
        draw.line([(162, 100), (162, 118)], fill=0, width=3)
        draw.line([(162, 118), (180, 118)], fill=0, width=3)
    image.save(path)


def test_right_angle_fallback_detects_square_on_dashed_arm(tmp_path) -> None:
    image = tmp_path / "dashed_square.png"
    _write_dashed_perpendicular(image, with_square=True)
    result = call_cv_tool("detect_right_angle_marker", {}, image_path=image, out_dir=tmp_path)

    assert result["ok"], result.get("error")
    assert result["results"]["count"] == 1
    vx, vy = result["results"]["markers"][0]["vertex_px"]
    assert abs(vx - 180) < 4 and abs(vy - 100) < 4


def test_right_angle_fallback_ignores_bare_cross(tmp_path) -> None:
    image = tmp_path / "dashed_cross.png"
    _write_dashed_perpendicular(image, with_square=False)
    result = call_cv_tool("detect_right_angle_marker", {}, image_path=image, out_dir=tmp_path)

    assert result["ok"], result.get("error")
    assert result["results"]["count"] == 0
