import sys
import argparse
from PyQt5.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT as NavigationToolbar
from PyQt5.QtWidgets import QFileDialog
import random
import csv
from matplotlib.figure import Figure
from threading import Thread

import matplotlib.pyplot as plt
import pandas as pd
from PyQt5.QtGui import QIcon

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





class PlotCanvas(FigureCanvas):
    def __init__(self, parent=None, width=5, height=4, dpi=100, file_path=None):
        fig = Figure(figsize=(width, height), dpi=dpi)
        self.axes = fig.add_subplot(211)
        FigureCanvas.__init__(self, fig)
        self.setParent(parent)
        self.data = []
        self.file_path = file_path
        Thread(target=self.load_data).start()

    def load_data(self):
        self.data = parse_file(self.file_path)
        self.plot()

    def plot(self):
        self.axes.clear()  # Clear previous plot

        self.axes.plot(self.data[0]/60.0, self.data[1], 'r.', alpha=0.2)
        self.axes.figure.canvas.draw()
        
        window_size = 20  # Define the size of the window for the moving average
        rolling_avg = self.data[1].rolling(window=window_size).mean()
        self.axes.plot(self.data[0]/60.0, rolling_avg, 'r-', lw=2)

        self.axes.set_xlabel('Time (min)')
        self.axes.set_ylabel('Count (total)')
        
        self.axes2 = self.figure.add_subplot(212)  # Add second subplot
        self.axes2.clear()  # Clear previous plot
        self.axes2.plot(self.data[2], 'b.-', alpha=0.3)

        self.axes2.set_yscale('log')
        self.axes2.set_xscale('log')

        self.axes2.set_xlabel('Channel')
        self.axes2.set_ylabel('Count')


        self.axes.grid()
        self.axes2.grid()

        self.axes.figure.canvas.draw()

        self.figure.tight_layout()
        self.axes.figure.tight_layout()


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
        
        # Set the window icon
        self.setWindowIcon(QIcon('media/icon_ust.png'))

        m = PlotCanvas(self, width=5, height=4, file_path=self.file_path)
        self.setCentralWidget(m)
        m.move(0,0)

        # Add navigation toolbar
        self.addToolBar(NavigationToolbar(m, self))
        
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

    app = QApplication(sys.argv)
    ex = App(args.file_path)
    sys.exit(app.exec_())

if __name__ == '__main__':
    main()