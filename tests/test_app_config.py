import json

import pytest

from app_config import AppConfig, load_app_config


def write_config(tmp_path, values):
    path = tmp_path / "app_config.json"
    path.write_text(json.dumps(values), encoding="utf-8")
    return path


def test_missing_options_keep_their_default_values(tmp_path):
    path = write_config(tmp_path, {"preview_debounce_ms": 1500})

    config = load_app_config(path)

    assert config.preview_debounce_ms == 1500
    assert config.opening_width_mm == AppConfig().opening_width_mm
    assert config.show_grid is True


def test_config_loads_all_default_options_from_project_file():
    config = load_app_config()

    assert config.preview_debounce_ms == 2000
    assert config.pattern == "square"
    assert config.horizontal_spacing_mm == 10.0
    assert config.vertical_spacing_mm == 10.0


@pytest.mark.parametrize(
    ("values", "message"),
    [
        ({"preview_debounce_ms": -1}, "preview_debounce_ms"),
        ({"preview_debounce_ms": True}, "preview_debounce_ms"),
        ({"polygon_sides": 2}, "polygon_sides"),
        ({"show_grid": "yes"}, "show_grid"),
        ({"pattern": "invalid"}, "pattern"),
        ({"opening_width_mm": float("nan")}, "opening_width_mm"),
        (
            {
                "random_min_width_mm": 20,
                "random_max_width_mm": 10,
            },
            "random_min_width_mm",
        ),
        ({"typo_option": 1}, "Nieznane pola"),
    ],
)
def test_invalid_config_values_are_rejected(tmp_path, values, message):
    path = write_config(tmp_path, values)

    with pytest.raises(ValueError, match=message):
        load_app_config(path)


def test_config_must_be_a_json_object(tmp_path):
    path = write_config(tmp_path, ["not", "an", "object"])

    with pytest.raises(ValueError, match="obiektem JSON"):
        load_app_config(path)
