import json

import pytest
from shapely.geometry import Polygon

from perforation_settings import (
    PerforationSettings,
    load_perforation_settings,
    save_perforation_settings,
)


def make_settings(
    opening_type="circle", custom_opening=None
) -> PerforationSettings:
    return PerforationSettings(
        width_mm=100.0,
        height_mm=80.0,
        pattern="staggered",
        opening_type=opening_type,
        opening_width_mm=8.0,
        opening_height_mm=4.0,
        polygon_sides=7,
        spacing_mm=12.0,
        spacing_mode="pitch",
        grid_angle_degrees=15.0,
        opening_angle_degrees=30.0,
        outer_margin_mm=2.0,
        inner_margin_mm=3.0,
        perforation_as_block=True,
        custom_opening=custom_opening,
    )


def test_settings_round_trip_preserves_parameters(tmp_path):
    path = tmp_path / "perforation.json"
    settings = make_settings()

    save_perforation_settings(path, settings)

    assert load_perforation_settings(path) == settings


def test_settings_round_trip_preserves_custom_opening_geometry(tmp_path):
    path = tmp_path / "custom.json"
    custom_shape = Polygon(
        [(0, 0), (12, 0), (12, 6), (0, 6)],
        holes=[[(4, 2), (8, 2), (8, 4), (4, 4)]],
    )
    settings = make_settings("custom", custom_shape)

    save_perforation_settings(path, settings)
    loaded = load_perforation_settings(path)

    assert loaded.custom_opening is not None
    assert loaded.custom_opening.equals(custom_shape)
    assert loaded.opening_type == "custom"


def test_settings_reject_unsupported_version(tmp_path):
    path = tmp_path / "future.json"
    path.write_text(json.dumps({"version": 2}), encoding="utf-8")

    with pytest.raises(ValueError, match="Nieobsługiwana wersja"):
        load_perforation_settings(path)


def test_custom_opening_settings_require_geometry():
    with pytest.raises(ValueError, match="nie zawiera własnego kształtu"):
        make_settings("custom")
