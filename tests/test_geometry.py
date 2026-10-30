import math

import ezdxf
import pytest
from shapely.affinity import translate
from shapely.geometry import MultiPolygon, Polygon

from geometry import (
    export_dxf,
    generate_holes,
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


def test_slot_has_rounded_ends_and_requested_overall_dimensions():
    opening = make_opening_shape("slot", 20, 9, radius_mm=4.5)

    assert opening.bounds == pytest.approx((-10, -4.5, 10, 4.5))
    assert opening.area == pytest.approx(11 * 9 + math.pi * 4.5**2, rel=0.002)


def test_slot_uses_independent_radius_instead_of_fixed_semicircles():
    opening = make_opening_shape("slot", 20, 9, radius_mm=2)

    assert opening.bounds == pytest.approx((-10, -4.5, 10, 4.5))
    assert opening.area == pytest.approx(
        20 * 9 - (4 - math.pi) * 2**2, rel=0.0001
    )


@pytest.mark.parametrize("radius", [-0.1, 4.6])
def test_slot_rejects_radius_outside_shorter_dimension(radius):
    with pytest.raises(ValueError, match="Promień fasolki"):
        make_opening_shape("slot", 20, 9, radius_mm=radius)


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
