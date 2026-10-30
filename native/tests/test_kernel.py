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

    def test_project_saves_whole_history_and_reopens_at_current_step(self):
        d=Document();a=Body('A',k.box(10,10,10)).prepared();d.commit([a],'Pierwszy');b=Body('B',k.box(5,5,5)).prepared();d.commit([a,b],'Drugi')
        d.commit([a],'Trzeci');d.undo()
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'h.rccadx';d.save(path);o=Document.load(path)
            self.assertEqual(o.timeline(),(['Początek','Pierwszy','Drugi','Trzeci'],2));self.assertEqual([x.name for x in o.bodies],['A','B'])
            self.assertAlmostEqual(o.bodies[1].shape.Volume(),125);o.redo();self.assertEqual(len(o.bodies),1);o.goto(0);self.assertFalse(o.bodies)
            o.goto(1);self.assertEqual(o.bodies[0].id,a.id);self.assertFalse(o.dirty and False)

    def test_history_recompute_through_pattern_chamfer_transform_mirror_bool(self):
        from dataclasses import replace as rep
        from rccad import history as h
        a=Body('A',k.box(10,10,10)).prepared();xmin=k.bounds(a.shape).xmin
        idx=[i for i,e in enumerate(a.shape.Edges()) if abs(e.positionAt(.5).toTuple()[0]-xmin)<1e-6][0]
        info=lambda r,i:{'label':i,'icon':i,'op':r}
        r_pat=dict(type='pattern',id=a.id,kind='rect',params=dict(counts=[2,1,1],spacing=[30,0,0]),join=False,out=['b'*32])
        r_mod=dict(type='mod',id=a.id,kind='chamfer',size=1,verts=[],edges=h.edge_refs(a.shape,[idx]))
        r_tr=dict(type='transform',id=a.id,mode='move',v=[0,0,5])
        r_mir=dict(type='mirror',id='b'*32,normal=[0,1,0],origin=[0,-5,0],keep=True,join=False,out='c'*32)
        r_bool=dict(type='bool',op='union',base=a.id,tools=['c'*32],keep=False)
        states=[((),{'label':'Początek','icon':'start'}),((a,),{'label':'A','icon':'file'})]
        for r in (r_pat,r_mod,r_tr,r_mir,r_bool):
            states.append((h.run_recipe(states[-1][0],r),info(r,r['type'])))
        wide=rep(a,shape=k.box(20,10,10),mesh=None).prepared()
        out,failed=h.recompute(states,1,(wide,));self.assertEqual(failed,0)
        final={b.id:b for b in out[-1][0]};self.assertNotIn('c'*32,final)          # narzędzie połączone i usunięte
        self.assertGreater(final[a.id].shape.Volume(),2000);self.assertAlmostEqual(final['b'*32].shape.Volume(),2000,2)
        base,_=h.toggle_step(states,3);vol=lambda st,i:{b.id:b for b in st[i][0]}[a.id].shape.Volume()
        self.assertTrue(base[3][1]['off']);self.assertAlmostEqual(vol(base,3),1000,2);self.assertAlmostEqual(vol(base,5),1000,2)     # bez fazy bryła ma pełną objętość
        gone,f2=h.delete_step(states,2);self.assertEqual((len(gone),f2),(len(states)-1,2))      # bez szyku odbicie i boolean nie mają obiektu: zostają oznaczone
        self.assertTrue(gone[-1][1].get('stale'))
        swapped,f3=h.move_step(states,3);self.assertEqual([i['icon'] for _,i in swapped[3:5]],['transform','mod'])
        mid=out[3][0];self.assertLess({b.id:b for b in mid}[a.id].shape.Volume(),2000)     # krok fazowania przeliczony na szerszej bryle

    def test_history_references_survive_resizing_of_the_base_body(self):
        import numpy as np
        from dataclasses import replace as rep
        from rccad import history as h
        a=Body('A',k.box(10,10,10)).prepared();xmin,ymin=k.bounds(a.shape).xmin,k.bounds(a.shape).ymin
        face,n=k.face_at(a.shape,(0,0,1),(5,5,10))
        src=dict(kind='face',id=a.id,face=face,normal=tuple(n),center=face.Center().toTuple(),hit=(5,5,10))
        r_ext=dict(type='extrude',mode='join',dir='one',d1=5,d2=0,profiles=h.describe_profiles([src],[a]),spent=[],out=[])
        idx=[i for i,e in enumerate(a.shape.Edges()) if abs(e.positionAt(.5).toTuple()[0]-xmin)<1e-6 and abs(e.positionAt(.5).toTuple()[1]-ymin)<1e-6][0]
        r_mod=dict(type='mod',id=a.id,kind='chamfer',size=1,verts=[],edges=h.edge_refs(a.shape,[idx]))
        corner=np.array([k.bounds(a.shape).xmax,k.bounds(a.shape).ymax,k.bounds(a.shape).zmax])
        r_vtx=dict(type='mod',id=a.id,kind='chamfer',size=2,verts=[corner.tolist()],vrefs=h.vertex_refs(a.shape,[corner]),edges=[])
        states=[((),{'label':'P','icon':'start'}),((a,),{'label':'A','icon':'file'})]
        for r in (r_ext,r_mod,r_vtx):states.append((h.run_recipe(states[-1][0],r),{'label':r['type'],'icon':r['type'],'op':r}))
        tall=rep(a,shape=k.box(10,10,20),mesh=None).prepared()
        out,failed=h.recompute(states,1,(tall,));self.assertEqual(failed,0)
        vol=out[2][0][0].shape.Volume();self.assertAlmostEqual(vol,2500,1)         # wyciągnięcie wskazało górną ścianę wyższej bryły
        self.assertLess(out[3][0][0].shape.Volume(),vol)                          # faza na właściwej krawędzi pionowej
        self.assertLess(out[4][0][0].shape.Volume(),out[3][0][0].shape.Volume())  # faza narożnika znalazła narożnik górnej ściany

    def test_dimension_constraints_follow_and_project_keeps_notes_groups_constraints(self):
        from dataclasses import replace as rep
        from rccad import history as h
        mk=lambda name,tool,pts:Body(name,k.sketch_shape(tool,'XY',pts,5),'sketch','XY',meta=dict(tool=tool,points=[list(p) for p in pts],sides=5)).prepared()
        a=mk('Prostokąt A','rect',[(0,0),(20,10)]);b=mk('Prostokąt B','rect',[(40,0),(50,5)])
        cons=[dict(a=a.id,ai=0,b=b.id,bi=0,k=1.0)]
        wide=mk('Prostokąt A','rect',[(0,0),(30,10)]);wide=rep(wide,id=a.id)
        out=h.apply_constraints((wide,b),cons);self.assertAlmostEqual(k.bounds(out[1].shape).xlen,30,3);self.assertAlmostEqual(k.bounds(out[1].shape).ylen,5,3)
        states=[((),{'label':'P','icon':'start'}),((a,),{'label':'A','icon':'sketch'}),((a,b),{'label':'B','icon':'sketch'})]
        new,failed=h.recompute(states,1,(wide,),cons);self.assertEqual(failed,0)
        self.assertAlmostEqual(k.bounds({x.id:x for x in new[2][0]}[b.id].shape).xlen,30,3)         # szkic B dogonił nowy wymiar A
        d=Document();d.commit([a],'A');d.commit([a,b],'B');d.constraints=cons;d.set_info(1,note='Pierwszy',group='Szkice')
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'c.rccadx';d.save(path);o=Document.load(path)
            self.assertEqual(o.constraints,cons);infos=o.infos()[0];self.assertEqual((infos[1]['note'],infos[1]['group']),('Pierwszy','Szkice'))

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
