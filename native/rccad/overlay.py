"""Pływające elementy nad widokiem 3D - jak w wersji HTML: kostka widoku, cofnij/ponów, dom, przesuwanie i obrót."""
from __future__ import annotations
from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QPushButton

AXIS_COLORS = {'Z': '#3b82f6', '-Z': '#3b82f6', 'X': '#e5484d', '-X': '#e5484d', 'Y': '#22a06b', '-Y': '#22a06b', '3D': '#050505'}
MARGIN = 14


def _round(text, color=None, size=34, tip=''):
    button = QPushButton(text)
    button.setFixedSize(size, size)
    button.setCursor(Qt.PointingHandCursor)
    button.setToolTip(tip)
    if color:
        button.setStyleSheet(f"QPushButton {{background:{color}; color:white; border:2px solid white; border-radius:{size // 2}px; font-weight:700; padding:0;}}"
                             f"QPushButton:hover {{border-color:#050505;}}")
    else:
        button.setStyleSheet(f"QPushButton {{background:white; color:#2c4062; border:1px solid #cfd9e6; border-radius:{size // 2}px; font-size:15px; padding:0;}}"
                             "QPushButton:hover {background:#e8f0fb;} QPushButton:disabled {color:#b8c4d3;} QPushButton:checked {background:#2c4062; color:white;}")
    return button


class ViewOverlay(QObject):
    def __init__(self, view, window):
        super().__init__(view)
        self.view, self.window = view, window
        frame_style = "QFrame#floating {background:white; border:1px solid #dde5ef; border-radius:12px;}"
        self.cube = QFrame(view)
        self.cube.setObjectName('floating')
        self.cube.setStyleSheet(frame_style)
        grid = QGridLayout(self.cube)
        grid.setContentsMargins(8, 8, 8, 8)
        grid.setSpacing(5)
        layout = {'Z': (0, 1), '-X': (1, 0), '3D': (1, 1), 'X': (1, 2), '-Y': (2, 0), '-Z': (2, 1), 'Y': (2, 2)}
        self.cube_buttons = {}
        for name, (row, col) in layout.items():
            button = _round(name, AXIS_COLORS[name], 34, 'Widok izometryczny' if name == '3D' else f'Widok z kierunku {name}')
            button.clicked.connect(lambda checked=False, n=name: view.set_view('iso' if n == '3D' else n))
            grid.addWidget(button, row, col)
            self.cube_buttons[name] = button
        self.history = QFrame(view)
        history = QHBoxLayout(self.history)
        history.setContentsMargins(0, 0, 0, 0)
        history.setSpacing(8)
        self.undo = _round('↶', tip='Cofnij (Ctrl+Z)', size=38)
        self.redo = _round('↷', tip='Ponów (Ctrl+Y)', size=38)
        self.home = _round('⌂', tip='Dopasuj widok do modelu', size=38)
        self.undo.clicked.connect(window.undo)
        self.redo.clicked.connect(window.redo)
        self.home.clicked.connect(lambda: (view.set_view('iso'), view.fit_all()))
        for button in (self.undo, self.redo, self.home):
            history.addWidget(button)
        self.pad = QFrame(view)
        self.pad.setObjectName('floating')
        self.pad.setStyleSheet(frame_style)
        pad = QHBoxLayout(self.pad)
        pad.setContentsMargins(8, 8, 8, 8)
        pad.setSpacing(8)
        self.pan = _round('✥', tip='Przesuwaj widok (lub prawy przycisk / Shift + przeciąganie)', size=40)
        self.orbit = _round('⟳', tip='Obracaj widok', size=40)
        for button, mode in ((self.pan, 'pan'), (self.orbit, 'orbit')):
            button.setCheckable(True)
            button.clicked.connect(lambda checked, m=mode: window.set_mouse_mode(m if checked else 'select'))
            pad.addWidget(button)
        for widget in (self.cube, self.history, self.pad):
            widget.show()
            widget.raise_()
        view.installEventFilter(self)
        self.reposition()

    def sync_mode(self, mode):
        self.pan.setChecked(mode == 'pan')
        self.orbit.setChecked(mode == 'orbit')

    def sync_history(self, can_undo, can_redo):
        self.undo.setEnabled(can_undo)
        self.redo.setEnabled(can_redo)

    def reposition(self):
        w, h = self.view.width(), self.view.height()
        for widget in (self.cube, self.history, self.pad):
            widget.adjustSize()
        self.cube.move(w - self.cube.width() - MARGIN, MARGIN)
        self.history.move(self.cube.x() - self.history.width() - 10, MARGIN + 4)
        self.pad.move((w - self.pad.width()) // 2, h - self.pad.height() - MARGIN)

    def eventFilter(self, obj, event):
        if obj is self.view and event.type() in (QEvent.Resize, QEvent.Show):
            self.reposition()
        return False
