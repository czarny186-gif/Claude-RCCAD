"""Exact CAD geometry. No GUI or triangle-based Boolean operations."""
from __future__ import annotations
from dataclasses import dataclass
from math import isfinite
from pathlib import Path
import cadquery as cq
import numpy as np
from OCP.BRep import BRep_Tool
from OCP.Bnd import Bnd_Box
from OCP.BRepBndLib import BRepBndLib
from OCP.GeomAbs import GeomAbs_C0
from OCP.StlAPI import StlAPI_Reader
from OCP.TopoDS import TopoDS_Shape


class CadError(ValueError):
    """A recoverable modelling error: the document must remain unchanged."""


def positive(value, label="Wymiar"):
    value = float(value)
    if not isfinite(value) or not 1e-5 <= value <= 1e6:
        raise CadError(f"{label}: podaj dodatnią liczbę od 0,00001 do 1 000 000 mm.")
    return value


def valid(shape, solid=True):
    if shape is None or shape.wrapped.IsNull() or not shape.isValid():
        raise CadError("Nie udało się utworzyć poprawnej geometrii. Model pozostaje bez zmian.")
    if solid and (not shape.Solids() or shape.Volume() <= 1e-8):
        raise CadError("Operacja nie utworzyła zamkniętej bryły. Sprawdź położenie i wymiary.")
    return shape


def point_state(shape, point, tol=1e-4):
    """'in' / 'on' / 'out' - położenie punktu względem bryły."""
    from OCP.BRepClass3d import BRepClass3d_SolidClassifier
    from OCP.TopAbs import TopAbs_IN, TopAbs_ON
    from OCP.gp import gp_Pnt
    state = BRepClass3d_SolidClassifier(shape.wrapped, gp_Pnt(*[float(c) for c in point]), tol).State()
    return 'in' if state == TopAbs_IN else ('on' if state == TopAbs_ON else 'out')


def bounds(shape):
    # Measurements must not depend on the display tessellation's deflection.
    box = Bnd_Box()
    BRepBndLib.AddOptimal_s(shape.wrapped, box, False, False)
    return cq.BoundBox(box)


def box(x, y, z):
    return valid(cq.Solid.makeBox(*(positive(v) for v in (x, y, z))))


def cylinder(radius, height):
    return valid(cq.Solid.makeCylinder(positive(radius, "Promień"), positive(height, "Wysokość")))


def sketch(kind, plane, width, height=0, x=0, y=0, sides=6):
    if not plane_ok(plane):
        raise CadError("Nieznana płaszczyzna szkicu.")
    wp_ = wp(plane).center(float(x), float(y))
    width = positive(width)
    if kind == "rectangle":
        return wp_.rect(width, positive(height)).wire().val()
    if kind == "circle":
        return wp_.circle(width / 2).wire().val()
    if kind == "polygon":
        if not 3 <= int(sides) <= 128:
            raise CadError("Wielokąt musi mieć od 3 do 128 boków.")
        return wp_.polygon(int(sides), width).wire().val()
    raise CadError("Nieznany typ szkicu.")


PLANE_AXES = {"XY": (0, 1), "XZ": (0, 2), "YZ": (1, 2)}


@dataclass(frozen=True)
class Frame:
    """Dowolna płaszczyzna szkicu (np. ściana bryły): początek, oś U (xdir) i normalna; oś V = normalna × U."""
    origin: tuple
    xdir: tuple
    normal: tuple

    @property
    def ydir(self):
        n, x = np.array(self.normal, float), np.array(self.xdir, float)
        return tuple(float(c) for c in np.cross(n, x))

    def to_dict(self):
        return dict(origin=list(self.origin), xdir=list(self.xdir), normal=list(self.normal))

    @staticmethod
    def from_dict(d):
        def v3(x):
            t = tuple(float(c) for c in x)
            if len(t) != 3 or not all(isfinite(c) for c in t):
                raise CadError("Nieprawidłowa płaszczyzna szkicu.")
            return t
        f = Frame(v3(d["origin"]), v3(d["xdir"]), v3(d["normal"]))
        if abs(float(np.dot(f.xdir, f.normal))) > 1e-6 or abs(float(np.linalg.norm(f.normal)) - 1) > 1e-6 or abs(float(np.linalg.norm(f.xdir)) - 1) > 1e-6:
            raise CadError("Nieprawidłowa płaszczyzna szkicu.")
        return f


STANDARD = {
    "XY": Frame((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 0.0, 1.0)),
    "XZ": Frame((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, -1.0, 0.0)),
    "YZ": Frame((0.0, 0.0, 0.0), (0.0, 1.0, 0.0), (1.0, 0.0, 0.0)),
}


def plane_ok(plane):
    return isinstance(plane, Frame) or plane in STANDARD


def frame_of(plane):
    if isinstance(plane, Frame):
        return plane
    if plane not in STANDARD:
        raise CadError("Nieznana płaszczyzna szkicu.")
    return STANDARD[plane]


def wp(plane):
    f = frame_of(plane)
    return cq.Workplane(cq.Plane(origin=f.origin, xDir=f.xdir, normal=f.normal))


def face_frame(origin, normal):
    """Płaszczyzna szkicu na ścianie: U poziomo (wzdłuż osi Z × normalna), a dla ścian poziomych wzdłuż X."""
    n = np.array(normal, float)
    n = n / np.linalg.norm(n)
    x = np.array([1.0, 0, 0]) if abs(n[2]) > .9 else np.cross([0, 0, 1.0], n)
    x = x / np.linalg.norm(x)
    r = lambda a: tuple(round(float(c), 12) for c in a)
    return Frame(r(origin), r(x), r(n))


def uv_of(plane, point):
    f = frame_of(plane)
    d = np.array(point, float) - np.array(f.origin, float)
    return float(d @ np.array(f.xdir)), float(d @ np.array(f.ydir))


def to_world(plane, u, v):
    """Współrzędne szkicu (U, V) -> punkt 3D (dla XY/XZ/YZ zgodne z cq.Workplane)."""
    f = frame_of(plane)
    p = np.array(f.origin) + np.array(f.xdir) * u + np.array(f.ydir) * v
    return float(p[0]), float(p[1]), float(p[2])


def sketch_from_drag(kind, plane, u0, v0, u1, v1, sides=6):
    """Argumenty dla sketch() z przeciągnięcia myszą: prostokąt = dwa rogi, okrąg i wielokąt = środek i punkt na obwodzie."""
    if not plane_ok(plane):
        raise CadError("Nieznana płaszczyzna szkicu.")
    u0, v0, u1, v1 = (float(x) for x in (u0, v0, u1, v1))
    if not all(isfinite(x) for x in (u0, v0, u1, v1)):
        raise CadError("Nieprawidłowe współrzędne szkicu.")
    if kind == "rectangle":
        if abs(u1 - u0) < 1e-4 or abs(v1 - v0) < 1e-4:
            raise CadError("Prostokąt jest za mały.")
        return dict(kind=kind, plane=plane, width=abs(u1 - u0), height=abs(v1 - v0), x=(u0 + u1) / 2, y=(v0 + v1) / 2)
    if kind in ("circle", "polygon"):
        radius = float(np.hypot(u1 - u0, v1 - v0))
        if radius < 1e-4:
            raise CadError("Figura jest za mała.")
        return dict(kind=kind, plane=plane, width=2 * radius, x=u0, y=v0, sides=int(sides))
    raise CadError("Nieznany typ szkicu.")


def edges_at_point(shape, point, tol=2e-3):
    """Indeksy krawędzi bryły schodzących się w wierzchołku `point` (zaokrąglenie / faza narożnika obejmuje wszystkie)."""
    p = np.asarray(point, dtype=float)
    out = []
    for i, edge in enumerate(shape.Edges()):
        if edge.Length() < 1e-6:
            continue
        if any(float(np.linalg.norm(np.array(edge.positionAt(t).toTuple()) - p)) < tol for t in (0.0, 1.0)):
            out.append(i)
    return out


def face_edge_indices(shape, point):
    """Ściana najbliższa punktowi i indeksy wszystkich jej krawędzi (do obróbki całego obwodu ściany naraz)."""
    vertex = cq.Vertex.makeVertex(*[float(c) for c in point])
    face = min(shape.Faces(), key=lambda f: f.distance(vertex))
    own = face.Edges()
    return face, [i for i, e in enumerate(shape.Edges()) if any(e.isSame(o) for o in own)]


def edge_chain(shape, index, max_angle=8.0):
    """Indeksy krawędzi tworzących łańcuch styczny (G1) z krawędzią `index` - jak Shift+klik w wersji HTML."""
    edges = shape.Edges()
    if not 0 <= index < len(edges):
        raise CadError("Nieprawidłowa krawędź.")
    key = lambda p: tuple(round(c, 4) for c in p.toTuple())
    joints = {}
    for i, edge in enumerate(edges):
        if edge.Length() < 1e-6:
            continue
        for param in (0.0, 1.0):
            joints.setdefault(key(edge.positionAt(param)), []).append((i, param))
    limit = np.cos(np.radians(max_angle))
    def direction(i, param):
        t = edges[i].tangentAt(param)
        v = np.array(t.toTuple(), dtype=float)
        n = np.linalg.norm(v)
        return v / n if n > 1e-12 else None
    chain, stack = {index}, [index]
    while stack:
        i = stack.pop()
        for param in (0.0, 1.0):
            here = direction(i, param)
            if here is None:
                continue
            for j, pj in joints.get(key(edges[i].positionAt(param)), []):
                if j in chain:
                    continue
                there = direction(j, pj)
                if there is not None and abs(float(here @ there)) >= limit:
                    chain.add(j)
                    stack.append(j)
    return chain


def sketch_shape(kind, plane, points, sides=5):
    """Zamknięty profil szkicu z punktów klikniętych w (U, V) - jak w wersji HTML.

    rect: dwa narożniki; centerRect: środek i narożnik; circle: środek i punkt na okręgu;
    circle2: końce średnicy; circle3: trzy punkty; ellipse: środek i narożnik opisanego prostokąta;
    slot: oba środki końców i punkt określający szerokość; polygon: środek i wierzchołek.
    """
    if not plane_ok(plane):
        raise CadError("Nieznana płaszczyzna szkicu.")
    pts = [(float(u), float(v)) for u, v in points]
    need = {"rect": 2, "centerRect": 2, "circle": 2, "circle2": 2, "circle3": 3, "ellipse": 2, "slot": 3, "polygon": 2}
    if kind not in need:
        raise CadError("Nieznany typ szkicu.")
    if len(pts) < need[kind] or not all(isfinite(c) for p in pts for c in p):
        raise CadError("Za mało punktów szkicu.")
    dist = lambda a, b: float(np.hypot(a[0] - b[0], a[1] - b[1]))
    tiny = 1e-4
    if kind in ("rect", "centerRect"):
        (u0, v0), (u1, v1) = pts[:2]
        if kind == "centerRect":
            u0, v0, u1, v1 = 2 * u0 - u1, 2 * v0 - v1, u1, v1
        return sketch(**sketch_from_drag("rectangle", plane, u0, v0, u1, v1))
    if kind == "circle":
        return sketch(**sketch_from_drag("circle", plane, *pts[0], *pts[1]))
    if kind == "polygon":
        return sketch(**sketch_from_drag("polygon", plane, *pts[0], *pts[1], sides=sides))
    wp_ = wp(plane)
    if kind == "circle2":
        (a, b) = pts[:2]
        d = dist(a, b)
        if d < tiny:
            raise CadError("Okrąg jest za mały.")
        return wp_.center((a[0] + b[0]) / 2, (a[1] + b[1]) / 2).circle(d / 2).wire().val()
    if kind == "circle3":
        (ax, ay), (bx, by), (cx, cy) = pts[:3]
        d = 2 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
        if abs(d) < 1e-9:
            raise CadError("Trzy punkty leżą na jednej prostej - nie wyznaczają okręgu.")
        ux = ((ax**2 + ay**2) * (by - cy) + (bx**2 + by**2) * (cy - ay) + (cx**2 + cy**2) * (ay - by)) / d
        uy = ((ax**2 + ay**2) * (cx - bx) + (bx**2 + by**2) * (ax - cx) + (cx**2 + cy**2) * (bx - ax)) / d
        return wp_.center(ux, uy).circle(float(np.hypot(ax - ux, ay - uy))).wire().val()
    if kind == "ellipse":
        (cx, cy), (ex, ey) = pts[:2]
        rx, ry = abs(ex - cx), abs(ey - cy)
        if rx < tiny or ry < tiny:
            raise CadError("Elipsa jest za mała.")
        return wp_.center(cx, cy).ellipse(rx, ry).wire().val()
    # slot: dwa środki końców i punkt szerokości (odległość od osi = promień zaokrąglenia)
    (ax, ay), (bx, by), (wx, wy) = pts[:3]
    length = dist((ax, ay), (bx, by))
    if length < tiny:
        raise CadError("Szczelina jest za krótka.")
    ux, uy = (bx - ax) / length, (by - ay) / length
    radius = abs((wx - ax) * -uy + (wy - ay) * ux)
    if radius < tiny:
        raise CadError("Szczelina jest za wąska.")
    angle = float(np.degrees(np.arctan2(by - ay, bx - ax)))
    return wp_.center((ax + bx) / 2, (ay + by) / 2).slot2D(length + 2 * radius, 2 * radius, angle).wire().val()


def mirror_plane(shape, normal, origin):
    """Odbicie względem dowolnej płaszczyzny (np. wskazanej ściany)."""
    n = np.asarray(normal, dtype=float)
    length = float(np.linalg.norm(n))
    if length < 1e-9:
        raise CadError("Nieprawidłowa płaszczyzna odbicia.")
    n /= length
    return valid(shape.mirror(tuple(float(x) for x in n), tuple(float(x) for x in origin)), bool(shape.Solids()))


NORMALS = {"XY": (0, 0, 1), "XZ": (0, -1, 0), "YZ": (1, 0, 0)}


def extrude(wire, plane, distance, symmetric=False):
    distance = float(distance)
    if not isfinite(distance) or abs(distance) < 1e-5:
        raise CadError("Odległość wyciągnięcia musi być różna od zera.")
    normal = cq.Vector(*frame_of(plane).normal).multiply(distance)
    base = wire.translate(normal.multiply(-.5)) if symmetric else wire
    if not base.IsClosed():
        raise CadError("Profil musi być zamknięty.")
    return valid(cq.Solid.extrudeLinear(base, [], normal))


def boolean(operation, base, tools):
    if not tools:
        raise CadError("Wybierz co najmniej dwie bryły w drzewie modelu.")
    try:
        if operation == "union":
            result = base.fuse(*tools)
        elif operation == "subtract":
            result = base.cut(*tools)
        elif operation == "intersect":
            result = base.intersect(*tools)
        else:
            raise CadError("Nieznana operacja na bryłach.")
        return valid(result.clean())
    except CadError:
        raise
    except Exception as exc:
        raise CadError("Operacja na bryłach nie powiodła się. Sprawdź ich przecięcie.") from exc


def blend(shape, indices, size, kind="fillet"):
    size = positive(size, "Promień / odległość")
    edges = shape.Edges()
    ids = sorted(set(indices))
    if not ids or any(i < 0 or i >= len(edges) for i in ids):
        raise CadError("Zaznacz krawędzie bryły. Shift + klik dodaje kolejne.")
    selected = [edges[i] for i in ids]
    try:
        # OpenCascade solves all selected edges and their common corners together.
        result = shape.fillet(size, selected) if kind == "fillet" else shape.chamfer(size, None, selected)
        return valid(result)
    except CadError:
        raise
    except Exception as exc:
        raise CadError("Ten promień / faza nie mieści się w geometrii. Zmniejsz wartość lub wybierz mniej krawędzi.") from exc


def hole(shape, radius, x, y, depth=0):
    radius = positive(radius, "Promień otworu")
    box_bounds = bounds(shape)
    depth = float(depth)
    if depth < 0 or not isfinite(depth):
        raise CadError("Głębokość musi być dodatnia lub równa zero dla otworu przelotowego.")
    height = box_bounds.zlen + 2 if depth == 0 else positive(depth) + 1
    bottom = box_bounds.zmin - 1 if depth == 0 else box_bounds.zmax - depth
    tool = cq.Solid.makeCylinder(radius, height, (float(x), float(y), bottom))
    result = boolean("subtract", shape, [tool])
    if shape.Volume() - result.Volume() < 1e-6:
        raise CadError("Otwór nie przecina bryły. Sprawdź współrzędne środka.")
    return result


def transform(shape, translation=(0, 0, 0), rotation=(0, 0, 0)):
    if not all(isfinite(float(v)) for v in (*translation, *rotation)):
        raise CadError("Współrzędne muszą być skończonymi liczbami.")
    center = shape.Center().toTuple()
    result = shape
    for axis, angle in zip(((1, 0, 0), (0, 1, 0), (0, 0, 1)), rotation):
        if angle:
            end = tuple(center[i] + axis[i] for i in range(3))
            result = result.rotate(center, end, float(angle))
    return valid(result.translate(tuple(float(v) for v in translation)), bool(shape.Solids()))


PATTERN_MAX = 400


def _unit(v):
    v = np.asarray(v, dtype=float)
    n = float(np.linalg.norm(v))
    if n < 1e-12:
        raise CadError("Nieprawidłowy kierunek.")
    return v / n


def pattern_ops(kind, p):
    """Kopie szyku (bez oryginału) jako lista operacji: ('t', (x, y, z)) - przesunięcie, ('r', oś, punkt, kąt°) - obrót.
    kind: 'rect' (counts, spacing), 'circ' (axis, pivot, count, angle) albo 'path' (points, count, fit, spacing)."""
    ops = []
    if kind == "rect":
        nx, ny, nz = (max(1, int(c)) for c in p["counts"])
        dx, dy, dz = (float(c) for c in p["spacing"])
        if nx * ny * nz > PATTERN_MAX:
            raise CadError(f"Zbyt wiele kopii (maksymalnie {PATTERN_MAX}).")
        for i in range(nx):
            for j in range(ny):
                for k in range(nz):
                    if (i, j, k) != (0, 0, 0):
                        ops.append(("t", (i * dx, j * dy, k * dz)))
    elif kind == "circ":
        n = max(1, int(p["count"]))
        if n > PATTERN_MAX:
            raise CadError(f"Zbyt wiele kopii (maksymalnie {PATTERN_MAX}).")
        total = float(p["angle"])
        axis = tuple(float(c) for c in _unit(p["axis"]))
        step = total / n if abs(abs(total) - 360.0) < 1e-9 else (total / (n - 1) if n > 1 else 0.0)
        pivot = tuple(float(c) for c in p["pivot"])
        offset = tuple(float(c) for c in p.get("offset", (0.0, 0.0, 0.0)))
        for i in range(1, n):
            ops.append(("r", axis, pivot, i * step, offset))
    elif kind == "path":
        pts = np.asarray(p["points"], dtype=float)
        if len(pts) < 2:
            raise CadError("Wskaż linię lub krawędź jako ścieżkę.")
        seg = np.linalg.norm(np.diff(pts, axis=0), axis=1)
        cum = np.concatenate([[0.0], np.cumsum(seg)])
        length = float(cum[-1])
        if length < 1e-9:
            raise CadError("Ścieżka ma zerową długość.")
        n = max(1, int(p["count"]))
        if n > PATTERN_MAX:
            raise CadError(f"Zbyt wiele kopii (maksymalnie {PATTERN_MAX}).")
        if p.get("fit", True):
            dist = np.linspace(0.0, length, n) if n > 1 else np.zeros(1)
        else:
            step = max(float(p.get("spacing", 10.0)), 1e-6)
            dist = np.arange(n) * step
            dist = dist[dist <= length + 1e-9]
        at = lambda d: np.array([np.interp(d, cum, pts[:, k]) for k in range(3)])
        base = at(0.0)
        for d in dist[1:]:
            ops.append(("t", tuple(float(c) for c in at(float(d)) - base)))
    else:
        raise CadError("Nieznany rodzaj szyku.")
    return ops


def op_matrix(op):
    """Macierz 4x4 operacji szyku (do natychmiastowego podglądu bez OCC)."""
    m = np.eye(4)
    if op[0] == "t":
        m[:3, 3] = op[1]
        return m
    axis, pivot, ang = _unit(op[1]), np.asarray(op[2], dtype=float), np.radians(op[3])
    k = np.array([[0, -axis[2], axis[1]], [axis[2], 0, -axis[0]], [-axis[1], axis[0], 0]])
    r = np.eye(3) + np.sin(ang) * k + (1 - np.cos(ang)) * (k @ k)
    m[:3, :3] = r
    m[:3, 3] = pivot - r @ pivot
    if len(op) > 4:      # najpierw przesunięcie promieniowe (odległość od środka), potem obrót
        m[:3, 3] = m[:3, 3] + r @ np.asarray(op[4], dtype=float)
    return m


def apply_op(shape, op):
    if op[0] == "t":
        return shape.translate(tuple(float(c) for c in op[1]))
    pivot = tuple(float(c) for c in op[2])
    end = tuple(pivot[i] + float(op[1][i]) for i in range(3))
    if len(op) > 4 and any(abs(float(c)) > 1e-12 for c in op[4]):
        shape = shape.translate(tuple(float(c) for c in op[4]))
    return shape.rotate(pivot, end, float(op[3]))


def pattern_mesh(mesh, ops, original=True):
    """Siatka podglądu szyku: kopie siatki bazowej przekształcone macierzami (czysty numpy, więc płynnie w czasie rzeczywistym).
    original=False pomija nieprzesunięty oryginał (gdy pierwszą operacją jest jego przesunięcie na zadaną odległość)."""
    vertices, triangles, edges = [], [], {}
    key, offset = 0, 0
    if original:
        vertices.append(mesh.vertices.astype(np.float32))
        triangles.append(mesh.triangles)
        offset = len(mesh.vertices)
        for points in mesh.edges.values():
            edges[key] = points
            key += 1
    for op in ops:
        m = op_matrix(op)
        vertices.append((mesh.vertices @ m[:3, :3].T + m[:3, 3]).astype(np.float32))
        triangles.append(mesh.triangles + offset)
        offset += len(mesh.vertices)
        for points in mesh.edges.values():
            edges[key] = (points @ m[:3, :3].T + m[:3, 3]).astype(np.float32)
            key += 1
    return DisplayMesh(np.vstack(vertices), np.vstack(triangles) if len(mesh.triangles) else mesh.triangles, edges, mesh.center, mesh.size)


def mirror(shape, plane):
    return valid(shape.mirror(plane), bool(shape.Solids()))


def import_shapes(path):
    path = Path(path)
    try:
        if path.suffix.lower() in (".step", ".stp"):
            root = cq.importers.importStep(str(path)).val()
            return [(valid(s), "solid") for s in root.Solids()]
        if path.suffix.lower() in (".brep", ".brp"):
            root = cq.importers.importBrep(str(path)).val()
            return [(valid(s), "solid") for s in root.Solids()]
        if path.suffix.lower() == ".stl":
            shape = TopoDS_Shape()
            if not StlAPI_Reader().Read(shape, str(path)):
                raise CadError("Nie można odczytać pliku STL.")
            return [(valid(cq.Shape.cast(shape), False), "mesh")]
        if path.suffix.lower() == ".dxf":
            wp = cq.importers.importDXF(str(path))
            return [(valid(w, False), "sketch") for w in wp.wires().vals()]
        raise CadError("Obsługiwane formaty: STEP, BREP, STL i DXF.")
    except CadError:
        raise
    except Exception as exc:
        raise CadError(f"Nie można odczytać pliku {path.name}.") from exc


def export_shapes(shapes, path):
    if not shapes:
        raise CadError("Brak geometrii do eksportu.")
    path = Path(path)
    formats = {".step": "STEP", ".stp": "STEP", ".stl": "STL", ".brep": "BREP", ".dxf": "DXF"}
    fmt = formats.get(path.suffix.lower())
    if not fmt:
        raise CadError("Wybierz rozszerzenie STEP, STL, BREP lub DXF.")
    compound = shapes[0] if len(shapes) == 1 else cq.Compound.makeCompound(shapes)
    cq.exporters.export(compound, str(path), exportType=fmt, tolerance=.05, angularTolerance=.08)


@dataclass
class DisplayMesh:
    vertices: np.ndarray
    triangles: np.ndarray
    # Entries refer to the original topological edge IDs, not triangle edges.
    edges: dict[int, np.ndarray]
    center: tuple[float, float, float]
    size: float


def display_mesh(shape, tolerance=.12):
    vertices, triangles = shape.tessellate(tolerance, .12)
    edge_faces = {}
    faces = shape.Faces()
    for face in faces:
        for edge in face.Edges():
            edge_faces.setdefault(edge.hashCode(), []).append(face)
    edges = {}
    for i, edge in enumerate(shape.Edges()):
        adjacent = edge_faces.get(edge.hashCode(), [])
        if len(adjacent) == 1 and BRep_Tool.IsClosed_s(edge.wrapped, adjacent[0].wrapped):
            continue  # Periodic seam of a cylinder/torus is not a physical edge.
        if len(adjacent) == 2:
            try:
                if BRep_Tool.Continuity_s(edge.wrapped, adjacent[0].wrapped, adjacent[1].wrapped) != GeomAbs_C0:
                    continue  # Do not draw/pick smooth fillet seams as sharp edges.
            except Exception:
                pass
        length = edge.Length()
        if length < 1e-6:
            continue
        count = 2 if edge.geomType() == "LINE" else min(96, max(16, int(length / 1.0)))
        points = edge.positions(np.linspace(0, 1, count))
        edges[i] = np.asarray([p.toTuple() for p in points], dtype=np.float32)
    box_bounds = bounds(shape)
    return DisplayMesh(np.asarray([v.toTuple() for v in vertices], dtype=np.float32).reshape(-1, 3),
                       np.asarray(triangles, dtype=np.uint32).reshape(-1, 3), edges,
                       box_bounds.center.toTuple(), max(box_bounds.xlen, box_bounds.ylen, box_bounds.zlen, 1))


# ---------- etap 2: linie, łuki, punkty, prostokąt 3-punktowy, okrąg styczny, tekst, SVG ----------
def _vec(plane, p):
    return cq.Vector(*to_world(plane, float(p[0]), float(p[1])))


def polyline(plane, points, closed=False):
    """Łamana (lub zamknięty wielokąt) z punktów (U, V)."""
    if not plane_ok(plane):
        raise CadError("Nieznana płaszczyzna szkicu.")
    pts = [(float(u), float(v)) for u, v in points]
    clean = [pts[0]]
    for p in pts[1:]:
        if np.hypot(p[0] - clean[-1][0], p[1] - clean[-1][1]) > 1e-4:
            clean.append(p)
    if closed and len(clean) > 2 and np.hypot(clean[0][0] - clean[-1][0], clean[0][1] - clean[-1][1]) <= 1e-4:
        clean.pop()
    if len(clean) < 2 or (closed and len(clean) < 3):
        raise CadError("Za mało różnych punktów.")
    seq = clean + [clean[0]] if closed else clean
    edges = [cq.Edge.makeLine(_vec(plane, a), _vec(plane, b)) for a, b in zip(seq[:-1], seq[1:])]
    return cq.Wire.assembleEdges(edges)


def arc3(plane, points):
    (a, b, c) = points[:3]
    d = 2 * (a[0] * (b[1] - c[1]) + b[0] * (c[1] - a[1]) + c[0] * (a[1] - b[1]))
    if abs(d) < 1e-9:
        raise CadError("Trzy punkty leżą na jednej prostej - nie wyznaczają łuku.")
    return cq.Wire.assembleEdges([cq.Edge.makeThreePointArc(_vec(plane, a), _vec(plane, b), _vec(plane, c))])


def rect3(plane, points):
    """Prostokąt 3-punktowy: dwa punkty podstawy i punkt określający wysokość."""
    (ax, ay), (bx, by), (cx, cy) = [(float(u), float(v)) for u, v in points[:3]]
    length = float(np.hypot(bx - ax, by - ay))
    if length < 1e-4:
        raise CadError("Podstawa prostokąta jest za krótka.")
    ux, uy = (bx - ax) / length, (by - ay) / length
    h = (cx - ax) * -uy + (cy - ay) * ux
    if abs(h) < 1e-4:
        raise CadError("Wysokość prostokąta jest za mała.")
    nx, ny = -uy * h, ux * h
    return polyline(plane, [(ax, ay), (bx, by), (bx + nx, by + ny), (ax + nx, ay + ny)], True)


def point_marker(plane, p, size=.6):
    return wp(plane).center(float(p[0]), float(p[1])).circle(size).wire().val()


def _line_uv(edge, plane):
    return uv_of(plane, edge.startPoint().toTuple()), uv_of(plane, edge.endPoint().toTuple())


def circle_tangent2(plane, line1, line2, hint):
    """Okrąg styczny do dwóch prostych (każda jako para punktów UV); środek na dwusiecznej bliższej punktowi `hint`."""
    def norm(l):
        (ax, ay), (bx, by) = l
        n = float(np.hypot(bx - ax, by - ay))
        if n < 1e-9:
            raise CadError("Linia jest zdegenerowana.")
        dx, dy = (bx - ax) / n, (by - ay) / n
        return ax, ay, dx, dy
    ax, ay, dx1, dy1 = norm(line1)
    bx, by, dx2, dy2 = norm(line2)
    det = dx1 * -dy2 - dy1 * -dx2
    if abs(det) < 1e-9:
        raise CadError("Linie są równoległe - okrąg styczny nie jest jednoznaczny.")
    t = ((bx - ax) * -dy2 - (by - ay) * -dx2) / det
    px, py = ax + t * dx1, ay + t * dy1
    best = None
    for s in (1, -1):
        bxv, byv = dx1 + s * dx2, dy1 + s * dy2
        n = float(np.hypot(bxv, byv))
        if n < 1e-9:
            continue
        bxv, byv = bxv / n, byv / n
        proj = (hint[0] - px) * bxv + (hint[1] - py) * byv
        cx, cy = px + bxv * proj, py + byv * proj
        dist = abs((cx - px) * -dy1 + (cy - py) * dx1)
        gap = float(np.hypot(hint[0] - cx, hint[1] - cy))
        if dist > 1e-4 and (best is None or gap < best[0]):
            best = (gap, cx, cy, dist)
    if best is None:
        raise CadError("Nie można wyznaczyć okręgu stycznego.")
    return wp(plane).center(best[1], best[2]).circle(best[3]).wire().val()


_STYLE_WORDS = {"bold", "italic", "oblique", "regular", "normal"}


def font_file(family, bold=False, italic=False):
    """Ścieżka pliku czcionki zainstalowanej w Windows (rejestr Fonts) dla rodziny i stylu; None, gdy brak / inny system."""
    import sys
    if sys.platform != "win32" or not family:
        return None
    try:
        import os
        import winreg
        wanted = ({"bold"} if bold else set()) | ({"italic"} if italic else set())
        best = None
        for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            try:
                key = winreg.OpenKey(root, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts")
            except OSError:
                continue
            i = 0
            while True:
                try:
                    name, value, _ = winreg.EnumValue(key, i)
                except OSError:
                    break
                i += 1
                base = name.rsplit(" (", 1)[0]
                for part in base.split(" & "):
                    words = part.split()
                    low = [w.lower() for w in words]
                    k = len(words)
                    while k > 0 and low[k - 1] in _STYLE_WORDS:
                        k -= 1
                    if " ".join(words[:k]).lower() != family.lower():
                        continue
                    style = {w for w in low[k:] if w in _STYLE_WORDS} - {"regular", "normal"}
                    style = {"italic" if w == "oblique" else w for w in style}
                    path = value if os.path.isabs(value) else os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", value)
                    if not os.path.exists(path):
                        alt = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "Windows", "Fonts", value)
                        path = alt if os.path.exists(alt) else None
                    if path is None:
                        continue
                    score = (style == wanted, -len(style ^ wanted), not path.lower().endswith(".ttc"))
                    if best is None or score > best[0]:
                        best = (score, path)
        return best[1] if best else None
    except Exception:
        return None


_TEXT_CACHE = {}
_TEXT_REF = 10.0   # wysokość odniesienia: napis liczymy raz, a rozmiar / obrót / położenie to tanie przekształcenia druty


def _text_direct(plane, text, size, font, bold, italic, halign):
    fr = frame_of(plane)
    n0, o0 = np.array(fr.normal), np.array(fr.origin)
    kind = "bold" if bold else ("italic" if italic else "regular")
    for name, path in ((font, font_file(font, bold, italic)), ("Arial", font_file("Arial", bold, italic)), ("Sans", None)):
        try:
            solid = wp(plane).text(text, float(size), 0.2, combine=False, font=name, fontPath=path, kind=kind,
                                   halign=halign, valign="bottom").val()
        except Exception:
            continue
        wires = [w for f in (solid.Faces() if solid is not None else [])
                 if abs(float((np.array(f.Center().toTuple()) - o0) @ n0)) < 1e-5 and abs(abs(float(np.array(f.normalAt().toTuple()) @ n0)) - 1) < 1e-3
                 for w in f.Wires()]
        if wires:
            return wires
    raise CadError("Nie udało się utworzyć tekstu (brak czcionki lub znaków w czcionce).")


def _text_base(plane, text, font, bold, italic, halign):
    key = (frame_of(plane), text, font, bool(bold), bool(italic), halign)
    wires = _TEXT_CACHE.get(key)
    if wires is None:
        wires = _text_direct(plane, text, _TEXT_REF, font, bold, italic, halign)
        if len(_TEXT_CACHE) > 24:
            _TEXT_CACHE.clear()
        _TEXT_CACHE[key] = wires
    return wires


def text_extent(plane, text, font="Arial", bold=False, italic=False, halign="left"):
    """Obrys napisu (umin, vmin, umax, vmax) w układzie szkicu dla wysokości odniesienia 10 mm i kotwicy w punkcie (0, 0)."""
    text = str(text).strip()
    if not text:
        raise CadError("Wpisz treść tekstu.")
    wires = _text_base(plane, text, font, bold, italic, halign)
    pts = np.array([uv_of(plane, e.positionAt(t).toTuple()) for w in wires for e in w.Edges() for t in (0.0, .25, .5, .75, 1.0)], dtype=float)
    return float(pts[:, 0].min()), float(pts[:, 1].min()), float(pts[:, 0].max()), float(pts[:, 1].max())


def text_shape(plane, text, u, v, size=10.0, font="Arial", bold=False, halign="left", angle=0.0, italic=False):
    """Kontury liter na płaszczyźnie szkicu: zewnętrzne i wewnętrzne (otwory w a, e, o, ą…) jako osobne druty.
    Czcionka: rodzina zainstalowana w systemie (w Windows z pliku czcionki, więc działają polskie znaki)."""
    text = str(text).strip()
    if not text:
        raise CadError("Wpisz treść tekstu.")
    size = float(size)
    if not isfinite(size) or size <= 0:
        raise CadError("Wysokość liter musi być dodatnia.")
    fr = frame_of(plane)
    n0, o0 = np.array(fr.normal, float), np.array(fr.origin, float)
    wires = _text_base(plane, text, font, bold, italic, halign)
    factor = size / _TEXT_REF
    try:
        back = cq.Vector(*o0)
        wires = [w.translate(back * -1).scale(factor).translate(back) for w in wires] if abs(factor - 1) > 1e-9 else list(wires)
    except Exception:
        wires = _text_direct(plane, text, size, font, bold, italic, halign)
    if abs(float(angle)) > 1e-9:
        pivot = cq.Vector(*o0)
        wires = [w.rotate(pivot, pivot + cq.Vector(*n0), float(angle)) for w in wires]
    shift = cq.Vector(*(np.array(to_world(plane, float(u), float(v)), float) - o0))
    return [w.translate(shift) for w in wires]


def profile_normal(shape, reference):
    """Rzeczywista normalna płaskiego profilu (także po obrocie / przesunięciu szkicu), zwrócona zgodnie z płaszczyzną odniesienia."""
    ref = np.asarray(reference, dtype=float)
    try:
        wires = shape.Wires() if hasattr(shape, "Wires") else [shape]
        n = np.array(cq.Face.makeFromWires(wires[0]).normalAt().toTuple(), dtype=float)
        n = n / np.linalg.norm(n)
    except Exception:
        return tuple(ref)
    if float(n @ ref) < 0:
        n = -n
    return tuple(float(c) for c in n)


def actual_frame(shape, plane, tol=1e-4):
    """Płaszczyzna, w której naprawdę leży szkic: ta sama, jeśli nie ruszano szkicu; po obrocie / przesunięciu - nowa Frame wyliczona z geometrii."""
    fr = frame_of(plane)
    n0, o0 = np.array(fr.normal, float), np.array(fr.origin, float)
    try:
        pts = np.array([e.positionAt(t).toTuple() for e in shape.Edges() for t in (0.0, .37, .71, 1.0)], dtype=float)
        if len(pts) and float(np.max(np.abs((pts - o0) @ n0))) < tol:
            return plane
        n = np.array(profile_normal(shape, n0), dtype=float)
        origin = n * float(n @ pts[0])
        x = np.array(fr.xdir, float) - n * float(np.array(fr.xdir, float) @ n)
        if np.linalg.norm(x) < 1e-6:
            x = np.cross(n, [0.0, 0.0, 1.0] if abs(n[2]) < .9 else [1.0, 0.0, 0.0])
        x = x / np.linalg.norm(x)
        r = lambda a: tuple(round(float(c), 9) + 0.0 for c in a)
        return Frame(r(origin), r(x), r(n))
    except Exception:
        return plane


def extrude2(wire, plane, d1, d2):
    """Wyciągnięcie w dwie strony niezależnie: d1 po normalnej, d2 przeciwnie."""
    d1, d2 = float(d1), float(d2)
    if not isfinite(d1) or not isfinite(d2) or d1 < 0 or d2 < 0 or d1 + d2 < 1e-5:
        raise CadError("Obie odległości muszą być nieujemne, a ich suma większa od zera.")
    n = cq.Vector(*frame_of(plane).normal)
    base = wire.translate(n.multiply(-d2))
    if not base.IsClosed():
        raise CadError("Profil musi być zamknięty.")
    return valid(cq.Solid.extrudeLinear(base, [], n.multiply(d1 + d2)))


def remove_edge(shape, index):
    """Nożyczki: usuwa jedną krawędź szkicu; zwraca listę pozostałych krawędzi złożonych w druty (może być pusta)."""
    edges = shape.Edges()
    if not 0 <= index < len(edges):
        raise CadError("Nieprawidłowa krawędź.")
    rest = [e for i, e in enumerate(edges) if i != index]
    if not rest:
        return []
    try:
        return [cq.Wire.assembleEdges(rest)]
    except Exception:
        return [cq.Wire.assembleEdges([e]) for e in rest]


def svg_profiles(path, plane="XY"):
    """Prosty import SVG: rect, circle, ellipse, polygon, polyline oraz path z M/L/H/V/Z (współrzędne mm, oś Y odwrócona)."""
    import re
    import xml.etree.ElementTree as ET
    text = Path(path).read_text(encoding="utf-8", errors="ignore")
    if len(text) > 5_000_000:
        raise CadError("Plik SVG jest zbyt duży.")
    root = ET.fromstring(text)
    num = lambda s: [float(x) for x in re.findall(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?", s or "")]
    flip = lambda p: (p[0], -p[1])
    out = []
    for el in root.iter():
        tag = el.tag.split("}")[-1]
        g = lambda k, d=0.0: float(num(el.get(k))[0]) if num(el.get(k)) else d
        try:
            if tag == "rect":
                x, y, w, h = g("x"), g("y"), g("width"), g("height")
                out.append(polyline(plane, [flip(p) for p in [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]], True))
            elif tag == "circle":
                out.append(wp(plane).center(g("cx"), -g("cy")).circle(g("r")).wire().val())
            elif tag == "ellipse":
                out.append(wp(plane).center(g("cx"), -g("cy")).ellipse(g("rx"), g("ry")).wire().val())
            elif tag in ("polygon", "polyline"):
                n = num(el.get("points"))
                pts = [flip((n[i], n[i + 1])) for i in range(0, len(n) - 1, 2)]
                out.append(polyline(plane, pts, tag == "polygon"))
            elif tag == "path":
                subs, cur, pos, start = [], [], (0.0, 0.0), (0.0, 0.0)
                for cmd, args in re.findall(r"([MmLlHhVvZz])([^MmLlHhVvZz]*)", el.get("d", "")):
                    n = num(args)
                    rel = cmd.islower()
                    c = cmd.upper()
                    if c == "Z":
                        if len(cur) > 2:
                            subs.append((cur, True))
                        cur, pos = [], start
                    elif c in "ML":
                        for i in range(0, len(n) - 1, 2):
                            pos = (pos[0] + n[i], pos[1] + n[i + 1]) if rel else (n[i], n[i + 1])
                            if c == "M" and i == 0:
                                if len(cur) > 1:
                                    subs.append((cur, False))
                                cur, start = [pos], pos
                            else:
                                cur.append(pos)
                    elif c == "H":
                        for v in n:
                            pos = (pos[0] + v if rel else v, pos[1]); cur.append(pos)
                    elif c == "V":
                        for v in n:
                            pos = (pos[0], pos[1] + v if rel else v); cur.append(pos)
                if len(cur) > 1:
                    subs.append((cur, False))
                for pts, closed in subs:
                    out.append(polyline(plane, [flip(p) for p in pts], closed))
        except CadError:
            continue
    if not out:
        raise CadError("W pliku SVG nie znaleziono obsługiwanych kształtów (prostokąt, okrąg, elipsa, wielokąt, ścieżka z liniami).")
    return out


def extrude_dir(wire, normal, d1, d2=0.0, symmetric=False):
    """Wyciągnięcie wzdłuż dowolnej normalnej (np. ściany bryły). d1 > 0 po normalnej, d1 < 0 przeciwnie."""
    d1, d2 = float(d1), float(d2)
    n = np.asarray(normal, dtype=float)
    n = n / np.linalg.norm(n)
    nv = cq.Vector(*[float(x) for x in n])
    if symmetric:
        base, total = wire.translate(nv.multiply(-d1 / 2)), d1
    else:
        base, total = wire.translate(nv.multiply(-d2)) if d2 else wire, d1 + d2
    if not isfinite(total) or abs(total) < 1e-5:
        raise CadError("Odległość wyciągnięcia musi być różna od zera.")
    if not base.IsClosed():
        raise CadError("Profil musi być zamknięty.")
    return valid(cq.Solid.extrudeLinear(base, [], nv.multiply(total)))


def face_at(shape, normal, point, tol=1e-3):
    """Płaska ściana bryły o danej normalnej zawierająca punkt (do wyciągania ścian)."""
    n = np.asarray(normal, dtype=float)
    n = n / np.linalg.norm(n)
    vertex = cq.Vertex.makeVertex(*[float(x) for x in point])
    for face in shape.Faces():
        if face.geomType() != "PLANE":
            continue
        fn = np.array(face.normalAt().toTuple())
        if abs(float(fn @ n)) > .999 and face.distance(vertex) < max(tol, 1e-3):
            return face, fn
    raise CadError("Wskazana ściana nie jest płaska.")


def edge_handle(shape, index):
    """Środek krawędzi i kierunek (do wnętrza bryły, po dwusiecznej ścian) - położenie strzałki zaokrąglenia / fazy."""
    edge = shape.Edges()[index]
    mid = edge.positionAt(.5)
    total = np.zeros(3)
    for face in shape.Faces():
        if any(e.isSame(edge) for e in face.Edges()):
            total += np.array(face.normalAt(mid).toTuple())
    n = np.linalg.norm(total)
    if n < 1e-6:
        t = np.array(edge.tangentAt(.5).toTuple())
        total = np.cross(t, (0, 0, 1.0) if abs(t[2]) < .9 else (1.0, 0, 0))
        n = np.linalg.norm(total)
    return mid.toTuple(), tuple(float(c) for c in -total / n)


# ---------- szkice łączą się jak w wersji HTML: obszary, przycinanie między przecięciami ----------
def _tolist(shapes):
    from OCP.TopTools import TopTools_ListOfShape
    lst = TopTools_ListOfShape()
    for s in shapes:
        lst.Append(s)
    return lst


def _fromlist(lst):
    return [s for s in lst]


def split_edges(edges):
    """General Fuse: dzieli krawędzie w punktach przecięcia. Zwraca dla każdej krawędzi wejściowej listę jej kawałków."""
    from OCP.BOPAlgo import BOPAlgo_Builder
    builder = BOPAlgo_Builder()
    for e in edges:
        builder.AddArgument(e.wrapped)
    builder.SetRunParallel(False)
    builder.Perform()
    if builder.HasErrors():
        raise CadError("Nie udało się połączyć szkiców.")
    out = []
    for e in edges:
        pieces = [cq.Shape.cast(m) for m in _fromlist(builder.Modified(e.wrapped))]
        pieces = [p for p in pieces if p.geomType() is not None and p.Length() > 1e-6]
        if pieces:
            out.append(pieces)
        elif builder.IsDeleted(e.wrapped):
            out.append([])
        else:
            out.append([e])
    return out


def regions(plane, edges, wires=()):
    """Wszystkie obszary ograniczone krawędziami szkiców (jak 'region' w HTML): nakładające się kształty tną się nawzajem."""
    from OCP.BOPAlgo import BOPAlgo_BuilderFace
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace
    from OCP.gp import gp_Ax3, gp_Dir, gp_Pln, gp_Pnt
    if not edges:
        return []
    unique = []
    for pieces in split_edges(edges):
        for p in pieces:
            if not any(p.isSame(q) for q in unique):
                unique.append(p)
    frame = frame_of(plane)
    pln = gp_Pln(gp_Ax3(gp_Pnt(*[float(c) for c in frame.origin]), gp_Dir(*[float(c) for c in frame.normal]), gp_Dir(*[float(c) for c in frame.xdir])))
    face = BRepBuilderAPI_MakeFace(pln, -1e4, 1e4, -1e4, 1e4).Face()
    builder = BOPAlgo_BuilderFace()
    builder.SetFace(face)
    both = [p.wrapped for p in unique] + [p.wrapped.Reversed() for p in unique]   # każda krawędź graniczy z dwoma obszarami
    builder.SetShapes(_tolist(both))
    builder.Perform()
    out = []
    for shape in ([] if builder.HasErrors() else _fromlist(builder.Areas())):
        f = cq.Shape.cast(shape)
        try:
            if 1e-6 < f.Area() < 1e7 and f.outerWire().IsClosed():
                out.append(f)
        except Exception:
            continue
    try:
        alt = _regions_from_wires(wires)
    except Exception:
        alt = []
    return alt if len(alt) > len(out) else out


def _regions_from_wires(wires):
    """Obszary z zamkniętych konturów: ściany tną się nawzajem (General Fuse), więc część wspólna i reszty są osobnymi obszarami."""
    from OCP.BOPAlgo import BOPAlgo_Builder
    faces = []
    for w in wires:
        if w.IsClosed():
            try:
                faces.append(cq.Face.makeFromWires(w))
            except Exception:
                pass
    if not faces:
        return []
    builder = BOPAlgo_Builder()
    for f in faces:
        builder.AddArgument(f.wrapped)
    builder.SetRunParallel(False)
    builder.Perform()
    if builder.HasErrors():
        return []
    out = []
    for f in cq.Shape.cast(builder.Shape()).Faces():
        if f.Area() > 1e-6 and not any(f.isSame(q) for q in out):
            out.append(f)
    return out


def face_contains(face, point):
    from OCP.BRepClass import BRepClass_FaceClassifier
    from OCP.TopAbs import TopAbs_IN, TopAbs_ON
    from OCP.gp import gp_Pnt
    try:
        return BRepClass_FaceClassifier(face.wrapped, gp_Pnt(*[float(c) for c in point]), 1e-5).State() in (TopAbs_IN, TopAbs_ON)
    except Exception:
        return face.distance(cq.Vertex.makeVertex(*[float(c) for c in point])) < 1e-5


def extrude_face(face, normal, d1, d2=0.0, symmetric=False):
    """Wyciągnięcie ściany / obszaru (z otworami) wzdłuż normalnej: d1 > 0 po normalnej, d1 < 0 przeciwnie."""
    d1, d2 = float(d1), float(d2)
    n = np.asarray(normal, dtype=float)
    n = n / np.linalg.norm(n)
    nv = cq.Vector(*[float(x) for x in n])
    shift, total = (-d1 / 2, d1) if symmetric else (-d2, d1 + d2)
    if not isfinite(total) or abs(total) < 1e-5:
        raise CadError("Odległość wyciągnięcia musi być różna od zera.")
    move = (lambda w: w.translate(nv.multiply(shift))) if shift else (lambda w: w)
    return valid(cq.Solid.extrudeLinear(move(face.outerWire()), [move(w) for w in face.innerWires()], nv.multiply(total)))


def _chains(edges, tol=1e-4):
    """Układa krawędzie w łańcuchy (druty) według wspólnych końców."""
    key = lambda p: (round(p.x / tol), round(p.y / tol), round(p.z / tol))
    left, chains = list(edges), []
    while left:
        chain = [left.pop(0)]
        grown = True
        while grown:
            grown = False
            for e in list(left):
                a, b = key(e.startPoint()), key(e.endPoint())
                head, tail = key(chain[0].startPoint()), key(chain[-1].endPoint())
                if a == tail or b == tail:
                    chain.append(e if a == tail else cq.Edge(e.wrapped.Reversed()))
                elif a == head or b == head:
                    chain.insert(0, e if b == head else cq.Edge(e.wrapped.Reversed()))
                else:
                    continue
                left.remove(e)
                grown = True
        chains.append(chain)
    wires = []
    for chain in chains:
        try:
            wires.append(cq.Wire.assembleEdges(chain))
        except Exception:
            wires += [cq.Wire.assembleEdges([e]) for e in chain]
    return wires


def trim_pieces(bodies_edges, target):
    """Kawałki krawędzi szkicu `target` między punktami przecięcia z pozostałymi szkicami (lista krawędzi)."""
    flat, owner = [], []
    for i, edges in enumerate(bodies_edges):
        for e in edges:
            flat.append(e)
            owner.append(i)
    per = split_edges(flat)
    return [p for pieces, o in zip(per, owner) if o == target for p in pieces]


def trim_result(pieces, index):
    """Druty po usunięciu kawałka `index`."""
    rest = [p for i, p in enumerate(pieces) if i != index]
    return _chains(rest) if rest else []
