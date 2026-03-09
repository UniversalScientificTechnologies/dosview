import datetime
import os

import numpy as np
import pyqtgraph as pg

from PyQt5.QtCore import QThread, QTimer, Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .parsers import CoincidenceLogParser


class CoincidenceLoadThread(QThread):
    loaded = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, file_path):
        super().__init__()
        self.file_path = file_path

    def run(self):
        try:
            data = CoincidenceLogParser(self.file_path).parse()
        except Exception as exc:  # pragma: no cover - GUI signal path
            self.failed.emit(str(exc))
            return
        self.loaded.emit(data)


class CoincidenceTab(QWidget):
    def __init__(self):
        super().__init__()
        self.file_path = ""
        self.current_data = None
        self.last_file_signature = None
        self.channel_pair = 0
        self.load_thread = None
        self._preserve_view_on_next_update = False
        self.init_ui()

    def init_ui(self):
        root_layout = QHBoxLayout()
        self.setLayout(root_layout)

        left_panel = QWidget()
        left_panel.setFixedWidth(320)
        left_layout = QVBoxLayout()
        left_panel.setLayout(left_layout)

        self.open_button = QPushButton("Open log")
        self.open_button.clicked.connect(self.open_file_dialog)
        left_layout.addWidget(self.open_button)

        self.reload_button = QPushButton("Reload log")
        self.reload_button.clicked.connect(lambda: self.load_file(self.file_path, force=True))
        left_layout.addWidget(self.reload_button)

        self.swap_button = QPushButton("Swap channels")
        self.swap_button.clicked.connect(self.swap_channels)
        left_layout.addWidget(self.swap_button)

        self.live_reload_checkbox = QCheckBox("Live reload (10 s)")
        self.live_reload_checkbox.toggled.connect(self.toggle_live_reload)
        left_layout.addWidget(self.live_reload_checkbox)

        self.log_counts_checkbox = QCheckBox("Log counts axis")
        self.log_counts_checkbox.toggled.connect(self.update_count_axis_mode)
        left_layout.addWidget(self.log_counts_checkbox)

        self.file_label = QLabel("File: -")
        self.file_label.setWordWrap(True)
        left_layout.addWidget(self.file_label)

        self.channel_label = QLabel("2D histogram: val0 vs. val0 - val0b")
        self.channel_label.setWordWrap(True)
        left_layout.addWidget(self.channel_label)

        self.status_label = QLabel("No log loaded")
        self.status_label.setWordWrap(True)
        left_layout.addWidget(self.status_label)

        self.metadata_tree = QTreeWidget()
        self.metadata_tree.setColumnCount(2)
        self.metadata_tree.setHeaderLabels(["Property", "Value"])
        left_layout.addWidget(self.metadata_tree, stretch=1)

        right_panel = QWidget()
        right_layout = QVBoxLayout()
        right_panel.setLayout(right_layout)

        self.energy_plot = pg.PlotWidget()
        self.energy_plot.showGrid(x=True, y=True, alpha=0.25)
        self.energy_plot.setLabel("left", "Counts")
        self.energy_plot.setLabel("bottom", "Energy channel")
        self.energy_plot.addLegend()
        right_layout.addWidget(self.energy_plot, stretch=1)

        orange_pen = pg.mkPen(color=(230, 140, 30), width=2)
        orange_dash_pen = pg.mkPen(color=(230, 140, 30), width=2, style=Qt.DashLine)
        blue_pen = pg.mkPen(color=(50, 110, 220), width=2)
        blue_dash_pen = pg.mkPen(color=(50, 110, 220), width=2, style=Qt.DashLine)

        self.val0_curve = self.energy_plot.plot(name="val0", pen=orange_pen)
        self.val1_curve = self.energy_plot.plot(name="val1", pen=blue_pen)
        self.val0b_curve = self.energy_plot.plot(name="val0b", pen=orange_dash_pen)
        self.val1b_curve = self.energy_plot.plot(name="val1b", pen=blue_dash_pen)

        self.delta_plot = pg.PlotWidget()
        self.delta_plot.showGrid(x=True, y=True, alpha=0.15)
        self.delta_plot.setLabel("left", "Delta")
        self.delta_plot.setLabel("bottom", "Energy channel")
        self.delta_plot.getViewBox().setAspectLocked(False)
        self.delta_image = pg.ImageItem()
        self.delta_plot.addItem(self.delta_image)
        cmap = pg.ColorMap(
            [0.0, 0.2, 0.5, 1.0],
            [
                (0, 0, 140, 255),
                (0, 170, 255, 255),
                (255, 215, 0, 255),
                (200, 0, 0, 255),
            ],
        )
        self.delta_lut = cmap.getLookupTable(0.0, 1.0, 256)
        self.delta_image.setLookupTable(self.delta_lut)
        self.delta_colorbar = pg.ColorBarItem(
            values=(0, 1),
            colorMap=cmap,
            label="Counts",
            interactive=False,
        )
        self.delta_colorbar.setImageItem(self.delta_image)
        self.delta_plot.getPlotItem().layout.addItem(self.delta_colorbar, 2, 1)
        right_layout.addWidget(self.delta_plot, stretch=1)

        root_layout.addWidget(left_panel)
        root_layout.addWidget(right_panel, stretch=1)

        self.live_reload_timer = QTimer(self)
        self.live_reload_timer.setInterval(10000)
        self.live_reload_timer.timeout.connect(self.reload_if_changed)

    def open_file(self, file_path):
        self.load_file(file_path, force=True)

    def open_file_dialog(self):
        file_path, _selected_filter = QFileDialog.getOpenFileName(
            self,
            "Open coincidence log",
            "",
            "Coincidence files (*.ddfc);;Log files (*.ddfc *.txt *.log *.dos *.csv);;All files (*)",
        )
        if file_path:
            self.load_file(file_path, force=True)

    def load_file(self, file_path, force=False):
        if not file_path:
            self.status_label.setText("No file selected")
            return
        if self.load_thread is not None and self.load_thread.isRunning():
            return
        if not force and not self._file_has_changed(file_path):
            return

        self._preserve_view_on_next_update = bool(self.current_data)
        self.file_path = file_path
        self.file_label.setText(f"File: {file_path}")
        self.status_label.setText("Loading log...")

        self.load_thread = CoincidenceLoadThread(file_path)
        self.load_thread.loaded.connect(self.on_data_loaded)
        self.load_thread.failed.connect(self.on_load_failed)
        self.load_thread.start()

    def on_data_loaded(self, data):
        self.current_data = data
        self.last_file_signature = self._get_file_signature(self.file_path)
        self.update_metadata_tree()
        self.update_plots(preserve_view=self._preserve_view_on_next_update)
        self._preserve_view_on_next_update = False
        loaded_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.status_label.setText(f"Loaded at {loaded_at}")

    def on_load_failed(self, error_message):
        self.status_label.setText(f"Load failed: {error_message}")

    def update_metadata_tree(self):
        self.metadata_tree.clear()
        if not self.current_data:
            return

        metadata = self.current_data["metadata"]

        def add_node(parent_item, key, value):
            if isinstance(value, dict):
                item = QTreeWidgetItem([str(key)])
                parent_item.addChild(item)
                for child_key, child_value in value.items():
                    add_node(item, child_key, child_value)
                return
            parent_item.addChild(QTreeWidgetItem([str(key), str(value)]))

        for key, value in metadata.items():
            if isinstance(value, dict):
                root_item = QTreeWidgetItem([str(key)])
                self.metadata_tree.addTopLevelItem(root_item)
                for child_key, child_value in value.items():
                    add_node(root_item, child_key, child_value)
            else:
                self.metadata_tree.addTopLevelItem(QTreeWidgetItem([str(key), str(value)]))
        self.metadata_tree.expandAll()

    def update_plots(self, preserve_view=False):
        if not self.current_data:
            return

        energy_view_range = self._capture_view_range(self.energy_plot) if preserve_view else None
        delta_view_range = self._capture_view_range(self.delta_plot) if preserve_view else None
        energy_autorange = self._capture_autorange_state(self.energy_plot) if preserve_view else None
        delta_autorange = self._capture_autorange_state(self.delta_plot) if preserve_view else None
        if preserve_view:
            self._set_autorange_enabled(self.energy_plot, False)
            self._set_autorange_enabled(self.delta_plot, False)

        histograms = self.current_data["histograms"]
        bins_count = max(len(values) for values in histograms.values())
        x_axis = np.arange(bins_count)

        self.val0_curve.setData(x=x_axis, y=histograms["val0"], stepMode=False)
        self.val0b_curve.setData(x=x_axis, y=histograms["val0b"], stepMode=False)
        self.val1_curve.setData(x=x_axis, y=histograms["val1"], stepMode=False)
        self.val1b_curve.setData(x=x_axis, y=histograms["val1b"], stepMode=False)
        self.update_count_axis_mode()

        cached_hist = self.get_cached_delta_histogram()
        matrix = cached_hist["matrix"]
        x_max = cached_hist["x_max"]
        delta_min = cached_hist["delta_min"]
        delta_max = cached_hist["delta_max"]
        if matrix.size == 0:
            self.delta_image.setImage(np.zeros((1, 1), dtype=float))
            self.delta_image.setRect(pg.QtCore.QRectF(-0.5, -0.5, 1.0, 1.0))
            self.delta_colorbar.setLevels((0, 1))
            self._restore_view_range(self.energy_plot, energy_view_range)
            self._restore_view_range(self.delta_plot, delta_view_range)
            self._restore_autorange_state(self.energy_plot, energy_autorange)
            self._restore_autorange_state(self.delta_plot, delta_autorange)
            return

        image = matrix.T.astype(float)
        image[image == 0] = np.nan
        self.delta_image.setImage(image, autoLevels=False)
        finite_values = image[np.isfinite(image)]
        max_count = float(np.max(finite_values)) if finite_values.size else 1.0
        self.delta_image.setLevels((0.0, max(1.0, max_count)))
        self.delta_colorbar.setLevels((0.0, max(1.0, max_count)))
        self.delta_image.setRect(
            pg.QtCore.QRectF(
                -0.5,
                delta_min - 0.5,
                float(x_max + 1),
                float(delta_max - delta_min + 1),
            )
        )
        if preserve_view:
            self._restore_view_range(self.energy_plot, energy_view_range)
            self._restore_view_range(self.delta_plot, delta_view_range)
            self._restore_autorange_state(self.energy_plot, energy_autorange)
            self._restore_autorange_state(self.delta_plot, delta_autorange)
        else:
            self.delta_plot.setXRange(-0.5, x_max + 0.5, padding=0)
            self.delta_plot.setYRange(delta_min - 0.5, delta_max + 0.5, padding=0)

    def get_cached_delta_histogram(self):
        if not self.current_data:
            return {
                "matrix": np.zeros((0, 0), dtype=int),
                "x_max": 0,
                "delta_min": 0,
                "delta_max": 0,
            }
        if self.channel_pair == 0:
            primary_label = "val0"
            secondary_label = "val0b"
            cache_key = "val0"
        else:
            primary_label = "val1"
            secondary_label = "val1b"
            cache_key = "val1"

        self.channel_label.setText(
            f"2D histogram: {primary_label} vs. {primary_label} - {secondary_label}"
        )
        self.delta_plot.setLabel("bottom", primary_label)
        self.delta_plot.setLabel("left", f"{primary_label} - {secondary_label}")
        return self.current_data.get("delta_histograms", {}).get(
            cache_key,
            {
                "matrix": np.zeros((0, 0), dtype=int),
                "x_max": 0,
                "delta_min": 0,
                "delta_max": 0,
            },
        )

    def swap_channels(self):
        self.channel_pair = 1 - self.channel_pair
        self.update_plots(preserve_view=True)

    def update_count_axis_mode(self):
        self.energy_plot.setLogMode(x=False, y=self.log_counts_checkbox.isChecked())

    def _capture_view_range(self, plot_widget):
        view_box = plot_widget.getViewBox()
        x_range, y_range = view_box.viewRange()
        return (tuple(x_range), tuple(y_range))

    def _capture_autorange_state(self, plot_widget):
        view_box = plot_widget.getViewBox()
        return (
            bool(view_box.state["autoRange"][0]),
            bool(view_box.state["autoRange"][1]),
        )

    def _restore_view_range(self, plot_widget, view_range):
        if view_range is None:
            return
        (x_min, x_max), (y_min, y_max) = view_range
        plot_widget.setXRange(x_min, x_max, padding=0)
        plot_widget.setYRange(y_min, y_max, padding=0)

    def _set_autorange_enabled(self, plot_widget, enabled):
        plot_widget.enableAutoRange(x=enabled, y=enabled)

    def _restore_autorange_state(self, plot_widget, autorange_state):
        if autorange_state is None:
            return
        plot_widget.enableAutoRange(x=autorange_state[0], y=autorange_state[1])

    def toggle_live_reload(self, checked):
        if checked:
            self.status_label.setText("Live reload enabled, checking every 10 s")
            self.live_reload_timer.start()
        else:
            self.live_reload_timer.stop()

    def reload_if_changed(self):
        if not self.file_path:
            return
        if self._file_has_changed(self.file_path):
            self.status_label.setText("Change detected, reloading...")
            self.load_file(self.file_path, force=True)

    def _file_has_changed(self, file_path):
        current_signature = self._get_file_signature(file_path)
        if current_signature is None:
            return True
        if self.last_file_signature is None:
            return True
        return current_signature != self.last_file_signature

    def _get_file_signature(self, file_path):
        try:
            stat_result = os.stat(file_path)
        except OSError:
            return None
        return (int(stat_result.st_mtime_ns), int(stat_result.st_size))

    def cleanup(self):
        self.live_reload_timer.stop()
        if self.load_thread is not None and self.load_thread.isRunning():
            self.load_thread.quit()
            self.load_thread.wait(1000)
