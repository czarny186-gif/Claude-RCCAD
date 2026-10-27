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
    w.tools['extrude'].click(); w.view_clicked(350, 350, False, False); shot('04_extrude')
run('04', s4)
def s5():
    w.ex_distance.setValue(20); w.apply_extrude(); settle(1500); w.view.set_view('iso'); w.view.fit_all(); shot('05_solid')
run('05', s5)
def s6():
    w.tools['mod'].click(); shot('06_mod')
run('06', s6)
sys.exit(0)
