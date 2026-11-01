from __future__ import annotations

import json
import secrets
import sys
from pathlib import Path
from threading import Event
from typing import Callable

import ezdxf
from PyQt5.QtCore import (
    QObject,
    QPoint,
    QPointF,
    QThread,
    Qt,
    pyqtSignal,
    pyqtSlot,
)
from PyQt5.QtGui import QColor, QPainter, QPainterPath, QPen
from PyQt5.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QProgressDialog,
    QSplitter,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)
from shapely.errors import GEOSException
from shapely.geometry import MultiPolygon, Polygon
from shapely.geometry.base import BaseGeometry

from perforation_settings import (
    PerforationSettings,
    load_perforation_settings,
    save_perforation_settings,
)
from geometry import (
    Drawing,
    export_dxf,
    generate_holes,
    generate_random_holes,
    load_dxf,
    material_clearance,
    make_opening_shape,
    open_area_percentage,
    resize_material,
)


class RandomPerforationWorker(QObject):
    progress = pyqtSignal(int)
    completed = pyqtSignal(object)
    failed = pyqtSignal(str)
    cancelled = pyqtSignal()

    def __init__(
        self,
        calculate: Callable[
            [Callable[[int], None], Callable[[], bool]],
            list[tuple[float, float, BaseGeometry]],
        ],
        cancellation: Event,
    ) -> None:
        super().__init__()
        self.calculate = calculate
        self.cancellation = cancellation

    @pyqtSlot()
    def run(self) -> None:
        try:
            result = self.calculate(
                self.progress.emit, self.cancellation.is_set
            )
        except InterruptedError:
            self.cancelled.emit()
        except (ValueError, GEOSException) as error:
            self.failed.emit(str(error))
        else:
            self.completed.emit(result)


class Preview(QWidget):
    zoomChanged = pyqtSignal(float)

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.title = title
        self.material: BaseGeometry | None = None
        self.holes: list[tuple[float, float]] = []
        self.opening_shape: BaseGeometry | None = None
        self.opening_type = "circle"
        self.margin = 0.0
        self.inner_margin = 0.0
        self.angle = 0.0
        self.show_margin = True
        self.zoom_factor = 1.0
        self.pan_offset = QPointF()
        self._drag_position: QPoint | None = None
        self.setCursor(Qt.OpenHandCursor)
        self.setMinimumSize(320, 300)

    def set_zoom(self, zoom_factor: float) -> None:
        self.zoom_factor = min(max(zoom_factor, 0.1), 20.0)
        self.zoomChanged.emit(self.zoom_factor)
        self.update()

    def reset_zoom(self) -> None:
        self.set_zoom(1.0)
        self.pan_offset = QPointF()
        self.update()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._drag_position = event.pos()
            self.setCursor(Qt.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._drag_position is not None:
            delta = event.pos() - self._drag_position
            self.pan_offset += QPointF(delta.x(), delta.y())
            self._drag_position = event.pos()
            self.update()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self._drag_position is not None:
            self._drag_position = None
            self.setCursor(Qt.OpenHandCursor)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event) -> None:
        steps = event.angleDelta().y() / 120
        if steps:
            self.set_zoom(self.zoom_factor * 1.15**steps)
            event.accept()
            return
        event.ignore()

    def set_data(
        self,
        material: BaseGeometry | None,
        holes: list[tuple[float, float]] | None = None,
        opening_shape: BaseGeometry | None = None,
        margin: float = 0.0,
        angle: float = 0.0,
        opening_type: str = "circle",
        inner_margin: float | None = None,
        opening_angle: float = 0.0,
        hole_openings: list[BaseGeometry] | None = None,
    ) -> None:
        self.material = material
        self.holes = holes or []
        self.opening_shape = opening_shape
        self.opening_type = opening_type
        self.margin = margin
        self.angle = angle + opening_angle
        self.inner_margin = margin if inner_margin is None else inner_margin
        self.hole_openings = hole_openings or []
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor("#101827"))
        painter.setPen(QColor("#cbd5e1"))
        painter.drawText(16, 24, self.title)
        if self.material is None or self.material.is_empty:
            painter.setPen(QColor("#8493a8"))
            painter.drawText(self.rect(), Qt.AlignCenter, "Wczytaj plik DXF")
            return

        min_x, min_y, max_x, max_y = self.material.bounds
        width = max(max_x - min_x, 1e-9)
        height = max(max_y - min_y, 1e-9)
        padding = 36.0
        factor = min(
            max((self.width() - 2 * padding) / width, 1e-9),
            max((self.height() - 2 * padding) / height, 1e-9),
        ) * self.zoom_factor
        painter.translate(
            self.width() / 2 + self.pan_offset.x(),
            self.height() / 2 + 5 + self.pan_offset.y(),
        )
        painter.scale(factor, -factor)
        painter.translate(-(min_x + max_x) / 2, -(min_y + max_y) / 2)

        outline = _geometry_path(self.material)
        painter.setPen(QPen(QColor("#f4d84b"), max(1.0 / factor, 0.25 / factor)))
        painter.setBrush(QColor(21, 179, 205, 48))
        painter.drawPath(outline)
        if self.show_margin and (
            self.margin > 0 or self.inner_margin > 0
        ):
            clearance = material_clearance(
                self.material, self.margin, self.inner_margin
            )
            if not clearance.is_empty:
                pen = QPen(QColor("#d378ce"), max(0.8 / factor, 0.2 / factor))
                pen.setStyle(Qt.DashLine)
                painter.setPen(pen)
                painter.setBrush(Qt.NoBrush)
                painter.drawPath(_geometry_path(clearance))
        if self.holes and self.opening_shape is not None:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor("#16c9df"))
            if self.hole_openings:
                for (x, y), opening in zip(self.holes, self.hole_openings):
                    painter.save()
                    painter.translate(x, y)
                    painter.rotate(self.angle)
                    painter.drawPath(_geometry_path(opening))
                    painter.restore()
            elif self.opening_type == "circle":
                radius = (
                    self.opening_shape.bounds[2]
                    - self.opening_shape.bounds[0]
                ) / 2
                for x, y in self.holes:
                    painter.drawEllipse(QPointF(x, y), radius, radius)
            else:
                opening_path = _geometry_path(self.opening_shape)
                for x, y in self.holes:
                    painter.save()
                    painter.translate(x, y)
                    painter.rotate(self.angle)
                    painter.drawPath(opening_path)
                    painter.restore()


def _geometry_path(geometry: BaseGeometry) -> QPainterPath:
    path = QPainterPath()
    path.setFillRule(Qt.OddEvenFill)
    polygons = [geometry] if isinstance(geometry, Polygon) else (
        list(geometry.geoms) if isinstance(geometry, MultiPolygon) else []
    )
    for polygon in polygons:
        for ring in [polygon.exterior, *polygon.interiors]:
            coordinates = list(ring.coords)
            if not coordinates:
                continue
            path.moveTo(coordinates[0][0], coordinates[0][1])
            for x, y in coordinates[1:]:
                path.lineTo(x, y)
            path.closeSubpath()
    return path


def _dimension_input(value: float = 100.0) -> QDoubleSpinBox:
    field = QDoubleSpinBox()
    field.setDecimals(1)
    field.setRange(0.1, 100_000.0)
    field.setSingleStep(5.0)
    field.setValue(value)
    field.setSuffix(" mm")
    return field


def _parameter_input(
    value: float, minimum: float, maximum: float, step: float = 1.0
) -> QDoubleSpinBox:
    field = QDoubleSpinBox()
    field.setDecimals(1)
    field.setRange(minimum, maximum)
    field.setSingleStep(step)
    field.setValue(value)
    field.setSuffix(" mm")
    return field


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Perforacja DXF")
        self.resize(1440, 900)
        self.setMinimumSize(1120, 700)
        self.drawing: Drawing | None = None
        self.source_path: Path | None = None
        self.preview_material: BaseGeometry | None = None
        self.preview_holes: list[tuple[float, float]] = []
        self.preview_opening: BaseGeometry | None = None
        self.preview_hole_shapes: list[BaseGeometry] = []
        self.custom_opening: BaseGeometry | None = None
        self.custom_opening_warnings: tuple[str, ...] = ()
        self.random_seed = secrets.randbits(32)
        self._random_result_current = False
        self._random_thread: QThread | None = None
        self._random_worker: RandomPerforationWorker | None = None
        self._random_cancellation: Event | None = None
        self._random_progress: QProgressDialog | None = None
        self._random_pending_material: BaseGeometry | None = None
        self._random_pending_opening: BaseGeometry | None = None
        self._build_ui()

    def _build_ui(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow, QWidget { background: #101827; color: #e2e8f0; }
            QFrame#controls { background: #151f30; }
            QLabel#muted { color: #9aa9bd; }
            QPushButton {
                background: #183247; border: 1px solid #2e7185;
                border-radius: 6px; padding: 8px 12px; color: #e2e8f0;
            }
            QPushButton:hover { background: #20506a; }
            QPushButton:disabled { color: #738095; background: #202a39; }
            QDoubleSpinBox, QComboBox, QLineEdit {
                background: #0e1624; border: 1px solid #36465c;
                border-radius: 4px; padding: 5px;
            }
            QSplitter::handle { background: #263347; width: 3px; }
            """
        )
        root = QWidget()
        main_layout = QVBoxLayout(root)
        main_layout.setContentsMargins(10, 10, 10, 10)
        header = QHBoxLayout()
        title = QLabel("Perforacja DXF")
        title.setStyleSheet("font-size: 22px; font-weight: 700; color: #20c6d9;")
        header.addWidget(title)
        header.addStretch()
        open_button = QPushButton("Otwórz DXF")
        open_button.clicked.connect(self._choose_input)
        header.addWidget(open_button)
        settings_button = QPushButton("Wczytaj ustawienia")
        settings_button.clicked.connect(self._choose_settings)
        header.addWidget(settings_button)
        self.export_button = QPushButton("Eksportuj DXF")
        self.export_button.clicked.connect(self._export)
        self.export_button.setEnabled(False)
        header.addWidget(self.export_button)
        main_layout.addLayout(header)

        splitter = QSplitter(Qt.Horizontal)
        controls = self._build_controls()
        splitter.addWidget(controls)
        preview_area = QWidget()
        self.source_preview = Preview("RYSUNEK ŹRÓDŁOWY")
        self.output_preview = Preview("PODGLĄD PERFORACJI")
        preview_layout = QVBoxLayout(preview_area)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        preview_layout.setSpacing(8)
        preview_toolbar = QHBoxLayout()
        self.source_preview_toggle = QCheckBox("Pokaż rysunek źródłowy")
        self.source_preview_toggle.setChecked(True)
        self.source_preview_toggle.toggled.connect(
            lambda visible: self.source_preview.setVisible(visible)
        )
        preview_toolbar.addWidget(self.source_preview_toggle)
        preview_toolbar.addStretch()
        preview_toolbar.addWidget(QLabel("Zoom podglądu:"))
        zoom_out_button = QPushButton("−")
        zoom_out_button.setToolTip("Pomniejsz podgląd")
        zoom_out_button.clicked.connect(
            lambda: self.output_preview.set_zoom(
                self.output_preview.zoom_factor / 1.25
            )
        )
        preview_toolbar.addWidget(zoom_out_button)
        self.zoom_label = QLabel("100%")
        self.zoom_label.setMinimumWidth(48)
        self.zoom_label.setAlignment(Qt.AlignCenter)
        preview_toolbar.addWidget(self.zoom_label)
        zoom_in_button = QPushButton("+")
        zoom_in_button.setToolTip("Powiększ podgląd")
        zoom_in_button.clicked.connect(
            lambda: self.output_preview.set_zoom(
                self.output_preview.zoom_factor * 1.25
            )
        )
        preview_toolbar.addWidget(zoom_in_button)
        fit_button = QPushButton("Dopasuj")
        fit_button.setToolTip("Dopasuj rysunek do podglądu")
        fit_button.clicked.connect(self.output_preview.reset_zoom)
        preview_toolbar.addWidget(fit_button)
        preview_layout.addLayout(preview_toolbar)

        previews = QHBoxLayout()
        previews.setContentsMargins(0, 0, 0, 0)
        previews.setSpacing(8)
        self.output_preview.zoomChanged.connect(
            lambda zoom: self.zoom_label.setText(f"{zoom:.0%}")
        )
        previews.addWidget(self.source_preview)
        previews.addWidget(self.output_preview)
        preview_layout.addLayout(previews, 1)
        splitter.addWidget(preview_area)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([350, 1050])
        main_layout.addWidget(splitter, 1)
        self.status = QLabel("Wczytaj plik DXF, aby rozpocząć.")
        self.status.setObjectName("muted")
        self.status.setWordWrap(True)
        main_layout.addWidget(self.status)
        self.setCentralWidget(root)

    def _build_controls(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("controls")
        panel.setMinimumWidth(310)
        panel.setMaximumWidth(390)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 14, 16, 14)

        def section(name: str) -> None:
            label = QLabel(name)
            label.setStyleSheet(
                "font-weight: 700; color: #20c6d9; margin-top: 8px;"
            )
            layout.addWidget(label)

        section("WYMIAR GOTOWEGO DETALU")
        dimensions = QFormLayout()
        self.width_input = _dimension_input()
        self.height_input = _dimension_input()
        dimensions.addRow("Szerokość:", self.width_input)
        dimensions.addRow("Wysokość:", self.height_input)
        layout.addLayout(dimensions)

        section("UKŁAD I OTWORY")
        form = QFormLayout()
        self.layout_mode_input = QComboBox()
        self.layout_mode_input.addItem("Regularna siatka", "grid")
        self.layout_mode_input.addItem("Losowy", "random")
        form.addRow("Rozmieszczenie:", self.layout_mode_input)
        self.pattern_input = QComboBox()
        self.pattern_input.addItem("Prosty (kwadratowy)", "square")
        self.pattern_input.addItem("Mijankowy", "staggered")
        self.pattern_label = QLabel("Układ:")
        form.addRow(self.pattern_label, self.pattern_input)
        self.opening_type_input = QComboBox()
        self.opening_type_input.addItem("Koło", "circle")
        self.opening_type_input.addItem("Kwadrat", "square")
        self.opening_type_input.addItem("Prostokąt", "rectangle")
        self.opening_type_input.addItem("Trójkąt równoboczny", "triangle")
        self.opening_type_input.addItem("Owal / elipsa", "ellipse")
        self.opening_type_input.addItem("Fasolka", "slot")
        self.opening_type_input.addItem("Wielokąt foremny", "regular_polygon")
        self.opening_type_input.addItem("Własny kształt z DXF", "custom")
        form.addRow("Kształt otworu:", self.opening_type_input)
        self.opening_width_input = _parameter_input(10.0, 0.1, 5000.0)
        self.opening_width_label = QLabel("Średnica otworu:")
        form.addRow(self.opening_width_label, self.opening_width_input)
        self.opening_height_input = _parameter_input(10.0, 0.1, 5000.0)
        self.opening_height_label = QLabel("Wysokość otworu:")
        form.addRow(self.opening_height_label, self.opening_height_input)
        self.polygon_sides_input = QSpinBox()
        self.polygon_sides_input.setRange(3, 20)
        self.polygon_sides_input.setValue(6)
        self.polygon_sides_label = QLabel("Liczba boków:")
        form.addRow(self.polygon_sides_label, self.polygon_sides_input)
        self.custom_opening_row = QWidget()
        custom_shape_layout = QVBoxLayout(self.custom_opening_row)
        custom_shape_layout.setContentsMargins(0, 0, 0, 0)
        self.custom_opening_button = QPushButton("Wczytaj kształt DXF…")
        self.custom_opening_button.clicked.connect(self._choose_opening_shape)
        custom_shape_layout.addWidget(self.custom_opening_button)
        self.custom_opening_name = QLabel("Nie wczytano pliku.")
        self.custom_opening_name.setObjectName("muted")
        self.custom_opening_name.setWordWrap(True)
        custom_shape_layout.addWidget(self.custom_opening_name)
        self.custom_opening_row_label = QLabel("Własny kształt:")
        form.addRow(self.custom_opening_row_label, self.custom_opening_row)
        self.spacing_input = _parameter_input(10.0, 0.1, 10_000.0)
        self.spacing_label = QLabel("Odstęp / podziałka:")
        form.addRow(self.spacing_label, self.spacing_input)
        self.spacing_mode = QComboBox()
        self.spacing_mode.addItem("Odstęp między krawędziami", "gap")
        self.spacing_mode.addItem("Podziałka osiowa", "pitch")
        self.spacing_mode_label = QLabel("Tryb odległości:")
        form.addRow(self.spacing_mode_label, self.spacing_mode)
        self.angle_input = QDoubleSpinBox()
        self.angle_input.setDecimals(1)
        self.angle_input.setRange(-180.0, 180.0)
        self.angle_input.setSingleStep(5.0)
        self.angle_input.setSuffix("°")
        self.angle_label = QLabel("Kąt siatki:")
        form.addRow(self.angle_label, self.angle_input)
        self.opening_angle_input = QDoubleSpinBox()
        self.opening_angle_input.setDecimals(1)
        self.opening_angle_input.setRange(-180.0, 180.0)
        self.opening_angle_input.setSingleStep(5.0)
        self.opening_angle_input.setSuffix("°")
        self.opening_angle_label = QLabel("Kąt kształtu względem siatki:")
        form.addRow(self.opening_angle_label, self.opening_angle_input)
        self.margin_input = _parameter_input(10.0, 0.0, 5000.0)
        form.addRow("Margines od krawędzi zewnętrznej:", self.margin_input)
        self.inner_margin_input = _parameter_input(10.0, 0.0, 5000.0)
        form.addRow(
            "Margines od krawędzi wewnętrznej / wyspy:",
            self.inner_margin_input,
        )
        def dimension_range_row(
            minimum: float,
            maximum: float,
            lower_bound: float = 0.1,
            upper_bound: float = 5000.0,
        ) -> tuple[QWidget, QDoubleSpinBox, QDoubleSpinBox]:
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.addWidget(QLabel("min"))
            minimum_input = _parameter_input(
                minimum, lower_bound, upper_bound
            )
            minimum_input.setMinimumWidth(115)
            row_layout.addWidget(minimum_input)
            row_layout.addWidget(QLabel("max"))
            maximum_input = _parameter_input(
                maximum, lower_bound, upper_bound
            )
            maximum_input.setMinimumWidth(115)
            row_layout.addWidget(maximum_input)
            return row, minimum_input, maximum_input

        self.randomize_width_input = QCheckBox("Losuj szerokość")
        self.randomize_width_input.setChecked(True)
        form.addRow(self.randomize_width_input)
        (
            self.random_width_range,
            self.random_min_width_input,
            self.random_max_width_input,
        ) = dimension_range_row(10.0, 20.0)
        self.random_width_range_label = QLabel("Zakres szerokości:")
        form.addRow(self.random_width_range_label)
        form.addRow(self.random_width_range)
        self.randomize_height_input = QCheckBox("Losuj wysokość")
        form.addRow(self.randomize_height_input)
        (
            self.random_height_range,
            self.random_min_height_input,
            self.random_max_height_input,
        ) = dimension_range_row(10.0, 20.0)
        self.random_height_range_label = QLabel("Zakres wysokości:")
        form.addRow(self.random_height_range_label)
        form.addRow(self.random_height_range)
        self.randomize_horizontal_gap_input = QCheckBox(
            "Losuj odstęp poziomy"
        )
        form.addRow(self.randomize_horizontal_gap_input)
        (
            self.random_horizontal_gap_range,
            self.random_min_horizontal_gap_input,
            self.random_max_horizontal_gap_input,
        ) = dimension_range_row(2.0, 8.0, 0.0, 10_000.0)
        self.random_horizontal_gap_range_label = QLabel(
            "Zakres odstępu poziomego:"
        )
        form.addRow(self.random_horizontal_gap_range_label)
        form.addRow(self.random_horizontal_gap_range)
        self.randomize_vertical_gap_input = QCheckBox(
            "Losuj odstęp pionowy"
        )
        form.addRow(self.randomize_vertical_gap_input)
        (
            self.random_vertical_gap_range,
            self.random_min_vertical_gap_input,
            self.random_max_vertical_gap_input,
        ) = dimension_range_row(2.0, 8.0, 0.0, 10_000.0)
        self.random_vertical_gap_range_label = QLabel(
            "Zakres odstępu pionowego:"
        )
        form.addRow(self.random_vertical_gap_range_label)
        form.addRow(self.random_vertical_gap_range)
        self.regenerate_random_button = QPushButton("Losuj losowy układ")
        form.addRow(self.regenerate_random_button)
        layout.addLayout(form)

        section("PLIK WYJŚCIOWY")
        self.perforation_export_input = QComboBox()
        self.perforation_export_input.addItem(
            "Otwory jako osobne obiekty", False
        )
        self.perforation_export_input.addItem(
            "Perforacja jako jeden blok", True
        )
        layout.addWidget(self.perforation_export_input)
        output_row = QHBoxLayout()
        self.output_path = QLineEdit()
        self.output_path.setPlaceholderText("Wybierz nazwę pliku DXF…")
        output_row.addWidget(self.output_path, 1)
        browse_button = QPushButton("…")
        browse_button.setFixedWidth(40)
        browse_button.clicked.connect(self._choose_output)
        output_row.addWidget(browse_button)
        layout.addLayout(output_row)
        layout.addStretch()

        self.opening_type_input.currentIndexChanged.connect(
            self._opening_type_changed
        )
        for field in (
            self.width_input,
            self.height_input,
            self.pattern_input,
            self.opening_width_input,
            self.opening_height_input,
            self.spacing_input,
            self.spacing_mode,
            self.angle_input,
            self.opening_angle_input,
            self.margin_input,
            self.inner_margin_input,
            self.random_min_width_input,
            self.random_max_width_input,
            self.random_min_height_input,
            self.random_max_height_input,
            self.random_min_horizontal_gap_input,
            self.random_max_horizontal_gap_input,
            self.random_min_vertical_gap_input,
            self.random_max_vertical_gap_input,
            self.polygon_sides_input,
            self.randomize_width_input,
            self.randomize_height_input,
            self.randomize_horizontal_gap_input,
            self.randomize_vertical_gap_input,
        ):
            signal = (
                field.valueChanged
                if isinstance(field, (QDoubleSpinBox, QSpinBox))
                else (
                    field.currentIndexChanged
                    if isinstance(field, QComboBox)
                    else field.toggled
                )
            )
            signal.connect(self._parameters_changed)
        self.layout_mode_input.currentIndexChanged.connect(
            self._layout_mode_changed
        )
        self.regenerate_random_button.clicked.connect(
            self._generate_random_on_request
        )
        self._update_opening_controls()
        self._update_random_controls()
        return panel

    def _choose_input(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(
            self, "Otwórz rysunek DXF", "", "Pliki DXF (*.dxf)"
        )
        if filename:
            self._load_file(Path(filename))

    def _choose_settings(self) -> None:
        if self.drawing is None:
            QMessageBox.warning(
                self,
                "Najpierw wczytaj DXF",
                "Przed wczytaniem ustawień otwórz rysunek DXF.",
            )
            return
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Wczytaj ustawienia perforacji",
            "",
            "Pliki konfiguracji (*.json)",
        )
        if not filename:
            return
        try:
            settings = load_perforation_settings(filename)
            self._apply_settings(settings)
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
            QMessageBox.critical(
                self, "Nie można wczytać ustawień", str(error)
            )
            return
        QMessageBox.information(
            self,
            "Wczytano ustawienia",
            f"Wczytano ustawienia z:\n{filename}",
        )

    def _apply_settings(self, settings: PerforationSettings) -> None:
        fields = (
            self.width_input,
            self.height_input,
            self.layout_mode_input,
            self.pattern_input,
            self.opening_type_input,
            self.opening_width_input,
            self.opening_height_input,
            self.polygon_sides_input,
            self.spacing_input,
            self.spacing_mode,
            self.angle_input,
            self.opening_angle_input,
            self.margin_input,
            self.inner_margin_input,
            self.perforation_export_input,
            self.randomize_width_input,
            self.randomize_height_input,
            self.randomize_horizontal_gap_input,
            self.randomize_vertical_gap_input,
            self.random_min_width_input,
            self.random_max_width_input,
            self.random_min_height_input,
            self.random_max_height_input,
            self.random_min_horizontal_gap_input,
            self.random_max_horizontal_gap_input,
            self.random_min_vertical_gap_input,
            self.random_max_vertical_gap_input,
        )
        previous_signal_states = [
            (field, field.blockSignals(True)) for field in fields
        ]
        try:
            self.width_input.setValue(settings.width_mm)
            self.height_input.setValue(settings.height_mm)
            self.layout_mode_input.setCurrentIndex(
                self.layout_mode_input.findData(settings.layout_mode)
            )
            self.pattern_input.setCurrentIndex(
                self.pattern_input.findData(settings.pattern)
            )
            self.opening_type_input.setCurrentIndex(
                self.opening_type_input.findData(settings.opening_type)
            )
            self.opening_width_input.setValue(settings.opening_width_mm)
            self.opening_height_input.setValue(settings.opening_height_mm)
            self.polygon_sides_input.setValue(settings.polygon_sides)
            self.spacing_input.setValue(settings.spacing_mm)
            self.spacing_mode.setCurrentIndex(
                self.spacing_mode.findData(settings.spacing_mode)
            )
            self.angle_input.setValue(settings.grid_angle_degrees)
            self.opening_angle_input.setValue(settings.opening_angle_degrees)
            self.margin_input.setValue(settings.outer_margin_mm)
            self.inner_margin_input.setValue(settings.inner_margin_mm)
            self.randomize_width_input.setChecked(settings.randomize_width)
            self.randomize_height_input.setChecked(settings.randomize_height)
            self.randomize_horizontal_gap_input.setChecked(
                settings.randomize_horizontal_gap
            )
            self.randomize_vertical_gap_input.setChecked(
                settings.randomize_vertical_gap
            )
            self.random_min_width_input.setValue(settings.random_min_width_mm)
            self.random_max_width_input.setValue(settings.random_max_width_mm)
            self.random_min_height_input.setValue(settings.random_min_height_mm)
            self.random_max_height_input.setValue(settings.random_max_height_mm)
            self.random_min_horizontal_gap_input.setValue(
                settings.random_min_horizontal_gap_mm
            )
            self.random_max_horizontal_gap_input.setValue(
                settings.random_max_horizontal_gap_mm
            )
            self.random_min_vertical_gap_input.setValue(
                settings.random_min_vertical_gap_mm
            )
            self.random_max_vertical_gap_input.setValue(
                settings.random_max_vertical_gap_mm
            )
            self.random_seed = settings.random_seed
            self.perforation_export_input.setCurrentIndex(
                self.perforation_export_input.findData(
                    settings.perforation_as_block
                )
            )
            self.custom_opening = settings.custom_opening
            self.custom_opening_warnings = ()
            self.custom_opening_name.setText(
                "Kształt zapisany w konfiguracji."
                if settings.custom_opening is not None
                else "Nie wczytano pliku."
            )
        finally:
            for field, previous_state in previous_signal_states:
                field.blockSignals(previous_state)
        self._update_opening_controls()
        self._update_random_controls()
        if settings.layout_mode == "random":
            self._layout_mode_changed()
        else:
            self._refresh()

    def _choose_output(self) -> None:
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Zapisz perforowany detal",
            self.output_path.text(),
            "Pliki DXF (*.dxf)",
        )
        if filename:
            destination = Path(filename)
            if destination.suffix.lower() != ".dxf":
                destination = destination.with_suffix(".dxf")
            self.output_path.setText(str(destination))

    def _opening_type_changed(self, *_args) -> None:
        self._update_opening_controls()
        self._parameters_changed()

    def _parameters_changed(self, *_args) -> None:
        self._update_random_controls()
        if self.layout_mode_input.currentData() == "random":
            self._random_result_current = False
            self.export_button.setEnabled(False)
            self.status.setStyleSheet("color: #fbbf24;")
            self.status.setText(
                "Parametry zmienione — kliknij „Losuj losowy układ”, "
                "aby przeliczyć perforację."
            )
            return
        self._refresh()

    def _layout_mode_changed(self, *_args) -> None:
        self._update_random_controls()
        if self.layout_mode_input.currentData() == "random":
            self._random_result_current = False
            self.preview_material = None
            self.preview_holes = []
            self.preview_opening = None
            self.preview_hole_shapes = []
            self.output_preview.set_data(None)
            self.export_button.setEnabled(False)
            self.status.setStyleSheet("color: #9aa9bd;")
            self.status.setText(
                "Kliknij „Losuj losowy układ”, aby utworzyć perforację."
            )
            return
        self._refresh()

    def _generate_random_on_request(self) -> None:
        if self.drawing is None or self._random_thread is not None:
            return
        try:
            material = resize_material(
                self.drawing.material,
                self.width_input.value(),
                self.height_input.value(),
            )
            opening_shape = make_opening_shape(
                self.opening_type_input.currentData(),
                self.opening_width_input.value(),
                self.opening_height_input.value(),
                self.polygon_sides_input.value(),
                self.custom_opening,
            )
            opening_bounds = opening_shape.bounds
            fixed_width = opening_bounds[2] - opening_bounds[0]
            fixed_height = opening_bounds[3] - opening_bounds[1]
            min_width = (
                self.random_min_width_input.value()
                if self.randomize_width_input.isChecked()
                else fixed_width
            )
            max_width = (
                self.random_max_width_input.value()
                if self.randomize_width_input.isChecked()
                else fixed_width
            )
            min_height = (
                self.random_min_height_input.value()
                if self.randomize_height_input.isChecked()
                else fixed_height
            )
            max_height = (
                self.random_max_height_input.value()
                if self.randomize_height_input.isChecked()
                else fixed_height
            )
            if self.opening_type_input.currentData() == "circle":
                min_height = min_width
                max_height = max_width
            min_horizontal_gap = (
                self.random_min_horizontal_gap_input.value()
                if self.randomize_horizontal_gap_input.isChecked()
                else self.spacing_input.value()
            )
            max_horizontal_gap = (
                self.random_max_horizontal_gap_input.value()
                if self.randomize_horizontal_gap_input.isChecked()
                else self.spacing_input.value()
            )
            min_vertical_gap = (
                self.random_min_vertical_gap_input.value()
                if self.randomize_vertical_gap_input.isChecked()
                else self.spacing_input.value()
            )
            max_vertical_gap = (
                self.random_max_vertical_gap_input.value()
                if self.randomize_vertical_gap_input.isChecked()
                else self.spacing_input.value()
            )
            margin = self.margin_input.value()
            inner_margin = self.inner_margin_input.value()
            angle = self.angle_input.value()
            self.random_seed = secrets.randbits(32)
            seed = self.random_seed
        except ValueError as error:
            self.status.setStyleSheet("color: #fb7185;")
            self.status.setText(str(error))
            return

        def calculate(
            progress: Callable[[int], None],
            cancellation_requested: Callable[[], bool],
        ) -> list[tuple[float, float, BaseGeometry]]:
            return generate_random_holes(
                material,
                opening_shape,
                min_width,
                max_width,
                min_height,
                max_height,
                min_horizontal_gap,
                max_horizontal_gap,
                min_vertical_gap,
                max_vertical_gap,
                margin,
                inner_margin_mm=inner_margin,
                angle_degrees=angle,
                seed=seed,
                progress_callback=progress,
                cancellation_requested=cancellation_requested,
            )

        self._random_cancellation = Event()
        self._random_progress = QProgressDialog(
            "Obliczanie losowego układu…",
            "Anuluj",
            0,
            100,
            self,
        )
        self._random_progress.setWindowTitle("Losowa perforacja")
        self._random_progress.setWindowModality(Qt.WindowModal)
        self._random_progress.setMinimumDuration(0)
        self._random_progress.setAutoClose(False)
        self._random_progress.canceled.connect(
            self._random_cancellation.set
        )
        self._random_thread = QThread(self)
        self._random_pending_material = material
        self._random_pending_opening = opening_shape
        self._random_worker = RandomPerforationWorker(
            calculate, self._random_cancellation
        )
        self._random_worker.moveToThread(self._random_thread)
        self._random_thread.started.connect(self._random_worker.run)
        self._random_worker.progress.connect(self._random_progress.setValue)
        self._random_worker.completed.connect(
            self._random_generation_finished
        )
        self._random_worker.failed.connect(self._random_generation_failed)
        self._random_worker.cancelled.connect(self._random_generation_cancelled)
        self._random_worker.completed.connect(self._random_thread.quit)
        self._random_worker.failed.connect(self._random_thread.quit)
        self._random_worker.cancelled.connect(self._random_thread.quit)
        self._random_thread.finished.connect(self._random_worker.deleteLater)
        self._random_thread.finished.connect(self._random_thread.deleteLater)
        self._random_thread.finished.connect(self._random_generation_stopped)
        self.regenerate_random_button.setEnabled(False)
        self.export_button.setEnabled(False)
        self._random_progress.open()
        self._random_thread.start()

    def _random_generation_finished(
        self,
        result: list[tuple[float, float, BaseGeometry]],
    ) -> None:
        if self._random_progress is not None:
            self._random_progress.setValue(100)
        if (
            self._random_pending_material is None
            or self._random_pending_opening is None
        ):
            self._random_generation_failed(
                "Nie udało się odczytać geometrii perforacji."
            )
            return
        holes = [(x, y) for x, y, _shape in result]
        hole_shapes = [shape for _x, _y, shape in result]
        self._random_result_current = True
        self._set_preview(
            self._random_pending_material,
            self._random_pending_opening,
            holes,
            hole_shapes,
        )

    def _random_generation_failed(self, message: str) -> None:
        self._random_result_current = False
        self.status.setStyleSheet("color: #fb7185;")
        self.status.setText(message)

    def _random_generation_cancelled(self) -> None:
        self._random_result_current = False
        self.status.setStyleSheet("color: #fbbf24;")
        self.status.setText(
            "Losowanie anulowane. Kliknij „Losuj losowy układ”, "
            "aby spróbować ponownie."
        )

    def _random_generation_stopped(self) -> None:
        if self._random_progress is not None:
            self._random_progress.close()
            self._random_progress.deleteLater()
        self.regenerate_random_button.setEnabled(True)
        self._random_progress = None
        self._random_cancellation = None
        self._random_worker = None
        self._random_thread = None
        self._random_pending_material = None
        self._random_pending_opening = None

    def _update_random_controls(self) -> None:
        is_random = self.layout_mode_input.currentData() == "random"
        random_width = is_random and self.randomize_width_input.isChecked()
        random_height = is_random and self.randomize_height_input.isChecked()
        random_horizontal_gap = (
            is_random and self.randomize_horizontal_gap_input.isChecked()
        )
        random_vertical_gap = (
            is_random and self.randomize_vertical_gap_input.isChecked()
        )
        for widget in (
            self.randomize_width_input,
            self.random_width_range_label,
            self.randomize_height_input,
            self.random_height_range_label,
            self.randomize_horizontal_gap_input,
            self.randomize_vertical_gap_input,
            self.regenerate_random_button,
        ):
            widget.setVisible(is_random)
        self.random_width_range.setVisible(random_width)
        self.random_height_range.setVisible(random_height)
        self.random_horizontal_gap_range_label.setVisible(
            random_horizontal_gap
        )
        self.random_horizontal_gap_range.setVisible(random_horizontal_gap)
        self.random_vertical_gap_range_label.setVisible(random_vertical_gap)
        self.random_vertical_gap_range.setVisible(random_vertical_gap)
        self.pattern_input.setVisible(not is_random)
        self.pattern_label.setVisible(not is_random)
        fixed_gaps_remain = not random_horizontal_gap or not random_vertical_gap
        self.spacing_label.setVisible(not is_random or fixed_gaps_remain)
        self.spacing_input.setVisible(
            not is_random or fixed_gaps_remain
        )
        if is_random and fixed_gaps_remain:
            if not random_horizontal_gap and not random_vertical_gap:
                self.spacing_label.setText("Stały odstęp poziomy i pionowy:")
            elif not random_horizontal_gap:
                self.spacing_label.setText("Stały odstęp poziomy:")
            else:
                self.spacing_label.setText("Stały odstęp pionowy:")
        self.spacing_mode_label.setVisible(not is_random)
        self.spacing_mode.setVisible(not is_random)
        if not is_random:
            self.spacing_label.setText("Odstęp / podziałka:")
        self.angle_label.setText(
            "Kąt otworów:" if is_random else "Kąt siatki:"
        )
        self.opening_angle_label.setVisible(not is_random)
        self.opening_angle_input.setVisible(not is_random)
        self._update_opening_controls()

    def _update_opening_controls(self) -> None:
        opening_type = self.opening_type_input.currentData()
        circular_opening = opening_type == "circle"
        if circular_opening and self.randomize_height_input.isChecked():
            previous_state = self.randomize_height_input.blockSignals(True)
            self.randomize_height_input.setChecked(False)
            self.randomize_height_input.blockSignals(previous_state)
        self.randomize_height_input.setEnabled(not circular_opening)
        self.random_height_range_label.setEnabled(not circular_opening)
        self.random_height_range.setEnabled(not circular_opening)
        self.opening_width_label.setText(
            {
                "circle": "Średnica otworu:",
                "square": "Bok kwadratu:",
                "triangle": "Szerokość trójkąta:",
                "slot": "Długość fasolki:",
            }.get(opening_type, "Szerokość otworu:")
        )
        show_height = opening_type in {"rectangle", "ellipse", "slot"}
        self.opening_height_label.setVisible(show_height)
        self.opening_height_input.setVisible(show_height)
        self.opening_height_label.setText(
            "Szerokość fasolki:"
            if opening_type == "slot"
            else "Wysokość otworu:"
        )
        show_sides = opening_type == "regular_polygon"
        self.polygon_sides_input.setVisible(show_sides)
        self.polygon_sides_label.setVisible(show_sides)
        show_custom = opening_type == "custom"
        self.custom_opening_button.setVisible(show_custom)
        self.custom_opening_name.setVisible(show_custom)
        self.custom_opening_row.setVisible(show_custom)
        self.custom_opening_row_label.setVisible(show_custom)
        if opening_type == "slot":
            self.random_width_range_label.setText("Zakres długości fasolki:")
            self.random_height_range_label.setText("Zakres szerokości fasolki:")
        else:
            self.random_width_range_label.setText("Zakres szerokości:")
            self.random_height_range_label.setText("Zakres wysokości:")

    def _choose_opening_shape(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(
            self, "Wczytaj kształt otworu", "", "Pliki DXF (*.dxf)"
        )
        if not filename:
            return
        path = Path(filename)
        try:
            drawing = load_dxf(path)
        except (OSError, ezdxf.DXFError, ValueError) as error:
            QMessageBox.critical(
                self, "Nie można wczytać kształtu DXF", str(error)
            )
            return
        self.custom_opening = drawing.material
        self.custom_opening_warnings = drawing.warnings
        self.custom_opening_name.setText(path.name)
        self.opening_width_input.setValue(drawing.width_mm)
        self.opening_type_input.setCurrentIndex(
            self.opening_type_input.findData("custom")
        )
        self._refresh()

    def _load_file(self, path: Path) -> None:
        try:
            drawing = load_dxf(path)
        except (OSError, ezdxf.DXFError, ValueError) as error:
            QMessageBox.critical(self, "Nie można wczytać DXF", str(error))
            return
        self.drawing = drawing
        self.source_path = path
        self.output_preview.reset_zoom()
        self.width_input.setValue(drawing.width_mm)
        self.height_input.setValue(drawing.height_mm)
        self.output_path.setText(
            str(path.with_name(f"{path.stem}_perforacja.dxf"))
        )
        self.source_preview.set_data(drawing.material)
        self._refresh()

    def _refresh(self, *_args) -> None:
        if self.drawing is None:
            return
        if self.layout_mode_input.currentData() == "random":
            self._parameters_changed()
            return
        self.spacing_label.setText(
            "Podziałka po przekątnej:"
            if self.pattern_input.currentData() == "staggered"
            and self.spacing_mode.currentData() == "pitch"
            else "Odstęp / podziałka:"
        )
        try:
            material = resize_material(
                self.drawing.material,
                self.width_input.value(),
                self.height_input.value(),
            )
            opening_shape = make_opening_shape(
                self.opening_type_input.currentData(),
                self.opening_width_input.value(),
                self.opening_height_input.value(),
                self.polygon_sides_input.value(),
                self.custom_opening,
            )
            holes = generate_holes(
                material,
                opening_shape,
                self.spacing_input.value(),
                self.margin_input.value(),
                self.angle_input.value(),
                self.pattern_input.currentData(),
                self.spacing_mode.currentData(),
                inner_margin_mm=self.inner_margin_input.value(),
                opening_angle_degrees=self.opening_angle_input.value(),
            )
        except ValueError as error:
            self.preview_material = None
            self.preview_holes = []
            self.preview_opening = None
            self.preview_hole_shapes = []
            self.output_preview.set_data(None)
            self.export_button.setEnabled(False)
            self.status.setText(str(error))
            self.status.setStyleSheet("color: #fb7185;")
            return
        self._random_result_current = True
        self._set_preview(material, opening_shape, holes, [])

    def _set_preview(
        self,
        material: BaseGeometry,
        opening_shape: BaseGeometry,
        holes: list[tuple[float, float]],
        hole_shapes: list[BaseGeometry],
    ) -> None:
        assert self.drawing is not None
        self.preview_material = material
        self.preview_holes = holes
        self.preview_opening = opening_shape
        self.preview_hole_shapes = hole_shapes
        is_random = self.layout_mode_input.currentData() == "random"
        self.output_preview.set_data(
            material,
            holes,
            opening_shape,
            self.margin_input.value(),
            self.angle_input.value(),
            self.opening_type_input.currentData(),
            self.inner_margin_input.value(),
            0.0 if is_random else self.opening_angle_input.value(),
            hole_shapes,
        )
        self.export_button.setEnabled(bool(holes) and self._random_result_current)
        self.status.setStyleSheet("color: #9aa9bd;")
        min_x, min_y, max_x, max_y = material.bounds
        open_area = (
            sum(shape.area for shape in hole_shapes) / material.area * 100
            if hole_shapes
            else open_area_percentage(material, len(holes), opening_shape)
        )
        messages = [
            f"Wymiary: {max_x - min_x:.1f} × {max_y - min_y:.1f} mm",
            f"Liczba otworów: {len(holes):,}",
            f"Stopień prześwitu: {open_area:.1f}%",
        ]
        messages.extend(self.drawing.warnings)
        if self.opening_type_input.currentData() == "custom":
            messages.extend(self.custom_opening_warnings)
        if not holes:
            messages.append(
                "Brak otworów: zmień wymiary, margines lub odstęp."
            )
        self.status.setText("  |  ".join(messages))

    def _export(self) -> None:
        if (
            self.preview_material is None
            or self.preview_opening is None
            or not self.preview_holes
            or not self._random_result_current
        ):
            return
        filename = self.output_path.text().strip()
        if not filename:
            self._choose_output()
            filename = self.output_path.text().strip()
        if not filename:
            return
        destination = Path(filename)
        if destination.suffix.lower() != ".dxf":
            destination = destination.with_suffix(".dxf")
            self.output_path.setText(str(destination))
        if self.source_path and destination.resolve() == self.source_path.resolve():
            QMessageBox.warning(
                self,
                "Nie można nadpisać źródła",
                "Wybierz inną nazwę pliku niż oryginalny rysunek DXF.",
            )
            return
        settings_destination = destination.with_suffix(".json")
        existing_outputs = [
            str(path)
            for path in (destination, settings_destination)
            if path.exists()
        ]
        if existing_outputs and QMessageBox.question(
            self,
            "Potwierdź nadpisanie",
            "Następujące pliki już istnieją:\n"
            f"{chr(10).join(existing_outputs)}\n\nCzy je nadpisać?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        ) != QMessageBox.Yes:
            return
        try:
            settings = self._current_settings()
            export_dxf(
                destination,
                self.preview_material,
                self.preview_holes,
                self.preview_opening,
                self.opening_type_input.currentData(),
                self.angle_input.value(),
                (
                    0.0
                    if self.layout_mode_input.currentData() == "random"
                    else self.opening_angle_input.value()
                ),
                self.perforation_export_input.currentData(),
                self.preview_hole_shapes or None,
            )
        except (OSError, ezdxf.DXFError, ValueError) as error:
            QMessageBox.critical(self, "Nie można zapisać DXF", str(error))
            return
        try:
            save_perforation_settings(settings_destination, settings)
        except (OSError, ValueError) as error:
            QMessageBox.critical(
                self,
                "Nie zapisano konfiguracji",
                f"DXF został zapisany, ale konfiguracji nie udało się "
                f"zapisać:\n{error}",
            )
            return
        QMessageBox.information(
            self,
            "Zapisano plik",
            f"Zapisano {len(self.preview_holes):,} otworów do:\n"
            f"{destination}\n\n"
            f"Ustawienia perforacji zapisano do:\n{settings_destination}",
        )

    def _current_settings(self) -> PerforationSettings:
        opening_type = self.opening_type_input.currentData()
        return PerforationSettings(
            width_mm=self.width_input.value(),
            height_mm=self.height_input.value(),
            pattern=self.pattern_input.currentData(),
            opening_type=opening_type,
            opening_width_mm=self.opening_width_input.value(),
            opening_height_mm=self.opening_height_input.value(),
            polygon_sides=self.polygon_sides_input.value(),
            spacing_mm=self.spacing_input.value(),
            spacing_mode=self.spacing_mode.currentData(),
            grid_angle_degrees=self.angle_input.value(),
            opening_angle_degrees=self.opening_angle_input.value(),
            outer_margin_mm=self.margin_input.value(),
            inner_margin_mm=self.inner_margin_input.value(),
            perforation_as_block=self.perforation_export_input.currentData(),
            layout_mode=self.layout_mode_input.currentData(),
            random_min_width_mm=self.random_min_width_input.value(),
            random_max_width_mm=self.random_max_width_input.value(),
            random_min_height_mm=self.random_min_height_input.value(),
            random_max_height_mm=self.random_max_height_input.value(),
            randomize_width=self.randomize_width_input.isChecked(),
            randomize_height=self.randomize_height_input.isChecked(),
            randomize_horizontal_gap=(
                self.randomize_horizontal_gap_input.isChecked()
            ),
            randomize_vertical_gap=self.randomize_vertical_gap_input.isChecked(),
            random_min_horizontal_gap_mm=(
                self.random_min_horizontal_gap_input.value()
            ),
            random_max_horizontal_gap_mm=(
                self.random_max_horizontal_gap_input.value()
            ),
            random_min_vertical_gap_mm=(
                self.random_min_vertical_gap_input.value()
            ),
            random_max_vertical_gap_mm=(
                self.random_max_vertical_gap_input.value()
            ),
            random_seed=self.random_seed,
            custom_opening=(
                self.custom_opening if opening_type == "custom" else None
            ),
        )

def main() -> int:
    application = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
