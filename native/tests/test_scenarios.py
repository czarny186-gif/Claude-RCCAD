"""Scenariusze z życia: operacje -> cofnięcie się -> zmiana kroku -> powrót na koniec -> dalsza praca.
Wzorzec poprawności: wynik przeliczenia historii musi być taki sam jak świeże wykonanie tych samych kroków od początku."""
import unittest, tempfile
from dataclasses import replace
from pathlib import Path
from rccad import kernel as k, history as h
from rccad.document import Body, Document

PTS = lambda *p: [list(x) for x in p]


def sketch(name, tool, pts, plane='XY', ident=None):
    shape = k.polyline(plane, [tuple(p) for p in pts], False) if tool == 'line' else k.sketch_shape(tool, plane, [tuple(p) for p in pts], 5)
    body = Body(name, shape, 'sketch', plane, meta=dict(tool=tool, points=PTS(*pts), sides=5)).prepared()
    return replace(body, id=ident) if ident else body


def signature(bodies):
    out = []
    for b in bodies:
        box = k.bounds(b.shape)
        out.append((b.id, b.kind, bool(b.visible), round(b.shape.Volume(), 2) if b.kind == 'solid' else 0.0,
                    round(box.xmin, 2), round(box.ymin, 2), round(box.zmin, 2), round(box.xmax, 2), round(box.ymax, 2), round(box.zmax, 2)))
    return sorted(out)


class Scenario:
    """Rejestruje kroki jak Studio (raw = gotowe bryły, op = przepis) i potrafi odtworzyć je od zera z podmienionym krokiem."""

    def __init__(self):
        self.doc = Document()
        self.items = []

    def raw(self, fn, label='Szkic'):
        self.items.append(('raw', fn, label))
        self.doc.commit(fn(self.doc.bodies), label)
        return len(self.items)          # numer stanu w historii

    def op(self, recipe, label='Operacja'):
        self.items.append(('op', recipe, label))
        self.doc.pending_op = recipe
        self.doc.commit(h.run_recipe(self.doc.bodies, recipe), label, recipe['type'] if recipe['type'] in h.ICONS else 'move')
        return len(self.items)

    def fresh(self, index=None, replacement=None):
        """Wynik wykonania wszystkich kroków od zera (opcjonalnie z podmienionym krokiem `index`)."""
        bodies = ()
        for n, (kind, payload, _) in enumerate(self.items, 1):
            if kind == 'raw':
                bodies = tuple(payload(bodies))
                if n == index:
                    bodies = tuple(replacement(bodies))      # krok bez przepisu: zmiana jego wyniku (jak edycja szkicu w panelu)
            else:
                bodies = h.run_recipe(bodies, replacement if n == index else payload)
        return bodies

    def edit(self, index, replacement):
        """Edycja kroku jak w panelu historii: nowy wynik kroku + przeliczenie następnych. Zwraca (stany, liczba nieprzeliczonych)."""
        states = self.doc.states()
        _, kind_payload, _ = self.items[index - 1]
        kind = self.items[index - 1][0]
        before = states[index - 1][0]
        if kind == 'raw':
            first = tuple(replacement(states[index][0]))
            patched = states
        else:
            first = h.run_recipe(before, replacement)
            patched = list(states)
            patched[index] = (states[index][0], dict(states[index][1], op=replacement))
        return h.recompute(patched, index, first, ())


class ScenarioTests(unittest.TestCase):
    def check_edit(self, scenario, index, replacement):
        states, failed = scenario.edit(index, replacement)
        self.assertEqual(failed, 0, [i.get('why') for _, i in states if i.get('stale')])
        expected = scenario.fresh(index, replacement)
        self.assertEqual(signature(states[-1][0]), signature(expected))
        return states

    def box_scene(self):
        box = Body('Baza', k.box(20, 20, 10)).prepared()
        circle = sketch('Otwór', 'circle', [(10, 10), (13, 10)])
        sc = Scenario()
        sc.raw(lambda cur, b=box: [*cur, b], 'Baza')
        sc.raw(lambda cur, c=circle: [*cur, c], 'Szkic otworu')
        cut = dict(type='extrude', mode='cut', dir='one', d1=6.0, d2=0, profiles=[{'k': 'sketch', 'id': circle.id}], spent=[circle.id], out=[])
        sc.op(cut, 'Otwór')
        sc.box, sc.circle, sc.cut = box, circle, cut
        return sc

    def test_hole_then_more_steps_then_resize_base_and_continue(self):
        sc = self.box_scene()
        edge = [i for i, e in enumerate(sc.doc.bodies[0].shape.Edges()) if abs(e.positionAt(.5).toTuple()[0]) < 1e-6 and abs(e.positionAt(.5).toTuple()[1]) < 1e-6 and abs(e.positionAt(0).toTuple()[2] - e.positionAt(1).toTuple()[2]) > 1][0]
        base_id = sc.box.id
        sc.op(dict(type='mod', id=base_id, kind='fillet', size=2.0, verts=[], edges=h.edge_refs(sc.doc.bodies[0].shape, [edge])), 'Zaokrąglenie')
        sc.op(dict(type='transform', id=base_id, mode='move', v=[5.0, 0.0, 0.0]), 'Przesunięcie')
        bigger = lambda cur, b=sc.box: [replace(x, shape=k.box(30, 30, 10), mesh=None).prepared() if x.id == b.id else x for x in cur]
        states = self.check_edit(sc, 1, bigger)
        # po edycji wracamy na koniec i pracujemy dalej: nowy krok na wyniku przeliczenia
        d = Document()
        d.commit(states[-1][0], 'x')
        d.rewrite(states, len(states) - 1)
        d.pending_op = dict(type='transform', id=base_id, mode='move', v=[0.0, 5.0, 0.0])
        d.commit(h.run_recipe(d.bodies, d.pending_op), 'Dalej')
        self.assertEqual(len(d.states()), len(states) + 1)

    def test_hole_resize_in_the_middle(self):
        sc = self.box_scene()
        sc.op(dict(type='transform', id=sc.box.id, mode='move', v=[1.0, 2.0, 0.0]), 'Przesunięcie')
        wide = lambda cur, c=sc.circle: [x if x.id != c.id else sketch(c.name, 'circle', [(10, 10), (16, 10)], ident=c.id) for x in cur]
        states = self.check_edit(sc, 2, wide)
        solid = [b for b in states[-1][0] if b.kind == 'solid'][0]
        self.assertLess(solid.shape.Volume(), 20 * 20 * 10 - 3.14 * 5 * 5 * 6 + 1)       # otwór faktycznie się powiększył

    def test_cut_depth_and_mode_edit(self):
        sc = self.box_scene()
        sc.op(dict(type='transform', id=sc.box.id, mode='move', v=[3.0, 0.0, 0.0]), 'Przesunięcie')
        self.check_edit(sc, 3, dict(sc.cut, d1=9.0))

    def test_toggle_delete_and_move_steps_match_fresh(self):
        sc = self.box_scene()
        a = sc.op(dict(type='transform', id=sc.box.id, mode='move', v=[4.0, 0.0, 0.0]), 'A')
        b = sc.op(dict(type='transform', id=sc.box.id, mode='move', v=[0.0, 4.0, 0.0]), 'B')
        states = sc.doc.states()
        off, failed = h.toggle_step(states, a)
        self.assertEqual(failed, 0)
        only_b = [x for x in sc.doc.states()]
        y = [bd for bd in off[-1][0] if bd.kind == 'solid'][0].shape.Center().toTuple()
        x0 = [bd for bd in states[-1][0] if bd.kind == 'solid'][0].shape.Center().toTuple()
        self.assertAlmostEqual(x0[0] - y[0], 4.0, 2)      # po wyłączeniu A zostaje samo przesunięcie B
        gone, failed = h.delete_step(states, a)
        self.assertEqual(failed, 0)
        self.assertEqual(signature(gone[-1][0]), signature(off[-1][0]))
        swapped, failed = h.move_step(states, a)
        self.assertEqual(failed, 0)
        self.assertEqual(signature(swapped[-1][0]), signature(states[-1][0]))      # przesunięcia są przemienne

    def test_text_cut_then_edit_text_matches_fresh(self):
        try:
            k.text_shape('XY', 'AB', 0, 0, 10)
        except Exception:
            self.skipTest('brak czcionki w środowisku')
        box = Body('Płyta', k.box(80, 30, 10)).prepared()
        group = h.new_text_group()
        txt = lambda content: dict(type='text', plane='XY', name='Tekst', out=h.text_ids(group, 2),
                                   params=dict(text=content, anchor=[5, 5], size=12.0, font='Arial', bold=False, italic=False, angle=0.0))
        sc = Scenario()
        sc.raw(lambda cur, b=box: [*cur, b], 'Płyta')
        sc.op(txt('AB'), 'Tekst')
        letters = [b for b in sc.doc.bodies if b.kind == 'sketch']
        faces = h.material_regions('XY', letters)
        srcs = [dict(kind='region', id=None, face=f, wire=f.outerWire(), plane='XY', normal=(0, 0, 1), center=f.Center().toTuple()) for f in faces]
        specs = h.describe_profiles(srcs, sc.doc.bodies)
        self.assertEqual([s['k'] for s in specs], ['textgroup'])
        sc.op(dict(type='extrude', mode='cut', dir='one', d1=3.0, d2=0, profiles=specs, spent=[b.id for b in letters], out=[]), 'Wycięcie napisu')
        edge = [i for i, e in enumerate(box.shape.Edges()) if abs(e.positionAt(.5).toTuple()[0]) < 1e-6 and abs(e.positionAt(.5).toTuple()[1]) < 1e-6 and abs(e.positionAt(0).toTuple()[2] - e.positionAt(1).toTuple()[2]) > 1][0]
        sc.op(dict(type='mod', id=box.id, kind='chamfer', size=1.5, verts=[], edges=h.edge_refs(box.shape, [edge])), 'Faza')
        sc.op(dict(type='transform', id=box.id, mode='move', v=[0.0, 0.0, 4.0]), 'Przesunięcie')
        for content in ('ABCD', 'A'):
            states = self.check_edit(sc, 2, txt(content))
            self.assertFalse(any(b.kind == 'sketch' and b.visible for b in states[-1][0]), content)       # wszystkie litery zużyte

    def test_embossed_text_on_solid_face_frame_then_edit_text(self):
        try:
            k.text_shape('XY', 'AB', 0, 0, 10)
        except Exception:
            self.skipTest('brak czcionki w środowisku')
        box = Body('Płyta', k.box(80, 30, 10)).prepared()
        frame = k.Frame((0.0, 0.0, 10.0), (1.0, 0.0, 0.0), (0.0, 0.0, 1.0))
        group = h.new_text_group()
        txt = lambda content: dict(type='text', plane=h.plane_to_json(frame), name='Tekst', out=h.text_ids(group, 2),
                                   params=dict(text=content, anchor=[5, 5], size=12.0, font='Arial', bold=False, italic=False, angle=0.0))
        sc = Scenario()
        sc.raw(lambda cur, b=box: [*cur, b], 'Płyta')
        sc.op(txt('BO'), 'Tekst')
        letters = [b for b in sc.doc.bodies if b.kind == 'sketch']
        all_faces = h._group_regions(frame, letters)
        faces = h.material_regions(frame, letters)
        self.assertLessEqual(len(faces), len(all_faces))
        srcs = [dict(kind='region', id=None, face=f, wire=f.outerWire(), plane=frame, normal=(0, 0, 1), center=f.Center().toTuple()) for f in faces]
        specs = h.describe_profiles(srcs, sc.doc.bodies)
        self.assertEqual([x['k'] for x in specs], ['textgroup'], f'regions={len(all_faces)} material={len(faces)}')
        sc.op(dict(type='extrude', mode='join', dir='one', d1=2.0, d2=0, profiles=specs, spent=[b.id for b in letters], out=[]), 'Wypukły napis')
        sc.op(dict(type='transform', id=box.id, mode='move', v=[2.0, 1.0, 0.0]), 'Przesunięcie')
        for content in ('BOKS', 'I'):
            states = self.check_edit(sc, 2, txt(content))
            self.assertFalse(any(b.kind == 'sketch' and b.visible for b in states[-1][0]), content)
            self.assertEqual(len([b for b in states[-1][0] if b.kind == 'solid']), 1)


    def test_user_scenario_box_text_two_side_holes_then_change_text(self):
        """Prostokąt -> bryła, napis „Radek” wyciągnięty na górze, po otworze w dwóch bocznych ścianach, powrót i zmiana napisu na „Zosia”."""
        try:
            k.text_shape('XY', 'AB', 0, 0, 10)
        except Exception:
            self.skipTest('brak czcionki w środowisku')
        rect = sketch('Prostokąt', 'rect', [(0, 0), (80, 30)])
        sc = Scenario()
        sc.raw(lambda cur, r=rect: [*cur, r], 'Prostokąt')
        box_id = h.stable_id('box', 0)
        sc.op(dict(type='extrude', mode='new', dir='one', d1=10.0, d2=0, profiles=[{'k': 'sketch', 'id': rect.id}], spent=[rect.id], out=[box_id]), 'Bryła')
        top = k.Frame((0.0, 0.0, 10.0), (1.0, 0.0, 0.0), (0.0, 0.0, 1.0))
        group = h.new_text_group()
        txt = lambda content: dict(type='text', plane=h.plane_to_json(top), name='Tekst', out=h.text_ids(group, 12),
                                   params=dict(text=content, anchor=[5, 8], size=14.0, font='Arial', bold=False, italic=False, angle=0.0))
        sc.op(txt('Radek'), 'Tekst')
        letters = [b for b in sc.doc.bodies if b.kind == 'sketch']
        faces = h.material_regions(top, letters)
        srcs = [dict(kind='region', id=None, face=f, wire=f.outerWire(), plane=top, normal=(0, 0, 1), center=f.Center().toTuple()) for f in faces]
        specs = h.describe_profiles(srcs, sc.doc.bodies)
        info = [(x['k'], (x.get('anchor') or {}).get('id', '')[:14], h.text_group_of((x.get('anchor') or {}).get('id')) == group) for x in specs]
        grp = h.sketch_groups(sc.doc.bodies).get(h.plane_key(top))
        members = [b for b in (grp[1] if grp else []) if h.text_group_of(b.id) == group]
        self.assertEqual([x['k'] for x in specs], ['textgroup'], f'obszary={len(h._group_regions(top, letters))} materiał={len(faces)} litery={len(letters)} grupa={len(members)} specs={info}')
        sc.op(dict(type='extrude', mode='join', dir='one', d1=2.0, d2=0, profiles=specs, spent=[b.id for b in letters], out=[]), 'Napis')
        holes = []
        for frame, u in ((k.Frame((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, -1.0, 0.0)), 20.0), (k.Frame((0.0, 30.0, 0.0), (-1.0, 0.0, 0.0), (0.0, 1.0, 0.0)), 20.0)):
            circle = Body('Otwór', k.sketch_shape('circle', frame, [(u, 5.0), (u + 3.0, 5.0)]), 'sketch', frame).prepared()
            sc.raw(lambda cur, c=circle: [*cur, c], 'Szkic otworu')
            region = h._group_regions(frame, [circle])[0]
            src = dict(kind='region', id=None, face=region, wire=region.outerWire(), plane=frame, normal=tuple(k.frame_of(frame).normal), center=region.Center().toTuple())
            sc.op(dict(type='extrude', mode='cut', dir='one', d1=-6.0, d2=0, profiles=h.describe_profiles([src], sc.doc.bodies), spent=[circle.id], out=[]), 'Otwór')
            holes.append(circle)
        solid_before = [b for b in sc.doc.bodies if b.kind == 'solid'][0].shape.Volume()
        self.assertLess(solid_before, 80 * 30 * 10 + 400)       # otwory istnieją już przed zmianą
        text_index = 3
        for content in ('Zosia', 'Radek', 'I'):
            states = self.check_edit(sc, text_index, txt(content))
            final = states[-1][0]
            self.assertFalse(any(b.kind == 'sketch' and b.visible for b in final), content)       # ani litery, ani szkice otworów nie zostają
            solid = [b for b in final if b.kind == 'solid']
            self.assertEqual(len(solid), 1, content)
            self.assertGreater(solid[0].shape.Volume(), 0)
            # objętość z otworami jest mniejsza niż bryła + napis bez otworów (2 x pi*3^2*6 = ok. 339 mm3 ubytku)
            plain = [b for b in states[text_index + 1][0] if b.kind == 'solid'][0].shape.Volume()
            self.assertAlmostEqual(plain - solid[0].shape.Volume(), 2 * 3.14159 * 9 * 6, delta=20, msg=content)


    def test_mirror_and_union_follow_base_edit(self):
        box = Body('Baza', k.box(20, 10, 10)).prepared()
        sc = Scenario()
        sc.raw(lambda cur, b=box: [*cur, b], 'Baza')
        out = h.stable_id('mir', 0)
        sc.op(dict(type='mirror', id=box.id, normal=[1.0, 0.0, 0.0], origin=[30.0, 0.0, 0.0], keep=True, join=False, out=out), 'Lustro')
        sc.op(dict(type='bool', op='union', base=box.id, tools=[out], keep=False), 'Suma')
        self.assertEqual(len([b for b in sc.doc.bodies if b.kind == 'solid']), 1)
        wide = lambda cur, b=box: [replace(x, shape=k.box(26, 10, 10), mesh=None).prepared() if x.id == b.id else x for x in cur]
        self.check_edit(sc, 1, wide)

    def test_project_roundtrip_in_the_middle_of_work(self):
        sc = self.box_scene()
        sc.op(dict(type='transform', id=sc.box.id, mode='move', v=[3.0, 0.0, 0.0]), 'Przesunięcie')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 's.rccadx'
            sc.doc.save(path)
            loaded = Document.load(path)
            states = loaded.states()
            self.assertEqual(signature(states[-1][0]), signature(sc.doc.bodies))
            new_cut = dict(sc.cut, d1=9.0)
            patched = list(states)
            patched[3] = (states[3][0], dict(states[3][1], op=new_cut))
            first = h.run_recipe(states[2][0], new_cut)
            out, failed = h.recompute(patched, 3, first, ())
            self.assertEqual(failed, 0)
            self.assertEqual(signature(out[-1][0]), signature(sc.fresh(3, new_cut)))

    # ---------- dalsze scenariusze: szyk, Nożyczki, wiele profili, ściana bryły, narożniki ----------
    def test_rect_pattern_with_step_on_a_copy_then_more_copies(self):
        part = Body('Element', k.box(5, 5, 5)).prepared()
        sc = Scenario()
        sc.raw(lambda cur, b=part: [*cur, b], 'Element')
        pat = dict(type='pattern', id=part.id, kind='rect', params=dict(counts=[3, 1, 1], spacing=[10.0, 0.0, 0.0]), join=False, out=[h.stable_id('pat', 0), h.stable_id('pat', 1)])
        sc.op(pat, 'Szyk')
        copy = sc.doc.bodies[1]
        top_edge = [i for i, e in enumerate(copy.shape.Edges()) if abs(e.positionAt(.5).toTuple()[2] - 5) < 1e-6][0]
        sc.op(dict(type='mod', id=copy.id, kind='chamfer', size=1.0, verts=[], edges=h.edge_refs(copy.shape, [top_edge])), 'Faza na kopii')
        sc.op(dict(type='transform', id=part.id, mode='move', v=[0.0, 3.0, 0.0]), 'Przesunięcie oryginału')
        for params in (dict(counts=[5, 1, 1], spacing=[10.0, 0.0, 0.0]), dict(counts=[3, 1, 1], spacing=[14.0, 0.0, 0.0]), dict(counts=[3, 2, 1], spacing=[10.0, 12.0, 0.0])):
            states = self.check_edit(sc, 2, dict(pat, params=params))
            self.assertIn(copy.id, {b.id for b in states[-1][0]})       # kopia, na której wykonano fazę, zachowała tożsamość

    def test_joined_pattern_and_boolean_follow_part_resize(self):
        part = Body('Element', k.box(5, 5, 5)).prepared()
        plate = Body('Płyta', k.box(60, 20, 3)).prepared()
        plate = replace(plate, shape=k.transform(plate.shape, (-5, -5, -3), (0, 0, 0))).prepared()
        sc = Scenario()
        sc.raw(lambda cur, b=part, p=plate: [*cur, b, p], 'Elementy')
        sc.op(dict(type='pattern', id=part.id, kind='rect', params=dict(counts=[4, 1, 1], spacing=[10.0, 0.0, 0.0]), join=True, out=[]), 'Szyk połączony')
        sc.op(dict(type='bool', op='union', base=plate.id, tools=[part.id], keep=False), 'Suma z płytą')
        self.assertEqual(len([b for b in sc.doc.bodies if b.kind == 'solid']), 1)
        self.check_edit(sc, 1, lambda cur, b=part: [replace(x, shape=k.box(7, 7, 8), mesh=None).prepared() if x.id == b.id else x for x in cur])

    def test_trim_pieces_and_followup_delete_survive_sketch_edit(self):
        a = sketch('Linia A', 'line', [(0, 0), (20, 0)])
        b = sketch('Linia B', 'line', [(10, -10), (10, 10)])
        sc = Scenario()
        sc.raw(lambda cur, x=a, y=b: [*cur, x, y], 'Linie')
        trim = dict(type='trim', id=a.id, mid=[5.0, 0.0, 0.0], out=[])
        before = {x.id for x in sc.doc.bodies}
        made = h.run_trim(sc.doc.bodies, trim)
        trim['out'] = [x.id for x in made if x.id not in before]
        sc.op(trim, 'Nożyczki')
        survivor = trim['out'][-1]
        sc.op(dict(type='delete', ids=[b.id]), 'Usunięcie linii B')
        moved = lambda cur, y=b: [x if x.id != y.id else sketch(y.name, 'line', [(12, -10), (12, 10)], ident=y.id) for x in cur]
        states = self.check_edit(sc, 1, lambda cur: cur)       # bez zmian: wynik identyczny ze świeżym
        longer = lambda cur, x=a: [y if y.id != x.id else sketch(x.name, 'line', [(0, 0), (30, 0)], ident=x.id) for y in cur]
        self.check_edit(sc, 1, longer)
        self.assertTrue(survivor)

    def test_extrude_two_profiles_as_new_bodies_then_boolean(self):
        c1 = sketch('Okrąg 1', 'circle', [(0, 0), (5, 0)])
        c2 = sketch('Okrąg 2', 'circle', [(8, 0), (13, 0)])
        sc = Scenario()
        sc.raw(lambda cur, x=c1, y=c2: [*cur, x, y], 'Okręgi')
        out = [h.stable_id('ext', 0), h.stable_id('ext', 1)]
        sc.op(dict(type='extrude', mode='new', dir='one', d1=6.0, d2=0, profiles=[{'k': 'sketch', 'id': c1.id}, {'k': 'sketch', 'id': c2.id}], spent=[c1.id, c2.id], out=out), 'Wyciągnięcie')
        sc.op(dict(type='bool', op='union', base=out[0], tools=[out[1]], keep=False), 'Suma')
        self.assertEqual(len([x for x in sc.doc.bodies if x.kind == 'solid']), 1)
        bigger = lambda cur, y=c2: [x if x.id != y.id else sketch(y.name, 'circle', [(8, 0), (15, 0)], ident=y.id) for x in cur]
        self.check_edit(sc, 1, bigger)

    def test_extrude_from_solid_face_and_vertex_fillet_follow_base_resize(self):
        box = Body('Baza', k.box(20, 20, 10)).prepared()
        face, normal = k.face_at(box.shape, (0, 0, 1), (10, 10, 10))
        src = dict(kind='face', id=box.id, face=face, normal=tuple(normal), center=face.Center().toTuple(), hit=(10, 10, 10))
        sc = Scenario()
        sc.raw(lambda cur, b=box: [*cur, b], 'Baza')
        sc.op(dict(type='extrude', mode='join', dir='one', d1=4.0, d2=0, profiles=h.describe_profiles([src], [box]), spent=[], out=[]), 'Nadbudowa z ściany')
        solid = sc.doc.bodies[0]
        corner = max((v for v in solid.shape.Vertices()), key=lambda v: sum(v.toTuple()))
        point = [float(c) for c in corner.toTuple()]
        sc.op(dict(type='mod', id=box.id, kind='chamfer', size=1.0, verts=[point], vrefs=h.vertex_refs(solid.shape, [point]), edges=[]), 'Faza narożnika')
        self.check_edit(sc, 1, lambda cur, b=box: [replace(x, shape=k.box(30, 25, 14), mesh=None).prepared() if x.id == b.id else x for x in cur])


    def test_ids_of_pattern_copies_are_stable_when_count_changes(self):
        ids = h.pad_ids([], 3, 'seed')
        self.assertEqual(ids, h.pad_ids([], 3, 'seed'))
        self.assertEqual(h.pad_ids(ids[:2], 4, ids[0])[:2], ids[:2])
        self.assertEqual(len(set(ids)), 3)


if __name__ == '__main__':
    unittest.main()
