"""Executed by the packaged EXE as well as Python: validates shipped DLLs and I/O."""
from __future__ import annotations
import json
from pathlib import Path
import platform
import tempfile
from . import __version__, kernel as k
from .document import Body, Document


def run(report_path=None):
    checks = []
    shape = k.box(30, 30, 30)
    rounded = k.blend(shape, range(len(shape.Edges())), 3)
    assert rounded.isValid() and 0 < rounded.Volume() < shape.Volume()
    assert len(k.display_mesh(rounded).edges) == 0
    checks.append('OpenCascade: 12 edge fillets with smooth corner patches')
    drilled = k.hole(shape, 4, 15, 15)
    assert drilled.Volume() < shape.Volume() and drilled.isValid()
    checks.append('through hole')
    cut = k.boolean('subtract', shape, [k.box(10, 10, 40)])
    assert cut.isValid() and abs(cut.Volume()-24000) < 1e-5
    checks.append('Boolean subtraction')
    wire = k.sketch('rectangle','XY',20,10)
    assert abs(k.extrude(wire,'XY',10).Volume()-2000) < 1e-5
    checks.append('native sketch extrusion')
    drag = k.sketch_from_drag('rectangle','XZ',0,0,20,10)
    assert abs(k.extrude(k.sketch(**drag),'XZ',5).Volume()-1000) < 1e-5
    checks.append('mouse sketch geometry')
    plain = k.box(40,30,20)
    vertical = [i for i,e in enumerate(plain.Edges()) if abs(e.startPoint().z-e.endPoint().z) > 10]
    outline = k.blend(plain, vertical, 5)
    top = {i for i,e in enumerate(outline.Edges()) if abs(e.startPoint().z-20) < 1e-6 and abs(e.endPoint().z-20) < 1e-6}
    assert len(top) == 8 and k.edge_chain(outline, min(top)) == top
    checks.append('tangent edge chain')
    doc=Document();body=Body('Zaokrąglona kostka',rounded).prepared();doc.commit([body])
    doc.undo();assert not doc.bodies;doc.redo();assert len(doc.bodies)==1
    with tempfile.TemporaryDirectory(prefix='rccad-check-') as directory:
        root=Path(directory)
        doc.save(root/'test.rccadx')
        opened=Document.load(root/'test.rccadx')
        assert abs(opened.bodies[0].shape.Volume()-rounded.Volume()) < 1e-5
        k.export_shapes([rounded],root/'test.step')
        imported=k.import_shapes(root/'test.step')
        assert abs(imported[0][0].Volume()-rounded.Volume()) < .001
        k.export_shapes([rounded],root/'test.stl')
        assert (root/'test.stl').stat().st_size>100
    checks.append('project, undo/redo, STEP round trip and STL export')
    # Construct actual native widgets, even on CI without a graphics-capable desktop.
    from PySide6.QtWidgets import QApplication
    from .window import MainWindow
    app=QApplication.instance() or QApplication([])
    window=MainWindow();window.document=doc;window.selected=[body.id];window.refresh()
    assert window.tree.topLevelItemCount()==1 and 'Objętość' in window.properties.text()
    window.view.resize(800,600);window.view.fit_all()
    projected,_,_=window.view.project_points(body.mesh.vertices[:3])
    assert window.view._ray(float(projected[0][0]),float(projected[0][1])) is not None
    checks.append('Qt coordinate projection and picking ray')
    window.document._saved_revision=window.document._revision
    window.close();app.processEvents()
    checks.append('Qt native window, object tree and properties')
    result=dict(app='RCCAD Desktop',version=__version__,platform=platform.platform(),passed=True,checks=checks)
    if report_path:
        Path(report_path).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return result
