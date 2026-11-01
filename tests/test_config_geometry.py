from __future__ import annotations

import pytest

from geoagent.config import GeometrySettings, load_settings
from main import _settings, build_parser

_ENV_NAMES = (
    "GEOAGENT_GEOMETRY_REPAIR",
    "GEOAGENT_RIGHT_ANGLE_RECTIFY",
    "GEOAGENT_RIGHT_ANGLE_MODE",
    "GEOAGENT_GEOM_REPAIR_MAX_RELATIONS",
    "GEOAGENT_GEOM_REPAIR_ANGLE_TOL_DEG",
    "GEOAGENT_GEOM_REPAIR_EQ_TOL",
    "GEOAGENT_GEOM_REPAIR_COLLINEAR_ANGLE_TOL_DEG",
    "GEOAGENT_GEOM_REPAIR_COLLINEAR_PX",
    "GEOAGENT_GEOM_REPAIR_MAX_SHIFT_PX",
    "GEOAGENT_GEOM_REPAIR_MAX_DISP_FRAC",
    "GEOAGENT_GEOM_REPAIR_ITERS",
    "GEOAGENT_GEOM_REPAIR_DAMP",
    "GEOAGENT_GEOM_POINT_WRITEBACK",
    "GEOAGENT_GEOM_POINT_TRUST_FRAC",
)


@pytest.fixture()
def clean_env(monkeypatch):
    for name in _ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def test_geometry_repair_is_enabled_by_default(clean_env) -> None:
    settings = load_settings()
    assert settings.geometry == GeometrySettings()
    assert settings.geometry.enabled is True
    assert settings.geometry.repair_stage == "post_tikz"
    assert settings.geometry.post_max_shift_rel == 0.005
    assert settings.geometry.post_max_length_change_rel == 0.01
    assert settings.geometry.post_topology_tol_rel == 0.003
    assert settings.geometry.post_incidence_mode == "snap"
    assert settings.geometry.post_curve_policy == "defer"
    assert settings.geometry.post_length_weight == 0.01
    assert settings.geometry.post_curve_options["relation_types"] == ["parallel"]
    assert settings.geometry.rectify_enabled is True
    # The selected scheme owns right angles softly and caps a point object's
    # snap to 0.2 % of the nearest point gap.
    assert settings.geometry.right_angle_mode == "soft"
    assert settings.geometry.point_writeback == "trust"
    assert settings.geometry.point_trust_frac == 0.002
    assert settings.geometry.angle_tol_deg == 0.5
    assert settings.geometry.equal_length_rel_tol == 0.002
    assert settings.geometry.collinear_angle_tol_deg == 0.5
    assert settings.geometry.collinear_tolerance_px == 1.0
    assert settings.geometry.max_shift_px == 2.0
    assert settings.public_dict()["geometry"]["enabled"] is True


def test_env_enables_repair_and_overrides_numbers(clean_env) -> None:
    clean_env.setenv("GEOAGENT_GEOMETRY_REPAIR", "true")
    clean_env.setenv("GEOAGENT_GEOM_REPAIR_ANGLE_TOL_DEG", "1.0")
    clean_env.setenv("GEOAGENT_GEOM_REPAIR_MAX_RELATIONS", "12")

    settings = load_settings()

    assert settings.geometry.enabled is True
    assert settings.geometry.angle_tol_deg == 1.0
    assert settings.geometry.max_relations == 12


def test_run_override_beats_env(clean_env) -> None:
    clean_env.setenv("GEOAGENT_GEOMETRY_REPAIR", "false")

    assert load_settings({"geometry_repair": True}).geometry.enabled is True
    assert load_settings({"geometry_repair": False}).geometry.enabled is False


def test_rectify_can_be_disabled(clean_env) -> None:
    clean_env.setenv("GEOAGENT_RIGHT_ANGLE_RECTIFY", "false")
    assert load_settings().geometry.rectify_enabled is False
    assert load_settings({"rectify": True}).geometry.rectify_enabled is True
    assert load_settings({"rectify": False}).geometry.rectify_enabled is False


def test_right_angle_mode_env_and_override(clean_env) -> None:
    clean_env.setenv("GEOAGENT_RIGHT_ANGLE_MODE", "soft")
    assert load_settings().geometry.right_angle_mode == "soft"
    assert load_settings({"right_angle_mode": "ignore"}).geometry.right_angle_mode == "ignore"

    parser = build_parser()
    soft = parser.parse_args(["run", "--image", "x.png", "--right-angle-mode", "soft"])
    default = parser.parse_args(["run", "--image", "x.png"])
    assert soft.right_angle_mode == "soft"
    assert default.right_angle_mode is None
    assert _settings(soft).geometry.right_angle_mode == "soft"


def test_cli_boolean_switch_is_two_way(clean_env) -> None:
    parser = build_parser()

    enabled = parser.parse_args(["run", "--image", "x.png", "--geometry-repair"])
    disabled = parser.parse_args(["run", "--image", "x.png", "--no-geometry-repair"])
    no_rectify = parser.parse_args(["run", "--image", "x.png", "--no-right-angle-rectify"])
    default = parser.parse_args(["run", "--image", "x.png"])

    assert enabled.geometry_repair is True
    assert disabled.geometry_repair is False
    assert default.geometry_repair is None
    assert _settings(enabled).geometry.enabled is True
    assert _settings(disabled).geometry.enabled is False
    assert _settings(default).geometry.enabled is True
    assert no_rectify.right_angle_rectify is False
    assert _settings(no_rectify).geometry.rectify_enabled is False
    assert _settings(default).geometry.rectify_enabled is True


def test_batch_exposes_the_same_switch(clean_env) -> None:
    parser = build_parser()
    args = parser.parse_args(["batch", "--limit", "2", "--geometry-repair"])
    assert args.geometry_repair is True
    assert args.right_angle_rectify is None
    assert args.workers == 4
    assert args.skip_existing is False
    no_rectify = parser.parse_args(["batch", "--limit", "2", "--no-right-angle-rectify"])
    assert _settings(no_rectify).geometry.rectify_enabled is False
