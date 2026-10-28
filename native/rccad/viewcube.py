"""Kostka orientacji w prawym górnym rogu (jak ViewCube w Fusion 360): obraca się razem z kamerą; klik ściany = widok z tej strony,
klik narożnika lub krawędzi = widok izometryczny / ukośny."""
from __future__ import annotations
import itertools
import math
import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPolygonF, QTransform
from PySide6.QtWidgets import QWidget

FACES = {  # nazwa widoku -> (normalna, etykieta)
    'Z': ((0, 0, 1), 'GÓRA'), '-Z': ((0, 0, -1), 'DÓŁ'),
    'X': ((1, 0, 0), 'PRAWO'), '-X': ((-1, 0, 0), 'LEWO'),
    '-Y': ((0, -1, 0), 'PRZÓD'), 'Y': ((0, 1, 0), 'TYŁ'),
}
# wierzchołki ścian (kolejność dookoła; pierwsza krawędź to „dół” napisu)
QUADS = {
    'Z': [(-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1)],
    '-Z': [(-1, 1, -1), (1, 1, -1), (1, -1, -1), (-1, -1, -1)],
    'X': [(1, -1, -1), (1, 1, -1), (1, 1, 1), (1, -1, 1)],
    '-X': [(-1, 1, -1), (-1, -1, -1), (-1, -1, 1), (-1, 1, 1)],
    '-Y': [(-1, -1, -1), (1, -1, -1), (1, -1, 1), (-1, -1, 1)],
    'Y': [(1, 1, -1), (-1, 1, -1), (-1, 1, 1), (1, 1, 1)],
}


class ViewCube(QWidget):
    faceClicked = Signal(str)
    directionClicked = Signal(float, float)   # azymut, elewacja (stopnie)

    def __init__(self, view, parent=None):
        super().__init__(parent)
        self.view = view
        self.setFixedSize(138, 138)
        self.setMouseTracking(True)
        self.hover = None          # ('face', nazwa) | ('corner', wektor) | ('edge', wektor)
        self.setCursor(Qt.PointingHandCursor)

    # ---- rzut: ortograficzny, zgodny z kamerą widoku 3D ----
    def _basis(self):
        az, el = math.radians(float(self.view.opts['azimuth'])), math.radians(float(self.view.opts['elevation']))
        c = np.array([math.cos(el) * math.cos(az), math.cos(el) * math.sin(az), math.sin(el)])
        r = np.array([-math.sin(az), math.cos(az), 0.0])
        u = np.array([-math.sin(el) * math.cos(az), -math.sin(el) * math.sin(az), math.cos(el)])
        return c, r, u

    def _project(self, p):
        c, r, u = self._basis()
        scale = 31.0
        p = np.asarray(p, float)
        return QPointF(self.width() / 2 + float(p @ r) * scale, self.height() / 2 - float(p @ u) * scale), float(p @ c)

    def _visible_faces(self):
        c, _, _ = self._basis()
        out = []
        for name, (n, label) in FACES.items():
            depth = float(np.dot(n, c))
            if depth > 1e-3:
                out.append((depth, name))
        return sorted(out)

    def _hit(self, pos):
        c, _, _ = self._basis()
        best = None
        for sx, sy, sz in itertools.product((-1, 1), repeat=3):
            v = np.array([sx, sy, sz])
            pt, depth = self._project(v)
            if float(v @ c) > 0 and math.hypot(pt.x() - pos.x(), pt.y() - pos.y()) <= 9:
                return ('corner', v)
        for a, b in itertools.combinations(itertools.product((-1, 1), repeat=3), 2):
            if sum(1 for i in range(3) if a[i] != b[i]) != 1:
                continue
            m = (np.array(a) + np.array(b)) / 2.0
            if float(m @ c) > 0.2:
                pt, _ = self._project(m * 1.0)
                if math.hypot(pt.x() - pos.x(), pt.y() - pos.y()) <= 7:
                    return ('edge', m / np.linalg.norm(m))
        for depth, name in reversed(self._visible_faces()):
            poly = QPolygonF([self._project(q)[0] for q in QUADS[name]])
            if poly.containsPoint(QPointF(pos), Qt.OddEvenFill):
                return ('face', name)
        return best

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setBrush(QColor(255, 255, 255, 215))
        p.setPen(QPen(QColor('#cfdbe8'), 1))
        p.drawRoundedRect(QRectF(.5, .5, self.width() - 1, self.height() - 1), 16, 16)
        shade = {'Z': 1.0, '-Z': .78, 'X': .93, '-X': .86, '-Y': .97, 'Y': .82}
        for depth, name in self._visible_faces():
            pts = [self._project(q)[0] for q in QUADS[name]]
            poly = QPolygonF(pts)
            hot = self.hover == ('face', name) if self.hover and self.hover[0] == 'face' else False
            base = QColor('#bcdcff') if hot else QColor.fromHsvF(.585, .07, shade.get(name, .9) * .97)
            p.setBrush(base)
            p.setPen(QPen(QColor('#94abc2'), 1.3))
            p.drawPolygon(poly)
            # napis zgodny z perspektywą ściany
            w, h = 100.0, 100.0
            tr = QTransform()
            if QTransform.quadToQuad(QPolygonF([QPointF(0, h), QPointF(w, h), QPointF(w, 0), QPointF(0, 0)]), poly, tr):
                p.save()
                p.setTransform(tr, True)
                font = QFont('Segoe UI')
                font.setBold(True)
                font.setPixelSize(17)
                p.setFont(font)
                p.setPen(QColor('#e5262b' if False else '#3f607f'))
                p.drawText(QRectF(0, 0, w, h), Qt.AlignCenter, FACES[name][1])
                p.restore()
        if self.hover and self.hover[0] in ('corner', 'edge'):
            pt, _ = self._project(self.hover[1] if self.hover[0] == 'corner' else self.hover[1] * 1.2)
            p.setBrush(QColor('#2f87e8'))
            p.setPen(QPen(QColor('#ffffff'), 2))
            p.drawEllipse(pt, 5.5, 5.5)
        # osie świata w rogu
        for axis, color, label in (((1, 0, 0), '#df5a5e', 'X'), ((0, 1, 0), '#3aa77a', 'Y'), ((0, 0, 1), '#4a8fe0', 'Z')):
            o, _ = self._project((0, 0, 0))
            e, _ = self._project(np.array(axis) * 1.9)
            o = QPointF(14, self.height() - 14)
            e = QPointF(o.x() + (e.x() - self.width() / 2) * .42, o.y() + (e.y() - self.height() / 2) * .42)
            p.setPen(QPen(QColor(color), 2.2, Qt.SolidLine, Qt.RoundCap))
            p.drawLine(o, e)
            font = QFont('Segoe UI')
            font.setBold(True)
            font.setPixelSize(10)
            p.setFont(font)
            p.drawText(QPointF(e.x() + 2, e.y() + 3), label)
        p.end()

    def mouseMoveEvent(self, event):
        hit = self._hit(event.position())
        key = None if hit is None else (hit[0], hit[1] if hit[0] == 'face' else tuple(np.round(hit[1], 3)))
        old = None if self.hover is None else (self.hover[0], self.hover[1] if self.hover[0] == 'face' else tuple(np.round(self.hover[1], 3)))
        if key != old:
            self.hover = hit
            self.update()

    def leaveEvent(self, event):
        self.hover = None
        self.update()

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton:
            return
        hit = self._hit(event.position())
        if hit is None:
            return
        if hit[0] == 'face':
            self.faceClicked.emit(hit[1])
        else:
            d = np.asarray(hit[1], float)
            d /= np.linalg.norm(d)
            self.directionClicked.emit(math.degrees(math.atan2(d[1], d[0])), math.degrees(math.asin(max(-1, min(1, d[2])))))
