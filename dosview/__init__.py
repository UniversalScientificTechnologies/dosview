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
        metadata['log_info']['log_version'] = '1.0'
        metadata['log_info']['internal_time_min'] = df_spectrum['time'].min()
        metadata['log_info']['internal_time_max'] = df_spectrum['time'].max()
        metadata['log_info']['log_duration'] = float(duration)
        metadata['log_info']['spectral_count'] = df_spectrum.shape[0]
        metadata['log_info']['channels'] = df_spectrum.shape[1] - 1
        metadata['log_info']['types'] = data_types

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

    def plot(self, data):

        self.data = data
        window_size = 20

        self.clear()
        plot_evolution = self.addPlot(row=0, col=0)
        plot_spectrum = self.addPlot(row=1, col=0)

        plot_evolution.showGrid(x=True, y=True)
        plot_evolution.setLabel("left",  "Total count per exposion", units="Counts per exposition")
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
        plot_spectrum.setLabel("left", "Total count per channel", units="counts")
        plot_spectrum.setLabel("bottom", "Channel", units="#")


        pen = pg.mkPen(color = "brown", width = 2)
        plot_evolution.plot(self.data[4]['time']/60, self.data[4]['pressure_3'], 
                        pen=pen, name = "Pressure")
        plot_evolution.plot(self.data[4]['time']/60, self.data[4]['temperature_0'], 
                        pen=pen, name = "Temp")
        plot_evolution.plot(self.data[4]['time']/60, self.data[4]['voltage'], 
                        pen=pen, name = "Pressure")
        plot_evolution.plot(self.data[4]['time']/60, self.data[4]['current'], 
                        pen=pen, name = "Pressure")

        plot_spectrum.setLogMode(x=True, y=True)
        plot_spectrum.showGrid(x=True, y=True)


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
        
        hl = QHBoxLayout()
        left_column = QVBoxLayout() 

        self.plot_canvas = PlotCanvas(self, file_path=self.file_path)
        
        self.properties_tree = QTreeWidget()
        self.properties_tree.setColumnCount(2)
        self.properties_tree.setHeaderLabels(["Property", "Value"])

        central_widget = QWidget()

        self.left_panel = QSplitter(Qt.Vertical)
        self.left_panel.addWidget(self.properties_tree)


        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.addWidget(self.left_panel)
        self.splitter.addWidget(self.plot_canvas)
        self.splitter.setSizes([1, 9])
        hl.addWidget(self.splitter)

        central_widget.setLayout(hl)
        self.setCentralWidget(central_widget)

        bar = self.menuBar()
        file = bar.addMenu("&File")

        open = QAction("Open",self)
        open.setShortcut("Ctrl+O")
        open.triggered.connect(self.open_new_file)
        
        file.addAction(open)

        self.setWindowTitle(f"dosview - {self.file_path}")

        self.start_data_loading()
        
        self.show()



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

        self.properties_tree.expandAll()
        self.splitter.setSizes([10, 90])


    def open_new_file(self, flag):
        print("Open new file")

        dlg = QFileDialog(self, "Projects", options=None)
        dlg.setFileMode(QFileDialog.ExistingFile)

        fn = dlg.getOpenFileName()
        print(fn)

        dlg.deleteLater()
        

def main():
    parser = argparse.ArgumentParser(description='Process some integers.')
    parser.add_argument('file_path', type=str, help='Path to the input file', default=None)
    args = parser.parse_args()

    if not args.file_path:
        pass

    pg.setConfigOption('background', 'w')
    pg.setConfigOption('foreground', 'gray')


    app = QApplication(sys.argv)
    ex = App(args.file_path)
    sys.exit(app.exec_())

if __name__ == '__main__':
    main()