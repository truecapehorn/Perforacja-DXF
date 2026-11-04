from __future__ import annotations

import json
import math
import sys
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class AppConfig:
    preview_debounce_ms: int = 2000
    opening_type: str = "circle"
    opening_width_mm: float = 10.0
    opening_height_mm: float = 10.0
    polygon_sides: int = 6
    layout_mode: str = "grid"
    pattern: str = "square"
    spacing_mode: str = "gap"
    horizontal_spacing_mm: float = 10.0
    vertical_spacing_mm: float = 10.0
    grid_angle_degrees: float = 0.0
    opening_angle_degrees: float = 0.0
    outer_margin_mm: float = 10.0
    inner_margin_mm: float = 10.0
    randomize_width: bool = True
    randomize_height: bool = False
    randomize_horizontal_gap: bool = False
    randomize_vertical_gap: bool = False
    random_min_width_mm: float = 10.0
    random_max_width_mm: float = 20.0
    random_min_height_mm: float = 10.0
    random_max_height_mm: float = 20.0
    random_min_horizontal_gap_mm: float = 2.0
    random_max_horizontal_gap_mm: float = 8.0
    random_min_vertical_gap_mm: float = 2.0
    random_max_vertical_gap_mm: float = 8.0
    perforation_as_block: bool = False
    show_source_preview: bool = True
    show_grid: bool = True


_NUMERIC_RANGES = {
    "opening_width_mm": (0.1, 5000.0),
    "opening_height_mm": (0.1, 5000.0),
    "horizontal_spacing_mm": (0.0, 10_000.0),
    "vertical_spacing_mm": (0.0, 10_000.0),
    "grid_angle_degrees": (-180.0, 180.0),
    "opening_angle_degrees": (-180.0, 180.0),
    "outer_margin_mm": (0.0, 5000.0),
    "inner_margin_mm": (0.0, 5000.0),
    "random_min_width_mm": (0.1, 5000.0),
    "random_max_width_mm": (0.1, 5000.0),
    "random_min_height_mm": (0.1, 5000.0),
    "random_max_height_mm": (0.1, 5000.0),
    "random_min_horizontal_gap_mm": (0.0, 10_000.0),
    "random_max_horizontal_gap_mm": (0.0, 10_000.0),
    "random_min_vertical_gap_mm": (0.0, 10_000.0),
    "random_max_vertical_gap_mm": (0.0, 10_000.0),
}
_BOOLEAN_FIELDS = {
    "randomize_width",
    "randomize_height",
    "randomize_horizontal_gap",
    "randomize_vertical_gap",
    "perforation_as_block",
    "show_source_preview",
    "show_grid",
}
_STRING_CHOICES = {
    "opening_type": {
        "circle",
        "square",
        "rectangle",
        "triangle",
        "ellipse",
        "slot",
        "regular_polygon",
    },
    "layout_mode": {"grid", "random"},
    "pattern": {"square", "staggered"},
    "spacing_mode": {"gap", "pitch"},
}
_RANGE_PAIRS = (
    ("random_min_width_mm", "random_max_width_mm"),
    ("random_min_height_mm", "random_max_height_mm"),
    ("random_min_horizontal_gap_mm", "random_max_horizontal_gap_mm"),
    ("random_min_vertical_gap_mm", "random_max_vertical_gap_mm"),
)
_CONFIG_FIELDS = {field.name for field in fields(AppConfig)}


def app_config_path() -> Path:
    """Return the editable configuration path beside the application."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().with_name("app_config.json")
    return Path(__file__).resolve().with_name("app_config.json")


def load_app_config(path: str | Path | None = None) -> AppConfig:
    config_path = Path(path) if path is not None else app_config_path()
    with config_path.open(encoding="utf-8") as config_file:
        values: Any = json.load(config_file)
    if not isinstance(values, dict):
        raise ValueError("Główny element app_config.json musi być obiektem JSON.")

    unknown_fields = set(values) - _CONFIG_FIELDS
    if unknown_fields:
        names = ", ".join(sorted(unknown_fields))
        raise ValueError(f"Nieznane pola w app_config.json: {names}.")

    config = AppConfig(**values)
    if (
        isinstance(config.preview_debounce_ms, bool)
        or not isinstance(config.preview_debounce_ms, int)
        or not 0 <= config.preview_debounce_ms <= 60_000
    ):
        raise ValueError(
            "preview_debounce_ms musi być liczbą całkowitą od 0 do 60000."
        )
    if (
        isinstance(config.polygon_sides, bool)
        or not isinstance(config.polygon_sides, int)
        or not 3 <= config.polygon_sides <= 20
    ):
        raise ValueError("polygon_sides musi być liczbą całkowitą od 3 do 20.")

    for name, (minimum, maximum) in _NUMERIC_RANGES.items():
        value = getattr(config, name)
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or (isinstance(value, float) and not math.isfinite(value))
            or not minimum <= value <= maximum
        ):
            raise ValueError(
                f"{name} musi mieścić się w zakresie {minimum}–{maximum}."
            )
    for name in _BOOLEAN_FIELDS:
        if not isinstance(getattr(config, name), bool):
            raise ValueError(f"{name} musi mieć wartość true albo false.")
    for name, choices in _STRING_CHOICES.items():
        value = getattr(config, name)
        if not isinstance(value, str) or value not in choices:
            allowed = ", ".join(sorted(choices))
            raise ValueError(f"{name} musi mieć jedną z wartości: {allowed}.")
    for minimum_name, maximum_name in _RANGE_PAIRS:
        if getattr(config, minimum_name) > getattr(config, maximum_name):
            raise ValueError(
                f"{minimum_name} nie może być większe niż {maximum_name}."
            )
    if config.spacing_mode == "pitch" and (
        config.horizontal_spacing_mm <= 0
        or config.vertical_spacing_mm <= 0
    ):
        raise ValueError(
            "Przy spacing_mode=pitch oba odstępy muszą być większe od zera."
        )
    return config
