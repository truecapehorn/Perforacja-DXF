from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

from shapely import wkb
from shapely.errors import GEOSException
from shapely.geometry import MultiPolygon, Polygon
from shapely.geometry.base import BaseGeometry

_VERSION = 4
_SUPPORTED_VERSIONS = {1, 2, 3, 4}
_PATTERNS = {"square", "staggered"}
_LAYOUT_MODES = {"grid", "random"}
_OPENING_TYPES = {
    "circle",
    "square",
    "rectangle",
    "triangle",
    "ellipse",
    "slot",
    "regular_polygon",
    "custom",
}
_SPACING_MODES = {"gap", "pitch"}


@dataclass(frozen=True)
class PerforationSettings:
    width_mm: float
    height_mm: float
    pattern: str
    opening_type: str
    opening_width_mm: float
    opening_height_mm: float
    polygon_sides: int
    spacing_mm: float
    spacing_mode: str
    grid_angle_degrees: float
    opening_angle_degrees: float
    outer_margin_mm: float
    inner_margin_mm: float
    perforation_as_block: bool
    custom_opening: BaseGeometry | None = None
    layout_mode: str = "grid"
    target_open_area_percentage: float = 30.0
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
    random_seed: int = 0

    def __post_init__(self) -> None:
        numeric_ranges = {
            "width_mm": (0.1, 100_000.0),
            "height_mm": (0.1, 100_000.0),
            "opening_width_mm": (0.1, 5000.0),
            "opening_height_mm": (0.1, 5000.0),
            "spacing_mm": (0.1, 10_000.0),
            "grid_angle_degrees": (-180.0, 180.0),
            "opening_angle_degrees": (-180.0, 180.0),
            "outer_margin_mm": (0.0, 5000.0),
            "inner_margin_mm": (0.0, 5000.0),
            "target_open_area_percentage": (0.1, 99.9),
            "random_min_width_mm": (0.1, 5000.0),
            "random_max_width_mm": (0.1, 5000.0),
            "random_min_height_mm": (0.1, 5000.0),
            "random_max_height_mm": (0.1, 5000.0),
            "random_min_horizontal_gap_mm": (0.0, 10_000.0),
            "random_max_horizontal_gap_mm": (0.0, 10_000.0),
            "random_min_vertical_gap_mm": (0.0, 10_000.0),
            "random_max_vertical_gap_mm": (0.0, 10_000.0),
        }
        for name, (minimum, maximum) in numeric_ranges.items():
            value = getattr(self, name)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or not minimum <= value <= maximum
            ):
                raise ValueError(f"Nieprawidłowa wartość parametru {name}.")
        if not isinstance(self.pattern, str) or self.pattern not in _PATTERNS:
            raise ValueError("Nieznany rodzaj układu perforacji.")
        if (
            not isinstance(self.layout_mode, str)
            or self.layout_mode not in _LAYOUT_MODES
        ):
            raise ValueError("Nieznany sposób rozmieszczania otworów.")
        if (
            not isinstance(self.opening_type, str)
            or self.opening_type not in _OPENING_TYPES
        ):
            raise ValueError("Nieznany kształt otworu.")
        if (
            not isinstance(self.spacing_mode, str)
            or self.spacing_mode not in _SPACING_MODES
        ):
            raise ValueError("Nieznany tryb odległości.")
        if (
            isinstance(self.polygon_sides, bool)
            or not isinstance(self.polygon_sides, int)
            or not 3 <= self.polygon_sides <= 20
        ):
            raise ValueError("Liczba boków musi mieścić się w zakresie 3–20.")
        if not isinstance(self.perforation_as_block, bool):
            raise ValueError("Nieprawidłowy sposób eksportu perforacji.")
        if any(
            not isinstance(value, bool)
            for value in (
                self.randomize_width,
                self.randomize_height,
                self.randomize_horizontal_gap,
                self.randomize_vertical_gap,
            )
        ):
            raise ValueError("Nieprawidłowe ustawienie losowania parametru.")
        if (
            self.random_min_width_mm > self.random_max_width_mm
            or self.random_min_height_mm > self.random_max_height_mm
            or self.random_min_horizontal_gap_mm
            > self.random_max_horizontal_gap_mm
            or self.random_min_vertical_gap_mm
            > self.random_max_vertical_gap_mm
        ):
            raise ValueError("Zakres losowanego parametru jest nieprawidłowy.")
        if (
            isinstance(self.random_seed, bool)
            or not isinstance(self.random_seed, int)
            or not 0 <= self.random_seed <= 2**32 - 1
        ):
            raise ValueError("Nieprawidłowe ziarno losowego układu.")
        if self.custom_opening is not None and (
            not isinstance(self.custom_opening, (Polygon, MultiPolygon))
            or self.custom_opening.is_empty
            or not self.custom_opening.is_valid
        ):
            raise ValueError("Nieprawidłowa geometria własnego otworu.")
        if self.opening_type == "custom" and self.custom_opening is None:
            raise ValueError("Konfiguracja nie zawiera własnego kształtu otworu.")


def save_perforation_settings(
    path: str | Path, settings: PerforationSettings
) -> None:
    custom_opening = (
        wkb.dumps(settings.custom_opening, hex=True)
        if settings.custom_opening is not None
        else None
    )
    data = {
        "version": _VERSION,
        "width_mm": settings.width_mm,
        "height_mm": settings.height_mm,
        "pattern": settings.pattern,
        "opening_type": settings.opening_type,
        "opening_width_mm": settings.opening_width_mm,
        "opening_height_mm": settings.opening_height_mm,
        "polygon_sides": settings.polygon_sides,
        "spacing_mm": settings.spacing_mm,
        "spacing_mode": settings.spacing_mode,
        "grid_angle_degrees": settings.grid_angle_degrees,
        "opening_angle_degrees": settings.opening_angle_degrees,
        "outer_margin_mm": settings.outer_margin_mm,
        "inner_margin_mm": settings.inner_margin_mm,
        "perforation_as_block": settings.perforation_as_block,
        "custom_opening_wkb": custom_opening,
        "layout_mode": settings.layout_mode,
        "target_open_area_percentage": settings.target_open_area_percentage,
        "randomize_width": settings.randomize_width,
        "randomize_height": settings.randomize_height,
        "randomize_horizontal_gap": settings.randomize_horizontal_gap,
        "randomize_vertical_gap": settings.randomize_vertical_gap,
        "random_min_width_mm": settings.random_min_width_mm,
        "random_max_width_mm": settings.random_max_width_mm,
        "random_min_height_mm": settings.random_min_height_mm,
        "random_max_height_mm": settings.random_max_height_mm,
        "random_min_horizontal_gap_mm": settings.random_min_horizontal_gap_mm,
        "random_max_horizontal_gap_mm": settings.random_max_horizontal_gap_mm,
        "random_min_vertical_gap_mm": settings.random_min_vertical_gap_mm,
        "random_max_vertical_gap_mm": settings.random_max_vertical_gap_mm,
        "random_seed": settings.random_seed,
    }
    Path(path).write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def load_perforation_settings(
    path: str | Path,
) -> PerforationSettings:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or type(data.get("version")) is not int:
        raise ValueError("Nieprawidłowy plik konfiguracji perforacji.")
    if data["version"] not in _SUPPORTED_VERSIONS:
        raise ValueError(
            f"Nieobsługiwana wersja konfiguracji: {data['version']}."
        )
    try:
        legacy_min_size = data.get("random_min_size_mm", 10.0)
        legacy_max_size = data.get("random_max_size_mm", 20.0)
        legacy_randomize_size = data.get("randomize_opening_size", True)
        legacy_randomize_gap = data.get("randomize_gap", False)
        legacy_gap = data.get("random_min_gap_mm", 2.0)
        legacy_max_gap = data.get("random_max_gap_mm", legacy_gap)
        layout_mode = data.get("layout_mode", "grid")
        spacing_mm = data["spacing_mm"]
        if data["version"] == 2 and layout_mode == "random":
            spacing_mm = legacy_gap
        custom_wkb = data["custom_opening_wkb"]
        if custom_wkb is not None and not isinstance(custom_wkb, str):
            raise ValueError("Nieprawidłowe dane własnego kształtu.")
        custom_opening = (
            wkb.loads(bytes.fromhex(custom_wkb))
            if custom_wkb is not None
            else None
        )
        return PerforationSettings(
            width_mm=data["width_mm"],
            height_mm=data["height_mm"],
            pattern=data["pattern"],
            opening_type=data["opening_type"],
            opening_width_mm=data["opening_width_mm"],
            opening_height_mm=data["opening_height_mm"],
            polygon_sides=data["polygon_sides"],
            spacing_mm=spacing_mm,
            spacing_mode=data["spacing_mode"],
            grid_angle_degrees=data["grid_angle_degrees"],
            opening_angle_degrees=data["opening_angle_degrees"],
            outer_margin_mm=data["outer_margin_mm"],
            inner_margin_mm=data["inner_margin_mm"],
            perforation_as_block=data["perforation_as_block"],
            custom_opening=custom_opening,
            layout_mode=layout_mode,
            target_open_area_percentage=data.get(
                "target_open_area_percentage", 30.0
            ),
            randomize_width=data.get(
                "randomize_width", legacy_randomize_size
            ),
            randomize_height=data.get("randomize_height", False),
            randomize_horizontal_gap=data.get(
                "randomize_horizontal_gap", legacy_randomize_gap
            ),
            randomize_vertical_gap=data.get(
                "randomize_vertical_gap", legacy_randomize_gap
            ),
            random_min_width_mm=data.get(
                "random_min_width_mm", legacy_min_size
            ),
            random_max_width_mm=data.get(
                "random_max_width_mm", legacy_max_size
            ),
            random_min_height_mm=data.get(
                "random_min_height_mm", data["opening_height_mm"]
            ),
            random_max_height_mm=data.get(
                "random_max_height_mm", data["opening_height_mm"]
            ),
            random_min_horizontal_gap_mm=data.get(
                "random_min_horizontal_gap_mm", legacy_gap
            ),
            random_max_horizontal_gap_mm=data.get(
                "random_max_horizontal_gap_mm", legacy_max_gap
            ),
            random_min_vertical_gap_mm=data.get(
                "random_min_vertical_gap_mm", legacy_gap
            ),
            random_max_vertical_gap_mm=data.get(
                "random_max_vertical_gap_mm", legacy_max_gap
            ),
            random_seed=data.get("random_seed", 0),
        )
    except KeyError as error:
        raise ValueError(
            f"Brak wymaganego parametru w konfiguracji: {error.args[0]}."
        ) from error
    except (GEOSException, ValueError) as error:
        raise ValueError(f"Nieprawidłowy plik konfiguracji: {error}") from error
