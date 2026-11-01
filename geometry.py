from __future__ import annotations

import math
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

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
MAX_RANDOM_CANDIDATES = 200_000

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
        if width_mm < height_mm:
            raise ValueError(
                "Długość fasolki musi być równa lub większa od jej szerokości."
            )
        radius = height_mm / 2
        half_centerline = (width_mm - height_mm) / 2
        if half_centerline == 0:
            opening = Point(0, 0).buffer(radius, quad_segs=32)
        else:
            opening = LineString(
                [(-half_centerline, 0), (half_centerline, 0)]
            ).buffer(radius, quad_segs=32)
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


def generate_random_holes(
    material: BaseGeometry,
    opening_shape: BaseGeometry,
    target_open_area_percentage: float,
    min_width_mm: float,
    max_width_mm: float,
    min_height_mm: float,
    max_height_mm: float,
    min_horizontal_gap_mm: float,
    max_horizontal_gap_mm: float,
    min_vertical_gap_mm: float,
    max_vertical_gap_mm: float,
    margin_mm: float,
    inner_margin_mm: float | None = None,
    angle_degrees: float = 0.0,
    seed: int = 0,
    progress_callback: Callable[[int], None] | None = None,
    cancellation_requested: Callable[[], bool] | None = None,
) -> list[tuple[float, float, BaseGeometry]]:
    if not 0 < target_open_area_percentage < 100:
        raise ValueError("Docelowy stopień prześwitu musi być między 0 a 100%.")
    if (
        min_width_mm <= 0
        or max_width_mm < min_width_mm
        or min_height_mm <= 0
        or max_height_mm < min_height_mm
    ):
        raise ValueError("Zakres wymiarów otworu jest nieprawidłowy.")
    if (
        min_horizontal_gap_mm < 0
        or max_horizontal_gap_mm < min_horizontal_gap_mm
        or min_vertical_gap_mm < 0
        or max_vertical_gap_mm < min_vertical_gap_mm
    ):
        raise ValueError("Zakres odstępu między otworami jest nieprawidłowy.")
    if not opening_shape.is_valid or opening_shape.area <= 0:
        raise ValueError("Kształt otworu tworzy nieprawidłową geometrię.")

    allowed = material_clearance(material, margin_mm, inner_margin_mm)
    if allowed.is_empty:
        return []

    min_x, min_y, max_x, max_y = opening_shape.bounds
    base_width = max_x - min_x
    base_height = max_y - min_y
    if base_width <= 0:
        raise ValueError("Kształt otworu nie ma prawidłowej szerokości.")
    if base_height <= 0:
        raise ValueError("Kształt otworu nie ma prawidłowej wysokości.")
    rows: list[list[list[tuple[float, float, BaseGeometry]]]] = []
    prepared = prep(allowed)
    generator = random.Random(seed)
    area_target = material.area * target_open_area_percentage / 100

    def axis_density(
        factor: float,
        min_size: float,
        max_size: float,
        min_gap: float,
        max_gap: float,
    ) -> float:
        size = min_size + (max_size - min_size) * factor
        gap = max_gap - (max_gap - min_gap) * factor
        return size / (size + gap)

    def factor_for_density(
        density: float,
        min_size: float,
        max_size: float,
        min_gap: float,
        max_gap: float,
    ) -> float:
        if density <= axis_density(0.0, min_size, max_size, min_gap, max_gap):
            return 0.0
        if density >= axis_density(1.0, min_size, max_size, min_gap, max_gap):
            return 1.0
        low, high = 0.0, 1.0
        for _ in range(32):
            middle = (low + high) / 2
            if axis_density(
                middle, min_size, max_size, min_gap, max_gap
            ) < density:
                low = middle
            else:
                high = middle
        return (low + high) / 2

    def sample_factor(target_factor: float) -> float:
        concentration = 40.0
        target_factor = min(1.0, max(0.0, target_factor))
        return generator.betavariate(
            max(target_factor * concentration, 2.0),
            max((1 - target_factor) * concentration, 2.0),
        )

    def sample_axis(
        min_size: float,
        max_size: float,
        min_gap: float,
        max_gap: float,
        target_factor: float,
    ) -> tuple[float, float]:
        factor = sample_factor(target_factor)
        return (
            min_size + (max_size - min_size) * factor,
            max_gap - (max_gap - min_gap) * factor,
        )

    target_fraction = target_open_area_percentage / 100
    minimum_horizontal_density = axis_density(
        0.0,
        min_width_mm,
        max_width_mm,
        min_horizontal_gap_mm,
        max_horizontal_gap_mm,
    )
    max_horizontal_density = axis_density(
        1.0,
        min_width_mm,
        max_width_mm,
        min_horizontal_gap_mm,
        max_horizontal_gap_mm,
    )
    minimum_vertical_density = axis_density(
        0.0,
        min_height_mm,
        max_height_mm,
        min_vertical_gap_mm,
        max_vertical_gap_mm,
    )
    max_vertical_density = axis_density(
        1.0,
        min_height_mm,
        max_height_mm,
        min_vertical_gap_mm,
        max_vertical_gap_mm,
    )
    balanced_density = min(1.0, math.sqrt(target_fraction) * 1.1)
    target_horizontal_density = min(
        max_horizontal_density,
        max(minimum_horizontal_density, balanced_density),
    )
    target_vertical_density = min(
        max_vertical_density,
        max(minimum_vertical_density, balanced_density),
    )
    if target_horizontal_density * target_vertical_density < target_fraction:
        low_scale, high_scale = 1.0, 2.0
        while (
            min(max_horizontal_density, target_horizontal_density * high_scale)
            * min(max_vertical_density, target_vertical_density * high_scale)
            < target_fraction
            and high_scale < 1_000_000
        ):
            high_scale *= 2
        for _ in range(40):
            middle_scale = (low_scale + high_scale) / 2
            candidate_horizontal = min(
                max_horizontal_density,
                target_horizontal_density * middle_scale,
            )
            candidate_vertical = min(
                max_vertical_density,
                target_vertical_density * middle_scale,
            )
            if candidate_horizontal * candidate_vertical < target_fraction:
                low_scale = middle_scale
            else:
                high_scale = middle_scale
        target_horizontal_density = min(
            max_horizontal_density, target_horizontal_density * high_scale
        )
        target_vertical_density = min(
            max_vertical_density, target_vertical_density * high_scale
        )

    vertical_factor = factor_for_density(
        target_vertical_density,
        min_height_mm,
        max_height_mm,
        min_vertical_gap_mm,
        max_vertical_gap_mm,
    )
    horizontal_factor = factor_for_density(
        target_horizontal_density,
        min_width_mm,
        max_width_mm,
        min_horizontal_gap_mm,
        max_horizontal_gap_mm,
    )

    if progress_callback is not None:
        progress_callback(0)

    allowed_min_x, allowed_min_y, allowed_max_x, allowed_max_y = allowed.bounds
    row_bottom = allowed_min_y
    attempts = 0
    expected_height = min_height_mm + (
        max_height_mm - min_height_mm
    ) * vertical_factor
    expected_width = min_width_mm + (
        max_width_mm - min_width_mm
    ) * horizontal_factor
    nominal_shape = rotate(
        scale(
            opening_shape,
            xfact=expected_width / base_width,
            yfact=expected_height / base_height,
            origin=(0, 0),
        ),
        angle_degrees,
        origin=(0, 0),
    )
    nominal_row_height = nominal_shape.bounds[3] - nominal_shape.bounds[1]
    while row_bottom < allowed_max_y and attempts < MAX_RANDOM_CANDIDATES:
        if cancellation_requested is not None and cancellation_requested():
            raise InterruptedError("Losowanie zostało anulowane.")
        row_height = 0.0
        scan_y = row_bottom + nominal_row_height / 2
        scanline = LineString(
            [(allowed_min_x, scan_y), (allowed_max_x, scan_y)]
        )
        intersections = allowed.intersection(scanline)
        line_parts = (
            intersections.geoms
            if hasattr(intersections, "geoms")
            else (intersections,)
        )
        intervals = sorted(
            (part.bounds[0], part.bounds[2])
            for part in line_parts
            if part.geom_type == "LineString" and part.length > 1e-8
        )
        placed_row_segments = []
        for interval_min_x, interval_max_x in intervals:
            row_shapes: list[
                tuple[BaseGeometry, BaseGeometry, float, float]
            ] = []
            cursor_x = interval_min_x
            while (
                cursor_x < interval_max_x
                and attempts < MAX_RANDOM_CANDIDATES
            ):
                if (
                    cancellation_requested is not None
                    and cancellation_requested()
                ):
                    raise InterruptedError("Losowanie zostało anulowane.")
                attempts += 1
                local_max_width = min(
                    max_width_mm,
                    interval_max_x - cursor_x,
                )
                if local_max_width < min_width_mm:
                    break
                local_horizontal_factor = factor_for_density(
                    target_horizontal_density,
                    min_width_mm,
                    local_max_width,
                    min_horizontal_gap_mm,
                    max_horizontal_gap_mm,
                )
                width_mm, horizontal_gap = sample_axis(
                    min_width_mm,
                    local_max_width,
                    min_horizontal_gap_mm,
                    max_horizontal_gap_mm,
                    local_horizontal_factor,
                )
                height_sample = sample_factor(vertical_factor)
                height_mm = min_height_mm + (
                    max_height_mm - min_height_mm
                ) * height_sample
                hole_shape = scale(
                    opening_shape,
                    xfact=width_mm / base_width,
                    yfact=height_mm / base_height,
                    origin=(0, 0),
                )
                oriented_shape = rotate(
                    hole_shape, angle_degrees, origin=(0, 0)
                )
                shape_bounds = oriented_shape.bounds
                shape_width = shape_bounds[2] - shape_bounds[0]
                shape_height = shape_bounds[3] - shape_bounds[1]
                if cursor_x + shape_width > interval_max_x:
                    fitted_width = width_mm * (
                        (interval_max_x - cursor_x) / shape_width
                    )
                    if fitted_width < min_width_mm:
                        break
                    width_mm = fitted_width
                    hole_shape = scale(
                        opening_shape,
                        xfact=width_mm / base_width,
                        yfact=height_mm / base_height,
                        origin=(0, 0),
                    )
                    oriented_shape = rotate(
                        hole_shape, angle_degrees, origin=(0, 0)
                    )
                    shape_bounds = oriented_shape.bounds
                    shape_width = shape_bounds[2] - shape_bounds[0]
                    shape_height = shape_bounds[3] - shape_bounds[1]
                row_shapes.append(
                    (hole_shape, oriented_shape, cursor_x, shape_width)
                )
                row_height = max(row_height, shape_height)
                cursor_x += shape_width + horizontal_gap
            if row_shapes:
                placed_segment: list[
                    tuple[float, float, BaseGeometry]
                ] = []
                for hole_shape, oriented_shape, cursor_x, _shape_width in row_shapes:
                    shape_bounds = oriented_shape.bounds
                    x = cursor_x - shape_bounds[0]
                    y = row_bottom - shape_bounds[1]
                    translated = translate(oriented_shape, xoff=x, yoff=y)
                    if prepared.covers(translated):
                        placed_segment.append((x, y, hole_shape))
                if placed_segment:
                    placed_row_segments.append(placed_segment)

        if row_height <= 0:
            row_height = nominal_row_height
        if row_height <= 0:
            break
        if placed_row_segments:
            rows.append(placed_row_segments)
        _row_height_sample, vertical_gap = sample_axis(
            min_height_mm,
            max_height_mm,
            min_vertical_gap_mm,
            max_vertical_gap_mm,
            vertical_factor,
        )
        row_bottom += row_height + vertical_gap
        if progress_callback is not None:
            progress_callback(
                min(
                    99,
                    int(
                        (row_bottom - allowed_min_y)
                        / max(allowed_max_y - allowed_min_y, 1e-9)
                        * 100
                    ),
                )
            )
    if not rows:
        return []

    row_representatives: list[list[tuple[float, float, BaseGeometry]]] = []
    row_expansions: list[list[list[tuple[float, float, BaseGeometry]]]] = []
    for row in rows:
        representatives = []
        segment_expansions = []
        for segment in row:
            start_index = generator.randrange(len(segment))
            representatives.append(segment[start_index])
            left_index = start_index - 1
            right_index = start_index + 1
            expansion = []
            while left_index >= 0 or right_index < len(segment):
                if left_index >= 0 and (
                    right_index >= len(segment) or generator.random() < 0.5
                ):
                    expansion.append(segment[left_index])
                    left_index -= 1
                else:
                    expansion.append(segment[right_index])
                    right_index += 1
            segment_expansions.append(expansion)
        row_representatives.append(representatives)
        row_expansions.append(segment_expansions)
    coverage_row_count = min(len(rows), MAX_HOLES)
    while coverage_row_count > 1:
        row_indices = [
            round(index * (len(rows) - 1) / (coverage_row_count - 1))
            for index in range(coverage_row_count)
        ]
        coverage_area = sum(
            hole[2].area
            for index in row_indices
            for hole in row_representatives[index]
        )
        if coverage_area <= area_target:
            break
        coverage_row_count -= 1
    if coverage_row_count == 1:
        row_indices = [round((len(rows) - 1) / 2)]

    placed = [
        hole
        for index in row_indices
        for hole in row_representatives[index]
    ]
    placed_row_indices = [
        index for index in row_indices for _hole in row_representatives[index]
    ]
    area_current = sum(hole[2].area for hole in placed)

    remaining_by_segment = [
        segment
        for index in row_indices
        for segment in row_expansions[index]
    ]
    segment_row_indices = [
        index
        for index in row_indices
        for _segment in row_expansions[index]
    ]
    next_hole_by_segment = [0] * len(remaining_by_segment)
    while area_current < area_target and len(placed) < MAX_HOLES:
        added_hole = False
        for index, row_holes in enumerate(remaining_by_segment):
            next_hole = next_hole_by_segment[index]
            if next_hole >= len(row_holes) or len(placed) >= MAX_HOLES:
                continue
            hole = row_holes[next_hole]
            next_hole_by_segment[index] += 1
            placed.append(hole)
            placed_row_indices.append(segment_row_indices[index])
            area_current += hole[2].area
            added_hole = True
            if area_current >= area_target or len(placed) >= MAX_HOLES:
                break
        if not added_hole:
            break

    # Keep only the best-effort result at the requested open-area target.
    while placed and area_current - area_target > area_target - (
        area_current - placed[-1][2].area
    ):
        area_current -= placed.pop()[2].area
        placed_row_indices.pop()

    if placed and not math.isclose(area_current, area_target, abs_tol=1e-8):
        first_adjustment_candidate = max(0, len(placed) - 16)
        for hole_index in range(
            len(placed) - 1, first_adjustment_candidate - 1, -1
        ):
            x, y, hole_shape = placed[hole_index]
            min_x, min_y, max_x, max_y = hole_shape.bounds
            current_width = max_x - min_x
            current_height = max_y - min_y
            desired_area = area_target - area_current + hole_shape.area
            if desired_area <= 0 or hole_shape.area <= 0:
                continue
            area_ratio = desired_area / hole_shape.area
            preserve_proportions = (
                min_width_mm == min_height_mm
                and max_width_mm == max_height_mm
            )
            scale_options: list[tuple[float, float]] = []
            if min_width_mm < max_width_mm and min_height_mm < max_height_mm:
                scale_options.append(
                    (math.sqrt(area_ratio), math.sqrt(area_ratio))
                )
            if not preserve_proportions:
                if min_width_mm < max_width_mm:
                    scale_options.append((area_ratio, 1.0))
                if min_height_mm < max_height_mm:
                    scale_options.append((1.0, area_ratio))
            for width_factor, height_factor in scale_options:
                new_width = current_width * width_factor
                new_height = current_height * height_factor
                if not (
                    min_width_mm - 1e-7
                    <= new_width
                    <= max_width_mm + 1e-7
                    and min_height_mm - 1e-7
                    <= new_height
                    <= max_height_mm + 1e-7
                ):
                    continue
                adjusted_shape = scale(
                    hole_shape,
                    xfact=width_factor,
                    yfact=height_factor,
                    origin=(0, 0),
                )
                adjusted_position = translate(
                    rotate(adjusted_shape, angle_degrees, origin=(0, 0)),
                    xoff=x,
                    yoff=y,
                )
                if not prepared.covers(adjusted_position):
                    continue
                row_index = placed_row_indices[hole_index]
                valid_spacing = True
                for other_index, (other_x, other_y, other_shape) in enumerate(
                    placed
                ):
                    if other_index == hole_index:
                        continue
                    other_position = translate(
                        rotate(other_shape, angle_degrees, origin=(0, 0)),
                        xoff=other_x,
                        yoff=other_y,
                    )
                    required_gap = (
                        min_horizontal_gap_mm
                        if placed_row_indices[other_index] == row_index
                        else min_vertical_gap_mm
                    )
                    if (
                        adjusted_position.distance(other_position)
                        < required_gap - 1e-7
                    ):
                        valid_spacing = False
                        break
                if not valid_spacing:
                    continue
                placed[hole_index] = (x, y, adjusted_shape)
                area_current += adjusted_shape.area - hole_shape.area
                break
            if math.isclose(area_current, area_target, abs_tol=1e-8):
                break
    if progress_callback is not None:
        progress_callback(100)
    return placed


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
    hole_openings: Iterable[BaseGeometry] | None = None,
) -> None:
    hole_points = list(holes)
    opening_shapes = list(hole_openings) if hole_openings is not None else None
    if opening_shapes is not None and len(opening_shapes) != len(hole_points):
        raise ValueError("Liczba kształtów otworów nie zgadza się z ich liczbą.")
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
    for index, (x, y) in enumerate(hole_points):
        current_opening = (
            opening_shapes[index]
            if opening_shapes is not None
            else opening_shape
        )
        if opening_type == "circle":
            radius = (current_opening.bounds[2] - current_opening.bounds[0]) / 2
            target.add_circle(
                (x, y), radius, dxfattribs={"layer": "OTWORY"}
            )
            continue
        placed_opening = translate(
            rotate(
                current_opening,
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
