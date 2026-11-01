import math

import ezdxf
import pytest
from shapely.affinity import translate
from shapely.geometry import MultiPolygon, Point, Polygon

from geometry import (
    export_dxf,
    generate_holes,
    generate_random_holes,
    load_dxf,
    material_clearance,
    make_opening_shape,
    open_area_percentage,
    resize_material,
)


def test_spacing_gap_and_pitch_have_expected_center_distance():
    square = Polygon([(0, 0), (100, 0), (100, 100), (0, 100)])
    opening = make_opening_shape("circle", 10)
    gap_holes = generate_holes(square, opening, 10, 0, 0, "square", "gap")
    pitch_holes = generate_holes(square, opening, 30, 0, 0, "square", "pitch")

    assert len(gap_holes) > len(pitch_holes)
    x_values = sorted({round(x, 6) for x, _ in gap_holes})
    assert all(math.isclose(b - a, 20.0) for a, b in zip(x_values, x_values[1:]))


@pytest.mark.parametrize("angle", [0.0, 37.0])
def test_staggered_pitch_is_exact_between_diagonal_neighbors(angle):
    square = Polygon([(0, 0), (60, 0), (60, 60), (0, 60)])

    holes = generate_holes(
        square, make_opening_shape("circle", 2), 10, 0, angle, "staggered", "pitch"
    )

    nearest_distance = min(
        math.dist(first, second)
        for index, first in enumerate(holes)
        for second in holes[index + 1 :]
    )
    assert nearest_distance == pytest.approx(10.0)


def test_staggered_gap_includes_diameter_in_diagonal_pitch():
    square = Polygon([(0, 0), (60, 0), (60, 60), (0, 60)])

    holes = generate_holes(
        square, make_opening_shape("circle", 4), 6, 0, 0, "staggered", "gap"
    )

    nearest_distance = min(
        math.dist(first, second)
        for index, first in enumerate(holes)
        for second in holes[index + 1 :]
    )
    assert nearest_distance == pytest.approx(10.0)


def test_pitch_allows_openings_that_touch_without_overlapping():
    square = Polygon([(0, 0), (40, 0), (40, 40), (0, 40)])

    holes = generate_holes(
        square, make_opening_shape("circle", 10), 10, 0, 0, "square", "pitch"
    )

    assert holes


def test_square_pitch_remains_equal_in_horizontal_and_vertical_directions():
    square = Polygon([(0, 0), (60, 0), (60, 60), (0, 60)])

    holes = generate_holes(
        square, make_opening_shape("circle", 2), 10, 0, 0, "square", "pitch"
    )

    x_values = sorted({round(x, 6) for x, _ in holes})
    y_values = sorted({round(y, 6) for _, y in holes})
    assert all(
        math.isclose(second - first, 10.0)
        for first, second in zip(x_values, x_values[1:])
    )
    assert all(
        math.isclose(second - first, 10.0)
        for first, second in zip(y_values, y_values[1:])
    )


def test_margin_keeps_full_holes_clear_of_outer_and_inner_edges():
    shape = Polygon(
        [(0, 0), (100, 0), (100, 100), (0, 100)],
        holes=[[(40, 40), (60, 40), (60, 60), (40, 60)]],
    )
    opening = make_opening_shape("rectangle", 4, 2)
    holes = generate_holes(shape, opening, 8, 3, 0, "square", "pitch")

    assert holes
    assert all(
        shape.buffer(-3, join_style="mitre").covers(
            translate(opening, xoff=x, yoff=y)
        )
        for x, y in holes
    )


def test_resizing_sets_exact_dimensions():
    source = Polygon([(10, 20), (110, 20), (110, 70), (10, 70)])

    resized = resize_material(source, 250.1, 125.5)

    assert resized.bounds == pytest.approx((0, 0, 250.1, 125.5))


def test_open_area_percentage_uses_net_material_area_and_hole_count():
    material = Polygon(
        [(0, 0), (10, 0), (10, 10), (0, 10)],
        holes=[[(3, 3), (7, 3), (7, 7), (3, 7)]],
    )

    opening = make_opening_shape("circle", 2)
    percentage = open_area_percentage(material, 2, opening)

    assert percentage == pytest.approx(2 * opening.area / 84 * 100)


def test_random_holes_are_reproducible_sized_and_respect_clearance():
    material = Polygon([(0, 0), (100, 0), (100, 100), (0, 100)])
    opening = make_opening_shape("slot", 10, 4)

    holes = generate_random_holes(
        material,
        opening,
        min_width_mm=6,
        max_width_mm=10,
        min_height_mm=4,
        max_height_mm=4,
        min_horizontal_gap_mm=2,
        max_horizontal_gap_mm=2,
        min_vertical_gap_mm=2,
        max_vertical_gap_mm=2,
        margin_mm=5,
        seed=123,
    )
    repeated = generate_random_holes(
        material,
        opening,
        min_width_mm=6,
        max_width_mm=10,
        min_height_mm=4,
        max_height_mm=4,
        min_horizontal_gap_mm=2,
        max_horizontal_gap_mm=2,
        min_vertical_gap_mm=2,
        max_vertical_gap_mm=2,
        margin_mm=5,
        seed=123,
    )

    assert holes == repeated
    assert holes
    assert all(
        6 <= shape.bounds[2] - shape.bounds[0] <= 10
        for _, _, shape in holes
    )
    assert all(
        shape.bounds[3] - shape.bounds[1] == pytest.approx(4)
        for _, _, shape in holes
    )
    placed = [translate(shape, xoff=x, yoff=y) for x, y, shape in holes]
    assert all(material.buffer(-5).covers(shape) for shape in placed)
    assert all(
        first.distance(second) >= 2 - 1e-7
        for index, first in enumerate(placed)
        for second in placed[index + 1 :]
    )
    assert len(holes) > 10


def test_random_holes_reject_invalid_size_range():
    plate = Polygon([(0, 0), (50, 0), (50, 50), (0, 50)])

    with pytest.raises(ValueError, match="Zakres wymiarów"):
        generate_random_holes(
            plate,
            make_opening_shape("circle", 5),
            10,
            5,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
        )


def test_random_holes_can_vary_rectangle_width_height_and_spacing():
    material = Polygon([(0, 0), (120, 0), (120, 120), (0, 120)])
    opening = make_opening_shape("rectangle", 10, 8)

    holes = generate_random_holes(
        material,
        opening,
        min_width_mm=6,
        max_width_mm=14,
        min_height_mm=4,
        max_height_mm=10,
        min_horizontal_gap_mm=1,
        max_horizontal_gap_mm=4,
        min_vertical_gap_mm=1,
        max_vertical_gap_mm=4,
        margin_mm=4,
        seed=456,
    )

    assert len(holes) > 3
    widths = {
        round(shape.bounds[2] - shape.bounds[0], 1)
        for _, _, shape in holes
    }
    heights = {
        round(shape.bounds[3] - shape.bounds[1], 1)
        for _, _, shape in holes
    }
    assert len(widths) > 1
    assert len(heights) > 1
    placed = [translate(shape, xoff=x, yoff=y) for x, y, shape in holes]
    assert all(
        first.distance(second) >= 1 - 1e-7
        for index, first in enumerate(placed)
        for second in placed[index + 1 :]
    )


def test_random_slot_is_rebuilt_as_a_capsule_instead_of_stretched_oval():
    material = Polygon([(0, 0), (100, 0), (100, 100), (0, 100)])
    opening = make_opening_shape("slot", 10, 10)

    holes = generate_random_holes(
        material,
        opening,
        min_width_mm=40,
        max_width_mm=40,
        min_height_mm=10,
        max_height_mm=10,
        min_horizontal_gap_mm=2,
        max_horizontal_gap_mm=2,
        min_vertical_gap_mm=2,
        max_vertical_gap_mm=2,
        margin_mm=2,
        seed=456,
        opening_shape_factory=lambda width, height: make_opening_shape(
            "slot", width, height
        ),
    )

    assert holes
    for _, _, shape in holes:
        assert shape.bounds[2] - shape.bounds[0] == pytest.approx(40)
        assert shape.bounds[3] - shape.bounds[1] == pytest.approx(10)
        assert shape.area == pytest.approx(30 * 10 + math.pi * 5**2, rel=1e-3)


def test_fixed_random_spacing_uses_even_rows_and_constant_horizontal_gap():
    material = Polygon([(0, 0), (100, 0), (100, 100), (0, 100)])
    opening = make_opening_shape("rectangle", 10, 8)

    holes = generate_random_holes(
        material,
        opening,
        min_width_mm=6,
        max_width_mm=14,
        min_height_mm=8,
        max_height_mm=8,
        min_horizontal_gap_mm=3,
        max_horizontal_gap_mm=3,
        min_vertical_gap_mm=3,
        max_vertical_gap_mm=3,
        margin_mm=2,
        seed=456,
    )

    placed = [
        translate(shape, xoff=x, yoff=y)
        for x, y, shape in holes
    ]
    rows: dict[float, list[Polygon]] = {}
    for shape in placed:
        rows.setdefault(round(shape.centroid.y, 6), []).append(shape)
    row_centers = sorted(rows)
    assert len(row_centers) > 1
    assert all(
        second - first == pytest.approx(11)
        for first, second in zip(row_centers, row_centers[1:])
    )
    for row in rows.values():
        row.sort(key=lambda shape: shape.bounds[0])
        assert all(
            first.distance(second) == pytest.approx(3)
            for first, second in zip(row, row[1:])
        )


def test_random_horizontal_gap_keeps_vertical_spacing_fixed():
    material = Polygon([(0, 0), (100, 0), (100, 100), (0, 100)])
    opening = make_opening_shape("rectangle", 10, 8)

    holes = generate_random_holes(
        material,
        opening,
        min_width_mm=10,
        max_width_mm=10,
        min_height_mm=8,
        max_height_mm=8,
        min_horizontal_gap_mm=1,
        max_horizontal_gap_mm=5,
        min_vertical_gap_mm=3,
        max_vertical_gap_mm=3,
        margin_mm=2,
        seed=456,
    )

    placed = [translate(shape, xoff=x, yoff=y) for x, y, shape in holes]
    rows: dict[float, list[Polygon]] = {}
    for shape in placed:
        rows.setdefault(round(shape.centroid.y, 6), []).append(shape)
    row_centers = sorted(rows)
    assert len(row_centers) > 2
    assert all(
        second - first == pytest.approx(11)
        for first, second in zip(row_centers, row_centers[1:])
    )
    horizontal_gaps = []
    for row in rows.values():
        row.sort(key=lambda shape: shape.bounds[0])
        horizontal_gaps.extend(
            first.distance(second) for first, second in zip(row, row[1:])
        )
    assert len(set(round(gap, 6) for gap in horizontal_gaps)) > 1
    assert all(1 <= gap <= 5 for gap in horizontal_gaps)


def test_random_vertical_gap_keeps_horizontal_spacing_fixed():
    material = Polygon([(0, 0), (100, 0), (100, 100), (0, 100)])
    opening = make_opening_shape("rectangle", 10, 8)

    holes = generate_random_holes(
        material,
        opening,
        min_width_mm=10,
        max_width_mm=10,
        min_height_mm=8,
        max_height_mm=8,
        min_horizontal_gap_mm=3,
        max_horizontal_gap_mm=3,
        min_vertical_gap_mm=1,
        max_vertical_gap_mm=5,
        margin_mm=2,
        seed=456,
    )

    placed = [translate(shape, xoff=x, yoff=y) for x, y, shape in holes]
    rows: dict[float, list[Polygon]] = {}
    for shape in placed:
        rows.setdefault(round(shape.centroid.y, 6), []).append(shape)
    row_centers = sorted(rows)
    assert len(row_centers) > 2
    vertical_gaps = [
        second - first - 8
        for first, second in zip(row_centers, row_centers[1:])
    ]
    assert len(set(round(gap, 6) for gap in vertical_gaps)) > 1
    assert all(1 <= gap <= 5 for gap in vertical_gaps)
    for row in rows.values():
        row.sort(key=lambda shape: shape.bounds[0])
        assert all(
            first.distance(second) == pytest.approx(3)
            for first, second in zip(row, row[1:])
        )


def test_random_holes_cover_full_height_of_u_shaped_material():
    material = Polygon(
        [
            (0, 0),
            (100, 0),
            (100, 100),
            (80, 100),
            (80, 20),
            (20, 20),
            (20, 100),
            (0, 100),
        ]
    )
    opening = make_opening_shape("square", 4)

    holes = generate_random_holes(
        material,
        opening,
        min_width_mm=4,
        max_width_mm=4,
        min_height_mm=4,
        max_height_mm=4,
        min_horizontal_gap_mm=2,
        max_horizontal_gap_mm=2,
        min_vertical_gap_mm=2,
        max_vertical_gap_mm=2,
        margin_mm=2,
        seed=789,
    )

    placed = [translate(shape, xoff=x, yoff=y) for x, y, shape in holes]
    assert min(shape.centroid.y for shape in placed) < 10
    assert max(shape.centroid.y for shape in placed) > 90
    assert any(shape.centroid.x < 20 for shape in placed if shape.centroid.y > 80)
    assert any(shape.centroid.x > 80 for shape in placed if shape.centroid.y > 80)


def test_random_holes_cover_available_segments_without_target_control():
    material = Polygon(
        [
            (0, 0),
            (1620, 0),
            (1620, 1320),
            (1400, 1320),
            (1400, 570),
            (220, 570),
            (220, 1320),
            (0, 1320),
        ],
        holes=[
            list(Point(810, 390).buffer(100).exterior.coords),
            list(Point(100, 100).buffer(25).exterior.coords),
        ],
    )

    holes = generate_random_holes(
        material,
        make_opening_shape("rectangle", 10, 10),
        min_width_mm=10,
        max_width_mm=200,
        min_height_mm=10,
        max_height_mm=10,
        min_horizontal_gap_mm=10,
        max_horizontal_gap_mm=10,
        min_vertical_gap_mm=2,
        max_vertical_gap_mm=40,
        margin_mm=10,
        inner_margin_mm=10,
        seed=20261101,
    )

    widths = [shape.bounds[2] - shape.bounds[0] for _, _, shape in holes]
    assert len(holes) > 100
    assert 80 < sum(widths) / len(widths) < 130
    assert max(widths) <= 200
    placed = [translate(shape, xoff=x, yoff=y) for x, y, shape in holes]
    assert any(
        shape.centroid.x < 220
        for shape in placed
        if shape.centroid.y > 1000
    )
    assert any(
        shape.centroid.x > 1400
        for shape in placed
        if shape.centroid.y > 1000
    )


def test_random_hole_generation_reports_progress_and_can_be_cancelled():
    plate = Polygon([(0, 0), (100, 0), (100, 100), (0, 100)])
    progress: list[int] = []

    holes = generate_random_holes(
        plate,
        make_opening_shape("circle", 4),
        min_width_mm=4,
        max_width_mm=4,
        min_height_mm=4,
        max_height_mm=4,
        min_horizontal_gap_mm=1,
        max_horizontal_gap_mm=1,
        min_vertical_gap_mm=1,
        max_vertical_gap_mm=1,
        margin_mm=2,
        seed=3,
        progress_callback=progress.append,
    )

    assert holes
    assert progress[0] == 0
    assert progress[-1] == 100
    with pytest.raises(InterruptedError, match="anulowane"):
        generate_random_holes(
            plate,
            make_opening_shape("circle", 4),
            min_width_mm=4,
            max_width_mm=4,
            min_height_mm=4,
            max_height_mm=4,
            min_horizontal_gap_mm=1,
            max_horizontal_gap_mm=1,
            min_vertical_gap_mm=1,
            max_vertical_gap_mm=1,
            margin_mm=2,
            cancellation_requested=lambda: True,
        )


@pytest.mark.parametrize(
    ("shape_type", "width", "height"),
    [
        ("circle", 12, 12),
        ("square", 12, 12),
        ("rectangle", 12, 8),
        ("triangle", 12, 12 * math.sqrt(3) / 2),
        ("ellipse", 12, 8),
        ("slot", 12, 8),
        ("regular_polygon", 12, 12 * math.sqrt(3) / 2),
    ],
)
def test_builtin_opening_shapes_have_expected_bounds(shape_type, width, height):
    opening = make_opening_shape(
        shape_type,
        12,
        8 if shape_type in {"rectangle", "ellipse", "slot"} else None,
        3,
    )

    min_x, min_y, max_x, max_y = opening.bounds
    assert max_x - min_x == pytest.approx(width)
    assert max_y - min_y == pytest.approx(height)


def test_custom_opening_keeps_aspect_ratio_and_is_centered():
    source = Polygon([(10, 20), (30, 20), (30, 30), (10, 30)])

    opening = make_opening_shape("custom", 40, custom_shape=source)

    assert opening.bounds == pytest.approx((-20, -10, 20, 10))


def test_slot_radius_is_half_its_width():
    opening = make_opening_shape("slot", 20, 9)

    assert opening.bounds == pytest.approx((-10, -4.5, 10, 4.5))
    assert opening.area == pytest.approx(11 * 9 + math.pi * 4.5**2, rel=0.002)


def test_slot_rejects_length_shorter_than_width():
    with pytest.raises(ValueError, match="Długość fasolki"):
        make_opening_shape("slot", 8, 12)


def test_inner_and_outer_margins_are_applied_independently():
    outer = Polygon(
        [(0, 0), (100, 0), (100, 100), (0, 100)],
        holes=[[(20, 20), (80, 20), (80, 80), (20, 80)]],
    )
    island = Polygon([(35, 35), (65, 35), (65, 65), (35, 65)])
    material = MultiPolygon([outer, island])

    allowed = material_clearance(material, 2, 5)

    assert allowed.bounds == pytest.approx((2, 2, 98, 98))
    assert allowed.covers(Polygon([(40, 45), (60, 45), (60, 55), (40, 55)]))
    assert not allowed.covers(Polygon([(34, 45), (66, 45), (66, 55), (34, 55)]))
    assert not allowed.covers(Polygon([(14, 45), (16, 45), (16, 55), (14, 55)]))


def test_too_small_pitch_rejects_overlapping_rectangular_openings():
    plate = Polygon([(0, 0), (100, 0), (100, 100), (0, 100)])

    with pytest.raises(ValueError, match="nachodzą na siebie"):
        generate_holes(
            plate,
            make_opening_shape("rectangle", 10, 20),
            10,
            0,
            0,
            "square",
            "pitch",
        )


def test_load_dxf_joins_connected_lines(tmp_path):
    source = tmp_path / "rounded.dxf"
    document = ezdxf.new()
    document.units = ezdxf.units.MM
    modelspace = document.modelspace()
    modelspace.add_line((0, 0), (100, 0))
    modelspace.add_line((100, 0), (100, 100))
    modelspace.add_line((100, 100), (0, 100))
    modelspace.add_line((0, 100), (0, 0))
    document.saveas(source)

    drawing = load_dxf(source)

    assert drawing.width_mm == pytest.approx(100)
    assert drawing.height_mm == pytest.approx(100)
    assert drawing.material.area == pytest.approx(10_000)


def test_load_dxf_preserves_nested_inner_contour_as_a_hole(tmp_path):
    source = tmp_path / "with_hole.dxf"
    document = ezdxf.new()
    document.units = ezdxf.units.MM
    modelspace = document.modelspace()
    modelspace.add_lwpolyline(
        [(0, 0), (100, 0), (100, 100), (0, 100)], close=True
    )
    modelspace.add_lwpolyline(
        [(30, 30), (70, 30), (70, 70), (30, 70)], close=True
    )
    document.saveas(source)

    drawing = load_dxf(source)

    assert drawing.material.area == pytest.approx(8_400)
    assert len(drawing.material.interiors) == 1
    opening = make_opening_shape(
        "custom", 200, custom_shape=drawing.material
    )
    assert opening.bounds == pytest.approx((-100, -100, 100, 100))
    assert opening.area == pytest.approx(8_400 * 4)


def test_load_dxf_flattens_circle_entity(tmp_path):
    source = tmp_path / "circle.dxf"
    document = ezdxf.new()
    document.units = ezdxf.units.MM
    document.modelspace().add_circle((20, 30), 10)
    document.saveas(source)

    drawing = load_dxf(source)

    assert drawing.width_mm == pytest.approx(20, abs=0.01)
    assert drawing.height_mm == pytest.approx(20, abs=0.01)
    assert drawing.material.area == pytest.approx(math.pi * 100, rel=0.006)


def test_export_writes_outline_and_circle_entities(tmp_path):
    destination = tmp_path / "output.dxf"
    shape = Polygon([(0, 0), (20, 0), (20, 20), (0, 20)])

    export_dxf(
        destination,
        shape,
        [(10, 10)],
        make_opening_shape("circle", 4),
        "circle",
    )

    modelspace = ezdxf.readfile(destination).modelspace()
    assert [entity.dxftype() for entity in modelspace] == [
        "LWPOLYLINE",
        "CIRCLE",
    ]


def test_export_writes_rotated_rectangular_opening_as_closed_polyline(tmp_path):
    destination = tmp_path / "rectangle.dxf"
    material = Polygon([(0, 0), (20, 0), (20, 20), (0, 20)])

    export_dxf(
        destination,
        material,
        [(10, 10)],
        make_opening_shape("rectangle", 10, 4),
        "rectangle",
        90,
    )

    modelspace = ezdxf.readfile(destination).modelspace()
    opening = list(modelspace)[1]
    points = list(opening.get_points("xy"))
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    assert opening.dxftype() == "LWPOLYLINE"
    assert opening.closed
    assert min(xs) == pytest.approx(8)
    assert max(xs) == pytest.approx(12)
    assert min(ys) == pytest.approx(5)
    assert max(ys) == pytest.approx(15)


def test_export_writes_per_hole_randomized_opening_sizes(tmp_path):
    destination = tmp_path / "random_sizes.dxf"
    material = Polygon([(0, 0), (50, 0), (50, 50), (0, 50)])
    opening = make_opening_shape("circle", 4)
    hole_openings = [
        make_opening_shape("circle", 4),
        make_opening_shape("circle", 8),
    ]

    export_dxf(
        destination,
        material,
        [(10, 10), (30, 30)],
        opening,
        "circle",
        hole_openings=hole_openings,
    )

    circles = [
        entity
        for entity in ezdxf.readfile(destination).modelspace()
        if entity.dxftype() == "CIRCLE"
    ]
    assert [circle.dxf.radius for circle in circles] == pytest.approx([2, 4])


def test_export_rotates_opening_independently_of_grid(tmp_path):
    destination = tmp_path / "rotated_slot.dxf"
    material = Polygon([(0, 0), (30, 0), (30, 30), (0, 30)])

    export_dxf(
        destination,
        material,
        [(15, 15)],
        make_opening_shape("slot", 20, 5),
        "slot",
        opening_angle_degrees=90,
    )

    opening = list(ezdxf.readfile(destination).modelspace())[1]
    points = list(opening.get_points("xy"))
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    assert max(xs) - min(xs) == pytest.approx(5)
    assert max(ys) - min(ys) == pytest.approx(20)


@pytest.mark.parametrize("as_block", [False, True])
def test_exported_perforation_can_be_reimported_without_old_holes(
    tmp_path, as_block
):
    destination = tmp_path / "reimport.dxf"
    material = Polygon([(0, 0), (20, 0), (20, 20), (0, 20)])

    export_dxf(
        destination,
        material,
        [(10, 10), (15, 15)],
        make_opening_shape("slot", 8, 3),
        "slot",
        perforation_as_block=as_block,
    )

    drawing = load_dxf(destination)

    assert drawing.width_mm == pytest.approx(20)
    assert drawing.height_mm == pytest.approx(20)
    assert drawing.material.area == pytest.approx(400)
    document = ezdxf.readfile(destination)
    assert document.layers.has_entry("OBRYS")
    assert document.layers.has_entry("OTWORY")
    if as_block:
        inserts = [
            entity
            for entity in document.modelspace()
            if entity.dxftype() == "INSERT"
        ]
        assert len(inserts) == 1
        assert inserts[0].dxf.layer == "OTWORY"
        assert len(document.blocks.get("PERFORACJA")) == 2
