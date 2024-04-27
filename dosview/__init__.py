import sys
import argparse

from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget, QHBoxLayout
from PyQt5.QtWidgets import QFileDialog, QTreeWidget, QTreeWidgetItem, QAction, QSplitter, QTableWidgetItem

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

def parse_file(file_path):

        print("Parser start ")

        metadata = {
            'log_runs_count': 0,
            'log_device_info': {}
        }
        max_size = 0

        with open(file_path, 'r') as file:
            for line in file:
                parts_size = len(line.split(","))
                if parts_size > max_size: max_size = parts_size

                for line in file:
                    parts_size = len(line.split(","))
                    if parts_size > max_size: max_size = parts_size

                    parts = line.split(",")
                    match parts[0]:
                        case "$HIST":
                            pass
                            # spec_mod = SpectrumData()
                            # spec_mod.record = instance
                            # spec_mod.spectrum = parts[8:]
                            # spec_mod.integration = 10
                            # spec_mod.time = parts[2]
                            # spec_mod.save()
                        case "$DOS":
                            print("DOS", line)
                            metadata['log_runs_count'] += 1
                            metadata['log_device_info']['DOS'] = {
                                "type": parts[0],
                                "hw-model": parts[1],
                                "fw-version": parts[2],
                                "fw-build_info": parts[5],
                                "fw-commit": parts[4],
                                'hw-sn': parts[6].strip()
                            }
                        case "$DIG":
                            print("DIG", line)
                            metadata['log_device_info']['DIG'] = {
                                "type": parts[0],
                                "hw-model": parts[1],
                                "hw-sn": parts[2],
                                'eeprom': parts[3].strip()
                            }
                        case "$ADC":
                            print("ADC", line)
                            metadata['log_device_info']['ADC'] = {
                                "type": parts[0],
                                "hw-model": parts[1],
                                "hw-sn": parts[2],
                                'eeprom': parts[3].strip()
                            }
                        case _:
                            pass

        df_log = pd.read_csv(file_path, sep = ',', header = None, names=range(max_size), low_memory=False)
        data_types = df_log[0].unique().tolist()

        df_spectrum = df_log [df_log[0] == '$HIST'] 
        df_spectrum = df_spectrum.drop(columns=[0, 1, 3, 4, 5, 6, 7])

        new_columns = ['time'] + list(range(df_spectrum.shape[1] - 1))
        df_spectrum.columns = new_columns

        df_spectrum['time'] = df_spectrum['time'].astype(float)
        minimal_time = df_spectrum['time'].min()
        duration = df_spectrum['time'].max() - df_spectrum['time'].min()

        metadata['log_info'] = {}
        metadata['log_info']['log_type'] = 'xDOS_SPECTRAL'
        metadata['log_info']['log_type_version'] = '1.0'
        metadata['log_info']['internal_time_min'] = df_spectrum['time'].min()
        metadata['log_info']['internal_time_max'] = df_spectrum['time'].max()
        metadata['log_info']['log_duration'] = float(duration)
        metadata['log_info']['spectral_count'] = df_spectrum.shape[0]
        metadata['log_info']['channels'] = df_spectrum.shape[1] - 1
        metadata['log_info']['types'] = data_types
        metadata['log_info']['telemetry_values'] = []

        df_spectrum['time'] = df_spectrum['time'] - df_spectrum['time'].min()

        time = df_spectrum['time'].to_list()
        sums = df_spectrum.drop('time', axis=1).sum(axis=1) #.div(total_time)

        hist = df_spectrum.drop('time', axis=1).sum(axis=0)


        df_metadata = pd.DataFrame()
        
        if True:
            try:
                for index, row in df_log.iterrows():
                    first_column_value = row[0]
                    row_as_list = row.tolist()[2:]
                    
                    match first_column_value:
                        case '$BATT':
                            keys = ['time', 'voltage', 'current', 'capacity_remaining', 'capacity_full', 'temperature']
                            bat = { k:float(v) for (k,v) in zip(keys, row_as_list[0:len(keys)])}
                            #bat['current'] /= 1000.0
                            #bat['voltage'] /= 1000.0
                            df_metadata = pd.concat([df_metadata, pd.DataFrame([bat])], ignore_index=True)
                            del bat
                        case '$ENV':
                            keys = ['time', 'temperature_0', 'humidity_0', 'temperature_1', 'humidity_1', 'temperature_2', 'pressure_3']
                            env = { k:float(v) for (k,v) in zip(keys, row_as_list[0:len(keys)])}
                            df_metadata = pd.concat([df_metadata, pd.DataFrame([env])], ignore_index=True)
                            del env
                        case '$HIST':
                            pass
                        case _:
                            print('Unknown row', first_column_value)
                            
                df_metadata['time'] = df_metadata['time'] - minimal_time
            except Exception as e:
                print(e)
            

        print("File parsered ..")

        return [df_spectrum['time'], sums, hist, metadata, df_metadata]

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

        self.data = data
        window_size = 20

        self.clear()
        plot_evolution = self.addPlot(row=0, col=0)
        plot_spectrum = self.addPlot(row=1, col=0)

        plot_evolution.showGrid(x=True, y=True)
        plot_evolution.setLabel("left",  "Total count per exposition", units="#")
        plot_evolution.setLabel("bottom","Time", units="min")

        time_axis = (self.data[0]/60).to_list()
        plot_evolution.plot(time_axis, self.data[1].to_list(),
                        symbol ='o', symbolPen ='pink', name ='Channel', pen=None)
        
        pen = pg.mkPen(color="r", width=3)
        rolling_avg = self.data[1].rolling(window=window_size).mean().to_list()
        plot_evolution.plot(time_axis, rolling_avg, pen=pen)


        ev_data = self.data[2].to_list()
        plot_spectrum.plot(range(len(ev_data)), ev_data, 
                        pen="r", symbol='x', symbolPen = 'g',
                        symbolBrush = 0.2, name = "Energy")
        plot_spectrum.setLabel("left", "Total count per channel", units="#")
        plot_spectrum.setLabel("bottom", "Channel", units="#")


        plot_evolution.setLabel("right", "Pressure/Temp/Voltage/Current", units="units")
        plot_evolution.showAxis('right')
        pen = pg.mkPen(color = "brown", width = 2)

        for key, value in self.telemetry_lines.items():
            try:
                self.telemetry_lines[key] = plot_evolution.plot(self.data[4]['time']/60, self.data[4][key], 
                    pen=pen, name = key)
            except:
                pass

        plot_spectrum.setLogMode(x=True, y=True)
        plot_spectrum.showGrid(x=True, y=True)


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
        data = []
        for i in range(length):
            self.write_byte_data(address, register, i)
            byte = self.read_byte(address)
            data.append(byte)
        return data
        
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

    VID = 0x0403
    PID = 0x6030
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
            # Do ATMEGA se to prepne tak, ze bit[0] a bit[2] maji stejne hodnoty hodnoty
            self.ftdi.write_byte_data(self.addr_switch, 0x01, 0b0000)

    @pyqtSlot()
    def connectSlot(self, state = True, power_off = False):
        print("Connecting to HID device... ", state)
        if state:
            self.dev = hid.device()
            self.dev.open(self.VID, self.PID)
            print("Connected to HID device", self.dev)

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
        r06 = self.ftdi.read_byte_data(self.addr_rtc, 0x06)
        r07 = self.ftdi.read_byte_data(self.addr_rtc, 0x07)

        sec100 = r00
        absdate = datetime.datetime.utcnow()
        sec = ((r01 >> 4) & 0b111) * 10 + (r01 & 0b1111)
        minu= ((r02 >> 4) & 0b111) * 10 + (r02 & 0b1111)
        hourL= ((r03 >> 4) & 0b11) * 10 + (r03 & 0b1111)
        hourM = ((r04 >> 4) & 0b11) * 10 + (r04 & 0b1111)
        hourR = ((r06 >> 4) & 0b1) * 10 + (r06 & 0b1111)

        hour = hourR << 8 | hourM << 4 | hourL
        date = datetime.timedelta(hours=hour, minutes=minu, seconds=sec, milliseconds=sec100*10)
        
        return(absdate, date)

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
                'abs_time': abstime
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


class App(QMainWindow):
    def __init__(self, file_path):
        super().__init__()
        self.left = 100
        self.top = 100
        self.title = 'dosview'
        self.width = 640
        self.height = 400
        self.file_path = file_path
        self.initUI()

    def initUI(self):
        self.setWindowTitle(self.title)
        self.setGeometry(self.left, self.top, self.width, self.height)
        self.setWindowIcon(QIcon('media/icon_ust.png'))
        

        self.plot_canvas = PlotCanvas(self, file_path=self.file_path)
        
        self.properties_tree = QTreeWidget()
        self.properties_tree.setColumnCount(2)
        self.properties_tree.setHeaderLabels(["Property", "Value"])

        self.datalines_tree = QTreeWidget()
        self.datalines_tree.setColumnCount(1)
        self.datalines_tree.setHeaderLabels(["Units"])

        log_view_widget = QWidget()

        self.left_panel = QSplitter(Qt.Vertical)

        self.left_panel.addWidget(self.datalines_tree)
        self.left_panel.addWidget(self.properties_tree)


        self.logView_splitter = QSplitter(Qt.Horizontal)
        self.logView_splitter.addWidget(self.left_panel)
        self.logView_splitter.addWidget(self.plot_canvas)
        self.logView_splitter.setSizes([1, 9])
        sizes = self.logView_splitter.sizes()
        sizes[0] = int(sizes[1] * 0.1)
        self.logView_splitter.setSizes(sizes)

        tab_widget = QTabWidget()
        tab_widget.addTab(self.logView_splitter, "Log View")
        self.airdos_config = AirdosConfigTab()
        tab_widget.addTab(self.airdos_config, "Airdos control")

        tab_widget.setCurrentIndex(0)
        self.setCentralWidget(tab_widget)

        bar = self.menuBar()
        file = bar.addMenu("&File")

        open = QAction("Open",self)
        open.setShortcut("Ctrl+O")
        open.triggered.connect(self.open_new_file)
        
        file.addAction(open)


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


        self.setWindowTitle(f"dosview - {self.file_path}")
        self.start_data_loading()
        self.show()


    def about(self):
        message = QMessageBox.about(self, "About dosview", "dosview is a simple tool to visualize data from Universal Scientific Technologies's")


    def start_data_loading(self):
        self.load_data_thread = LoadDataThread(self.file_path)
        self.load_data_thread.data_loaded.connect(self.on_data_loaded)
        self.load_data_thread.start()

    def on_data_loaded(self, data):
        print("Data are fully loaded...")
        self.plot_canvas.plot(data)
        
        self.properties_tree.clear()

        def add_properties_to_tree(item, properties):
            for key, value in properties.items():
                if isinstance(value, dict):
                    parent_item = QTreeWidgetItem([key])
                    item.addChild(parent_item)
                    add_properties_to_tree(parent_item, value)
                else:
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

    def open_new_file(self, flag):
        print("Open new file")

        dlg = QFileDialog(self, "Projects", options=None)
        dlg.setFileMode(QFileDialog.ExistingFile)

        fn = dlg.getOpenFileName()
        print(fn)

        dlg.deleteLater()
        

def main():
    parser = argparse.ArgumentParser(description='Process some integers.')
    parser.add_argument('file_path', type=str, help='Path to the input file', default=None, nargs='?')
    args = parser.parse_args()

    if not args.file_path:
        pass

    print("...", args.file_path)

    pg.setConfigOption('background', 'w')
    pg.setConfigOption('foreground', 'gray')


    app = QApplication(sys.argv)
    ex = App(args.file_path)
    sys.exit(app.exec_())

if __name__ == '__main__':
    main()