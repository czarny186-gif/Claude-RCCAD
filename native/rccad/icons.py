"""Ikony operacji rysowane wektorowo (QPainter) — kolorowe, czytelne piktogramy w panelach narzędzi."""
from __future__ import annotations
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QPainter, QPainterPath, QPen, QPixmap, QPolygonF

BLUE = '#2f87e8'
BLUE_SOFT = '#cfe4fb'
ORANGE = '#f09a22'
GREEN = '#2fa56d'
RED = '#e5484d'
INK = '#40586f'
PALE = '#e6edf5'


def _rounded(x, y, w, h, r=4):
    path = QPainterPath()
    path.addRoundedRect(QRectF(x, y, w, h), r, r)
    return path


def _circle(cx, cy, r):
    path = QPainterPath()
    path.addEllipse(QPointF(cx, cy), r, r)
    return path


def pixmap(kind: str, size: int = 38, scale: int = 2) -> QPixmap:
    S = 48.0
    pm = QPixmap(size * scale, size * scale)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.scale(size * scale / S, size * scale / S)
    pen = lambda c, w=2.2: QPen(QColor(c), w, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    fill = lambda path, c, edge=INK: (p.setBrush(QColor(c)), p.setPen(pen(edge)), p.drawPath(path))
    a, b = _rounded(7, 11, 24, 24), _rounded(17, 17, 24, 24)
    ca, cb = _circle(19, 24, 12), _circle(30, 24, 12)
    if kind == 'new':
        fill(_rounded(9, 13, 26, 26), BLUE_SOFT, BLUE)
        p.setPen(pen(BLUE, 2.6)); p.drawLine(QPointF(38, 8), QPointF(38, 22)); p.drawLine(QPointF(31, 15), QPointF(45, 15))
    elif kind in ('join', 'union'):
        path = (ca.united(cb)) if kind == 'union' else (a.united(b))
        fill(path, BLUE_SOFT, BLUE)
    elif kind in ('cut', 'subtract'):
        base, tool = (a, b) if kind == 'cut' else (ca, cb)
        fill(base.subtracted(tool), BLUE_SOFT, BLUE)
        p.setBrush(Qt.NoBrush); pn = pen(ORANGE, 1.8); pn.setStyle(Qt.DashLine); p.setPen(pn); p.drawPath(tool)
    elif kind in ('intersect', 'common'):
        base, tool = (a, b) if kind == 'intersect' else (ca, cb)
        p.setBrush(Qt.NoBrush); p.setPen(pen('#9fb4c8', 1.8)); p.drawPath(base); p.drawPath(tool)
        fill(base.intersected(tool), BLUE, BLUE)
    elif kind in ('one', 'sym', 'two'):
        fill(_rounded(15, 20, 18, 8, 2), BLUE_SOFT, BLUE)
        p.setPen(pen(ORANGE, 2.6))
        if kind in ('one', 'sym', 'two'):
            p.drawLine(QPointF(24, 20), QPointF(24, 6)); p.drawPolyline(QPolygonF([QPointF(19, 11), QPointF(24, 5), QPointF(29, 11)]))
        if kind in ('sym', 'two'):
            p.setPen(pen(BLUE if kind == 'two' else ORANGE, 2.6))
            p.drawLine(QPointF(24, 28), QPointF(24, 42)); p.drawPolyline(QPolygonF([QPointF(19, 37), QPointF(24, 43), QPointF(29, 37)]))
    elif kind == 'fillet':
        path = QPainterPath(); path.moveTo(10, 8); path.lineTo(10, 40); path.lineTo(38, 40); path.lineTo(38, 30)
        path.lineTo(28, 30); path.quadTo(20, 30, 20, 22); path.lineTo(20, 8); path.closeSubpath()
        fill(path, BLUE_SOFT, BLUE)
        p.setBrush(Qt.NoBrush); p.setPen(pen(GREEN, 2.4)); p.drawArc(QRectF(12, 22, 16, 16), 90 * 16, 90 * 16)
    elif kind == 'chamfer':
        path = QPainterPath(); path.moveTo(10, 8); path.lineTo(10, 40); path.lineTo(38, 40); path.lineTo(38, 30)
        path.lineTo(30, 30); path.lineTo(20, 22); path.lineTo(20, 8); path.closeSubpath()
        fill(path, BLUE_SOFT, BLUE)
        p.setPen(pen(ORANGE, 2.4)); p.drawLine(QPointF(20, 22), QPointF(30, 30))
    elif kind == 'mirror':
        tri = QPolygonF([QPointF(8, 38), QPointF(8, 10), QPointF(21, 38)])
        mir = QPolygonF([QPointF(40, 38), QPointF(40, 10), QPointF(27, 38)])
        p.setBrush(QColor(BLUE_SOFT)); p.setPen(pen(BLUE)); p.drawPolygon(tri)
        p.setBrush(QColor('#d6f1e3')); p.setPen(pen(GREEN)); p.drawPolygon(mir)
        pn = pen(ORANGE, 2); pn.setStyle(Qt.DashLine); p.setPen(pn); p.drawLine(QPointF(24, 5), QPointF(24, 43))
    elif kind == 'sketch':
        p.setBrush(QColor(BLUE_SOFT)); p.setPen(pen(BLUE)); p.drawRoundedRect(QRectF(8, 14, 28, 22), 3, 3)
        p.setPen(pen(ORANGE, 2.8)); p.drawLine(QPointF(30, 12), QPointF(42, 24))
        p.setBrush(QColor(ORANGE)); p.drawPolygon(QPolygonF([QPointF(28, 14), QPointF(26, 21), QPointF(34, 18)]))
    elif kind in ('f_new', 'f_save', 'f_saveas', 'f_open', 'f_import', 'f_export'):
        if kind == 'f_new':
            page = QPainterPath(); page.moveTo(12, 6); page.lineTo(29, 6); page.lineTo(37, 14); page.lineTo(37, 42); page.lineTo(12, 42); page.closeSubpath()
            fill(page, '#ffffff', INK)
            p.setPen(pen(INK, 2)); p.drawPolyline(QPolygonF([QPointF(29, 6), QPointF(29, 14), QPointF(37, 14)]))
            p.setPen(pen(BLUE, 3)); p.drawLine(QPointF(24.5, 22), QPointF(24.5, 36)); p.drawLine(QPointF(17.5, 29), QPointF(31.5, 29))
        elif kind in ('f_save', 'f_saveas'):
            body = QPainterPath(); body.moveTo(8, 8); body.lineTo(34, 8); body.lineTo(41, 15); body.lineTo(41, 41); body.lineTo(8, 41); body.closeSubpath()
            fill(body, BLUE_SOFT, BLUE)
            fill(_rounded(14, 8, 18, 10, 1.5), '#ffffff', BLUE)
            fill(_rounded(13, 26, 22, 15, 2), '#ffffff', BLUE)
            if kind == 'f_saveas':
                p.setPen(pen(ORANGE, 3)); p.drawLine(QPointF(30, 44), QPointF(44, 30))
                p.setBrush(QColor(ORANGE)); p.setPen(Qt.NoPen); p.drawPolygon(QPolygonF([QPointF(28, 46), QPointF(29, 40), QPointF(34, 45)]))
        elif kind == 'f_open':
            back = QPainterPath(); back.moveTo(5, 12); back.lineTo(18, 12); back.lineTo(22, 17); back.lineTo(40, 17); back.lineTo(40, 40); back.lineTo(5, 40); back.closeSubpath()
            fill(back, BLUE_SOFT, BLUE)
            front = QPainterPath(); front.moveTo(5, 40); front.lineTo(11, 23); front.lineTo(45, 23); front.lineTo(39, 40); front.closeSubpath()
            fill(front, '#ffffff', BLUE)
        else:
            up = kind == 'f_export'
            tray = QPainterPath(); tray.moveTo(7, 30); tray.lineTo(7, 41); tray.lineTo(41, 41); tray.lineTo(41, 30)
            p.setBrush(Qt.NoBrush); p.setPen(pen(BLUE, 2.6)); p.drawPath(tray)
            p.setPen(pen(ORANGE if up else GREEN, 3))
            if up:
                p.drawLine(QPointF(24, 32), QPointF(24, 8)); p.drawPolyline(QPolygonF([QPointF(15, 17), QPointF(24, 8), QPointF(33, 17)]))
            else:
                p.drawLine(QPointF(24, 8), QPointF(24, 32)); p.drawPolyline(QPolygonF([QPointF(15, 23), QPointF(24, 32), QPointF(33, 23)]))
    elif kind.startswith('v_'):
        dot = lambda x, y, c=ORANGE: (p.setBrush(QColor(c)), p.setPen(Qt.NoPen), p.drawEllipse(QPointF(x, y), 3.2, 3.2))
        thin = lambda c=BLUE, w=2.2: (p.setBrush(Qt.NoBrush), p.setPen(pen(c, w)))
        if kind == 'v_rect2':
            fill(_rounded(8, 12, 32, 24, 2), BLUE_SOFT, BLUE); dot(8, 12); dot(40, 36)
        elif kind == 'v_rectC':
            fill(_rounded(8, 12, 32, 24, 2), BLUE_SOFT, BLUE); thin(ORANGE, 1.8); p.drawLine(QPointF(24, 24), QPointF(40, 12)); dot(24, 24, GREEN); dot(40, 12)
        elif kind == 'v_rect3':
            poly = QPolygonF([QPointF(6, 30), QPointF(26, 12), QPointF(42, 24), QPointF(22, 42)])
            p.setBrush(QColor(BLUE_SOFT)); p.setPen(pen(BLUE)); p.drawPolygon(poly); dot(6, 30); dot(26, 12); dot(22, 42)
        elif kind == 'v_circle':
            fill(_circle(24, 24, 15), BLUE_SOFT, BLUE); thin(ORANGE, 1.8); p.drawLine(QPointF(24, 24), QPointF(39, 24)); dot(24, 24, GREEN); dot(39, 24)
        elif kind == 'v_circle2':
            fill(_circle(24, 24, 15), BLUE_SOFT, BLUE); thin(ORANGE, 1.8); p.drawLine(QPointF(9, 24), QPointF(39, 24)); dot(9, 24); dot(39, 24)
        elif kind == 'v_circle3':
            fill(_circle(24, 24, 15), BLUE_SOFT, BLUE); dot(24, 9); dot(10.8, 31.5); dot(37.2, 31.5)
        elif kind == 'v_tan':
            thin(INK, 2.4); p.drawLine(QPointF(6, 42), QPointF(42, 42)); p.drawLine(QPointF(6, 42), QPointF(6, 6))
            fill(_circle(22, 26, 16), BLUE_SOFT, BLUE); dot(6, 26, GREEN); dot(22, 42, GREEN)
    elif kind == 'check':
        p.setPen(pen('#ffffff', 4)); p.drawPolyline(QPolygonF([QPointF(11, 25), QPointF(21, 35), QPointF(38, 14)]))
    p.end()
    pm.setDevicePixelRatio(scale)
    return pm


def badge(kind: str, color: str = BLUE, size: int = 34) -> QPixmap:
    """Okrągła plakietka z ikoną (nagłówek panelu)."""
    scale = 2
    pm = QPixmap(size * scale, size * scale)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QColor(color)); p.setPen(Qt.NoPen)
    p.drawRoundedRect(QRectF(0, 0, size * scale, size * scale), 10 * scale, 10 * scale)
    p.end()
    inner = pixmap(kind, size - 6, scale)
    q = QPainter(pm)
    q.drawPixmap(3 * scale, 3 * scale, inner)
    q.end()
    pm.setDevicePixelRatio(scale)
    return pm
