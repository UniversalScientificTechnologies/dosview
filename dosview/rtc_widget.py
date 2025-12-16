"""PyQt5 widget for RTC (Real Time Clock) management.

This widget provides controls for:
- Total Reset (reset RTC to zero and record timestamp in EEPROM)
- Sync Time (record calibration point in EEPROM without changing RTC)
- Update (refresh displayed values)

And displays:
- Current system time
- RTC computed time (based on EEPROM calibration)
- RTC elapsed time (raw counter value)
- Time error (drift)
- EEPROM calibration data (init_time, sync_time, sync_rtc_seconds)
"""
from __future__ import annotations

import datetime
from typing import Any, Callable, Optional

from PyQt5 import QtCore, QtWidgets, QtGui


# Type hints for callbacks
RTCReader = Callable[[], "RTCTime"]
RTCResetter = Callable[[], datetime.datetime]
RTCSyncer = Callable[[], datetime.datetime]


class RTCTime:
    """Placeholder for RTCTime dataclass from airdos04.py"""
    def __init__(
        self,
        absolute_time: datetime.datetime = None,
        elapsed: datetime.timedelta = None,
        start_time: datetime.datetime = None,
        raw_registers: tuple = None
    ):
        self.absolute_time = absolute_time or datetime.datetime.now(datetime.timezone.utc)
        self.elapsed = elapsed or datetime.timedelta()
        self.start_time = start_time or datetime.datetime.now(datetime.timezone.utc)
        self.raw_registers = raw_registers or ()


class RTCManagerWidget(QtWidgets.QWidget):
    """Widget pro správu RTC obvodu."""
    
    # Signály pro notifikaci o změnách
    rtc_reset = QtCore.pyqtSignal()
    rtc_synced = QtCore.pyqtSignal()
    
    def __init__(
        self,
        parent: Optional[QtWidgets.QWidget] = None,
        read_rtc: Optional[RTCReader] = None,
        reset_rtc: Optional[RTCResetter] = None,
        sync_rtc: Optional[RTCSyncer] = None,
    ) -> None:
        super().__init__(parent)
        self._read_rtc = read_rtc
        self._reset_rtc = reset_rtc
        self._sync_rtc = sync_rtc
        
        # Stav
        self._last_reset_time: Optional[datetime.datetime] = None
        self._last_sync_time: Optional[datetime.datetime] = None
        self._last_rtc_data: Optional[RTCTime] = None
        
        self._build_ui()
        
        # Auto-update timer
        self._timer = QtCore.QTimer(self)
        self._timer.timeout.connect(self._on_update)
        self._timer.start(1000)  # Update každou sekundu
    
    def _build_ui(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)
        
        # === Buttons ===
        buttons_group = QtWidgets.QGroupBox("Controls")
        buttons_layout = QtWidgets.QHBoxLayout(buttons_group)
        
        self.btn_update = QtWidgets.QPushButton("🔄 Update")
        self.btn_update.setToolTip("Refresh displayed values")
        
        self.btn_sync = QtWidgets.QPushButton("🔄 Sync Time")
        self.btn_sync.setToolTip("Record calibration point to EEPROM (does not change RTC counter)")
        
        self.btn_reset = QtWidgets.QPushButton("⚠️ Total Reset")
        self.btn_reset.setToolTip("Reset RTC counter to zero and write timestamp to EEPROM")
        self.btn_reset.setStyleSheet("background-color: #ffcccc;")
        
        buttons_layout.addWidget(self.btn_update)
        buttons_layout.addWidget(self.btn_sync)
        buttons_layout.addWidget(self.btn_reset)
        buttons_layout.addStretch(1)
        
        layout.addWidget(buttons_group)
        
        # === Current state ===
        times_group = QtWidgets.QGroupBox("Current State")
        times_layout = QtWidgets.QFormLayout(times_group)
        times_layout.setLabelAlignment(QtCore.Qt.AlignRight)
        
        # System time
        self.lbl_system_time = self._make_time_label()
        times_layout.addRow("System time (UTC):", self.lbl_system_time)
        
        # RTC time (computed from EEPROM calibration)
        self.lbl_rtc_time = self._make_time_label()
        times_layout.addRow("RTC time (calibrated):", self.lbl_rtc_time)
        
        # Elapsed time - raw counter value
        self.lbl_elapsed = self._make_time_label()
        times_layout.addRow("RTC counter (raw):", self.lbl_elapsed)
        
        # Error (drift)
        self.lbl_error = self._make_time_label()
        times_layout.addRow("Drift (error):", self.lbl_error)
        
        layout.addWidget(times_group)
        
        # === EEPROM calibration ===
        history_group = QtWidgets.QGroupBox("EEPROM Calibration")
        history_layout = QtWidgets.QFormLayout(history_group)
        history_layout.setLabelAlignment(QtCore.Qt.AlignRight)
        
        # Init time (when RTC was reset - from Total Reset)
        self.lbl_init_time = self._make_time_label()
        history_layout.addRow("Init time (reset time):", self.lbl_init_time)
        
        # Sync time (computed time when RTC=0 at last Sync)
        self.lbl_sync_time = self._make_time_label()
        history_layout.addRow("Sync time (RTC=0):", self.lbl_sync_time)
        
        # RTC value at sync
        self.lbl_sync_rtc_seconds = self._make_time_label()
        history_layout.addRow("RTC at sync:", self.lbl_sync_rtc_seconds)
        
        # Time since last sync (computed)
        self.lbl_since_sync = self._make_time_label()
        history_layout.addRow("Since last sync:", self.lbl_since_sync)
        
        layout.addWidget(history_group)
        
        # === Raw registry ===
        self.raw_group = QtWidgets.QGroupBox("Raw RTC registry")
        raw_layout = QtWidgets.QVBoxLayout(self.raw_group)
        self.lbl_raw = QtWidgets.QLabel("—")
        self.lbl_raw.setFont(QtGui.QFont("monospace"))
        raw_layout.addWidget(self.lbl_raw)
        self.raw_group.setVisible(False)  # Skrytý ve výchozím stavu
        layout.addWidget(self.raw_group)
        
        # === Status ===
        self.status_label = QtWidgets.QLabel("Ready")
        self.status_label.setStyleSheet("padding: 5px; background: #f0f0f0; border-radius: 3px;")
        layout.addWidget(self.status_label)
        
        layout.addStretch(1)
        
        # Připojení signálů
        self.btn_update.clicked.connect(self._on_update)
        self.btn_sync.clicked.connect(self._on_sync)
        self.btn_reset.clicked.connect(self._on_reset_confirm)
    
    def _make_time_label(self) -> QtWidgets.QLabel:
        """Vytvoří label pro zobrazení času."""
        label = QtWidgets.QLabel("—")
        label.setFont(QtGui.QFont("monospace", 10))
        label.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        return label
    
    def _format_datetime(self, dt: Optional[datetime.datetime]) -> str:
        """Formátuje datetime pro zobrazení."""
        if dt is None:
            return "—"
        return dt.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    
    def _format_timedelta(self, td: Optional[datetime.timedelta]) -> str:
        """Formátuje timedelta pro zobrazení."""
        if td is None:
            return "—"
        
        total_seconds = td.total_seconds()
        sign = "-" if total_seconds < 0 else ""
        total_seconds = abs(total_seconds)
        
        days = int(total_seconds // 86400)
        hours = int((total_seconds % 86400) // 3600)
        minutes = int((total_seconds % 3600) // 60)
        seconds = total_seconds % 60
        
        if days > 0:
            return f"{sign}{days}d {hours:02d}h {minutes:02d}m {seconds:06.3f}s"
        elif hours > 0:
            return f"{sign}{hours}h {minutes:02d}m {seconds:06.3f}s"
        elif minutes > 0:
            return f"{sign}{minutes}m {seconds:06.3f}s"
        else:
            return f"{sign}{seconds:.3f}s"
    
    def _on_update(self) -> None:
        """Aktualizuje zobrazené hodnoty."""
        now = datetime.datetime.now(datetime.timezone.utc)
        self.lbl_system_time.setText(self._format_datetime(now))
        
        if self._read_rtc:
            try:
                rtc_data = self._read_rtc()
                self._last_rtc_data = rtc_data
                
                # RTC čas (start_time + elapsed = absolute_time)
                self.lbl_rtc_time.setText(self._format_datetime(rtc_data.absolute_time))
                
                # Uplynulý čas
                self.lbl_elapsed.setText(self._format_timedelta(rtc_data.elapsed))
                
                # Chyba = systémový čas - RTC čas
                error = now - rtc_data.absolute_time
                error_secs = error.total_seconds()
                elapsed_secs = rtc_data.elapsed.total_seconds()
                
                # Výpočet PPM a zobrazení chyby + PPM na jednom řádku
                error_str = self._format_timedelta(error)
                if elapsed_secs > 60:  # Minimálně 1 minuta pro smysluplný výpočet PPM
                    ppm = (error_secs / elapsed_secs) * 1_000_000
                    self.lbl_error.setText(f"{error_str}  ({ppm:+.1f} ppm)")
                else:
                    self.lbl_error.setText(error_str)
                
                # Zbarvení chyby podle velikosti
                error_secs_abs = abs(error_secs)
                if error_secs_abs < 1:
                    self.lbl_error.setStyleSheet("color: green;")
                elif error_secs_abs < 60:
                    self.lbl_error.setStyleSheet("color: orange;")
                else:
                    self.lbl_error.setStyleSheet("color: red;")
                
                # Raw registry
                if rtc_data.raw_registers:
                    raw_hex = " ".join(f"{r:02X}" for r in rtc_data.raw_registers)
                    self.lbl_raw.setText(raw_hex)
                
                # === EEPROM kalibrace ===
                # Init time - čas kdy bylo RTC resetováno na 0
                if hasattr(rtc_data, 'init_time') and rtc_data.init_time > 0:
                    init_dt = datetime.datetime.fromtimestamp(rtc_data.init_time, tz=datetime.timezone.utc)
                    self.lbl_init_time.setText(self._format_datetime(init_dt))
                else:
                    self.lbl_init_time.setText("— (not in EEPROM)")
                
                # Sync time - vypočtený čas kdy RTC = 0 (referenční bod pro kalibraci)
                if hasattr(rtc_data, 'sync_time') and rtc_data.sync_time > 0:
                    sync_dt = datetime.datetime.fromtimestamp(rtc_data.sync_time, tz=datetime.timezone.utc)
                    self.lbl_sync_time.setText(self._format_datetime(sync_dt))
                    
                    # Vypočteme reálný čas synchronizace: sync_time + sync_rtc_seconds
                    if hasattr(rtc_data, 'sync_rtc_seconds') and rtc_data.sync_rtc_seconds > 0:
                        actual_sync_timestamp = rtc_data.sync_time + rtc_data.sync_rtc_seconds
                        actual_sync_dt = datetime.datetime.fromtimestamp(actual_sync_timestamp, tz=datetime.timezone.utc)
                        self._last_sync_time = actual_sync_dt
                        
                        # Time since actual synchronization
                        since_sync = now - actual_sync_dt
                        self.lbl_since_sync.setText(self._format_timedelta(since_sync))
                    else:
                        # Don't have sync_rtc_seconds, so we don't know when sync was done
                        self.lbl_since_sync.setText("— (missing sync_rtc_seconds)")
                else:
                    self.lbl_sync_time.setText("— (not in EEPROM)")
                    self.lbl_since_sync.setText("—")
                
                # RTC value at sync
                if hasattr(rtc_data, 'sync_rtc_seconds') and rtc_data.sync_rtc_seconds > 0:
                    rtc_val_td = datetime.timedelta(seconds=rtc_data.sync_rtc_seconds)
                    self.lbl_sync_rtc_seconds.setText(self._format_timedelta(rtc_val_td))
                else:
                    self.lbl_sync_rtc_seconds.setText("— (not in EEPROM)")
                
            except Exception as e:
                self._set_status(f"❌ RTC read error: {e}")
    
    def _on_sync(self) -> None:
        """Synchronizes RTC with system time."""
        if not self._sync_rtc:
            self._set_status("❌ Sync function not connected")
            return
        
        try:
            self._last_sync_time = self._sync_rtc()
            self._set_status("✅ RTC synchronized")
            self.rtc_synced.emit()
            self._on_update()
        except Exception as e:
            self._set_status(f"❌ Sync error: {e}")
    
    def _on_reset_confirm(self) -> None:
        """Shows confirmation dialog for reset."""
        dialog = QtWidgets.QMessageBox(self)
        dialog.setIcon(QtWidgets.QMessageBox.Warning)
        dialog.setWindowTitle("Confirm RTC Reset")
        dialog.setText("Do you really want to reset RTC counter to zero?")
        dialog.setInformativeText(
            "This action will reset the time counter in the detector.\n"
            "All measurements will have a new time offset from this moment."
        )
        dialog.setStandardButtons(
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.Cancel
        )
        dialog.setDefaultButton(QtWidgets.QMessageBox.Cancel)
        
        # Přidání druhého potvrzení
        result = dialog.exec_()
        
        if result == QtWidgets.QMessageBox.Yes:
            # Druhé potvrzení
            confirm = QtWidgets.QMessageBox.question(
                self,
                "Finální potvrzení",
                "OPRAVDU resetovat RTC?\n\nTato akce je nevratná!",
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
                QtWidgets.QMessageBox.No
            )
            
            if confirm == QtWidgets.QMessageBox.Yes:
                self._on_reset()
    
    def _on_reset(self) -> None:
        """Provede reset RTC."""
        if not self._reset_rtc:
            self._set_status("❌ Není připojena funkce resetu")
            return
        
        try:
            self._last_reset_time = self._reset_rtc()
            self._last_sync_time = self._last_reset_time  # Reset je také sync
            self._set_status("✅ RTC resetováno na nulu")
            self.rtc_reset.emit()
            self._on_update()
        except Exception as e:
            self._set_status(f"❌ Chyba resetu: {e}")
    
    def _set_status(self, msg: str) -> None:
        """Nastaví status zprávu."""
        self.status_label.setText(msg)
    
    def set_callbacks(
        self,
        read_rtc: Optional[RTCReader] = None,
        reset_rtc: Optional[RTCResetter] = None,
        sync_rtc: Optional[RTCSyncer] = None,
    ) -> None:
        """Nastaví callback funkce pro komunikaci s hardware."""
        if read_rtc:
            self._read_rtc = read_rtc
        if reset_rtc:
            self._reset_rtc = reset_rtc
        if sync_rtc:
            self._sync_rtc = sync_rtc
    
    def show_raw_registers(self, show: bool = True) -> None:
        """Zobrazí/skryje raw RTC registry."""
        self.raw_group.setVisible(show)
    
    def stop_auto_update(self) -> None:
        """Zastaví automatický update."""
        self._timer.stop()
    
    def start_auto_update(self, interval_ms: int = 1000) -> None:
        """Spustí automatický update."""
        self._timer.setInterval(interval_ms)
        self._timer.start()


__all__ = ["RTCManagerWidget"]
