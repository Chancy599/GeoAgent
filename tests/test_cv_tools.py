from __future__ import annotations

from pathlib import Path

import pytest

from geoagent.cv_tools.registry import call_cv_tool


def test_free_endpoints_bind_visible_labels_without_pulling_junctions():
    from geoagent.cv_tools.label_detection import bind_point_labels
    root=Path(__file__).resolve().parents[1]
    result=bind_point_labels(root/'data/test/image/50_q_fig1.png',visualize=False)
    bindings={b['char']:b['point_px'] for b in result['results']['bindings']}
    assert bindings['P']==pytest.approx([49,349],abs=1)
    assert bindings['Q']==pytest.approx([470,349],abs=1)
    assert bindings['A']==pytest.approx([142,349],abs=1)
    assert result['params']['free_endpoint_candidates']>=2


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


def test_detach_point_dots_drops_filled_dot_not_split_ring() -> None:
    """A centre dot must be detached even when it is the largest component.

    Erasing the line band through a circle-centre "O" splits the letter into
    pieces smaller than the accompanying filled dot, so size rank alone cannot
    identify the dot.
    """
    import numpy as np

    from geoagent.cv_tools.label_detection import _detach_point_dots

    sel = np.zeros((30, 40), bool)
    yy, xx = np.mgrid[0:30, 0:40]
    ring = (np.hypot(xx - 10, yy - 15) >= 6) & (np.hypot(xx - 10, yy - 15) <= 9)
    ring &= ~((xx >= 9) & (xx <= 11))
    sel |= ring
    sel |= np.hypot(xx - 30.5, yy - 14.5) <= 5  # filled dot, larger than each half

    kept = _detach_point_dots(sel, cap_h=20.0)

    assert kept[:, :20].sum() == sel[:, :20].sum()  # letter halves fully kept
    assert not kept[:, 24:].any()  # filled dot removed


def test_style_metrics_convert_pixels_to_points_for_a_fixed_span(monkeypatch) -> None:
    """Stroke width / label size must be expressed relative to the figure span."""
    import numpy as np

    from geoagent.cv_tools import label_detection

    mask = np.zeros((100, 200), np.uint8)
    mask[10:90, 20:180] = 1  # ink bbox 160x80 -> span 160 px
    monkeypatch.setattr(
        label_detection, "_line_suppressed_text", lambda _path: (mask, mask, 2.0, 10.0)
    )

    metrics = label_detection.measure_style_metrics("unused.png", target_span_units=8.0)

    assert metrics["ok"]
    assert metrics["ink_size_px"] == [160, 80]
    assert metrics["span_px"] == 160
    assert metrics["suggested_scale"] == pytest.approx(0.05)
    # 2 px / 160 px * (8 cm in pt) = 2.83 pt
    assert metrics["line_width_pt"] == pytest.approx(2.8)
    # 10 px cap height -> 10/160 * 226.77 / 0.68 = 20.8 pt
    assert metrics["label_font_pt"] == pytest.approx(21.0)
    assert metrics["label_line_pt"] == pytest.approx(25.2)
