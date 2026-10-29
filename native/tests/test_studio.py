"""Okno Studio: układ jak w HTML oraz przepływ szkic → wyciągnięcie → Boolean / zaokrąglenie / lustro."""
import os, faulthandler
faulthandler.dump_traceback_later(420, exit=True, file=open(os.environ.get("DIAG_FILE","diag_hang.txt"),"w"))
os.environ.setdefault('QT_QPA_PLATFORM','offscreen' if not os.environ.get('DISPLAY') and os.name!='nt' else '')
import time, math
import numpy as np
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
        self.assertEqual(w.undo_button.x(),W-398);self.assertEqual(w.redo_button.x(),W-350);self.assertEqual(w.layers.x(),W-302);self.assertEqual(w.xray.x(),W-254)
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

    def test_rotated_sketch_extrudes_along_its_tilt(self):
        from dataclasses import replace as rep
        w=self.w;self.sketch('rect',(0,0),(20,10));b=w.document.bodies[0]
        tilted=k.transform(b.shape,(0,0,0),(10,0,0));w.document.commit([rep(b,shape=tilted,mesh=k.display_mesh(tilted))])
        centre=np.array(tilted.Center().toTuple())
        for patches in (dict(),dict(_region_at=None)):
            with patch.object(w.view,'_plane_hit',lambda pl,x,y:(1.0,centre)),patch.object(w.view,'pick_face',return_value=None),patch.object(w.view,'pick_profile',return_value=b.id):
                if patches:
                    with patch.object(w,'_region_at',return_value=None):src=w._profile_at(5,5)
                else:src=w._profile_at(5,5)
            self.assertAlmostEqual(abs(src['normal'][2]),math.cos(math.radians(10)),4);self.assertGreater(abs(src['normal'][1]),.1)
            w.ex_profiles=[src];w.ex_value.setValue(10)
            solid=w._make_tools()[0]();self.assertAlmostEqual(solid.Volume(),2000,1)
            self.assertAlmostEqual(solid.BoundingBox().ylen,10*math.cos(math.radians(10))+10*math.sin(math.radians(10)),2)

    def test_smallest_coplanar_region_wins_over_old_profile(self):
        w=self.w;self.sketch('rect',(0,0),(20,20))
        fr=k.Frame((0.0,0.0,0.0),(1.0,0.0,0.0),(0.0,0.0,-1.0))
        c=Body('Szkic ściana',k.sketch_shape('circle',fr,[(10,-10),(13,-10)]),'sketch',fr).prepared();w.document.commit([*w.document.bodies,c]);w.refresh()
        with patch.object(w.view,'_plane_hit',lambda pl,x,y:(5.0,np.array([10.0,10.0,0.0]))):
            region=w._region_at(5,5)
        self.assertIsNotNone(region);self.assertLess(region[2].Area(),100)

    def test_extrude_by_clicking_profile_with_preview(self):
        w=self.w;self.sketch('rect',(0,0),(20,10));w.set_mode('extrude')
        self.pick_sketch_profile(w.document.bodies[0]);w.ex_value.setValue(15)
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

    def test_corner_vertex_is_blended_alone_and_face_double_click_selects_edges(self):
        w=self.w;a=Body('A',k.box(20,20,20)).prepared();w.document.commit([a]);w.refresh();w.set_mode('mod')
        pt=np.array(a.mesh.edges[0][0],float)
        cham=k.blend_vertices(a.shape,[pt],3,'chamfer');rnd=k.blend_vertices(a.shape,[pt],3,'fillet')
        self.assertAlmostEqual(8000-cham.Volume(),27/6,3);self.assertTrue(0<8000-rnd.Volume()<27/6)
        self.assertEqual(len(cham.Edges()),len(a.shape.Edges())+3)
        with patch.object(w.view,'nearest_vertex',return_value=(a.id,pt)):w.view_clicked(5,5,False,False)
        self.assertEqual((len(w.mod_vertices[a.id]),w.edges),(1,{}));self.assertTrue(w.view.handles);self.assertEqual(len(w.view.sel_vertices),1)
        w.mod_size.setValue(3);w.update_mod_preview();self.preview();self.assertTrue(w.view.preview_items)
        w.apply_mod();self.wait();self.assertLess(w.document.bodies[0].shape.Volume(),8000);self.assertGreater(w.document.bodies[0].shape.Volume(),7990)
        a=w.document.bodies[0];w.set_mode('mod');far=max((np.array(e[0],float) for e in a.mesh.edges.values()),key=lambda q:float(np.linalg.norm(q-pt)))
        with patch.object(w.view,'pick_face',return_value=(a.id,[0,0,1],far.tolist())):w.view_double_clicked(5,5)
        self.assertEqual(w.mod_vertices,{});self.assertGreaterEqual(len(w.edges[a.id]),4);self.assertTrue(w.view.selection_items)

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
        w.t_spins[0].setValue(7);self.assertIn(a.id,w.view._body_m)
        w.handle_dragged('x',3.0);w.handle_released('x');w.apply_transform();self.wait()
        self.assertAlmostEqual(w.document.get(a.id).shape.Center().x,10+10,2)
        w.selected=[a.id];w.set_mode('rotate');w.t_spins[2].setValue(90);self.assertIn(a.id,w.view._body_m)
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
        pieces=k.trim_pieces([body.shape.Edges()],0)
        with patch.object(w,'_trim_target',return_value=(body,pieces,0)):w.sketch_clicked('XY',0,0)
        self.wait();self.assertFalse(w.document.bodies[0].shape.IsClosed())

    def test_tangent_circle_between_two_lines(self):
        w=self.w;self.sketch('line',(0,0),(30,0),(30,0));self.sketch('line',(0,0),(0,30),(0,30))
        a,b=w.document.bodies;w.choose_tool('circleTangent2')
        for body in (a,b):
            with patch.object(w,'_cursor_edge',return_value=(body.id,0)):w.sketch_clicked('XY',1,1)
        self.assertEqual(len(w.tangent_lines),2);w.sketch_clicked('XY',10,10);self.wait()
        self.assertEqual(len(w.document.bodies),3)

    def test_text_wizard_surface_area_handles_and_enter(self):
        try:k.text_shape('XY','AB',0,0,10)
        except Exception:self.skipTest('brak czcionki w środowisku')
        self.assertGreaterEqual(len(k.text_shape('XY','O',0,0,10)),2)
        a=k.text_shape('XY','Ab',0,0,10)[0].Center().toTuple();b=k.text_shape('XY','Ab',30,5,10)[0].Center().toTuple()
        self.assertAlmostEqual(b[0]-a[0],30,3);self.assertAlmostEqual(b[1]-a[1],5,3)
        s20=k.text_shape('XY','Ab',0,0,20)[0].Center().toTuple();self.assertAlmostEqual(s20[0],a[0]*2,3)
        w=self.w;w.set_mode('plane');w.plane_picked('XY');w.choose_tool('text')
        self.assertEqual(w.txt['stage'],'surface');self.assertTrue(w.view.plane_pick)
        with patch.object(w,'pick_surface',return_value=('XZ',None)):w.view_clicked(5,5,False,False)
        self.assertEqual((w.txt['stage'],w.sketch_plane),('area',"XZ"))
        with patch.object(w.view,'plane_point',side_effect=lambda pl,x,y:(x/10,y/10)),patch.object(w.view,'project_one',side_effect=lambda p:(p[0]*10,p[2]*10) if True else None):
            self.assertTrue(w._sketch_hook('press',0,0));w._sketch_hook('move',300,100);w._sketch_hook('release',300,100)
            self.assertEqual(w.txt['stage'],'edit');self.assertIsNotNone(w.view.sketch_box);size0=w.txt['size'];self.assertGreater(size0,0)
            g=w._text_geometry();bx=w._text_box_world()
            sx,sy=bx['scale'][0]*10,bx['scale'][2]*10
            self.assertTrue(w._sketch_hook('press',sx,sy));w._sketch_hook('move',sx*1.5,sy*1.5);w._sketch_hook('release',sx*1.5,sy*1.5)
            self.assertGreater(w.txt['size'],size0)
            rx,ry=w._text_box_world()['rotate'][0]*10,w._text_box_world()['rotate'][2]*10
            self.assertTrue(w._sketch_hook('press',rx,ry));w._sketch_hook('move',rx-80,ry+80);w._sketch_hook('release',rx-80,ry+80)
            self.assertNotEqual(w.txt['angle'],0.0)
        before=len(w.document.bodies);ev=QKeyEvent(QEvent.KeyPress,Qt.Key_Return,Qt.NoModifier);w.keyPressEvent(ev);self.wait()
        self.assertGreater(len(w.document.bodies),before);self.assertEqual(w.txt['stage'],'area')

    def test_typed_dimensions_are_live(self):
        w=self.w;w.set_mode('plane');w.plane_picked('XY');w.choose_tool('rect');w.sketch_clicked('XY',0,0)
        self.assertTrue(w.open_dim_input('3'));w.dim_edits[0].setText('30');w.dim_edits[1].setText('10')
        w.update_dim_preview();self.preview();self.assertTrue(w.view.preview_items);w.apply_typed();self.wait()
        b=k.bounds(w.document.bodies[0].shape);self.assertAlmostEqual(b.xlen,30,3);self.assertAlmostEqual(b.ylen,10,3)

    def test_handles_are_drawn_on_top_overlay_and_draggable(self):
        w=self.w;self.sketch('rect',(0,0),(10,10));w.set_mode('extrude');self.pick_sketch_profile(w.document.bodies[0])
        self.assertTrue(w.view.handles);geo=w.view.handle_geometry(w.view.handles[0]);self.assertIsNotNone(geo)
        grabbed=w.view._grab_handle(*geo['end']);self.assertIsNotNone(grabbed);self.assertEqual(grabbed['id'],'ex')
        w.view.overlay.repaint();self.app.processEvents()

    def test_snap_to_existing_sketch_corner(self):
        w=self.w;self.sketch('rect',(0,0),(10,10));w.choose_tool('line')
        x,y=w.view.project_one(k.to_world('XY',10,10))
        u,v,label=w._snapper(x+3,y+2,(10.4,10.3));self.assertEqual(label,'Punkt styku');self.assertAlmostEqual(u,10,3);self.assertAlmostEqual(v,10,3)
        u,v,label=w._snapper(x+60,y+60,(14.3,3.9));self.assertEqual(label,None if label is None else 'Siatka')
        w.view.set_marker(k.to_world('XY',10,10),label='Punkt styku');self.assertIsNotNone(w.view.snap_marker)

    def test_overlapping_shapes_make_regions_and_extrude_overlap(self):
        w=self.w;self.sketch('rect',(0,0),(10,10));self.sketch('rect',(5,0),(15,10))
        plane,bodies=w._drawn_sketches()['XY'];faces=w._regions_for('XY',plane,bodies)
        self.assertEqual(len(faces),3);areas=sorted(round(f.Area()) for f in faces);self.assertEqual(areas,[50,50,50])
        self.assertTrue(any(k.face_contains(f,k.to_world('XY',7.5,5)) for f in faces))
        mid=[f for f in faces if k.face_contains(f,k.to_world('XY',7.5,5))][0]
        w.set_mode('extrude');src=dict(kind='region',id=None,face=mid,wire=mid.outerWire(),plane='XY',normal=(0,0,1),center=mid.Center().toTuple())
        with patch.object(w,'_profile_at',return_value=src):w.view_clicked(5,5,False,False)
        w.ex_value.setValue(4);w.apply_extrude();self.wait()
        solid=[b for b in w.document.bodies if b.kind=='solid'][0];self.assertAlmostEqual(solid.shape.Volume(),50*4,2)

    def test_trim_splits_at_intersection(self):
        w=self.w;self.sketch('line',(0,0),(20,0),(20,0));self.sketch('line',(10,-5),(10,5),(10,5))
        a,b=w.document.bodies;pieces=k.trim_pieces([a.shape.Edges(),b.shape.Edges()],0);self.assertEqual(len(pieces),2)
        w.choose_tool('trim')
        with patch.object(w,'_trim_target',return_value=(a,pieces,0)):w.sketch_clicked('XY',0,0)
        self.wait();self.assertEqual(len(w.document.bodies),2)
        self.assertAlmostEqual(k.bounds(w.document.bodies[0].shape).xlen,10,3)

    def test_help_dialog_selection_glow_and_mirror_steps(self):
        from rccad.help import HelpDialog,TOPICS
        d=HelpDialog(self.w);self.assertEqual(d.list.count(),len(TOPICS));d.list.setCurrentRow(2);self.assertTrue(d.body.text());d.close()
        w=self.w;self.sketch('rect',(0,0),(10,10));w.set_mode('extrude');self.pick_sketch_profile(w.document.bodies[0])
        self.assertTrue(w.view.selection_items)
        w.set_mode('mirror');self.assertEqual(w.mir_step1.value.text(),'Kliknij bryłę lub szkic')
        w.view.stretch_preview((0,0,0),(0,0,1),1.5)


    def test_cube_arrows_auto_cut_xray_pick_and_splash(self):
        w=self.w;w.view.setCameraPosition(azimuth=-90,elevation=0);w._cube_rotate(90,0);self.assertAlmostEqual(w.view.opts['azimuth'],0,3)
        w._cube_rotate(0,90);self.assertAlmostEqual(w.view.opts['elevation'],90,3)
        hit=w.cube._hit(w.cube._arrow_center('left'));self.assertEqual(hit,('arrow','left'))
        self.sketch('rect',(0,0),(10,10));w.set_mode('extrude');self.pick_sketch_profile(w.document.bodies[0])
        w.ex_value.setValue(10);w.apply_extrude();self.wait()
        solid=[b for b in w.document.bodies if b.kind=='solid'][0]
        self.assertEqual(k.point_state(solid.shape,(5,5,5)),'in')
        from rccad.splash import Splash
        sp=Splash('');sp.show();sp.repaint();sp.close()

    def test_idle_planes_axes_close_prompt_and_reverse_arrow(self):
        w=self.w;w.set_mode(None);w.view.set_view('iso');self.app.processEvents()
        xy=w.view.project_one((.5,.5,0));name=w.view.plane_at(*xy);self.assertIn(name,('XY','XZ','YZ'))
        w.view_clicked(xy[0],xy[1],False,False);self.assertEqual((w.mode,w.sketch_plane),('sketch',name))
        w.set_mode(None);w.view.set_view('Z');w.view.update();self.assertFalse(w.view.axis_lines[2][0].visible())
        w.view.set_view('iso');w.view.update();self.assertTrue(w.view.axis_lines[2][0].visible())
        self.sketch('rect',(0,0),(10,10));w.set_mode('extrude');self.pick_sketch_profile(w.document.bodies[0])
        w.ex_value.setValue(-5);w._place_extrude_handle();h=w.view.handles[0];self.assertAlmostEqual(float(np.dot(h['dir'],h['tip']-h['start'])),-5,3)
        self.assertTrue(w.document.dirty)
        with patch.object(QMessageBox,'question',return_value=QMessageBox.Cancel):
            from PySide6.QtGui import QCloseEvent
            ev=QCloseEvent();w.closeEvent(ev);self.assertFalse(ev.isAccepted())

    def test_defaults_and_auto_new_body(self):
        w=self.w;self.sketch('rect',(0,0),(10,10));w.set_mode('extrude');self.pick_sketch_profile(w.document.bodies[0])
        self.assertEqual(w.ex_value.value(),10);self.assertEqual(w.ex_op.currentData(),'new')
        w.set_mode('mod');self.assertEqual(w.mod_size.value(),2)

    def test_tab_numeric_edit_polygon_sides_and_clear_all(self):
        w=self.w
        self.sketch('rect',(0,0),(20,10))
        sk=w.document.bodies[-1];self.assertEqual(sk.meta['tool'],'rect')
        w.set_mode(None);w.selected=[sk.id];self.assertTrue(w.open_dim_edit())
        self.assertEqual([e.text() for e in w.dim_edits if e.isVisible()],['20.0','10.0'])
        w.dim_edits[0].setText('30');w.dim_edits[1].setText('5');w.apply_dim_edit();self.wait()
        b=k.bounds(w.document.bodies[-1].shape);self.assertAlmostEqual(b.xlen,30,3);self.assertAlmostEqual(b.ylen,5,3)
        w.set_mode('plane');w.plane_picked('XY');w.choose_tool('polygon');w.sketch_clicked('XY',0,0)
        self.assertTrue(w.open_dim_input());self.assertEqual(len([e for e in w.dim_edits if e.isVisible()]),2)
        w.dim_edits[0].setText('10');w.dim_edits[1].setText('6');w.apply_typed();self.wait()
        self.assertEqual(w.document.bodies[-1].meta['sides'],6);self.assertEqual(len(w.document.bodies[-1].shape.Edges()),6)
        with patch.object(QMessageBox,'question',return_value=QMessageBox.Yes):w.clear_all()
        self.assertEqual(len(w.document.bodies),0)
        w.undo();self.assertTrue(w.document.bodies)

    def test_shape_icons_and_menu_card(self):
        from rccad import shell_ui as ui
        for item in ui.load_shapes():
            if not item['variant']:self.assertFalse(ui.style_icon('s_'+item['shape'],28).isNull(),item['shape'])
        m=ui.RichMenu(self.w,[(ui.icons.pixmap('f_new',34),'A','b',lambda:None)],'T',300);self.assertEqual(m.card.objectName(),'rich');m.close()

    def test_tool_toggle_select_and_drag_resize(self):
        w=self.w;self.sketch('rect',(0,0),(20,10))
        w._tool_clicked('rect');self.assertIsNone(w.tool);self.assertFalse(any(b.isChecked() for b in w.shape_buttons.values()))
        w.view.update();a=w.view.project_one((20,5,0));self.assertTrue(w.view.drag_hook('press',*a))
        self.assertEqual(w.selected,[w.document.bodies[-1].id]);self.assertEqual(len(w.view.sketch_grips),8)
        w.view.drag_hook('move',*w.view.project_one((30,5,0)));w.view.drag_hook('release',*w.view.project_one((30,5,0)));self.wait()
        b=k.bounds(w.document.bodies[-1].shape);self.assertAlmostEqual(b.xlen,30,1);self.assertAlmostEqual(b.ylen,10,1)
        w._tool_clicked('circle');self.assertEqual(w.tool,'circle');self.assertEqual(w.selected,[])
        w._tool_clicked('circle');self.assertIsNone(w.tool)

    def test_arc_is_editable_after_drawing(self):
        w=self.w;w.set_mode('plane');w.plane_picked('XY')
        w.choose_tool('arc');w.sketch_clicked('XY',0,20);w.sketch_clicked('XY',5,23);w.sketch_clicked('XY',10,20);self.wait()
        arc=w.document.bodies[-1];self.assertEqual(arc.meta['tool'],'arc');w.choose_tool(None);w.selected=[arc.id];self.assertTrue(w.open_dim_edit())
        self.assertEqual([e.text() for e in w.dim_edits if e.isVisible()],['10.0','3.0']);w.dim_panel.hide()

    def test_cube_face_preselects_sketch_plane_and_grid_button(self):
        w=self.w;w.set_mode(None);w._cube_clicked('X');self.assertIsNone(w.mode)
        w.toggle_mode('sketch');self.assertEqual((w.mode,w.sketch_plane),('sketch','YZ'))
        w.set_mode(None);w.view.set_view('iso');w.toggle_mode('sketch');self.assertEqual(w.mode,'plane')
        w.set_mode(None);self.assertTrue(w.grid_button.isChecked())
        w.grid_button.setChecked(False);self.assertFalse(any(g.visible() for g in w.view.grid_items))
        w.grid_button.setChecked(True);self.assertTrue(all(g.visible() for g in w.view.grid_items))

    def test_cube_button_picks_sketch_plane_and_grid_adapts(self):
        w=self.w;w.set_mode('plane');w._cube_clicked('X');self.assertEqual((w.mode,w.sketch_plane),('sketch','YZ'))
        w.view.opts['distance']=400;w.view.update();far=w.view._grid_key[0]
        w.view.opts['distance']=15;w.view.update();near=w.view._grid_key[0];self.assertLess(near,far)

    def test_transform_preview_is_instant_matrix(self):
        w=self.w;a,b=self.make_solids();w.selected=[a.id];w.set_mode('rotate');w.t_spins[0].setValue(30)
        self.assertIsNotNone(w.view._body_m.get(a.id));w.set_mode(None);self.assertNotIn(a.id,w.view._body_m)

    def test_trimmed_union_outline_is_one_extrudable_region(self):
        w=self.w;self.sketch('rect',(0,0),(10,10));self.sketch('rect',(5,0),(15,10));w.choose_tool('trim')
        for which,(x,y) in ((0,(10,5)),(-1,(5,5))):
            n=len(w.document.bodies);bi=which if which>=0 else n-1;body=w.document.bodies[bi]
            pieces=k.trim_pieces([b.shape.Edges() for b in w.document.bodies],bi)
            idx=min(range(len(pieces)),key=lambda i:(pieces[i].Center().x-x)**2+(pieces[i].Center().y-y)**2)
            with patch.object(w,'_trim_target',return_value=(body,pieces,idx)):w.sketch_clicked('XY',0,0)
            self.wait()
        plane,bodies=w._drawn_sketches()['XY'];faces=w._regions_for('XY',plane,bodies)
        self.assertTrue(any(abs(f.Area()-150)<1e-3 for f in faces),[round(f.Area(),2) for f in faces])
        big=[f for f in faces if abs(f.Area()-150)<1e-3][0]
        w.set_mode('extrude');src=dict(kind='region',id=None,face=big,wire=big.outerWire(),plane='XY',normal=(0,0,1),center=big.Center().toTuple())
        with patch.object(w,'_profile_at',return_value=src):w.view_clicked(5,5,False,False)
        w.ex_value.setValue(3);w.apply_extrude();self.wait()
        self.assertAlmostEqual([b for b in w.document.bodies if b.kind=='solid'][0].shape.Volume(),450,2)

    def test_escape_and_right_click_keep_line_and_leave_drawing(self):
        w=self.w;w.set_mode('plane');w.plane_picked('XY');w.choose_tool('line')
        for p in ((0,0),(10,0),(10,10)):w.sketch_clicked('XY',*p)
        w.keyPressEvent(QKeyEvent(QEvent.KeyPress,Qt.Key_Escape,Qt.NoModifier));self.wait()
        self.assertEqual(len(w.document.bodies),1);self.assertEqual(w.points,[]);self.assertEqual(w.mode,'sketch')
        for p in ((20,0),(30,0)):w.sketch_clicked('XY',*p)
        w.context_menu(5,5);self.wait();self.assertEqual(len(w.document.bodies),2)
        w.sketch_clicked('XY',40,0);w.context_menu(5,5);self.assertEqual(len(w.document.bodies),2)

    def test_hover_cursor_only_after_first_click(self):
        w=self.w;w.set_mode('plane');w.plane_picked('XY');w.choose_tool('rect');self.assertFalse(w.sketch_hover_wanted())
        w.sketch_clicked('XY',0,0);self.assertTrue(w.sketch_hover_wanted())

    def test_svg_import(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            f=os.path.join(d,'a.svg');open(f,'w').write('<svg xmlns="http://www.w3.org/2000/svg"><rect x="0" y="0" width="20" height="10"/><circle cx="5" cy="5" r="2"/><path d="M0 0 L10 0 L10 10 Z"/></svg>')
            self.assertEqual(len(k.svg_profiles(f)),3)

    def test_file_menu_and_context_menu_open(self):
        from rccad import shell_ui as ui
        seen=[]
        with patch.object(ui.PopupMenu,'popup_at',lambda menu,pos:seen.append(('ctx',len(menu.actions)))),\
             patch.object(ui.RichMenu,'popup_at',lambda menu,pos:seen.append(('rich',len(menu.actions)))):
            self.w.file_menu()
            a,b=self.make_solids()
            with patch.object(self.w.view,'pick_body',return_value=a.id):self.w.context_menu(5,5)
            self.w.tools['sketch'].click();self.w.plane_picked('XY')
            for b in self.w.shape_bar.findChildren(__import__('PySide6.QtWidgets',fromlist=['QToolButton']).QToolButton):
                if b.objectName()=='shapeExpand':b.click()
        self.assertEqual(seen[:2],[('rich',7),('ctx',4)]);self.assertEqual([n for kind,n in seen[2:]],[3,4])

    def test_every_button_click_raises_no_exception(self):
        import sys
        from PySide6.QtWidgets import QToolButton
        from rccad import shell_ui as ui
        errors=[];old=sys.excepthook;sys.excepthook=lambda *a:errors.append(a[1])
        try:
            with patch.object(ui.PopupMenu,'popup_at',lambda *a:None),patch.object(ui.RichMenu,'popup_at',lambda *a:None):
                for key in ('file','sketch','extrude','bool','mod','mirror','mod','bool'):self.w.tools[key].click();self.app.processEvents()
                self.w.tools['sketch'].click();self.w.plane_picked('XY')
                for b in list(self.w.shape_buttons.values()):b.click();self.app.processEvents()
                for b in self.w.shape_bar.findChildren(QToolButton):
                    if b.objectName()=='shapeExpand':b.click();self.app.processEvents()
                self.w.set_mode(None)
                for b in self.w.cube.findChildren(QToolButton):b.click()
                for b in (*self.w.pad_buttons.values(),self.w.layers,self.w.xray,self.w.home,self.w.undo_button,self.w.redo_button):b.click();self.app.processEvents()
        finally:sys.excepthook=old
        self.assertEqual(errors,[])


if __name__=='__main__':
    unittest.main()
