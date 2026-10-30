"""Historia parametryczna: przepisy operacji (JSON), ich ponowne wykonanie na zmienionym stanie i przeliczanie następnych kroków.
Czysta logika bez Qt: studio podaje stany (listy Body), a tu wyliczane są nowe stany po edycji któregoś kroku."""
from __future__ import annotations
import uuid
from dataclasses import replace
import numpy as np
import cadquery as cq
from . import kernel
from .document import Body

# klucz ikony kroku -> ikona paska narzędzi (icons.pixmap('t_' + nazwa)); wartości wspólne dla wszystkich kroków historii
ICONS = {'start': 'history', 'sketch': 'sketch', 'extrude': 'extrude', 'cut': 'cut', 'intersect': 'bool', 'bool': 'bool', 'mod': 'mod',
         'mirror': 'mirror', 'pattern': 'pattern', 'move': 'move', 'rotate': 'rotate', 'trash': 'trash', 'file': 'file', 'text': 'text'}
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


def face_ref(face, normal, point):
    c = np.array(face.Center().toTuple(), float)
    n = _unit(normal)
    return dict(normal=[float(x) for x in n], point=[float(x) for x in point], centroid=[float(x) for x in c], area=float(face.Area()))


def match_face(shape, ref):
    """Płaska ściana bryły odpowiadająca zapisanej: najpierw ta, która nadal zawiera punkt; inaczej najlepiej pasująca
    (ta sama normalna, położenie płaszczyzny, środek i pole), więc krok przeżywa zmianę rozmiaru bryły."""
    n0 = _unit(ref['normal'])
    try:
        return kernel.face_at(shape, n0, ref['point'])
    except kernel.CadError:
        pass
    c0, a0, scale = np.array(ref.get('centroid', ref['point']), float), float(ref.get('area', 0.0)), _scale(shape)
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
        score = off + .25 * inplane + .5 * scale * abs(area - a0) / max(area, a0, 1e-9)
        if best is None or score < best[0]:
            best = (score, face, fn)
    if best is None or best[0] > 1.5 * scale:
        raise kernel.CadError('Ściana użyta w tym kroku już nie istnieje.')
    return best[1], best[2]


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
            ref = face_ref(src['face'], src['normal'], src.get('hit', src['center'])) if src.get('face') is not None else dict(
                normal=[float(c) for c in src['normal']], point=[float(c) for c in src.get('hit', src['center'])])
            out.append(dict(ref, k='face', id=src['id']))
    return out


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
        faces = kernel.regions(plane, [e for b in members for e in b.shape.Edges()], [b.shape for b in members if b.shape.IsClosed()])
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
        return fade([*existing, *[Body('Wyciągnięcie', t, id=(ids[i] if i < len(ids) else uuid.uuid4().hex)).prepared() for i, t in enumerate(tools)]])
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
    tools = [make_tool(resolve_profile(bodies, spec), float(recipe['d1']), float(recipe.get('d2', 0)), mode) for spec in recipe['profiles']]
    return combine(bodies, tools, recipe['mode'], set(recipe.get('spent', ())), recipe.get('out', ()))


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
    out = list(recipe.get('out', ()))
    out += [uuid.uuid4().hex for _ in range(len(copies) - len(out))]
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
    ids += [uuid.uuid4().hex for _ in range(len(shapes) - len(ids))]
    return [*bodies, *[Body(recipe['name'], sh, 'sketch', plane, id=ids[i]).prepared() for i, sh in enumerate(shapes)]]


RUNNERS = {'text': run_text, 'extrude': run_extrude, 'pattern': run_pattern, 'mod': run_mod, 'transform': run_transform, 'mirror': run_mirror, 'bool': run_bool}


def run_recipe(bodies, recipe):
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


def rebuild(base, steps):
    """Wykonuje kolejno kroki na stanie `base`. steps: lista (stan_przed_oryginalny, stan_po_oryginalny, info) - dwa pierwsze służą
    krokom bez przepisu (przenoszenie różnicy). Krok wyłączony ('off') niczego nie zmienia; nieprzeliczalny dostaje 'stale'.
    Zwraca (lista (bryły, info), liczba nieprzeliczonych)."""
    out, failed, current = [], 0, tuple(base)
    for before, after, info in steps:
        info = {key: v for key, v in info.items() if key != 'stale'}
        recipe = info.get('op')
        result = None
        if info.get('off'):
            result = current
        elif recipe and recipe.get('type') in RUNNERS:
            try:
                result = run_recipe(current, recipe)
            except Exception:
                result = None
        else:
            merged, ok = diff_apply(before, after, current)
            result = tuple(merged) if ok else None
        if result is None:
            failed += 1
            info['stale'] = True
            result = current
        out.append((result, info))
        current = result
    return out, failed


def _steps(states, indices):
    return [(states[j - 1][0], states[j][0], states[j][1]) for j in indices]


def recompute(states, k, edited_bodies):
    """Po edycji kroku k (jego nowy wynik: edited_bodies) przelicza kolejne kroki. Zwraca (nowe stany, liczba nieprzeliczonych kroków)."""
    head = list(states[:k]) + [(tuple(edited_bodies), {key: v for key, v in states[k][1].items() if key != 'stale'})]
    tail, failed = rebuild(edited_bodies, _steps(states, range(k + 1, len(states))))
    return head + tail, failed


def toggle_step(states, j):
    """Wyłącza / włącza krok j (stan go pomija) i przelicza resztę."""
    info = dict(states[j][1])
    if info.get('off'):
        info.pop('off')
    else:
        info['off'] = True
    steps = [(states[j - 1][0], states[j][0], info), *_steps(states, range(j + 1, len(states)))]
    tail, failed = rebuild(states[j - 1][0], steps)
    return list(states[:j]) + tail, failed


def delete_step(states, j):
    """Usuwa krok j z osi czasu i przelicza następne."""
    tail, failed = rebuild(states[j - 1][0], _steps(states, range(j + 1, len(states))))
    return list(states[:j]) + tail, failed


def move_step(states, j):
    """Zamienia miejscami kroki j i j+1 (krok j przesuwa się później) i przelicza od j."""
    steps = [(states[j][0], states[j + 1][0], states[j + 1][1]), (states[j - 1][0], states[j][0], states[j][1]),
             *_steps(states, range(j + 2, len(states)))]
    tail, failed = rebuild(states[j - 1][0], steps)
    return list(states[:j]) + tail, failed
