import sys
import argparse

from PyQt5 import QtNetwork
from PyQt5.QtNetwork import QLocalSocket, QLocalServer
from PyQt5.QtCore import QThread, pyqtSignal, QSettings
from PyQt5.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget, QHBoxLayout, QFormLayout
from PyQt5.QtWidgets import QPushButton, QFileDialog, QTreeWidget, QTreeWidgetItem, QAction, QSplitter, QTableWidgetItem
from PyQt5.QtGui import QIcon

import pyqtgraph as pg

import pandas as pd

import datetime
import time

from PyQt5.QtCore import *
from PyQt5.QtGui import *
from PyQt5.QtWidgets import *

import hid
import numpy as np
import os

from .version import __version__
from pyqtgraph import ImageView

from .parsers import (
    BaseLogParser,
    Airdos04CLogParser,
    OldLogParser,
    get_parser_for_file,
    parse_file,
)
from .eeprom_widget import EepromManagerWidget
from .rtc_widget import RTCManagerWidget
from .airdos04 import Airdos04Hardware, Airdos04Addresses
from .loading_dialog import LoadingDialog, LoadingContext


class LoadDataThread(QThread):
    data_loaded = pyqtSignal(list)

    def __init__(self, file_path):
        QThread.__init__(self)
        self.file_path = file_path

    def run(self):
        data = parse_file(self.file_path)
        self.data_loaded.emit(data)



class PlotCanvas(pg.GraphicsLayoutWidget):
    def __init__(self, parent=None, file_path=None):
        super().__init__(parent)
        self.data = []
        self.file_path = file_path
        self.telemetry_lines = {'temperature_0': None, 'humidity_0': None, 'temperature_1': None, 'humidity_1': None, 'temperature_2': None, 'pressure_3': None, 
                                'voltage': None, 'current': None, 'capacity_remaining': None, 'capacity_full': None, 'temperature': None}

    def plot(self, data):
        start_time = time.time()

        self.data = data
        window_size = 20

        self.clear()

        plot_evolution = self.addPlot(row=0, col=0)
        plot_spectrum = self.addPlot(row=1, col=0)


        plot_evolution.showGrid(x=True, y=True)
        plot_evolution.setLabel("left",  "Total count per exposition", units="#")
        plot_evolution.setLabel("bottom","Time", units="min")

        time_axis = self.data[0]/60
        plot_evolution.plot(time_axis, self.data[1],
                        symbol ='o', symbolPen ='pink', name ='Channel', pen=None)
        

        pen = pg.mkPen(color="r", width=3)
        rolling_avg = np.convolve(self.data[1], np.ones(window_size)/window_size, mode='valid')
        plot_evolution.plot(time_axis[window_size-1:], rolling_avg, pen=pen)

        ev_data = self.data[2]
        plot_spectrum.plot(range(len(ev_data)), ev_data, 
                        pen="r", symbol='x', symbolPen = 'g',
                        symbolBrush = 0.2, name = "Energy")
        plot_spectrum.setLabel("left", "Total count per channel", units="#")
        plot_spectrum.setLabel("bottom", "Channel", units="#")

        # np_metadata = data[4]
        
        # print("METADATA")
        # print(np_metadata[:,0]/60)
        # print(np_metadata[:,6])
        # plot_evolution.plot(np_metadata[:,0]/60, np_metadata[:,6], pen="b", symbol='p', symbolPen='b', symbolBrush=0.1, name="Pressure")


        plot_spectrum.setLogMode(x=True, y=True)
        plot_spectrum.showGrid(x=True, y=True)

        print("PLOT DURATION ... ", time.time()-start_time)

    def telemetry_toggle(self, key, value):
        if self.telemetry_lines[key] is not None:
            self.telemetry_lines[key].setVisible(value)

import ft260
FT260HidDriver = ft260.FT260_I2C
# Enable verbose FT260 HID/I2C debugging
try:
    ft260.set_debug(True)
except Exception as _e:
    print(f"[dosview] Warning: could not enable ft260 debug: {_e}")


class AIRDOS04CTRL(QThread):
    """
    Qt thread pro komunikaci s AIRDOS04 detektorem přes HID/I2C.
    
    Hardware operace jsou delegovány na Airdos04Hardware třídu.
    Tento thread se stará o:
    - HID připojení/odpojení
    - Qt signály pro GUI
    - Thread-safe volání hardware operací
    """
    connected = pyqtSignal(bool)
    connect = pyqtSignal(bool)
    sendAirdosStatus = pyqtSignal(dict)
    sendEepromData = pyqtSignal(dict)  # Signál pro EEPROM data
    loadingStateChanged = pyqtSignal(bool, str)  # (is_loading, message)

    # USB HID identifikace
    VID = 0x1209    
    PID = 0x7aa0

    basic_params = {}

    dev = None
    ftdi = None
    hw = None  # Airdos04Hardware instance

    def __init__(self):
        QThread.__init__(self)
        self.hw = None  # Will be set on connect
        self.dev_uart = None

    def run(self):
        # Main thread loop
        self.connected.emit(False)
        while True:
            pass

    @pyqtSlot()
    def connectSlot(self, state=True, power_off=False):
        print("Connecting to HID device... ", state)
        if state:
            self.loadingStateChanged.emit(True, "Connecting to device...")

            hid_interface_i2c = None
            hid_interface_uart = None

            for hidDevice in hid.enumerate(0, 0):
                print(hidDevice)
                if hidDevice['vendor_id'] == self.VID and hidDevice['product_id'] == self.PID:
                    if hidDevice['interface_number'] == 0:
                        hid_interface_i2c = hidDevice
                    else:
                        hid_interface_uart = hidDevice
            
            self.dev = hid.device()
            #self.dev.open(self.VID, self.PID)
            self.dev.open_path(hid_interface_i2c['path'])

            self.dev_uart = hid.device()
            self.dev_uart.open_path(hid_interface_uart['path'])
            print("Connected to HID device", self.dev, self.dev_uart)

            self.loadingStateChanged.emit(True, "Initializing device...")
            
            self.dev.send_feature_report([0xA1, 0x20])
            self.dev.send_feature_report([0xA1, 0x02, 0x01])

            # Bind the already-open HID interface to the FT260_I2C driver
            self.ftdi = FT260HidDriver(hid_device=self.dev)

            # Inicializace Airdos04Hardware - Qt-nezávislé rozhraní pro hardware
            self.hw = Airdos04Hardware(self.ftdi)

            # Přepnout I2C switch na I2C z USB
            self.hw.set_i2c_direction(to_usb=True)

            # Povolit nabíjení
            self.hw.enable_charging()

            self.loadingStateChanged.emit(True, "Reading serial numbers...")
            
            # Vyčíst sériová čísla pomocí hw modulu
            print("AIRDOS SN ... ")
            try:
                self.basic_params['sn_batdatunit'] = self.hw.read_serial_number_batdatunit()
                print(self.basic_params['sn_batdatunit'])
            except Exception as e:
                print(f"Error reading BatDatUnit SN: {e}")
                self.basic_params['sn_batdatunit'] = "N/A"

            try:
                self.basic_params['sn_ustsipin'] = self.hw.read_serial_number_ustsipin()
                print(self.basic_params['sn_ustsipin'])
            except Exception as e:
                print(f"Error reading USTSIPIN SN: {e}")
                self.basic_params['sn_ustsipin'] = "N/A"

            self.hw.set_i2c_direction(to_usb=False)


            self.connected.emit(True)
            
            # Automaticky načíst data ze senzorů a EEPROM
            self.get_all_data()
        
        else:
            # Odpojení
            if self.hw is not None:
                self.hw.set_i2c_direction(to_usb=True)
                
                # Vypnout nabíječku pokud je požadováno
                if power_off:
                    self.hw.disable_charging_and_poweroff()
                
                self.hw.set_i2c_direction(to_usb=False)
            
            if self.dev is not None:
                self.dev.close()
            if hasattr(self, 'dev_uart') and self.dev_uart is not None:
                self.dev_uart.close()
            
            self.dev = None
            self.dev_uart = None
            self.ftdi = None
            self.hw = None
            self.connected.emit(False)

    @pyqtSlot()
    def get_airdos_status(self):
        """Vyčte kompletní stav AIRDOS04 a emituje signál s daty."""
        if self.hw is None:
            print("[I2C] Not connected; skipping status read")
            return
        
        self.hw.set_i2c_direction(to_usb=True)
        
        try:
            # Použijeme Airdos04Hardware.to_dict() pro kompatibilitu s původním API
            data = self.hw.to_dict()
            # Přidáme základní parametry (SN načtené při připojení)
            data.update(self.basic_params)
        except Exception as e:
            print(f"[I2C] Error reading status: {e}")
            data = self.basic_params.copy()
        finally:
            self.hw.set_i2c_direction(to_usb=False)
        
        print("Posilam...", type(data))
        print(data)
        self.sendAirdosStatus.emit(data)


    @pyqtSlot()
    def reset_rtc_time(self):
        """Resetuje RTC stopky na nulu."""
        if self.hw is None:
            print("[I2C] Not connected; skipping RTC reset")
            return
        
        self.hw.set_i2c_direction(to_usb=True)
        try:
            reset_time = self.hw.reset_rtc()
            print(f"Time reset at: {reset_time}")
        finally:
            self.hw.set_i2c_direction(to_usb=False)

    @pyqtSlot()
    def get_all_data(self):
        """Načte všechna data - senzory i EEPROM."""
        self.loadingStateChanged.emit(True, "Načítání senzorů...")
        self.get_airdos_status()
        
        self.loadingStateChanged.emit(True, "Načítání EEPROM...")
        self.get_eeprom_data()
        
        self.loadingStateChanged.emit(False, "")

    @pyqtSlot()
    def get_eeprom_data(self):
        """Vyčte EEPROM data z detektoru a baterie a emituje signál."""
        if self.hw is None:
            print("[I2C] Not connected; skipping EEPROM read")
            return
        
        from .eeprom_schema import unpack_record, TOTAL_SIZE
        
        eeprom_data = {}
        self.hw.set_i2c_direction(to_usb=True)
        
        try:
            # EEPROM detektor
            try:
                det_data = self.hw.read_eeprom(TOTAL_SIZE, start_address=0, eeprom_address=self.hw.addr.eeprom)
                det_record = unpack_record(det_data, verify_crc=False)
                eeprom_data['detector'] = det_record.to_dict()
            except Exception as e:
                print(f"[EEPROM] Error reading detector EEPROM: {e}")
                eeprom_data['detector'] = {'error': str(e)}
            
            # EEPROM baterie
            try:
                bat_data = self.hw.read_eeprom(TOTAL_SIZE, start_address=0, eeprom_address=self.hw.addr.eeprom_bat)
                bat_record = unpack_record(bat_data, verify_crc=False)
                eeprom_data['battery'] = bat_record.to_dict()
            except Exception as e:
                print(f"[EEPROM] Error reading battery EEPROM: {e}")
                eeprom_data['battery'] = {'error': str(e)}
                
        finally:
            self.hw.set_i2c_direction(to_usb=False)
        
        self.sendEepromData.emit(eeprom_data)

class HIDUARTCommunicationThread(QThread):
    connected = pyqtSignal(bool)

    def __init__(self):
        QThread.__init__(self)
        # Initialize HID communication here
    
    def run(self):
        pass
        # Implement HID communication logic here


class USBStorageMonitoringThread(QThread):
    connected = pyqtSignal(bool)

    def __init__(self):
        QThread.__init__(self)
        # Initialize USB storage monitoring here
    
    def run(self):
        pass
        # Implement USB storage monitoring logic here



class LabdosConfigTab(QWidget):
    def __init__(self):
        super().__init__()
        
        self.initUI()
    
    def initUI(self):
        # Create a QTabWidget
        tab_widget = QTabWidget()
        tab_widget.setTabPosition(QTabWidget.West)  # Set the tab position to vertical

        # Create the first tab - Realtime Data
        realtime_tab = QWidget()
        realtime_layout = QVBoxLayout()

        firmware_tab = QWidget()
        firmware_layout = QVBoxLayout()

        # Add the tabs to the tab_widget
        tab_widget.addTab(realtime_tab, "Realtime Data")
        tab_widget.addTab(firmware_tab, "Firmware")

        # Create a main layout for the LabdosConfigTab
        main_layout = QVBoxLayout()
        main_layout.addWidget(tab_widget)

        # Set the main layout for the LabdosConfigTab
        self.setLayout(main_layout)



class AirdosConfigTab(QWidget):
    def __init__(self):
        super().__init__()

        self.i2c_thread = AIRDOS04CTRL()
        self.i2c_thread.connected.connect(self.on_i2c_connected)  
        self.i2c_thread.sendAirdosStatus.connect(self.on_airdos_status)
        self.i2c_thread.sendEepromData.connect(self.on_eeprom_data)
        self.i2c_thread.loadingStateChanged.connect(self.on_loading_state)
        self.i2c_thread.start()

        #self.uart_thread = HIDUARTCommunicationThread().start()
        #self.mass_thread = USBStorageMonitoringThread().start()

        return self.initUI()
    
    def on_i2c_connected(self, connected: bool = True):
        self.i2c_connect_button.setEnabled(not connected)
        self.i2c_disconnect_button.setEnabled(connected)
        self.i2c_power_off_button.setEnabled(connected)

    def on_i2c_connect(self):
        pass

    def on_i2c_disconnect(self):
        pass

    def on_uart_connect(self):
        pass

    def on_uart_disconnect(self):

        pass
    
    def on_mass_connect(self):
        pass
    
    def on_mass_disconnect(self):
        pass

    def on_airdos_status(self, status):
        print("AIRDOS STATUS:")
        print(status)

        self._update_tree_with_data(self.i2c_parameters_tree, status)

    def on_eeprom_data(self, eeprom_data):
        """Handler pro EEPROM data."""
        print("EEPROM DATA:")
        print(eeprom_data)
        
        self._update_tree_with_data(self.eeprom_tree, eeprom_data)

    def on_loading_state(self, is_loading: bool, message: str):
        """Handler pro změnu stavu načítání."""
        if is_loading:
            # Zobrazit loading dialog
            if not hasattr(self, '_loading_dialog') or self._loading_dialog is None:
                self._loading_dialog = LoadingDialog(self, "Loading", message)
                self._loading_dialog.start()
            else:
                self._loading_dialog.set_message(message)
                if not self._loading_dialog.isVisible():
                    self._loading_dialog.start()
        else:
            # Skrýt loading dialog
            if hasattr(self, '_loading_dialog') and self._loading_dialog is not None:
                self._loading_dialog.stop()
                self._loading_dialog = None

    def _update_tree_with_data(self, tree: QTreeWidget, data: dict):
        """Aktualizuje tree widget s daty."""
        tree.clear()

        def add_properties_to_tree(item, properties):
            for key, value in properties.items():
                if isinstance(value, dict):
                    parent_item = QTreeWidgetItem([key])
                    item.addChild(parent_item)
                    add_properties_to_tree(parent_item, value)
                elif isinstance(value, (list, tuple)):
                    parent_item = QTreeWidgetItem([key, f"[{len(value)} items]"])
                    item.addChild(parent_item)
                    for i, v in enumerate(value):
                        if isinstance(v, dict):
                            child = QTreeWidgetItem([f"[{i}]"])
                            parent_item.addChild(child)
                            add_properties_to_tree(child, v)
                        else:
                            child = QTreeWidgetItem([f"[{i}]", str(v)])
                            parent_item.addChild(child)
                else:
                    child_item = QTreeWidgetItem([key, str(value)])
                    item.addChild(child_item)

        for key, value in data.items():
            if isinstance(value, dict):
                parent_item = QTreeWidgetItem([key])
                tree.addTopLevelItem(parent_item)
                add_properties_to_tree(parent_item, value)
            elif isinstance(value, (list, tuple)):
                parent_item = QTreeWidgetItem([key, f"[{len(value)} items]"])
                tree.addTopLevelItem(parent_item)
                for i, v in enumerate(value):
                    if isinstance(v, dict):
                        child = QTreeWidgetItem([f"[{i}]"])
                        parent_item.addChild(child)
                        add_properties_to_tree(child, v)
                    else:
                        child = QTreeWidgetItem([f"[{i}]", str(v)])
                        parent_item.addChild(child)
            else:
                tree.addTopLevelItem(QTreeWidgetItem([key, str(value)]))
        tree.expandAll()


    def initUI(self):
        splitter = QSplitter(Qt.Horizontal)
        
        i2c_widget = QGroupBox("I2C")
        i2c_layout = QVBoxLayout()        
        i2c_layout.setAlignment(Qt.AlignTop)
        i2c_widget.setLayout(i2c_layout)

        i2c_layout_row_1 = QHBoxLayout()

        self.i2c_connect_button = QPushButton("Connect")
        self.i2c_disconnect_button = QPushButton("Disconnect")
        self.i2c_disconnect_button.disabled = True
        self.i2c_connect_button.clicked.connect(lambda: self.i2c_thread.connectSlot(True))
        self.i2c_disconnect_button.clicked.connect(lambda: self.i2c_thread.connectSlot(False)) 
        
        self.i2c_power_off_button = QPushButton("Power off and Disconnect")
        self.i2c_power_off_button.clicked.connect(lambda: self.i2c_thread.connectSlot(False, True))
        self.i2c_power_off_button.disabled = True
        
        i2c_layout_row_1.addWidget(self.i2c_connect_button)
        i2c_layout_row_1.addWidget(self.i2c_disconnect_button)
        i2c_layout_row_1.addWidget(self.i2c_power_off_button)
        i2c_layout.addLayout(i2c_layout_row_1)

        # Senzory tree
        sensors_label = QLabel("📊 Senzory")
        sensors_label.setStyleSheet("font-weight: bold; margin-top: 5px;")
        i2c_layout.addWidget(sensors_label)
        
        self.i2c_parameters_tree = QTreeWidget()
        self.i2c_parameters_tree.setHeaderLabels(["Parameter", "Value"])
        i2c_layout.addWidget(self.i2c_parameters_tree)

        # EEPROM tree
        eeprom_label = QLabel("💾 EEPROM")
        eeprom_label.setStyleSheet("font-weight: bold; margin-top: 5px;")
        i2c_layout.addWidget(eeprom_label)
        
        self.eeprom_tree = QTreeWidget()
        self.eeprom_tree.setHeaderLabels(["Parameter", "Value"])
        i2c_layout.addWidget(self.eeprom_tree)

        # Řádek s akčními tlačítky
        i2c_actions_row = QHBoxLayout()
        
        reload_button = QPushButton("🔄 Reload All")
        reload_button.clicked.connect(self.i2c_thread.get_all_data)
        i2c_actions_row.addWidget(reload_button)

        rtc_button = QPushButton("⏱️ RTC Manager")
        rtc_button.clicked.connect(self.open_rtc_manager)
        i2c_actions_row.addWidget(rtc_button)
        
        i2c_layout.addLayout(i2c_actions_row)

        # Řádek s EEPROM manager tlačítky
        i2c_eeprom_row = QHBoxLayout()
        
        eeprom_det_btn = QPushButton("📀 EEPROM (detector)")
        eeprom_bat_btn = QPushButton("🔋 EEPROM (battery)")
        eeprom_det_btn.clicked.connect(self.open_eeprom_manager_detector)
        eeprom_bat_btn.clicked.connect(self.open_eeprom_manager_battery)
        i2c_eeprom_row.addWidget(eeprom_det_btn)
        i2c_eeprom_row.addWidget(eeprom_bat_btn)
        
        i2c_layout.addLayout(i2c_eeprom_row)

        uart_widget = QGroupBox("UART")
        uart_layout = QVBoxLayout()
        uart_layout.setAlignment(Qt.AlignTop)
        uart_widget.setLayout(uart_layout)

        uart_connect_button = QPushButton("Connect")
        uart_disconnect_button = QPushButton("Disconnect")
        uart_layout.addWidget(uart_connect_button)
        uart_layout.addWidget(uart_disconnect_button)
        
        splitter.addWidget(i2c_widget)
        splitter.addWidget(uart_widget)
        
        layout = QVBoxLayout()
        layout.addWidget(splitter)
        self.setLayout(layout)

    def _open_eeprom_manager(self, read_addr: int):
        def _log_eeprom(kind, message, data=None, *, full=False):
            colors = {"read": "\x1b[32m", "write": "\x1b[33m", "info": "\x1b[36m"}
            prefix = f"[EEPROM][{kind.upper()}]"
            color = colors.get(kind, "")
            reset = "\x1b[0m" if color else ""
            print(f"{color}{prefix} {message}{reset}")
            if data:
                if full or len(data) <= 64:
                    preview = " ".join(f"{b:02X}" for b in data)
                    ellipsis = ""
                else:
                    preview = " ".join(f"{b:02X}" for b in data[:32])
                    ellipsis = " ..."
                print(f"{color}{prefix} DATA={preview}{ellipsis}{reset}")

        if not self.i2c_thread or not self.i2c_thread.hw:
            # Graceful fallback: demo mode without device
            def read_device() -> bytes:
                # Return empty 101-byte block (unprogrammed EEPROM = 0xFF)
                _log_eeprom("info", "I2C není připojeno; spouštím demo mode")
                _log_eeprom("read", "Demo mode: returning synthetic 0xFF block", data=b'\xFF' * 16)
                return b'\xFF' * 101
            def write_device(blob: bytes) -> None:
                _log_eeprom(
                    "write", f"Demo mode: would write {len(blob)} bytes", data=bytes(blob[:16])
                )
        else:
            hw = self.i2c_thread.hw
            
            def read_device() -> bytes:
                try:
                    hw.set_i2c_direction(to_usb=True)
                    _log_eeprom("read", f"Reading 101 bytes from EEPROM addr=0x{read_addr:02X}")
                    
                    # Debug: vyčíst SN
                    try:
                        sn = hw.read_serial_number(hw.addr.eeprom_sn)
                        print(f"EEPROM SN: {hex(sn)}")
                    except Exception as e:
                        print(f"Warning: Could not read EEPROM SN: {e}")
                    
                    # Vyčíst data z EEPROM pomocí Airdos04Hardware
                    data = hw.read_eeprom(101, start_address=0, eeprom_address=read_addr)
                    _log_eeprom(
                        "read",
                        f"Total read {len(data)} bytes; sample={list(data[:8])}",
                        data=bytes(data[:16]),
                    )
                    _log_eeprom("read", "Read sequence (all bytes)", data=bytes(data), full=True)
                    return data
                finally:
                    hw.set_i2c_direction(to_usb=False)

            def write_device(blob: bytes) -> None:
                try:
                    hw.set_i2c_direction(to_usb=True)
                    _log_eeprom("write", f"Writing {len(blob)} bytes to addr=0x{read_addr:02X}", data=bytes(blob[:16]))
                    _log_eeprom("write", "Write sequence (all bytes)", data=bytes(blob), full=True)
                    
                    success = hw.write_eeprom(blob, start_address=0, eeprom_address=read_addr)
                    if success:
                        _log_eeprom("write", "Write completed successfully")
                    else:
                        _log_eeprom("write", "Write failed!")
                finally:
                    hw.set_i2c_direction(to_usb=False)

        dlg = QDialog(self)
        dlg.setWindowTitle(f"EEPROM Manager (addr=0x{read_addr:02X})")
        v = QVBoxLayout(dlg)

        w = EepromManagerWidget(
            read_device=read_device,
            write_device=write_device,
            io_context=self.i2c_thread,
        )
        v.addWidget(w)
        btn_close = QPushButton("Zavřít")
        btn_close.clicked.connect(dlg.accept)
        v.addWidget(btn_close)
        dlg.resize(900, 600)
        dlg.exec_()

    def open_eeprom_manager_detector(self):
        """Otevře EEPROM manager pro analogovou desku (USTSIPIN)."""
        if self.i2c_thread.hw:
            self._open_eeprom_manager(self.i2c_thread.hw.addr.an_eeprom)
        else:
            self._open_eeprom_manager(0x53)  # fallback address

    def open_eeprom_manager_battery(self):
        """Otevře EEPROM manager pro BatDatUnit."""
        if self.i2c_thread.hw:
            self._open_eeprom_manager(self.i2c_thread.hw.addr.eeprom)
        else:
            self._open_eeprom_manager(0x50)  # fallback address

    def open_rtc_manager(self):
        """Otevře RTC manager pro správu hodin detektoru."""
        if not self.i2c_thread or not self.i2c_thread.hw:
            # Demo mode
            QMessageBox.warning(
                self,
                "RTC Manager",
                "I2C není připojeno. Připojte se k detektoru."
            )
            return
        
        hw = self.i2c_thread.hw
        
        def read_rtc():
            try:
                hw.set_i2c_direction(to_usb=True)
                return hw.read_rtc()
            finally:
                hw.set_i2c_direction(to_usb=False)
        
        def reset_rtc():
            try:
                hw.set_i2c_direction(to_usb=True)
                return hw.reset_rtc()
            finally:
                hw.set_i2c_direction(to_usb=False)
        
        def sync_rtc():
            # Zapíše kalibrační bod do EEPROM (sync_time, sync_rtc_seconds)
            try:
                hw.set_i2c_direction(to_usb=True)
                return hw.sync_rtc()
            finally:
                hw.set_i2c_direction(to_usb=False)
        
        dlg = QDialog(self)
        dlg.setWindowTitle("RTC Manager - AIRDOS04")
        v = QVBoxLayout(dlg)
        
        w = RTCManagerWidget(
            read_rtc=read_rtc,
            reset_rtc=reset_rtc,
            sync_rtc=sync_rtc
        )
        w.show_raw_registers(True)
        v.addWidget(w)
        
        btn_close = QPushButton("Zavřít")
        btn_close.clicked.connect(dlg.accept)
        v.addWidget(btn_close)
        
        dlg.resize(550, 550)
        dlg.exec_()


class DataSpectrumView(QWidget):

    def __init__(self,parent):
        self.parent = parent 
        super(DataSpectrumView, self).__init__(parent)
        self.setWindowFlags(self.windowFlags() | Qt.Window)
        self.initUI()

    def initUI(self):

        self.setWindowTitle(repr(self.parent))
        self.setGeometry(100, 100, 400, 300)
        self.imv = pg.ImageView(view=pg.PlotItem())
        layout = QVBoxLayout()
        layout.addWidget(self.imv)
        self.setLayout(layout)

    def plot_data(self, data):
        # Clear the plot widget
        self.imv.clear()

        # Set the image data
        self.imv.setImage(np.where(data == 0, np.nan, data))
        #self.imv.autoLevels()
        #self.imv.autoRange()

        self.imv.show() 

        self.imv.setPredefinedGradient('thermal')
        self.imv.getView().showGrid(True, True, 0.2)

        # Invert the y-axis
        self.imv.getView().invertY(False)
        #self.imv.getView().setLogMode(x=False, y=True)
        
        # Add axis labels
        #self.imv.setLabel('left', 'Y Axis')
        #self.imv.setLabel('bottom', 'X Axis')

class PlotTab(QWidget):
    def __init__(self):
        super().__init__()
        self.initUI()
    
    def initUI(self):
        self.properties_tree = QTreeWidget()
        self.properties_tree.setColumnCount(2)
        self.properties_tree.setHeaderLabels(["Property", "Value"])

        self.datalines_tree = QTreeWidget()
        self.datalines_tree.setColumnCount(1)
        self.datalines_tree.setHeaderLabels(["Units"])


        self.open_img_view_button = QPushButton("Spectrogram")
        self.open_img_view_button.setMaximumHeight(20)
        self.open_img_view_button.clicked.connect(self.open_spectrogram_view)

        self.upload_file_button = QPushButton("Upload file")
        self.upload_file_button.setMaximumHeight(20)
        self.upload_file_button.clicked.connect(lambda: UploadFileDialog().exec_())

        log_view_widget = QWidget()

        self.left_panel = QSplitter(Qt.Vertical)

        self.left_panel.addWidget(self.datalines_tree)
        self.left_panel.addWidget(self.properties_tree)

        vb = QHBoxLayout()
        vb.addWidget(self.open_img_view_button)
        vb.addWidget(self.upload_file_button)
        self.left_panel.setLayout(vb)

        self.logView_splitter = QSplitter(Qt.Horizontal)
        self.logView_splitter.addWidget(self.left_panel)
        #self.logView_splitter.addWidget(QWidget())

        layout = QVBoxLayout()
        layout.addWidget(self.logView_splitter)
        self.setLayout(layout)
    

    def open_file(self, file_path):
        self.file_path = file_path
        self.plot_canvas = PlotCanvas(self, file_path=self.file_path)
        self.logView_splitter.addWidget(self.plot_canvas)

        self.logView_splitter.setSizes([1, 9])
        sizes = self.logView_splitter.sizes()
        sizes[0] = int(sizes[1] * 0.1)
        self.logView_splitter.setSizes(sizes)

        self.start_data_loading()

    def start_data_loading(self):
        self.load_data_thread = LoadDataThread(self.file_path)
        self.load_data_thread.data_loaded.connect(self.on_data_loaded)
        self.load_data_thread.start()

    def on_data_loaded(self, data):
        self.data = data # TODO>.. tohle do budoucna zrusit a nahradit tridou parseru.. 
        print("Data are fully loaded...")
        self.plot_canvas.plot(data)
        print("After plot data canvas")
        
        self.properties_tree.clear()

        def add_properties_to_tree(item, properties):
            for key, value in properties.items():
                # Pokud je to uroven ve storomu
                if isinstance(value, dict):
                    parent_item = QTreeWidgetItem([key])
                    item.addChild(parent_item)
                    add_properties_to_tree(parent_item, value)
                # Zobraz samotne hodnoty
                else:
                    if key in ['internal_time_min', 'internal_time_max', 'log_duration']:
                        value_td = datetime.timedelta(seconds=value)
                        value = f"{value_td}, ({value} seconds)"
                    child_item = QTreeWidgetItem([key, str(value)])
                    item.addChild(child_item)

        metadata = data[3]
        for key, value in metadata.items():
           if isinstance(value, dict):
               parent_item = QTreeWidgetItem([key])
               self.properties_tree.addTopLevelItem(parent_item)
               add_properties_to_tree(parent_item, value)
           else:
               self.properties_tree.addTopLevelItem(QTreeWidgetItem([key, str(value)]))
        
        self.datalines_tree.clear()
        dataline_options = ['temperature_0', 'humidity_0', 'temperature_1', 'humidity_1', 'temperature_2', 'pressure_3', 'voltage', 'current', 'capacity_remaining', 'temperature']
        for option in dataline_options:
           child_item = QTreeWidgetItem([option])
           child_item.setCheckState(0, Qt.Checked)
           self.datalines_tree.addTopLevelItem(child_item)

        self.datalines_tree.itemChanged.connect(lambda item, state: self.plot_canvas.telemetry_toggle(item.text(0), item.checkState(0) == Qt.Checked))
        self.datalines_tree.setMaximumHeight(self.datalines_tree.sizeHintForRow(0) * (self.datalines_tree.topLevelItemCount()+4))

        self.properties_tree.expandAll()


    def open_spectrogram_view(self):
        matrix = self.data[-1] #TODO .. tohle predelat na nejakou tridu pro parserovani 

        w = DataSpectrumView(self)
        w.show()
        w.plot_data(matrix)


class UploadFileDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__()
        self._manager = QtNetwork.QNetworkAccessManager()
        self._manager.finished.connect(self.on_request_finished)
        self.initUI()
    
    def initUI(self):
        self.setWindowTitle("Upload file")
        self.setGeometry(100, 100, 400, 300)
        self.layout = QVBoxLayout()
        self.setLayout(self.layout)

        self.file_path = QLineEdit()
        self.record_name = QLineEdit()
        self.description = QTextEdit()
        self.time_tracked = QCheckBox("Time tracked")
        self.record_metadata = QTextEdit()
        
        upload_button = QPushButton("Upload")
        upload_button.clicked.connect(self.upload_file)

        lay = QFormLayout()
        lay.addRow("File path:", self.file_path)
        lay.addRow("Record name:", self.record_name)
        lay.addRow("Description:", self.description)
        lay.addRow("Time tracked:", self.time_tracked)
        lay.addRow("Record metadata:", self.record_metadata)
        lay.addRow(upload_button)

        self.upload_button = QPushButton("Upload")
        self.upload_button.clicked.connect(self.upload_file)
        self.layout.addLayout(lay)
    
    def upload_file(self):
        file_path = self.file_path.text()
        print("Uploading file", file_path)
        self.accept()
    
    def on_request_finished(self, reply):
        print("Upload finished")
        self.accept()

    @pyqtSlot()
    def upload(self):   
        data = {
            "name": self.record_name.text(),
            "": ""
        }
        path = self.filepath_lineedit.text()
        files = {"image": path}
        multi_part = self.construct_multipart(data, files)
        if multi_part:
            url = Qt.QUrl("http://127.0.0.1:8100/api/record/")
            request = QtNetwork.QNetworkRequest(url)
            reply = self._manager.post(request, multi_part)
            multi_part.setParent(reply)

class PreferencesVindow(QDialog):
    def __init__(self):
        super().__init__()
        self.initUI()
    

    def DosportalTab(self):
        #self.dosportal_tab_group = QGroupBox("DOSPORTAL settings")
        self.dosportal_tab_layout = QVBoxLayout()
        settings = QSettings("UST", "dosview")


        self.url = QLineEdit()
        self.login = QLineEdit()
        self.password = QLineEdit()

        # Load data from QSettings
        url = settings.value("url")
        if url is not None:
            self.url.setText(url)
        login = settings.value("login")
        if login is not None:
            self.login.setText(login)

        password = settings.value("password")
        self.password.setEchoMode(QLineEdit.Password)
        if password is not None:
            self.password.setText(password)

        vb = QHBoxLayout()
        vb.addWidget(QLabel("URL"))
        vb.addWidget(self.url)
        self.dosportal_tab_layout.addLayout(vb)

        vb = QHBoxLayout()
        vb.addWidget(QLabel("Login"))
        vb.addWidget(self.login)
        self.dosportal_tab_layout.addLayout(vb)

        vb = QHBoxLayout()
        vb.addWidget(QLabel("Password"))
        vb.addWidget(self.password)
        self.dosportal_tab_layout.addLayout(vb)


        # Save data to QSettings
        def save_settings():
            settings.setValue("url", self.url.text())
            settings.setValue("login", self.login.text())
            settings.setValue("password", self.password.text())

        # Connect save button to save_settings function
        save_button = QPushButton("Save credentials")
        save_button.clicked.connect(save_settings)

        test_button = QPushButton("Test connection")
        test_button.clicked.connect(lambda: print("Testing connection .... not implemented yet :-) "))

        vb = QHBoxLayout()
        vb.addWidget(save_button)
        vb.addWidget(test_button)

        self.dosportal_tab_layout.addLayout(vb)

        self.dosportal_tab_layout.addStretch(1)
        return self.dosportal_tab_layout
        #self.dosportal_tab_group.setLayout(self.dosportal_tab_layout)
        #return self.dosportal_tab_group
        
    
    def initUI(self):
        
        self.setWindowTitle("DOSVIEW Preferences")
        self.setGeometry(100, 100, 400, 300)
        self.layout = QVBoxLayout()
        self.setLayout(self.layout)

        self.tabs = QTabWidget()
        self.layout.addWidget(self.tabs)

        self.dosportal_tab = QWidget()
        #self.dosportal_tab_layout = QVBoxLayout()
        self.dosportal_tab.setLayout( self.DosportalTab() )

        self.tabs.addTab(self.dosportal_tab, "DOSPORTAL")



        self.tabs.addTab(QWidget(), "Advanced")
        #self.layout.addWidget(QPushButton("Save"))


class App(QMainWindow):
    def __init__(self, args):
        super().__init__()
        self.args = args
        self.left = 100
        self.top = 100
        self.settings = QSettings("UST", "dosview")
        self.title = 'dosview'
        self.width = 640
        self.height = 400
        self.file_path = args.file_path
        self.initUI()


        self.plot_tab = None
        self.airdos_tab = None

        self.solve_startup_args()

    
    def solve_startup_args(self):

        if self.args.file_path:
            print("Oteviram zalozku s logem")
            self.openPlotTab()
        
        if self.args.airdos:
            print("Oteviram zalozku s airdosem")
            self.openAirdosTab()
        
        if self.args.labdos:
            print("Oteviram zalozku s labdosem")
            self.openLabdosTab()

    def updateStackedWidget(self):
        print("Updating stacked widget")
        print(self.tab_widget.count())
        if self.tab_widget.count():
            self.stacked_container.setCurrentIndex(1)
        else:
            self.stacked_container.setCurrentIndex(0)

    def openPlotTab(self, file_path = None):
        plot_tab = PlotTab()
        if not file_path:
            file_path = self.args.file_path
        print("Oteviram log.. ", file_path)
        
        plot_tab.open_file(file_path)
        file_name = os.path.basename(file_path)
        
        self.tab_widget.addTab(plot_tab, f"{file_name}")
        self.tab_widget.setCurrentIndex(self.tab_widget.count() - 1)
        self.updateStackedWidget()

    
    def openAirdosTab(self):
        airdos_tab = AirdosConfigTab()
        self.tab_widget.addTab(airdos_tab, "Airdos control")
        self.tab_widget.setCurrentIndex(self.tab_widget.count() - 1)
        self.updateStackedWidget()
    
    def openLabdosTab(self):
        labdos_tab = LabdosConfigTab()
        self.tab_widget.addTab(labdos_tab, "Labdos control")
        self.tab_widget.setCurrentIndex(self.tab_widget.count() - 1)
        self.updateStackedWidget()

    def blank_page(self):
        # This is widget for blank page
        # When no tab is opened
        widget = QWidget()
        layout = QVBoxLayout()
        label = QLabel("No tab is opened yet. Open a file or enable airdos control.", alignment=Qt.AlignCenter)
        layout.addWidget(label)
        widget.setLayout(layout)
        return widget

    def initUI(self):
        self.setWindowTitle(self.title)
        self.setGeometry(self.left, self.top, self.width, self.height)
        self.setWindowIcon(QIcon('media/icon_ust.png'))
        
        self.restoreGeometry(self.settings.value("geometry", self.saveGeometry()))
        self.restoreState(self.settings.value("windowState", self.saveState()))

        self.tab_widget = QTabWidget()

        self.tab_widget.setCurrentIndex(0)
        self.tab_widget.setTabsClosable(True)

        bar = self.menuBar()
        file = bar.addMenu("&File")

        open = QAction("Open",self)
        open.setShortcut("Ctrl+O")
        open.triggered.connect(self.open_new_file)
        
        file.addAction(open)


        tools = bar.addMenu("&Tools")

        preferences = QAction("Preferences", self)
        preferences.triggered.connect(lambda: PreferencesVindow().exec())
        tools.addAction(preferences)

        tool_airdosctrl = QAction("AirdosControl", self)
        tool_airdosctrl.triggered.connect(self.action_switch_airdoscontrol)
        tools.addAction(tool_airdosctrl)

        tools_labdosctrl = QAction("LabdosControl", self)
        tools_labdosctrl.triggered.connect(self.action_switch_labdoscontrol)
        tools.addAction(tools_labdosctrl)


        help = bar.addMenu("&Help")
        doc = QAction("Documentation", self)
        help.addAction(doc)
        doc.triggered.connect(lambda: QDesktopServices.openUrl(QUrl("https://docs.dos.ust.cz/dosview/")))

        gith = QAction("GitHub repository", self)
        help.addAction(gith)
        gith.triggered.connect(lambda: QDesktopServices.openUrl(QUrl("https://github.com/UniversalScientificTechnologies/dosview/")))

        about = QAction("About", self)
        help.addAction(about)
        about.triggered.connect(self.about)

        self.statusBar = QStatusBar()
        self.setStatusBar(self.statusBar)
        self.statusBar.showMessage("Welcome to dosview")

        self.stacked_container = QStackedWidget()
        self.stacked_container.addWidget(self.blank_page())
        self.stacked_container.addWidget(self.tab_widget)
        self.stacked_container.setCurrentIndex(0)
        self.setCentralWidget(self.stacked_container)

        self.show()


    def action_switch_airdoscontrol(self):
        self.openAirdosTab()
    
    def action_switch_labdoscontrol(self):
        self.openLabdosTab()

    import sys
    import datetime
    from PyQt5.QtCore import QT_VERSION_STR
    from PyQt5.QtWidgets import QMessageBox
    from PyQt5.QtGui import QPixmap

    def about(self):
        about_text = f"""
        <b>dosview</b><br>
        <b>Version:</b> {__version__}<br>
        <br>
        Universal Scientific Technologies, s.r.o.<br>
        <a href="https://www.ust.cz/about/">www.ust.cz/</a><br>
        <br>
        <b>Description:</b><br>
        dosview is a utility for visualization and analysis of data from UST's <a href="https://docs.dos.ust.cz/">dosimeters and spectrometers</a>.<br>
        <br>
        <b>Support:</b> <a href="mailto:support@ust.cz">support@ust.cz</a><br>
        <br>
        <b> <a href="https://github.com/UniversalScientificTechnologies/dosview/issues">Report an issue to GitHub Issues</a><br>
        <br>
        <b>Source code:</b> <a href="https://github.com/UniversalScientificTechnologies/dosview/">GitHub repository</a><br>
        <br>
        <b>Technical info:</b><br>
        Python: {sys.version.split()[0]}<br>
        Qt: {QT_VERSION_STR}<br>
        Build date: {datetime.datetime.now().strftime("%Y-%m-%d")}<br>
        <br>
        <b>License:</b> GPL-3.0 License<br>
        &copy; 2025 Universal Scientific Technologies, s.r.o.<br>
        """
        dlg = QMessageBox(self)
        dlg.setWindowTitle("About dosview")
        dlg.setTextFormat(Qt.TextFormat.RichText)
        dlg.setText(about_text)
        dlg.setIconPixmap(QPixmap("media/icon_ust.png").scaled(64, 64))
        dlg.setStandardButtons(QMessageBox.Ok)
        dlg.exec_()


    def open_new_file(self, flag):
        print("Open new file")

        dlg = QFileDialog(self, "Projects" )
        dlg.setFileMode(QFileDialog.ExistingFile)

        fn = dlg.getOpenFileName()
        print("Open file", fn[0])
        if fn[0]:
            self.openPlotTab(fn[0])

        dlg.deleteLater()
    
    def closeEvent(self, event):
        print("Closing dosview...")
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("windowState", self.saveState())
        event.accept()
        

def main():
    parser = argparse.ArgumentParser(description='Process some integers.')
    parser.add_argument('file_path', type=str, help='Path to the input file', default=False, nargs='?')
    parser.add_argument('--airdos', action='store_true', help='Enable airdos control tab')
    parser.add_argument('--labdos', action='store_true', help='Enable labdos control tab')
    parser.add_argument('--no_gui', action='store_true', help='Disable GUI and run in headless mode')
    parser.add_argument('--version', action='store_true', help='Print version and exit')
    parser.add_argument('--new-window', action='store_true', help="Open file in new window")

    args = parser.parse_args()

    if args.version:
        print(f"dosview version {__version__}")
        sys.exit(0)

    print(args)

    pg.setConfigOption('background', 'w')
    pg.setConfigOption('foreground', 'gray')

    app = QApplication(sys.argv)

    # Create a local server for IPC
    server_name = 'dosview'
    socket = QLocalSocket()
    socket.connectToServer(server_name)
    
    if socket.waitForConnected(500):
        socket.write(args.file_path.encode())
        socket.flush()
        socket.waitForBytesWritten(1000)
        socket.disconnectFromServer()
        print("dosview is already running. Sending file path to the running instance.")
        sys.exit(0)
    else:
        server = QLocalServer()
        server.listen(server_name)
        
        def handle_connection():
            socket = server.nextPendingConnection()
            if socket.waitForReadyRead(1000):
                filename = socket.readAll().data().decode()
                print("Opening file from external instance startup ...", filename)
                ex.openPlotTab(filename)
                ex.activateWindow()
                ex.raise_()
                ex.setFocus()

                
        
        server.newConnection.connect(handle_connection)
    

    ex = App(args)
    sys.exit(app.exec_())

if __name__ == '__main__':
    main()
