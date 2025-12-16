"""Loading dialog with spinner for long-running operations."""
from __future__ import annotations

from typing import Optional

from PyQt5 import QtCore, QtWidgets, QtGui


class LoadingDialog(QtWidgets.QDialog):
    """Modal dialog with spinner animation for blocking operations."""
    
    def __init__(
        self,
        parent: Optional[QtWidgets.QWidget] = None,
        title: str = "Loading",
        message: str = "Please wait..."
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setWindowFlags(
            QtCore.Qt.Dialog |
            QtCore.Qt.CustomizeWindowHint |
            QtCore.Qt.WindowTitleHint
        )
        
        # Remove close button
        self.setWindowFlags(self.windowFlags() & ~QtCore.Qt.WindowCloseButtonHint)
        
        self._build_ui(message)
        self.setFixedSize(300, 120)
        
        # Animation
        self._angle = 0
        self._timer = QtCore.QTimer(self)
        self._timer.timeout.connect(self._rotate)
        
    def _build_ui(self, message: str) -> None:
        layout = QtWidgets.QVBoxLayout(self)
        layout.setSpacing(15)
        
        # Spinner label
        self.spinner_label = QtWidgets.QLabel()
        self.spinner_label.setAlignment(QtCore.Qt.AlignCenter)
        self.spinner_label.setFixedSize(48, 48)
        layout.addWidget(self.spinner_label, alignment=QtCore.Qt.AlignCenter)
        
        # Message label
        self.message_label = QtWidgets.QLabel(message)
        self.message_label.setAlignment(QtCore.Qt.AlignCenter)
        self.message_label.setWordWrap(True)
        font = self.message_label.font()
        font.setPointSize(10)
        self.message_label.setFont(font)
        layout.addWidget(self.message_label)
        
        layout.addStretch(1)
        
    def set_message(self, message: str) -> None:
        """Update the message text."""
        self.message_label.setText(message)
        
    def start(self) -> None:
        """Start spinner animation and show dialog."""
        self._timer.start(50)  # Update every 50ms
        self.show()
        QtWidgets.QApplication.processEvents()
        
    def stop(self) -> None:
        """Stop animation and close dialog."""
        self._timer.stop()
        self.close()
        
    def _rotate(self) -> None:
        """Rotate spinner icon."""
        self._angle = (self._angle + 15) % 360
        
        # Create rotating spinner
        pixmap = QtGui.QPixmap(48, 48)
        pixmap.fill(QtCore.Qt.transparent)
        
        painter = QtGui.QPainter(pixmap)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        painter.translate(24, 24)
        painter.rotate(self._angle)
        
        # Draw spinner arcs
        pen = QtGui.QPen(QtGui.QColor("#4A90E2"))
        pen.setWidth(4)
        pen.setCapStyle(QtCore.Qt.RoundCap)
        painter.setPen(pen)
        
        # Draw 3/4 arc
        painter.drawArc(-18, -18, 36, 36, 0, 270 * 16)
        
        painter.end()
        
        self.spinner_label.setPixmap(pixmap)


class LoadingContext:
    """Context manager for loading dialog."""
    
    def __init__(
        self,
        parent: Optional[QtWidgets.QWidget] = None,
        title: str = "Loading",
        message: str = "Please wait..."
    ):
        self.dialog = LoadingDialog(parent, title, message)
        
    def __enter__(self):
        self.dialog.start()
        return self.dialog
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.dialog.stop()
        return False
