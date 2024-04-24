import sys
import argparse

from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget, QHBoxLayout
from PyQt5.QtWidgets import QFileDialog, QTreeWidget, QTreeWidgetItem, QAction, QSplitter, QTableWidgetItem

from PyQt5.QtGui import QIcon

import pyqtgraph as pg

import pandas as pd
from PyQt5.QtWidgets import QSplitter



from PyQt5.QtCore import *
from PyQt5.QtGui import *
from PyQt5.QtWidgets import *

def parse_file(file_path):

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
        except Exception as e:
            print(e)
            
        df_metadata['time'] = df_metadata['time'] - minimal_time

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
            self.telemetry_lines[key] = plot_evolution.plot(self.data[4]['time']/60, self.data[4][key], 
                    pen=pen, name = key)

        plot_spectrum.setLogMode(x=True, y=True)
        plot_spectrum.showGrid(x=True, y=True)


    def telemetry_toggle(self, key, value):
        if self.telemetry_lines[key] is not None:
            self.telemetry_lines[key].setVisible(value)


class HIDI2CCommunicationThread(QThread):
    connected = pyqtSignal(bool)
    connect = pyqtSignal(bool)

    def __init__(self):
        QThread.__init__(self)
        # Initialize HID communication here

    def run(self):
        # Implement HID communication logic here

        # Connect to HID device
        self.connected.emit(True)
        while 1:
            pass

    @pyqtSlot()
    def connectSlot(self, state):
        print("Connecting to HID device... ", state)
        
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
        self.i2c_thread.start()

        #self.uart_thread = HIDUARTCommunicationThread().start()
        #self.mass_thread = USBStorageMonitoringThread().start()

        return self.initUI()
    
    def on_i2c_connected(self, connected: bool = True):
        self.i2c_connect_button.setEnabled(not connected)
        self.i2c_disconnect_button.setEnabled(connected)

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

    def initUI(self):
        splitter = QSplitter(Qt.Horizontal)
        
        i2c_widget = QGroupBox("I2C")
        i2c_layout = QVBoxLayout()        
        i2c_layout.setAlignment(Qt.AlignTop)
        i2c_widget.setLayout(i2c_layout)

        self.i2c_connect_button = QPushButton("Connect")
        self.i2c_disconnect_button = QPushButton("Disconnect")
        self.i2c_connect_button.clicked.connect(lambda: self.i2c_thread.connect(True))
        self.i2c_disconnect_button.clicked.connect(lambda: self.i2c_thread.connect(False)) 
        
        i2c_layout.addWidget(self.i2c_connect_button)
        i2c_layout.addWidget(self.i2c_disconnect_button)
        

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