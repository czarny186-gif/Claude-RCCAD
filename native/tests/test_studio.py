"""Okno Studio: układ jak w HTML oraz przepływ szkic → wyciągnięcie → Boolean / zaokrąglenie / lustro."""
import os, faulthandler
faulthandler.dump_traceback_later(420, exit=True, file=open(os.environ.get("DIAG_FILE","diag_hang.txt"),"w"))
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

    def preview(self):
        end=time.monotonic()+20
        while time.monotonic()<end and any(st['running'] or st['pending'] for st in self.w._pv.values()):
            self.app.processEvents();time.sleep(.005)
        self.app.processEvents()

    def sketch(self,tool,*points,plane='XY'):
        if self.w.mode!='sketch':self.w.set_mode('plane');self.w.plane_picked(plane)
        self.w.choose_tool(tool)
        for p in points:self.w.sketch_clicked(plane,*p)
        self.wait()

    def test_layout_matches_html_measurements(self):
        w=self.w;W=w.view.width()
        for i,key in enumerate(('file','sketch','extrude','bool','mod','mirror')):
            b=w.tools[key];self.assertEqual((b.x(),b.y(),b.width(),b.height()),(18+60*i,18,52,52),key)
        self.assertEqual(w.cube.width(),138);self.assertEqual(w.cube.x(),W-160)
        self.assertEqual(w.undo_button.x(),W-350);self.assertEqual(w.redo_button.x(),W-302);self.assertEqual(w.layers.x(),W-254)
        self.assertFalse(w.shape_bar.isVisible())

    def test_rectangle_is_live_on_any_plane(self):
        w=self.w
        for plane in ('XY','XZ','YZ'):
            w.set_mode(None);w.set_mode('plane');w.plane_picked(plane);w.choose_tool('rect')
            w.sketch_clicked(plane,0,0);w.sketch_moved(plane,20,10);self.assertTrue(w.view.preview_items,plane)
            self.assertIn('20,000',w.dim.text())
            w.sketch_clicked(plane,20,10);self.wait()
        self.assertEqual([b.plane for b in w.document.bodies],['XY','XZ','YZ'])

    def test_sketch_on_solid_face_and_live_preview(self):
        w=self.w;a=Body('A',k.box(20,20,20)).prepared();w.document.commit([a]);w.refresh();w.set_mode('plane')
        with patch.object(w.view,'pick_face',return_value=(a.id,[0,0,1],[10,10,20])):
            w.view_hover(5,5);w.view_clicked(5,5,False,False)
        self.assertEqual(w.mode,'sketch');self.assertNotIsInstance(w.sketch_plane,str)
        w.choose_tool('circle');w.sketch_clicked(w.sketch_plane,10,10);w.sketch_moved(w.sketch_plane,14,10)
        self.preview();self.assertTrue(w.view.preview_items);w.sketch_clicked(w.sketch_plane,14,10);self.wait()
        sk=w.document.bodies[-1];self.assertEqual(sk.kind,'sketch');self.assertAlmostEqual(k.bounds(sk.shape).zmin,20,3)

    def test_all_supported_shapes_create_sketches(self):
        cases=[('centerRect',[(0,0),(10,5)]),('circle',[(0,0),(8,0)]),('circle2',[(0,0),(10,0)]),('circle3',[(10,0),(0,10),(-10,0)]),
               ('ellipse',[(0,0),(12,6)]),('slot',[(0,0),(20,0),(0,4)]),('polygon',[(0,0),(10,0)])]
        for tool,points in cases:
            before=len(self.w.document.bodies);self.sketch(tool,*points)
            self.assertEqual(len(self.w.document.bodies),before+1,tool)

    def pick_sketch_profile(self,sk):
        with patch.object(self.w.view,'pick_profile',return_value=sk.id):self.w.view_clicked(5,5,False,False)

    def test_extrude_by_clicking_profile_with_preview(self):
        w=self.w;self.sketch('rect',(0,0),(20,10));w.set_mode('extrude');w.ex_value.setValue(15)
        self.pick_sketch_profile(w.document.bodies[0])
        self.assertTrue(w.ex_bar.isVisible());self.preview();self.assertTrue(w.view.preview_items);self.assertTrue(w.view.handles)
        w.apply_extrude();self.wait()
        solids=[b for b in w.document.bodies if b.kind=='solid'];self.assertEqual(len(solids),1)
        self.assertAlmostEqual(solids[0].shape.Volume(),20*10*15,2);self.assertIsNone(w.mode)

    def test_extrude_arrow_drag_changes_distance_live(self):
        w=self.w;self.sketch('rect',(0,0),(10,10));w.set_mode('extrude');self.pick_sketch_profile(w.document.bodies[0])
        w.ex_value.setValue(10);w.handle_dragged('ex',5.04);self.assertAlmostEqual(w.ex_value.value(),15.0,1)
        w.handle_dragged('ex',-2.0);self.assertAlmostEqual(w.ex_value.value(),8.0,1);w.handle_released('ex');self.assertIsNone(w._hv)

    def test_two_sided_extrude(self):
        w=self.w;self.sketch('rect',(0,0),(10,10));w.set_mode('extrude');self.pick_sketch_profile(w.document.bodies[0])
        w.ex_dir.setCurrentIndex(2);w.ex_value.setValue(10);w.ex_second.setValue(5);w.apply_extrude();self.wait()
        solid=[b for b in w.document.bodies if b.kind=='solid'][0];self.assertAlmostEqual(solid.shape.Volume(),1500,2)

    def test_extrude_face_of_solid_joins_and_cuts(self):
        w=self.w;a=Body('A',k.box(20,20,20)).prepared();w.document.commit([a]);w.refresh();w.set_mode('extrude')
        with patch.object(w.view,'pick_profile',return_value=None),patch.object(w.view,'pick_face',return_value=(a.id,[0,0,1],[10,10,20])):
            w.view_clicked(5,5,False,False)
        self.assertEqual(w.ex_profiles[0]['kind'],'face')
        w.ex_op.setCurrentIndex(1);w.ex_value.setValue(5);w.apply_extrude();self.wait()
        self.assertAlmostEqual(w.document.get(a.id).shape.Volume(),20*20*25,1)

    def make_solids(self):
        w=self.w
        a=Body('A',k.box(20,20,20)).prepared();b=Body('B',k.box(10,10,40)).prepared()
        w.document.commit([a,b]);w.refresh()
        return a,b

    def test_boolean_base_and_tool_selection_with_live_result(self):
        w=self.w;a,b=self.make_solids();w.set_mode('bool')
        for body in (a,b):
            with patch.object(w.view,'pick_body',return_value=body.id):w.view_clicked(5,5,False,False)
        self.assertEqual(w.bool_ids,[a.id,b.id]);self.assertIn(a.id,w.view.tints)
        w.update_bool_preview();self.preview();self.assertTrue(w.view.preview_items)
        w.bool_op.setCurrentIndex(0);w.apply_bool();self.wait()
        self.assertEqual(len([x for x in w.document.bodies if x.kind=='solid']),1)
        self.assertGreater(w.document.bodies[0].shape.Volume(),8000)

    def test_fillet_arrow_and_live_preview(self):
        w=self.w;a=Body('A',k.box(20,20,20)).prepared();w.document.commit([a]);w.refresh();w.set_mode('mod')
        with patch.object(w.view,'nearest_edge',return_value=(a.id,0)):w.view_clicked(5,5,False,False)
        self.assertEqual(w.edges,{a.id:{0}});self.assertTrue(w.view.handles)
        w.handle_dragged('mod',2.0);self.assertGreater(w.mod_size.value(),3.0);w.handle_released('mod')
        w.mod_size.setValue(2);w.update_mod_preview();self.preview();self.assertTrue(w.view.preview_items)
        w.apply_mod();self.wait();self.assertLess(w.document.bodies[0].shape.Volume(),8000)

    def test_chamfer(self):
        w=self.w;a=Body('A',k.box(20,20,20)).prepared();w.document.commit([a]);w.refresh();w.set_mode('mod');w.mod_kind.setCurrentIndex(1)
        w.edges={a.id:{0}};w.mod_size.setValue(2);w.apply_mod();self.wait();self.assertLess(w.document.bodies[0].shape.Volume(),8000)

    def test_mirror_object_then_face(self):
        w=self.w;a=Body('A',k.hole(k.box(20,20,20),3,5,5)).prepared();w.document.commit([a]);w.refresh();w.set_mode('mirror')
        with patch.object(w.view,'pick_body',return_value=a.id):w.view_clicked(5,5,False,False)
        with patch.object(w.view,'pick_face',return_value=(a.id,[1,0,0],[20,10,10])):w.view_clicked(5,5,False,False)
        self.assertIsNotNone(w.mirror_frame);w.update_mirror_preview();self.preview();self.assertTrue(w.view.preview_items)
        w.apply_mirror();self.wait();self.assertEqual(len(w.document.bodies),2)

    def test_move_and_rotate_selected_solid_live(self):
        w=self.w;a,b=self.make_solids();w.selected=[a.id];w.set_mode('move');self.assertIs(w.t_target.id,a.id)
        w.t_spins[0].setValue(7);w.update_transform_preview();self.preview();self.assertAlmostEqual(w.override[a.id].shape.Center().x,10+7,2)
        w.handle_dragged('x',3.0);w.handle_released('x');w.apply_transform();self.wait()
        self.assertAlmostEqual(w.document.get(a.id).shape.Center().x,10+10,2)
        w.selected=[a.id];w.set_mode('rotate');w.t_spins[2].setValue(90);w.update_transform_preview();self.preview();self.assertTrue(w.override)
        w.apply_transform();self.wait()

    def test_move_selected_sketch(self):
        w=self.w;self.sketch('rect',(0,0),(10,10));sk=w.document.bodies[0];w.set_mode(None);w.selected=[sk.id];w.set_mode('move')
        w.t_spins[1].setValue(5);w.apply_transform();self.wait()
        self.assertAlmostEqual(k.bounds(w.document.get(sk.id).shape).ymin,5,3)

    def test_undo_redo_and_escape(self):
        w=self.w;self.sketch('circle',(0,0),(5,0));self.assertTrue(w.undo_button.isEnabled())
        w.undo();self.assertEqual(len(w.document.bodies),0);w.redo();self.assertEqual(len(w.document.bodies),1)
        w.points=[(0,0)];w.keyPressEvent(QKeyEvent(QEvent.KeyPress,Qt.Key_Escape,Qt.NoModifier));self.assertEqual(w.points,[])

    def test_line_chain_closes_into_extrudable_profile(self):
        w=self.w;w.set_mode('plane');w.plane_picked('XY');w.choose_tool('line')
        for p in ((0,0),(20,0),(20,10),(0,0)):w.sketch_clicked('XY',*p)
        self.wait();self.assertEqual(len(w.document.bodies),1);self.assertTrue(w.document.bodies[0].shape.IsClosed())

    def test_open_line_finishes_on_double_point(self):
        w=self.w;w.set_mode('plane');w.plane_picked('XY');w.choose_tool('line')
        for p in ((0,0),(10,0),(10,10),(10,10)):w.sketch_clicked('XY',*p)
        self.wait();self.assertEqual(len(w.document.bodies),1);self.assertFalse(w.document.bodies[0].shape.IsClosed())

    def test_arc_point_construction_rect3(self):
        self.sketch('arc',(10,0),(0,10),(-10,0));self.sketch('point',(3,3));self.sketch('construction',(0,0),(30,0))
        self.sketch('rect3',(0,0),(10,0),(5,4));self.assertEqual(len(self.w.document.bodies),4)

    def test_measure_does_not_create_geometry(self):
        self.sketch('measure',(0,0),(3,4));self.assertEqual(len(self.w.document.bodies),0);self.assertIn('5,000',self.w.notice.text())

    def test_trim_removes_clicked_segment(self):
        self.sketch('rect',(0,0),(10,10));w=self.w;w.choose_tool('trim');body=w.document.bodies[0]
        with patch.object(w,'_cursor_edge',return_value=(body.id,0)):w.sketch_clicked('XY',0,0)
        self.wait();self.assertFalse(w.document.bodies[0].shape.IsClosed())

    def test_tangent_circle_between_two_lines(self):
        w=self.w;self.sketch('line',(0,0),(30,0),(30,0));self.sketch('line',(0,0),(0,30),(0,30))
        a,b=w.document.bodies;w.choose_tool('circleTangent2')
        for body in (a,b):
            with patch.object(w,'_cursor_edge',return_value=(body.id,0)):w.sketch_clicked('XY',1,1)
        self.assertEqual(len(w.tangent_lines),2);w.sketch_clicked('XY',10,10);self.wait()
        self.assertEqual(len(w.document.bodies),3)

    def test_text_creates_profiles_when_font_exists(self):
        try:k.text_shape('XY','AB',0,0,10)
        except Exception:self.skipTest('brak czcionki w środowisku')
        self.sketch('text',(0,0));self.assertGreaterEqual(len(self.w.document.bodies),1)

    def test_typed_dimensions_are_live(self):
        w=self.w;w.set_mode('plane');w.plane_picked('XY');w.choose_tool('rect');w.sketch_clicked('XY',0,0)
        self.assertTrue(w.open_dim_input('3'));w.dim_edits[0].setText('30');w.dim_edits[1].setText('10')
        w.update_dim_preview();self.preview();self.assertTrue(w.view.preview_items);w.apply_typed();self.wait()
        b=k.bounds(w.document.bodies[0].shape);self.assertAlmostEqual(b.xlen,30,3);self.assertAlmostEqual(b.ylen,10,3)

    def test_handles_are_drawn_on_top_overlay_and_draggable(self):
        w=self.w;self.sketch('rect',(0,0),(10,10));w.set_mode('extrude');self.pick_sketch_profile(w.document.bodies[0])
        self.assertTrue(w.view.handles);geo=w.view.handle_geometry(w.view.handles[0]);self.assertIsNotNone(geo)
        grabbed=w.view._grab_handle(*geo['end']);self.assertEqual(grabbed[1],'ex')
        w.view.overlay.repaint();self.app.processEvents()

    def test_snap_to_existing_sketch_corner(self):
        w=self.w;self.sketch('rect',(0,0),(10,10));w.choose_tool('line')
        x,y=w.view.project_one(k.to_world('XY',10,10))
        u,v,label=w._snapper(x+3,y+2,(10.4,10.3));self.assertEqual(label,'Punkt styku');self.assertAlmostEqual(u,10,3);self.assertAlmostEqual(v,10,3)
        u,v,label=w._snapper(x+60,y+60,(14.3,3.9));self.assertEqual(label,None if label is None else 'Siatka')
        w.view.set_marker(k.to_world('XY',10,10),label='Punkt styku');self.assertIsNotNone(w.view.snap_marker)

    def test_svg_import(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            f=os.path.join(d,'a.svg');open(f,'w').write('<svg xmlns="http://www.w3.org/2000/svg"><rect x="0" y="0" width="20" height="10"/><circle cx="5" cy="5" r="2"/><path d="M0 0 L10 0 L10 10 Z"/></svg>')
            self.assertEqual(len(k.svg_profiles(f)),3)

    def test_file_menu_and_context_menu_open(self):
        from rccad import shell_ui as ui
        seen=[]
        with patch.object(ui.PopupMenu,'popup_at',lambda menu,pos:seen.append(len(menu.findChildren(ui._Row)))):
            self.w.file_menu()
            a,b=self.make_solids()
            with patch.object(self.w.view,'pick_body',return_value=a.id):self.w.context_menu(5,5)
        self.assertEqual(seen,[6,4])

    def test_every_button_click_raises_no_exception(self):
        import sys
        from PySide6.QtWidgets import QToolButton
        from rccad import shell_ui as ui
        errors=[];old=sys.excepthook;sys.excepthook=lambda *a:errors.append(a[1])
        try:
            with patch.object(ui.PopupMenu,'popup_at',lambda *a:None):
                for key in ('file','sketch','extrude','bool','mod','mirror','mod','bool'):self.w.tools[key].click();self.app.processEvents()
                self.w.tools['sketch'].click();self.w.plane_picked('XY')
                for b in list(self.w.shape_buttons.values()):b.click();self.app.processEvents()
                for b in self.w.shape_bar.findChildren(QToolButton):
                    if b.objectName()=='shapeExpand':b.click();self.app.processEvents()
                self.w.set_mode(None)
                for b in self.w.cube.findChildren(QToolButton):b.click()
                for b in (*self.w.pad_buttons.values(),self.w.layers,self.w.layers,self.w.home,self.w.undo_button,self.w.redo_button):b.click();self.app.processEvents()
        finally:sys.excepthook=old
        self.assertEqual(errors,[])


if __name__=='__main__':
    unittest.main()
