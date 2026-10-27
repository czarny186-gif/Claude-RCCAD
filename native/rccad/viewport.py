"""Native Qt/OpenGL viewport with picking against displayed CAD edge curves."""
from __future__ import annotations
import math
import time
import numpy as np
import pyqtgraph as pg
import pyqtgraph.opengl as gl
from pyqtgraph.opengl import shaders
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QVector3D, QColor
from .document import Body
from . import kernel

# Wygląd jak w wersji HTML: jasne tło, niebieska siatka, jasnoszare bryły z czarnym obrysem.
BACKGROUND = '#f3f6fc'
GRID_COLOR = '#9fb6cf'
SOLID_COLOR = (.54, .54, .56, 1)
SOLID_SELECTED = (.40, .60, .90, 1)
EDGE_COLOR = (0, 0, 0, 1)
SKETCH_COLOR = (.15, .45, .85, 1)
PREVIEW_COLOR = (1, .48, .05, 1)
PLANE_COLORS = {'XY': '#3b82f6', 'XZ': '#22a06b', 'YZ': '#e5484d'}
PLANE_HALF = 30.0
VIEWS = {  # (elewacja, azymut) kamery pyqtgraph
    'iso': (25, -55), 'XY': (90, -90), 'XZ': (0, -90), 'YZ': (0, 0),
    'Z': (90, -90), '-Z': (-90, -90), 'X': (0, 0), '-X': (0, 180), 'Y': (0, 90), '-Y': (0, -90),
}


class CadView(gl.GLViewWidget):
    edgeClicked = Signal(str, int, bool, bool)  # bryła, krawędź, dodaj do zaznaczenia, cały łańcuch styczny
    planeClicked = Signal(str)
    sketchDrawn = Signal(str, str, float, float, float, float)
    sketchInfo = Signal(str)
    bodyClicked = Signal(str, bool)
    selectionCleared = Signal()

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
        self.setBackgroundColor(BACKGROUND)
        self.setCameraPosition(distance=120, elevation=25, azimuth=-55)
        grid = gl.GLGridItem()
        grid.setSize(200, 200)
        grid.setSpacing(10, 10)
        grid.setColor(pg.mkColor(GRID_COLOR))
        self.addItem(grid)
        self.grid_item = grid
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

    def set_models(self, bodies, selected_bodies=(), selected_edges=None):
        self._set_hover_edge(None)
        for item in self.model_items + self.highlight_items:
            self.removeItem(item)
        self.model_items, self.highlight_items = [], []
        self.bodies = tuple(bodies)
        self.selected_bodies = set(selected_bodies)
        self.selected_edges = selected_edges or {}
        for body in self.bodies:
            if not body.visible or body.mesh is None:
                continue
            mesh = body.mesh
            color = SOLID_SELECTED if body.id in self.selected_bodies else SOLID_COLOR
            if len(mesh.triangles):
                item = gl.GLMeshItem(vertexes=mesh.vertices, faces=mesh.triangles, smooth=True, color=color, shader='rccad', drawEdges=False)
                item.setGLOptions('opaque')
                self.addItem(item)
                self.model_items.append(item)
            for index, points in mesh.edges.items():
                selected = index in self.selected_edges.get(body.id, set())
                base = SKETCH_COLOR if body.kind == 'sketch' else EDGE_COLOR
                line = gl.GLLinePlotItem(pos=points, color=PREVIEW_COLOR if selected else base, width=4 if selected else (2.5 if body.kind == 'sketch' else 1.5), antialias=True)
                self.addItem(line)
                self.model_items.append(line)
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
        axis = {'XY': 2, 'XZ': 1, 'YZ': 0}[plane]
        if abs(direction[axis]) < 1e-9:
            return None
        t = -origin[axis] / direction[axis]
        if t <= 0:
            return None
        return t, origin + direction * t

    def plane_at(self, x, y):
        best = None
        for name in self.plane_items:
            if self.plane_items[name][0] not in self.items:
                continue
            hit = self._plane_hit(name, x, y)
            if hit and all(abs(c) <= PLANE_HALF for i, c in enumerate(hit[1]) if i != {'XY': 2, 'XZ': 1, 'YZ': 0}[name]):
                if best is None or hit[0] < best[0]:
                    best = (hit[0], name)
        return best[1] if best else None

    def plane_point(self, plane, x, y):
        hit = self._plane_hit(plane, x, y)
        if hit is None:
            return None
        i, j = kernel.PLANE_AXES[plane]
        return float(hit[1][i]), float(hit[1][j])

    def _snap(self, point, event=None):
        if event is not None and event.modifiers() & Qt.AltModifier:
            return point
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
        if now - self._hover_time < .06:
            return
        self._hover_time = now
        try:
            if self.plane_pick:
                self._highlight_plane(self.plane_at(pos.x(), pos.y()))
                self.setCursor(Qt.PointingHandCursor if self._hover_plane else Qt.ArrowCursor)
            elif self.edge_mode and self.mouse_mode == 'select':
                self._set_hover_edge(self.nearest_edge(pos.x(), pos.y()))
        except Exception:
            self._hover_key = None  # podświetlenie jest tylko pomocnicze

    def mousePressEvent(self, event):
        self._drag_position = event.position()
        self._press = (event.position().x(), event.position().y(), event.button())
        if (self.sketch_plane and self.sketch_tool and event.button() == Qt.LeftButton
                and not event.modifiers() & Qt.ShiftModifier):
            point = self.plane_point(self.sketch_plane, event.position().x(), event.position().y())
            if point:
                self._sk_start = self._snap(point, event)
                event.accept()
                return
        if event.button() == Qt.RightButton or (event.button() == Qt.LeftButton and event.modifiers() & Qt.ShiftModifier):
            event.accept()  # przesuwanie widoku obsługujemy sami (prawy przycisk lub Shift + przeciąganie)
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
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
        if button != Qt.LeftButton or np.hypot(event.position().x()-x, event.position().y()-y) > 4:
            return
        if self.plane_pick:
            name = self.plane_at(x, y)
            if name:
                self.planeClicked.emit(name)
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
