import math

import ezdxf
import pytest
from shapely.geometry import Point, Polygon

from geometry import export_dxf, generate_holes, load_dxf, resize_material


def test_spacing_gap_and_pitch_have_expected_center_distance():
    square = Polygon([(0, 0), (100, 0), (100, 100), (0, 100)])
    gap_holes = generate_holes(square, 10, 10, 0, 0, "square", "gap")
    pitch_holes = generate_holes(square, 10, 30, 0, 0, "square", "pitch")

    assert len(gap_holes) > len(pitch_holes)
    x_values = sorted({round(x, 6) for x, _ in gap_holes})
    assert all(math.isclose(b - a, 20.0) for a, b in zip(x_values, x_values[1:]))


@pytest.mark.parametrize("angle", [0.0, 37.0])
def test_staggered_pitch_is_exact_between_diagonal_neighbors(angle):
    square = Polygon([(0, 0), (60, 0), (60, 60), (0, 60)])

    holes = generate_holes(square, 2, 10, 0, angle, "staggered", "pitch")

    nearest_distance = min(
        math.dist(first, second)
        for index, first in enumerate(holes)
        for second in holes[index + 1 :]
    )
    assert nearest_distance == pytest.approx(10.0)


def test_staggered_gap_includes_diameter_in_diagonal_pitch():
    square = Polygon([(0, 0), (60, 0), (60, 60), (0, 60)])

    holes = generate_holes(square, 4, 6, 0, 0, "staggered", "gap")

    nearest_distance = min(
        math.dist(first, second)
        for index, first in enumerate(holes)
        for second in holes[index + 1 :]
    )
    assert nearest_distance == pytest.approx(10.0)


def test_square_pitch_remains_equal_in_horizontal_and_vertical_directions():
    square = Polygon([(0, 0), (60, 0), (60, 60), (0, 60)])

    holes = generate_holes(square, 2, 10, 0, 0, "square", "pitch")

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
    holes = generate_holes(shape, 4, 8, 3, 0, "square", "pitch")

    assert holes
    assert all(
        shape.boundary.distance(Point(point)) >= 5.0 - 1e-7
        for point in holes
    )


def test_resizing_sets_exact_dimensions():
    source = Polygon([(10, 20), (110, 20), (110, 70), (10, 70)])

    resized = resize_material(source, 250.1, 125.5)

    assert resized.bounds == pytest.approx((0, 0, 250.1, 125.5))


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

    export_dxf(destination, shape, [(10, 10)], 4)

    modelspace = ezdxf.readfile(destination).modelspace()
    assert [entity.dxftype() for entity in modelspace] == [
        "LWPOLYLINE",
        "CIRCLE",
    ]
