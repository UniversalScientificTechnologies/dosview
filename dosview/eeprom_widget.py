"""PyQt5 widget for viewing/editing EEPROM content.

This widget stays reusable: parent provides callbacks for device IO.
Single column editor with load/save functionality.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Optional

from PyQt5 import QtCore, QtWidgets

from .eeprom_schema import (
    DeviceType,
    EepromRecord,
    TOTAL_SIZE,
    compute_crc32,
    pack_record,
    unpack_record,
)
from .loading_dialog import LoadingContext


IntReader = Callable[[], bytes]
IntWriter = Callable[[bytes], None]


class EepromManagerWidget(QtWidgets.QWidget):
    def __init__(
        self,
        parent: Optional[QtWidgets.QWidget] = None,
        read_device: Optional[IntReader] = None,
        write_device: Optional[IntWriter] = None,
        io_context: Optional[Any] = None,
    ) -> None:
        super().__init__(parent)
        self._read_device = read_device
        self._write_device = write_device
        self._io_context = io_context
        self._widgets = {}
        self._build_ui()

    # UI construction -----------------------------------------------------
    def _build_ui(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)

        # Buttons
        buttons = QtWidgets.QHBoxLayout()
        self.btn_load_device = QtWidgets.QPushButton("📋 Load from Device")
        self.btn_write_device = QtWidgets.QPushButton("💾 Write to Device")
        self.btn_load_file = QtWidgets.QPushButton("📋 Load from File")
        self.btn_save_file = QtWidgets.QPushButton("💾 Save to File")
        
        for btn in (
            self.btn_load_device,
            self.btn_write_device,
            self.btn_load_file,
            self.btn_save_file,
        ):
            buttons.addWidget(btn)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        # Scroll area pro formulář
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_content = QtWidgets.QWidget()
        scroll.setWidget(scroll_content)
        
        form_layout = QtWidgets.QFormLayout(scroll_content)
        form_layout.setLabelAlignment(QtCore.Qt.AlignRight)
        
        # === Basic information ===
        form_layout.addRow(self._make_section_label("Basic Information"))
        
        self._widgets["format_version"] = self._make_int_field(minv=0, maxv=65535)
        form_layout.addRow("Format version:", self._widgets["format_version"])

        self._widgets["device_type"] = self._make_device_type_field()
        form_layout.addRow("Device type:", self._widgets["device_type"])

        self._widgets["crc32"] = self._make_line_edit(readonly=True)
        form_layout.addRow("CRC32:", self._widgets["crc32"])

        # === Hardware ===
        form_layout.addRow(self._make_section_label("Hardware"))
        
        hw_layout = QtWidgets.QHBoxLayout()
        self._widgets["hw_rev_major"] = self._make_int_field(minv=0, maxv=255)
        self._widgets["hw_rev_minor"] = self._make_int_field(minv=0, maxv=255)
        hw_layout.addWidget(self._widgets["hw_rev_major"])
        hw_layout.addWidget(QtWidgets.QLabel("."))
        hw_layout.addWidget(self._widgets["hw_rev_minor"])
        hw_layout.addStretch(1)
        form_layout.addRow("HW revision:", hw_layout)

        self._widgets["device_id"] = self._make_line_edit(max_length=10)
        form_layout.addRow("Device ID (max 10 chars):", self._widgets["device_id"])

        # === Configuration ===
        form_layout.addRow(self._make_section_label("Configuration"))
        
        self._widgets["config_flags"] = self._make_binary_field(bits=32)
        form_layout.addRow("Config flags (bin):", self._widgets["config_flags"])

        self._widgets["rtc_flags"] = self._make_binary_field(bits=8)
        form_layout.addRow("RTC flags (bin):", self._widgets["rtc_flags"])

        # === RTC synchronization ===
        form_layout.addRow(self._make_section_label("RTC Synchronization"))
        
        rtc_info = QtWidgets.QLabel("Timestamps for RTC clock synchronization")
        rtc_info.setStyleSheet("color: gray; font-size: 10px;")
        form_layout.addRow("", rtc_info)
        
        # Init time (kdy RTC bylo na 0)
        self._widgets["init_time"] = self._make_line_edit()
        self._widgets["init_time"].setPlaceholderText("Unix timestamp (s)")
        form_layout.addRow("Init time:", self._widgets["init_time"])
        
        self._widgets["init_time_label"] = QtWidgets.QLabel("")
        self._widgets["init_time_label"].setStyleSheet("color: #666; font-style: italic;")
        form_layout.addRow("", self._widgets["init_time_label"])
        
        # Sync time (čas poslední synchronizace)
        self._widgets["sync_time"] = self._make_line_edit()
        self._widgets["sync_time"].setPlaceholderText("Unix timestamp (s)")
        form_layout.addRow("Sync time:", self._widgets["sync_time"])
        
        self._widgets["sync_time_label"] = QtWidgets.QLabel("")
        self._widgets["sync_time_label"].setStyleSheet("color: #666; font-style: italic;")
        form_layout.addRow("", self._widgets["sync_time_label"])
        
        # Sync RTC seconds (RTC value at synchronization)
        self._widgets["sync_rtc_seconds"] = self._make_line_edit()
        self._widgets["sync_rtc_seconds"].setPlaceholderText("RTC seconds at sync")
        form_layout.addRow("Sync RTC seconds:", self._widgets["sync_rtc_seconds"])

        # === keV calibration ===
        form_layout.addRow(self._make_section_label("keV Calibration"))
        
        calib_info = QtWidgets.QLabel("Polynomial coefficients: keV = a₀ + a₁·ch + a₂·ch²")
        calib_info.setStyleSheet("color: gray; font-size: 10px;")
        form_layout.addRow("", calib_info)
        
        self._widgets["calib"] = []
        calib_labels = ["a₀ (offset) [keV]:", "a₁ (linear) [keV/ch]:", "a₂ (quadratic) [keV/ch²]:"]
        for i, label in enumerate(calib_labels):
            field = self._make_double_field()
            self._widgets["calib"].append(field)
            form_layout.addRow(label, field)

        self._widgets["calib_ts"] = self._make_line_edit()
        self._widgets["calib_ts"].setPlaceholderText("Unix timestamp")
        form_layout.addRow("Calibration timestamp:", self._widgets["calib_ts"])

        layout.addWidget(scroll)

        # Status bar
        self.status_label = QtWidgets.QLabel("Ready")
        self.status_label.setStyleSheet("padding: 5px; background: #f0f0f0; border-radius: 3px;")
        layout.addWidget(self.status_label)

        # Připojení signálů
        self.btn_load_device.clicked.connect(self._on_load_device)
        self.btn_write_device.clicked.connect(self._on_write_device)
        self.btn_load_file.clicked.connect(self._on_load_file)
        self.btn_save_file.clicked.connect(self._on_save_file)

    def _make_section_label(self, text: str) -> QtWidgets.QLabel:
        label = QtWidgets.QLabel(f"<b>{text}</b>")
        label.setStyleSheet("margin-top: 10px; color: #333;")
        return label

    # Field factories -----------------------------------------------------
    def _make_line_edit(self, readonly: bool = False, max_length: Optional[int] = None) -> QtWidgets.QLineEdit:
        le = QtWidgets.QLineEdit()
        le.setReadOnly(readonly)
        if max_length:
            le.setMaxLength(max_length)
        return le

    def _make_int_field(self, minv: int = 0, maxv: int = 0xFFFFFFFF) -> QtWidgets.QSpinBox:
        sb = QtWidgets.QSpinBox()
        max_qt = min(maxv, 2147483647)
        min_qt = max(minv, -2147483648)
        sb.setRange(min_qt, max_qt)
        sb.setButtonSymbols(QtWidgets.QAbstractSpinBox.NoButtons)
        return sb

    def _make_double_field(self) -> QtWidgets.QDoubleSpinBox:
        dsb = QtWidgets.QDoubleSpinBox()
        dsb.setRange(-1e9, 1e9)
        dsb.setDecimals(6)
        dsb.setButtonSymbols(QtWidgets.QAbstractSpinBox.NoButtons)
        return dsb

    def _make_binary_field(self, bits: int = 32) -> QtWidgets.QLineEdit:
        """Pole pro binární hodnotu."""
        le = QtWidgets.QLineEdit()
        le.setPlaceholderText("0" * bits)
        font = le.font()
        font.setFamily("monospace")
        le.setFont(font)
        le.setMaxLength(bits)
        return le

    def _make_device_type_field(self) -> QtWidgets.QComboBox:
        cb = QtWidgets.QComboBox()
        for dt in DeviceType:
            cb.addItem(dt.name, int(dt))
        return cb

    def _format_timestamp(self, ts: int) -> str:
        """Formátuje Unix timestamp na čitelný čas."""
        if ts <= 0:
            return ""
        try:
            import datetime
            dt = datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc)
            return dt.strftime("%Y-%m-%d %H:%M:%S UTC")
        except (OSError, ValueError):
            return "Neplatný čas"

    # Data population -----------------------------------------------------
    def _populate(self, record: EepromRecord) -> None:
        w = self._widgets
        w["format_version"].setValue(int(record.format_version))
        
        idx = w["device_type"].findData(int(record.device_type))
        if idx >= 0:
            w["device_type"].setCurrentIndex(idx)
        
        w["crc32"].setText(f"0x{record.crc32:08X}")
        w["hw_rev_major"].setValue(int(record.hw_rev_major))
        w["hw_rev_minor"].setValue(int(record.hw_rev_minor))
        w["device_id"].setText(record.device_id)
        
        # Binární zobrazení flagů
        w["config_flags"].setText(f"{record.config_flags:032b}")
        w["rtc_flags"].setText(f"{record.rtc_flags:08b}")

        # RTC synchronizace - samostatné položky
        w["init_time"].setText(str(record.init_time))
        w["init_time_label"].setText(self._format_timestamp(record.init_time))
        
        w["sync_time"].setText(str(record.sync_time))
        w["sync_time_label"].setText(self._format_timestamp(record.sync_time))
        
        w["sync_rtc_seconds"].setText(str(record.sync_rtc_seconds))

        # Kalibrační konstanty
        for widget, val in zip(w["calib"], record.calib):
            widget.setValue(float(val))
        
        w["calib_ts"].setText(str(int(record.calib_ts)))

    # Handlers ------------------------------------------------------------
    def _on_load_device(self) -> None:
        if not self._read_device:
            self._set_status("❌ Read function not connected")
            return
        try:
            with LoadingContext(self, "Loading EEPROM", "Reading data from device..."):
                data = self._read_device()
                record = unpack_record(data, verify_crc=False)
            self._populate(record)
            self._set_status("✅ Loaded from device")
        except Exception as exc:
            self._set_status(f"❌ Read error: {exc}")

    def _on_write_device(self) -> None:
        if not self._write_device:
            self._set_status("❌ Write function not connected")
            return
        try:
            record = self._collect_record()
            payload = pack_record(record, with_crc=True)
            
            with LoadingContext(self, "Writing EEPROM", "Writing data to device..."):
                self._write_device(payload)

                # Verifikace
                verified = None
                if self._read_device:
                    try:
                        read_back = self._read_device()
                        verified = read_back == payload
                    except Exception:
                        verified = False

            if verified is True:
                self._set_status("✅ Written to device (verified)")
            elif verified is False:
                self._set_status("⚠️ Written to device (verification failed)")
            else:
                self._set_status("✅ Written to device")
        except Exception as exc:
            self._set_status(f"❌ Write error: {exc}")

    def _on_load_file(self) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Open EEPROM", "", "EEPROM bin (*.bin);;All files (*)"
        )
        if not path:
            return
        try:
            data = Path(path).read_bytes()
            record = unpack_record(data, verify_crc=False)
            self._populate(record)
            self._set_status(f"✅ Loaded from file {Path(path).name}")
        except Exception as exc:
            self._set_status(f"❌ File load error: {exc}")

    def _on_save_file(self) -> None:
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Save EEPROM", "eeprom.bin", "EEPROM bin (*.bin);;All files (*)"
        )
        if not path:
            return
        try:
            record = self._collect_record()
            payload = pack_record(record, with_crc=True)
            Path(path).write_bytes(payload)
            self._set_status(f"✅ Saved to {Path(path).name}")
        except Exception as exc:
            self._set_status(f"❌ Save error: {exc}")

    # Helpers -------------------------------------------------------------
    def _collect_record(self) -> EepromRecord:
        """Sestaví EepromRecord z hodnot ve formuláři."""
        w = self._widgets
        try:
            format_version = int(w["format_version"].value())
            device_type = DeviceType(w["device_type"].currentData())
            hw_rev_major = int(w["hw_rev_major"].value())
            hw_rev_minor = int(w["hw_rev_minor"].value())
            device_id = w["device_id"].text()
            
            # Parsování binárních flagů
            config_flags_text = w["config_flags"].text().strip() or "0"
            config_flags = int(config_flags_text, 2)
            
            rtc_flags_text = w["rtc_flags"].text().strip() or "0"
            rtc_flags = int(rtc_flags_text, 2)
            
            # RTC synchronizace - samostatné položky
            init_time_text = w["init_time"].text().strip() or "0"
            init_time = int(init_time_text, 0)
            
            sync_time_text = w["sync_time"].text().strip() or "0"
            sync_time = int(sync_time_text, 0)
            
            sync_rtc_seconds_text = w["sync_rtc_seconds"].text().strip() or "0"
            sync_rtc_seconds = int(sync_rtc_seconds_text, 0)
            
            # Kalibrační konstanty
            calib_vals = [float(sp.value()) for sp in w["calib"]]
            calib_ts_text = w["calib_ts"].text()
            calib_ts = int(calib_ts_text or "0", 0)
            
        except Exception as exc:
            raise ValueError(f"Invalid form value: {exc}") from exc

        record = EepromRecord(
            format_version=format_version,
            device_type=device_type,
            hw_rev_major=hw_rev_major,
            hw_rev_minor=hw_rev_minor,
            device_id=device_id,
            config_flags=config_flags,
            rtc_flags=rtc_flags,
            init_time=init_time,
            sync_time=sync_time,
            sync_rtc_seconds=sync_rtc_seconds,
            calib=tuple(calib_vals),
            calib_ts=calib_ts,
        )
        payload = pack_record(record, with_crc=True)
        record.crc32 = compute_crc32(payload)
        return record

    def _set_status(self, msg: str) -> None:
        self.status_label.setText(msg)

    @property
    def io_context(self) -> Optional[Any]:
        """Expose the optional device/thread context passed from the caller."""
        return self._io_context

    def set_io_context(self, context: Any) -> None:
        """Update the context later."""
        self._io_context = context


__all__ = ["EepromManagerWidget"]


def _demo():
    """Launch a standalone demo window with in-memory read/write."""
    import sys

    app = QtWidgets.QApplication(sys.argv)

    # Demo data
    import time
    demo_record = EepromRecord(
        format_version=1,
        device_type=DeviceType.AIRDOS04,
        hw_rev_major=2,
        hw_rev_minor=1,
        device_id="AIRDOS001",
        config_flags=0b00000001,
        rtc_flags=0b00000011,
        init_time=int(time.time()) - 86400,    # Před 24 hodinami (kdy RTC=0)
        sync_time=int(time.time()) - 3600,     # Před hodinou (poslední sync)
        sync_rtc_seconds=82800,                # 23 hodin v sekundách (RTC při sync)
        calib=(0.5, 0.125, 0.00001),  # Příklad: offset, lineární, kvadratický
        calib_ts=1702500000,
    )
    mem = {"blob": pack_record(demo_record, with_crc=True)}

    def read_dev():
        return mem["blob"]

    def write_dev(blob: bytes):
        mem["blob"] = blob

    w = EepromManagerWidget(read_device=read_dev, write_device=write_dev)
    w.setWindowTitle("EEPROM Manager")
    w.resize(600, 700)
    w.show()
    
    # Načíst demo data při spuštění
    w._on_load_device()
    
    sys.exit(app.exec_())


if __name__ == "__main__":
    _demo()

