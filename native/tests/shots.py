"""Zrzuty ekranu okna Studio (uruchamiane w CI, wynik trafia na gałąź ci-shots) — do porównania z wersją HTML."""
import os, sys, time, traceback
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtGui import QSurfaceFormat
from PySide6.QtWidgets import QApplication
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
fmt = QSurfaceFormat(); fmt.setDepthBufferSize(24); fmt.setSamples(4); QSurfaceFormat.setDefaultFormat(fmt)
app = QApplication([])
from rccad import kernel as k
from rccad.document import Body
from rccad.studio import StudioWindow
out = Path(sys.argv[1] if len(sys.argv) > 1 else 'shots'); out.mkdir(exist_ok=True)
w = StudioWindow(); w.resize(1400, 850); w.show()

def settle(ms=500):
    end = time.monotonic() + ms / 1000
    while time.monotonic() < end:
        app.processEvents(); time.sleep(.01)

def shot(name):
    settle(400)
    try:
        w.view.update(); app.processEvents()
        w.grab().save(str(out / f'{name}.png'))
        w.view.grabFramebuffer().save(str(out / f'{name}_gl.png'))
    except Exception:
        (out / f'{name}.err').write_text(traceback.format_exc())

def run(label, fn):
    try:
        fn()
    except Exception:
        (out / f'{label}.err').write_text(traceback.format_exc())

shot('01_idle')
run('02', lambda: (w.tools['sketch'].click(), shot('02_plane_pick')))
def s3():
    w.plane_picked('XY'); w.choose_tool('rect'); w.sketch_clicked('XY', 0, 0); w.sketch_moved('XY', 34, 17); shot('03_rect_live')
run('03', s3)
def s4():
    w.sketch_clicked('XY', 34, 17); settle(800)
    w.tools['extrude'].click()
    from unittest.mock import patch
    with patch.object(w.view, 'pick_profile', return_value=w.document.bodies[0].id):
        w.view_clicked(350, 350, False, False)
    w.ex_value.setValue(20); settle(500); shot('04_extrude')
run('04', s4)
def s5():
    w.apply_extrude(); settle(1500); w.view.set_view('iso'); w.view.fit_all(); shot('05_solid')
run('05', s5)
def s6():
    from unittest.mock import patch
    sid = w.document.bodies[-1].id
    w.tools['mod'].click()
    with patch.object(w.view, 'nearest_edge', return_value=(sid, 0)):
        w.view_clicked(5, 5, False, False)
    w.mod_size.setValue(4); settle(800); shot('06_mod')
run('06', s6)
def s7():
    w.set_mode(None); w.tools['sketch'].click(); settle(300); shot('07_plane_pick_with_solid')
run('07', s7)
sys.exit(0)
