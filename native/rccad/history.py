"""Historia parametryczna: przepisy operacji (JSON), ich ponowne wykonanie na zmienionym stanie i przeliczanie następnych kroków.
Czysta logika bez Qt: studio podaje stany (listy Body), a tu wyliczane są nowe stany po edycji któregoś kroku."""
from __future__ import annotations
import ast
import json
import re
import math
import operator
import uuid
from dataclasses import replace
import numpy as np
import cadquery as cq
from . import kernel
from . import sketchmeta as sm
from .document import Body

# klucz ikony kroku -> ikona paska narzędzi (icons.pixmap('t_' + nazwa)); wartości wspólne dla wszystkich kroków historii
ICONS = {'start': 'history', 'sketch': 'sketch', 'extrude': 'extrude', 'cut': 'cut', 'intersect': 'bool', 'bool': 'bool', 'mod': 'mod',
         'mirror': 'mirror', 'pattern': 'pattern', 'move': 'move', 'rotate': 'rotate', 'trash': 'trash', 'file': 'file', 'text': 'text'}
# filtr paska historii: nazwa -> zbiór kluczy ikon (None = wszystko; 'stale' obsługiwane osobno)
FILTERS = {'Wszystkie kroki': None, 'Szkice i tekst': {'sketch', 'text'}, 'Operacje na bryłach': {'extrude', 'cut', 'intersect', 'bool'},
           'Modyfikacje': {'mod', 'mirror', 'pattern', 'move', 'rotate', 'trash'}, 'Import': {'file'}, 'Tylko błędy': 'stale'}


def passes_filter(info, name):
    """Czy krok pokazuje się przy danym filtrze paska historii."""
    allowed = FILTERS.get(name)
    if allowed is None:
        return True
    if allowed == 'stale':
        return bool(info.get('stale'))
    return info.get('icon') in allowed


# etykieta operacji uruchamianej przez run_operation -> klucz ikony
LABEL_ICONS = {'Tworzenie szkicu': 'sketch', 'Nożyczki': 'sketch', 'Zmiana wymiarów szkicu': 'sketch', 'Wyciągnięcie': 'extrude',
               'Wyciągnięcie (dodaj)': 'extrude', 'Wycięcie': 'cut', 'Część wspólna': 'intersect', 'Operacja na bryłach': 'bool',
               'Zaokrąglanie': 'mod', 'Fazowanie': 'mod', 'Odbicie lustrzane': 'mirror', 'Szyk': 'pattern', 'Przekształcenie': 'move',
               'Wklejanie': 'file', 'Importowanie SVG': 'file', 'Importowanie modelu': 'file'}


def plane_to_json(plane):
    return plane if isinstance(plane, str) else plane.to_dict()


def plane_from_json(value):
    return value if isinstance(value, str) else kernel.Frame.from_dict(value)


def plane_key(plane):
    return plane if isinstance(plane, str) else (plane.origin, plane.xdir, plane.normal)


def sketch_groups(bodies):
    """Widoczne szkice (bez konstrukcji i punktów) pogrupowane według rzeczywistej płaszczyzny: klucz -> (płaszczyzna, [bryły])."""
    groups = {}
    for b in bodies:
        if b.kind == 'sketch' and b.visible and not b.name.startswith(('Konstrukcja', 'Punkt')):
            plane = kernel.actual_frame(b.shape, b.plane)
            groups.setdefault(plane_key(plane), (plane, []))[1].append(b)
    return groups


def _unit(v):
    v = np.array(v, float)
    return v / np.linalg.norm(v)


def _adjacent_normals(shape, edge=None, vertex_point=None):
    """Posortowane normalne ścian przylegających do krawędzi (lub wierzchołka): „podpis” elementu niezależny od rozmiaru bryły."""
    out = []
    for face in shape.Faces():
        try:
            if edge is not None:
                if not any(e.isSame(edge) for e in face.Edges()):
                    continue
                n = face.normalAt(edge.positionAt(.5)).toTuple()
            else:
                if not any(float(np.linalg.norm(np.array(v.toTuple()) - vertex_point)) < 1e-6 for v in face.Vertices()):
                    continue
                n = face.normalAt(cq.Vector(*[float(c) for c in vertex_point])).toTuple()
            out.append([round(float(c), 3) for c in n])
        except Exception:
            continue
    return sorted(out)


def _same_normals(a, b, tol=0.05):
    return len(a) == len(b) and all(float(np.linalg.norm(np.array(x) - np.array(y))) < tol for x, y in zip(sorted(a), sorted(b)))


def _scale(shape):
    box = kernel.bounds(shape)
    return max(box.xlen, box.ylen, box.zlen, 1e-6)


def _extent_along(shape, n):
    """(min, max) rzutu wierzchołków bryły na kierunek n."""
    values = [float(np.array(v.toTuple(), float) @ n) for v in shape.Vertices()]
    return (min(values), max(values)) if values else (0.0, 0.0)


def _extreme(shape, face, n):
    """'max' / 'min', gdy ściana leży na skraju bryły w kierunku normalnej (np. górna ściana), inaczej None."""
    if shape is None:
        return None
    lo, hi = _extent_along(shape, n)
    offset = float(np.array(face.Center().toTuple(), float) @ n)
    tol = 1e-6 * max(_scale(shape), 1.0)
    return 'max' if abs(offset - hi) < tol else 'min' if abs(offset - lo) < tol else None


def face_ref(face, normal, point, shape=None):
    c = np.array(face.Center().toTuple(), float)
    n = _unit(normal)
    ref = dict(normal=[float(x) for x in n], point=[float(x) for x in point], centroid=[float(x) for x in c], area=float(face.Area()))
    extreme = _extreme(shape, face, n)
    if extreme:
        ref['extreme'] = extreme      # ściana na skraju bryły (górna / dolna) zostaje na skraju po zmianie rozmiarów
    return ref


def match_face(shape, ref):
    """Płaska ściana bryły odpowiadająca zapisanej: najpierw ta, która nadal zawiera punkt; inaczej najlepiej pasująca
    (ta sama normalna, położenie płaszczyzny, środek i pole), więc krok przeżywa zmianę rozmiaru bryły."""
    n0 = _unit(ref['normal'])
    try:
        return kernel.face_at(shape, n0, ref['point'])
    except kernel.CadError:
        pass
    c0, a0, scale = np.array(ref.get('centroid', ref['point']), float), float(ref.get('area', 0.0)), _scale(shape)
    lo, hi = _extent_along(shape, n0)
    want = ref.get('extreme')
    best = None
    for face in shape.Faces():
        if face.geomType() != 'PLANE':
            continue
        fn = np.array(face.normalAt().toTuple(), float)
        if float(fn @ n0) < .999:
            continue
        c = np.array(face.Center().toTuple(), float)
        d = c - c0
        off = abs(float(d @ n0))
        inplane = float(np.linalg.norm(d - float(d @ n0) * n0))
        area = float(face.Area())
        offset = float(c @ n0)
        at = 'max' if abs(offset - hi) < 1e-6 * max(scale, 1.0) else 'min' if abs(offset - lo) < 1e-6 * max(scale, 1.0) else None
        if want:
            # ściana była skrajna: skrajna ściana w tym samym kierunku wygrywa mimo zmiany położenia, nieskrajne dostają karę
            off = 0.0 if at == want else off + scale
        score = off + .25 * inplane + .5 * scale * abs(area - a0) / max(area, a0, 1e-9)
        if best is None or score < best[0]:
            best = (score, face, fn)
    if best is None or best[0] > 1.5 * scale:
        raise kernel.CadError('Ściana użyta w tym kroku już nie istnieje.')
    return best[1], best[2]


_NS = uuid.UUID('6f1c1a52-8b3e-4b77-9d6a-2c1f5e0a7b11')


def stable_id(seed, index):
    """Powtarzalny identyfikator (32 znaki hex) wynikający z ziarna kroku i numeru elementu - przeliczenie historii daje te same id."""
    return uuid.uuid5(_NS, f'{seed}:{index}').hex


def pad_ids(ids, count, seed):
    """Uzupełnia listę identyfikatorów wyników kroku do `count`: z ziarna, jeśli jest (powtarzalnie), inaczej losowo."""
    ids = list(ids)
    return ids + [stable_id(seed, i) if seed else uuid.uuid4().hex for i in range(len(ids), count)]


def new_text_group():
    """Znacznik grupy liter jednego napisu: 24 znaki hex, na pozycji 12 zawsze 'f' (zwykłe identyfikatory uuid4 mają tam '4')."""
    raw = uuid.uuid4().hex[:24]
    return raw[:12] + 'f' + raw[13:]


def text_ids(group, count):
    return [f'{group}{i:08x}' for i in range(count)]


def text_group_of(identifier):
    """Grupa napisu, do której należy szkic o danym identyfikatorze (albo None dla zwykłego szkicu)."""
    return identifier[:24] if isinstance(identifier, str) and len(identifier) == 32 and identifier[12] == 'f' else None


def _group_regions(plane, members):
    """Obszary szkiców w płaszczyźnie. Pojedynczy kształt (np. jeden okrąg) nie przechodzi przez General Fuse - wtedy obszarem jest ściana z jego konturu
    (tak samo jak przy wskazywaniu obszaru w oknie), inaczej przeliczenie historii gubiłoby takie kroki."""
    try:
        faces = kernel.regions(plane, [e for b in members for e in b.shape.Edges()], [b.shape for b in members if b.shape.IsClosed()])
    except Exception:
        faces = []
    if faces:
        return faces
    out = []
    for b in members:
        try:
            if b.shape.IsClosed():
                out.append(cq.Face.makeFromWires(b.shape))
        except Exception:
            continue
    return out


def _inner_point(face):
    """Punkt leżący wewnątrz ściany (środek pierwszego trójkąta siatki) - środek ciężkości pierścienia leży poza nim."""
    vertices, triangles = face.tessellate(0.05, 0.2)
    if not triangles:
        return np.array(face.Center().toTuple(), float)
    t = triangles[0]
    return np.mean([np.array(vertices[i].toTuple(), float) for i in t], axis=0)


def material_regions(plane, members):
    """Obszary napisu, które są materiałem liter (reguła parzystości): bez wnętrz otworów w literach typu A, B, O, e."""
    faces = _group_regions(plane, members)
    outlines = []
    for b in members:
        try:
            if b.shape.IsClosed():
                outlines.append(cq.Face.makeFromWires(b.shape))
        except Exception:
            continue
    if not outlines:
        return faces
    material = []
    for f in faces:
        point = _inner_point(f)
        depth = sum(1 for o in outlines if kernel.face_contains(o, point))
        if depth % 2 == 1:
            material.append(f)
    return material or faces


def same_face(a, b):
    try:
        ca, cb = np.array(a.Center().toTuple(), float), np.array(b.Center().toTuple(), float)
        return abs(a.Area() - b.Area()) <= 1e-4 * max(a.Area(), 1e-9) and float(np.linalg.norm(ca - cb)) < 1e-3
    except Exception:
        return False


def describe_profiles(profiles, bodies=()):
    """Przepis na wybrane profile wyciągnięcia (src z Studio) -> lista słowników JSON. Obszar zapamiętuje też szkic-kotwicę
    i przesunięcie względem jego środka, więc podąża za szkicem po zmianie jego wymiarów."""
    out = []
    for src in profiles:
        if src['kind'] == 'sketch':
            out.append({'k': 'sketch', 'id': src['id']})
        elif src['kind'] == 'region':
            center = np.array(src['center'], float)
            spec = {'k': 'region', 'plane': plane_to_json(src['plane']), 'center': [float(c) for c in center]}
            group = sketch_groups(bodies).get(plane_key(src['plane']))
            best = None
            for b in (group[1] if group else []):
                box = kernel.bounds(b.shape)
                lo, hi = np.array((box.xmin, box.ymin, box.zmin)), np.array((box.xmax, box.ymax, box.zmax))
                if np.all(center >= lo - 1e-6) and np.all(center <= hi + 1e-6):
                    size = float(np.prod(np.maximum(hi - lo, 1e-6)))
                    if best is None or size < best[0]:
                        best = (size, b.id, center - (lo + hi) / 2)
            if best is not None:
                spec['anchor'] = {'id': best[1], 'offset': [float(c) for c in best[2]]}
            out.append(spec)
        else:
            owner = next((b for b in bodies if b.id == src.get('id')), None)
            ref = face_ref(src['face'], src['normal'], src.get('hit', src['center']), owner.shape if owner is not None else None) if src.get('face') is not None else dict(
                normal=[float(c) for c in src['normal']], point=[float(c) for c in src.get('hit', src['center'])])
            out.append(dict(ref, k='face', id=src['id']))
    return _merge_text_groups(out, profiles, bodies)


def _merge_text_groups(out, profiles, bodies):
    """Gdy wybrano WSZYSTKIE obszary materiału napisu (bez wnętrz otworów w literach), krok zapamiętuje „cały napis”:
    po zmianie treści obejmie też nowe litery."""
    picked = {}
    for n, spec in enumerate(out):
        group = text_group_of((spec.get('anchor') or {}).get('id')) if spec['k'] == 'region' else None
        if group:
            picked.setdefault((group, json.dumps(spec['plane'], sort_keys=True)), []).append(n)
    drop, extra = set(), []
    for (group, _), numbers in picked.items():
        spec = out[numbers[0]]
        try:
            plane = plane_from_json(spec['plane'])
            found = sketch_groups(bodies).get(plane_key(plane))
            members = [b for b in (found[1] if found else []) if text_group_of(b.id) == group]
            material = material_regions(found[0], members) if members else []
            faces = [profiles[n].get('face') for n in numbers]
            covered = [f for f in material if any(g is not None and same_face(f, g) for g in faces)]
            if material and len(covered) == len(material):
                drop |= {n for n in numbers if profiles[n].get('face') is not None and any(same_face(f, profiles[n]['face']) for f in material)}
                extra.append({'k': 'textgroup', 'group': group, 'plane': spec['plane']})
        except Exception:
            continue
    return [x for n, x in enumerate(out) if n not in drop] + extra


def resolve_profile(bodies, spec):
    """Odtwarza profil (wire, normal, plane, face) w podanym stanie albo rzuca CadError."""
    by_id = {b.id: b for b in bodies}
    if spec['k'] == 'sketch':
        body = by_id.get(spec['id'])
        if body is None or body.kind != 'sketch':
            raise kernel.CadError('Szkic użyty w tym kroku już nie istnieje.')
        frame = kernel.frame_of(body.plane)
        normal = kernel.profile_normal(body.shape, frame.normal)
        tilted = abs(float(np.dot(normal, frame.normal))) < 1 - 1e-6
        return dict(wire=body.shape, normal=tuple(float(c) for c in normal), plane=None if tilted else body.plane, face=None)
    if spec['k'] == 'region':
        plane = plane_from_json(spec['plane'])
        group = sketch_groups(bodies).get(plane_key(plane))
        if group is None:
            raise kernel.CadError('Brak szkiców w płaszczyźnie tego kroku.')
        plane, members = group
        faces = _group_regions(plane, members)
        if not faces:
            raise kernel.CadError('Szkic nie tworzy już zamkniętego obszaru.')
        center = np.array(spec['center'], float)
        anchor = spec.get('anchor')
        if anchor and anchor['id'] in by_id and by_id[anchor['id']].kind == 'sketch':      # obszar podąża za szkicem-kotwicą
            box = kernel.bounds(by_id[anchor['id']].shape)
            center = np.array((box.center.toTuple()), float) + np.array(anchor['offset'], float)
        inside = [f for f in faces if kernel.face_contains(f, center)]
        face = min(inside or faces, key=lambda f: float(np.linalg.norm(np.array(f.Center().toTuple()) - center)) if not inside else float(f.Area()))
        return dict(wire=face.outerWire(), normal=tuple(kernel.frame_of(plane).normal), plane=plane, face=face)
    body = by_id.get(spec['id'])
    if body is None or body.kind != 'solid':
        raise kernel.CadError('Bryła użyta w tym kroku już nie istnieje.')
    face, normal = match_face(body.shape, spec)
    return dict(wire=face.outerWire(), normal=tuple(float(c) for c in normal), plane=None, face=face)


def resolve_profiles(bodies, spec):
    """Lista profili dla jednej pozycji przepisu (napis = wszystkie jego obszary, reszta = jeden profil)."""
    if spec['k'] != 'textgroup':
        return [resolve_profile(bodies, spec)]
    plane = plane_from_json(spec['plane'])
    found = sketch_groups(bodies).get(plane_key(plane))
    members = [b for b in (found[1] if found else []) if text_group_of(b.id) == spec['group']]
    if not members:
        raise kernel.CadError('Napis użyty w tym kroku już nie istnieje.')
    faces = material_regions(found[0], members)
    if not faces:
        raise kernel.CadError('Napis nie tworzy już zamkniętych obszarów.')
    return [dict(wire=f.outerWire(), normal=tuple(kernel.frame_of(found[0]).normal), plane=found[0], face=f) for f in faces]


def make_tool(src, d1, d2, mode):
    face, wire, normal, plane = src['face'], src['wire'], src['normal'], src['plane']
    if face is not None:
        return kernel.extrude_face(face, normal, d1, d2 if mode == 'two' else 0.0, mode == 'symmetric')
    if mode == 'two':
        return kernel.extrude_dir(wire, normal, d1, d2)
    if plane is not None:
        return kernel.extrude(wire, plane, d1, mode == 'symmetric')
    return kernel.extrude_dir(wire, normal, d1, 0.0, mode == 'symmetric')


def combine(existing, tools, op, spent=(), ids=()):
    """Nowe bryły albo operacja logiczna narzędzi z bryłami; użyte szkice wygasają."""
    fade = lambda bodies: [replace(b, visible=False) if b.id in spent else b for b in bodies]
    if op == 'new':
        ids2 = pad_ids(ids, len(tools), list(ids)[0] if ids else None)
        return fade([*existing, *[Body('Wyciągnięcie', t, id=ids2[i]).prepared() for i, t in enumerate(tools)]])
    bodies, used = list(existing), False
    for tool in tools:
        box = kernel.bounds(tool)
        for i, b in enumerate(bodies):
            if b.kind != 'solid':
                continue
            other = kernel.bounds(b.shape)
            if (box.xmin > other.xmax + 1e-3 or box.xmax < other.xmin - 1e-3 or box.ymin > other.ymax + 1e-3 or
                    box.ymax < other.ymin - 1e-3 or box.zmin > other.zmax + 1e-3 or box.zmax < other.zmin - 1e-3):
                continue
            try:
                bodies[i] = b.changed(kernel.boolean({'join': 'union', 'cut': 'subtract', 'intersect': 'intersect'}[op], b.shape, [tool]))
                used = True
            except kernel.CadError:
                continue
    if not used:
        raise kernel.CadError('Nie ma bryły, z którą można wykonać tę operację. Profil musi dotykać bryły lub ją przecinać.')
    return fade(bodies)


def run_extrude(bodies, recipe):
    """Ponownie wykonuje zapisane wyciągnięcie / wycięcie na podanym stanie."""
    mode = recipe.get('dir', 'one')
    tools = [make_tool(src, float(recipe['d1']), float(recipe.get('d2', 0)), mode) for spec in recipe['profiles'] for src in resolve_profiles(bodies, spec)]
    spent = set(recipe.get('spent', ()))
    groups = {spec['group'] for spec in recipe['profiles'] if spec['k'] == 'textgroup'}
    spent |= {b.id for b in bodies if text_group_of(b.id) in groups}      # wszystkie litery napisu (także nowe po zmianie treści)
    return combine(bodies, tools, recipe['mode'], spent, recipe.get('out', ()))


def _body(bodies, identifier):
    body = next((b for b in bodies if b.id == identifier), None)
    if body is None:
        raise kernel.CadError('Obiekt użyty w tym kroku już nie istnieje.')
    return body


def _replace(bodies, new):
    return [new if b.id == new.id else b for b in bodies]


def radial(center, pivot, axis, radius_now=None):
    """(odległość środka obiektu od osi, wersor promieniowy) - jak w panelu Szyk."""
    axis = np.array(axis, float)
    axis /= np.linalg.norm(axis)
    v = np.array(center, float) - np.array(pivot, float)
    r = v - float(v @ axis) * axis
    d = float(np.linalg.norm(r))
    if d > 1e-6:
        return d, r / d
    other = np.cross(axis, [0.0, 0.0, 1.0] if abs(axis[2]) < .9 else [1.0, 0.0, 0.0])
    return 0.0, other / np.linalg.norm(other)


def pattern_ops_for(body, recipe):
    """(kopie, przesunięcie oryginału albo None) dla zapisanych parametrów szyku i bieżącego położenia obiektu."""
    kind, p = recipe['kind'], recipe['params']
    if kind == 'circ':
        center = np.array(kernel.bounds(body.shape).center.toTuple(), float)
        d0, direction = radial(center, p['pivot'], p['axis'])
        offset = tuple(float(c) for c in direction * (float(p['radius']) - d0))
        ops = kernel.pattern_ops('circ', dict(p, offset=offset))
        return ops, (('t', offset) if max(abs(c) for c in offset) > 1e-9 else None)
    return kernel.pattern_ops(kind, p), None


def run_pattern(bodies, recipe):
    body = _body(bodies, recipe['id'])
    ops, moved = pattern_ops_for(body, recipe)
    source = kernel.apply_op(body.shape, moved) if moved else body.shape
    copies = [kernel.apply_op(body.shape, op) for op in ops]
    if recipe.get('join') and body.kind == 'solid':
        merged = kernel.boolean('union', source, copies) if copies else source
        return _replace(bodies, body.changed(merged))
    out = pad_ids(recipe.get('out', ()), len(copies), (recipe.get('out') or [body.id])[0])
    made = [Body(f'{body.name} — szyk {i + 1}', sh, body.kind, body.plane, id=out[i]).prepared() for i, sh in enumerate(copies)]
    current = _replace(bodies, body.changed(source)) if moved else list(bodies)
    return [*current, *made]


def edge_refs(shape, indices):
    """Odwołania do krawędzi: środek, kierunek i normalne przylegających ścian (rozpoznanie niezależne od rozmiaru bryły)."""
    edges, out = shape.Edges(), []
    for i in sorted(indices):
        e = edges[i]
        a, b = np.array(e.positionAt(0).toTuple(), float), np.array(e.positionAt(1).toTuple(), float)
        d = b - a
        out.append(dict(mid=[float(c) for c in e.positionAt(.5).toTuple()], dir=[float(c) for c in (d / max(np.linalg.norm(d), 1e-12))],
                        normals=_adjacent_normals(shape, edge=e)))
    return out


def edge_indices(shape, refs):
    """Krawędzie bryły odpowiadające zapisanym odwołaniom: ten sam kierunek i sąsiedztwo ścian, najbliższy środek."""
    scale = _scale(shape)
    tol = max(1e-3, 0.02 * scale)
    edges = shape.Edges()
    mids = np.array([e.positionAt(.5).toTuple() for e in edges], float)
    info = None
    out = []
    for ref in refs:
        if not isinstance(ref, dict):                       # stary format: sam środek
            d = np.linalg.norm(mids - np.array(ref, float), axis=1)
            i = int(np.argmin(d))
            if d[i] > tol:
                raise kernel.CadError('Krawędź użyta w tym kroku już nie istnieje.')
            out.append(i)
            continue
        if info is None:
            info = []
            for e in edges:
                a, b = np.array(e.positionAt(0).toTuple(), float), np.array(e.positionAt(1).toTuple(), float)
                info.append((_unit(b - a) if np.linalg.norm(b - a) > 1e-12 else np.zeros(3), _adjacent_normals(shape, edge=e)))
        mid, direction = np.array(ref['mid'], float), np.array(ref['dir'], float)
        cands = [i for i, (d, n) in enumerate(info) if abs(float(d @ direction)) > .999 and _same_normals(n, ref['normals'])]
        if not cands:
            d = np.linalg.norm(mids - mid, axis=1)
            i = int(np.argmin(d))
            if d[i] > tol:
                raise kernel.CadError('Krawędź użyta w tym kroku już nie istnieje.')
            out.append(i)
            continue
        out.append(min(cands, key=lambda i: float(np.linalg.norm(mids[i] - mid))))
    return out


def vertex_refs(shape, points):
    return [dict(p=[float(c) for c in q], normals=_adjacent_normals(shape, vertex_point=np.array(q, float))) for q in points]


def vertex_points(shape, recipe):
    """Narożniki bryły odpowiadające zapisanym: ten sam układ przylegających ścian, najbliższy punkt."""
    refs = recipe.get('vrefs')
    if not refs:
        return [np.array(q, float) for q in recipe['verts']]
    pts = [np.array(v.toTuple(), float) for v in shape.Vertices()]
    tol = max(1e-3, 0.02 * _scale(shape))
    out = []
    for ref in refs:
        p0 = np.array(ref['p'], float)
        cands = [q for q in pts if _same_normals(_adjacent_normals(shape, vertex_point=q), ref['normals'])]
        pool = cands or [q for q in pts if float(np.linalg.norm(q - p0)) <= tol]
        if not pool:
            raise kernel.CadError('Narożnik użyty w tym kroku już nie istnieje.')
        out.append(min(pool, key=lambda q: float(np.linalg.norm(q - p0))))
    return out


def run_mod(bodies, recipe):
    body = _body(bodies, recipe['id'])
    if recipe.get('verts'):
        shape = kernel.blend_vertices(body.shape, vertex_points(body.shape, recipe), float(recipe['size']), recipe['kind'])
    else:
        shape = kernel.blend(body.shape, set(edge_indices(body.shape, recipe['edges'])), float(recipe['size']), recipe['kind'])
    return _replace(bodies, body.changed(shape))


def run_transform(bodies, recipe):
    body = _body(bodies, recipe['id'])
    v = tuple(float(c) for c in recipe['v'])
    shape = kernel.transform(body.shape, v, (0, 0, 0)) if recipe['mode'] == 'move' else kernel.transform(body.shape, (0, 0, 0), v)
    return _replace(bodies, body.changed(shape))


def run_mirror(bodies, recipe):
    body = _body(bodies, recipe['id'])
    shape = kernel.mirror_plane(body.shape, recipe['normal'], recipe['origin'])
    if recipe.get('join') and body.kind == 'solid':
        return _replace(bodies, body.changed(kernel.boolean('union', body.shape, [shape])))
    mirrored = Body(body.name + ' — odbicie', shape, body.kind, body.plane, id=recipe.get('out') or uuid.uuid4().hex).prepared()
    if recipe.get('keep'):
        return [*bodies, mirrored]
    return [mirrored if b.id == body.id else b for b in bodies]


def run_bool(bodies, recipe):
    base = _body(bodies, recipe['base'])
    tools = [_body(bodies, i) for i in recipe['tools']]
    result = base.changed(kernel.boolean(recipe['op'], base.shape, [t.shape for t in tools]))
    gone = set(recipe['tools'])
    return [result if b.id == base.id else b for b in bodies if recipe.get('keep') or b.id not in gone]


def run_text(bodies, recipe):
    """Dodaje szkic z tekstem (litery i ich otwory jako osobne druty) w zapisanej płaszczyźnie."""
    plane = plane_from_json(recipe['plane'])
    q = recipe['params']
    shapes = kernel.text_shape(plane, q['text'], *q['anchor'], size=q['size'], font=q['font'], bold=q['bold'], italic=q['italic'], angle=q['angle'])
    ids = list(recipe.get('out', ()))
    group = text_group_of(ids[0]) if ids else None
    if group:      # identyfikatory liter wynikają z grupy napisu, więc po zmianie treści kolejne kroki nadal je znajdują
        ids = text_ids(group, len(shapes))
    else:
        ids = pad_ids(ids, len(shapes), ids[0] if ids else None)
    return [*bodies, *[Body(recipe['name'], sh, 'sketch', plane, id=ids[i]).prepared() for i, sh in enumerate(shapes)]]


def run_delete(bodies, recipe):
    gone = set(recipe['ids'])
    return [b for b in bodies if b.id not in gone]


def run_sketchmeta(bodies, recipe):
    body = _body(bodies, recipe['id'])
    meta = recipe['meta']
    shape = meta_shape(body.plane, meta)
    return _replace(bodies, replace(body, shape=shape, mesh=kernel.display_mesh(shape), meta=meta))


def run_trim(bodies, recipe):
    """Nożyczki: usuwa kawałek szkicu (między przecięciami z innymi szkicami) najbliższy zapisanemu punktowi."""
    body = _body(bodies, recipe['id'])
    plane = kernel.actual_frame(body.shape, body.plane)
    group = sketch_groups(bodies).get(plane_key(plane))
    if group is None or body not in group[1]:
        raise kernel.CadError('Szkic nie jest już widoczny w tej płaszczyźnie.')
    members = group[1]
    pieces = kernel.trim_pieces([b.shape.Edges() for b in members], members.index(body))
    if not pieces:
        raise kernel.CadError('Brak kawałków do przycięcia.')
    mid = np.array(recipe['mid'], float)
    index = min(range(len(pieces)), key=lambda i: float(np.linalg.norm(np.array(pieces[i].positionAt(.5).toTuple()) - mid)))
    wires = kernel.trim_result(pieces, index)
    ids = pad_ids(recipe.get('out', ()), len(wires), (recipe.get('out') or [body.id])[0])
    made = [Body(body.name, w, 'sketch', body.plane, id=ids[i]).prepared() for i, w in enumerate(wires)]
    out = []
    for b in bodies:
        out.extend(made if b.id == body.id else [b])
    return out


def place_bodies(bodies, ids, move=(0, 0, 0), rotate=(0, 0, 0)):
    """Przesuwa i obraca (wokół wspólnego środka) wskazane obiekty: edycja położenia obiektów dodanych w kroku bez przepisu."""
    ids = set(ids)
    group = [b for b in bodies if b.id in ids]
    if not group:
        return tuple(bodies)
    center = np.mean([b.shape.Center().toTuple() for b in group], axis=0)
    out = []
    for b in bodies:
        if b.id not in ids:
            out.append(b)
            continue
        shape = b.shape
        for axis, angle in zip(((1, 0, 0), (0, 1, 0), (0, 0, 1)), rotate):
            if angle:
                shape = shape.rotate(tuple(float(c) for c in center), tuple(float(center[i] + axis[i]) for i in range(3)), float(angle))
        out.append(replace(b.changed(shape.translate(tuple(float(c) for c in move))), meta=None))
    return tuple(out)


RUNNERS = {'delete': run_delete, 'sketchmeta': run_sketchmeta, 'trim': run_trim, 'text': run_text, 'extrude': run_extrude, 'pattern': run_pattern, 'mod': run_mod, 'transform': run_transform, 'mirror': run_mirror, 'bool': run_bool}


_BINARY = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv, ast.Pow: operator.pow,
           ast.Mod: operator.mod, ast.FloorDiv: operator.floordiv}
_FUNCTIONS = {'sqrt': math.sqrt, 'sin': lambda x: math.sin(math.radians(x)), 'cos': lambda x: math.cos(math.radians(x)),
              'tan': lambda x: math.tan(math.radians(x)), 'abs': abs, 'min': min, 'max': max, 'round': round}


def _decimal(text):
    text = str(text).strip()
    return text if re.search(r'\b(min|max|round)\s*\(', text) else text.replace(',', '.')


def evaluate(text, variables=None):
    """Bezpieczne wyliczenie wyrażenia (liczby, + - * / ** %, nawiasy, zmienne, sqrt / sin / cos / tan / abs / min / max / round, pi)."""
    names = dict(variables or {})
    names.setdefault('pi', math.pi)

    def walk(node):
        if isinstance(node, ast.Expression):
            return walk(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return float(node.value)
        if isinstance(node, ast.Name) and node.id in names:
            return float(names[node.id])
        if isinstance(node, ast.BinOp) and type(node.op) in _BINARY:
            return float(_BINARY[type(node.op)](walk(node.left), walk(node.right)))
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
            return -walk(node.operand) if isinstance(node.op, ast.USub) else walk(node.operand)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _FUNCTIONS and not node.keywords:
            return float(_FUNCTIONS[node.func.id](*[walk(a) for a in node.args]))
        raise ValueError(ast.dump(node)[:40])

    try:
        value = walk(ast.parse(_decimal(text), mode='eval'))
    except Exception as exc:
        raise kernel.CadError(f'Nieprawidłowe wyrażenie: {text}') from exc
    if not math.isfinite(value):
        raise kernel.CadError(f'Wyrażenie nie daje liczby: {text}')
    return value


def variable_values(variables):
    """Zmienne projektu (nazwa -> wyrażenie) policzone po kolei: późniejsze mogą korzystać z wcześniejszych."""
    out = {}
    for name, expr in (variables or {}).items():
        out[name] = evaluate(expr, out)
    return out


def has_expr(obj):
    if isinstance(obj, dict):
        return ('expr' in obj and len(obj) == 1) or any(has_expr(v) for v in obj.values())
    if isinstance(obj, (list, tuple)):
        return any(has_expr(v) for v in obj)
    return False


def resolve(obj, values):
    """Zamienia {'expr': '...'} w przepisie na liczby (według zmiennych projektu)."""
    if isinstance(obj, dict):
        if len(obj) == 1 and 'expr' in obj:
            return evaluate(obj['expr'], values)
        return {k: resolve(v, values) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [resolve(v, values) for v in obj]
    return obj


class Context:
    """Więzy, zmienne i znacznik zmiany zmiennych przekazywane do przeliczania."""

    def __init__(self, constraints=(), values=None, force=False):
        self.constraints, self.values, self.force = list(constraints or ()), dict(values or {}), force


def _ctx(value):
    return value if isinstance(value, Context) else Context(value or ())


def changed_ids(before, current):
    """Identyfikatory obiektów, które różnią się między dwoma stanami (inny kształt, widoczność, nazwa albo brak po jednej stronie)."""
    bm, cm = {b.id: b for b in before}, {b.id: b for b in current}
    return {i for i in bm.keys() | cm.keys()
            if i not in bm or i not in cm or bm[i].shape is not cm[i].shape or bm[i].visible != cm[i].visible or bm[i].name != cm[i].name}


def reads(recipe, current):
    """Zbiór obiektów, od których zależy wynik kroku (None = nie wiadomo, trzeba liczyć od nowa)."""
    kind = recipe['type']
    sketches = {b.id for b in current if b.kind == 'sketch'}
    if kind == 'extrude':
        ids = set(recipe.get('spent', ()))
        for spec in recipe['profiles']:
            if spec['k'] in ('region', 'textgroup'):
                ids |= sketches
            else:
                ids.add(spec['id'])
        return ids
    if kind in ('mod', 'transform', 'mirror', 'pattern', 'sketchmeta'):
        return {recipe['id']}
    if kind == 'bool':
        return {recipe['base'], *recipe['tools']}
    if kind == 'delete':
        return set(recipe['ids'])
    if kind == 'trim':
        return {recipe['id']} | sketches
    if kind == 'text':
        return set()
    return None


def run_recipe(bodies, recipe, values=None):
    if values is not None and has_expr(recipe):
        recipe = resolve(recipe, values)
    return tuple(RUNNERS[recipe['type']](bodies, recipe))


def diff_apply(old_prev, old_cur, new_prev):
    """Ogólny krok bez przepisu: przenosi różnicę (dodane / usunięte / zmienione obiekty) na nowy stan poprzedni.
    Zwraca (bryły, czy_się_udało)."""
    prev, cur = {b.id: b for b in old_prev}, {b.id: b for b in old_cur}
    merged = {b.id: b for b in new_prev}
    ok = True
    for i in prev:
        if i not in cur:
            merged.pop(i, None)
    for i, b in cur.items():
        if i not in prev:
            merged.setdefault(i, b)
            continue
        ob, nb = prev[i], merged.get(i)
        if nb is None:
            continue
        if b.shape is not ob.shape:
            if nb.shape is ob.shape:
                merged[i] = replace(nb, shape=b.shape, mesh=b.mesh, meta=b.meta, name=b.name, visible=b.visible, plane=b.plane)
            else:
                ok = False          # ten obiekt zmienił się na wcześniejszym kroku, a ten krok nie ma przepisu
            continue
        changes = {f: getattr(b, f) for f in ('name', 'visible', 'plane') if getattr(b, f) != getattr(ob, f)}
        if changes:
            merged[i] = replace(nb, **changes)
    order = [i for i in cur if i in merged] + [i for i in merged if i not in cur]
    return [merged[i] for i in order], ok


def meta_shape(plane, meta):
    t = meta['tool']
    pts = [tuple(p) for p in meta['points']]
    if t == 'line':
        return kernel.polyline(plane, pts, False)
    if t == 'arc':
        return kernel.arc3(plane, pts)
    if t == 'rect3':
        return kernel.rect3(plane, pts)
    return kernel.sketch_shape(t, plane, pts, meta.get('sides', 5))


def apply_constraints(bodies, constraints):
    """Więzy wymiarów: wymiar bi szkicu b = k * wymiar ai szkicu a albo = wyrażenie ze zmiennych projektu. Brak szkicu - więz pomijany."""
    ctx = _ctx(constraints)
    if not ctx.constraints:
        return tuple(bodies)
    bodies = list(bodies)
    for _ in range(len(ctx.constraints) + 1):      # kilka przebiegów: łańcuch więzów (A -> B -> C) ustala się niezależnie od kolejności
      changed = False
      for c in ctx.constraints:
          index = {b.id: i for i, b in enumerate(bodies)}
          if c['b'] not in index:
              continue
          b = bodies[index[c['b']]]
          if not (b.meta and b.meta.get('tool') in sm.EDITABLE):
              continue
          try:
              if 'expr' in c:
                  target = evaluate(c['expr'], ctx.values)
              else:
                  if c['a'] not in index:
                      continue
                  a = bodies[index[c['a']]]
                  if not (a.meta and a.meta.get('tool') in sm.EDITABLE):
                      continue
                  target = float(sm.values(a.meta)[c['ai']].replace(',', '.')) * float(c.get('k', 1.0))
              values = [float(x.replace(',', '.')) for x in sm.values(b.meta)]
              if abs(values[c['bi']] - target) < 1e-6:
                  continue
              values[c['bi']] = target
              meta = sm.apply_values(b.meta, values)
              shape = meta_shape(b.plane, meta)
              bodies[index[c['b']]] = Body(b.name, shape, b.kind, b.plane, b.id, b.visible, meta=meta).prepared()
              changed = True
          except Exception:
              continue
      if not changed:
        break
    return tuple(bodies)


def constraint_cycle(constraints):
    """True, gdy więzy wymiarów tworzą pętlę zależności (wymiar zależy od samego siebie przez inne)."""
    graph = {}
    for c in constraints:
        if 'a' in c:
            graph.setdefault((c['a'], c['ai']), set()).add((c['b'], c['bi']))
    state = {}

    def visit(node):
        state[node] = 1
        for nxt in graph.get(node, ()):
            if state.get(nxt) == 1 or (nxt not in state and visit(nxt)):
                return True
        state[node] = 2
        return False
    return any(node not in state and visit(node) for node in list(graph))


def rebuild(base, steps, constraints=(), job=None):
    ctx = _ctx(constraints)
    """Wykonuje kolejno kroki na stanie `base`. steps: lista (stan_przed_oryginalny, stan_po_oryginalny, info[, info_oryginalny]).
    Szybkie ścieżki: stan wejściowy nie zmienił się względem oryginału -> wynik oryginalny; krok niezależny od zmienionych obiektów ->
    przeniesienie różnicy bez ponownych obliczeń. Krok wyłączony ('off') niczego nie zmienia; nieprzeliczalny dostaje 'stale'.
    job: słownik {'cancel', 'i', 'n'} do przerywania i paska postępu. Zwraca (lista (bryły, info), liczba nieprzeliczonych)."""
    out, failed, current = [], 0, tuple(base)
    for n, step in enumerate(steps):
        before, after, info = step[:3]
        original = step[3] if len(step) > 3 else info
        if job is not None:
            if job.get('cancel'):
                raise kernel.CadError('Przeliczanie przerwane.')
            job['i'], job['n'] = n, len(steps)
        info = {key: v for key, v in info.items() if key != 'stale'}
        original = {key: v for key, v in original.items() if key != 'stale'}
        recipe = info.get('op')
        result, why = None, None
        diff = changed_ids(before, current)
        expr_step = bool(recipe) and ctx.force and has_expr(recipe)
        if info == original and not diff and not expr_step:
            result = tuple(after)
        elif info.get('off'):
            result = current
        elif recipe and recipe.get('type') in RUNNERS:
            dependencies = reads(recipe, current) if (info == original and not expr_step) else None
            if dependencies is not None and not (dependencies & diff):
                merged, ok = diff_apply(before, after, current)
                result = tuple(merged) if ok else None
            if result is None:
                try:
                    result = run_recipe(current, recipe, ctx.values)
                except Exception as exc:
                    result, why = None, str(exc) or exc.__class__.__name__
        else:
            merged, ok = diff_apply(before, after, current)
            result = tuple(merged) if ok else None
            if not ok:
                why = 'Ten krok zmienił obiekt, który wcześniej został zmieniony, a krok nie ma przepisu do ponownego wykonania.'
        info.pop('why', None)
        if result is None:
            failed += 1
            info['stale'] = True
            info['why'] = why or 'Nie udało się przeliczyć tego kroku.'
            result = current
        result = apply_constraints(result, ctx)
        out.append((result, info))
        current = result
    return out, failed


def _steps(states, indices):
    return [(states[j - 1][0], states[j][0], states[j][1]) for j in indices]


def recompute(states, k, edited_bodies, constraints=(), job=None):
    """Po edycji kroku k (jego nowy wynik: edited_bodies) przelicza kolejne kroki. Zwraca (nowe stany, liczba nieprzeliczonych kroków)."""
    edited_bodies = apply_constraints(edited_bodies, constraints)
    head = list(states[:k]) + [(tuple(edited_bodies), {key: v for key, v in states[k][1].items() if key not in ('stale', 'why')})]
    tail, failed = rebuild(edited_bodies, _steps(states, range(k + 1, len(states))), constraints, job)
    return head + tail, failed


def toggle_step(states, j, constraints=(), job=None):
    """Wyłącza / włącza krok j (stan go pomija) i przelicza resztę."""
    info = dict(states[j][1])
    if info.get('off'):
        info.pop('off')
    else:
        info['off'] = True
    steps = [(states[j - 1][0], states[j][0], info, states[j][1]), *_steps(states, range(j + 1, len(states)))]
    tail, failed = rebuild(states[j - 1][0], steps, constraints, job)
    return list(states[:j]) + tail, failed


def delete_step(states, j, constraints=(), job=None):
    """Usuwa krok j z osi czasu i przelicza następne."""
    tail, failed = rebuild(states[j - 1][0], _steps(states, range(j + 1, len(states))), constraints, job)
    return list(states[:j]) + tail, failed


def move_step(states, j, constraints=(), job=None):
    """Zamienia miejscami kroki j i j+1 (krok j przesuwa się później) i przelicza od j."""
    steps = [(states[j][0], states[j + 1][0], states[j + 1][1]), (states[j - 1][0], states[j][0], states[j][1]),
             *_steps(states, range(j + 2, len(states)))]
    tail, failed = rebuild(states[j - 1][0], steps, constraints, job)
    return list(states[:j]) + tail, failed


def recompute_all(states, constraints=(), job=None):
    """Pełne przeliczenie od pierwszego kroku (np. po zmianie zmiennej projektu): kroki z wyrażeniami liczone od nowa."""
    ctx = _ctx(constraints)
    ctx.force = True
    tail, failed = rebuild(states[0][0], _steps(states, range(1, len(states))), ctx, job)
    return [states[0], *tail], failed
