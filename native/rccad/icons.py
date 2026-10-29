"""Ikony operacji rysowane wektorowo (QPainter) — kolorowe, czytelne piktogramy w panelach narzędzi."""
from __future__ import annotations
import math
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
    elif kind == 'x_text':
        p.setPen(pen(INK, 4.6)); p.drawLine(QPointF(10, 11), QPointF(34, 11)); p.drawLine(QPointF(22, 11), QPointF(22, 36))
        p.setPen(pen(BLUE, 2.4)); p.drawLine(QPointF(35, 20), QPointF(35, 36)); p.drawLine(QPointF(32, 20), QPointF(38, 20)); p.drawLine(QPointF(32, 36), QPointF(38, 36))
        p.setPen(pen(ORANGE, 3.2)); p.drawLine(QPointF(12, 42), QPointF(32, 42))
    elif kind == 'x_surface':
        p.setBrush(QColor(BLUE_SOFT)); p.setPen(pen(BLUE, 2.2))
        p.drawPolygon(QPolygonF([QPointF(4, 34), QPointF(16, 18), QPointF(42, 18), QPointF(30, 34)]))
        p.setBrush(QColor(ORANGE)); p.setPen(pen('#ffffff', 1.6))
        p.drawPolygon(QPolygonF([QPointF(26, 20), QPointF(26, 40), QPointF(31.5, 34.5), QPointF(35.5, 44), QPointF(39, 42.4), QPointF(35, 33), QPointF(42, 32.5)]))
    elif kind == 'x_area':
        pn = pen(BLUE, 2.2); pn.setStyle(Qt.DashLine); p.setPen(pn); p.setBrush(QColor(207, 228, 251, 150))
        p.drawRect(QRectF(9, 13, 30, 22))
        p.setBrush(QColor('#ffffff')); p.setPen(pen(BLUE, 2.2))
        for cx, cy in ((9, 13), (39, 13), (9, 35), (39, 35)):
            p.drawRect(QRectF(cx - 3.2, cy - 3.2, 6.4, 6.4))
        p.setPen(pen(ORANGE, 3.0)); p.drawLine(QPointF(15, 19), QPointF(31, 29))
        p.setBrush(QColor(ORANGE)); p.setPen(Qt.NoPen); p.drawPolygon(QPolygonF([QPointF(34, 31), QPointF(26, 31), QPointF(31, 24)]))
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
    elif kind.startswith('t_'):
        name = kind[2:]
        white = name.endswith('_w')
        name = name[:-2] if white else name
        ink = '#ffffff' if white else '#324c68'
        acc = '#ffb54d' if white else ORANGE
        soft = (QColor(255, 255, 255, 46) if white else QColor('#dbe9f8'))
        st = lambda c=ink, w=2.6: (p.setBrush(Qt.NoBrush), p.setPen(pen(c, w)))
        fl = lambda path, c, edge=ink, w=2.6: (p.setBrush(c if isinstance(c, QColor) else QColor(c)), p.setPen(pen(edge, w)), p.drawPath(path))
        poly = lambda pts: QPolygonF([QPointF(*q) for q in pts])
        if name == 'file':
            body = QPainterPath(); body.moveTo(8, 8); body.lineTo(34, 8); body.lineTo(41, 15); body.lineTo(41, 41); body.lineTo(8, 41); body.closeSubpath()
            fl(body, soft)
            fl(_rounded(14, 8, 17, 10, 1.5), QColor(acc), ink, 2.2)
            fl(_rounded(13, 26, 22, 15, 2), QColor(0, 0, 0, 0), ink, 2.4)
        elif name == 'sketch':
            fl(_rounded(7, 18, 26, 22, 3), soft)
            st(acc, 3.2); p.drawLine(QPointF(24, 30), QPointF(39, 12))
            p.setBrush(QColor(acc)); p.setPen(Qt.NoPen); p.drawPolygon(poly([(20, 33), (22, 26), (28, 31)]))
        elif name == 'extrude':
            fl(_rounded(8, 28, 26, 14, 2), soft)
            st(acc, 3.0); p.drawLine(QPointF(21, 24), QPointF(21, 6)); p.drawPolyline(poly([(14, 13), (21, 6), (28, 13)]))
            st(ink, 2.0); pn = pen(ink, 2.0); pn.setStyle(Qt.DashLine); p.setPen(pn); p.drawRect(QRectF(8, 10, 0, 0))
        elif name == 'bool':
            a2, b2 = _rounded(6, 9, 25, 25, 4), _rounded(17, 15, 25, 25, 4)
            fl(a2, soft); fl(b2, QColor(0, 0, 0, 0))
            fl(a2.intersected(b2), QColor(acc), acc, 1.2)
            st(ink, 2.6); p.drawPath(a2); p.drawPath(b2)
        elif name == 'mod':
            path = QPainterPath(); path.moveTo(8, 40); path.lineTo(8, 14); path.lineTo(24, 14); path.arcTo(QRectF(12, 14, 24, 24), 90, -90); path.lineTo(40, 40); path.closeSubpath()
            path2 = QPainterPath(); path2.moveTo(8, 40); path2.lineTo(8, 10); path2.lineTo(24, 10); path2.arcTo(QRectF(8, 10, 32, 32), 90, -90); path2.lineTo(40, 40); path2.closeSubpath()
            fl(path2, soft)
            st(acc, 3.0); p.drawArc(QRectF(8, 10, 32, 32), 90 * 16, -90 * 16)
        elif name == 'mirror':
            fl(QPainterPath(), QColor(0, 0, 0, 0))
            tri = QPainterPath(); tri.moveTo(21, 10); tri.lineTo(21, 40); tri.lineTo(5, 40); tri.closeSubpath()
            tri2 = QPainterPath(); tri2.moveTo(27, 10); tri2.lineTo(27, 40); tri2.lineTo(43, 40); tri2.closeSubpath()
            fl(tri, soft); fl(tri2, QColor(acc), acc, 2.0)
            pn = pen(ink, 2.2); pn.setStyle(Qt.DashLine); p.setPen(pn); p.drawLine(QPointF(24, 5), QPointF(24, 44))
        elif name in ('undo', 'redo'):
            flip = name == 'redo'
            m = (lambda x: 48 - x) if flip else (lambda x: x)
            st(ink, 3.0)
            p.drawPolyline(poly([(m(15), 11), (m(7), 19), (m(15), 27)]))
            path = QPainterPath(); path.moveTo(m(8), 19); path.lineTo(m(28), 19); path.cubicTo(m(41), 19, m(41), 38, m(28), 38); path.lineTo(m(20), 38)
            p.drawPath(path)
        elif name.startswith('s_'):
            dot = lambda x, y, c=None: (p.setBrush(QColor(c or acc)), p.setPen(pen('#ffffff' if white else '#ffffff', 1.6)), p.drawEllipse(QPointF(x, y), 3.6, 3.6))
            sh = name[2:]
            if sh == 'line':
                st(ink, 3.0); p.drawLine(QPointF(10, 38), QPointF(38, 10)); dot(10, 38); dot(38, 10)
            elif sh == 'rect':
                fl(_rounded(8, 13, 32, 22, 2), soft); dot(8, 13); dot(40, 35)
            elif sh == 'circle':
                fl(_circle(24, 24, 15), soft); st(acc, 2.4); p.drawLine(QPointF(24, 24), QPointF(34.6, 13.4)); dot(24, 24, ink); dot(34.6, 13.4)
            elif sh == 'text':
                st(ink, 3.4); p.drawLine(QPointF(11, 12), QPointF(37, 12)); p.drawLine(QPointF(24, 12), QPointF(24, 38))
                st(acc, 3.0); p.drawLine(QPointF(17, 40), QPointF(31, 40))
            elif sh == 'ellipse':
                path = QPainterPath(); path.addEllipse(QRectF(6, 14, 36, 20)); fl(path, soft); dot(24, 24, acc)
            elif sh == 'slot':
                path = QPainterPath(); path.addRoundedRect(QRectF(6, 15, 36, 18), 9, 9); fl(path, soft); dot(15, 24); dot(33, 24)
            elif sh == 'polygon':
                pts = [(24 + 16 * math.sin(2 * math.pi * k / 5), 25 - 16 * math.cos(2 * math.pi * k / 5)) for k in range(5)]
                path = QPainterPath(); path.addPolygon(poly(pts + [pts[0]])); fl(path, soft); dot(24, 25, ink); dot(*pts[0])
            elif sh == 'arc':
                st(ink, 3.0); p.drawArc(QRectF(7, 17, 34, 34), 28 * 16, 124 * 16); dot(10.5, 30); dot(37.5, 30); dot(24, 17, ink)
            elif sh == 'point':
                st(ink, 2.4); p.drawLine(QPointF(24, 8), QPointF(24, 40)); p.drawLine(QPointF(8, 24), QPointF(40, 24)); dot(24, 24)
            elif sh == 'construction':
                pn = pen(acc, 3.0); pn.setStyle(Qt.DashLine); p.setPen(pn); p.setBrush(Qt.NoBrush); p.drawLine(QPointF(9, 38), QPointF(39, 10)); dot(9, 38, ink); dot(39, 10, ink)
            elif sh == 'measure':
                st(ink, 2.6); p.drawLine(QPointF(8, 31), QPointF(40, 31)); p.drawLine(QPointF(8, 24), QPointF(8, 38)); p.drawLine(QPointF(40, 24), QPointF(40, 38))
                st(acc, 3.0); p.drawLine(QPointF(15, 17), QPointF(33, 17)); p.drawPolyline(poly([(19, 13), (14, 17), (19, 21)])); p.drawPolyline(poly([(29, 13), (34, 17), (29, 21)]))
            elif sh == 'trim':
                st(ink, 2.8); p.drawLine(QPointF(14, 14), QPointF(40, 36)); p.drawLine(QPointF(14, 34), QPointF(40, 12))
                st(acc, 2.6); p.drawEllipse(QPointF(11, 12), 4.5, 4.5); p.drawEllipse(QPointF(11, 36), 4.5, 4.5)
        elif name in ('move', 'rotate'):
            if name == 'move':
                st(ink, 2.8)
                for dx, dy in ((0, -1), (0, 1), (-1, 0), (1, 0)):
                    p.drawLine(QPointF(24, 24), QPointF(24 + dx * 16, 24 + dy * 16))
                    tip = (24 + dx * 18, 24 + dy * 18)
                    p.drawPolyline(poly([(tip[0] - dx * 6 - dy * 5, tip[1] - dy * 6 + dx * 5), tip, (tip[0] - dx * 6 + dy * 5, tip[1] - dy * 6 - dx * 5)]))
                p.setBrush(QColor(acc)); p.setPen(Qt.NoPen); p.drawEllipse(QPointF(24, 24), 4.2, 4.2)
            else:
                st(ink, 3.0); p.drawArc(QRectF(9, 9, 30, 30), 40 * 16, 270 * 16)
                p.setBrush(QColor(acc)); p.setPen(Qt.NoPen); p.drawPolygon(poly([(36, 10), (38, 22), (27, 17)]))
        elif name == 'trash':
            st(ink, 2.8); p.drawLine(QPointF(9, 13), QPointF(39, 13)); p.drawPolyline(poly([(19, 13), (19, 8), (29, 8), (29, 13)]))
            body = QPainterPath(); body.moveTo(12, 13); body.lineTo(14, 41); body.lineTo(34, 41); body.lineTo(36, 13)
            fl(body, soft)
            st(acc, 2.6); p.drawLine(QPointF(20, 20), QPointF(20, 34)); p.drawLine(QPointF(28, 20), QPointF(28, 34))
        elif name == 'home':
            path = QPainterPath(); path.moveTo(7, 24); path.lineTo(24, 8); path.lineTo(41, 24); path.lineTo(36, 24); path.lineTo(36, 40); path.lineTo(12, 40); path.lineTo(12, 24); path.closeSubpath()
            fl(path, soft)
            fl(_rounded(20, 28, 8, 12, 1.5), QColor(acc), acc, 1.2)
        elif name == 'layers':
            for k, y in enumerate((30, 20, 10)):
                q = poly([(24, y + 8), (42, y), (24, y - 8 + 0), (6, y)])
                p.setBrush(soft if k else QColor(acc)); p.setPen(pen(ink if k else acc, 2.4)); p.drawPolygon(poly([(24, y + 9), (42, y), (24, y - 9), (6, y)]))
    elif kind == 'f_help':
        fill(_rounded(7, 9, 34, 30, 3), '#ffffff', BLUE)
        p.setPen(pen(BLUE, 2.2)); p.drawLine(QPointF(24, 9), QPointF(24, 39))
        p.setPen(pen(BLUE_SOFT, 2.4))
        for y in (17, 23, 29):
            p.drawLine(QPointF(11, y), QPointF(20, y)); p.drawLine(QPointF(28, y), QPointF(37, y))
        p.setBrush(QColor(ORANGE)); p.setPen(Qt.NoPen); p.drawPolygon(QPolygonF([QPointF(31, 9), QPointF(37, 9), QPointF(37, 21), QPointF(34, 18), QPointF(31, 21)]))
    elif kind in ('xray', 'xray_w'):
        ink = '#ffffff' if kind == 'xray_w' else '#324c68'
        p.setBrush(Qt.NoBrush)
        dashed = pen(ink, 1.8); dashed.setStyle(Qt.DashLine)
        p.setPen(dashed)
        p.drawRect(QRectF(15, 6, 24, 24)); p.drawLine(QPointF(15, 6), QPointF(6, 15)); p.drawLine(QPointF(39, 6), QPointF(30, 15)); p.drawLine(QPointF(39, 30), QPointF(30, 39))
        p.setPen(pen(ink, 2.4))
        p.drawRect(QRectF(6, 15, 24, 24)); p.drawLine(QPointF(6, 15), QPointF(15, 6)); p.drawLine(QPointF(30, 15), QPointF(39, 6)); p.drawLine(QPointF(30, 39), QPointF(39, 30))
        p.drawLine(QPointF(30, 15), QPointF(39, 6)); p.drawLine(QPointF(39, 6), QPointF(39, 30))
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


def badge(kind: str, color: str = BLUE, size: int = 34, plain: bool = False) -> QPixmap:
    """Okrągła plakietka z ikoną (nagłówek panelu)."""
    scale = 2
    pm = QPixmap(size * scale, size * scale)
    pm.fill(Qt.transparent)
    if plain:       # sama grafika, bez zaokrąglonego kwadratu
        pm = pixmap(kind, size, scale)
        pm.setDevicePixelRatio(scale)
        return pm
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    tint, edge = QColor(color), QColor(color)
    tint.setAlpha(34); edge.setAlpha(120)
    p.setBrush(tint); p.setPen(QPen(edge, 1.4 * scale))
    p.drawRoundedRect(QRectF(scale, scale, (size - 2) * scale, (size - 2) * scale), 10 * scale, 10 * scale)
    p.end()
    kind = {'one': 't_extrude', 'union': 't_bool', 'fillet': 't_mod', 'chamfer': 't_mod', 'mirror': 't_mirror', 'sym': 't_mirror',
            'sketch': 't_sketch', 'extrude': 't_extrude', 'bool': 't_bool'}.get(kind, kind)
    inner = pixmap(kind, size - 8, scale)
    q = QPainter(pm)
    q.drawPixmap(4 * scale, 4 * scale, inner)
    q.end()
    pm.setDevicePixelRatio(scale)
    return pm
