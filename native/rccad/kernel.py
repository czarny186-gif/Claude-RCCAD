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
    if plane not in ("XY", "XZ", "YZ"):
        raise CadError("Nieznana płaszczyzna szkicu.")
    wp = cq.Workplane(plane).center(float(x), float(y))
    width = positive(width)
    if kind == "rectangle":
        return wp.rect(width, positive(height)).wire().val()
    if kind == "circle":
        return wp.circle(width / 2).wire().val()
    if kind == "polygon":
        if not 3 <= int(sides) <= 128:
            raise CadError("Wielokąt musi mieć od 3 do 128 boków.")
        return wp.polygon(int(sides), width).wire().val()
    raise CadError("Nieznany typ szkicu.")


PLANE_AXES = {"XY": (0, 1), "XZ": (0, 2), "YZ": (1, 2)}


def to_world(plane, u, v):
    """Współrzędne szkicu (U, V) -> punkt 3D; zgodne z cq.Workplane('XY'/'XZ'/'YZ')."""
    return {"XY": (u, v, 0.0), "XZ": (u, 0.0, v), "YZ": (0.0, u, v)}[plane]


def sketch_from_drag(kind, plane, u0, v0, u1, v1, sides=6):
    """Argumenty dla sketch() z przeciągnięcia myszą: prostokąt = dwa rogi, okrąg i wielokąt = środek i punkt na obwodzie."""
    if plane not in PLANE_AXES:
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
    if plane not in PLANE_AXES:
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
    wp = cq.Workplane(plane)
    if kind == "circle2":
        (a, b) = pts[:2]
        d = dist(a, b)
        if d < tiny:
            raise CadError("Okrąg jest za mały.")
        return wp.center((a[0] + b[0]) / 2, (a[1] + b[1]) / 2).circle(d / 2).wire().val()
    if kind == "circle3":
        (ax, ay), (bx, by), (cx, cy) = pts[:3]
        d = 2 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
        if abs(d) < 1e-9:
            raise CadError("Trzy punkty leżą na jednej prostej - nie wyznaczają okręgu.")
        ux = ((ax**2 + ay**2) * (by - cy) + (bx**2 + by**2) * (cy - ay) + (cx**2 + cy**2) * (ay - by)) / d
        uy = ((ax**2 + ay**2) * (cx - bx) + (bx**2 + by**2) * (ax - cx) + (cx**2 + cy**2) * (bx - ax)) / d
        return wp.center(ux, uy).circle(float(np.hypot(ax - ux, ay - uy))).wire().val()
    if kind == "ellipse":
        (cx, cy), (ex, ey) = pts[:2]
        rx, ry = abs(ex - cx), abs(ey - cy)
        if rx < tiny or ry < tiny:
            raise CadError("Elipsa jest za mała.")
        return wp.center(cx, cy).ellipse(rx, ry).wire().val()
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
    return wp.center((ax + bx) / 2, (ay + by) / 2).slot2D(length + 2 * radius, 2 * radius, angle).wire().val()


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
    normal = cq.Vector(NORMALS[plane]).multiply(distance)
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
        result = valid(result)
        if result.Volume() >= shape.Volume() + 1e-5:
            raise CadError("Nieprawidłowy wynik operacji na krawędziach.")
        return result
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
        count = 2 if edge.geomType() == "LINE" else min(256, max(24, int(length / .5)))
        points = edge.positions(np.linspace(0, 1, count))
        edges[i] = np.asarray([p.toTuple() for p in points], dtype=np.float32)
    box_bounds = bounds(shape)
    return DisplayMesh(np.asarray([v.toTuple() for v in vertices], dtype=np.float32).reshape(-1, 3),
                       np.asarray(triangles, dtype=np.uint32).reshape(-1, 3), edges,
                       box_bounds.center.toTuple(), max(box_bounds.xlen, box_bounds.ylen, box_bounds.zlen, 1))
