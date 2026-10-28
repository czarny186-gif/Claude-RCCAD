"""Ekran startowy z kręcącym się kółkiem: widoczny od razu, gdy ładują się ciężkie biblioteki (CadQuery / OpenCascade)."""
from __future__ import annotations
import threading
import time
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QConicalGradient, QFont, QLinearGradient, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QWidget


class Splash(QWidget):
    """Ekran startowy 380x300 renderowany w pełnej rozdzielczości ekranu (devicePixelRatio) - ostry także na HiDPI."""

    def __init__(self, icon_path=''):
        super().__init__(None, Qt.SplashScreen | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(380, 300)
        self.icon_path = icon_path
        self._icon = None
        self.text = 'Uruchamianie…'
        self.t0 = time.monotonic()
        screen = self.screen().availableGeometry() if self.screen() else None
        if screen:
            self.move(screen.center().x() - self.width() // 2, screen.center().y() - self.height() // 2)

    def _icon_pixmap(self):
        dpr = max(1.0, float(self.devicePixelRatioF()))
        if self._icon is None or self._icon[0] != dpr:
            pm = QPixmap(self.icon_path) if self.icon_path else QPixmap()
            if not pm.isNull():
                pm = pm.scaled(int(104 * dpr), int(104 * dpr), Qt.KeepAspectRatio, Qt.SmoothTransformation)
                pm.setDevicePixelRatio(dpr)
            self._icon = (dpr, pm)
        return self._icon[1]

    def set_text(self, text):
        self.text = text
        self.repaint()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform | QPainter.TextAntialiasing)
        w, h = self.width(), self.height()
        # miękki cień i tło z delikatnym gradientem
        for i, a in enumerate((10, 16, 24)):
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(20, 50, 90, a))
            p.drawRoundedRect(QRectF(2 + i * 2, 4 + i * 2, w - 4 - i * 4, h - 6 - i * 4), 24 - i * 2, 24 - i * 2)
        bg = QLinearGradient(0, 0, 0, h)
        bg.setColorAt(0, QColor('#ffffff'))
        bg.setColorAt(1, QColor('#e9f2fc'))
        p.setBrush(bg)
        p.setPen(QPen(QColor('#d3e1f0'), 1))
        p.drawRoundedRect(QRectF(7, 7, w - 14, h - 14), 20, 20)
        icon = self._icon_pixmap()
        if icon is not None and not icon.isNull():
            p.drawPixmap(int((w - 104) / 2), 26, icon)
        font = QFont('Segoe UI')
        font.setBold(True)
        font.setPixelSize(26)
        font.setLetterSpacing(QFont.AbsoluteSpacing, 3)
        p.setFont(font)
        p.setPen(QColor('#17314a'))
        p.drawText(QRectF(0, 138, w, 36), Qt.AlignCenter, 'RCCAD')
        font = QFont('Segoe UI')
        font.setPixelSize(12)
        p.setFont(font)
        p.setPen(QColor('#7b93a8'))
        p.drawText(QRectF(0, 172, w, 18), Qt.AlignCenter, 'Modelowanie 3D')
        # kręcące się kółko z gradientowym ogonem
        angle = ((time.monotonic() - self.t0) * 400) % 360
        cx, cy, r = w / 2, 222, 15
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor('#dde8f4'), 4))
        p.drawEllipse(QRectF(cx - r, cy - r, 2 * r, 2 * r))
        cone = QConicalGradient(cx, cy, -angle)
        cone.setColorAt(0, QColor('#2f87e8'))
        cone.setColorAt(.28, QColor(47, 135, 232, 0))
        cone.setColorAt(1, QColor(47, 135, 232, 0))
        pen = QPen(QBrush(cone), 4)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        p.drawEllipse(QRectF(cx - r, cy - r, 2 * r, 2 * r))
        font.setPixelSize(12)
        p.setFont(font)
        p.setPen(QColor('#6c869b'))
        p.drawText(QRectF(0, 252, w, 20), Qt.AlignCenter, self.text)
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
