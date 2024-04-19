import sys
import argparse

from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget, QHBoxLayout
from PyQt5.QtWidgets import QFileDialog
from PyQt5.QtGui import QIcon

import pyqtgraph as pg

import pandas as pd



def parse_file(file_path):

        metadata = {}
        max_size = 0

        with open(file_path, 'r') as file:
            for line in file:
                parts_size = len(line.split(","))
                if parts_size > max_size: max_size = parts_size

        df_log = pd.read_csv(file_path, sep = ',', header = None, names=range(max_size), low_memory=False)
        data_types = df_log[0].unique().tolist()

        df_spectrum = df_log [df_log[0] == '$HIST'] 
        df_spectrum = df_spectrum.drop(columns=[0, 1, 3, 4, 5, 6, 7])

        new_columns = ['time'] + list(range(df_spectrum.shape[1] - 1))
        df_spectrum.columns = new_columns

        df_spectrum['time'] = df_spectrum['time'].astype(float)
        duration = df_spectrum['time'].max() - df_spectrum['time'].min()

        metadata['log_info'] = {}
        metadata['log_info']['internal_time_min'] = df_spectrum['time'].min()
        metadata['log_info']['internal_time_max'] = df_spectrum['time'].max()
        metadata['log_info']['log_duration'] = float(duration)
        metadata['log_info']['spectral_count'] = df_spectrum.shape[0]
        metadata['log_info']['channels'] = df_spectrum.shape[1] - 1 # remove time column
        metadata['log_info']['types'] = data_types

        df_spectrum['time'] = df_spectrum['time'] - df_spectrum['time'].min()

        sums = df_spectrum.drop('time', axis=1).sum(axis=1) #.div(total_time)

        hist = df_spectrum.drop('time', axis=1).sum(axis=0)

        return [df_spectrum['time'], sums, hist]

class LoadDataThread(QThread):
    data_loaded = pyqtSignal(list)

    def __init__(self, file_path):
        QThread.__init__(self)
        self.file_path = file_path

    def run(self):
        data = parse_file(self.file_path)
        self.data_loaded.emit(data)

class PlotCanvas(pg.GraphicsLayoutWidget):
    def __init__(self, parent=None, width=5, height=4, dpi=100, file_path=None):
        print("PLOT CANVAS INIT")
        super().__init__(parent)
        self.data = []
        self.file_path = file_path
        print("LOADING DATA ....    ")
        self.load_data_thread = LoadDataThread(self.file_path)
        self.load_data_thread.data_loaded.connect(self.on_data_loaded)
        self.load_data_thread.start()
        print("DONE")

    def on_data_loaded(self, data):
        self.data = data
        self.plot()

    def plot(self):

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
        left_column = QHBoxLayout() 

        m = PlotCanvas(self, width=5, height=4, file_path=self.file_path)
        

        hl.addLayout(left_column, stretch=90)
        hl.addWidget(m)

        #self.setCentralWidget()
        self.setCentralWidget(m)
        #self.setLayout(hl)
        #m.move(0,0)

        #self.addToolBar()
        
        self.show()


def main():
    parser = argparse.ArgumentParser(description='Process some integers.')
    parser.add_argument('file_path', type=str, help='Path to the input file', default=None)
    args = parser.parse_args()

    if not args.file_path:
        print("Please provide a file path")
        file_dialog = QFileDialog()
        file_path, _ = file_dialog.getOpenFileName()
        if not file_path:
            print("No file selected")
            sys.exit()
        else:
            args.file_path = file_path

    pg.setConfigOption('background', 'w')
    pg.setConfigOption('foreground', 'gray')


    app = QApplication(sys.argv)
    ex = App(args.file_path)
    sys.exit(app.exec_())

if __name__ == '__main__':
    main()