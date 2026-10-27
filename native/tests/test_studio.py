"""Okno Studio: układ jak w HTML oraz przepływ szkic → wyciągnięcie → Boolean / zaokrąglenie / lustro."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen' if not os.environ.get('DISPLAY') and os.name!='nt' else '')
import time
import unittest
from unittest.mock import patch
from PySide6.QtCore import QEvent,Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication,QMessageBox
from rccad import kernel as k
from rccad.document import Body
from rccad.studio import StudioWindow


class StudioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        self.w=StudioWindow();self.w.resize(1400,850);self.w.show();self.app.processEvents()
        self.patches=[patch.object(QMessageBox,'warning',return_value=QMessageBox.Ok),patch.object(QMessageBox,'information',return_value=QMessageBox.Ok)]
        for p in self.patches:p.start()

    def tearDown(self):
        self.wait();self.w.document._saved_revision=self.w.document._revision;self.w.close();self.app.processEvents()
        for p in self.patches:p.stop()

    def wait(self):
        end=time.monotonic()+20
        while self.w.busy and time.monotonic()<end:
            self.app.processEvents();time.sleep(.005)
        self.app.processEvents()
        self.assertFalse(self.w.busy)

    def sketch(self,tool,*points,plane='XY'):
        if self.w.mode not in('plane','sketch'):self.w.set_mode('plane')
        if self.w.mode=='plane':self.w.plane_picked(plane)
        self.w.choose_tool(tool)
        for p in points:self.w.sketch_clicked(plane,*p)
        self.wait()

    def test_layout_matches_html_measurements(self):
        w=self.w;W=w.view.width();H=w.view.height()
        for i,key in enumerate(('file','sketch','extrude','bool','mod','mirror')):
            b=w.tools[key];self.assertEqual((b.x(),b.y(),b.width(),b.height()),(18+60*i,18,52,52),key)
        self.assertEqual(w.cube.size().width(),138);self.assertEqual(w.cube.x(),W-160)
        self.assertEqual(w.undo_button.x(),W-350);self.assertEqual(w.redo_button.x(),W-302);self.assertEqual(w.layers.x(),W-254)
        self.assertFalse(w.shape_bar.isVisible())

    def test_plane_pick_then_click_click_rectangle(self):
        w=self.w
        w.set_mode('plane');self.assertTrue(w.view.plane_pick)
        w.plane_picked('XZ');self.assertTrue(w.shape_bar.isVisible());self.assertEqual(w.mode,'sketch')
        w.choose_tool('rect');w.sketch_clicked('XZ',0,0);self.assertEqual(len(w.document.bodies),0)
        w.sketch_moved('XZ',20,10);self.assertTrue(w.view.preview_items);self.assertIn('20.00',w.dim.text())
        w.sketch_clicked('XZ',20,10);self.wait()
        self.assertEqual(len(w.document.bodies),1);body=w.document.bodies[0]
        self.assertEqual((body.kind,body.plane),('sketch','XZ'))
        b=k.bounds(body.shape);self.assertAlmostEqual(b.xlen,20,3);self.assertAlmostEqual(b.zlen,10,3)

    def test_all_supported_shapes_create_sketches(self):
        cases=[('centerRect',[(0,0),(10,5)]),('circle',[(0,0),(8,0)]),('circle2',[(0,0),(10,0)]),('circle3',[(10,0),(0,10),(-10,0)]),
               ('ellipse',[(0,0),(12,6)]),('slot',[(0,0),(20,0),(0,4)]),('polygon',[(0,0),(10,0)])]
        for tool,points in cases:
            before=len(self.w.document.bodies);self.sketch(tool,*points)
            self.assertEqual(len(self.w.document.bodies),before+1,tool)

    def test_extrude_by_clicking_profile_with_preview(self):
        w=self.w;self.sketch('rect',(0,0),(20,10))
        w.set_mode('extrude');w.ex_distance.setValue(15)
        sk=w.document.bodies[0]
        with patch.object(w.view,'pick_profile',return_value=sk.id):w.view_clicked(10,10,False,False)
        self.assertTrue(w.ex_bar.isVisible());self.assertTrue(w.view.preview_items)
        w.apply_extrude();self.wait()
        solids=[b for b in w.document.bodies if b.kind=='solid'];self.assertEqual(len(solids),1)
        self.assertAlmostEqual(solids[0].shape.Volume(),20*10*15,2);self.assertIsNone(w.mode)

    def make_solids(self):
        w=self.w
        a=Body('A',k.box(20,20,20)).prepared();b=Body('B',k.box(10,10,40)).prepared()
        w.document.commit([a,b]);w.refresh()
        return a,b

    def test_boolean_base_and_tool_selection(self):
        w=self.w;a,b=self.make_solids();w.set_mode('bool')
        for body in (a,b):
            with patch.object(w.view,'pick_body',return_value=body.id):w.view_clicked(5,5,False,False)
        self.assertEqual(w.bool_ids,[a.id,b.id]);self.assertIn(a.id,w.view.tints)
        w.bool_op.setCurrentIndex(0);w.apply_bool();self.wait()
        self.assertEqual(len([x for x in w.document.bodies if x.kind=='solid']),1)
        self.assertGreater(w.document.bodies[0].shape.Volume(),8000)

    def test_fillet_by_clicked_edge(self):
        w=self.w;a=Body('A',k.box(20,20,20)).prepared();w.document.commit([a]);w.refresh();w.set_mode('mod')
        with patch.object(w.view,'nearest_edge',return_value=(a.id,0)):w.view_clicked(5,5,False,False)
        self.assertEqual(w.edges,{a.id:{0}})
        w.mod_size.setValue(2);w.apply_mod();self.wait()
        self.assertLess(w.document.bodies[0].shape.Volume(),8000)

    def test_mirror_keeps_original(self):
        w=self.w;a=Body('A',k.hole(k.box(20,20,20),3,5,5)).prepared();w.document.commit([a]);w.refresh();w.set_mode('mirror')
        with patch.object(w.view,'pick_body',return_value=a.id):w.view_clicked(5,5,False,False)
        w.mir_plane.setCurrentIndex(2);w.apply_mirror();self.wait()
        self.assertEqual(len(w.document.bodies),2)

    def test_undo_redo_and_escape(self):
        w=self.w;self.sketch('circle',(0,0),(5,0));self.assertTrue(w.undo_button.isEnabled())
        w.undo();self.assertEqual(len(w.document.bodies),0);w.redo();self.assertEqual(len(w.document.bodies),1)
        w.points=[(0,0)];w.keyPressEvent(QKeyEvent(QEvent.KeyPress,Qt.Key_Escape,Qt.NoModifier));self.assertEqual(w.points,[])


if __name__=='__main__':
    unittest.main()
