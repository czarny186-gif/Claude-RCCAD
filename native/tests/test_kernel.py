import math
from pathlib import Path
import tempfile
import unittest
from rccad import kernel as k
from rccad.document import Body, Document


class KernelTests(unittest.TestCase):
    def test_box_volume(self):
        self.assertAlmostEqual(k.box(10,20,30).Volume(),6000)

    def test_invalid_dimensions(self):
        for x in (0,-1,float('nan'),float('inf')):
            with self.subTest(x=x),self.assertRaises(k.CadError):k.box(x,20,30)

    def test_all_edges_fillet_true_spherical_corners(self):
        s=k.box(30,30,30);r=k.blend(s,range(12),3)
        exact=24**3+6*24**2*3+3*math.pi*24*9+4*math.pi*27/3
        self.assertAlmostEqual(r.Volume(),exact,places=5)
        self.assertTrue(r.isValid())
        self.assertEqual(len(k.display_mesh(r).edges),0)
        self.assertAlmostEqual(s.Volume(),27000)  # Input is never changed.

    def test_chamfer(self):
        s=k.box(30,30,30);r=k.blend(s,[0],2,'chamfer')
        self.assertTrue(r.isValid());self.assertLess(r.Volume(),s.Volume())

    def test_bad_fillet_does_not_change_shape(self):
        s=k.box(10,10,10)
        with self.assertRaises(k.CadError):k.blend(s,[0],1000)
        self.assertAlmostEqual(s.Volume(),1000)

    def test_empty_and_invalid_edge_selection(self):
        for indices in ([],[-1],[999]):
            with self.subTest(indices=indices),self.assertRaises(k.CadError):k.blend(k.box(10,10,10),indices,1)

    def test_through_hole(self):
        self.assertAlmostEqual(k.hole(k.box(30,30,30),4,15,15).Volume(),27000-math.pi*16*30,places=5)

    def test_blind_hole(self):
        self.assertAlmostEqual(k.hole(k.box(30,30,30),4,15,15,10).Volume(),27000-math.pi*16*10,places=5)

    def test_hole_outside_rejected(self):
        with self.assertRaises(k.CadError):k.hole(k.box(30,30,30),4,200,200)

    def test_hole_then_all_roundings(self):
        s=k.hole(k.box(40,40,30),6,20,20)
        r=k.blend(s,range(len(s.Edges())),2)
        self.assertTrue(r.isValid());self.assertLess(r.Volume(),s.Volume())
        self.assertEqual(len(k.display_mesh(r).edges),0)

    def test_boolean_operations(self):
        a=k.box(10,10,10);b=k.box(10,10,10).translate((5,0,0))
        for op,volume in [('union',1500),('subtract',500),('intersect',500)]:
            with self.subTest(op=op):self.assertAlmostEqual(k.boolean(op,a,[b]).Volume(),volume,places=5)

    def test_non_intersecting_intersection_rejected(self):
        with self.assertRaises(k.CadError):k.boolean('intersect',k.box(10,10,10),[k.box(10,10,10).translate((100,0,0))])

    def test_sketch_and_extrude_all_planes(self):
        for plane in ('XY','XZ','YZ'):
            with self.subTest(plane=plane):
                wire=k.sketch('rectangle',plane,20,10)
                self.assertAlmostEqual(k.extrude(wire,plane,5).Volume(),1000,places=5)

    def test_circle_polygon_and_symmetric_extrusion(self):
        wire=k.sketch('circle','XY',10)
        s=k.extrude(wire,'XY',10,True)
        self.assertAlmostEqual(s.Volume(),math.pi*25*10,places=5)
        self.assertAlmostEqual(s.BoundingBox().zmin,-5)
        self.assertGreater(k.extrude(k.sketch('polygon','XY',10,sides=6),'XY',10).Volume(),0)

    def test_sketch_from_drag_uses_workplane_axes(self):
        for plane in ('XY','XZ','YZ'):
            with self.subTest(plane=plane):
                args=k.sketch_from_drag('rectangle',plane,10,20,40,50)
                box=k.bounds(k.sketch(**args))
                c0,c1=k.to_world(plane,10,20),k.to_world(plane,40,50)
                for got,want in zip((box.xmin,box.ymin,box.zmin),map(min,zip(c0,c1))):self.assertAlmostEqual(got,want,places=5)
                for got,want in zip((box.xmax,box.ymax,box.zmax),map(max,zip(c0,c1))):self.assertAlmostEqual(got,want,places=5)
        circle=k.sketch_from_drag('circle','XY',5,5,8,9)
        self.assertAlmostEqual(circle['width'],10)
        with self.assertRaises(k.CadError):k.sketch_from_drag('rectangle','XY',0,0,0,5)

    def test_edge_chain_follows_tangent_outline(self):
        plain=k.box(40,30,20)
        self.assertEqual(k.edge_chain(plain,0),{0})
        vertical=[i for i,e in enumerate(plain.Edges()) if abs(e.startPoint().z-e.endPoint().z)>10]
        rounded=k.blend(plain,vertical,5)
        top=[i for i,e in enumerate(rounded.Edges()) if abs(e.startPoint().z-20)<1e-6 and abs(e.endPoint().z-20)<1e-6]
        self.assertEqual(len(top),8)
        self.assertEqual(k.edge_chain(rounded,top[0]),set(top))

    def test_transform_and_mirror(self):
        a=k.box(10,20,30);b=k.transform(a,(2,3,4),(20,30,40));c=k.mirror(a,'YZ')
        self.assertAlmostEqual(a.Volume(),b.Volume(),places=5)
        self.assertAlmostEqual(a.Volume(),c.Volume(),places=5)
        self.assertLessEqual(c.BoundingBox().xmax,1e-6)

    def test_step_and_brep_roundtrip(self):
        a=k.blend(k.box(30,30,30),range(12),3)
        with tempfile.TemporaryDirectory() as directory:
            for ext in ('step','brep'):
                with self.subTest(ext=ext):
                    path=Path(directory)/('model.'+ext);k.export_shapes([a],path)
                    imported=k.import_shapes(path)
                    self.assertEqual(len(imported),1)
                    self.assertAlmostEqual(imported[0][0].Volume(),a.Volume(),places=4)

    def test_stl_export_import(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'model.stl';k.export_shapes([k.box(10,10,10)],path)
            imported=k.import_shapes(path)
            self.assertEqual(imported[0][1],'mesh')
            self.assertGreater(len(k.display_mesh(imported[0][0]).triangles),0)

    def test_exact_measurements_and_blind_hole_after_tessellation(self):
        shape=k.box(30,30,30);k.display_mesh(shape)
        bounds=k.bounds(shape)
        self.assertAlmostEqual(bounds.xlen,30,places=6)
        self.assertAlmostEqual(bounds.zmax,30,places=6)
        self.assertAlmostEqual(k.hole(shape,4,15,15,10).Volume(),27000-math.pi*16*10,places=5)

    def test_dxf_sketch_roundtrip(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'profile.dxf'
            k.export_shapes([k.sketch('rectangle','XY',20,10)],path)
            imported=k.import_shapes(path)
            self.assertEqual(len(imported),1)
            self.assertEqual(imported[0][1],'sketch')
            self.assertAlmostEqual(k.extrude(imported[0][0],'XY',5).Volume(),1000,places=4)

    def test_wire_display_has_edges(self):
        mesh=k.display_mesh(k.sketch('rectangle','XY',20,10))
        self.assertEqual(len(mesh.edges),4)


class DocumentTests(unittest.TestCase):
    def test_history_and_saved_revision(self):
        d=Document();a=Body('A',k.box(10,10,10)).prepared();d.commit([a])
        self.assertTrue(d.dirty);d.undo();self.assertFalse(d.bodies);self.assertFalse(d.dirty)
        d.redo();self.assertEqual(d.bodies[0].id,a.id)
        with tempfile.TemporaryDirectory() as directory:
            d.save(Path(directory)/'a.rccadx');self.assertFalse(d.dirty)
            d.commit([]);self.assertTrue(d.dirty);d.undo();self.assertFalse(d.dirty)

    def test_project_roundtrip_solid_and_sketch(self):
        d=Document();d.commit([Body('Bryła ą',k.box(10,10,10)).prepared(),Body('Szkic',k.sketch('circle','XY',10),'sketch').prepared()])
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'a.rccadx';d.save(path);other=Document.load(path)
            self.assertEqual(other.bodies[0].name,'Bryła ą')
            self.assertEqual(other.bodies[0].id,d.bodies[0].id)
            self.assertEqual(other.bodies[1].kind,'sketch')
            self.assertFalse(other.dirty)
            self.assertAlmostEqual(other.bodies[0].shape.Volume(),1000)

    def test_corrupted_project(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'bad.rccadx';path.write_bytes(b'not a zip')
            with self.assertRaises(k.CadError):Document.load(path)

    def test_failed_save_preserves_previous_file(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'a.rccadx';d=Document();d.save(path);before=path.read_bytes()
            d.commit([Body('A',k.box(10,10,10)).prepared()])
            with patch('rccad.document.cq.exporters.export',side_effect=OSError('disk full')):
                with self.assertRaises(OSError):d.save(path)
            self.assertEqual(path.read_bytes(),before)
            self.assertTrue(d.dirty)


if __name__=='__main__':unittest.main()
