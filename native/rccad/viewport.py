"""Native Qt/OpenGL viewport with picking against displayed CAD edge curves."""
from __future__ import annotations
import math
import time
import numpy as np
import pyqtgraph as pg
import pyqtgraph.opengl as gl
from pyqtgraph.opengl import shaders
from PySide6.QtCore import QPointF, Qt, Signal
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
SOLID_COLOR = (.54, .54, .56, 1)
SOLID_SELECTED = (.40, .60, .90, 1)
EDGE_COLOR = (0, 0, 0, 1)
SKETCH_COLOR = (.106, .427, .757, 1)
PREVIEW_COLOR = (1, .48, .05, 1)
PLANE_COLORS = {'XY': '#3b82f6', 'XZ': '#22a06b', 'YZ': '#e5484d'}
PLANE_HALF = 30.0
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
            for h in v.handles:
                geo = v.handle_geometry(h)
                if geo is None:
                    continue
                ring = h.get('ring')
                color = QColor.fromRgbF(*h.get('color', (.94, .6, .13, 1)))
                if ring:
                    c, axis, radius = (np.asarray(ring[0], float), np.asarray(ring[1], float), float(ring[2]))
                    e1 = np.cross(axis, (0, 0, 1.0) if abs(axis[2]) < .9 else (1.0, 0, 0))
                    e1 /= np.linalg.norm(e1)
                    e2 = np.cross(axis, e1)
                    pts = np.array([c + radius * (np.cos(a) * e1 + np.sin(a) * e2) for a in np.linspace(0, 2 * np.pi, 73)])
                    xy, _, w = v.project_points(pts)
                    pen = QPen(color, 3)
                    pen.setCapStyle(Qt.RoundCap)
                    p.setPen(pen)
                    p.setBrush(Qt.NoBrush)
                    p.drawPolyline(QPolygonF([QPointF(float(a), float(b)) for a, b in xy]))
                start, end = geo['start'], geo['end']
                pen = QPen(color, 5)
                pen.setCapStyle(Qt.RoundCap)
                p.setPen(pen)
                p.drawLine(QPointF(*start), QPointF(*end))
                p.setPen(Qt.NoPen)
                p.setBrush(color)
                p.drawEllipse(QPointF(*end), 10, 10)
                label = h.get('label')
                if label:
                    p.setPen(QColor('#ffffff'))
                    font = QFont('Segoe UI')
                    font.setBold(True)
                    font.setPixelSize(12)
                    p.setFont(font)
                    p.drawText(QPointF(end[0] - 4 * max(1, len(label)), end[1] + 4), label)
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
                        float diffuse = max(0.0, dot(normalize(v_normal), normalize(vec3(0.3, 0.6, 1.0))));
                        gl_FragColor = vec4(v_color.rgb * (0.58 + 0.42 * diffuse), v_color.a);
                    }
                """),
            ])
        self.setMouseTracking(True)   # bez tego widok nie dostaje ruchów myszy bez wciśniętego przycisku (brak podglądu na żywo)
        self.setBackgroundColor(BACKGROUND)
        self.setCameraPosition(distance=120, elevation=25, azimuth=-55)
        self.addItem(GradientBackground(BG_TOP, BG_BOTTOM))
        self.grid_items = []
        for size, step, color in ((600, 5, '#d1dcea'), (600, 25, '#a3b9cf')):
            grid = gl.GLGridItem()
            grid.setSize(size, size)
            grid.setSpacing(step, step)
            grid.setColor(pg.mkColor(color))
            self.addItem(grid)
            self.grid_items.append(grid)
        self.grid_item = self.grid_items[-1]
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
        self.snap_marker = None       # ((x, y), etykieta) - przyciąganie jak w wersji HTML
        self.snapper = None           # funkcja (x, y, (u, v)) -> (u, v, etykieta) ustawiana przez Studio
        self._cache = {}              # id bryły -> (klucz, elementy GL): bez przebudowy całej sceny przy każdej zmianie
        self.overlay = Overlay2D(self)
        self.overlay.setGeometry(0, 0, self.width(), self.height())
        self.overlay.raise_()

    def update(self, *args):
        super().update(*args)
        ov = getattr(self, 'overlay', None)
        if ov is not None:
            ov.update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.overlay.setGeometry(0, 0, self.width(), self.height())
        self.overlay.raise_()

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
            key = (id(mesh), tuple(color), picked, sel, body.kind)
            cached = self._cache.get(body.id)
            if cached is None or cached[0] != key:
                if cached is not None:
                    for item in cached[1]:
                        self.removeItem(item)
                items = []
                if len(mesh.triangles):
                    item = gl.GLMeshItem(vertexes=mesh.vertices, faces=mesh.triangles, smooth=True, color=color, shader='rccad', drawEdges=False)
                    item.setGLOptions('opaque')
                    self.addItem(item)
                    items.append(item)
                for index, points in mesh.edges.items():
                    hot = index in sel or picked
                    base = SKETCH_COLOR if body.kind == 'sketch' else EDGE_COLOR
                    line = gl.GLLinePlotItem(pos=points, color=PREVIEW_COLOR if hot else base, width=3.5 if hot else (2.3 if body.kind == 'sketch' else 1.5), antialias=False)
                    self.addItem(line)
                    items.append(line)
                self._cache[body.id] = (key, items)
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
        h = PLANE_HALF
        corners = {
            'XY': [(-h, -h, 0), (h, -h, 0), (h, h, 0), (-h, h, 0)],
            'XZ': [(-h, 0, -h), (h, 0, -h), (h, 0, h), (-h, 0, h)],
            'YZ': [(0, -h, -h), (0, h, -h), (0, h, h), (0, -h, h)],
        }
        for name, pts in corners.items():
            color = pg.mkColor(PLANE_COLORS[name])
            rgb = (color.redF(), color.greenF(), color.blueF())
            fill = gl.GLMeshItem(vertexes=np.array(pts, dtype=np.float32), faces=np.array([[0, 1, 2], [0, 2, 3]]),
                                 color=(*rgb, .16), smooth=False, drawEdges=False)
            fill.setGLOptions('translucent')
            outline = gl.GLLinePlotItem(pos=np.array([*pts, pts[0]], dtype=np.float32), color=(*rgb, .9), width=2, antialias=True)
            label = gl.GLTextItem(pos=np.array(pts[2], dtype=np.float32) * .92, text=name, color=QColor(PLANE_COLORS[name]))
            self.plane_items[name] = (fill, outline, label, rgb)

    def show_planes(self, visible, only=None):
        for name, (fill, outline, label, rgb) in self.plane_items.items():
            show = visible and (only is None or name == only)
            for item in (fill, outline, label):
                if show and item not in self.items:
                    self.addItem(item)
                elif not show and item in self.items:
                    self.removeItem(item)
        self._hover_plane = None
        self.update()

    def _highlight_plane(self, name):
        if name == self._hover_plane:
            return
        self._hover_plane = name
        for key, (fill, outline, label, rgb) in self.plane_items.items():
            fill.setColor((*rgb, .38 if key == name else .16))
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
                u, v = kernel.uv_of(name, hit[1])
                if abs(u) <= PLANE_HALF and abs(v) <= PLANE_HALF and (best is None or hit[0] < best[0]):
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

    def set_preview_mesh(self, mesh, color=(.25, .55, .95, .55), line_color=(.1, .25, .5, 1), width=1.5, dashed=False):
        for item in self.preview_items:
            self.removeItem(item)
        self.preview_items = []
        if mesh is not None:
            if len(mesh.triangles):
                item = gl.GLMeshItem(vertexes=mesh.vertices, faces=mesh.triangles, smooth=False, color=color, drawEdges=False)
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

    def set_handles(self, handles):
        """Uchwyty-strzałki rysowane na wierzchu (Overlay2D): dict(id, start, tip, dir, color, label, min_px, ring=(środek, oś, promień)|None)."""
        self.handles = []
        for h in handles or []:
            d = np.asarray(h['dir'], dtype=float)
            d = d / np.linalg.norm(d)
            tip = np.asarray(h['tip'], dtype=float)
            start = np.asarray(h.get('start', tip - d), dtype=float)
            self.handles.append(dict(h, dir=d, tip=tip, start=start))
        self.update()

    def set_handle(self, tip, direction):
        self.set_handles([] if tip is None else [dict(id='ex', tip=tip, dir=direction)])

    def handle_geometry(self, h):
        """Ekranowe położenie strzałki: start, koniec (min. 34 px) oraz kierunek jednostkowy i skala px/mm."""
        s0 = self.project_one(h['start'])
        s1 = self.project_one(h['tip'])
        u = self.project_one(h['start'] + h['dir'] * 10.0)
        if s0 is None or s1 is None or u is None:
            return None
        dx, dy = u[0] - s0[0], u[1] - s0[1]
        length = math.hypot(dx, dy)
        if length < 1e-3:
            return None
        end = s1
        minimum = h.get('min_px', 34)
        if math.hypot(s1[0] - s0[0], s1[1] - s0[1]) < minimum:
            end = (s0[0] + dx / length * minimum, s0[1] + dy / length * minimum)
        return dict(start=s0, end=end, ux=dx / length, uy=dy / length, px_per_mm=length / 10.0)

    def _grab_handle(self, x, y):
        best = None
        for h in self.handles:
            geo = self.handle_geometry(h)
            if geo is None:
                continue
            dist = math.hypot(x - geo['end'][0], y - geo['end'][1])
            if dist <= 16 and (best is None or dist < best[0]):
                best = (dist, h['id'], geo)
        return best

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
        frame = kernel.frame_of(plane or 'XY')
        m = QMatrix4x4()
        x, y, n, o = (np.array(v, float) for v in (frame.xdir, frame.ydir, frame.normal, frame.origin))
        m.setToIdentity()
        for r in range(3):
            m.setRow(r, QVector4D(float(x[r]), float(y[r]), float(n[r]), float(o[r])))
        for grid in self.grid_items:
            grid.setTransform(m)
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

    def nearest_edge(self, x, y):
        best, distance = None, 10.
        for body in self.bodies:
            if not body.visible or not body.mesh:
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
                    if self._visible_point(world):
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
        if self._handle_drag is not None:
            hid, x0, y0, geo = self._handle_drag
            self.handleDragged.emit(hid, ((pos.x() - x0) * geo['ux'] + (pos.y() - y0) * geo['uy']) / geo['px_per_mm'])
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
                self._handle_drag = (grabbed[1], event.position().x(), event.position().y(), grabbed[2])
                self._press = None
                event.accept()
                return
        if event.button() == Qt.RightButton or (event.button() == Qt.LeftButton and event.modifiers() & Qt.ShiftModifier):
            event.accept()  # przesuwanie widoku obsługujemy sami (prawy przycisk lub Shift + przeciąganie)
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if self._handle_drag is not None:
            hid = self._handle_drag[0]
            self._handle_drag = None
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
