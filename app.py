from __future__ import annotations

import sys
from pathlib import Path

import ezdxf
from PyQt5.QtCore import QPointF, Qt
from PyQt5.QtGui import QColor, QPainter, QPainterPath, QPen
from PyQt5.QtWidgets import (
    QApplication,
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
    QSplitter,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)
from shapely.geometry import MultiPolygon, Polygon
from shapely.geometry.base import BaseGeometry

from geometry import (
    Drawing,
    export_dxf,
    generate_holes,
    load_dxf,
    make_opening_shape,
    open_area_percentage,
    resize_material,
)


class Preview(QWidget):
    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.title = title
        self.material: BaseGeometry | None = None
        self.holes: list[tuple[float, float]] = []
        self.opening_shape: BaseGeometry | None = None
        self.opening_type = "circle"
        self.margin = 0.0
        self.angle = 0.0
        self.show_margin = True
        self.setMinimumSize(320, 300)

    def set_data(
        self,
        material: BaseGeometry | None,
        holes: list[tuple[float, float]] | None = None,
        opening_shape: BaseGeometry | None = None,
        margin: float = 0.0,
        angle: float = 0.0,
        opening_type: str = "circle",
    ) -> None:
        self.material = material
        self.holes = holes or []
        self.opening_shape = opening_shape
        self.opening_type = opening_type
        self.margin = margin
        self.angle = angle
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
        )
        painter.translate(self.width() / 2, self.height() / 2 + 5)
        painter.scale(factor, -factor)
        painter.translate(-(min_x + max_x) / 2, -(min_y + max_y) / 2)

        outline = _geometry_path(self.material)
        painter.setPen(QPen(QColor("#f4d84b"), max(1.0 / factor, 0.25 / factor)))
        painter.setBrush(QColor(21, 179, 205, 48))
        painter.drawPath(outline)
        if self.show_margin and self.margin > 0:
            clearance = self.material.buffer(-self.margin, join_style="mitre")
            if not clearance.is_empty:
                pen = QPen(QColor("#d378ce"), max(0.8 / factor, 0.2 / factor))
                pen.setStyle(Qt.DashLine)
                painter.setPen(pen)
                painter.setBrush(Qt.NoBrush)
                painter.drawPath(_geometry_path(clearance))
        if self.holes and self.opening_shape is not None:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor("#16c9df"))
            if self.opening_type == "circle":
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
        self.custom_opening: BaseGeometry | None = None
        self.custom_opening_warnings: tuple[str, ...] = ()
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
        self.export_button = QPushButton("Eksportuj DXF")
        self.export_button.clicked.connect(self._export)
        self.export_button.setEnabled(False)
        header.addWidget(self.export_button)
        main_layout.addLayout(header)

        splitter = QSplitter(Qt.Horizontal)
        controls = self._build_controls()
        splitter.addWidget(controls)
        preview_area = QWidget()
        previews = QHBoxLayout(preview_area)
        previews.setContentsMargins(0, 0, 0, 0)
        previews.setSpacing(8)
        self.source_preview = Preview("RYSUNEK ŹRÓDŁOWY")
        self.output_preview = Preview("PODGLĄD PERFORACJI")
        previews.addWidget(self.source_preview)
        previews.addWidget(self.output_preview)
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
        self.pattern_input = QComboBox()
        self.pattern_input.addItem("Prosty (kwadratowy)", "square")
        self.pattern_input.addItem("Mijankowy", "staggered")
        form.addRow("Układ:", self.pattern_input)
        self.opening_type_input = QComboBox()
        self.opening_type_input.addItem("Koło", "circle")
        self.opening_type_input.addItem("Kwadrat", "square")
        self.opening_type_input.addItem("Prostokąt", "rectangle")
        self.opening_type_input.addItem("Trójkąt równoboczny", "triangle")
        self.opening_type_input.addItem("Owal / elipsa", "ellipse")
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
        form.addRow("Tryb odległości:", self.spacing_mode)
        self.angle_input = QDoubleSpinBox()
        self.angle_input.setDecimals(1)
        self.angle_input.setRange(-180.0, 180.0)
        self.angle_input.setSingleStep(5.0)
        self.angle_input.setSuffix("°")
        form.addRow("Kąt siatki:", self.angle_input)
        self.margin_input = _parameter_input(10.0, 0.0, 5000.0)
        form.addRow("Margines od krawędzi:", self.margin_input)
        layout.addLayout(form)

        section("PLIK WYJŚCIOWY")
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

        for field in (
            self.width_input,
            self.height_input,
            self.pattern_input,
            self.opening_width_input,
            self.opening_height_input,
            self.spacing_input,
            self.spacing_mode,
            self.angle_input,
            self.margin_input,
        ):
            field.valueChanged.connect(self._refresh) if isinstance(
                field, QDoubleSpinBox
            ) else field.currentIndexChanged.connect(self._refresh)
        self.opening_type_input.currentIndexChanged.connect(
            self._opening_type_changed
        )
        self.polygon_sides_input.valueChanged.connect(self._refresh)
        self._update_opening_controls()
        return panel

    def _choose_input(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(
            self, "Otwórz rysunek DXF", "", "Pliki DXF (*.dxf)"
        )
        if filename:
            self._load_file(Path(filename))

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
        self._refresh()

    def _update_opening_controls(self) -> None:
        opening_type = self.opening_type_input.currentData()
        self.opening_width_label.setText(
            {
                "circle": "Średnica otworu:",
                "square": "Bok kwadratu:",
                "triangle": "Szerokość trójkąta:",
            }.get(opening_type, "Szerokość otworu:")
        )
        show_height = opening_type in {"rectangle", "ellipse"}
        self.opening_height_label.setVisible(show_height)
        self.opening_height_input.setVisible(show_height)
        show_sides = opening_type == "regular_polygon"
        self.polygon_sides_input.setVisible(show_sides)
        self.polygon_sides_label.setVisible(show_sides)
        show_custom = opening_type == "custom"
        self.custom_opening_button.setVisible(show_custom)
        self.custom_opening_name.setVisible(show_custom)
        self.custom_opening_row.setVisible(show_custom)
        self.custom_opening_row_label.setVisible(show_custom)

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
            )
        except ValueError as error:
            self.preview_material = None
            self.preview_holes = []
            self.preview_opening = None
            self.output_preview.set_data(None)
            self.export_button.setEnabled(False)
            self.status.setText(str(error))
            self.status.setStyleSheet("color: #fb7185;")
            return
        self.preview_material = material
        self.preview_holes = holes
        self.preview_opening = opening_shape
        self.output_preview.set_data(
            material,
            holes,
            opening_shape,
            self.margin_input.value(),
            self.angle_input.value(),
            self.opening_type_input.currentData(),
        )
        self.export_button.setEnabled(bool(holes))
        self.status.setStyleSheet("color: #9aa9bd;")
        min_x, min_y, max_x, max_y = material.bounds
        open_area = open_area_percentage(
            material, len(holes), opening_shape
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
                "Brak otworów: zmniejsz margines lub wymiary otworu."
            )
        self.status.setText("  |  ".join(messages))

    def _export(self) -> None:
        if (
            self.preview_material is None
            or self.preview_opening is None
            or not self.preview_holes
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
        if destination.exists() and QMessageBox.question(
            self,
            "Potwierdź nadpisanie",
            f"Plik już istnieje:\n{destination}\n\nCzy go nadpisać?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        ) != QMessageBox.Yes:
            return
        try:
            export_dxf(
                destination,
                self.preview_material,
                self.preview_holes,
                self.preview_opening,
                self.opening_type_input.currentData(),
                self.angle_input.value(),
            )
        except (OSError, ezdxf.DXFError, ValueError) as error:
            QMessageBox.critical(self, "Nie można zapisać DXF", str(error))
            return
        QMessageBox.information(
            self,
            "Zapisano plik",
            f"Zapisano {len(self.preview_holes):,} otworów do:\n{destination}",
        )


def main() -> int:
    application = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
