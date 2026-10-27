"""Browser regression tests. Run: python tests/test_browser.py (requires Playwright and Chromium)."""
import json
import os
import shutil
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
HTML = Path(os.environ.get('RCCAD_HTML', ROOT / 'RCCAD.html'))
RESULTS = []

def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=os.environ.get('CHROMIUM_PATH') or shutil.which('chromium') or shutil.which('google-chrome'), args=['--no-sandbox'])
        page = browser.new_page(viewport={'width': 1440, 'height': 1000}, accept_downloads=True)
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        # Expose lexical internals only in the intercepted test response, never in the application.
        source = HTML.read_text().replace('syncPlanesButton();new ResizeObserver(resize).observe(vp);resize();',
            'window.__test = code => eval(code); syncPlanesButton();new ResizeObserver(resize).observe(vp);resize();')
        page.route('http://rccad.test/**', lambda route: route.fulfill(body=source, content_type='text/html'))
        page.goto('http://rccad.test/')
        page.wait_for_timeout(250)
        def check(name, code):
            try:
                result = page.evaluate('(code) => window.__test(code)', code)
                assert result is True, repr(result)
                RESULTS.append({'test':name,'passed':True})
            except Exception as e:
                RESULTS.append({'test':name,'passed':False,'error':str(e)})
        check('startup and canvas', 'state.w > 0 && state.h > 0 && !!canvas.getContext("2d")')
        check('SVG rotate 30 degrees', '''(() => {const s=IO.parseSVG('<svg xmlns="http://www.w3.org/2000/svg"><line x1="0" y1="0" x2="10" y2="0" transform="rotate(30)"/></svg>',1).shapes[0];return Math.abs(s.b[0]-Math.sqrt(75))<1e-6 && Math.abs(s.b[1]+5)<1e-6})()''')
        check('SVG skewX 30 degrees', '''(() => {const s=IO.parseSVG('<svg xmlns="http://www.w3.org/2000/svg"><line x1="0" y1="0" x2="0" y2="10" transform="skewX(30)"/></svg>',1).shapes[0];return Math.abs(s.b[0]-10/Math.sqrt(3))<1e-6})()''')
        check('SVG skewY 30 degrees', '''(() => {const s=IO.parseSVG('<svg xmlns="http://www.w3.org/2000/svg"><line x1="0" y1="0" x2="10" y2="0" transform="skewY(30)"/></svg>',1).shapes[0];return Math.abs(s.b[1]+10/Math.sqrt(3))<1e-6})()''')
        check('DXF arc scale and angles', '''(() => {const s=IO.parseDXF('0\\nSECTION\\n2\\nENTITIES\\n0\\nARC\\n10\\n10\\n20\\n20\\n40\\n5\\n50\\n0\\n51\\n60\\n0\\nENDSEC',2).shapes[0];return Math.abs(s.a[0]-30)<1e-6&&Math.abs(s.a[1]-40)<1e-6&&Math.abs(s.b[0]-25)<1e-6&&Math.abs(s.b[1]-(40+5*Math.sqrt(3)))<1e-6})()''')
        # Fixtures use the actual extrusion and mesh-building pipeline.
        check('rectangular extrusion volume', '''(() => {projectApply(projectBlank());const sh={type:'rect',plane:'XY',a:[0,0,0],b:[10,10,0]};extValue.value=10;extrudeDirection.value='one';extrudeOperation.value='new';window.testBox=extrusionToolMesh(sh,solidForExtrusion(sh,true));return Math.abs(solidVolumeQuick(window.testBox)-1000)<1e-5})()''')
        for op, vol in [('csgUnion',1500),('csgSubtract',500),('csgIntersect',500)]:
            check(op+' overlapping boxes', f'''(() => {{const a=window.testBox,b=JSON.parse(JSON.stringify(a));b.vertices=b.vertices.map(p=>[p[0]+5,p[1],p[2]]);const s=csgToSolid({op}(solidToCsg(a),solidToCsg(b)));return Math.abs(solidVolumeQuick(s)-{vol})<1e-4}})()''')
        for fmt in ['binary','ascii']:
            check('STL '+fmt+' round trip', '''(async () => {const ts=IO.triangles([window.testBox]);const data=await (FORMAT==='binary'?IO.stlBinary(ts):IO.stlAscii(ts,'box')).arrayBuffer();const s=IO.trisToSolid(IO.parseSTL(data),1);return !!s&&Math.abs(solidVolumeQuick(s)-1000)<1e-3&&IO.badEdgesOfSolid(s)===0})()'''.replace('FORMAT',json.dumps(fmt)))
        check('STEP round trip', '''(() => {const text=IO.stepText([window.testBox],'box'),sets=IO.stepToTriangleSets(text,{});return sets.length===1&&Math.abs(solidVolumeQuick(IO.trisToSolid(sets[0],1))-1000)<1e-3})()''')
        check('project save/load round trip', '''(() => {projectApply(projectBlank());sketchShapes.push({type:'rect',plane:'XY',a:[0,0,0],b:[10,10,0]});extrudeSolids.push(window.testBox);const data=JSON.parse(projectJson());projectApply(projectBlank());projectApply(data);return sketchShapes.length===1&&extrudeSolids.length===1&&Math.abs(solidVolumeQuick(extrudeSolids[0])-1000)<1e-4})()''')
        check('undo and redo', '''(() => {projectApply(projectBlank());pushStateHistory();extrudeSolids.push(window.testBox);undoSolids();if(extrudeSolids.length)return false;redoSolids();return extrudeSolids.length===1})()''')
        check('mirror preserves volume and reflects coordinates', '''(() => {const s=mirrorSolidCopy(window.testBox,[1,0,0],0);return s.vertices.every(p=>p[0]<=1e-6)&&Math.abs(solidVolumeQuick(s)-1000)<1e-4})()''')
        check('solid rotation preserves volume', '''(() => {const s=JSON.parse(JSON.stringify(window.testBox));transformRotateShape(window.testBox,s,[0,0,30]);return Math.abs(solidVolumeQuick(s)-1000)<1e-4})()''')
        check('SVG primitives', '''(() => {const r=IO.parseSVG('<svg xmlns="http://www.w3.org/2000/svg"><rect width="10" height="20"/><circle cx="30" cy="0" r="5"/><ellipse cx="50" cy="0" rx="5" ry="3"/><polyline points="0,0 5,5 10,0"/><polygon points="0,0 5,5 10,0"/><path d="M 0 0 L 10 0 L 10 10 Z"/></svg>',1);return r.count===6&&r.shapes.length>6})()''')
        for shape in ['line','construction','point','rect','centerRect','circle','ellipse','polygon','rect3','slot','arc']:
            check('sketch geometry '+shape, f'''(() => {{const v=sketchVertices({{type:{json.dumps(shape)},plane:'XY',a:[0,0,0],b:[10,0,0],c:[5,5,0],sides:6}});return v.length>0&&v.every(p=>p.every(Number.isFinite))}})()''')
        check('invalid SVG rejected', 'IO.parseSVG("<broken",1)===null')
        check('invalid STL rejected', 'IO.parseSTL(new ArrayBuffer(0)).length===0')
        check('invalid import scale rejected', '(async()=>!(await IO.importRun(new File([""],"bad.stl"),0)))()')
        check('circle from three points', "(() => {const s=circleThrough3([5,0,0],[0,5,0],[-5,0,0],'XY');return Math.hypot(...s.a)<1e-6&&Math.abs(dimAmount(s)-10)<1e-6})()")
        check('collinear circle rejected', "circleThrough3([0,0,0],[1,0,0],[2,0,0],'XY')===null")
        check('tangent circle', "(() => {const s=tangentCircleFromLines({type:'line',a:[0,0,0],b:[10,0,0]},{type:'line',a:[0,0,0],b:[0,10,0]},[3,3,0],'XY');return Math.abs(s.a[0]-3)<1e-6&&Math.abs(s.a[1]-3)<1e-6&&Math.abs(dimAmount(s)-6)<1e-6})()")
        check('diameter endpoint circle', "(() => {const s=makeSketchRecord('circle2','XY',[0,0,0],[10,0,0]);return s.a[0]===5&&dimAmount(s)===10})()")
        for kind in ['fillet','chamfer']:
            check(kind+' edge geometry', "(() => {const s=window.testBox,c=findEdgeChain(s,0,0);const r=filletSurgery(s,c,1,KIND);return !!r&&solidBadEdges(r)===0&&solidVolumeQuick(r)>900&&solidVolumeQuick(r)<1000})()".replace('KIND',json.dumps(kind)))
        for direction, bounds in [('one',[0,10]),('symmetric',[-5,5]),('two',[-4,10])]:
            check('extrusion direction '+direction, "(() => {extrudeAmount=10;extrudeDirection.value=DIR;extrudeSecond.value=4;return JSON.stringify(extrudeBounds())===BOUNDS})()".replace('DIR',json.dumps(direction)).replace('BOUNDS',json.dumps(json.dumps(bounds,separators=(',',':')))))
        check('trim between intersections', "(() => {projectApply(projectBlank());sketchShapes.push({type:'line',plane:'XY',a:[0,0,0],b:[10,0,0]},{type:'line',plane:'XY',a:[3,-5,0],b:[3,5,0]},{type:'line',plane:'XY',a:[7,-5,0],b:[7,5,0]});return trimShapeAt({si:0,at:5})&&sketchShapes.length===5&&sketchShapes.filter(s=>s.type==='trimPath').every(s=>s.b[0]<=3||s.a[0]>=5)})()")
        check('dimension edit rectangle', "(() => {projectApply(projectBlank());const s={type:'rect',plane:'XY',a:[0,0,0],b:[10,10,0]};sketchShapes.push(s);placeExistingDim(s,100,100);existingDimValue.value=20;existingDimSecondValue.value=30;applyExistingDim();return s.b[0]===20&&s.b[1]===30})()")
        for action in ['copy','cut','delete']:
            check('clipboard '+action, "(() => {projectApply(projectBlank());const s=JSON.parse(JSON.stringify(window.testBox));extrudeSolids.push(s);ctxSel=s;ACTION;if(EXPECT)return extrudeSolids.length===0;ctxPaste();return extrudeSolids.length===2&&Math.abs(solidVolumeQuick(extrudeSolids[1])-1000)<1e-5})()".replace('ACTION',{'copy':'ctxCopy()','cut':'ctxCut()','delete':'ctxDelete()'}[action]).replace('EXPECT','false' if action=='copy' else 'true'))
        for font in ['sans','bold','serif']:
            check('text outlines '+font, "(() => {const s=TXT.make('XY',[0,0,0],{str:'OABą',height:10,font:FONT,align:'left',angle:30});const rs=TXT.regions(s);return rs.length===5&&rs.some(r=>r.holes.length>0)&&s.contours.flat().every(p=>p.every(Number.isFinite))})()".replace('FONT',json.dumps(font)))
        check('hole extrusion volume', "(() => {extrudeAmount=10;extrudeDirection.value='one';const s={type:'region',plane:'XY',a:[0,0,0],b:[10,0,0],points:[[0,0,0],[10,0,0],[10,10,0],[0,10,0]],holes:[[[2,2,0],[8,2,0],[8,8,0],[2,8,0]]]};const m=extrusionToolMesh(s,solidForExtrusion(s,true));return Math.abs(solidVolumeQuick(m)-640)<1e-4&&solidBadEdges(m)===0})()")
        check('project load resets sketch history baseline', "(() => {projectApply(projectBlank());skhSettle();const d=projectBlank();d.shapes=[{type:'line',plane:'XY',a:[0,0,0],b:[10,0,0]}];projectApply(d);skhSettle();return solidHistory.length===0&&SKH.sig===JSON.stringify(sketchShapes)})()")
        # Real UI clicks exercise tool transitions and dialog handlers.
        for button in ['fileTool','newSketch','extrudeTool','boolTool','modTool','mirrorTool','moveTool','rotateTool','planesToggle']:
            try:
                page.locator('#'+button).click(timeout=2000)
                page.keyboard.press('Escape')
                RESULTS.append({'test':'UI '+button,'passed':True})
            except Exception as e: RESULTS.append({'test':'UI '+button,'passed':False,'error':str(e)})
        # Activate every sketch variant through its real UI handler.
        variants = page.locator('[data-shape]').evaluate_all('(nodes)=>[...new Set(nodes.map(n=>n.dataset.shape))]')
        for shape in variants:
            check('activate sketch tool '+shape, "(() => {projectApply(projectBlank());if(!sketchMode)toggleSketch();selectPlane(planes[0]);const b=document.querySelector('[data-shape=\"SHAPE\"]');b.click();return currentShape===SHAPE_JSON})()".replace('SHAPE_JSON',json.dumps(shape)).replace('SHAPE',shape))
        check('translation preview and cancellation', "(() => {projectApply(projectBlank());const s=JSON.parse(JSON.stringify(window.testBox));extrudeSolids.push(s);transformSelected=s;transformBackup=transformClone(s);transformMode='move';transformFields[0].value=3;transformFields[1].value=4;transformFields[2].value=5;transformApplyPreview();const ok=s.vertices.every((p,i)=>p.every((v,k)=>Math.abs(v-window.testBox.vertices[i][k]-[3,4,5][k])<1e-6));transformFinish(false);return ok&&JSON.stringify(s.vertices)===JSON.stringify(window.testBox.vertices)})()")
        check('sketch undo after dimension edit', "(() => {projectApply(projectBlank());const s={type:'rect',plane:'XY',a:[0,0,0],b:[10,10,0]};sketchShapes.push(s);skhSettle();placeExistingDim(s,100,100);existingDimValue.value=20;existingDimSecondValue.value=30;applyExistingDim();skhSettle();undoSolids();return sketchShapes[0].b[0]===10&&sketchShapes[0].b[1]===10})()")
        check('DXF line circle and ellipse scaling', "(() => {const r=IO.parseDXF('0\\nSECTION\\n2\\nENTITIES\\n0\\nLINE\\n10\\n1\\n20\\n2\\n11\\n3\\n21\\n4\\n0\\nCIRCLE\\n10\\n10\\n20\\n10\\n40\\n5\\n0\\nELLIPSE\\n10\\n20\\n20\\n20\\n11\\n5\\n21\\n0\\n40\\n0.5\\n0\\nENDSEC',2);return r.count===3&&r.shapes[0].a[0]===2&&dimAmount(r.shapes[1])===20})()")
        check('SVG elliptical arc rotation', "(() => {const path='M 0 0 A 20 10 30 0 1 30 10';const r=IO.parseSVG('<svg xmlns=\"http://www.w3.org/2000/svg\"><path d=\"'+path+'\"/></svg>',1);const el=document.createElementNS('http://www.w3.org/2000/svg','path');el.setAttribute('d',path);const p=el.getPointAtLength(el.getTotalLength()/2);const vertices=r.shapes.flatMap(s=>[s.a,s.b]);return vertices.every(p=>p.every(Number.isFinite))&&Math.min(...vertices.map(q=>Math.hypot(q[0]-p.x,q[1]+p.y)))<1})()")
        check('prepare download scene', "(() => {projectApply(projectBlank());extrudeSolids.push(window.testBox);return true})()")
        for fmt, suffix in [('step','.step'),('stlb','.stl'),('stla','.stl')]:
            try:
                page.evaluate('()=>window.__test("exportDialogOpen()")')
                page.locator('#exportFormat').select_option(fmt)
                page.locator('#exportName').fill('TestExport')
                with page.expect_download(timeout=10000) as download:
                    page.locator('#exportOk').click()
                d=download.value
                assert d.suggested_filename.endswith(suffix)
                assert Path(d.path()).stat().st_size>100
                RESULTS.append({'test':'UI download '+fmt,'passed':True})
            except Exception as e: RESULTS.append({'test':'UI download '+fmt,'passed':False,'error':str(e)})
        try:
            page.evaluate('()=>window.__test("saveDialogOpen()")')
            page.locator('#saveName').fill('BrowserTest')
            with page.expect_download(timeout=10000) as download:
                page.locator('#saveOk').click()
            data=json.loads(Path(download.value.path()).read_text())
            assert data['app']=='RCCAD' and len(data['solids'])==1 and data['name']=='BrowserTest'
            RESULTS.append({'test':'UI project download','passed':True})
        except Exception as e: RESULTS.append({'test':'UI project download','passed':False,'error':str(e)})
        page.evaluate('()=>window.__test("projectLeaveModes()")')
        RESULTS.append({'test':'no browser runtime errors','passed':not errors,'errors':errors})
        print(json.dumps(RESULTS,ensure_ascii=False,indent=2))
        browser.close()
    return all(r['passed'] for r in RESULTS)

if __name__=='__main__':
    raise SystemExit(0 if main() else 1)
