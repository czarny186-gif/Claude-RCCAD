"""Ekran startowy z kręcącym się kółkiem: widoczny od razu, gdy ładują się ciężkie biblioteki (CadQuery / OpenCascade)."""
from __future__ import annotations
import threading
import time
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QWidget


class Splash(QWidget):
    def __init__(self, icon_path=''):
        super().__init__(None, Qt.SplashScreen | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(380, 300)
        self.icon = QPixmap(icon_path).scaled(96, 96, Qt.KeepAspectRatio, Qt.SmoothTransformation) if icon_path else QPixmap()
        self.text = 'Uruchamianie…'
        self.t0 = time.monotonic()
        screen = self.screen().availableGeometry() if self.screen() else None
        if screen:
            self.move(screen.center().x() - self.width() // 2, screen.center().y() - self.height() // 2)

    def set_text(self, text):
        self.text = text
        self.repaint()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(QColor('#cfdbe8'), 1))
        p.setBrush(QColor('#ffffff'))
        p.drawRoundedRect(QRectF(.5, .5, self.width() - 1, self.height() - 1), 20, 20)
        if not self.icon.isNull():
            p.drawPixmap((self.width() - 96) // 2, 28, self.icon)
        font = QFont('Segoe UI')
        font.setBold(True)
        font.setPixelSize(22)
        p.setFont(font)
        p.setPen(QColor('#17314a'))
        p.drawText(QRectF(0, 134, self.width(), 32), Qt.AlignCenter, 'RCCAD')
        font.setBold(False)
        font.setPixelSize(13)
        p.setFont(font)
        p.setPen(QColor('#6c869b'))
        p.drawText(QRectF(0, 242, self.width(), 24), Qt.AlignCenter, self.text)
        # kręcące się kółko
        angle = int(((time.monotonic() - self.t0) * 360 * 1.3) % 360)
        rect = QRectF(self.width() / 2 - 20, 182, 40, 40)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor('#e3ecf6'), 5))
        p.drawEllipse(rect)
        pen = QPen(QColor('#2f87e8'), 5)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        p.drawArc(rect, -angle * 16, -100 * 16)
        p.end()


def run_with_splash(app, splash, build):
    """Ładuje moduły w wątku (kółko wciąż się kręci), potem tworzy okno w wątku GUI."""
    state = {}

    def load():
        try:
            import cadquery  # noqa: F401
            from rccad import kernel, studio  # noqa: F401
        except Exception as exc:  # błąd zgłosi build()
            state['error'] = exc
        state['done'] = True

    worker = threading.Thread(target=load, daemon=True)
    worker.start()
    while not state.get('done'):
        splash.repaint()
        app.processEvents()
        time.sleep(.016)
    splash.set_text('Tworzenie okna…')
    app.processEvents()
    window = build()
    return window
