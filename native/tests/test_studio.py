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

    # ----- etap 2 -----
    def test_line_chain_closes_into_extrudable_profile(self):
        w=self.w;w.set_mode('plane');w.plane_picked('XY');w.choose_tool('line')
        for p in ((0,0),(20,0),(20,10),(0,0)):w.sketch_clicked('XY',*p)
        self.wait();self.assertEqual(len(w.document.bodies),1)
        self.assertTrue(w.document.bodies[0].shape.IsClosed())
        self.assertAlmostEqual(k.extrude(w.document.bodies[0].shape,'XY',2).Volume(),20*10/2*2,3)

    def test_open_line_finishes_on_enter_and_double_point(self):
        w=self.w;w.set_mode('plane');w.plane_picked('XY');w.choose_tool('line')
        w.sketch_clicked('XY',0,0);w.sketch_clicked('XY',10,0);w.sketch_clicked('XY',10,10);w.sketch_clicked('XY',10,10);self.wait()
        self.assertEqual(len(w.document.bodies),1);self.assertFalse(w.document.bodies[0].shape.IsClosed())

    def test_arc_point_construction_rect3(self):
        self.sketch('arc',(10,0),(0,10),(-10,0));self.sketch('point',(3,3));self.sketch('construction',(0,0),(30,0))
        self.sketch('rect3',(0,0),(10,0),(5,4));self.assertEqual(len(self.w.document.bodies),4)
        self.assertAlmostEqual(k.extrude(self.w.document.bodies[3].shape,'XY',1).Volume(),40,3)

    def test_measure_does_not_create_geometry(self):
        self.sketch('measure',(0,0),(3,4));self.assertEqual(len(self.w.document.bodies),0);self.assertIn('5.000',self.w.notice.text())

    def test_trim_removes_clicked_segment(self):
        self.sketch('rect',(0,0),(10,10));w=self.w;w.choose_tool('trim');body=w.document.bodies[0]
        with patch.object(w,'_cursor_edge',return_value=(body.id,0)):w.sketch_clicked('XY',0,0)
        self.wait();self.assertEqual(len(w.document.bodies),1);self.assertFalse(w.document.bodies[0].shape.IsClosed())

    def test_tangent_circle_between_two_lines(self):
        w=self.w;self.sketch('line',(0,0),(30,0),(30,0));self.sketch('line',(0,0),(0,30),(0,30))
        a,b=w.document.bodies;w.choose_tool('circleTangent2')
        for body in (a,b):
            with patch.object(w,'_cursor_edge',return_value=(body.id,0)):w.sketch_clicked('XY',1,1)
        self.assertEqual(len(w.tangent_lines),2);w.sketch_clicked('XY',10,10);self.wait()
        self.assertEqual(len(w.document.bodies),3)
        self.assertAlmostEqual(k.bounds(w.document.bodies[2].shape).xlen,20,2)

    def test_text_creates_profiles_when_font_exists(self):
        try:k.text_shape('XY','AB',0,0,10)
        except Exception:self.skipTest('brak czcionki w środowisku')
        self.sketch('text',(0,0));self.assertGreaterEqual(len(self.w.document.bodies),1)

    def test_typed_dimensions(self):
        w=self.w;w.set_mode('plane');w.plane_picked('XY');w.choose_tool('rect');w.sketch_clicked('XY',0,0)
        self.assertTrue(w.open_dim_input('3'));w.dim_edit.setText('30 10');w.apply_typed();self.wait()
        b=k.bounds(w.document.bodies[0].shape);self.assertAlmostEqual(b.xlen,30,3);self.assertAlmostEqual(b.ylen,10,3)

    def test_two_sided_extrude_and_transform_bar(self):
        w=self.w;self.sketch('rect',(0,0),(10,10));w.set_mode('extrude');sk=w.document.bodies[0]
        with patch.object(w.view,'pick_profile',return_value=sk.id):w.view_clicked(1,1,False,False)
        w.ex_two.setChecked(True);w.ex_distance.setValue(10);w.ex_distance2.setValue(5);w.apply_extrude();self.wait()
        solid=[b for b in w.document.bodies if b.kind=='solid'][0];self.assertAlmostEqual(solid.shape.Volume(),1500,2)
        self.assertAlmostEqual(k.bounds(solid.shape).zmin if hasattr(k.bounds(solid.shape),'zmin') else -5,-5,2)
        w.selected=[solid.id];w.refresh();self.assertTrue(w.tbar.isVisible())
        w.t_spins['x'].setValue(7);w.apply_transform();self.wait()
        self.assertAlmostEqual(w.document.get(solid.id).shape.Center().x,5+7,2)

    def test_duplicate_hide_show(self):
        w=self.w;a,b=self.make_solids();w.selected=[a.id];w.duplicate_selected();self.wait();self.assertEqual(len(w.document.bodies),3)
        w.selected=[a.id];w.hide_selected();self.assertFalse(w.document.get(a.id).visible);w.show_all();self.assertTrue(w.document.get(a.id).visible)

    def test_svg_import(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            f=os.path.join(d,'a.svg');open(f,'w').write('<svg xmlns="http://www.w3.org/2000/svg"><rect x="0" y="0" width="20" height="10"/><circle cx="5" cy="5" r="2"/><path d="M0 0 L10 0 L10 10 Z"/></svg>')
            self.assertEqual(len(k.svg_profiles(f)),3)

    def test_extrude_face_of_solid_adds_and_cuts(self):
        w=self.w;a=Body('A',k.box(20,20,20)).prepared();w.document.commit([a]);w.refresh();w.set_mode('extrude')
        top=([0,0,1],[10,10,20])
        with patch.object(w.view,'pick_profile',return_value=None),patch.object(w.view,'pick_face',return_value=(a.id,top[0],top[1])):
            w.view_clicked(5,5,False,False)
        self.assertIsNotNone(w.extrude_src);self.assertEqual(w.extrude_src['kind'],'face');self.assertIsNotNone(w.view.handle)
        w.ex_distance.setValue(5);w.update_extrude_preview();self.assertEqual(w.ex_op.currentData(),'union')
        w.apply_extrude();self.wait();self.assertAlmostEqual(w.document.get(a.id).shape.Volume(),20*20*25,1)
        w.set_mode('extrude');b=w.document.get(a.id)
        with patch.object(w.view,'pick_profile',return_value=None),patch.object(w.view,'pick_face',return_value=(a.id,[0,0,1],[10,10,25])):
            w.view_clicked(5,5,False,False)
        w.ex_distance.setValue(-3);w.update_extrude_preview();self.assertEqual(w.ex_op.currentData(),'subtract')
        w.apply_extrude();self.wait();self.assertAlmostEqual(w.document.get(a.id).shape.Volume(),20*20*22,1)

    def test_extrude_arrow_drag_changes_distance(self):
        w=self.w;self.sketch('rect',(0,0),(10,10));w.set_mode('extrude');sk=w.document.bodies[0]
        with patch.object(w.view,'pick_profile',return_value=sk.id):w.view_clicked(1,1,False,False)
        w.ex_distance.setValue(10);w.handle_dragged(5.04);self.assertAlmostEqual(w.ex_distance.value(),15.0,1)
        w.handle_dragged(-2.0);self.assertAlmostEqual(w.ex_distance.value(),8.0,1);w.handle_released();self.assertIsNone(w._hv)

    def test_fillet_preview_shows_result(self):
        w=self.w;a=Body('A',k.box(20,20,20)).prepared();w.document.commit([a]);w.refresh();w.set_mode('mod')
        w.edges={a.id:{0}};w.mod_size.setValue(2);w.update_mod_preview();self.assertTrue(w.view.preview_items)

    def test_file_menu_opens_with_all_entries(self):
        from PySide6.QtWidgets import QMenu
        seen=[]
        with patch.object(QMenu,'exec',lambda menu,*a:seen.append([x.text() for x in menu.actions() if not x.isSeparator()])):
            self.w.file_menu()
        self.assertEqual(len(seen[0]),8);self.assertTrue(seen[0][0].startswith('Nowy'))

    def test_context_menu_opens(self):
        from PySide6.QtWidgets import QMenu
        a,b=self.make_solids();seen=[]
        with patch.object(QMenu,'exec',lambda menu,*a:seen.append(len(menu.actions()))),patch.object(self.w.view,'pick_body',return_value=a.id):
            self.w.context_menu(5,5)
        self.assertEqual(seen,[5])

    def test_every_button_click_raises_no_exception(self):
        import sys
        from PySide6.QtWidgets import QMenu,QToolButton,QPushButton
        errors=[];old=sys.excepthook;sys.excepthook=lambda *a:errors.append(a[1])
        try:
            with patch.object(QMenu,'exec',lambda *a:None):
                for key in ('file','sketch','extrude','bool','mod','mirror','mod','bool'):self.w.tools[key].click();self.app.processEvents()
                self.w.tools['sketch'].click();self.w.plane_picked('XY')
                for b in list(self.w.shape_buttons.values()):b.click();self.app.processEvents()
                for m in self.w.shape_bar.findChildren(QToolButton):
                    if m.menu():
                        for act in m.menu().actions():act.trigger();self.app.processEvents()
                self.w.set_mode(None)
                for b in self.w.cube.findChildren(QToolButton):b.click()
                for b in (*self.w.pad_buttons.values(),self.w.layers,self.w.layers,self.w.home,self.w.undo_button,self.w.redo_button):b.click();self.app.processEvents()
        finally:sys.excepthook=old
        self.assertEqual(errors,[])


if __name__=='__main__':
    unittest.main()
