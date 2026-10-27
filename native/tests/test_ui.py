"""Native widget actions and background computation; no browser automation."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen' if not os.environ.get('DISPLAY') and os.name!='nt' else '')
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from PySide6.QtCore import Qt,QThread
from PySide6.QtWidgets import QApplication,QMessageBox,QAbstractItemView
from rccad import kernel as k
from rccad.document import Body
from rccad.window import MainWindow


class NativeUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        self.window=MainWindow()
        self.window.resize(1200,850)
        self.window.layout().activate()
        self.warning=patch.object(QMessageBox,'warning',return_value=QMessageBox.Ok)
        self.warning_mock=self.warning.start()
        self.info=patch.object(QMessageBox,'information',return_value=QMessageBox.Ok)
        self.info.start()

    def tearDown(self):
        self.wait()
        self.window.pool.waitForDone(5000)
        self.window.document._saved_revision=self.window.document._revision
        self.window.close()
        self.app.processEvents()
        self.warning.stop();self.info.stop()

    def wait(self):
        end=time.monotonic()+15
        while self.window.busy and time.monotonic()<end:
            self.app.processEvents();time.sleep(.005)
        self.app.processEvents()
        self.assertFalse(self.window.busy,'Background CAD operation did not finish')

    def add_box(self):
        with patch('rccad.window.values_dialog',return_value={'x':30,'y':30,'z':30}):
            self.window.add_box()
        self.wait()
        self.assertEqual(len(self.window.document.bodies),1)

    def test_creation_updates_native_tree_properties_and_undo(self):
        self.add_box()
        self.assertEqual(self.window.tree.topLevelItemCount(),1)
        self.assertIn('Objętość',self.window.properties.text())
        self.window.undo();self.assertEqual(len(self.window.document.bodies),0)
        self.window.redo();self.assertEqual(len(self.window.document.bodies),1)

    def test_worker_applies_result_on_gui_thread(self):
        threads=[]
        self.window.run_operation('Test',lambda:Body('A',k.box(10,10,10)).prepared(),lambda body:(threads.append(QThread.currentThread()),self.window.add_prepared(body)))
        self.wait()
        self.assertEqual(threads,[self.app.thread()])

    def test_failed_operation_keeps_model(self):
        self.add_box();body=self.window.document.bodies[0]
        self.window.run_operation('Błąd',lambda:body.changed(k.blend(body.shape,[0],1000)),lambda r:self.window.replace_body(body,r))
        self.wait()
        self.assertEqual(self.window.document.bodies[0],body)
        self.assertEqual(self.warning_mock.call_count,1)
        self.assertTrue(self.window.tree.isEnabled())

    def test_mouse_sketch_creates_visible_sketch_on_plane(self):
        self.window.add_sketch()
        self.assertTrue(self.window.view.plane_pick)
        self.window.plane_picked('XZ')
        self.assertEqual(self.window.view.sketch_plane,'XZ')
        self.window.sketch_drawn('XZ','rectangle',0,0,20,10)
        self.wait()
        body=self.window.document.bodies[0]
        self.assertEqual((body.kind,body.plane),('sketch','XZ'))
        self.window.end_sketch()
        self.assertIsNone(self.window.view.sketch_plane)

    def test_shift_click_selects_tangent_chain_and_plain_click_one_edge(self):
        plain=k.box(40,30,20)
        vertical=[i for i,e in enumerate(plain.Edges()) if abs(e.startPoint().z-e.endPoint().z)>10]
        rounded=k.blend(plain,vertical,5)
        top=[i for i,e in enumerate(rounded.Edges()) if abs(e.startPoint().z-20)<1e-6 and abs(e.endPoint().z-20)<1e-6]
        body=Body('Zaokrąglona',rounded).prepared()
        self.window.document.commit([body]);self.window.refresh()
        self.window.edge_clicked(body.id,top[0],False)
        self.assertEqual(self.window.edges,{body.id:{top[0]}})
        self.window.edge_clicked(body.id,top[0],False,True)
        self.assertEqual(self.window.edges,{body.id:set(top)})

    def test_edge_selection_and_fillet_apply(self):
        self.add_box();body=self.window.document.bodies[0]
        self.window.start_blend('fillet')
        self.window.edge_clicked(body.id,0,False)
        self.window.edge_clicked(body.id,1,False)
        self.assertEqual(self.window.edges,{body.id:{1}})
        self.window.edge_clicked(body.id,2,True)
        self.assertEqual(self.window.edges,{body.id:{1,2}})
        self.window.blend_size.setValue(2)
        self.window.apply_blend();self.wait()
        self.assertLess(self.window.document.bodies[0].shape.Volume(),27000)
        self.assertFalse(self.window.edges)
        self.assertEqual(self.warning_mock.call_count,0)

    def test_save_and_open_through_native_actions(self):
        self.add_box()
        with tempfile.TemporaryDirectory() as directory:
            path=str(Path(directory)/'ui.rccadx')
            with patch('rccad.window.QFileDialog.getSaveFileName',return_value=(path,'')):
                self.window.save_project()
            self.wait();self.assertFalse(self.window.document.dirty)
            self.window.new_project();self.assertFalse(self.window.document.bodies)
            with patch('rccad.window.QFileDialog.getOpenFileName',return_value=(path,'')):
                self.window.open_project()
            self.wait();self.assertEqual(len(self.window.document.bodies),1)
            self.assertAlmostEqual(self.window.document.bodies[0].shape.Volume(),27000)

    def test_export_and_import_through_native_actions(self):
        self.add_box()
        with tempfile.TemporaryDirectory() as directory:
            path=str(Path(directory)/'ui.step')
            with patch('rccad.window.QFileDialog.getSaveFileName',return_value=(path,'')):
                self.window.export_model()
            self.wait();self.assertTrue(Path(path).exists())
            with patch('rccad.window.QFileDialog.getOpenFileName',return_value=(path,'')):
                self.window.import_model()
            self.wait();self.assertEqual(len(self.window.document.bodies),2)
            self.assertEqual(self.warning_mock.call_count,0)

    def test_projection_ray_and_visible_edge_picking(self):
        import numpy as np
        self.add_box();view=self.window.view;view.resize(800,600)
        body=self.window.document.bodies[0];view.fit_all()
        candidates=[]
        for points in body.mesh.edges.values():
            xy,_,_=view.project_points(points)
            midpoint=(xy[0]+xy[-1])/2
            ray=view._ray(*midpoint)
            self.assertIsNotNone(ray)
            if (hit:=view.nearest_edge(*midpoint)) is not None:
                candidates.append(hit)
        self.assertTrue(candidates)
        self.assertTrue(all(hit[0]==body.id and hit[1] in body.mesh.edges for hit in candidates))

    def test_graphical_buttons_create_body_and_choose_navigation(self):
        from PySide6.QtTest import QTest
        with patch('rccad.window.values_dialog', return_value={'x':20,'y':15,'z':10}):
            QTest.mouseClick(self.window.tool_buttons['Prostopadłościan'], Qt.LeftButton)
        self.wait()
        self.assertEqual(len(self.window.document.bodies), 1)
        self.assertAlmostEqual(self.window.document.bodies[0].shape.Volume(), 3000)
        for button, mode in zip(self.window.mouse_modes.buttons(), ['select','orbit','pan']):
            QTest.mouseClick(button, Qt.LeftButton)
            self.assertEqual(self.window.view.mouse_mode, mode)
        self.window.start_blend('fillet')
        self.assertEqual(self.window.view.mouse_mode, 'select')
        self.assertTrue(self.window.mouse_modes.buttons()[0].isChecked())

    def test_multiple_selection_toggle_needs_no_keyboard(self):
        self.add_box()
        first = self.window.document.bodies[0]
        second = Body('Druga', k.box(5,5,5)).prepared()
        self.window.add_prepared(second)
        self.window.refresh()
        self.window.multi_select.setChecked(True)
        self.assertTrue(self.window.view.multi_select)
        self.assertEqual(self.window.tree.selectionMode(), QAbstractItemView.MultiSelection)
        self.window.body_clicked(first.id, self.window.view.multi_select)
        self.assertEqual(set(self.window.selected), {first.id,second.id})
        self.window.multi_select.setChecked(False)
        self.assertFalse(self.window.view.multi_select)

    def test_visibility_is_reversible(self):
        self.add_box()
        item=self.window.tree.topLevelItem(0)
        item.setCheckState(0,Qt.Unchecked)
        self.assertFalse(self.window.document.bodies[0].visible)
        self.window.undo();self.assertTrue(self.window.document.bodies[0].visible)


if __name__=='__main__':unittest.main()
