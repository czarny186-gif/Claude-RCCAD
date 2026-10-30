"""Pomiar wydajności historii (druk do logu CI: linie „PERF”) oraz szerokie limity, które łapią regresje, nie zakłócając pracy."""
import os, sys, time, tempfile
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen' if not os.environ.get('DISPLAY') and os.name != 'nt' else '')
import unittest
from pathlib import Path
from rccad import kernel as k, history as h
from rccad.document import Body, Document

STEPS = 240


def report(name, seconds, extra=''):
    print(f'PERF {name}: {seconds * 1000:.1f} ms {extra}', file=sys.stderr, flush=True)


class Timer:
    def __enter__(self):
        self.t = time.perf_counter()
        return self

    def __exit__(self, *exc):
        self.seconds = time.perf_counter() - self.t


class HistoryPerf(unittest.TestCase):
    def build(self):
        """30 brył i 240 kroków przesunięcia po 8 na bryłę (zależne łańcuchy) - realistyczny projekt ze średnią historią."""
        solids = [Body(f'B{i}', k.transform(k.box(10, 10, 10), (i * 15, 0, 0), (0, 0, 0))).prepared() for i in range(30)]
        d = Document()
        d.commit(solids, 'Start')
        recipes = []
        with Timer() as t:
            for n in range(STEPS):
                target = solids[n % 30]
                recipe = dict(type='transform', id=target.id, mode='move', v=[1.0, 0.0, 0.0])
                d.pending_op, d.pending_icon, d.pending_label = recipe, 'move', 'Przekształcenie'
                d.commit(h.run_recipe(d.bodies, recipe))
                recipes.append(recipe)
        report('dodanie jednego kroku (średnio)', t.seconds / STEPS, f'({STEPS} kroków łącznie {t.seconds:.2f} s)')
        return d, recipes

    def test_history_timings(self):
        d, recipes = self.build()
        n = len(d.states())
        with Timer() as t:
            for _ in range(20):
                d.states(); d.infos(); d.timeline()
        report('states+infos+timeline x1', t.seconds / 20, f'(kroków: {n})')
        self.assertLess(t.seconds / 20, .05)
        with Timer() as t:
            for i in range(0, n, 12):
                d.goto(i)
            d.goto(n - 1)
        report('skok w historii (średnio)', t.seconds / (n // 12 + 1))
        self.assertLess(t.seconds / (n // 12 + 1), .25)
        states = d.states()
        # edycja kroku 1 (zmienia bryłę 0) -> przeliczenie niezależnych kroków szybką ścieżką, zależnych na nowo
        edited = dict(recipes[0], v=[3.0, 0.0, 0.0])
        info = dict(states[2][1], op=edited)
        patched = list(states)
        patched[2] = (states[2][0], info)
        first = h.run_recipe(states[1][0], edited)
        with Timer() as t:
            out, failed = h.recompute(patched, 2, first, ())
        report('przeliczenie po edycji pierwszego kroku', t.seconds, f'(nieprzeliczone: {failed})')
        self.assertEqual(failed, 0)
        with Timer() as t:
            out, failed = h.recompute_all(states, h.Context((), {}))
        report('pełne przeliczenie całej historii', t.seconds, f'(nieprzeliczone: {failed})')
        self.assertEqual(failed, 0)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'p.rccadx'
            with Timer() as t:
                d.save(path)
            report('zapis projektu (pierwszy)', t.seconds, f'({path.stat().st_size // 1024} KB)')
            with Timer() as t:
                d.save(path)
            report('zapis projektu (drugi, z pamięcią podręczną BREP)', t.seconds)
            self.assertLess(t.seconds, 1.5)
            import cadquery as cq
            from zipfile import ZipFile
            from concurrent.futures import ThreadPoolExecutor
            with ZipFile(path) as archive, tempfile.TemporaryDirectory() as work:
                names = [n for n in archive.namelist() if n.endswith('.brep')]
                files = []
                for n in names:
                    f = Path(work) / Path(n).name
                    f.write_bytes(archive.read(n)); files.append(f)
                with Timer() as t:
                    shapes = [cq.importers.importBrep(str(f)).val() for f in files]
                report('wczytanie: sam import BREP po kolei', t.seconds, f'({len(files)} plików)')
                with Timer() as t:
                    for sh in shapes:
                        k.valid(sh, True)
                report('wczytanie: sama walidacja po kolei', t.seconds)
                with Timer() as t:
                    with ThreadPoolExecutor(4) as pool:
                        list(pool.map(lambda f: cq.importers.importBrep(str(f)).val(), files))
                report('wczytanie: import w 4 wątkach', t.seconds)
            with Timer() as t:
                o = Document.load(path)
            report('wczytanie projektu', t.seconds)
            with Timer() as t:
                o.goto(3); o.goto(len(o.states()) - 1)
            report('pierwszy skok po wczytaniu (siatki leniwie)', t.seconds)
            self.assertLess(t.seconds, 5)


class MeshPerf(unittest.TestCase):
    def test_display_mesh_profile(self):
        import cProfile, pstats, io
        shapes = [k.transform(k.box(10 + i, 10, 10), (i * 15, 0, 0), (0, 0, 0)) for i in range(30)]
        profile = cProfile.Profile()
        with Timer() as t:
            profile.enable()
            for sh in shapes:
                k.display_mesh(sh)
            profile.disable()
        report('siatka wyswietlania jednej bryly (box)', t.seconds / 30)
        out = io.StringIO()
        pstats.Stats(profile, stream=out).sort_stats('tottime').print_stats(10)
        print('PERFPROF\n' + out.getvalue(), file=sys.stderr, flush=True)


class StudioPerf(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_history_bar_and_refresh(self):
        from rccad.studio import StudioWindow
        d, recipes = HistoryPerf().build()
        w = StudioWindow()
        w.resize(1400, 850)
        w.show()
        self.app.processEvents()
        w.document = d
        with Timer() as t:
            w.refresh(True); self.app.processEvents()
        report('okno: odświeżenie z paskiem ukrytym', t.seconds)
        with Timer() as t:
            w.hist_button.setChecked(True); self.app.processEvents()
        report('okno: pierwsze zbudowanie paska historii', t.seconds, f'(symboli: {len(w._hist_widgets)})')
        self.assertLess(t.seconds, 5)
        n = len(d.states())
        with Timer() as t:
            for i in range(0, n, 20):
                w.history_goto(i); self.app.processEvents()
            w.history_goto(n - 1); self.app.processEvents()
        report('okno: skok w historii z odświeżeniem (średnio)', t.seconds / (n // 20 + 1))
        self.assertLess(t.seconds / (n // 20 + 1), .5)
        with Timer() as t:
            for _ in range(10):
                w._hist_sig = (w._hist_sig[0], w._hist_sig[1], w._hist_sig[2]); w.refresh(); self.app.processEvents()
        report('okno: samo odświeżenie bez zmian (średnio)', t.seconds / 10)
        recipe = dict(type='transform', id=d.bodies[0].id, mode='move', v=[1.0, 0.0, 0.0])
        d.pending_op, d.pending_icon, d.pending_label = recipe, 'move', 'Przekształcenie'
        d.commit(h.run_recipe(d.bodies, recipe))
        with Timer() as t:
            w.refresh(); self.app.processEvents()
        report('okno: odświeżenie po dodaniu kroku', t.seconds)
        self.assertLess(t.seconds, .5)
        w.document._saved_revision = w.document._revision
        w.close()


if __name__ == '__main__':
    unittest.main()
