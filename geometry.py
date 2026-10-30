from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import ezdxf
from ezdxf.path import make_path
from shapely import set_precision
from shapely import unary_union
from shapely.affinity import rotate, scale, translate
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

    modelspace = document.modelspace()
    reimporting_perforation = (
        document.layers.has_entry("OBRYS")
        and document.layers.has_entry("OTWORY")
    )
    lines: list[LineString] = []
    skipped: set[str] = set()
    flattening_distance = max(flattening_tolerance_mm / factor, 1e-7)
    for entity in modelspace:
        if reimporting_perforation and entity.dxf.layer.upper() != "OBRYS":
            continue
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


def make_opening_shape(
    shape: str,
    width_mm: float,
    height_mm: float | None = None,
    sides: int = 6,
    custom_shape: BaseGeometry | None = None,
    radius_mm: float | None = None,
) -> BaseGeometry:
    if width_mm <= 0:
        raise ValueError("Szerokość otworu musi być większa od zera.")
    if shape in {"rectangle", "ellipse", "slot"} and (
        height_mm is None or height_mm <= 0
    ):
        raise ValueError("Wysokość otworu musi być większa od zera.")

    if shape == "circle":
        opening = Point(0, 0).buffer(width_mm / 2, quad_segs=32)
    elif shape == "square":
        opening = Polygon(
            [
                (-width_mm / 2, -width_mm / 2),
                (width_mm / 2, -width_mm / 2),
                (width_mm / 2, width_mm / 2),
                (-width_mm / 2, width_mm / 2),
            ]
        )
    elif shape == "rectangle":
        assert height_mm is not None
        opening = Polygon(
            [
                (-width_mm / 2, -height_mm / 2),
                (width_mm / 2, -height_mm / 2),
                (width_mm / 2, height_mm / 2),
                (-width_mm / 2, height_mm / 2),
            ]
        )
    elif shape == "triangle":
        height = width_mm * math.sqrt(3) / 2
        opening = Polygon(
            [
                (-width_mm / 2, -height / 3),
                (width_mm / 2, -height / 3),
                (0, 2 * height / 3),
            ]
        )
    elif shape == "ellipse":
        assert height_mm is not None
        opening = scale(
            Point(0, 0).buffer(1, quad_segs=32),
            xfact=width_mm / 2,
            yfact=height_mm / 2,
            origin=(0, 0),
        )
    elif shape == "slot":
        assert height_mm is not None
        radius = (
            min(width_mm, height_mm) / 2
            if radius_mm is None
            else radius_mm
        )
        if radius < 0 or radius > min(width_mm, height_mm) / 2:
            raise ValueError(
                "Promień fasolki musi mieścić się między 0 a połową "
                "jej krótszego wymiaru."
            )
        half_length = width_mm / 2
        half_width = height_mm / 2
        inner_x = half_length - radius
        inner_y = half_width - radius
        if radius == 0:
            opening = Polygon(
                [
                    (-half_length, -half_width),
                    (half_length, -half_width),
                    (half_length, half_width),
                    (-half_length, half_width),
                ]
            )
        elif inner_x > 0 and inner_y > 0:
            opening = Polygon(
                [
                    (-inner_x, -inner_y),
                    (inner_x, -inner_y),
                    (inner_x, inner_y),
                    (-inner_x, inner_y),
                ]
            ).buffer(radius, quad_segs=32)
        elif inner_x > 0:
            opening = LineString([(-inner_x, 0), (inner_x, 0)]).buffer(
                radius, quad_segs=32
            )
        elif inner_y > 0:
            opening = LineString([(0, -inner_y), (0, inner_y)]).buffer(
                radius, quad_segs=32
            )
        else:
            opening = Point(0, 0).buffer(radius, quad_segs=32)
    elif shape == "regular_polygon":
        if not 3 <= sides <= 20:
            raise ValueError("Wielokąt musi mieć od 3 do 20 boków.")
        unit_polygon = Polygon(
            [
                (
                    math.cos(math.pi / 2 + 2 * math.pi * index / sides),
                    math.sin(math.pi / 2 + 2 * math.pi * index / sides),
                )
                for index in range(sides)
            ]
        )
        min_x, min_y, max_x, max_y = unit_polygon.bounds
        opening = scale(
            unit_polygon,
            xfact=width_mm / (max_x - min_x),
            yfact=width_mm / (max_x - min_x),
            origin=(0, 0),
        )
    elif shape == "custom":
        if custom_shape is None or custom_shape.is_empty:
            raise ValueError("Wczytaj zamknięty kształt otworu z pliku DXF.")
        min_x, min_y, max_x, max_y = custom_shape.bounds
        source_width = max_x - min_x
        source_height = max_y - min_y
        if source_width <= 0 or source_height <= 0:
            raise ValueError("Kształt z DXF nie ma prawidłowych wymiarów.")
        factor = width_mm / source_width
        opening = scale(
            custom_shape,
            xfact=factor,
            yfact=factor,
            origin=((min_x + max_x) / 2, (min_y + max_y) / 2),
        )
        opening = translate(
            opening,
            xoff=-(min_x + max_x) / 2,
            yoff=-(min_y + max_y) / 2,
        )
    else:
        raise ValueError("Nieznany kształt otworu.")

    if not opening.is_valid or opening.area <= 0:
        raise ValueError("Kształt otworu tworzy nieprawidłową geometrię.")
    return opening


def open_area_percentage(
    material: BaseGeometry, hole_count: int, opening_shape: BaseGeometry
) -> float:
    return hole_count * opening_shape.area / material.area * 100


def material_clearance(
    material: BaseGeometry,
    outer_margin_mm: float,
    inner_margin_mm: float | None = None,
) -> BaseGeometry:
    if outer_margin_mm < 0 or (
        inner_margin_mm is not None and inner_margin_mm < 0
    ):
        raise ValueError("Margines nie może być ujemny.")
    if inner_margin_mm is None:
        inner_margin_mm = outer_margin_mm

    polygons = _polygon_parts(material)
    clearances: list[BaseGeometry] = []
    for index, polygon in enumerate(polygons):
        is_island = any(
            Polygon(interior.coords).contains(polygon)
            for other_index, other in enumerate(polygons)
            if other_index != index
            for interior in other.interiors
        )
        shell_margin = inner_margin_mm if is_island else outer_margin_mm
        clearance = Polygon(polygon.exterior).buffer(
            -shell_margin, join_style="mitre"
        )
        for interior in polygon.interiors:
            clearance = clearance.difference(
                Polygon(interior.coords).buffer(
                    inner_margin_mm, join_style="mitre"
                )
            )
        if not clearance.is_empty:
            clearances.append(clearance)
    return unary_union(clearances) if clearances else Polygon()


def generate_holes(
    material: BaseGeometry,
    opening_shape: BaseGeometry,
    spacing_mm: float,
    margin_mm: float,
    angle_degrees: float,
    pattern: str,
    spacing_mode: str,
    inner_margin_mm: float | None = None,
    opening_angle_degrees: float = 0.0,
) -> list[tuple[float, float]]:
    if opening_shape.is_empty or opening_shape.area <= 0:
        raise ValueError("Kształt otworu musi mieć dodatnie pole.")
    if spacing_mm <= 0:
        raise ValueError("Odstęp lub podziałka musi być większa od zera.")
    if margin_mm < 0 or (
        inner_margin_mm is not None and inner_margin_mm < 0
    ):
        raise ValueError("Margines nie może być ujemny.")
    if not opening_shape.is_valid:
        raise ValueError("Kształt otworu tworzy nieprawidłową geometrię.")
    if pattern not in {"square", "staggered"}:
        raise ValueError("Nieznany typ układu otworów.")
    if spacing_mode not in {"gap", "pitch"}:
        raise ValueError("Nieznany tryb określania odległości.")

    min_x, shape_min_y, max_x, shape_max_y = opening_shape.bounds
    radius = max(
        math.hypot(x, y)
        for x in (min_x, max_x)
        for y in (shape_min_y, shape_max_y)
    )
    if spacing_mode == "gap":

        def has_required_gap(pitch: float) -> bool:
            row_pitch = (
                pitch * math.sqrt(3) / 2
                if pattern == "staggered"
                else pitch
            )
            offsets = (
                [(pitch, 0), (0, pitch)]
                if pattern == "square"
                else [
                    (pitch, 0),
                    (pitch / 2, row_pitch),
                    (-pitch / 2, row_pitch),
                ]
            )
            return all(
                opening_shape.distance(
                    translate(opening_shape, xoff=offset_x, yoff=offset_y)
                )
                + 1e-7
                >= spacing_mm
                for offset_x, offset_y in offsets
            )

        low = 0.0
        high = max(2 * radius + spacing_mm, spacing_mm)
        for _ in range(40):
            middle = (low + high) / 2
            if has_required_gap(middle):
                high = middle
            else:
                low = middle
        pitch = high
    else:
        pitch = spacing_mm

    allowed = material_clearance(material, margin_mm, inner_margin_mm)
    if allowed.is_empty:
        return []

    min_x, min_y, max_x, max_y = allowed.bounds
    min_x -= radius
    min_y -= radius
    max_x += radius
    max_y += radius
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
    row_pitch = (
        pitch * math.sqrt(3) / 2 if pattern == "staggered" else pitch
    )
    first_column = math.floor(local_min_x / pitch) - 1
    last_column = math.ceil(local_max_x / pitch) + 1
    first_row = math.floor(local_min_y / row_pitch) - 1
    last_row = math.ceil(local_max_y / row_pitch) + 1
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
    center_limit = max(
        2 * radius + (spacing_mm if spacing_mode == "gap" else 0), 1e-9
    )
    cell_size = center_limit
    neighboring_holes: dict[
        tuple[int, int],
        list[tuple[float, float, BaseGeometry]],
    ] = {}
    local_opening = rotate(
        opening_shape, opening_angle_degrees, origin=(0, 0)
    )
    rotated_opening = rotate(
        opening_shape,
        angle_degrees + opening_angle_degrees,
        origin=(0, 0),
    )
    for row in range(first_row, last_row + 1):
        row_offset = pitch / 2 if pattern == "staggered" and row % 2 else 0.0
        local_y = row * row_pitch
        for column in range(first_column, last_column + 1):
            local_x = column * pitch + row_offset
            x = center_x + local_x * cosine - local_y * sine
            y = center_y + local_x * sine + local_y * cosine
            placed_opening = translate(rotated_opening, xoff=x, yoff=y)
            if not prepared.covers(placed_opening):
                continue

            bucket = (
                math.floor(local_x / cell_size),
                math.floor(local_y / cell_size),
            )
            for bucket_x in range(bucket[0] - 1, bucket[0] + 2):
                for bucket_y in range(bucket[1] - 1, bucket[1] + 2):
                    for other_x, other_y, other_opening in neighboring_holes.get(
                        (bucket_x, bucket_y), []
                    ):
                        if (
                            math.hypot(local_x - other_x, local_y - other_y)
                            > center_limit
                        ):
                            continue
                        local_placed_opening = translate(
                            local_opening, xoff=local_x, yoff=local_y
                        )
                        distance = local_placed_opening.distance(other_opening)
                        if spacing_mode == "pitch":
                            collides = (
                                local_placed_opening.intersection(
                                    other_opening
                                ).area
                                > 1e-9
                            )
                        else:
                            collides = distance + 1e-7 < spacing_mm
                        if collides:
                            raise ValueError(
                                "Otwory nachodzą na siebie lub mają za mały "
                                "odstęp. Zwiększ podziałkę albo zmniejsz "
                                "wymiary kształtu."
                            )

            holes.append((x, y))
            neighboring_holes.setdefault(bucket, []).append(
                (
                    local_x,
                    local_y,
                    translate(local_opening, xoff=local_x, yoff=local_y),
                )
            )
            if len(holes) > MAX_HOLES:
                raise ValueError(
                    f"Perforacja przekracza limit {MAX_HOLES:,} otworów. "
                    "Zwiększ odstęp lub zmniejsz wymiary detalu."
                )
    return holes


def export_dxf(
    path: str | Path,
    material: BaseGeometry,
    holes: Iterable[tuple[float, float]],
    opening_shape: BaseGeometry,
    opening_type: str = "custom",
    angle_degrees: float = 0.0,
    opening_angle_degrees: float = 0.0,
    perforation_as_block: bool = False,
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
    block = (
        document.blocks.new(name="PERFORACJA")
        if perforation_as_block
        else None
    )
    target = block if block is not None else modelspace
    for x, y in holes:
        if opening_type == "circle":
            radius = (opening_shape.bounds[2] - opening_shape.bounds[0]) / 2
            target.add_circle(
                (x, y), radius, dxfattribs={"layer": "OTWORY"}
            )
            continue
        placed_opening = translate(
            rotate(
                opening_shape,
                angle_degrees + opening_angle_degrees,
                origin=(0, 0),
            ),
            xoff=x,
            yoff=y,
        )
        for polygon in _polygon_parts(placed_opening):
            target.add_lwpolyline(
                list(polygon.exterior.coords)[:-1],
                format="xy",
                close=True,
                dxfattribs={"layer": "OTWORY"},
            )
            for interior in polygon.interiors:
                target.add_lwpolyline(
                    list(interior.coords)[:-1],
                    format="xy",
                    close=True,
                    dxfattribs={"layer": "OTWORY"},
                )
    if block is not None:
        modelspace.add_blockref(
            block.name, (0, 0), dxfattribs={"layer": "OTWORY"}
        )
    document.saveas(str(path))
