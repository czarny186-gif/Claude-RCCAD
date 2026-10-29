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


def describe_profiles(profiles):
    """Przepis na wybrane profile wyciągnięcia (src z Studio) -> lista słowników JSON."""
    out = []
    for src in profiles:
        if src['kind'] == 'sketch':
            out.append({'k': 'sketch', 'id': src['id']})
        elif src['kind'] == 'region':
            out.append({'k': 'region', 'plane': plane_to_json(src['plane']), 'center': [float(c) for c in src['center']]})
        else:
            out.append({'k': 'face', 'id': src['id'], 'normal': [float(c) for c in src['normal']],
                        'point': [float(c) for c in src.get('hit', src['center'])]})
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
        inside = [f for f in faces if kernel.face_contains(f, center)]
        face = min(inside or faces, key=lambda f: float(np.linalg.norm(np.array(f.Center().toTuple()) - center)) if not inside else float(f.Area()))
        return dict(wire=face.outerWire(), normal=tuple(kernel.frame_of(plane).normal), plane=plane, face=face)
    body = by_id.get(spec['id'])
    if body is None or body.kind != 'solid':
        raise kernel.CadError('Bryła użyta w tym kroku już nie istnieje.')
    found = kernel.face_at(body.shape, spec['normal'], spec['point'])
    if found is None or found[0] is None:
        raise kernel.CadError('Ściana użyta w tym kroku już nie istnieje.')
    face, normal = found
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
    edges = shape.Edges()
    return [[float(c) for c in edges[i].positionAt(.5).toTuple()] for i in sorted(indices)]


def edge_indices(shape, refs):
    """Krawędzie bryły najbliższe zapisanym środkom (tolerancja proporcjonalna do rozmiaru bryły)."""
    box = kernel.bounds(shape)
    tol = max(1e-3, 0.02 * max(box.xlen, box.ylen, box.zlen))
    mids = np.array([e.positionAt(.5).toTuple() for e in shape.Edges()], float)
    out = []
    for ref in refs:
        d = np.linalg.norm(mids - np.array(ref, float), axis=1)
        i = int(np.argmin(d))
        if d[i] > tol:
            raise kernel.CadError('Krawędź użyta w tym kroku już nie istnieje.')
        out.append(i)
    return out


def run_mod(bodies, recipe):
    body = _body(bodies, recipe['id'])
    if recipe.get('verts'):
        shape = kernel.blend_vertices(body.shape, [np.array(q, float) for q in recipe['verts']], float(recipe['size']), recipe['kind'])
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


RUNNERS = {'extrude': run_extrude, 'pattern': run_pattern, 'mod': run_mod, 'transform': run_transform, 'mirror': run_mirror, 'bool': run_bool}


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


def recompute(states, k, edited_bodies):
    """Po edycji kroku k (jego nowy wynik: edited_bodies) przelicza kolejne kroki. Zwraca (nowe stany, liczba nieprzeliczonych kroków).
    Krok bez możliwości przeliczenia zostaje w osi czasu z oznaczeniem 'stale' i nie zmienia stanu."""
    out = list(states[:k]) + [(tuple(edited_bodies), {key: v for key, v in states[k][1].items() if key != 'stale'})]
    failed = 0
    for j in range(k + 1, len(states)):
        _, info = states[j]
        info = {key: v for key, v in info.items() if key != 'stale'}
        base = out[-1][0]
        recipe = info.get('op')
        result = None
        if recipe and recipe.get('type') in RUNNERS:
            try:
                result = run_recipe(base, recipe)
            except Exception:
                result = None
        else:
            merged, ok = diff_apply(states[j - 1][0], states[j][0], base)
            result = tuple(merged) if ok else None
        if result is None:
            failed += 1
            info['stale'] = True
            result = tuple(base)
        out.append((result, info))
    return out, failed
