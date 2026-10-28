"""Native Qt/OpenGL viewport with picking against displayed CAD edge curves."""
from __future__ import annotations
import math
import time
import numpy as np
import pyqtgraph as pg
import pyqtgraph.opengl as gl
from pyqtgraph.opengl import shaders
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QWidget
from PySide6.QtGui import QVector3D, QVector4D, QColor
from OpenGL import GL
from PySide6.QtGui import QMatrix4x4
from .document import Body
from . import kernel


class GradientBackground(gl.GLGraphicsItem.GLGraphicsItem):
    """Pionowy gradient tła (jak w wersji HTML), rysowany jako pierwszy, bez głębi."""

    def __init__(self, top, bottom):
        super().__init__()
        self.top, self.bottom = top, bottom
        self.setDepthValue(-1000)

    def paint(self):
        GL.glMatrixMode(GL.GL_PROJECTION)
        GL.glPushMatrix()
        GL.glLoadIdentity()
        GL.glMatrixMode(GL.GL_MODELVIEW)
        GL.glPushMatrix()
        GL.glLoadIdentity()
        GL.glDisable(GL.GL_DEPTH_TEST)
        GL.glDisable(GL.GL_BLEND)
        GL.glDepthMask(GL.GL_FALSE)
        GL.glBegin(GL.GL_QUADS)
        GL.glColor3f(*self.top)
        GL.glVertex2f(-1, 1)
        GL.glVertex2f(1, 1)
        GL.glColor3f(*self.bottom)
        GL.glVertex2f(1, -1)
        GL.glVertex2f(-1, -1)
        GL.glEnd()
        GL.glDepthMask(GL.GL_TRUE)
        GL.glEnable(GL.GL_DEPTH_TEST)
        GL.glMatrixMode(GL.GL_PROJECTION)
        GL.glPopMatrix()
        GL.glMatrixMode(GL.GL_MODELVIEW)
        GL.glPopMatrix()

# Wygląd jak w wersji HTML: jasne tło, niebieska siatka, jasnoszare bryły z czarnym obrysem.
BACKGROUND = '#edf2f8'
GRID_COLOR = '#9fb6cf'
BG_TOP = (0.985, 0.992, 1.0)
BG_BOTTOM = (0.875, 0.915, 0.96)
SOLID_COLOR = (.62, .68, .76, 1)
SOLID_SELECTED = (.40, .60, .90, 1)
EDGE_COLOR = (.10, .13, .18, 1)
SKETCH_COLOR = (.03, .20, .52, 1)
PREVIEW_COLOR = (1, .48, .05, 1)
PLANE_COLORS = {'XY': '#4a8fe0', 'XZ': '#3aa77a', 'YZ': '#df5a5e'}
PLANE_SIZES = (2, 3, 4, 6, 8, 12, 16, 24, 32, 48, 64, 96, 128)
PLANE_HALF = 14.0
GRID_LEVELS = (.1, .2, .5, 1, 2, 5, 10, 20, 50, 100, 200, 500, 1000)
VIEWS = {  # (elewacja, azymut) kamery pyqtgraph
    'iso': (25, -55), 'XY': (90, -90), 'XZ': (0, -90), 'YZ': (0, 0),
    'Z': (90, -90), '-Z': (-90, -90), 'X': (0, 0), '-X': (0, 180), 'Y': (0, 90), '-Y': (0, -90),
}



class Overlay2D(QWidget):
    """Przezroczysta warstwa 2D nad widokiem 3D (jak <canvas> w wersji HTML): strzałki i uchwyty są ZAWSZE na wierzchu,
    nigdy nie chowają się za bryłą. Rysuje też środki szkiców i znacznik przyciągania."""

    def __init__(self, view):
        super().__init__(view)
        self.view = view
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.setAttribute(Qt.WA_TranslucentBackground)

    @staticmethod
    def _qc(color, alpha=None):
        c = QColor.fromRgbF(*[min(1.0, max(0.0, float(x))) for x in color[:4]]) if len(color) >= 3 else QColor('#f09a22')
        if len(color) < 4:
            c.setAlphaF(1.0)
        if alpha is not None:
            c.setAlpha(alpha)
        return c

    def paintEvent(self, event):
        v = self.view
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        try:
            for c in v.sketch_centers:
                xy = v.project_one(c)
                if xy is None:
                    continue
                p.setPen(QPen(QColor('#087d55'), 1.6))
                p.setBrush(QColor('#ffffff'))
                p.drawEllipse(QPointF(*xy), 4.5, 4.5)
                p.drawLine(QPointF(xy[0] - 9, xy[1]), QPointF(xy[0] + 9, xy[1]))
                p.drawLine(QPointF(xy[0], xy[1] - 9), QPointF(xy[0], xy[1] + 9))
            if v._origin_visible:
                xy0 = v.project_one((0, 0, 0))
                if xy0 is not None:
                    p.setPen(QPen(QColor('#3d4a58'), 1.8))
                    p.setBrush(QColor('#ffffff'))
                    p.drawEllipse(QPointF(*xy0), 6.5, 6.5)
                    p.setBrush(QColor('#8d9aa8'))
                    p.setPen(Qt.NoPen)
                    p.drawEllipse(QPointF(*xy0), 2.6, 2.6)
            box = v.sketch_box
            if box:
                pts = [v.project_one(c) for c in box['corners']]
                if all(q is not None for q in pts):
                    blue = QColor('#2f87e8')
                    dash = QPen(blue, 1.6, Qt.DashLine)
                    p.setPen(dash)
                    p.setBrush(QColor(47, 135, 232, 24))
                    p.drawPolygon(QPolygonF([QPointF(*q) for q in pts]))
                    top, rot = v.project_one(box['top']), v.project_one(box['rotate'])
                    if top is not None and rot is not None:
                        p.setPen(QPen(blue, 1.6))
                        p.drawLine(QPointF(*top), QPointF(*rot))
                    mv, sc = v.project_one(box['move']), v.project_one(box['scale'])
                    p.setPen(QPen(blue, 2))
                    p.setBrush(QColor('#ffffff'))
                    if sc is not None:
                        p.drawRect(QRectF(sc[0] - 6, sc[1] - 6, 12, 12))
                        p.drawLine(QPointF(sc[0] - 3, sc[1] + 3), QPointF(sc[0] + 3, sc[1] - 3))
                    if rot is not None:
                        p.drawEllipse(QPointF(*rot), 7.5, 7.5)
                        p.drawArc(QRectF(rot[0] - 3.5, rot[1] - 3.5, 7, 7), 40 * 16, 270 * 16)
                    if mv is not None:
                        p.setBrush(blue)
                        p.setPen(QPen(QColor('#ffffff'), 1.8))
                        p.drawRoundedRect(QRectF(mv[0] - 8, mv[1] - 8, 16, 16), 4, 4)
                        p.setPen(QPen(QColor('#ffffff'), 1.6, Qt.SolidLine, Qt.RoundCap))
                        p.drawLine(QPointF(mv[0] - 5, mv[1]), QPointF(mv[0] + 5, mv[1]))
                        p.drawLine(QPointF(mv[0], mv[1] - 5), QPointF(mv[0], mv[1] + 5))
            for g in v.sketch_grips:
                xy = v.project_one(g)
                if xy is None:
                    continue
                p.setPen(QPen(QColor('#2f87e8'), 1.8))
                p.setBrush(QColor('#ffffff'))
                p.drawRect(QRectF(xy[0] - 4.5, xy[1] - 4.5, 9, 9))
            order = {'plane': 0, 'ring': 1, 'axis': 2, 'arrow': 3}
            for h in sorted(v.handles, key=lambda h: order.get(h.get('kind', 'arrow'), 3)):
                hot = v.hover_handle == h['id'] or (v._handle_drag is not None and v._handle_drag['id'] == h['id'])
                getattr(self, '_draw_' + h.get('kind', 'arrow'))(p, v, h, hot)
            snap = v.snap_marker
            if snap is not None:
                xy, text = snap
                p.setPen(QPen(QColor('#e06c12'), 2))
                p.setBrush(QColor('#ffffff'))
                p.drawEllipse(QPointF(*xy), 5.5, 5.5)
                if text:
                    font = QFont('Segoe UI')
                    font.setPixelSize(12)
                    p.setFont(font)
                    p.setPen(QColor('#9a4b0b'))
                    p.drawText(QPointF(xy[0] + 10, xy[1] - 10), text)
        finally:
            p.end()

    def _draw_plane(self, p, v, h, hot):
        pts = [v.project_one(q) for q in h['quad']]
        if any(q is None for q in pts):
            return
        poly = QPolygonF([QPointF(*q) for q in pts])
        p.setBrush(self._qc(h['color'], 170 if hot else 95))
        p.setPen(QPen(self._qc(h['color'], 235), 2))
        p.drawPolygon(poly)

    def _draw_ring(self, p, v, h, hot):
        c, axis, radius = (np.asarray(h['ring'][0], float), np.asarray(h['ring'][1], float), float(h['ring'][2]))
        e1 = np.cross(axis, (0, 0, 1.0) if abs(axis[2]) < .9 else (1.0, 0, 0))
        e1 /= np.linalg.norm(e1)
        e2 = np.cross(axis, e1)
        pts = np.array([c + radius * (np.cos(a) * e1 + np.sin(a) * e2) for a in np.linspace(0, 2 * np.pi, 97)])
        xy, _, w = v.project_points(pts)
        if not np.isfinite(xy).all():
            return
        poly = QPolygonF([QPointF(float(a), float(b)) for a, b in xy])
        halo = QPen(QColor(255, 255, 255, 190), 8.5 if hot else 7)
        halo.setCapStyle(Qt.RoundCap)
        p.setBrush(Qt.NoBrush)
        p.setPen(halo)
        p.drawPolyline(poly)
        pen = QPen(self._qc(h['color'], 255 if hot else 225), 5.5 if hot else 4)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        p.drawPolyline(poly)
        tip = v.project_one(h['tip'])
        if tip is not None:
            self._badge(p, tip, h['color'], h.get('label'), 10 + (2 if hot else 0))

    def _badge(self, p, xy, color, label, r):
        p.setPen(QPen(QColor('#ffffff'), 2.4))
        p.setBrush(self._qc(color))
        p.drawEllipse(QPointF(*xy), r, r)
        if label:
            font = QFont('Segoe UI')
            font.setBold(True)
            font.setPixelSize(12)
            p.setFont(font)
            p.setPen(QColor('#ffffff'))
            p.drawText(QRectF(xy[0] - r, xy[1] - r, 2 * r, 2 * r), Qt.AlignCenter, label)

    def _draw_axis(self, p, v, h, hot, big=False):
        geo = v.handle_geometry(h)
        if geo is None:
            return
        s, e = geo['start'], geo['end']
        dx, dy = e[0] - s[0], e[1] - s[1]
        length = math.hypot(dx, dy) or 1.0
        ux, uy = dx / length, dy / length
        head = (24 if big else 17) + (3 if hot else 0)
        base = (e[0] - ux * head * .7, e[1] - uy * head * .7)
        halo = QPen(QColor(255, 255, 255, 200), 10.5 if big else 8.5)
        halo.setCapStyle(Qt.RoundCap)
        p.setPen(halo)
        p.drawLine(QPointF(*s), QPointF(*base))
        pen = QPen(self._qc(h['color']), (6 if big else 4.6) + (1.4 if hot else 0))
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        p.drawLine(QPointF(*s), QPointF(*base))
        tri = QPolygonF([QPointF(*e), QPointF(e[0] - ux * head + -uy * head * .5, e[1] - uy * head + ux * head * .5),
                         QPointF(e[0] - ux * head - -uy * head * .5, e[1] - uy * head - ux * head * .5)])
        p.setPen(QPen(QColor('#ffffff'), 2.2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.setBrush(self._qc(h['color']))
        p.drawPolygon(tri)
        if h.get('label'):
            font = QFont('Segoe UI')
            font.setBold(True)
            font.setPixelSize(13)
            p.setFont(font)
            p.setPen(self._qc(h['color']).darker(125))
            p.drawText(QPointF(e[0] + ux * 12 - 4, e[1] + uy * 12 + 5), h['label'])

    def _draw_arrow(self, p, v, h, hot):
        return self._draw_axis(p, v, dict(h, label=h.get('label') if h.get('label') not in ('+', '-') else None), hot, big=True)

    def _draw_arrow_old(self, p, v, h, hot):
        geo = v.handle_geometry(h)
        if geo is None:
            return
        s, e = geo['start'], geo['end']
        halo = QPen(QColor(255, 255, 255, 215), 9)
        halo.setCapStyle(Qt.RoundCap)
        p.setPen(halo)
        p.drawLine(QPointF(*s), QPointF(*e))
        pen = QPen(self._qc(h['color']), 5.2)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        p.drawLine(QPointF(*s), QPointF(*e))
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 45))
        p.drawEllipse(QPointF(e[0] + 1, e[1] + 3), 14, 14)
        self._badge(p, e, h['color'], h.get('label'), 13 if hot else 11.5)


class OverMesh(gl.GLMeshItem):
    """Półprzezroczysta nakładka na ścianę: przesunięta ku kamerze, więc nie ginie w z-fightingu z bryłą."""

    def paint(self):
        GL.glEnable(GL.GL_POLYGON_OFFSET_FILL)
        GL.glPolygonOffset(-2.0, -2.0)
        try:
            super().paint()
        finally:
            GL.glDisable(GL.GL_POLYGON_OFFSET_FILL)


class OffsetMesh(gl.GLMeshItem):
    """Siatka z przesunięciem wielokątów w głąb: krawędzie leżą czysto na ścianach, a ukryte części są naprawdę zasłonięte."""

    def paint(self):
        GL.glEnable(GL.GL_POLYGON_OFFSET_FILL)
        GL.glPolygonOffset(2.0, 2.0)
        try:
            super().paint()
        finally:
            GL.glDisable(GL.GL_POLYGON_OFFSET_FILL)


class CadView(gl.GLViewWidget):
    edgeClicked = Signal(str, int, bool, bool)  # bryła, krawędź, dodaj do zaznaczenia, cały łańcuch styczny
    planeClicked = Signal(str)
    sketchDrawn = Signal(str, str, float, float, float, float)
    sketchInfo = Signal(str)
    # tryb "studio" (jak HTML): klik-klik na płaszczyźnie szkicu i ogólne kliknięcia / ruch kursora
    sketchMoved = Signal(object, float, float)
    sketchClicked = Signal(object, float, float)
    viewClicked = Signal(float, float, bool, bool)  # x, y, Shift, Ctrl
    viewHover = Signal(float, float)
    bodyClicked = Signal(str, bool)
    selectionCleared = Signal()
    contextRequested = Signal(float, float)
    handleDragged = Signal(str, float)   # id uchwytu, przesunięcie wzdłuż jego osi (mm)
    handleReleased = Signal(str)
    pointDragged = Signal(str, object)    # id uchwytu płaszczyznowego / swobodnego, wektor przesunięcia w świecie (mm)
    cameraMoved = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        if 'rccad' not in shaders.ShaderProgram.names:
            shaders.ShaderProgram('rccad', [
                shaders.VertexShader(shaders.getShaderProgram('shaded').shaders[0].code),
                shaders.FragmentShader("""
                    #ifdef GL_ES
                    precision mediump float;
                    #endif
                    varying vec4 v_color;
                    varying vec3 v_normal;
                    void main() {
                        vec3 n = normalize(v_normal);
                        float key = max(0.0, dot(n, normalize(vec3(0.3, 0.6, 1.0))));
                        float fill = max(0.0, dot(n, normalize(vec3(-0.6, -0.4, 0.25))));
                        float sky = 0.5 + 0.5 * n.z;
                        float light = 0.46 + 0.34 * key + 0.12 * sky + 0.16 * fill;
                        gl_FragColor = vec4(v_color.rgb * light, v_color.a);
                    }
                """),
            ])
        self.setMouseTracking(True)   # bez tego widok nie dostaje ruchów myszy bez wciśniętego przycisku (brak podglądu na żywo)
        self.setBackgroundColor(BACKGROUND)
        self.setCameraPosition(distance=120, elevation=25, azimuth=-55)
        self.addItem(GradientBackground(BG_TOP, BG_BOTTOM))
        self.grid_items = []
        self.axis_lines = []
        self._grid_plane = None
        self._plane_half = 8.0
        self._grid_key = None
        for size, step, color in ((600, 5, '#d3deeb'), (600, 25, '#9db5cc')):
            grid = gl.GLGridItem()
            grid.setSize(size, size)
            grid.setSpacing(step, step)
            grid.setColor(pg.mkColor(color))
            self.addItem(grid)
            self.grid_items.append(grid)
        self.grid_item = self.grid_items[-1]
        self.axis_defs = []
        for direction, col in (((1, 0, 0), (.89, .31, .33, .95)), ((0, 1, 0), (.14, .64, .42, .95)), ((0, 0, 1), (.2, .5, .9, .95))):
            direction = np.array(direction, float)
            solid = gl.GLLinePlotItem(pos=np.array([(0, 0, 0), direction * 100], dtype=np.float32), color=col, width=2.4, antialias=True)
            dashed = gl.GLLinePlotItem(pos=np.zeros((2, 3), dtype=np.float32), color=col, width=2.0, antialias=True, mode='lines')
            self.addItem(solid)
            self.addItem(dashed)
            self.axis_defs.append((solid, dashed, direction))
            self.axis_lines.append((solid, direction))
            self.axis_lines.append((dashed, direction))
        self._origin_visible = False
        self.custom_plane_items = []
        self.marker_items = []
        self.bodies = ()
        self.model_items = []
        self.highlight_items = []
        self.selected_bodies = set()
        self.selected_edges = {}
        self.edge_mode = False
        self.mouse_mode = "select"
        self.multi_select = False
        self._drag_position = None
        self._press = None
        # szkicowanie myszą
        self.sketch_plane = None
        self.sketch_tool = None
        self.sketch_sides = 6
        self.plane_pick = False
        self._sk_start = None
        self._sk_item = None
        self._hover_plane = None
        self._hover_item = None
        self._hover_key = None
        self._hover_time = 0.0
        self.plane_items = {}
        self._build_planes()
        self.click_mode = False       # True: studio (klik-klik), False: klasyczne okno (przeciąganie)
        self.tints = {}               # id bryły -> kolor RGBA (np. baza / narzędzia Boolean)
        self.preview_items = []
        self.handles = []             # uchwyty-strzałki: dict(id, tip, dir, color, ring=(środek, oś, promień)|None)
        self.handle_items = []
        self._handle_drag = None
        self.snap_label = None
        self.sketch_centers = []
        self.sketch_grips = []
        self.sketch_box = None
        self.drag_hook = None
        self._hook_active = False
        self.snap_marker = None       # ((x, y), etykieta) - przyciąganie jak w wersji HTML
        self.hover_handle = None
        self.free_drag = None         # (id bryły, środek): przeciąganie bryły lewym przyciskiem po płaszczyźnie najbardziej zwróconej do kamery
        self.xray = False
        self.hover_gate = None        # funkcja () -> bool: czy w ogóle liczyć kursor szkicu (Studio włącza po pierwszym kliknięciu)
        self.snapper = None           # funkcja (x, y, (u, v)) -> (u, v, etykieta) ustawiana przez Studio
        self._body_m = {}             # id bryły -> macierz podglądu przesunięcia / obrotu (bez ponownego liczenia geometrii)
        self._cache = {}              # id bryły -> (klucz, elementy GL): bez przebudowy całej sceny przy każdej zmianie
        self.overlay = Overlay2D(self)
        self.overlay.setGeometry(0, 0, self.width(), self.height())
        self.overlay.raise_()

    def _refresh_grid(self):
        """Siatka zagęszcza się przy przybliżaniu (min. 12 px między cienkimi liniami) i podąża za środkiem widoku."""
        if not getattr(self, 'grid_items', None) or self.width() < 2:
            return
        dist = max(float(self.opts['distance']), 1e-6)
        ppm = (self.height() / 2) / (dist * math.tan(math.radians(float(self.opts['fov']) / 2)))
        step = next((g for g in GRID_LEVELS if g * ppm >= 12), GRID_LEVELS[-1])
        want = next((z for z in PLANE_SIZES if z >= dist * .035), PLANE_SIZES[-1])
        if want != self._plane_half and hasattr(self, '_plane_corners'):
            self._plane_half = float(want)
            self._apply_plane_size()
        major = step * 5
        plane = self._grid_plane or 'XY'
        c = self.opts['center']
        u, v = kernel.uv_of(plane, (c.x(), c.y(), c.z()))
        cu, cv = round(u / major) * major, round(v / major) * major
        key = (step, cu, cv, id(plane) if not isinstance(plane, str) else plane)
        if key == self._grid_key:
            return
        self._grid_key = key
        frame = kernel.frame_of(plane)
        m = QMatrix4x4()
        x, y, n = (np.array(vec, float) for vec in (frame.xdir, frame.ydir, frame.normal))
        o = np.array(frame.origin, float) + x * cu + y * cv
        for r in range(3):
            m.setRow(r, QVector4D(float(x[r]), float(y[r]), float(n[r]), float(o[r])))
        half = step * 120
        for grid, spacing in zip(self.grid_items, (step, major)):
            grid.setSize(2 * half, 2 * half)
            grid.setSpacing(spacing, spacing)
            grid.setTransform(m)

    def update(self, *args):
        self._refresh_grid()
        self._refresh_axes()
        super().update(*args)
        self.cameraMoved.emit()
        ov = getattr(self, 'overlay', None)
        if ov is not None:
            ov.update()

    def _refresh_axes(self):
        """Oś patrzenia wzdłuż osi świata (np. widok z góry) rzutowałaby się jako skośna kreska - wtedy ją chowamy."""
        try:
            cam = self.camera_dir()
        except Exception:
            return
        if getattr(self, '_axes_busy', False):
            return
        self._axes_busy = True
        try:
            for item, direction in getattr(self, 'axis_lines', ()):
                show = abs(float(np.dot(cam, direction))) < .985
                if item.visible() != show:
                    item.setVisible(show)
        finally:
            self._axes_busy = False

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.overlay.setGeometry(0, 0, self.width(), self.height())
        self.overlay.raise_()

    def set_xray(self, on):
        """Przezroczyste bryły (podgląd ukrytych krawędzi); domyślnie bryły są w pełni nieprzezroczyste."""
        self.xray = bool(on)
        for bid in list(self._cache):
            for item in self._cache.pop(bid)[1]:
                self.removeItem(item)
        self.set_models(self.bodies, self.selected_bodies, self.selected_edges)

    def _apply_body_matrix(self, bid):
        cached = self._cache.get(bid)
        if not cached:
            return
        m = self._body_m.get(bid)
        for item in cached[1]:
            if m is None:
                item.resetTransform()
            else:
                item.setTransform(m)

    def set_body_matrix(self, bid, matrix):
        """Natychmiastowy podgląd przesunięcia / obrotu: macierz 4x4 nakładana na elementy GL bryły."""
        if matrix is None:
            self._body_m.pop(bid, None)
        else:
            self._body_m[bid] = QMatrix4x4(matrix)
        self._apply_body_matrix(bid)
        self.update()

    def clear_body_matrices(self):
        for bid in list(self._body_m):
            self._body_m.pop(bid)
            self._apply_body_matrix(bid)
        self.update()

    def project_one(self, point):
        xy, _, w = self.project_points(np.asarray([point], float))
        if not np.isfinite(xy[0]).all() or w[0] <= 0:
            return None
        return float(xy[0][0]), float(xy[0][1])

    def set_models(self, bodies, selected_bodies=(), selected_edges=None):
        self._set_hover_edge(None)
        self.bodies = tuple(bodies)
        self.selected_bodies = set(selected_bodies)
        self.selected_edges = selected_edges or {}
        live = set()
        centers = []
        for body in self.bodies:
            if not body.visible or body.mesh is None:
                continue
            live.add(body.id)
            mesh = body.mesh
            color = self.tints.get(body.id) or SOLID_COLOR
            picked = body.id in self.selected_bodies
            sel = frozenset(self.selected_edges.get(body.id, ()))
            key = (id(mesh), tuple(color), picked, sel, body.kind, self.xray)
            cached = self._cache.get(body.id)
            if cached is None or cached[0] != key:
                if cached is not None:
                    for item in cached[1]:
                        self.removeItem(item)
                items = []
                if len(mesh.triangles):
                    shown = (*color[:3], .30) if self.xray and body.kind != 'sketch' else color
                    item = OffsetMesh(vertexes=mesh.vertices, faces=mesh.triangles, smooth=True, color=shown, shader='rccad', drawEdges=False)
                    item.setGLOptions('translucent' if self.xray else 'opaque')
                    self.addItem(item)
                    items.append(item)
                for index, points in mesh.edges.items():
                    hot = index in sel or picked
                    base = SKETCH_COLOR if body.kind == 'sketch' else EDGE_COLOR
                    line = gl.GLLinePlotItem(pos=points, color=PREVIEW_COLOR if hot else base, width=3.5 if hot else (2.3 if body.kind == 'sketch' else 1.5), antialias=True)
                    if body.kind != 'sketch':
                        line.setGLOptions('additive' if self.xray else 'translucent')
                    self.addItem(line)
                    items.append(line)
                self._cache[body.id] = (key, items)
                if body.id in self._body_m:
                    self._apply_body_matrix(body.id)
            if body.kind == 'sketch' and len(mesh.vertices) + len(mesh.edges):
                pts = np.concatenate([e.reshape(-1, 3) for e in mesh.edges.values()]) if mesh.edges else mesh.vertices
                if len(pts):
                    centers.append(((pts.min(axis=0) + pts.max(axis=0)) / 2).tolist())
        for bid in [b for b in self._cache if b not in live]:
            for item in self._cache.pop(bid)[1]:
                self.removeItem(item)
        self.sketch_centers = centers
        self.update()

    def fit_all(self):
        visible = [b for b in self.bodies if b.visible and b.mesh is not None and len(b.mesh.vertices)]
        if not visible:
            self.opts['center'] = QVector3D(0, 0, 0)
            self.setCameraPosition(distance=120)
            return
        low = np.min([b.mesh.vertices.min(axis=0) for b in visible], axis=0)
        high = np.max([b.mesh.vertices.max(axis=0) for b in visible], axis=0)
        center = (low + high) / 2
        self.opts['center'] = QVector3D(*map(float, center))
        self.setCameraPosition(distance=max(20, float(np.linalg.norm(high - low)) * 1.6))

    def set_view(self, name):
        el, az = VIEWS[name]
        self.setCameraPosition(elevation=el, azimuth=az)

    # ---------- płaszczyzny (jak w HTML) ----------
    def _build_planes(self):
        """Płaszczyzny podstawowe jak punkt początkowy w Fusion 360: trzy brzoskwiniowe, półprzezroczyste kwadraty wychodzące z początku układu."""
        corners = {
            'XY': [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)],
            'XZ': [(0, 0, 0), (1, 0, 0), (1, 0, 1), (0, 0, 1)],
            'YZ': [(0, 0, 0), (0, 1, 0), (0, 1, 1), (0, 0, 1)],
        }
        self._plane_corners = corners
        for name, pts in corners.items():
            rgb = (.96, .62, .40)
            fill = gl.GLMeshItem(vertexes=np.array(pts, dtype=np.float32), faces=np.array([[0, 1, 2], [0, 2, 3]]),
                                 color=(*rgb, .22), smooth=False, drawEdges=False)
            fill.setGLOptions('translucent')
            outline = gl.GLLinePlotItem(pos=np.array([*pts, pts[0]], dtype=np.float32), color=(.88, .50, .26, .95), width=1.6, antialias=True)
            label = gl.GLTextItem(pos=np.array(pts[2], dtype=np.float32) * .85, text=name, color=QColor('#b8672f'))
            self.plane_items[name] = (fill, outline, label, rgb)
        self._apply_plane_size()

    def _apply_plane_size(self):
        half = self._plane_half
        m = QMatrix4x4()
        m.scale(half, half, half)
        for name, (fill, outline, label, rgb) in self.plane_items.items():
            fill.setTransform(m)
            outline.setTransform(m)
            label.setData(pos=np.array(self._plane_corners[name][2], dtype=np.float32) * half * .85)
        self._rebuild_axes()

    def _rebuild_axes(self):
        """Osie jak w Fusion 360: część dodatnia ciągła, ujemna kreskowana; długość i gęstość kresek zależą od rozmiaru płaszczyzn."""
        half = self._plane_half
        length = 30.0 * half
        dash = half / 7.0
        for solid, dashed, direction in getattr(self, 'axis_defs', ()):
            solid.setData(pos=np.array([(0, 0, 0), direction * length], dtype=np.float32))
            ts = np.arange(0.0, length, 2 * dash)
            seg = np.empty((len(ts) * 2, 3), dtype=np.float32)
            seg[0::2] = -np.outer(ts, direction)
            seg[1::2] = -np.outer(ts + dash, direction)
            dashed.setData(pos=seg)

    def show_planes(self, visible, only=None):
        for name, (fill, outline, label, rgb) in self.plane_items.items():
            show = visible and (only is None or name == only)
            for item in (fill, outline, label):
                if show and item not in self.items:
                    self.addItem(item)
                elif not show and item in self.items:
                    self.removeItem(item)
        self._hover_plane = None
        self._origin_visible = bool(visible and only is None)
        self.update()

    def _highlight_plane(self, name):
        if name == self._hover_plane:
            return
        self._hover_plane = name
        for key, (fill, outline, label, rgb) in self.plane_items.items():
            fill.setColor((*rgb, .45 if key == name else .22))
        self.update()

    def _plane_hit(self, plane, x, y):
        ray = self._ray(x, y)
        if ray is None:
            return None
        origin, direction = ray
        frame = kernel.frame_of(plane)
        n, o = np.array(frame.normal), np.array(frame.origin)
        denom = float(direction @ n)
        if abs(denom) < 1e-9:
            return None
        t = float((o - origin) @ n) / denom
        if t <= 0:
            return None
        return t, origin + direction * t

    def plane_at(self, x, y):
        best = None
        for name in self.plane_items:
            if self.plane_items[name][0] not in self.items:
                continue
            hit = self._plane_hit(name, x, y)
            if hit:
                p = np.asarray(hit[1], float)
                eps = .03 * self._plane_half
                if np.all(p >= -eps) and np.all(p <= self._plane_half + eps) and (best is None or hit[0] < best[0]):
                    best = (hit[0], name)
        return best[1] if best else None

    def plane_point(self, plane, x, y):
        hit = self._plane_hit(plane, x, y)
        if hit is None:
            return None
        return kernel.uv_of(plane, hit[1])

    def _snap(self, point, event=None, pos=None):
        if event is not None and event.modifiers() & Qt.AltModifier:
            self.snap_label = None
            return point
        if pos is None and event is not None:
            pos = event.position()
        if self.snapper is not None and pos is not None:
            u, v, label = self.snapper(pos.x(), pos.y(), point)
            self.snap_label = label
            return u, v
        distance = float(self.opts['distance'])
        step = 10 ** math.floor(math.log10(max(distance / 40, 1e-3)))
        return round(point[0] / step) * step, round(point[1] / step) * step

    def _sketch_outline(self, plane, start, end):
        (u0, v0), (u1, v1) = start, end
        if self.sketch_tool == 'rectangle':
            uv = [(u0, v0), (u1, v0), (u1, v1), (u0, v1), (u0, v0)]
        else:
            r = math.hypot(u1 - u0, v1 - v0)
            n = 72 if self.sketch_tool == 'circle' else max(3, int(self.sketch_sides))
            uv = [(u0 + r * math.cos(2 * math.pi * k / n), v0 + r * math.sin(2 * math.pi * k / n)) for k in range(n + 1)]
        return np.array([kernel.to_world(plane, u, v) for u, v in uv], dtype=np.float32)

    def _set_sketch_preview(self, points):
        if self._sk_item is not None:
            self.removeItem(self._sk_item)
            self._sk_item = None
        if points is not None:
            self._sk_item = gl.GLLinePlotItem(pos=points, color=PREVIEW_COLOR, width=2.5, antialias=True)
            self.addItem(self._sk_item)
        self.update()

    def _set_hover_edge(self, hit):
        if hit == self._hover_key:
            return
        self._hover_key = hit
        if self._hover_item is not None:
            self.removeItem(self._hover_item)
            self._hover_item = None
        if hit:
            body = next((b for b in self.bodies if b.id == hit[0]), None)
            points = body.mesh.edges.get(hit[1]) if body and body.mesh else None
            if points is not None:
                self._hover_item = gl.GLLinePlotItem(pos=points, color=(1, .65, .2, 1), width=5, antialias=True)
                self.addItem(self._hover_item)
        self.update()

    # ---------- podglądy i wybieranie (studio) ----------
    def _dashed(self, points):
        pts = np.asarray(points, float)
        seg = np.linalg.norm(np.diff(pts, axis=0), axis=1)
        total = float(seg.sum())
        if total < 1e-9:
            return None
        dash = max(float(self.opts['distance']) * .012, 1e-3)
        cum = np.concatenate([[0], np.cumsum(seg)])
        starts = np.arange(0, total, dash * 2)
        ends = np.minimum(starts + dash, total)
        point_at = lambda t: np.column_stack([np.interp(t, cum, pts[:, k]) for k in range(3)])
        out = np.empty((len(starts) * 2, 3))
        out[0::2], out[1::2] = point_at(starts), point_at(ends)
        return out.astype(np.float32)

    def stretch_preview(self, origin, normal, factor):
        """Natychmiastowe skalowanie podglądu wyciągnięcia wzdłuż normalnej (płynność w czasie rzeczywistym, zanim OCC policzy dokładny wynik)."""
        n = np.asarray(normal, float)
        n = n / np.linalg.norm(n)
        o = np.asarray(origin, float)
        m = np.eye(3) + (float(factor) - 1.0) * np.outer(n, n)
        t = o - m @ o
        mat = QMatrix4x4(m[0, 0], m[0, 1], m[0, 2], t[0], m[1, 0], m[1, 1], m[1, 2], t[1], m[2, 0], m[2, 1], m[2, 2], t[2], 0, 0, 0, 1)
        for item in self.preview_items:
            item.setTransform(mat)
        self.update()

    def set_preview_mesh(self, mesh, color=(.25, .55, .95, .55), line_color=(.1, .25, .5, 1), width=1.5, dashed=False):
        for item in self.preview_items:
            self.removeItem(item)
        self.preview_items = []
        if mesh is not None:
            if len(mesh.triangles):
                item = OverMesh(vertexes=mesh.vertices, faces=mesh.triangles, smooth=False, color=color, drawEdges=False)
                item.setGLOptions('translucent')
                self.addItem(item)
                self.preview_items.append(item)
            for points in mesh.edges.values():
                if dashed:
                    seg = self._dashed(points)
                    if seg is None:
                        continue
                    line = gl.GLLinePlotItem(pos=seg, color=line_color, width=width, antialias=True, mode='lines')
                else:
                    line = gl.GLLinePlotItem(pos=points, color=line_color, width=width, antialias=True)
                self.addItem(line)
                self.preview_items.append(line)
        self.update()

    def set_selection_meshes(self, meshes, color=(1, .55, .1, .55), line_color=(.95, .42, .02, 1)):
        """Trwałe podświetlenie wybranych ścian / profili (świeci się, dopóki operacja trwa)."""
        for item in getattr(self, 'selection_items', []):
            self.removeItem(item)
        self.selection_items = []
        for mesh in meshes or []:
            if mesh is None:
                continue
            if len(mesh.triangles):
                item = OverMesh(vertexes=mesh.vertices, faces=mesh.triangles, smooth=False, color=color, drawEdges=False)
                item.setGLOptions('translucent')
                self.addItem(item)
                self.selection_items.append(item)
            for points in mesh.edges.values():
                line = gl.GLLinePlotItem(pos=points, color=line_color, width=3.2, antialias=True)
                self.addItem(line)
                self.selection_items.append(line)
        self.update()

    def set_handles(self, handles):
        """Uchwyty-strzałki rysowane na wierzchu (Overlay2D): dict(id, start, tip, dir, color, label, min_px, ring=(środek, oś, promień)|None)."""
        self.handles = []
        for h in handles or []:
            d = np.asarray(h.get('dir', (0, 0, 1)), dtype=float)
            d = d / np.linalg.norm(d)
            tip = np.asarray(h.get('tip', h.get('start', (0, 0, 0))), dtype=float)
            start = np.asarray(h.get('start', tip - d), dtype=float)
            self.handles.append(dict(h, dir=d, tip=tip, start=start))
        self.update()

    def set_handle(self, tip, direction):
        self.set_handles([] if tip is None else [dict(id='ex', tip=tip, dir=direction)])

    def camera_dir(self):
        """Wersor od celu do kamery (świat)."""
        az, el = math.radians(float(self.opts['azimuth'])), math.radians(float(self.opts['elevation']))
        return np.array([math.cos(el) * math.cos(az), math.cos(el) * math.sin(az), math.sin(el)])

    def _cam_ppm(self):
        return (self.height() / 2) / (max(float(self.opts['distance']), 1e-6) * math.tan(math.radians(float(self.opts['fov']) / 2)))

    def handle_geometry(self, h):
        """Ekranowe położenie strzałki: start, koniec, kierunek jednostkowy i skala px/mm. Dopasowuje się do kamery:
        przy patrzeniu wzdłuż osi (skrót perspektywiczny) kierunek i skala są stabilizowane, więc uchwyt zawsze da się złapać."""
        s0 = self.project_one(h['start'])
        s1 = self.project_one(h['tip'])
        u = self.project_one(h['start'] + h['dir'] * 10.0)
        if s0 is None or s1 is None or u is None:
            return None
        dx, dy = u[0] - s0[0], u[1] - s0[1]
        length = math.hypot(dx, dy)
        cam = self._cam_ppm()
        ppm = length / 10.0
        if length < 3.0:
            ux, uy = 0.0, -1.0
        else:
            ux, uy = dx / length, dy / length
        floor = .4 * cam
        foreshortened = ppm < floor
        ppm_eff = max(ppm, floor)
        minimum = h.get('min_px', 44)
        signed = float(np.dot(h['tip'] - h['start'], h['dir']))
        end = s1
        if foreshortened or math.hypot(s1[0] - s0[0], s1[1] - s0[1]) < minimum:
            px = signed * ppm_eff
            if abs(px) < minimum:
                px = minimum if signed >= 0 else -minimum
            if minimum == 0:
                px = signed * ppm_eff
            end = (s0[0] + ux * px, s0[1] + uy * px)
        return dict(start=s0, end=end, ux=ux, uy=uy, px_per_mm=ppm_eff)

    def _seg_dist(self, x, y, a, b):
        dx, dy = b[0] - a[0], b[1] - a[1]
        l2 = dx * dx + dy * dy
        t = 0.0 if l2 < 1e-9 else max(0.0, min(1.0, ((x - a[0]) * dx + (y - a[1]) * dy) / l2))
        return math.hypot(x - (a[0] + t * dx), y - (a[1] + t * dy))

    def _ring_points(self, h):
        c, axis, radius = (np.asarray(h['ring'][0], float), np.asarray(h['ring'][1], float), float(h['ring'][2]))
        e1 = np.cross(axis, (0, 0, 1.0) if abs(axis[2]) < .9 else (1.0, 0, 0))
        e1 /= np.linalg.norm(e1)
        e2 = np.cross(axis, e1)
        return np.array([c + radius * (np.cos(a) * e1 + np.sin(a) * e2) for a in np.linspace(0, 2 * np.pi, 97)])

    def _grab_handle(self, x, y):
        """Najbliższy uchwyt pod kursorem: strzałki i osie mają pierwszeństwo, potem pierścienie, na końcu kwadraty płaszczyzn."""
        best = None
        for h in self.handles:
            kind = h.get('kind', 'arrow')
            try:
                if kind in ('arrow', 'axis'):
                    geo = self.handle_geometry(h)
                    if geo is None:
                        continue
                    d = min(math.hypot(x - geo['end'][0], y - geo['end'][1]) - 6, self._seg_dist(x, y, geo['start'], geo['end']))
                    ok, rank = d <= 12, 0
                elif kind == 'ring':
                    xy, _, _ = self.project_points(self._ring_points(h))
                    d = min(self._seg_dist(x, y, xy[i], xy[i + 1]) for i in range(len(xy) - 1))
                    ok, rank = d <= 10, 1
                else:
                    pts = [self.project_one(q) for q in h['quad']]
                    if any(q is None for q in pts):
                        continue
                    inside = QPolygonF([QPointF(*q) for q in pts]).containsPoint(QPointF(x, y), Qt.OddEvenFill)
                    d, ok, rank = 0.0, inside, 2
            except Exception:
                continue
            if ok and (best is None or (rank, d) < (best[0], best[1])):
                best = (rank, d, h)
        return best[2] if best else None

    # ---------- przeciąganie uchwytów: promień kursora → oś / płaszczyzna / pierścień (zawsze zgodnie z kamerą) ----------
    @staticmethod
    def _line_param(ray, p0, d):
        """Parametr t punktu osi p0 + t·d najbliższego promieniowi kursora; None, gdy promień jest równoległy do osi."""
        o, r = ray
        w0 = o - p0
        b, dd, e = float(r @ d), float(r @ w0), float(d @ w0)
        den = 1.0 - b * b
        if den < .02:
            return None
        return (e - b * dd) / den

    @staticmethod
    def _ray_plane(ray, origin, normal):
        o, r = ray
        den = float(r @ normal)
        if abs(den) < 1e-4:
            return None
        t = float((origin - o) @ normal) / den
        return o + r * t if t > 0 else None

    def _begin_drag(self, h, x, y):
        ray = self._ray(x, y)
        if ray is None:
            return None
        kind = h.get('kind', 'arrow')
        st = dict(id=h['id'], kind=kind, x0=x, y0=y, geo=self.handle_geometry(h) if kind in ('arrow', 'axis') else None)
        if kind in ('arrow', 'axis'):
            st['line'] = (np.asarray(h['start'], float), np.asarray(h['dir'], float))
            st['t0'] = self._line_param(ray, *st['line'])
        elif kind == 'plane':
            st['plane'] = (np.asarray(h['plane_origin'], float), np.asarray(h['normal'], float))
            st['hit0'] = self._ray_plane(ray, *st['plane'])
        elif kind == 'ring':
            c, axis, radius = (np.asarray(h['ring'][0], float), np.asarray(h['ring'][1], float), float(h['ring'][2]))
            e1 = np.cross(axis, (0, 0, 1.0) if abs(axis[2]) < .9 else (1.0, 0, 0))
            e1 /= np.linalg.norm(e1)
            st.update(c=c, axis=axis, radius=radius, e1=e1, e2=np.cross(axis, e1), total=0.0)
            hit = self._ray_plane(ray, c, axis)
            st['ang'] = None if hit is None else math.atan2(float((hit - c) @ st['e2']), float((hit - c) @ e1))
        return st

    def _drag_to(self, st, x, y):
        ray = self._ray(x, y)
        if ray is None:
            return
        kind = st['kind']
        if kind in ('arrow', 'axis'):
            t = self._line_param(ray, *st['line'])
            if st['t0'] is not None and t is not None:
                self.handleDragged.emit(st['id'], float(t - st['t0']))
            elif st['t0'] is None and st['geo'] is not None:
                g = st['geo']
                self.handleDragged.emit(st['id'], ((x - st['x0']) * g['ux'] + (y - st['y0']) * g['uy']) / g['px_per_mm'])
        elif kind in ('plane', 'free'):
            hit = self._ray_plane(ray, *st['plane'])
            if hit is not None and st['hit0'] is not None:
                self.pointDragged.emit(st['id'], hit - st['hit0'])
        elif kind == 'ring':
            hit = self._ray_plane(ray, st['c'], st['axis'])
            if hit is None or st['ang'] is None:
                return
            ang = math.atan2(float((hit - st['c']) @ st['e2']), float((hit - st['c']) @ st['e1']))
            delta = (ang - st['ang'] + math.pi) % (2 * math.pi) - math.pi
            st['ang'] = ang
            st['total'] += delta
            self.handleDragged.emit(st['id'], st['total'] * st['radius'])

    def _update_hover_handle(self, pos):
        if not self.handles and not self.free_drag:
            if self.hover_handle is not None:
                self.hover_handle = None
                self.overlay.update()
            return
        h = self._grab_handle(pos.x(), pos.y())
        hid = h['id'] if h else None
        if hid != self.hover_handle:
            self.hover_handle = hid
            self.setCursor(Qt.OpenHandCursor if hid else Qt.ArrowCursor)
            self.overlay.update()

    def pick_body(self, x, y):
        ray = self._ray(x, y)
        hit = self._hit(*ray) if ray else None
        return hit[1] if hit else None

    def pick_face(self, x, y):
        """Zwraca (id bryły, normalna, punkt) dla trójkąta pod kursorem albo None."""
        ray = self._ray(x, y)
        if ray is None:
            return None
        origin, direction = ray
        best = None
        for body in self.bodies:
            if not body.visible or not body.mesh or not len(body.mesh.triangles):
                continue
            tri = body.mesh.vertices[body.mesh.triangles]
            e1, e2 = tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]
            h = np.cross(np.broadcast_to(direction, e2.shape), e2)
            a = np.einsum('ij,ij->i', e1, h)
            f = np.divide(1., a, out=np.zeros_like(a), where=np.abs(a) > 1e-9)
            sv = origin - tri[:, 0]
            u = f * np.einsum('ij,ij->i', sv, h)
            q = np.cross(sv, e1)
            v = f * np.einsum('j,ij->i', direction, q)
            t = f * np.einsum('ij,ij->i', e2, q)
            ok = (np.abs(a) > 1e-9) & (u >= -1e-6) & (v >= -1e-6) & (u + v <= 1 + 1e-6) & (t > 1e-6)
            if ok.any():
                idx = np.where(ok)[0][int(np.argmin(t[ok]))]
                if best is None or t[idx] < best[0]:
                    n = np.cross(e1[idx], e2[idx])
                    n = n / max(np.linalg.norm(n), 1e-12)
                    best = (float(t[idx]), body.id, n, origin + direction * t[idx])
        return None if best is None else (best[1], best[2], best[3])

    def pick_profile(self, x, y):
        """Identyfikator szkicu, którego zamknięty obrys obejmuje punkt pod kursorem."""
        best = None
        for body in self.bodies:
            if body.kind != 'sketch' or not body.visible or not body.mesh:
                continue
            try:
                if not body.shape.IsClosed():
                    continue
            except Exception:
                pass
            hit = self._plane_hit(body.plane, x, y)
            if not hit:
                continue
            frame = kernel.frame_of(body.plane)
            o, ux, uy = np.array(frame.origin), np.array(frame.xdir), np.array(frame.ydir)
            px, py = kernel.uv_of(body.plane, hit[1])
            crossings = 0
            for points in body.mesh.edges.values():
                rel = points.astype(float) - o
                us, vs = rel @ ux, rel @ uy
                ax, ay, bx, by = us[:-1], vs[:-1], us[1:], vs[1:]
                straddle = (ay > py) != (by > py)
                with np.errstate(divide='ignore', invalid='ignore'):
                    xc = ax + (py - ay) * (bx - ax) / (by - ay)
                crossings += int(np.count_nonzero(straddle & (xc > px)))
            if crossings % 2 == 1 and (best is None or hit[0] < best[0]):
                best = (hit[0], body.id)
        return best[1] if best else None

    # ---------- siatka szkicu, płaszczyzna ściany, kamera, znacznik ----------
    def set_grid_frame(self, plane):
        """Siatka leży na płaszczyźnie szkicu (None = XY)."""
        self._grid_plane = plane
        self._grid_key = None
        self.update()

    def show_custom_plane(self, frame, half=30.0, color=(1.0, .55, .1)):
        for item in self.custom_plane_items:
            self.removeItem(item)
        self.custom_plane_items = []
        if frame is not None:
            pts = np.array([kernel.to_world(frame, u, v) for u, v in ((-half, -half), (half, -half), (half, half), (-half, half))], dtype=np.float32)
            fill = gl.GLMeshItem(vertexes=pts, faces=np.array([[0, 1, 2], [0, 2, 3]]), color=(*color, .14), smooth=False, drawEdges=False)
            fill.setGLOptions('translucent')
            outline = gl.GLLinePlotItem(pos=np.array([*pts, pts[0]], dtype=np.float32), color=(*color, .9), width=2, antialias=True)
            for item in (fill, outline):
                self.addItem(item)
                self.custom_plane_items.append(item)
        self.update()

    def look_along(self, plane):
        """Kamera patrzy na płaszczyznę szkicu wprost (z jej strony normalnej)."""
        frame = kernel.frame_of(plane)
        n = np.array(frame.normal, float)
        self.opts['center'] = QVector3D(*[float(c) for c in frame.origin])
        self.setCameraPosition(elevation=math.degrees(math.asin(max(-1, min(1, n[2])))), azimuth=math.degrees(math.atan2(n[1], n[0])))

    def set_marker(self, point, color=None, label=None):
        """Znacznik przyciągania (pomarańczowe kółko z etykietą) - tylko gdy kursor złapał punkt, jak w wersji HTML."""
        self.snap_marker = None
        if point is not None and label:
            xy = self.project_one(point)
            if xy is not None:
                self.snap_marker = (xy, label)
        self.overlay.update()

    def camera_matrix(self):
        viewport = (0, 0, max(1,self.width()), max(1,self.height()))
        return self.projectionMatrix(viewport,viewport) * self.viewMatrix()

    def project_points(self, points):
        # Explicit Qt matrix data avoid NumPy/Qt row-major ambiguity.
        matrix = self.camera_matrix()
        m = np.array([[r.x(), r.y(), r.z(), r.w()] for r in (matrix.row(i) for i in range(4))])
        homogeneous = np.column_stack((points, np.ones(len(points)))) @ m.T
        w = homogeneous[:, 3]
        safe = np.where(np.abs(w) > 1e-12, w, np.nan)
        ndc = homogeneous[:, :3] / safe[:, None]
        xy = np.column_stack(((ndc[:, 0] + 1) * self.width() / 2, (1 - ndc[:, 1]) * self.height() / 2))
        return xy, ndc[:, 2], w

    def nearest_edge(self, x, y, solids_only=False, kinds=None):
        best, distance = None, 10.
        for body in self.bodies:
            if not body.visible or not body.mesh or (solids_only and body.kind != 'solid') or (kinds and body.kind not in kinds):
                continue
            for index, points in body.mesh.edges.items():
                xy, z, w = self.project_points(points)
                if len(xy) < 2:
                    continue
                a, b = xy[:-1], xy[1:]
                delta = b - a
                denom = (delta * delta).sum(axis=1)
                t = np.clip(((np.array([x, y]) - a) * delta).sum(axis=1) / np.maximum(denom, 1e-12), 0, 1)
                projected = a + delta * t[:, None]
                dist = np.linalg.norm(projected - [x, y], axis=1)
                dist[(w[:-1] <= 0) | (w[1:] <= 0)] = np.inf
                if not np.isfinite(dist).any():
                    continue
                j = int(np.nanargmin(dist))
                if dist[j] < distance:
                    world = points[j] + (points[j + 1] - points[j]) * t[j]
                    if self.xray or self._visible_point(world):
                        distance, best = float(dist[j]), (body.id, index)
        return best

    def _ray(self, x, y):
        inverse, ok = (self.camera_matrix()).inverted()
        if not ok:
            return None
        from PySide6.QtGui import QVector4D
        pts = []
        for z in (-1, 1):
            p = inverse.map(QVector3D(float(2*x/self.width()-1), float(1-2*y/self.height()), float(z)))
            pts.append(np.array([p.x(), p.y(), p.z()]))
        direction = pts[1] - pts[0]
        return pts[0], direction / np.linalg.norm(direction)

    def _hit(self, origin, direction):
        best = None
        for body in self.bodies:
            if not body.visible or not body.mesh or not len(body.mesh.triangles):
                continue
            v = body.mesh.vertices[body.mesh.triangles]
            e1, e2 = v[:, 1]-v[:, 0], v[:, 2]-v[:, 0]
            h = np.cross(np.broadcast_to(direction, e2.shape), e2)
            a = np.einsum('ij,ij->i', e1, h)
            f = np.divide(1., a, out=np.zeros_like(a), where=np.abs(a)>1e-9)
            s = origin-v[:, 0]
            u = f*np.einsum('ij,ij->i', s, h)
            q = np.cross(s, e1)
            vv = f*np.einsum('j,ij->i', direction, q)
            t = f*np.einsum('ij,ij->i', e2, q)
            mask=(np.abs(a)>1e-9)&(u>=-1e-6)&(vv>=-1e-6)&(u+vv<=1+1e-6)&(t>1e-6)
            if mask.any():
                value=float(t[mask].min())
                if best is None or value<best[0]:
                    best=(value,body.id)
        return best

    def _visible_point(self, point):
        xy, _, _ = self.project_points(np.asarray([point]))
        ray = self._ray(*xy[0])
        if ray is None:
            return False
        origin, direction = ray
        hit = self._hit(origin, direction)
        return hit is None or hit[0] >= np.linalg.norm(point-origin)-.25

    def mouseMoveEvent(self, event):
        pos = event.position()
        buttons = event.buttons()
        if self._hook_active:
            self.drag_hook('move', pos.x(), pos.y())
            event.accept()
            return
        if self._handle_drag is not None:
            self._drag_to(self._handle_drag, pos.x(), pos.y())
            event.accept()
            return
        if self._sk_start is not None and buttons & Qt.LeftButton:
            point = self.plane_point(self.sketch_plane, pos.x(), pos.y())
            if point:
                end = self._snap(point, event)
                self._set_sketch_preview(self._sketch_outline(self.sketch_plane, self._sk_start, end))
                du, dv = end[0] - self._sk_start[0], end[1] - self._sk_start[1]
                if self.sketch_tool == 'rectangle':
                    self.sketchInfo.emit(f"Prostokąt {abs(du):.2f} × {abs(dv):.2f} mm")
                else:
                    self.sketchInfo.emit(f"Promień {math.hypot(du, dv):.2f} mm")
            event.accept()
            return
        if self._press and (buttons & Qt.RightButton or (buttons & Qt.LeftButton and event.modifiers() & Qt.ShiftModifier)):
            delta = pos - (self._drag_position or pos)
            self._drag_position = pos
            self.pan(delta.x(), delta.y(), 0, relative='view-upright')
            event.accept()
            return
        if self._press and self._press[2] == Qt.LeftButton and self.mouse_mode in ('orbit', 'pan'):
            previous = self._drag_position or pos
            delta = pos - previous
            self._drag_position = pos
            if self.mouse_mode == 'orbit':
                self.orbit(-delta.x(), delta.y())
            else:
                self.pan(delta.x(), delta.y(), 0, relative='view-upright')
            event.accept()
            return
        if not buttons:
            self._update_hover_handle(pos)
            self._hover(pos)
        super().mouseMoveEvent(event)

    def _hover(self, pos):
        now = time.monotonic()
        if now - self._hover_time < .04:
            return
        self._hover_time = now
        try:
            if self.click_mode and not self.plane_pick:
                if self.sketch_plane and self.sketch_tool:
                    if self.hover_gate is not None and not self.hover_gate():
                        if self.snap_marker is not None:
                            self.snap_marker = None
                            self.overlay.update()
                        return
                    point = self.plane_point(self.sketch_plane, pos.x(), pos.y())
                    if point:
                        u, v = self._snap(point, pos=pos)
                        self.sketchMoved.emit(self.sketch_plane, u, v)
                else:
                    self.viewHover.emit(pos.x(), pos.y())
                return
            if self.plane_pick:
                self._highlight_plane(self.plane_at(pos.x(), pos.y()))
                self.setCursor(Qt.PointingHandCursor)
                self.viewHover.emit(pos.x(), pos.y())
            elif self.edge_mode and self.mouse_mode == 'select':
                self._set_hover_edge(self.nearest_edge(pos.x(), pos.y()))
        except Exception:
            self._hover_key = None  # podświetlenie jest tylko pomocnicze

    def mousePressEvent(self, event):
        self._drag_position = event.position()
        self._press = (event.position().x(), event.position().y(), event.button())
        if self.drag_hook is not None and event.button() == Qt.LeftButton and not event.modifiers() & Qt.ShiftModifier:
            if self.drag_hook('press', event.position().x(), event.position().y()):
                self._hook_active = True
                self._press = None
                event.accept()
                return
        if (not self.click_mode and self.sketch_plane and self.sketch_tool and event.button() == Qt.LeftButton
                and not event.modifiers() & Qt.ShiftModifier):
            point = self.plane_point(self.sketch_plane, event.position().x(), event.position().y())
            if point:
                self._sk_start = self._snap(point, event)
                event.accept()
                return
        if self.handles and event.button() == Qt.LeftButton:
            grabbed = self._grab_handle(event.position().x(), event.position().y())
            if grabbed:
                self._handle_drag = self._begin_drag(grabbed, event.position().x(), event.position().y())
                if self._handle_drag is not None:
                    self.setCursor(Qt.ClosedHandCursor)
                    self._press = None
                    event.accept()
                    return
        if self.free_drag and event.button() == Qt.LeftButton and not event.modifiers() & Qt.ShiftModifier:
            x, y = event.position().x(), event.position().y()
            bid = self.pick_body(x, y)
            if bid is None:
                near = self.nearest_edge(x, y)
                bid = near[0] if near else None
            ray = self._ray(x, y)
            if bid == self.free_drag[0] and ray is not None:
                c = self.camera_dir()
                axis = np.zeros(3)
                axis[int(np.argmax(np.abs(c)))] = 1.0
                origin = np.asarray(self.free_drag[1], float)
                self._handle_drag = dict(id='free', kind='free', plane=(origin, axis), hit0=self._ray_plane(ray, origin, axis))
                self.setCursor(Qt.ClosedHandCursor)
                self._press = None
                event.accept()
                return
        if event.button() == Qt.RightButton or (event.button() == Qt.LeftButton and event.modifiers() & Qt.ShiftModifier):
            event.accept()  # przesuwanie widoku obsługujemy sami (prawy przycisk lub Shift + przeciąganie)
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if self._hook_active:
            self._hook_active = False
            self.drag_hook('release', event.position().x(), event.position().y())
            event.accept()
            return
        if self._handle_drag is not None:
            hid = self._handle_drag['id']
            self._handle_drag = None
            self.setCursor(Qt.OpenHandCursor if self.hover_handle else Qt.ArrowCursor)
            self.overlay.update()
            self.handleReleased.emit(hid)
            event.accept()
            return
        if self._sk_start is not None:
            start, self._sk_start = self._sk_start, None
            self._press = None
            point = self.plane_point(self.sketch_plane, event.position().x(), event.position().y())
            self._set_sketch_preview(None)
            if point:
                end = self._snap(point, event)
                if abs(end[0] - start[0]) > 1e-4 or abs(end[1] - start[1]) > 1e-4:
                    self.sketchDrawn.emit(self.sketch_plane, self.sketch_tool, start[0], start[1], end[0], end[1])
            event.accept()
            return
        super().mouseReleaseEvent(event)
        if not self._press:
            return
        x, y, button = self._press
        self._press = None
        moved = np.hypot(event.position().x()-x, event.position().y()-y) > 4
        if button == Qt.RightButton and not moved and self.click_mode:
            self.contextRequested.emit(x, y)
            return
        if button != Qt.LeftButton or moved:
            return
        if self.plane_pick:
            if self.click_mode:
                self.viewClicked.emit(x, y, bool(event.modifiers() & Qt.ShiftModifier), bool(event.modifiers() & Qt.ControlModifier))
                return
            name = self.plane_at(x, y)
            if name:
                self.planeClicked.emit(name)
            return
        if self.click_mode:
            if self.sketch_plane and self.sketch_tool:
                point = self.plane_point(self.sketch_plane, x, y)
                if point:
                    u, v = self._snap(point, event)
                    self.sketchClicked.emit(self.sketch_plane, u, v)
                return
            if self.mouse_mode == 'select':
                self.viewClicked.emit(x, y, bool(event.modifiers() & Qt.ShiftModifier), bool(event.modifiers() & Qt.ControlModifier))
            return
        if self.mouse_mode != "select" or self.sketch_plane:
            return
        shift = bool(event.modifiers() & Qt.ShiftModifier)
        additive = self.multi_select or bool(event.modifiers() & Qt.ControlModifier)
        if self.edge_mode:
            hit = self.nearest_edge(x, y)
            if hit:
                self.edgeClicked.emit(*hit, additive, shift)
            elif not additive:
                self.selectionCleared.emit()
        else:
            ray = self._ray(x, y)
            hit = self._hit(*ray) if ray else None
            if hit:
                self.bodyClicked.emit(hit[1], additive or shift)
            elif not additive and not shift:
                self.selectionCleared.emit()
