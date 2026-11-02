import json
from dataclasses import replace

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
    assert "target_open_area_percentage" not in json.loads(
        path.read_text(encoding="utf-8")
    )


def test_random_settings_round_trip_preserves_generation_options(tmp_path):
    path = tmp_path / "random.json"
    settings = replace(
        make_settings(),
        layout_mode="random",
        randomize_width=True,
        randomize_height=True,
        randomize_horizontal_gap=True,
        randomize_vertical_gap=True,
        random_min_width_mm=6.0,
        random_max_width_mm=18.0,
        random_min_height_mm=3.0,
        random_max_height_mm=9.0,
        random_min_horizontal_gap_mm=1.5,
        random_max_horizontal_gap_mm=4.5,
        random_min_vertical_gap_mm=2.5,
        random_max_vertical_gap_mm=5.5,
        random_seed=12345,
        horizontal_spacing_mm=7.0,
        vertical_spacing_mm=13.0,
    )

    save_perforation_settings(path, settings)

    assert load_perforation_settings(path) == settings


def test_legacy_settings_use_same_horizontal_and_vertical_spacing(tmp_path):
    path = tmp_path / "legacy-spacing.json"
    settings = make_settings()
    save_perforation_settings(path, settings)
    data = json.loads(path.read_text(encoding="utf-8"))
    data.pop("horizontal_spacing_mm")
    data.pop("vertical_spacing_mm")
    path.write_text(json.dumps(data), encoding="utf-8")

    loaded = load_perforation_settings(path)

    assert loaded.horizontal_spacing_mm == settings.spacing_mm
    assert loaded.vertical_spacing_mm == settings.spacing_mm


def test_settings_load_version_one_without_random_options(tmp_path):
    path = tmp_path / "legacy.json"
    settings = make_settings()
    save_perforation_settings(path, settings)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["version"] = 1
    data["target_open_area_percentage"] = 88.0
    for key in (
        "layout_mode",
        "randomize_width",
        "randomize_height",
        "randomize_gap",
        "randomize_horizontal_gap",
        "randomize_vertical_gap",
        "random_min_width_mm",
        "random_max_width_mm",
        "random_min_height_mm",
        "random_max_height_mm",
        "random_min_gap_mm",
        "random_max_gap_mm",
        "random_min_horizontal_gap_mm",
        "random_max_horizontal_gap_mm",
        "random_min_vertical_gap_mm",
        "random_max_vertical_gap_mm",
        "random_seed",
    ):
        data.pop(key, None)
    path.write_text(json.dumps(data), encoding="utf-8")

    loaded = load_perforation_settings(path)

    assert loaded == replace(
        settings,
        random_min_height_mm=settings.opening_height_mm,
        random_max_height_mm=settings.opening_height_mm,
        random_max_vertical_gap_mm=settings.random_min_vertical_gap_mm,
        random_max_horizontal_gap_mm=settings.random_min_horizontal_gap_mm,
    )
    assert loaded.layout_mode == "grid"


def test_settings_migrate_version_two_random_options(tmp_path):
    path = tmp_path / "version_two.json"
    settings = make_settings()
    save_perforation_settings(path, settings)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["version"] = 2
    data["layout_mode"] = "random"
    data["randomize_opening_size"] = False
    data["random_min_size_mm"] = 7.0
    data["random_max_size_mm"] = 17.0
    data["random_min_gap_mm"] = 3.0
    data["randomize_gap"] = True
    for key in (
        "randomize_width",
        "randomize_height",
        "randomize_horizontal_gap",
        "randomize_vertical_gap",
        "random_min_width_mm",
        "random_max_width_mm",
        "random_min_height_mm",
        "random_max_height_mm",
        "random_max_gap_mm",
        "random_min_horizontal_gap_mm",
        "random_max_horizontal_gap_mm",
        "random_min_vertical_gap_mm",
        "random_max_vertical_gap_mm",
    ):
        data.pop(key, None)
    path.write_text(json.dumps(data), encoding="utf-8")

    loaded = load_perforation_settings(path)

    assert loaded.randomize_width is False
    assert loaded.randomize_height is False
    assert loaded.randomize_horizontal_gap is True
    assert loaded.randomize_vertical_gap is True
    assert loaded.random_min_width_mm == 7.0
    assert loaded.random_max_width_mm == 17.0
    assert loaded.random_min_horizontal_gap_mm == 3.0
    assert loaded.random_max_horizontal_gap_mm == 3.0
    assert loaded.random_min_vertical_gap_mm == 3.0
    assert loaded.random_max_vertical_gap_mm == 3.0
    assert loaded.spacing_mm == 3.0


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
    path.write_text(json.dumps({"version": 6}), encoding="utf-8")

    with pytest.raises(ValueError, match="Nieobsługiwana wersja"):
        load_perforation_settings(path)


def test_custom_opening_settings_require_geometry():
    with pytest.raises(ValueError, match="nie zawiera własnego kształtu"):
        make_settings("custom")
