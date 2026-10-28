"""Przyciąganie kursora w szkicu — jak sketchSnapPoint w wersji HTML: punkty styku, środki, krawędzie, okręgi,
przecięcia i siatka dopasowana do powiększenia; w promieniu 12 px bliska geometria wygrywa z siatką."""
from __future__ import annotations
import math
import numpy as np
from . import kernel

LEVELS = (.01, .02, .05, .1, .2, .5, 1, 2, 5, 10)
RADIUS = 12.0


class SketchGeometry:
    """Punkty / odcinki / okręgi istniejących szkiców leżących na płaszczyźnie szkicowania (we współrzędnych u, v)."""

    def __init__(self, bodies, plane):
        self.points = []     # (u, v, etykieta, priorytet)
        self.segments = []
        self.circles = []
        for body in bodies:
            if body.kind != 'sketch' or not body.visible or body.plane != plane:
                continue
            try:
                self._add(body.shape, plane)
            except Exception:
                continue

    def _add(self, shape, plane):
        uv = lambda p: kernel.uv_of(plane, p.toTuple())
        for edge in shape.Edges():
            kind = edge.geomType()
            a, b = uv(edge.startPoint()), uv(edge.endPoint())
            if kind == 'LINE':
                self.points += [(*a, 'Punkt styku', 0), (*b, 'Punkt styku', 0), ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2, 'Środek', 1)]
                self.segments.append((a, b))
            elif kind == 'CIRCLE':
                c = uv(edge.arcCenter())
                r = edge.radius()
                if edge.IsClosed():
                    self.points.append((*c, 'Środek', 0))
                    self.circles.append((c, r))
                else:
                    m = uv(edge.positionAt(.5))
                    self.points += [(*a, 'Punkt styku', 0), (*b, 'Punkt styku', 0), (*m, 'Środek', 1)]
                    pts = [uv(edge.positionAt(t)) for t in np.linspace(0, 1, 17)]
                    self.segments += list(zip(pts[:-1], pts[1:]))
            else:
                pts = [uv(edge.positionAt(t)) for t in np.linspace(0, 1, 25)]
                self.points += [(*pts[0], 'Punkt styku', 0), (*pts[-1], 'Punkt styku', 0)]
                self.segments += list(zip(pts[:-1], pts[1:]))
        c = shape.Center().toTuple()
        self.points.append((*kernel.uv_of(plane, c), 'Środek', 0))
        self.intersections = []
        segs = self.segments if len(self.segments) <= 160 else []
        for i in range(len(segs)):
            A, B = segs[i]
            r = (B[0] - A[0], B[1] - A[1])
            for j in range(i + 1, len(segs)):
                C, D = segs[j]
                q = (D[0] - C[0], D[1] - C[1])
                den = r[0] * q[1] - r[1] * q[0]
                if abs(den) < 1e-10:
                    continue
                ac = (C[0] - A[0], C[1] - A[1])
                t = (ac[0] * q[1] - ac[1] * q[0]) / den
                s = (ac[0] * r[1] - ac[1] * r[0]) / den
                if -1e-8 <= t <= 1 + 1e-8 and -1e-8 <= s <= 1 + 1e-8:
                    self.points.append((A[0] + t * r[0], A[1] + t * r[1], 'Punkt styku', 0))


def snap(view, plane, geometry, x, y, raw):
    """Zwraca (u, v, etykieta) dla kursora w pikselach (x, y) i surowego punktu raw = (u, v) na płaszczyźnie."""
    def screen(u, v):
        return view.project_one(kernel.to_world(plane, u, v))

    candidates = []

    def add(u, v, label, priority):
        s = screen(u, v)
        if s is None:
            return
        d = math.hypot(s[0] - x, s[1] - y)
        if d <= RADIUS:
            candidates.append((priority, d, u, v, label))

    for u, v, label, priority in geometry.points:
        add(u, v, label, priority)
    for a, b in geometry.segments:
        pa, pb = screen(*a), screen(*b)
        if pa is None or pb is None:
            continue
        dx, dy = pb[0] - pa[0], pb[1] - pa[1]
        l2 = dx * dx + dy * dy
        if l2 < .001:
            continue
        t = max(0.0, min(1.0, ((x - pa[0]) * dx + (y - pa[1]) * dy) / l2))
        add(a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, 'Krawędź', 3)
    for c, r in geometry.circles:
        if r > 1e-5:
            ang = math.atan2(raw[1] - c[1], raw[0] - c[0])
            add(c[0] + r * math.cos(ang), c[1] + r * math.sin(ang), 'Okrąg', 3)
    # siatka dopasowana do powiększenia (min. 12 px między liniami)
    o, e = screen(0, 0), screen(1, 0)
    px = math.hypot(e[0] - o[0], e[1] - o[1]) if o and e else 1.0
    grid = next((g for g in LEVELS if g * px >= 12), 10)
    add(round(raw[0] / grid) * grid, round(raw[1] / grid) * grid, 'Siatka', 5)
    if candidates:
        candidates.sort(key=lambda c: (c[0], c[1]))
        _, _, u, v, label = candidates[0]
        return u, v, label
    return round(raw[0] / grid) * grid, round(raw[1] / grid) * grid, None
