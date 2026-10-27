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
    QVBoxLayout,
    QWidget,
)
from shapely.geometry import MultiPolygon, Polygon
from shapely.geometry.base import BaseGeometry

from geometry import Drawing, export_dxf, generate_holes, load_dxf, resize_material


class Preview(QWidget):
    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.title = title
        self.material: BaseGeometry | None = None
        self.holes: list[tuple[float, float]] = []
        self.diameter = 0.0
        self.margin = 0.0
        self.show_margin = True
        self.setMinimumSize(320, 300)

    def set_data(
        self,
        material: BaseGeometry | None,
        holes: list[tuple[float, float]] | None = None,
        diameter: float = 0.0,
        margin: float = 0.0,
    ) -> None:
        self.material = material
        self.holes = holes or []
        self.diameter = diameter
        self.margin = margin
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
        if self.holes:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor("#16c9df"))
            radius = self.diameter / 2
            for x, y in self.holes:
                painter.drawEllipse(QPointF(x, y), radius, radius)


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
        self.diameter_input = _parameter_input(10.0, 0.1, 5000.0)
        form.addRow("Średnica otworu:", self.diameter_input)
        self.spacing_input = _parameter_input(10.0, 0.1, 10_000.0)
        form.addRow("Odstęp / podziałka:", self.spacing_input)
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
            self.diameter_input,
            self.spacing_input,
            self.spacing_mode,
            self.angle_input,
            self.margin_input,
        ):
            field.valueChanged.connect(self._refresh) if isinstance(
                field, QDoubleSpinBox
            ) else field.currentIndexChanged.connect(self._refresh)
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
        try:
            material = resize_material(
                self.drawing.material,
                self.width_input.value(),
                self.height_input.value(),
            )
            holes = generate_holes(
                material,
                self.diameter_input.value(),
                self.spacing_input.value(),
                self.margin_input.value(),
                self.angle_input.value(),
                self.pattern_input.currentData(),
                self.spacing_mode.currentData(),
            )
        except ValueError as error:
            self.preview_material = None
            self.preview_holes = []
            self.output_preview.set_data(None)
            self.export_button.setEnabled(False)
            self.status.setText(str(error))
            self.status.setStyleSheet("color: #fb7185;")
            return
        self.preview_material = material
        self.preview_holes = holes
        self.output_preview.set_data(
            material,
            holes,
            self.diameter_input.value(),
            self.margin_input.value(),
        )
        self.export_button.setEnabled(bool(holes))
        self.status.setStyleSheet("color: #9aa9bd;")
        min_x, min_y, max_x, max_y = material.bounds
        messages = [
            f"Wymiary: {max_x - min_x:.1f} × {max_y - min_y:.1f} mm",
            f"Liczba otworów: {len(holes):,}",
        ]
        messages.extend(self.drawing.warnings)
        if not holes:
            messages.append(
                "Brak otworów: zmniejsz margines lub średnicę."
            )
        self.status.setText("  |  ".join(messages))

    def _export(self) -> None:
        if self.preview_material is None or not self.preview_holes:
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
                self.diameter_input.value(),
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
