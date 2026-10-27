"""Browser regression: join a second extrusion, then cut its profile inwards."""
import json
import math
import os
from pathlib import Path
import shutil
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]
HTML=Path(os.environ.get('RCCAD_HTML',ROOT/'RCCAD.html'))
results=[]
with sync_playwright() as p:
    browser=p.chromium.launch(executable_path=os.environ.get('CHROMIUM_PATH') or shutil.which('chromium'),args=['--no-sandbox'])
    page=browser.new_page(viewport={'width':1440,'height':1000})
    errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    source=HTML.read_text().replace('syncPlanesButton();new ResizeObserver(resize).observe(vp);resize();','window.__test=code=>eval(code);syncPlanesButton();new ResizeObserver(resize).observe(vp);resize();')
    page.route('http://rccad.test/**',lambda r:r.fulfill(body=source,content_type='text/html'))
    page.goto('http://rccad.test/')
    def js(code):return page.evaluate('(code)=>__test(code)',code)
    def test(name,fn):
        try:results.append(dict(test=name,passed=True,detail=fn()))
        except Exception as e:results.append(dict(test=name,passed=False,error=str(e)))
    def setup(shape):
        js("""(()=>{projectApply(projectBlank());extrudeDirection.value='one';extrudeOperation.value='new';extrudeAmount=30;const base={type:'rect',plane:'XY',a:[0,0,0],b:[30,30,0]},post={type:'rect',plane:'XY',a:[5,5,30],b:[25,25,30]};extrudeSolids.push(extrusionToolMesh(base,solidForExtrusion(base,true)));extrudeAmount=10;extrudeOperation.value='join';extrudeOperation.dispatchEvent(new Event('change'));if(!applyExtrudeTools([extrusionToolMesh(post,solidForExtrusion(post,true))],'join'))throw Error('Join failed');sketchShapes.push(base,post,SHAPE);window.beforeStack=JSON.stringify(extrudeSolids);state.target=[15,15,40];state.az=0;state.el=Math.PI/2;state.dist=110;planesVisible=false;drawNow();})()""".replace('SHAPE',json.dumps(shape)))
        page.locator('#newSketch').click()
        position=[13,16,40] if shape.get('type')=='polyline' and len(shape.get('points',[]))>5 else [15,15,40]
        xy=js('project('+json.dumps(position)+').slice(0,2)')
        page.mouse.click(*xy)
        assert js('!!sketchFaceOffset&&Math.abs(sketchFaceOffset.offset-40)<1e-6')
        page.locator('#newSketch').click()
        page.locator('#extrudeTool').click()
        xy=js('project('+json.dumps(position)+').slice(0,2)')
        page.mouse.click(*xy)
        assert js('!!extrudeSelected'), 'No extrusion profile selected'
        assert js('extrusionOutline(extrudeSelected).every(p=>Math.abs(p[2]-40)<1e-5)'), 'Selected a hidden lower sketch'
    cases=[
        ('rectangle',dict(type='rect',plane='XY',a=[12,12,40],b=[18,18,40]),36),
        ('circle',dict(type='circle',plane='XY',a=[15,15,40],b=[18,15,40]),math.pi*9),
        ('ellipse',dict(type='ellipse',plane='XY',a=[15,15,40],b=[19,17,40]),math.pi*8),
        ('polygon',dict(type='polygon',plane='XY',a=[15,15,40],b=[19,15,40],sides=6),48*math.sin(math.pi/3)),
        ('slot',dict(type='slot',plane='XY',a=[12,15,40],b=[18,15,40],c=[15,17,40]),24+math.pi*4),
        ('three-point rectangle',dict(type='rect3',plane='XY',a=[12,12,40],b=[18,12,40],c=[15,18,40]),36),
        ('triangle',dict(type='polyline',plane='XY',a=[12,12,40],b=[18,12,40],points=[[12,12,40],[18,12,40],[15,18,40],[12,12,40]]),18),
        ('concave L profile',dict(type='polyline',plane='XY',a=[12,12,40],b=[18,12,40],points=[[12,12,40],[18,12,40],[18,14,40],[14,14,40],[14,18,40],[12,18,40],[12,12,40]]),20),
    ]
    for name,shape,area in cases:
        def cut_case(shape=shape,area=area):
            setup(shape)
            page.locator('#extrudeValue').fill('50')
            page.locator('#extrudeOperation').select_option('cut')
            amount=js('extrudeAmount')
            assert amount==50, {'unexpectedDistance':amount}
            bounds=js('solidBBox(solidForExtrusion(extrudeSelected,true))')
            assert bounds['mn'][2]<0 and 40<bounds['mx'][2]<40.1,bounds
            page.locator('#extrudeApply').click()
            r=js('({count:extrudeSolids.length,bad:solidBadEdges(extrudeSolids[0]),volume:solidVolumeQuick(extrudeSolids[0])})')
            assert r['count']==1 and r['bad']==0,r
            assert abs(r['volume']-(31000-area*40))<max(.01,area*40*.01),r
            js('undoSolids()');assert js('JSON.stringify(extrudeSolids)===window.beforeStack')
            js('redoSolids()');assert js('solidBadEdges(extrudeSolids[0])===0')
            return r
        test('UI cut after joined extrusion: '+name,cut_case)
    def nearest_profile():
        r=js("""(()=>{projectApply(projectBlank());sketchShapes.push({type:'rect',plane:'XY',a:[13,13,0],b:[17,17,0]},{type:'rect',plane:'XY',a:[5,5,40],b:[25,25,40]});state.target=[15,15,0];state.az=0;state.el=Math.PI/2;state.dist=110;const p=project([15,15,40]),sh=pickExtrusion(p[0],p[1]);return {z:extrusionOutline(sh).map(p=>p[2])}})()""")
        assert all(abs(z-40)<1e-6 for z in r['z']),r
        return r
    test('front profile wins over smaller hidden lower profile',nearest_profile)
    def no_intersection():
        setup(cases[0][1])
        page.locator('#extrudeOperation').select_option('cut')
        # Deliberately reverse the cut so it only touches the surface from outside.
        page.locator('#extrudeValue').fill('-10')
        before=js('solidHistory.length')
        ok=js('commitExtrusion()')
        assert not ok, 'A cut outside the body was reported as successful'
        assert js('JSON.stringify(extrudeSolids)===window.beforeStack')
        assert js('solidHistory.length')==before
        return True
    test('outward cut leaves geometry and history unchanged',no_intersection)
    def modes():
        setup(cases[0][1])
        page.locator('#extrudeDirection').select_option('two')
        page.locator('#extrudeValue').fill('8')
        page.locator('#extrudeSecond').fill('3')
        page.locator('#extrudeOperation').select_option('cut')
        r=js('({primary:extrudeAmount,secondary:Number(extrudeSecond.value),dir:extrudeDirVec(extrudeSelected)})')
        assert r['primary']==8 and r['secondary']==3 and r['dir'][2]==-1,r
        page.locator('#extrudeApply').click()
        assert abs(js('solidVolumeQuick(extrudeSolids[0])')-(31000-36*8))<.001
        return r
    test('two-sided cut preserves primary depth instead of swapping sides',modes)
    face_cases=[
        ('top','XY',[15,15,40],[18,15,40],[0,0,1],40,40),
        ('bottom','XY',[15,15,0],[18,15,0],[0,0,-1],0,40),
        ('front','XZ',[15,0,15],[18,0,15],[0,-1,0],0,30),
        ('back','XZ',[15,30,15],[18,30,15],[0,1,0],30,30),
        ('left','YZ',[0,15,15],[0,18,15],[-1,0,0],0,30),
        ('right','YZ',[30,15,15],[30,18,15],[1,0,0],30,30),
    ]
    for name,plane,a,b,normal,offset,depth in face_cases:
        def cut_face(plane=plane,a=a,b=b,normal=normal,offset=offset,depth=depth):
            setup(cases[0][1])
            shape=dict(type='circle',plane=plane,a=a,b=b)
            js("(()=>{const sh=SHAPE;registerFaceOutward({plane:sh.plane,offset:OFFSET,normal:NORMAL});extrudeSelected=sh;extrudeSelection=[sh];extrudeAmount=50;extrudeValue.value='50';})()".replace('SHAPE',json.dumps(shape)).replace('OFFSET',str(offset)).replace('NORMAL',json.dumps(normal)))
            page.locator('#extrudeOperation').select_option('cut')
            r=js('(()=>{const ok=commitExtrusion();return {ok,volume:solidVolumeQuick(extrudeSolids[0]),bad:solidBadEdges(extrudeSolids[0])}})()')
            assert r['ok'] and r['bad']==0 and abs(r['volume']-(31000-math.pi*9*depth))<math.pi*9*depth*.01,r
            return r
        test('positive cut goes inward on '+name+' face',cut_face)
    def rollback_invalid_mesh():
        setup(cases[0][1])
        r=js("""(()=>{const saved=booleanSolids,before=JSON.stringify(extrudeSolids),history=solidHistory.length;booleanSolids=(op,s,t)=>({...s,faces:s.faces.slice(1)});try{const ok=applyExtrudeTools([extrudeSolids[0]],'cut');return {ok,unchanged:JSON.stringify(extrudeSolids)===before,history:solidHistory.length===history};}finally{booleanSolids=saved;}})()""")
        assert not r['ok'] and r['unchanged'] and r['history'],r
        return r
    test('invalid Boolean mesh rolls back without an undo entry',rollback_invalid_mesh)
    results.append(dict(test='no runtime errors',passed=not errors,errors=errors))
    browser.close()
print(json.dumps(results,ensure_ascii=False,indent=2))
raise SystemExit(0 if all(r['passed'] for r in results) else 1)
