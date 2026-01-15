"""PyQt5 widget for spectrum calibration.

This widget provides tools for:
- Loading CSV spectrum logs
- Channel-to-energy calibration points with linear fit
- Energy markers for element identification
- Project save/load functionality
- Interactive plotting with energy axis
"""
from __future__ import annotations

import csv
import json
import os
from typing import Tuple

import numpy as np
import pyqtgraph as pg
from pyqtgraph.exporters import ImageExporter
from PyQt5.QtCore import Qt, QSettings
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QGroupBox,
    QPushButton, QTableWidget, QTableWidgetItem, QAbstractItemView,
    QFormLayout, QDoubleSpinBox, QCheckBox, QLabel, QFileDialog,
    QMessageBox
)


class EnergyAxisItem(pg.AxisItem):
    """Custom axis item for displaying energy values computed from channels."""
    
    def __init__(self, orientation, coeffs_provider, **kwargs):
        super().__init__(orientation, **kwargs)
        self._coeffs_provider = coeffs_provider

    def tickStrings(self, values, scale, spacing):
        slope, offset = self._coeffs_provider()
        labels = []
        for value in values:
            if not np.isfinite(value):
                labels.append("")
                continue
            energy = slope * value + offset
            labels.append(f"{energy:.6g}")
        return labels


class CalibrationTab(QWidget):
    """Widget for spectrum calibration workflow."""
    
    def __init__(self):
        super().__init__()
        self.log_data = {}
        self.energy_lines = []
        self.channel_energy_lines = []
        self.settings = QSettings("UST", "dosview")
        self.energy_config_key = "calibration/selected_energies"
        self.plot_legend = None
        self.legend_formula_item = None
        self._suppress_log_item_changed = False
        self._suppress_energy_item_changed = False
        self._suppress_channel_energy_item_changed = False
        self._suppress_channel_line_update = False
        self.initUI()
        self.load_energy_config()

    def initUI(self):
        main_splitter = QSplitter(Qt.Horizontal)

        left_widget = QWidget()
        left_layout = QVBoxLayout()
        left_layout.setAlignment(Qt.AlignTop)
        left_widget.setLayout(left_layout)

        project_group = QGroupBox("Project")
        project_layout = QHBoxLayout()
        project_load_button = QPushButton("Load")
        project_load_button.clicked.connect(self.load_project)
        project_save_button = QPushButton("Save")
        project_save_button.clicked.connect(self.save_project)
        project_layout.addWidget(project_load_button)
        project_layout.addWidget(project_save_button)
        project_group.setLayout(project_layout)

        logs_group = QGroupBox("Logs")
        logs_layout = QVBoxLayout()
        self.log_table = QTableWidget(0, 2)
        self.log_table.setHorizontalHeaderLabels(["Log", "Label"])
        self.log_table.horizontalHeader().setStretchLastSection(True)
        self.log_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.log_table.itemChanged.connect(self.on_log_item_changed)
        logs_layout.addWidget(self.log_table)

        logs_buttons = QHBoxLayout()
        add_log_button = QPushButton("Add CSV")
        add_log_button.clicked.connect(self.add_csv_logs)
        remove_log_button = QPushButton("Remove")
        remove_log_button.clicked.connect(self.remove_selected_logs)
        logs_buttons.addWidget(add_log_button)
        logs_buttons.addWidget(remove_log_button)
        logs_layout.addLayout(logs_buttons)
        logs_group.setLayout(logs_layout)

        points_group = QGroupBox("Channel-to-energy")
        points_layout = QVBoxLayout()
        self.channel_energy_table = QTableWidget(0, 3)
        self.channel_energy_table.setHorizontalHeaderLabels(["Channel", "Energy", "Label"])
        self.channel_energy_table.horizontalHeader().setStretchLastSection(True)
        self.channel_energy_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.channel_energy_table.itemChanged.connect(self.on_channel_energy_item_changed)
        points_layout.addWidget(self.channel_energy_table)

        points_buttons = QHBoxLayout()
        add_point_button = QPushButton("Add point")
        add_point_button.clicked.connect(self.add_empty_calibration_point)
        remove_point_button = QPushButton("Remove point")
        remove_point_button.clicked.connect(self.remove_selected_calibration_points)
        points_buttons.addWidget(add_point_button)
        points_buttons.addWidget(remove_point_button)
        points_layout.addLayout(points_buttons)
        points_group.setLayout(points_layout)

        constants_group = QGroupBox("Calibration constants")
        constants_layout = QFormLayout()
        self.slope_spin = QDoubleSpinBox()
        self.slope_spin.setRange(-1e9, 1e9)
        self.slope_spin.setDecimals(8)
        self.slope_spin.setValue(1.0)
        self.slope_spin.valueChanged.connect(self.update_energy_lines)
        self.offset_spin = QDoubleSpinBox()
        self.offset_spin.setRange(-1e9, 1e9)
        self.offset_spin.setDecimals(8)
        self.offset_spin.setValue(0.0)
        self.offset_spin.valueChanged.connect(self.update_energy_lines)
        constants_layout.addRow("Slope a (energy/channel)", self.slope_spin)
        constants_layout.addRow("Offset b (energy)", self.offset_spin)
        estimate_button = QPushButton("Estimate calibration constants")
        estimate_button.clicked.connect(self.estimate_calibration)
        constants_layout.addRow(estimate_button)
        constants_group.setLayout(constants_layout)

        energy_group = QGroupBox("Selected energies")
        energy_layout = QVBoxLayout()
        self.energy_table = QTableWidget(0, 2)
        self.energy_table.setHorizontalHeaderLabels(["Energy", "Element"])
        self.energy_table.horizontalHeader().setStretchLastSection(True)
        self.energy_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.energy_table.itemChanged.connect(self.on_energy_item_changed)
        energy_layout.addWidget(self.energy_table)

        energy_buttons = QHBoxLayout()
        add_energy_button = QPushButton("Add energy")
        add_energy_button.clicked.connect(self.add_energy_row)
        remove_energy_button = QPushButton("Remove energy")
        remove_energy_button.clicked.connect(self.remove_selected_energy_rows)
        import_energy_button = QPushButton("Import to channel-to-energy")
        import_energy_button.clicked.connect(self.import_selected_energies)
        energy_buttons.addWidget(add_energy_button)
        energy_buttons.addWidget(remove_energy_button)
        energy_buttons.addWidget(import_energy_button)
        energy_layout.addLayout(energy_buttons)
        energy_group.setLayout(energy_layout)

        left_layout.addWidget(project_group)
        left_layout.addWidget(logs_group)
        left_layout.addWidget(points_group)
        left_layout.addWidget(constants_group)
        left_layout.addWidget(energy_group)

        plot_widget = QWidget()
        plot_layout = QVBoxLayout()
        plot_widget.setLayout(plot_layout)

        plot_controls = QHBoxLayout()
        self.save_plot_button = QPushButton("Save plot")
        self.save_plot_button.clicked.connect(self.save_plot)
        self.matplotlib_button = QPushButton("Show as matplotlib")
        self.matplotlib_button.clicked.connect(self.show_matplotlib)
        self.log_scale_checkbox = QCheckBox("Log Y")
        self.log_scale_checkbox.toggled.connect(self.update_plot)
        self.show_energy_checkbox = QCheckBox("Show energy")
        self.show_energy_checkbox.setChecked(True)
        self.show_energy_checkbox.toggled.connect(self.toggle_energy_axis)
        self.cursor_label = QLabel("Ch: --  E: -- keV")
        plot_controls.addWidget(self.save_plot_button)
        plot_controls.addWidget(self.matplotlib_button)
        plot_controls.addStretch(1)
        plot_controls.addWidget(self.show_energy_checkbox)
        plot_controls.addWidget(self.log_scale_checkbox)
        plot_controls.addWidget(self.cursor_label)
        plot_layout.addLayout(plot_controls)

        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setBackground((250, 250, 250))
        self.plot_widget.showGrid(x=True, y=True, alpha=0.25)
        self.plot_widget.setLabel("left", "Counts")
        self.plot_widget.setLabel("bottom", "Channel")
        plot_item = self.plot_widget.plotItem
        plot_item.setDownsampling(mode="peak")
        plot_item.setClipToView(True)
        plot_item.getAxis("left").setPen(pg.mkPen((40, 40, 40)))
        plot_item.getAxis("left").setTextPen(pg.mkPen((40, 40, 40)))
        plot_item.getAxis("bottom").setPen(pg.mkPen((40, 40, 40)))
        plot_item.getAxis("bottom").setTextPen(pg.mkPen((40, 40, 40)))
        plot_item.getAxis("bottom").setLabel("Channel")
        self.energy_axis = EnergyAxisItem("bottom", self.get_calibration_coeffs)
        self.energy_axis.setLabel("Energy (keV)")
        self.energy_axis.setPen(pg.mkPen((90, 90, 90)))
        self.energy_axis.setTextPen(pg.mkPen((90, 90, 90)))
        self.energy_axis.setHeight(30)
        self.energy_axis.linkToView(plot_item.vb)
        plot_item.layout.addItem(self.energy_axis, 4, 1)
        plot_item.layout.setRowStretchFactor(4, 0)
        plot_item.layout.setRowSpacing(3, 4)
        self.energy_axis.setVisible(True)
        plot_layout.addWidget(self.plot_widget)
        self._mouse_proxy = pg.SignalProxy(
            self.plot_widget.scene().sigMouseMoved,
            rateLimit=30,
            slot=self.on_mouse_moved,
        )
        self.toggle_energy_axis(self.show_energy_checkbox.isChecked())

        main_splitter.addWidget(left_widget)
        main_splitter.addWidget(plot_widget)
        main_splitter.setStretchFactor(0, 0)
        main_splitter.setStretchFactor(1, 1)

        layout = QHBoxLayout()
        layout.addWidget(main_splitter)
        self.setLayout(layout)

    def add_csv_logs(self):
        file_paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Select calibration CSV files",
            "",
            "CSV files (*.csv);;All files (*)"
        )
        if not file_paths:
            return
        for file_path in file_paths:
            if file_path in self.log_data:
                continue
            try:
                channels, counts = self.load_csv_counts(file_path)
            except Exception as exc:
                QMessageBox.warning(self, "CSV load error", f"Failed to load {file_path}: {exc}")
                continue
            self.log_data[file_path] = {"channels": channels, "counts": counts}
            self.add_log_row(file_path)
        self.update_plot()

    def add_log_row(self, file_path):
        name = os.path.basename(file_path)
        row = self.log_table.rowCount()
        self.log_table.insertRow(row)

        log_item = QTableWidgetItem(name)
        log_item.setFlags(log_item.flags() | Qt.ItemIsUserCheckable)
        log_item.setCheckState(Qt.Checked)
        log_item.setFlags(log_item.flags() & ~Qt.ItemIsEditable)
        log_item.setData(Qt.UserRole, file_path)
        label_item = QTableWidgetItem(name)

        self._suppress_log_item_changed = True
        self.log_table.setItem(row, 0, log_item)
        self.log_table.setItem(row, 1, label_item)
        self._suppress_log_item_changed = False

    def remove_selected_logs(self):
        rows = sorted({idx.row() for idx in self.log_table.selectionModel().selectedRows()}, reverse=True)
        for row in rows:
            log_item = self.log_table.item(row, 0)
            if log_item:
                file_path = log_item.data(Qt.UserRole)
                if file_path in self.log_data:
                    del self.log_data[file_path]
            self.log_table.removeRow(row)
        self.update_plot()

    def on_log_item_changed(self, item):
        if self._suppress_log_item_changed:
            return
        if item is None:
            return
        row = item.row()
        log_item = self.log_table.item(row, 0)
        if log_item is None:
            return
        file_path = log_item.data(Qt.UserRole)
        if item.column() == 1 and not item.text().strip():
            name = os.path.basename(file_path) if file_path else "log"
            self._suppress_log_item_changed = True
            item.setText(name)
            self._suppress_log_item_changed = False
        self.update_plot()

    def load_csv_counts(self, file_path):
        channels = []
        counts = []
        with open(file_path, "r", newline="") as handle:
            reader = csv.reader(handle)
            for row in reader:
                if len(row) < 2:
                    continue
                try:
                    channel = float(row[0])
                    count = float(row[1])
                except ValueError:
                    continue
                channels.append(channel)
                counts.append(count)
        if not channels:
            raise ValueError("No numeric channel/count data found")
        return np.array(channels), np.array(counts)

    def add_empty_calibration_point(self):
        row = self.channel_energy_table.rowCount()
        self.channel_energy_table.insertRow(row)
        self._suppress_channel_energy_item_changed = True
        self.channel_energy_table.setItem(row, 0, QTableWidgetItem("0"))
        self.channel_energy_table.setItem(row, 1, QTableWidgetItem(""))
        self.channel_energy_table.setItem(row, 2, QTableWidgetItem(""))
        self._suppress_channel_energy_item_changed = False
        self.channel_energy_lines.append(None)
        self.sync_channel_energy_lines()

    def remove_selected_calibration_points(self):
        rows = sorted({idx.row() for idx in self.channel_energy_table.selectionModel().selectedRows()}, reverse=True)
        for row in rows:
            if row < len(self.channel_energy_lines):
                line = self.channel_energy_lines.pop(row)
                if line is not None:
                    self.plot_widget.removeItem(line)
            self.channel_energy_table.removeRow(row)
        self.update_channel_energy_line_indices()

    def on_channel_energy_item_changed(self, item):
        if self._suppress_channel_energy_item_changed:
            return
        if item is None:
            return
        if item.column() == 2:
            self.update_channel_energy_line_label(item.row())
            self.update_line_label_positions()
            return
        if item.column() != 0:
            return
        row = item.row()
        channel = None
        try:
            channel = float(item.text())
        except ValueError:
            channel = None
        if channel is None:
            if row < len(self.channel_energy_lines):
                line = self.channel_energy_lines[row]
                if line is not None:
                    self.plot_widget.removeItem(line)
                    self.channel_energy_lines[row] = None
            return
        self.ensure_channel_energy_line(row, channel)
        self.update_channel_energy_line_label(row)
        self.update_line_label_positions()

    def ensure_channel_energy_line(self, row, channel):
        if row >= len(self.channel_energy_lines):
            self.channel_energy_lines.extend([None] * (row - len(self.channel_energy_lines) + 1))
        line = self.channel_energy_lines[row]
        if line is None:
            label_text = self.channel_energy_label_text(row)
            line = pg.InfiniteLine(
                pos=channel,
                angle=90,
                pen=pg.mkPen((70, 130, 180), width=2),
                movable=True,
                label=label_text if label_text else None,
                labelOpts={"position": 0.75, "color": (70, 130, 180)},
            )
            line.setZValue(15)
            line._channel_energy_row = row
            line._label_text = label_text
            if hasattr(line, "sigPositionChangeFinished"):
                line.sigPositionChangeFinished.connect(self.on_channel_energy_line_moved)
            else:
                line.sigPositionChanged.connect(self.on_channel_energy_line_moved)
            self.channel_energy_lines[row] = line
        else:
            self._suppress_channel_line_update = True
            line.setValue(channel)
            self._suppress_channel_line_update = False
        if line.scene() is None:
            self.plot_widget.addItem(line)

    def channel_energy_label_text(self, row):
        label_item = self.channel_energy_table.item(row, 2)
        if label_item is None:
            return ""
        return label_item.text().strip()

    def update_channel_energy_line_label(self, row):
        if row >= len(self.channel_energy_lines):
            return
        line = self.channel_energy_lines[row]
        if line is None:
            return
        label_text = self.channel_energy_label_text(row)
        if getattr(line, "_label_text", None) == label_text:
            return
        line._label_text = label_text
        if label_text:
            if hasattr(line, "label"):
                line.label.format = label_text
                line.label.valueChanged()
                line.label.setVisible(True)
            else:
                line.label = pg.InfLineLabel(line, text=label_text, position=0.75, color=(70, 130, 180))
        else:
            if hasattr(line, "label"):
                line.label.setVisible(False)

    def on_channel_energy_line_moved(self, line):
        if self._suppress_channel_line_update:
            return
        row = getattr(line, "_channel_energy_row", None)
        if row is None or row >= self.channel_energy_table.rowCount():
            return
        channel = int(round(line.value()))
        self._suppress_channel_energy_item_changed = True
        item = self.channel_energy_table.item(row, 0)
        if item is None:
            item = QTableWidgetItem("")
            self.channel_energy_table.setItem(row, 0, item)
        item.setText(str(channel))
        self._suppress_channel_energy_item_changed = False
        self._suppress_channel_line_update = True
        line.setValue(channel)
        self._suppress_channel_line_update = False
        self.update_line_label_positions()

    def sync_channel_energy_lines(self):
        row_count = self.channel_energy_table.rowCount()
        if len(self.channel_energy_lines) < row_count:
            self.channel_energy_lines.extend([None] * (row_count - len(self.channel_energy_lines)))
        elif len(self.channel_energy_lines) > row_count:
            for extra_line in self.channel_energy_lines[row_count:]:
                if extra_line is not None:
                    self.plot_widget.removeItem(extra_line)
            self.channel_energy_lines = self.channel_energy_lines[:row_count]
        for row in range(row_count):
            item = self.channel_energy_table.item(row, 0)
            if item is None:
                continue
            try:
                channel = float(item.text())
            except ValueError:
                channel = None
            if channel is None:
                if self.channel_energy_lines[row] is not None:
                    self.plot_widget.removeItem(self.channel_energy_lines[row])
                    self.channel_energy_lines[row] = None
                continue
            self.ensure_channel_energy_line(row, channel)
            self.update_channel_energy_line_label(row)

    def update_channel_energy_line_indices(self):
        for idx, line in enumerate(self.channel_energy_lines):
            if line is not None:
                line._channel_energy_row = idx

    def estimate_calibration(self):
        channels = []
        energies = []
        for row in range(self.channel_energy_table.rowCount()):
            channel_item = self.channel_energy_table.item(row, 0)
            energy_item = self.channel_energy_table.item(row, 1)
            if channel_item is None or energy_item is None:
                continue
            try:
                channel = float(channel_item.text())
                energy = float(energy_item.text())
            except ValueError:
                continue
            channels.append(channel)
            energies.append(energy)
        if len(channels) < 2:
            QMessageBox.information(self, "Calibration", "Add at least two channel-energy points.")
            return
        slope, offset = np.polyfit(channels, energies, 1)
        self.slope_spin.setValue(slope)
        self.offset_spin.setValue(offset)
        self.update_energy_lines()

    def get_calibration_coeffs(self) -> Tuple[float, float]:
        return self.slope_spin.value(), self.offset_spin.value()

    def load_energy_config(self):
        raw = self.settings.value(self.energy_config_key, "")
        if not raw:
            return
        try:
            entries = json.loads(raw)
        except Exception:
            return
        if not isinstance(entries, list):
            return
        self._suppress_energy_item_changed = True
        self.energy_table.setRowCount(0)
        for entry in entries:
            energy_text = ""
            element_text = ""
            checked = True
            if isinstance(entry, dict):
                energy_text = "" if entry.get("energy") is None else str(entry.get("energy"))
                element_text = "" if entry.get("element") is None else str(entry.get("element"))
                checked = bool(entry.get("checked", True))
            row = self.energy_table.rowCount()
            self.energy_table.insertRow(row)
            energy_item = QTableWidgetItem(energy_text)
            energy_item.setFlags(energy_item.flags() | Qt.ItemIsUserCheckable)
            energy_item.setCheckState(Qt.Checked if checked else Qt.Unchecked)
            element_item = QTableWidgetItem(element_text)
            self.energy_table.setItem(row, 0, energy_item)
            self.energy_table.setItem(row, 1, element_item)
        self._suppress_energy_item_changed = False
        self.update_energy_lines()

    def save_energy_config(self):
        entries = []
        for row in range(self.energy_table.rowCount()):
            energy_item = self.energy_table.item(row, 0)
            element_item = self.energy_table.item(row, 1)
            energy_text = energy_item.text().strip() if energy_item else ""
            element_text = element_item.text().strip() if element_item else ""
            checked = energy_item.checkState() == Qt.Checked if energy_item else True
            entries.append({
                "energy": energy_text,
                "element": element_text,
                "checked": checked,
            })
        self.settings.setValue(self.energy_config_key, json.dumps(entries))

    def add_energy_row(self):
        row = self.energy_table.rowCount()
        self.energy_table.insertRow(row)
        energy_item = QTableWidgetItem("0.0")
        energy_item.setFlags(energy_item.flags() | Qt.ItemIsUserCheckable)
        energy_item.setCheckState(Qt.Checked)
        element_item = QTableWidgetItem("")
        self._suppress_energy_item_changed = True
        self.energy_table.setItem(row, 0, energy_item)
        self.energy_table.setItem(row, 1, element_item)
        self._suppress_energy_item_changed = False
        self.save_energy_config()
        self.update_energy_lines()

    def remove_selected_energy_rows(self):
        rows = sorted({idx.row() for idx in self.energy_table.selectionModel().selectedRows()}, reverse=True)
        for row in rows:
            self.energy_table.removeRow(row)
        self.save_energy_config()
        self.update_energy_lines()

    def on_energy_item_changed(self, item):
        if self._suppress_energy_item_changed:
            return
        if item is None:
            return
        self.save_energy_config()
        self.update_energy_lines()

    def import_selected_energies(self):
        selection = self.energy_table.selectionModel().selectedRows()
        rows = sorted({idx.row() for idx in selection})
        if not rows:
            rows = list(range(self.energy_table.rowCount()))
        slope = self.slope_spin.value()
        offset = self.offset_spin.value()
        for row in rows:
            energy_item = self.energy_table.item(row, 0)
            element_item = self.energy_table.item(row, 1)
            if energy_item is None:
                continue
            try:
                energy = float(energy_item.text())
            except ValueError:
                continue
            if slope != 0:
                channel = int(round((energy - offset) / slope))
            else:
                channel = 0
            new_row = self.channel_energy_table.rowCount()
            self.channel_energy_table.insertRow(new_row)
            self._suppress_channel_energy_item_changed = True
            self.channel_energy_table.setItem(new_row, 0, QTableWidgetItem(str(channel)))
            self.channel_energy_table.setItem(new_row, 1, QTableWidgetItem(str(energy)))
            label_text = element_item.text().strip() if element_item else ""
            self.channel_energy_table.setItem(new_row, 2, QTableWidgetItem(label_text))
            self._suppress_channel_energy_item_changed = False
            self.channel_energy_lines.append(None)
        self.sync_channel_energy_lines()
        self.update_line_label_positions()

    def collect_project_data(self):
        logs = []
        for row in range(self.log_table.rowCount()):
            log_item = self.log_table.item(row, 0)
            label_item = self.log_table.item(row, 1)
            if log_item is None:
                continue
            logs.append({
                "path": log_item.data(Qt.UserRole),
                "label": label_item.text().strip() if label_item else "",
                "checked": log_item.checkState() == Qt.Checked,
            })

        channel_energy = []
        for row in range(self.channel_energy_table.rowCount()):
            channel_item = self.channel_energy_table.item(row, 0)
            energy_item = self.channel_energy_table.item(row, 1)
            label_item = self.channel_energy_table.item(row, 2)
            channel_energy.append({
                "channel": channel_item.text().strip() if channel_item else "",
                "energy": energy_item.text().strip() if energy_item else "",
                "label": label_item.text().strip() if label_item else "",
            })

        selected_energies = []
        for row in range(self.energy_table.rowCount()):
            energy_item = self.energy_table.item(row, 0)
            element_item = self.energy_table.item(row, 1)
            selected_energies.append({
                "energy": energy_item.text().strip() if energy_item else "",
                "element": element_item.text().strip() if element_item else "",
                "checked": energy_item.checkState() == Qt.Checked if energy_item else True,
            })

        return {
            "version": 1,
            "logs": logs,
            "channel_energy": channel_energy,
            "selected_energies": selected_energies,
            "constants": {
                "slope": self.slope_spin.value(),
                "offset": self.offset_spin.value(),
            },
            "log_scale": self.log_scale_checkbox.isChecked(),
        }

    def apply_project_data(self, data):
        if not isinstance(data, dict):
            QMessageBox.warning(self, "Project load error", "Project file has invalid format.")
            return

        self._suppress_log_item_changed = True
        self._suppress_energy_item_changed = True
        self._suppress_channel_energy_item_changed = True
        self.log_table.setRowCount(0)
        self.channel_energy_table.setRowCount(0)
        self.energy_table.setRowCount(0)
        self._suppress_log_item_changed = False
        self._suppress_energy_item_changed = False
        self._suppress_channel_energy_item_changed = False

        self.log_data = {}
        self.channel_energy_lines = []
        self.energy_lines = []

        missing_logs = []
        for entry in data.get("logs", []):
            file_path = entry.get("path")
            if not file_path:
                continue
            try:
                channels, counts = self.load_csv_counts(file_path)
            except Exception:
                missing_logs.append(file_path)
                continue
            self.log_data[file_path] = {"channels": channels, "counts": counts}
            self.add_log_row(file_path)
            row = self.log_table.rowCount() - 1
            log_item = self.log_table.item(row, 0)
            label_item = self.log_table.item(row, 1)
            self._suppress_log_item_changed = True
            if log_item is not None:
                log_item.setCheckState(Qt.Checked if entry.get("checked", True) else Qt.Unchecked)
            if label_item is not None:
                label_item.setText(entry.get("label", label_item.text()))
            self._suppress_log_item_changed = False

        for entry in data.get("channel_energy", []):
            row = self.channel_energy_table.rowCount()
            self.channel_energy_table.insertRow(row)
            self._suppress_channel_energy_item_changed = True
            self.channel_energy_table.setItem(row, 0, QTableWidgetItem(str(entry.get("channel", ""))))
            self.channel_energy_table.setItem(row, 1, QTableWidgetItem(str(entry.get("energy", ""))))
            self.channel_energy_table.setItem(row, 2, QTableWidgetItem(str(entry.get("label", ""))))
            self._suppress_channel_energy_item_changed = False
            self.channel_energy_lines.append(None)

        for entry in data.get("selected_energies", []):
            row = self.energy_table.rowCount()
            self.energy_table.insertRow(row)
            energy_item = QTableWidgetItem(str(entry.get("energy", "")))
            energy_item.setFlags(energy_item.flags() | Qt.ItemIsUserCheckable)
            energy_item.setCheckState(Qt.Checked if entry.get("checked", True) else Qt.Unchecked)
            element_item = QTableWidgetItem(str(entry.get("element", "")))
            self._suppress_energy_item_changed = True
            self.energy_table.setItem(row, 0, energy_item)
            self.energy_table.setItem(row, 1, element_item)
            self._suppress_energy_item_changed = False

        constants = data.get("constants", {})
        self.slope_spin.setValue(float(constants.get("slope", self.slope_spin.value())))
        self.offset_spin.setValue(float(constants.get("offset", self.offset_spin.value())))
        self.log_scale_checkbox.setChecked(bool(data.get("log_scale", False)))

        self.save_energy_config()
        self.sync_channel_energy_lines()
        self.update_plot()

        if missing_logs:
            QMessageBox.information(
                self,
                "Project load",
                "Some logs could not be loaded:\n" + "\n".join(missing_logs),
            )

    def save_project(self):
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save calibration project",
            "",
            "Calibration project (*.dosview_calib);;All files (*)"
        )
        if not file_path:
            return
        if not file_path.endswith(".dosview_calib"):
            file_path = f"{file_path}.dosview_calib"
        payload = self.collect_project_data()
        try:
            with open(file_path, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2, ensure_ascii=True)
        except Exception as exc:
            QMessageBox.warning(self, "Save error", f"Failed to save project: {exc}")

    def load_project(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Load calibration project",
            "",
            "Calibration project (*.dosview_calib);;All files (*)"
        )
        if not file_path:
            return
        try:
            with open(file_path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except Exception as exc:
            QMessageBox.warning(self, "Load error", f"Failed to load project: {exc}")
            return
        self.apply_project_data(payload)

    def update_plot(self):
        plot_item = self.plot_widget.plotItem
        plot_item.clear()
        self.plot_widget.showGrid(x=True, y=True, alpha=0.25)
        log_scale = self.log_scale_checkbox.isChecked()
        self.plot_widget.setLogMode(x=False, y=log_scale)
        self.plot_widget.setLabel("left", "Counts" if log_scale else "Normalized counts")
        self.plot_widget.setLabel("bottom", "Channel")
        legend = self.ensure_legend()
        self.legend_formula_item = pg.PlotDataItem([], [], pen=None)
        legend.addItem(self.legend_formula_item, self.legend_formula_text())
        legend.setBrush(pg.mkBrush(255, 255, 255, 200))
        legend.setPen(pg.mkPen((180, 180, 180)))

        active_rows = []
        for row in range(self.log_table.rowCount()):
            log_item = self.log_table.item(row, 0)
            if log_item is None:
                continue
            if log_item.checkState() != Qt.Checked:
                continue
            label_item = self.log_table.item(row, 1)
            label = label_item.text().strip() if label_item else log_item.text()
            file_path = log_item.data(Qt.UserRole)
            data = self.log_data.get(file_path)
            if not data:
                continue
            active_rows.append((label, data))

        for idx, (label, data) in enumerate(active_rows):
            pen = pg.mkPen(color=pg.intColor(idx, hues=max(1, len(active_rows))), width=1.5)
            counts = data["counts"].astype(float)
            if log_scale:
                counts = np.where(counts > 0, counts, np.nan)
            else:
                max_count = np.nanmax(counts) if counts.size else 0
                counts = counts / max_count if max_count > 0 else counts
            channels = data["channels"].astype(float)
            if channels.size != counts.size:
                min_len = min(channels.size, counts.size)
                channels = channels[:min_len]
                counts = counts[:min_len]
            if channels.size == 0:
                continue
            self.plot_widget.plot(
                channels,
                counts,
                pen=pen,
                name=label,
                stepMode="right",
            )

        self.sync_channel_energy_lines()
        self.update_energy_lines()
        self.update_line_label_positions()

    def update_energy_lines(self):
        for line in self.energy_lines:
            self.plot_widget.removeItem(line)
        self.energy_lines = []
        slope = self.slope_spin.value()
        if slope == 0:
            return
        offset = self.offset_spin.value()
        for row in range(self.energy_table.rowCount()):
            energy_item = self.energy_table.item(row, 0)
            if energy_item is None:
                continue
            if energy_item.checkState() != Qt.Checked:
                continue
            element_item = self.energy_table.item(row, 1)
            element = element_item.text().strip() if element_item else ""
            try:
                energy = float(energy_item.text())
            except ValueError:
                continue
            channel = (energy - offset) / slope
            label_text = f"{element} {energy:g}".strip() if element else f"{energy:g}"
            line = pg.InfiniteLine(
                pos=channel,
                angle=90,
                pen=pg.mkPen((180, 180, 180), style=Qt.DashLine),
                label=label_text,
                labelOpts={"position": 0.9, "color": (120, 120, 120)},
            )
            line.setZValue(5)
            self.plot_widget.addItem(line)
            self.energy_lines.append(line)
        self.update_line_label_positions()
        self.update_plot_legend_formula()
        self.update_energy_axis()

    def ensure_legend(self):
        if self.plot_legend is None or self.plot_legend.scene() is None:
            self.plot_legend = self.plot_widget.addLegend()
        else:
            self.plot_legend.clear()
        self.legend_formula_item = None
        return self.plot_legend

    def legend_formula_text(self):
        slope, offset = self.get_calibration_coeffs()
        offset_sign = "+" if offset >= 0 else "-"
        return f"E [keV] = {slope:.6g}*ch {offset_sign} {abs(offset):.6g}"

    def update_plot_legend_formula(self):
        if self.plot_legend is None or self.plot_legend.scene() is None:
            return
        if self.legend_formula_item is None:
            return
        label = self.plot_legend.getLabel(self.legend_formula_item)
        if label is not None:
            label.setText(self.legend_formula_text())

    def update_energy_axis(self):
        if self.energy_axis is None:
            return
        self.energy_axis.setLabel("Energy (keV)")
        self.energy_axis.update()

    def toggle_energy_axis(self, checked):
        if self.energy_axis is None:
            return
        self.energy_axis.setVisible(checked)
        self.energy_axis.setHeight(30 if checked else 0)
        self.plot_widget.plotItem.layout.setRowSpacing(3, 4 if checked else 0)
        self.update_energy_axis()

    def on_mouse_moved(self, event):
        if isinstance(event, tuple):
            pos = event[0]
        else:
            pos = event
        vb = self.plot_widget.plotItem.vb
        if not vb.sceneBoundingRect().contains(pos):
            self.cursor_label.setText("Ch: --  E: -- keV")
            return
        mouse_point = vb.mapSceneToView(pos)
        channel = mouse_point.x()
        slope, offset = self.get_calibration_coeffs()
        energy = slope * channel + offset
        self.cursor_label.setText(f"Ch: {channel:.2f}  E: {energy:.2f} keV")

    def update_line_label_positions(self):
        labeled_lines = []
        for line in self.channel_energy_lines:
            if line is None or not hasattr(line, "label"):
                continue
            if not line.label.isVisible():
                continue
            labeled_lines.append(line)
        for line in self.energy_lines:
            if line is None or not hasattr(line, "label"):
                continue
            if not line.label.isVisible():
                continue
            labeled_lines.append(line)
        labeled_lines.sort(key=lambda ln: ln.value())
        positions = [0.92, 0.84, 0.76, 0.68, 0.6, 0.52, 0.44, 0.36]
        for idx, line in enumerate(labeled_lines):
            pos = positions[idx % len(positions)]
            line.label.orthoPos = pos
            line.label.updatePosition()

    def save_plot(self):
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save plot image",
            "",
            "PNG Image (*.png);;JPEG Image (*.jpg *.jpeg);;All files (*)"
        )
        if not file_path:
            return
        exporter = ImageExporter(self.plot_widget.plotItem)
        exporter.export(file_path)

    def show_matplotlib(self):
        try:
            import matplotlib.pyplot as plt
        except Exception as exc:
            QMessageBox.warning(self, "Matplotlib missing", f"Failed to import matplotlib: {exc}")
            return
        fig, ax = plt.subplots()
        log_scale = self.log_scale_checkbox.isChecked()
        channel_min = None
        channel_max = None
        for row in range(self.log_table.rowCount()):
            log_item = self.log_table.item(row, 0)
            if log_item is None or log_item.checkState() != Qt.Checked:
                continue
            label_item = self.log_table.item(row, 1)
            label = label_item.text().strip() if label_item else log_item.text()
            file_path = log_item.data(Qt.UserRole)
            data = self.log_data.get(file_path)
            if not data:
                continue
            counts = data["counts"].astype(float)
            if log_scale:
                counts = np.where(counts > 0, counts, np.nan)
            else:
                max_count = np.nanmax(counts) if counts.size else 0
                counts = counts / max_count if max_count > 0 else counts
            channels = data["channels"].astype(float)
            if channels.size != counts.size:
                min_len = min(channels.size, counts.size)
                channels = channels[:min_len]
                counts = counts[:min_len]
            if channels.size == 0:
                continue
            ax.step(channels, counts, where="post", label=label)
            channel_min = np.nanmin(channels) if channel_min is None else min(channel_min, np.nanmin(channels))
            channel_max = np.nanmax(channels) if channel_max is None else max(channel_max, np.nanmax(channels))
        slope = self.slope_spin.value()
        offset = self.offset_spin.value()
        if channel_min is None or channel_max is None:
            channel_min, channel_max = 0.0, 1.0
        ax.set_xlim(channel_min, channel_max)
        ax.legend()
        for line in self.energy_lines:
            if line is None:
                continue
            ax.axvline(line.value(), color="0.7", linestyle="--")
            if hasattr(line, "label") and line.label.isVisible():
                ax.text(line.value(), 0.98, line.label.format, rotation=90, va="top", ha="right", transform=ax.get_xaxis_transform())
        for line in self.channel_energy_lines:
            if line is None:
                continue
            ax.axvline(line.value(), color="tab:blue", linestyle="-")
            if hasattr(line, "label") and line.label.isVisible():
                ax.text(line.value(), 0.9, line.label.format, rotation=90, va="top", ha="left", transform=ax.get_xaxis_transform())
        ax.set_xlabel("Channel")
        ax.set_ylabel("Counts" if log_scale else "Normalized counts")
        if log_scale:
            ax.set_yscale("log")
        ax.grid(False)
        ax.spines["top"].set_visible(False)
        ax.spines["bottom"].set_position(("outward", 4))
        ax.tick_params(axis="x", pad=6)
        energy_axis = ax.twiny()
        energy_axis.xaxis.set_ticks_position("bottom")
        energy_axis.xaxis.set_label_position("bottom")
        energy_axis.spines["bottom"].set_position(("outward", 40))
        energy_axis.spines["top"].set_visible(False)
        if slope == 0:
            energy_min = offset - 0.5
            energy_max = offset + 0.5
        else:
            energy_min = slope * channel_min + offset
            energy_max = slope * channel_max + offset
        if energy_min > energy_max:
            energy_min, energy_max = energy_max, energy_min
        energy_axis.set_xlim(energy_min, energy_max)
        energy_axis.set_xlabel("Energy (keV)")
        energy_axis.tick_params(axis="x", pad=2)
        energy_axis.grid(True, axis="x", color="0.85", linestyle="-")
        offset_sign = "+" if offset >= 0 else "-"
        ax.set_title(f"Dosimeter calibration: E [keV] = {slope:.6g}*ch {offset_sign} {abs(offset):.6g}")
        fig.tight_layout()
        fig.canvas.draw_idle()
        plt.show()
