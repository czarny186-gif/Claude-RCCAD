"""Scenariusze z życia: operacje -> cofnięcie się -> zmiana kroku -> powrót na koniec -> dalsza praca.
Wzorzec poprawności: wynik przeliczenia historii musi być taki sam jak świeże wykonanie tych samych kroków od początku."""
import unittest, tempfile
from dataclasses import replace
from pathlib import Path
from rccad import kernel as k, history as h
from rccad.document import Body, Document

PTS = lambda *p: [list(x) for x in p]


def sketch(name, tool, pts, plane='XY', ident=None):
    body = Body(name, k.sketch_shape(tool, plane, [tuple(p) for p in pts], 5), 'sketch', plane, meta=dict(tool=tool, points=PTS(*pts), sides=5)).prepared()
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
        faces = h._group_regions('XY', letters)
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

    def test_ids_of_pattern_copies_are_stable_when_count_changes(self):
        ids = h.pad_ids([], 3, 'seed')
        self.assertEqual(ids, h.pad_ids([], 3, 'seed'))
        self.assertEqual(h.pad_ids(ids[:2], 4, ids[0])[:2], ids[:2])
        self.assertEqual(len(set(ids)), 3)


if __name__ == '__main__':
    unittest.main()
