from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import ezdxf
from ezdxf.path import make_path
from shapely import set_precision
from shapely import unary_union
from shapely.affinity import scale, translate
from shapely.geometry import LineString, MultiPolygon, Point, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import polygonize
from shapely.prepared import prep

MAX_HOLES = 100_000
MAX_GRID_CANDIDATES = 2_000_000

_UNIT_TO_MM = {
    0: 1.0,  # Unitless: assumed to be millimeters.
    1: 25.4,
    2: 304.8,
    4: 1.0,
    5: 10.0,
    6: 1000.0,
    7: 1_000_000.0,
    8: 0.0000254,
    9: 0.0254,
    10: 914.4,
    11: 1e-7,
    12: 1e-6,
    13: 0.001,
    14: 0.1,
    15: 10.0,
    16: 100.0,
    17: 1000.0,
    18: 1_000_000.0,
    19: 1_000_000_000.0,
}


@dataclass(frozen=True)
class Drawing:
    material: BaseGeometry
    width_mm: float
    height_mm: float
    warnings: tuple[str, ...]


def _polygon_parts(geometry: BaseGeometry) -> list[Polygon]:
    if isinstance(geometry, Polygon):
        return [geometry]
    if isinstance(geometry, MultiPolygon):
        return list(geometry.geoms)
    return []


def _contour_material(polygons: Iterable[Polygon]) -> BaseGeometry:
    ring_polygons: dict[bytes, Polygon] = {}
    for polygon in polygons:
        rings = [polygon.exterior, *polygon.interiors]
        for ring in rings:
            ring_polygon = Polygon(ring)
            if ring_polygon.area > 1e-8:
                ring_polygons[ring_polygon.normalize().wkb] = ring_polygon

    rings = sorted(ring_polygons.values(), key=lambda item: item.area)
    parents: dict[int, int | None] = {}
    depths: dict[int, int] = {}
    for index, ring in enumerate(rings):
        containers = [
            (other.area, other_index)
            for other_index, other in enumerate(rings)
            if other.area > ring.area and other.contains(ring)
        ]
        parents[index] = min(containers)[1] if containers else None

    def depth(index: int) -> int:
        if index not in depths:
            parent = parents[index]
            depths[index] = 0 if parent is None else depth(parent) + 1
        return depths[index]

    material_polygons: list[Polygon] = []
    for index, ring in enumerate(rings):
        if depth(index) % 2:
            continue
        holes = [
            child.exterior.coords
            for child_index, child in enumerate(rings)
            if parents[child_index] == index and depth(child_index) % 2
        ]
        material_polygons.append(Polygon(ring.exterior.coords, holes))

    if not material_polygons:
        raise ValueError(
            "Nie znaleziono zamkniętego konturu. Sprawdź, czy linie łączą się "
            "w zamknięty obrys."
        )
    material = unary_union(material_polygons)
    if material.is_empty or not material.is_valid:
        raise ValueError("Kontury DXF tworzą nieprawidłową geometrię.")
    return material


def load_dxf(path: str | Path, flattening_tolerance_mm: float = 0.05) -> Drawing:
    """Read closed planar contours and convert all coordinates to millimeters."""
    document = ezdxf.readfile(str(path))
    unit_code = int(document.header.get("$INSUNITS", 0) or 0)
    factor = _UNIT_TO_MM.get(unit_code, 1.0)
    warnings: list[str] = []
    if unit_code == 0:
        warnings.append("DXF nie określa jednostek; przyjęto milimetry.")
    elif unit_code not in _UNIT_TO_MM:
        warnings.append(
            f"Nieobsługiwana jednostka DXF ({unit_code}); przyjęto milimetry."
        )

    lines: list[LineString] = []
    skipped: set[str] = set()
    flattening_distance = max(flattening_tolerance_mm / factor, 1e-7)
    for entity in document.modelspace():
        try:
            path_object = make_path(entity)
            points = [
                (point.x * factor, point.y * factor)
                for point in path_object.flattening(
                    distance=flattening_distance, segments=8
                )
            ]
        except (AttributeError, NotImplementedError, TypeError, ValueError):
            skipped.add(entity.dxftype())
            continue
        if len(points) >= 2:
            # Remove floating-point noise at shared CAD endpoints before noding.
            line = set_precision(LineString(points), grid_size=0.001)
            if line.length > 1e-8:
                lines.append(line)
        else:
            skipped.add(entity.dxftype())

    if not lines:
        raise ValueError("Plik DXF nie zawiera obsługiwanej geometrii liniowej.")
    if skipped:
        types = ", ".join(sorted(skipped))
        warnings.append(f"Pominięto nieobsługiwane obiekty: {types}.")

    faces = list(polygonize(unary_union(lines)))
    material = _contour_material(faces)
    min_x, min_y, max_x, max_y = material.bounds
    material = translate(material, xoff=-min_x, yoff=-min_y)
    return Drawing(
        material=material,
        width_mm=max_x - min_x,
        height_mm=max_y - min_y,
        warnings=tuple(warnings),
    )


def resize_material(
    material: BaseGeometry, width_mm: float, height_mm: float
) -> BaseGeometry:
    if width_mm <= 0 or height_mm <= 0:
        raise ValueError("Wymiary arkusza muszą być większe od zera.")
    min_x, min_y, max_x, max_y = material.bounds
    width = max_x - min_x
    height = max_y - min_y
    if width <= 0 or height <= 0:
        raise ValueError("Nie można przeskalować pustego konturu.")
    normalized = translate(material, xoff=-min_x, yoff=-min_y)
    return scale(
        normalized,
        xfact=width_mm / width,
        yfact=height_mm / height,
        origin=(0, 0),
    )


def generate_holes(
    material: BaseGeometry,
    diameter_mm: float,
    spacing_mm: float,
    margin_mm: float,
    angle_degrees: float,
    pattern: str,
    spacing_mode: str,
) -> list[tuple[float, float]]:
    if diameter_mm <= 0:
        raise ValueError("Średnica otworu musi być większa od zera.")
    if spacing_mm <= 0:
        raise ValueError("Odstęp lub podziałka musi być większa od zera.")
    if margin_mm < 0:
        raise ValueError("Margines nie może być ujemny.")
    if pattern not in {"square", "staggered"}:
        raise ValueError("Nieznany typ układu otworów.")
    if spacing_mode not in {"gap", "pitch"}:
        raise ValueError("Nieznany tryb określania odległości.")

    pitch = spacing_mm + diameter_mm if spacing_mode == "gap" else spacing_mm
    if pitch + 1e-9 < diameter_mm:
        raise ValueError(
            "Podziałka nie może być mniejsza od średnicy otworu."
        )
    allowed = material.buffer(
        -(margin_mm + diameter_mm / 2),
        quad_segs=8,
        join_style="mitre",
    )
    if allowed.is_empty:
        return []

    min_x, min_y, max_x, max_y = allowed.bounds
    center_x = (min_x + max_x) / 2
    center_y = (min_y + max_y) / 2
    radians = math.radians(angle_degrees)
    cosine = math.cos(radians)
    sine = math.sin(radians)
    corners = [
        (min_x, min_y),
        (min_x, max_y),
        (max_x, min_y),
        (max_x, max_y),
    ]
    local_corners = [
        (
            (x - center_x) * cosine + (y - center_y) * sine,
            -(x - center_x) * sine + (y - center_y) * cosine,
        )
        for x, y in corners
    ]
    local_min_x = min(point[0] for point in local_corners)
    local_max_x = max(point[0] for point in local_corners)
    local_min_y = min(point[1] for point in local_corners)
    local_max_y = max(point[1] for point in local_corners)
    first_column = math.floor(local_min_x / pitch) - 1
    last_column = math.ceil(local_max_x / pitch) + 1
    first_row = math.floor(local_min_y / pitch) - 1
    last_row = math.ceil(local_max_y / pitch) + 1
    candidate_count = (last_column - first_column + 1) * (
        last_row - first_row + 1
    )
    if candidate_count > MAX_GRID_CANDIDATES:
        raise ValueError(
            "Układ tworzy zbyt wiele punktów siatki. Zwiększ podziałkę "
            "lub zmniejsz wymiary detalu."
        )

    prepared = prep(allowed)
    holes: list[tuple[float, float]] = []
    for row in range(first_row, last_row + 1):
        row_offset = pitch / 2 if pattern == "staggered" and row % 2 else 0.0
        local_y = row * pitch
        for column in range(first_column, last_column + 1):
            local_x = column * pitch + row_offset
            x = center_x + local_x * cosine - local_y * sine
            y = center_y + local_x * sine + local_y * cosine
            if prepared.contains(Point(x, y)):
                holes.append((x, y))
                if len(holes) > MAX_HOLES:
                    raise ValueError(
                        f"Perforacja przekracza limit {MAX_HOLES:,} otworów. "
                        "Zwiększ odstęp lub średnicę."
                    )
    return holes


def export_dxf(
    path: str | Path,
    material: BaseGeometry,
    holes: Iterable[tuple[float, float]],
    diameter_mm: float,
) -> None:
    document = ezdxf.new("R2010")
    document.units = ezdxf.units.MM
    document.layers.new("OBRYS", dxfattribs={"color": 3})
    document.layers.new("OTWORY", dxfattribs={"color": 4})
    modelspace = document.modelspace()
    for polygon in _polygon_parts(material):
        modelspace.add_lwpolyline(
            list(polygon.exterior.coords)[:-1],
            format="xy",
            close=True,
            dxfattribs={"layer": "OBRYS"},
        )
        for interior in polygon.interiors:
            modelspace.add_lwpolyline(
                list(interior.coords)[:-1],
                format="xy",
                close=True,
                dxfattribs={"layer": "OBRYS"},
            )
    radius = diameter_mm / 2
    for x, y in holes:
        modelspace.add_circle(
            (x, y), radius, dxfattribs={"layer": "OTWORY"}
        )
    document.saveas(str(path))
