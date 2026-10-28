"""Parametry kształtów szkicu (czysta matematyka bez Qt / CadQuery): wartości do pól Tab, przeliczanie wymiarów,
punkty uchwytów i przeciąganie. Meta kształtu: dict(tool, points=[[u, v], ...], sides, [text, size, font, bold, halign, angle])."""
from __future__ import annotations
import math

TWO_POINT = ('rect', 'centerRect', 'ellipse', 'circle', 'circle2', 'polygon', 'line')
THREE_POINT = ('arc', 'rect3', 'slot', 'circle3')
EDITABLE = (*TWO_POINT, *THREE_POINT)
LABELS = {
    'rect': ('Szerokość (mm)', 'Wysokość (mm)'), 'centerRect': ('Szerokość (mm)', 'Wysokość (mm)'), 'ellipse': ('Szerokość (mm)', 'Wysokość (mm)'),
    'circle': ('Promień (mm)',), 'polygon': ('Promień (mm)', 'Ilość kątów'), 'circle2': ('Średnica (mm)',), 'line': ('Długość (mm)', 'Kąt (°)'),
    'arc': ('Długość cięciwy (mm)', 'Wysokość łuku (mm)'), 'rect3': ('Szerokość (mm)', 'Wysokość (mm)'), 'slot': ('Długość (mm)', 'Szerokość (mm)'),
    'circle3': ('Promień (mm)',), 'text': ('Wysokość liter (mm)', 'Kąt (°)'),
}


def _d(a, b):
    return math.hypot(b[0] - a[0], b[1] - a[1])


def _unit(a, b):
    d = _d(a, b)
    return ((b[0] - a[0]) / d, (b[1] - a[1]) / d) if d > 1e-12 else (1.0, 0.0)


def circumcircle(a, b, c):
    d = 2 * (a[0] * (b[1] - c[1]) + b[0] * (c[1] - a[1]) + c[0] * (a[1] - b[1]))
    if abs(d) < 1e-9:
        return None
    ux = ((a[0] ** 2 + a[1] ** 2) * (b[1] - c[1]) + (b[0] ** 2 + b[1] ** 2) * (c[1] - a[1]) + (c[0] ** 2 + c[1] ** 2) * (a[1] - b[1])) / d
    uy = ((a[0] ** 2 + a[1] ** 2) * (c[0] - b[0]) + (b[0] ** 2 + b[1] ** 2) * (a[0] - c[0]) + (c[0] ** 2 + c[1] ** 2) * (b[0] - a[0])) / d
    return (ux, uy), math.hypot(a[0] - ux, a[1] - uy)


def arc_apex(p0, p1, p2):
    """Środek łuku (punkt na okręgu w połowie drogi od p0 do p2 przez p1)."""
    cc = circumcircle(p0, p1, p2)
    if cc is None:
        return tuple(p1)
    (cu, cv), r = cc
    ang = lambda p: math.atan2(p[1] - cv, p[0] - cu)
    a0, a1, a2 = ang(p0), ang(p1), ang(p2)
    tau = 2 * math.pi
    s1, s2 = (a1 - a0) % tau, (a2 - a0) % tau
    if s1 <= s2:          # p1 leży na łuku przeciwnym do ruchu wskazówek od p0 do p2
        mid = a0 + s2 / 2
    else:                 # w drugą stronę
        mid = a0 - ((a0 - a2) % tau) / 2
    return (cu + r * math.cos(mid), cv + r * math.sin(mid))


def _perp(u):
    return (-u[1], u[0])


def _r(x):
    return str(round(float(x), 3))


def dim_end(tool, p0, ref, v, direction=None):
    """Punkt końcowy figury 2-punktowej z wpisanych wymiarów; ref wyznacza stronę (znaki), direction - kierunek promienia."""
    u0, v0 = p0
    sx = 1 if ref[0] >= u0 else -1
    sy = 1 if ref[1] >= v0 else -1
    if tool in ('rect', 'ellipse', 'centerRect'):
        w = v[0]
        h = v[1] if len(v) > 1 and v[1] is not None else v[0]
        k = .5 if tool in ('centerRect', 'ellipse') else 1
        return (u0 + sx * w * k, v0 + sy * h * k)
    if tool in ('circle', 'polygon', 'circle2'):
        d = direction or (1.0, 0.0)
        return (u0 + v[0] * d[0], v0 + v[0] * d[1])
    ang = math.radians(v[1]) if len(v) > 1 and v[1] is not None else 0.0
    return (u0 + v[0] * math.cos(ang), v0 + v[0] * math.sin(ang))


def values(meta):
    """Aktualne wartości pól Tab (teksty)."""
    t, pts = meta['tool'], [tuple(p) for p in meta['points']]
    if t == 'text':
        return [_r(meta.get('size', 10)), _r(meta.get('angle', 0))]
    p0 = pts[0]
    if t in TWO_POINT:
        (u0, v0), (u1, v1) = pts[0], pts[1]
        du, dv, dist = abs(u1 - u0), abs(v1 - v0), math.hypot(u1 - u0, v1 - v0)
        if t == 'rect':
            return [_r(du), _r(dv)]
        if t in ('centerRect', 'ellipse'):
            return [_r(2 * du), _r(2 * dv)]
        if t == 'polygon':
            return [_r(dist), str(int(meta.get('sides', 5)))]
        if t in ('circle', 'circle2'):
            return [_r(dist)]
        return [_r(dist), _r(math.degrees(math.atan2(v1 - v0, u1 - u0)))]
    p1, p2 = pts[1], pts[2]
    if t == 'arc':
        apex = arc_apex(p0, p1, p2)
        u = _unit(p0, p2)
        mid = ((p0[0] + p2[0]) / 2, (p0[1] + p2[1]) / 2)
        h = abs((apex[0] - mid[0]) * _perp(u)[0] + (apex[1] - mid[1]) * _perp(u)[1])
        return [_r(_d(p0, p2)), _r(h)]
    if t == 'rect3':
        u = _unit(p0, p1)
        h = (p2[0] - p0[0]) * _perp(u)[0] + (p2[1] - p0[1]) * _perp(u)[1]
        return [_r(_d(p0, p1)), _r(abs(h))]
    if t == 'slot':
        u = _unit(p0, p1)
        r = abs((p2[0] - p0[0]) * _perp(u)[0] + (p2[1] - p0[1]) * _perp(u)[1])
        return [_r(_d(p0, p1)), _r(2 * r)]
    cc = circumcircle(p0, p1, p2)
    return [_r(cc[1] if cc else 0.0)]


def apply_values(meta, v):
    """Nowe meta po wpisaniu wartości v (lista liczb / None)."""
    t, pts = meta['tool'], [tuple(p) for p in meta['points']]
    out = dict(meta)
    if t == 'text':
        if v[0] is not None and v[0] > 1e-6:
            out['size'] = float(v[0])
        if len(v) > 1 and v[1] is not None:
            out['angle'] = float(v[1])
        return out
    p0 = pts[0]
    if t in TWO_POINT:
        (u0, v0), (u1, v1) = pts[0], pts[1]
        dist = math.hypot(u1 - u0, v1 - v0)
        direction = ((u1 - u0) / dist, (v1 - v0) / dist) if dist > 1e-9 else None
        if t == 'polygon' and len(v) > 1 and v[1] is not None and 3 <= int(v[1]) <= 64:
            out['sides'] = int(v[1])
        out['points'] = [list(p0), list(dim_end(t, p0, pts[1], v, direction))]
        return out
    p1, p2 = pts[1], pts[2]
    a, b = v[0], (v[1] if len(v) > 1 and v[1] is not None else None)
    if t == 'arc':
        apex = arc_apex(p0, p1, p2)
        u = _unit(p0, p2)
        n = _perp(u)
        mid = ((p0[0] + p2[0]) / 2, (p0[1] + p2[1]) / 2)
        side = 1.0 if ((apex[0] - mid[0]) * n[0] + (apex[1] - mid[1]) * n[1]) >= 0 else -1.0
        h = b if b is not None else abs((apex[0] - mid[0]) * n[0] + (apex[1] - mid[1]) * n[1])
        e = (p0[0] + u[0] * a, p0[1] + u[1] * a)
        m = ((p0[0] + e[0]) / 2 + n[0] * h * side, (p0[1] + e[1]) / 2 + n[1] * h * side)
        out['points'] = [list(p0), list(m), list(e)]
    elif t == 'rect3':
        u = _unit(p0, p1)
        n = _perp(u)
        side = 1.0 if ((p2[0] - p0[0]) * n[0] + (p2[1] - p0[1]) * n[1]) >= 0 else -1.0
        h = b if b is not None else abs((p2[0] - p0[0]) * n[0] + (p2[1] - p0[1]) * n[1])
        e = (p0[0] + u[0] * a, p0[1] + u[1] * a)
        out['points'] = [list(p0), list(e), [p0[0] + n[0] * h * side, p0[1] + n[1] * h * side]]
    elif t == 'slot':
        u = _unit(p0, p1)
        n = _perp(u)
        side = 1.0 if ((p2[0] - p0[0]) * n[0] + (p2[1] - p0[1]) * n[1]) >= 0 else -1.0
        width = b if b is not None else _r_slot(p0, p1, p2) * 2
        e = (p0[0] + u[0] * a, p0[1] + u[1] * a)
        out['points'] = [list(p0), list(e), [p0[0] + n[0] * width / 2 * side, p0[1] + n[1] * width / 2 * side]]
    else:  # circle3: ten sam środek, nowy promień
        cc = circumcircle(p0, p1, p2)
        if cc is not None:
            (cu, cv), _ = cc
            out['points'] = [[cu + a * _unit((cu, cv), p)[0], cv + a * _unit((cu, cv), p)[1]] for p in pts]
    return out


def _r_slot(p0, p1, p2):
    u = _unit(p0, p1)
    return abs((p2[0] - p0[0]) * _perp(u)[0] + (p2[1] - p0[1]) * _perp(u)[1])


# ---------- uchwyty i przeciąganie ----------
def extent(tool, pts):
    (u0, v0), (u1, v1) = pts[0], pts[1]
    if tool == 'rect':
        return min(u0, u1), max(u0, u1), min(v0, v1), max(v0, v1)
    if tool in ('centerRect', 'ellipse'):
        hw, hh = abs(u1 - u0), abs(v1 - v0)
        return u0 - hw, u0 + hw, v0 - hh, v0 + hh
    if tool == 'circle2':
        cu, cv, r = (u0 + u1) / 2, (v0 + v1) / 2, math.hypot(u1 - u0, v1 - v0) / 2
        return cu - r, cu + r, cv - r, cv + r
    r = math.hypot(u1 - u0, v1 - v0)
    return (u0 - r, u0 + r, v0 - r, v0 + r) if tool in ('circle', 'polygon') else (min(u0, u1), max(u0, u1), min(v0, v1), max(v0, v1))


def grip_points(meta):
    t, pts = meta['tool'], [tuple(p) for p in meta['points']]
    if t in THREE_POINT:
        p0, p1, p2 = pts[:3]
        if t == 'rect3':
            u = _unit(p0, p1)
            n = _perp(u)
            h = (p2[0] - p0[0]) * n[0] + (p2[1] - p0[1]) * n[1]
            return [p0, p1, ((p0[0] + p1[0]) / 2 + n[0] * h, (p0[1] + p1[1]) / 2 + n[1] * h)]
        if t == 'slot':
            u = _unit(p0, p1)
            n = _perp(u)
            side = 1.0 if ((p2[0] - p0[0]) * n[0] + (p2[1] - p0[1]) * n[1]) >= 0 else -1.0
            r = _r_slot(p0, p1, p2)
            mid = ((p0[0] + p1[0]) / 2, (p0[1] + p1[1]) / 2)
            return [p0, p1, (mid[0] + n[0] * r * side, mid[1] + n[1] * r * side)]
        return [p0, p1, p2]
    umin, umax, vmin, vmax = extent(t, pts)
    um, vm = (umin + umax) / 2, (vmin + vmax) / 2
    if t in ('rect', 'centerRect'):
        return [(umin, vmin), (umax, vmin), (umax, vmax), (umin, vmax), (um, vmin), (umax, vm), (um, vmax), (umin, vm)]
    if t in ('ellipse', 'circle', 'circle2'):
        return [(um, vmin), (umax, vm), (um, vmax), (umin, vm)]
    return [tuple(pts[0]), tuple(pts[1])]


def grab_info(tool, pts, uv, thr, meta=None):
    u, v = uv
    if tool in THREE_POINT:
        grips = grip_points(meta)
        return min(range(3), key=lambda i: _d(grips[i], uv))
    (u0, v0), (u1, v1) = pts[0], pts[1]
    if tool == 'line':
        return 0 if math.hypot(u - u0, v - v0) <= math.hypot(u - u1, v - v1) else 1
    if tool in ('circle', 'circle2', 'polygon'):
        return 'radius'
    if tool == 'ellipse':
        hw, hh = max(abs(u1 - u0), 1e-9), max(abs(v1 - v0), 1e-9)
        return 'u' if abs(u - u0) / hw > abs(v - v0) / hh else 'v'
    umin, umax, vmin, vmax = extent(tool, pts)
    dl, dr, db, dt = abs(u - umin), abs(u - umax), abs(v - vmin), abs(v - vmax)
    side_u, side_v = ('min' if dl < dr else 'max'), ('min' if db < dt else 'max')
    du, dv = min(dl, dr), min(db, dt)
    if du < thr and dv < thr:
        return ('uv', side_u, side_v)
    return ('u', side_u, None) if du <= dv else ('v', None, side_v)


def grab_apply(meta, grab, uv):
    """Nowe meta po przeciągnięciu uchwytu do punktu uv (albo None, gdy kształt zdegenerowałby się)."""
    tool, pts = meta['tool'], [tuple(p) for p in meta['points']]
    out = dict(meta)
    u, v = round(uv[0], 2), round(uv[1], 2)
    if tool in THREE_POINT:
        grips = grip_points(meta)
        new = [list(p) for p in pts]
        if tool in ('rect3', 'slot') and grab == 2:
            new[2] = [u, v]
        elif tool in ('rect3', 'slot'):
            keep = values(meta)
            new[grab] = [u, v]
            moved = dict(meta, points=new)
            if tool == 'rect3':        # przy zmianie podstawy zachowaj wysokość
                moved = apply_values(moved, [float(values(moved)[0]), float(keep[1])])
                new = moved['points']
            else:
                moved = apply_values(moved, [float(values(moved)[0]), float(keep[1])])
                new = moved['points']
        else:
            new[grab] = [u, v]
        out['points'] = new
        return out
    (u0, v0), (u1, v1) = pts[0], pts[1]
    if tool == 'line':
        out['points'] = [[u, v], list(pts[1])] if grab == 0 else [list(pts[0]), [u, v]]
        return out
    if tool in ('circle', 'polygon'):
        if math.hypot(u - u0, v - v0) <= 1e-3:
            return None
        out['points'] = [list(pts[0]), [u, v]]
        return out
    if tool == 'circle2':
        cu, cv = (u0 + u1) / 2, (v0 + v1) / 2
        r, d = math.hypot(u - cu, v - cv), math.hypot(u1 - u0, v1 - v0) or 1.0
        if r < 1e-3:
            return None
        dx, dy = (u1 - u0) / d, (v1 - v0) / d
        out['points'] = [[cu - r * dx, cv - r * dy], [cu + r * dx, cv + r * dy]]
        return out
    if tool == 'ellipse':
        sx, sy = (1 if u1 >= u0 else -1), (1 if v1 >= v0 else -1)
        hw, hh = abs(u1 - u0), abs(v1 - v0)
        if grab == 'u':
            hw = abs(u - u0)
        else:
            hh = abs(v - v0)
        if hw <= 1e-3 or hh <= 1e-3:
            return None
        out['points'] = [list(pts[0]), [u0 + sx * hw, v0 + sy * hh]]
        return out
    umin, umax, vmin, vmax = extent(tool, pts)
    kind, side_u, side_v = grab
    if 'u' in kind:
        if side_u == 'min':
            umin = u
        else:
            umax = u
    if 'v' in kind:
        if side_v == 'min':
            vmin = v
        else:
            vmax = v
    if tool == 'centerRect':
        sx, sy = (1 if u1 >= u0 else -1), (1 if v1 >= v0 else -1)
        hw = abs(u - u0) if 'u' in kind else abs(u1 - u0)
        hh = abs(v - v0) if 'v' in kind else abs(v1 - v0)
        if hw <= 1e-3 or hh <= 1e-3:
            return None
        out['points'] = [list(pts[0]), [u0 + sx * hw, v0 + sy * hh]]
        return out
    if abs(umax - umin) < 1e-3 or abs(vmax - vmin) < 1e-3:
        return None
    out['points'] = [[min(umin, umax), min(vmin, vmax)], [max(umin, umax), max(vmin, vmax)]]
    return out


# ---------- tekst: ramka z uchwytami (przesuń / skaluj / obróć) ----------
def _rot(p, c, ang):
    ca, sa = math.cos(ang), math.sin(ang)
    x, y = p[0] - c[0], p[1] - c[1]
    return (c[0] + x * ca - y * sa, c[1] + x * sa + y * ca)


def text_box(uvs, anchor, angle_deg, margin=0.0):
    """Ramka tekstu w jego własnym układzie (obrócona o kąt): rogi, uchwyt przesuwania (środek), skalowania (prawy dolny róg), obrotu (nad górą)."""
    ang = math.radians(angle_deg)
    local = [_rot(p, anchor, -ang) for p in uvs]
    us, vs = [p[0] for p in local], [p[1] for p in local]
    umin, umax, vmin, vmax = min(us) - margin, max(us) + margin, min(vs) - margin, max(vs) + margin
    corners_local = [(umin, vmin), (umax, vmin), (umax, vmax), (umin, vmax)]
    height = max(vmax - vmin, 1e-6)
    to_world = lambda p: _rot(p, anchor, ang)
    top_mid = ((umin + umax) / 2, vmax)
    return dict(corners=[to_world(p) for p in corners_local], move=to_world(((umin + umax) / 2, (vmin + vmax) / 2)),
                scale=to_world((umax, vmin)), rotate=to_world((top_mid[0], vmax + max(height * .45, 3.0))), top=to_world(top_mid))


def text_drag(meta, which, uv0, uv):
    out = dict(meta)
    anchor = tuple(meta['points'][0])
    if which == 'move':
        out['points'] = [[anchor[0] + uv[0] - uv0[0], anchor[1] + uv[1] - uv0[1]]]
    elif which == 'scale':
        d0, d1 = _d(anchor, uv0), _d(anchor, uv)
        if d0 > 1e-6:
            out['size'] = max(.2, float(meta.get('size', 10)) * d1 / d0)
    elif which == 'rotate':
        a0, a1 = math.atan2(uv0[1] - anchor[1], uv0[0] - anchor[0]), math.atan2(uv[1] - anchor[1], uv[0] - anchor[0])
        out['angle'] = float(meta.get('angle', 0.0)) + math.degrees(a1 - a0)
    return out
