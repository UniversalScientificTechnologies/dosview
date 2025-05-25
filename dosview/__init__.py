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
from PyQt5.QtWidgets import QSplitter

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

# ---- PARSER INFRA ----

class BaseLogParser:
    """Základní třída parseru."""
    def __init__(self, file_path):
        self.file_path = file_path

    @staticmethod
    def detect(file_path):
        """Vrací True pokud tento parser umí parsovat daný soubor."""
        raise NotImplementedError

    def parse(self):
        """Vrací rozparsovaná data."""
        raise NotImplementedError


class Airdos04CLogParser(BaseLogParser):
    """Parser pro logy typu AIRDOS04C."""
    @staticmethod
    def detect(file_path):
        with open(file_path, "r") as f:
            for line in f:
                if line.startswith("$DOS") and "AIRDOS04C" in line:
                    return True
        return False

    def parse(self):
        start_time = time.time()
        print("AIRDOS04C parser start")
        metadata = {
            'log_runs_count': 0,
            'log_device_info': {},
            'log_info': {}
        }
        hist = np.zeros(1024, dtype=int)
        total_counts = 0


        sums = []
        time_axis = []

        inside_run = False
        current_hist = None
        current_counts = 0

        with open(self.file_path, 'r') as file:
            for line in file:
                parts = line.strip().split(",")
                match parts[0]:
                    case "$DOS":
                        metadata['log_device_info']['DOS'] = {
                            "type": parts[0],
                            "hw-model": parts[1],
                            "fw-version": parts[2],
                            "eeprom": parts[3],
                            "fw-commit": parts[4],
                            "fw-build_info": parts[5],
                            'hw-sn': parts[6].strip(),
                        }
                        metadata['log_runs_count'] += 1
                    case "$START":
                        inside_run = True
                        current_hist = np.zeros_like(hist)
                        current_counts = 0
                    case "$E":
                        if inside_run and len(parts) >= 3:
                            channel = int(parts[2])
                            if 0 <= channel < current_hist.shape[0]:
                                current_hist[channel] += 1
                                current_counts += 1
                    case "$STOP":
                        if inside_run:
                            # Přičti hodnoty z $STOP (kanálové stavy na konci expozice)
                            if len(parts) > 4:
                                for idx, val in enumerate(parts[4:]):
                                    try:
                                        current_hist[idx] += int(val)
                                    except Exception:
                                        pass
                            hist += current_hist
                            total_counts += current_counts
                            sums.append(current_counts)
                            time_axis.append(float(parts[2]))
                        inside_run = False
                        current_hist = None
                    case _:
                        continue

        metadata['log_info']['histogram_channels'] = hist.shape[0]
        metadata['log_info']['events_total'] = int(total_counts)  # pouze součet všech E!
        metadata['log_info']['log_type_version'] = "2.0"
        metadata['log_info']['log_type'] = 'xDOS_SPECTRAL'
        metadata['log_info']['detector_type'] = "AIRDOS04C"
        print("Parsed AIRDOS04C format in", time.time() - start_time, "s")

        return [np.array(time_axis), np.array(sums), hist, metadata]


    
class OldLogParser(BaseLogParser):
    """Parser pro starší logy (ne-AIRDOS04C)."""
    @staticmethod
    def detect(file_path):
        with open(file_path, "r") as f:
            for line in f:
                if line.startswith("$DOS") and "AIRDOS04C" not in line:
                    return True
        return False

    def parse(self):
        start_time = time.time()
        print("OLD parser start")
        metadata = {
            'log_runs_count': 0,
            'log_device_info': {},
            'log_info': {}
        }
        df_lines = []  # $HIST
        df_metadata = []
        unique_events = []  # $HITS
        with open(self.file_path, 'r') as file:
            for line in file:
                parts = line.strip().split(",")
                match parts[0]:
                    case "$DOS":
                        metadata['log_device_info']['DOS'] = {
                            "type": parts[0],
                            "hw-model": parts[1],
                            "fw-version": parts[2],
                            "eeprom": parts[3],
                            "fw-commit": parts[4],
                            "fw-build_info": parts[5],
                            'hw-sn': parts[6].strip(),
                        }
                        metadata['log_runs_count'] += 1
                    case "$ENV":
                        df_metadata.append(parts[2:])
                    case "$HIST":
                        df_lines.append(parts[1:])
                    case "$HITS":
                        unique_events += [(float(parts[i]), int(parts[i+1])) for i in range(2, len(parts), 2)]
                    case _:
                        continue
        np_spectrum = np.array(df_lines, dtype=float)
        zero_columns = np.zeros((np_spectrum.shape[0], 1000))
        np_spectrum = np.hstack((np_spectrum, zero_columns))
        time_column = np_spectrum[:, 1]
        np_spectrum = np_spectrum[:, 7:]
        for event in unique_events:
            t, ch = event
            time_index = np.searchsorted(time_column, t)
            if 0 <= time_index < np_spectrum.shape[0] and 0 <= ch < np_spectrum.shape[1]:
                np_spectrum[time_index, ch] += 1
        hist = np.sum(np_spectrum[:, 1:], axis=0)
        sums = np.sum(np_spectrum[:, 1:], axis=1)
        metadata['log_info'].update({
            'internal_time_min': time_column.min(),
            'internal_time_max': time_column.max(),
            'log_duration': time_column.max() - time_column.min(),
            'spectral_count': sums.shape[0],
            'channels': hist.shape[0],
            'hits_count': len(unique_events),
            'log_type_version': "1.0",
            'log_type': 'xDOS_SPECTRAL',
            'detector_type': metadata['log_device_info']['DOS'].get('hw-model', 'unknown'),
        })
        print("Parsed OLD format in", time.time() - start_time, "s")
        return [time_column, sums, hist, metadata]


class dosparser():
    def __init__(self):
        pass 

    def load_file(self, datafile : str , detector = None):
        pass

LOG_PARSERS = [Airdos04CLogParser, OldLogParser]

def get_parser_for_file(file_path):
    for parser_cls in LOG_PARSERS:
        if parser_cls.detect(file_path):
            return parser_cls(file_path)
    raise ValueError("Neznámý typ logu nebo žádný vhodný parser.")

def parse_file(file_path):
    parser = get_parser_for_file(file_path)
    return parser.parse()


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


class FT260HidDriver():

    """
    Key to symbols
    ==============

    S     (1 bit) : Start bit
    P     (1 bit) : Stop bit
    Rd/Wr (1 bit) : Read/Write bit. Rd equals 1, Wr equals 0.
    A, NA (1 bit) : Accept and reverse accept bit.
    Addr  (7 bits): I2C 7 bit address. Note that this can be expanded as usual to
                    get a 10 bit I2C address.
    Comm  (8 bits): Command byte, a data byte which often selects a register on
                    the device.
    Data  (8 bits): A plain data byte. Sometimes, I write DataLow, DataHigh
                    for 16 bit data.
    Count (8 bits): A data byte containing the length of a block operation.

    [..]: Data sent by I2C device, as opposed to data sent by the host adapter.

    More detail documentation is at https://www.kernel.org/doc/Documentation/i2c/smbus-protocol
    """

    def __init__(self, port, device):
        self.port = port
        #self.smbus = smbus
        self.driver_type = 'ft260_hid'
        self.device = device
        self.initialize_ftdi()
    


    def initialize_ftdi(self):
        # TODO pripojeni k HID, nyni to mam jako self.device
        
        print(f'Device manufacturer: {self.device.get_manufacturer_string()}')
        print(f'Product: {self.device.get_product_string()}')
        print(f'Serial Number: {self.device.get_serial_number_string()}')

        self.device.set_nonblocking(0)

        self.reset_i2c()
        #self.set_i2c_speed(100000) # 100 Khz
        self.get_i2c_status()


    def get_i2c_status(self):
        d = self.device.get_feature_report(0xC0, 100)

        status = ['busy_chip', 'error', 'no_ack', 'arbitration_lost', 'idle', 'busy_bus']
        bits = [(d[1] & (1 << i)) >> i for i in range(8)]
        status = dict(zip(status, bits))

        baudrate = (d[2] | d[3]<<8)*1000
        status['baudrate'] = baudrate

        return status
        
    
    def reset_i2c(self):
        self.device.send_feature_report([0xA1, 0x20])
        
    def set_i2c_speed(self, speed = 100000):
        speed = int(speed/1000)
        LSB = (speed & 0xff)
        MSB = (speed>>8 & 0xff)
        print(f"Nastavit speed na {speed} Hz: ", hex(LSB), hex(MSB))
        self.device.send_feature_report([0xA1, 0x22, LSB, MSB])


    def write_byte(self, address, value):
        """
        SMBus Send Byte:  i2c_smbus_write_byte()
        ========================================

        This operation is the reverse of Receive Byte: it sends a single byte
        to a device.  See Receive Byte for more information.

        S Addr Wr [A] Data [A] P

        Functionality flag: I2C_FUNC_SMBUS_WRITE_BYTE
        """

        payload = [0xD0, address, 0x06, 1, value]
        self.device.write(payload)


    def read_byte(self, address):
        """
        SMBus Send Byte:  i2c_smbus_write_byte()
        ========================================

        This operation is the reverse of Receive Byte: it sends a single byte
        to a device.  See Receive Byte for more information.

        S Addr Wr [A] Data [A] P

        Functionality flag: I2C_FUNC_SMBUS_WRITE_BYTE
        """
        raise NotImplementedError

    def write_byte_data(self, address, register, value):
        """
        SMBus Read Byte:  i2c_smbus_read_byte_data()
        ============================================

        This reads a single byte from a device, from a designated register.
        The register is specified through the Comm byte.

        S Addr Wr [A] Comm [A] S Addr Rd [A] [Data] NA P

        Functionality flag: I2C_FUNC_SMBUS_READ_BYTE_DATA
        """

        return self.device.write([0xD0, address, 0x06, 2, register, value])


    def read_byte_data(self, address, register):
        """
        SMBus Read Byte:  i2c_smbus_read_byte_data()
        ============================================

        This reads a single byte from a device, from a designated register.
        The register is specified through the Comm byte.

        S Addr Wr [A] Comm [A] S Addr Rd [A] [Data] NA P

        Functionality flag: I2C_FUNC_SMBUS_READ_BYTE_DATA
        """


        payload = [0xD0, address, 0x06, 0b01, register]
        self.device.write(payload)
        length = (1).to_bytes(2, byteorder='little')
        self.device.write([0xC2, address, 0x06, length[0], length[1]])
        d = self.device.read(0xde)

        # TODO: Osetrit chyby v chybnem vycteni registru
        return d[2]


    def write_word_data(self, address, register, value):
        """
        SMBus Write Word:  i2c_smbus_write_word_data()
        ==============================================

        This is the opposite of the Read Word operation. 16 bits
        of data is written to a device, to the designated register that is
        specified through the Comm byte.

        S Addr Wr [A] Comm [A] DataLow [A] DataHigh [A] P

        Functionality flag: I2C_FUNC_SMBUS_WRITE_WORD_DATA

        Note the convenience function i2c_smbus_write_word_swapped is
        available for writes where the two data bytes are the other way
        around (not SMBus compliant, but very popular.)
        """
        return self.device.write([0xD0, address, 0x06, 3, register, (value)&0xff, (value>>8)&0xff ])

    def read_word_data(self, address, register):
        """
        SMBus Read Word:  i2c_smbus_read_word_data()
        ============================================

        This operation is very like Read Byte; again, data is read from a
        device, from a designated register that is specified through the Comm
        byte. But this time, the data is a complete word (16 bits).

        S Addr Wr [A] Comm [A] S Addr Rd [A] [DataLow] A [DataHigh] NA P

        Functionality flag: I2C_FUNC_SMBUS_READ_WORD_DATA

        Note the convenience function i2c_smbus_read_word_swapped is
        available for reads where the two data bytes are the other way
        around (not SMBus compliant, but very popular.)
        """

        payload = [0xD0, address, 0x06, 0b01, register]
        self.device.write(payload)
        length = (2).to_bytes(2, byteorder='little')
        self.device.write([0xC2, address, 0x06, length[0], length[1]])
        d = self.device.read(0xde)

        # TODO: Osetrit chyby v chybnem vycteni registru
        return d[2]<<8 | d[3]

    def write_block_data(self, address, register, value):
        """
        SMBus Block Write:  i2c_smbus_write_block_data()
        ================================================

        The opposite of the Block Read command, this writes up to 32 bytes to
        a device, to a designated register that is specified through the
        Comm byte. The amount of data is specified in the Count byte.

        S Addr Wr [A] Comm [A] Count [A] Data [A] Data [A] ... [A] Data [A] P

        Functionality flag: I2C_FUNC_SMBUS_WRITE_BLOCK_DATA
        """
        raise NotImplementedError

    def read_block_data(self, address, register):
        """
        SMBus Block Read:  i2c_smbus_read_block_data()
        ==============================================

        This command reads a block of up to 32 bytes from a device, from a
        designated register that is specified through the Comm byte. The amount
        of data is specified by the device in the Count byte.

        S Addr Wr [A] Comm [A]
                   S Addr Rd [A] [Count] A [Data] A [Data] A ... A [Data] NA P

        Functionality flag: I2C_FUNC_SMBUS_READ_BLOCK_DATA
        """
        raise NotImplementedError

    def block_process_call(self, address, register, value):
        """
        SMBus Block Write - Block Read Process Call
        ===========================================

        SMBus Block Write - Block Read Process Call was introduced in
        Revision 2.0 of the specification.

        This command selects a device register (through the Comm byte), sends
        1 to 31 bytes of data to it, and reads 1 to 31 bytes of data in return.

        S Addr Wr [A] Comm [A] Count [A] Data [A] ...
                                     S Addr Rd [A] [Count] A [Data] ... A P

        Functionality flag: I2C_FUNC_SMBUS_BLOCK_PROC_CALL
        """
        raise NotImplementedError

    ### I2C transactions not compatible with pure SMBus driver
    def write_i2c_block(self, address, value):
        """
        Simple send transaction
        ======================

        This corresponds to i2c_master_send.

          S Addr Wr [A] Data [A] Data [A] ... [A] Data [A] P

        More detail documentation is at: https://www.kernel.org/doc/Documentation/i2c/i2c-protocol
        """
        raise NotImplementedError

    def read_i2c_block(self, address, length):
        """
        Simple receive transaction
        ===========================

        This corresponds to i2c_master_recv

          S Addr Rd [A] [Data] A [Data] A ... A [Data] NA P

        More detail documentation is at: https://www.kernel.org/doc/Documentation/i2c/i2c-protocol
        """

        payload = [0xc2, address, 0x06, length, 0]
        self.device.write(payload)
        data = self.device.read(0xde)

        return data[2:data[1]+2]

    def write_i2c_block_data(self, address, register, value):
        """
        I2C block transactions do not limit the number of bytes transferred
        but the SMBus layer places a limit of 32 bytes.

        I2C Block Write:  i2c_smbus_write_i2c_block_data()
        ==================================================

        The opposite of the Block Read command, this writes bytes to
        a device, to a designated register that is specified through the
        Comm byte. Note that command lengths of 0, 2, or more bytes are
        supported as they are indistinguishable from data.

        S Addr Wr [A] Comm [A] Data [A] Data [A] ... [A] Data [A] P

        Functionality flag: I2C_FUNC_SMBUS_WRITE_I2C_BLOCK
        """
        
        payload = [0xD0, address, 0x06, len(value) + 1, register] + value
        self.device.write(payload)


    def read_i2c_block_data(self, address, register, length):
        """
        I2C Block Read: i2c_smbus_read_i2c_block_data()
        =================================================

        Reads a block of bytes from a specific register in a device. It's the direct
        opposite of the Block Write command, primarily used for retrieving a series
        of bytes from a given register.

        S Addr Wr [A] Comm [A] S Addr Rd [A] Data [A] Data [A] ... [A] Data [A] P

        The method respects SMBus limitations of 32 bytes for block transactions.
        """

        timeout = 500

        register = (register).to_bytes(2, byteorder='little')
        payload = [0xD4, address, 0x02, 2, register[0], register[1]]
        self.device.write(payload)
        length = (length).to_bytes(2, byteorder='little')
        self.device.write([0xC2, address, 0x07, length[0], length[1]])
        d = self.device.read(0xde, timeout)

        print(d)

        return d[2:d[1]]

    def write_i2c_block_data(self, address, register, data):
        """
        I2C Block Write: i2c_smbus_write_i2c_block_data()
        =================================================

        Writes a block of bytes to a specific register in a device. This command
        is designed for direct I2C communication, allowing for command lengths of 0,
        2, or more bytes, which are indistinguishable from data.

        S Addr Wr [A] Comm [A] Data [A] Data [A] ... [A] Data [A] P

        Functionality flag: I2C_FUNC_SMBUS_WRITE_I2C_BLOCK
        """

        register = (register).to_bytes(2, byteorder='little')
        payload = [0xD4, address, 0x06, 0, register[0], register[1]] + data
        payload[3] = len(payload) - 4
        self.device.write(payload)

        return True
    



class eeprom():
    def __init__(self, bus, address):
        self.bus = bus
        self.address = address
        
    def read_serial_number(self):
        serial_number = []
        #self.bus.write_byte_data(self.address+8, 0x08, 0x00)
        self.bus.write_byte_data(0x58, 0x08, 0x00)
        for _ in range(16):
            serial_byte = self.bus.read_byte(0x58)
            serial_number.append(serial_byte)
            print("Serial byte: ", serial_byte)
        
        result_number = 0
        for b in serial_number:
            result_number = (result_number << 8) | b

        #devices.append(address)
        return result_number

    def read_eeprom(self, len):
        serial_number = []
        self.bus.write_byte_data(self.address, 0x00, 0x00)
        for _ in range(len):
            serial_byte = self.bus.read_byte(self.address)
            serial_number.append(serial_byte)
        
        result_number = 0
        for b in serial_number:
            result_number = (result_number << 8) | b

        #devices.append(address)
        #return result_number
        return serial_number

    def write_to_eeprom(self, data, offset = 0):
        mem_addr_b = offset & 0xff
        mem_addr_a = (offset>>8) & 0xff

        self.bus.write_i2c_block_data(address, mem_addr_a, [mem_addr_b]+data)


class HIDI2CCommunicationThread(QThread):
    connected = pyqtSignal(bool)
    connect = pyqtSignal(bool)
    sendAirdosStatus = pyqtSignal(dict)

    #VID = 0x0403
    #PID = 0x6030
    VID = 0x1209    
    PID = 0x7aa0
    I2C_INTERFACE = 0


    addr_switch = 0x70
    addr_switch = 0x7c
    addr_charger = 0x6a
    addr_gauge = 0x55
    addr_rtc = 0x51
    addr_eeprom = 0x50
    addr_eepromsn = 0x58

    addr_sht = 0x44
    addr_switch = 0x70
    addr_sdcard = 0x71
    addr_charger = 0x6a
    addr_gauge = 0x55
    addr_rtc = 0x51
    addr_eeprom = 0x50
    addr_eepromsn = 0x58
    addr_altimet = 0x77
    addr_an_sht = 0x45
    addr_an_eeprom = 0x53
    addr_an_eepromsn = 0x5b

    basic_params = {}

    
    # Příkazy pro čtení teploty a vlhkosti
    temperature_cmd = [0x24, 0x00]  # Příkaz pro čtení teploty v režimu High Precision
    humidity_cmd = [0x24, 0x16]     # Příkaz pro čtení vlhkosti v režimu High Precision
    serial_number_cmd = [0x37, 0x80]



    dev = None
    ftdi = None

    def __init__(self):
        QThread.__init__(self)
        # Initialize HID communication here

    def run(self):
        # Implement HID communication logic here

        # Connect to HID device
        self.connected.emit(False)
        while 1:
            pass
    

    # Funkce pro čtení dat ze senzoru
    def sht_read_sensor_data(self, address, cmd):
        
        register = (0x08).to_bytes(2, byteorder='little')
        payload = [0xD4, address, 0x06, 2, cmd[0], cmd[1]]
        self.dev.write(payload)
        time.sleep(0.4)
        length = (6).to_bytes(2, byteorder='little')
        self.dev.write([0xC2, address, 0x06, length[0], length[1]])
        data = self.dev.read(0xde, 1000)[2:]

        print("... SHT data:", data)
        raw_temperature = (data[0] << 8) + data[1]
        raw_humidity = (data[3] << 8) + data[4]
        temperature = -45 + 175 * (raw_temperature / 65535.0)  # Výpočet teploty
        humidity = 100 * (raw_humidity / 65535.0)             # Výpočet vlhkosti
        return temperature, humidity


    def sht_read_sn(self, cmd):
        self.ftdi.write_i2c_block_data(self.addr_sht, cmd[0], [cmd[1]])
        data = self.ftdi.read_i2c_block_data(self.addr_sht, 0, 6)
        print(data)
        serial_number = (data[0] << 24) | (data[1] << 16) | (data[3] << 8) | data[4]
        return serial_number
    
    def set_i2c_direction_to_usb(self, usb = True):
        # Přepnout I2C switch na I2C z USB

        if usb:
            # Do usb se to prepne tak, ze bit[0] a bit[2] jsou rozdilne hodnoty, bit[1] a bit[3] jsou read-only
            self.ftdi.write_byte_data(self.addr_switch, 0x01, 0b011)
        else:
            # I2C do ATMEGA se to prepne tak, ze bit[0] a bit[2] maji stejne hodnoty hodnoty
            self.ftdi.write_byte_data(self.addr_switch, 0x01, 0b0000)

    @pyqtSlot()
    def connectSlot(self, state = True, power_off = False):
        print("Connecting to HID device... ", state)
        if state:

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

            self.dev.send_feature_report([0xA1, 0x20])
            self.dev.send_feature_report([0xA1, 0x02, 0x01])

            self.ftdi = FT260HidDriver(0, self.dev)


            # Přepnout I2C switch na I2C z USB
            self.set_i2c_direction_to_usb(True)


            # self.ftdi.write_byte_data(self.addr_charger, 0x26, 0b10111000) # ????? 
            self.ftdi.write_byte_data(self.addr_charger, 0x18, 0b00011000)


            print("AIRDOS SN ... ")
            eeprom_data = self.ftdi.read_i2c_block_data(self.addr_eepromsn, 0x08, 18)
            print(eeprom_data)
            sn = 0
            for s in eeprom_data:
                sn = (sn << 8) | s
            print(hex(sn))
            self.basic_params['sn_batdatunit'] = hex(sn)

            eeprom_data = self.ftdi.read_i2c_block_data(self.addr_an_eepromsn, 0x08, 18)
            print(eeprom_data)
            sn = 0
            for s in eeprom_data:
                sn = (sn << 8) | s
            print(hex(sn))
            self.basic_params['sn_ustsipin'] = hex(sn)

            self.set_i2c_direction_to_usb(False)


            self.connected.emit(True)
        
        else:
            
            self.set_i2c_direction_to_usb(True)

            # Vypnout nabijecku pokud je pozadovano
            if power_off:
                self.ftdi.write_byte_data(self.addr_charger, 0x18, 0b00011010)
            self.set_i2c_direction_to_usb(False)

            self.dev.close()
            self.dev_uart.close()
            self.dev = None
            self.ftdi = None
            self.connected.emit(False)

    def get_time(self):        
        # self.addr_rtc = 0x51
        r00 = self.ftdi.read_byte_data(self.addr_rtc, 0x00)
        r01 = self.ftdi.read_byte_data(self.addr_rtc, 0x01)
        r02 = self.ftdi.read_byte_data(self.addr_rtc, 0x02)
        r03 = self.ftdi.read_byte_data(self.addr_rtc, 0x03)
        r04 = self.ftdi.read_byte_data(self.addr_rtc, 0x04)
        r05 = self.ftdi.read_byte_data(self.addr_rtc, 0x05)
        r06 = self.ftdi.read_byte_data(self.addr_rtc, 0x06)
        r07 = self.ftdi.read_byte_data(self.addr_rtc, 0x07)

        #r = self.ftdi.read_i2c_block_data(self.addr_rtc, 0x00, 8)
        
        sec100 = r00 & 0b1111 + ((r00 & 0b11110000) >> 4) * 10
        absdate = datetime.datetime.now(datetime.timezone.utc)
        sec = r01 & 0b1111 + ((r01 & 0b01110000) >> 4) * 10
        minu= r02 & 0b1111 + ((r02 & 0b01110000) >> 4) * 10
        hour = r03 & 0b1111 + ((r03 & 0b11110000) >> 4) * 10
        hour += r04 & 0b1111 * 100 + ((r04 & 0b11110000) >> 4) * 1000
        hour += r05 & 0b1111 * 10000 + ((r05 & 0b11110000) >> 4) * 100000
        #hour = r03 + r04*100 + r05*10000

        print("RTC data:", r00, r01, r02, r03, r04, r05, r06, r07)
        print("RTC time: ", hour, minu, sec, sec100)

        date_delta = datetime.timedelta(hours=hour, minutes=minu, seconds=sec, milliseconds=sec100*10)
        
        return(absdate, date_delta)
    
    def reset_time(self):
        reset_time = datetime.datetime.now(datetime.timezone.utc)
        
        # self.ftdi.write_i2c_block_data(self.addr_rtc, 0x00, [0, 0, 0, 0, 0, 0, 0, 0])
        
        self.ftdi.write_byte_data(self.addr_rtc, 0x00, 0)
        self.ftdi.write_byte_data(self.addr_rtc, 0x01, 0)
        self.ftdi.write_byte_data(self.addr_rtc, 0x02, 0)
        self.ftdi.write_byte_data(self.addr_rtc, 0x03, 0)
        self.ftdi.write_byte_data(self.addr_rtc, 0x04, 0)
        self.ftdi.write_byte_data(self.addr_rtc, 0x05, 0)
        self.ftdi.write_byte_data(self.addr_rtc, 0x06, 0)
        self.ftdi.write_byte_data(self.addr_rtc, 0x07, 0)

        print("Time reseted at...", reset_time)


    def get_battery(self):
        ibus_adc = (self.ftdi.read_byte_data(self.addr_charger, 0x28) >> 1) * 2  
        ibat_adc = (self.ftdi.read_byte_data(self.addr_charger, 0x2A) >> 2) * 4 
        vbus_adc = (self.ftdi.read_byte_data(self.addr_charger, 0x2C) >> 2) * 3.97 / 1000
        vpmid_adc= (self.ftdi.read_byte_data(self.addr_charger, 0x2E) >> 2) * 3.97 / 1000
        vbat_adc = (self.ftdi.read_word_data(self.addr_charger, 0x30) >> 1) * 1.99 /1000  # VBAT ADC
        vsys_adc = (self.ftdi.read_word_data(self.addr_charger, 0x32) >> 1) * 1.99 /1000 # VSYS ADC
        tf_adc   = (self.ftdi.read_word_data(self.addr_charger, 0x34) >> 0) * 0.0961  # TF ADC
        tdie_adc = (self.ftdi.read_word_data(self.addr_charger, 0x36) >> 0) * 0.5  # TDIE ADC

        g_voltage = self.ftdi.read_word_data(self.addr_gauge, 0x08)
        g_cur_avg = self.ftdi.read_word_data(self.addr_gauge, 0x0A)
        g_cur_now = self.ftdi.read_word_data(self.addr_gauge, 0x10)
        g_rem_cap = self.ftdi.read_word_data(self.addr_gauge, 0x04)
        g_ful_cap = self.ftdi.read_word_data(self.addr_gauge, 0x06)
        g_temp    = self.ftdi.read_word_data(self.addr_gauge, 0x0C)
        g_state   = self.ftdi.read_word_data(self.addr_gauge, 0x02)


        return {
            'IBUS_ADC': ibus_adc,
            'IBAT_ADC': ibat_adc,
            'VBUS_ADC': vbus_adc,
            'VPMID_ADC': vpmid_adc,
            'VBAT_ADC': vbat_adc,
            'VSYS_ADC': vsys_adc,
            'TS_ADC': tf_adc,
            'TDIE_ADC': tdie_adc
        }, {
            'VOLTAGE': g_voltage,
            'CUR_AVG': g_cur_avg,
            'CUR_NOW': g_cur_now,
            'REM_CAP': g_rem_cap,
            'FUL_CAP': g_ful_cap,
            'TEMP': g_temp,
            'STATE': g_state
            
        }

    @pyqtSlot()
    def get_airdos_status(self):

        self.set_i2c_direction_to_usb(True)

        abstime, sys_date = self.get_time()
        charger, gauge = self.get_battery()

        data = self.basic_params.copy()
        data.update({
            'RTC': {
                'sys_time': sys_date,
                'abs_time': abstime,
                'sys_begin_time': abstime - sys_date
            },
            'CHARGER': charger,
            'GAUGE': gauge
        })

        a,b = self.sht_read_sensor_data(self.addr_sht, [0x24, 0x0b] )
        data['SHT'] = {
            'temperature': a,
            'humidity': b
        }

        a, b = self.sht_read_sensor_data(self.addr_an_sht, [0x24, 0x0b] )
        data['AIRDOS_SHT'] = {
            'temperature': a,
            'humidity': b
        }


        data['ALTIMET'] = {}
        data['ALTIMET']['calcoef'] = []
        for value in range(0xa0, 0xae, 2):
            self.ftdi.write_byte(self.addr_altimet, value)
            # time.sleep(0.2)
            # self.ftdi.write_byte(self.addr_altimet, 0)
            time.sleep(0.1)
            dat = self.ftdi.read_i2c_block(self.addr_altimet, 2)
            time.sleep(0.1)
            dat = dat[0] << 8 | dat[1]
            data['ALTIMET']['calcoef'].append(dat)
        time.sleep(0.2)
            
        self.ftdi.write_byte(self.addr_altimet, 0b01001000)
        time.sleep(0.2)
        self.ftdi.write_byte(self.addr_altimet, 0)
        time.sleep(0.2)
        hum = self.ftdi.read_i2c_block(self.addr_altimet, 3)
        time.sleep(0.2)

        self.ftdi.write_byte(self.addr_altimet, 0b01011000)
        time.sleep(0.2)
        self.ftdi.write_byte(self.addr_altimet, 0)
        time.sleep(0.2)
        temp = self.ftdi.read_i2c_block(self.addr_altimet, 3)
        time.sleep(0.2)

        data['ALTIMET'].update({
            'altitude': hum[0] << 16 | hum[1] << 8 | hum[2],
            'temperature': temp[0] << 16 | temp[1] << 8 | temp[2]
        })

        self.set_i2c_direction_to_usb(False)
        print("Posilam...", type(data))
        print(data)
        self.sendAirdosStatus.emit(data)


    @pyqtSlot()
    def reset_rtc_time(self):
        self.set_i2c_direction_to_usb(True)
        self.reset_time()
        self.set_i2c_direction_to_usb(False)

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

        self.i2c_thread = HIDI2CCommunicationThread()
        self.i2c_thread.connected.connect(self.on_i2c_connected)  
        self.i2c_thread.sendAirdosStatus.connect(self.on_airdos_status)
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


        self.i2c_parameters_tree.clear()

        def add_properties_to_tree(item, properties):
            for key, value in properties.items():
                if isinstance(value, dict):
                    parent_item = QTreeWidgetItem([key])
                    item.addChild(parent_item)
                    add_properties_to_tree(parent_item, value)
                else:
                    child_item = QTreeWidgetItem([key, str(value)])
                    item.addChild(child_item)

        for key, value in status.items():
            print(key, value)
            if isinstance(value, dict):
                parent_item = QTreeWidgetItem([key])
                self.i2c_parameters_tree.addTopLevelItem(parent_item)
                add_properties_to_tree(parent_item, value)
            else:
                self.i2c_parameters_tree.addTopLevelItem(QTreeWidgetItem([key, str(value)]))
        self.i2c_parameters_tree.expandAll()


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

        self.i2c_parameters_tree = QTreeWidget()
        self.i2c_parameters_tree.setHeaderLabels(["Parameter", "Value"])
        i2c_layout.addWidget(self.i2c_parameters_tree)

        reload_button = QPushButton("Reload")
        reload_button.clicked.connect(self.i2c_thread.get_airdos_status)
        i2c_layout.addWidget(reload_button)

        reset_time_button = QPushButton("Reset time")
        reset_time_button.clicked.connect(self.i2c_thread.reset_rtc_time)
        i2c_layout.addWidget(reset_time_button)

        uart_widget = QGroupBox("UART")
        uart_layout = QVBoxLayout()
        uart_layout.setAlignment(Qt.AlignTop)
        uart_widget.setLayout(uart_layout)

        uart_connect_button = QPushButton("Connect")
        uart_disconnect_button = QPushButton("Disconnect")
        uart_layout.addWidget(uart_connect_button)
        uart_layout.addWidget(uart_disconnect_button)

        data_memory_widget = QGroupBox("Data memory")
        data_memory_layout = QVBoxLayout()
        data_memory_layout.setAlignment(Qt.AlignTop)
        data_memory_widget.setLayout(data_memory_layout)
        
        data_memory_connect_button = QPushButton("Connect")
        data_memory_disconnect_button = QPushButton("Disconnect")
        data_memory_layout.addWidget(data_memory_connect_button)
        data_memory_layout.addWidget(data_memory_disconnect_button)
        
        
        splitter.addWidget(i2c_widget)
        splitter.addWidget(uart_widget)
        splitter.addWidget(data_memory_widget)
        
        layout = QVBoxLayout()
        layout.addWidget(splitter)
        self.setLayout(layout)


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
            url = QtCore.QUrl("http://127.0.0.1:8100/api/record/")
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

        gith = QAction("Dosview GitHub", self)
        help.addAction(gith)
        gith.triggered.connect(lambda: QDesktopServices.openUrl(QUrl("https://github.com/UniversalScientificTechnologies/dosview/")))

        about = QAction("About", self)
        help.addAction(about)
        help.triggered.connect(self.about)

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

    def about(self):
        message = QMessageBox.about(self, "About dosview", "dosview is a simple tool to visualize data from Universal Scientific Technologies's")


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