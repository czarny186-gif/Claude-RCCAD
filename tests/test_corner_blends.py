"""Regression for the black Y-shaped seams where three equal-radius fillets meet."""
import json
import os
from pathlib import Path
import shutil
from playwright.sync_api import sync_playwright
from PIL import Image

ROOT=Path(__file__).resolve().parents[1]
HTML=Path(os.environ.get('RCCAD_HTML',ROOT/'RCCAD.html'))
results=[]
with sync_playwright() as p:
    browser=p.chromium.launch(executable_path=os.environ.get('CHROMIUM_PATH') or shutil.which('chromium'),args=['--no-sandbox','--use-angle=swiftshader','--enable-unsafe-swiftshader'])
    page=browser.new_page(viewport={'width':1400,'height':1000})
    errors=[]
    page.on('pageerror',lambda e:errors.append(str(e)))
    page.on('dialog',lambda d:d.accept())
    source=HTML.read_text().replace('syncPlanesButton();new ResizeObserver(resize).observe(vp);resize();','window.__test=code=>eval(code);syncPlanesButton();new ResizeObserver(resize).observe(vp);resize();')
    page.route('http://rccad.test/**',lambda r:r.fulfill(body=source,content_type='text/html'))
    page.goto('http://rccad.test/?forcegl')
    def js(code):return page.evaluate('(code)=>__test(code)',code)
    def test(name,fn):
        try:results.append(dict(test=name,passed=True,detail=fn()))
        except Exception as e:results.append(dict(test=name,passed=False,error=str(e)))
    # Construct the old model through the unpatched cylinder-cutting kernel.
    js("""window.cornerFixture=(automatic=false)=>{const sh={type:'rect',plane:'XY',a:[0,0,0],b:[30,30,0]};extrudeAmount=30;extrudeDirection.value='one';extrudeOperation.value='new';let s=extrusionToolMesh(sh,solidForExtrusion(sh,true));const seeds=[],seen=new Set();for(let f=0;f<s.faces.length;f++)for(let k=0;k<s.faces[f].length;k++){const c=findEdgeChain(s,f,k);if(!c||c.keys.some(x=>seen.has(x)))continue;c.keys.forEach(x=>seen.add(x));seeds.push({mid:edgeKeyOf(s,f,k).mid,chain:c});}for(const e of seeds){const fk=findEdgeByMid(s,e.mid,e.chain),c=tryStraightRun(s,...fk,true),r=withModBudget(()=>(automatic?filletSurgery:filletSurgeryRaw)(s,c,3,'fillet'),1500);if(!r)throw Error('Fillet failed');s=r;}return s;};window.legacyCornerModel=window.cornerFixture();window.sharpCount=s=>s.feat.reduce((n,f)=>n+f.filter(Boolean).length,0);""")
    def geometry():
        r=js("""(()=>{const s=window.legacyCornerModel,t=performance.now(),r=withModBudget(()=>blendRoundedCorners(s),1500);window.fixedCornerModel=r;return {beforeSharp:window.sharpCount(s),afterSharp:window.sharpCount(r),bad:solidBadEdges(r),beforeVolume:solidVolumeQuick(s),afterVolume:solidVolumeQuick(r),corners:roundedCornerCandidates(r).length,ms:performance.now()-t}})()""")
        assert r['beforeSharp']>0 and r['afterSharp']==0 and r['bad']==0,r
        assert 0<r['afterVolume']<r['beforeVolume'] and r['corners']==8,r
        return r
    test('replace real cylinder creases with eight closed corner patches',geometry)
    def radius():
        r=js("""(()=>{const s=window.fixedCornerModel,cs=roundedCornerCandidates(s);let maxError=0,count=0;for(const {corner,n,r} of cs){const center=V3.sub(corner,V3.mul(n.reduce((a,b)=>V3.add(a,b),[0,0,0]),r));for(const p of s.vertices){const d=n.map(a=>V3.dot(a,V3.sub(corner,p)));if(d.every(x=>x>1e-5&&x<r-1e-5)){maxError=Math.max(maxError,Math.abs(V3.len(V3.sub(p,center))-r));count++;}}}return {maxError,count}})()""")
        assert r['count']>100 and r['maxError']<.04,r
        return r
    test('corner vertices approximate a radius 3 mm sphere',radius)
    def analytic_volume():
        r=js("(()=>{const expected=24**3+6*24**2*3+3*Math.PI*24*9+4*Math.PI*27/3,actual=solidVolumeQuick(window.fixedCornerModel);return {expected,actual,error:Math.abs(actual-expected)/expected}})()")
        assert r['error']<1e-4,r
        return r
    test('rounded box volume matches the analytic shape',analytic_volume)
    def rotated_legacy():
        r=js("(()=>{const s=transformClone(window.legacyCornerModel),base=transformClone(s);transformRotateShape(base,s,[20,15,30]);s.vertices=s.vertices.map(p=>[p[0]+123,p[1]-45,p[2]+7]);const r=withModBudget(()=>blendRoundedCorners(s),1500);return {sharp:window.sharpCount(r),bad:solidBadEdges(r),volume:solidVolumeQuick(r)}})()")
        assert r['sharp']==0 and r['bad']==0,r
        return r
    test('translated and rotated legacy corners are repaired',rotated_legacy)
    def automatic():
        r=js("""(()=>{const s=window.cornerFixture(true);return {bad:solidBadEdges(s),sharp:window.sharpCount(s),volume:solidVolumeQuick(s)}})()""")
        assert r['bad']==0 and r['sharp']==0,r
        return r
    test('successive edge operations automatically blend their corners',automatic)
    def unchanged_edges():
        r=js("""(()=>{extrudeAmount=30;const sh={type:'rect',plane:'XY',a:[0,0,0],b:[30,30,0]},s=extrusionToolMesh(sh,solidForExtrusion(sh,true)),c=findEdgeChain(s,0,0),ch=filletSurgery(s,c,3,'chamfer');return {cubeSharp:window.sharpCount(s),cubeSame:blendRoundedCorners(s)===s,chamferSharp:window.sharpCount(ch),chamferSame:blendRoundedCorners(ch)===ch}})()""")
        assert r['cubeSharp']==24 and r['cubeSame'] and r['chamferSharp']>0 and r['chamferSame'],r
        return r
    test('genuine box and chamfer edges remain visible and unchanged',unchanged_edges)
    def loaded_project():
        payload=js("JSON.stringify({...projectBlank(),app:'RCCAD',version:56,solids:[window.legacyCornerModel]})")
        js('projectApply(projectBlank())')
        page.locator('#fileInput').set_input_files({'name':'legacy.rccad.json','mimeType':'application/json','buffer':payload.encode()})
        page.wait_for_function('()=>__test("extrudeSolids.length===1")')
        r=js("({sharp:window.sharpCount(extrudeSolids[0]),bad:solidBadEdges(extrudeSolids[0]),notice:notice.textContent})")
        assert r['sharp']==0 and r['bad']==0 and 'wygładzono' in r['notice'],r
        return r
    test('opening an older project repairs the old corner seams',loaded_project)
    def draw_model(model,mode,label):
        js("(()=>{extrudeSolids.splice(0,extrudeSolids.length,window.MODEL);IO.fitView(extrudeSolids[0].vertices);planesVisible=false;activePlane=null;state.az=-.75;state.el=.55;const supported=glrInit()||!!GLR.gl;if(MODE==='canvas')GLR.ok=false;else if(supported)GLR.ok=true;drawNow();return supported})()".replace('MODEL',model).replace('MODE',json.dumps(mode)))
        page.wait_for_timeout(100)
        xy=js("project([1.27,1.27,28.73]).slice(0,2)")
        path=Path('/tmp')/('rccad-corner-'+label+'.png')
        page.screenshot(path=str(path))
        im=Image.open(path).convert('RGB');x,y=map(round,xy)
        black=sum(max(im.getpixel((a,b)))<45 for a in range(x-18,x+19) for b in range(y-18,y+19))
        return black
    def visual():
        before=draw_model('legacyCornerModel','canvas','before')
        after=draw_model('fixedCornerModel','canvas','after')
        assert before>10 and after==0,{'before':before,'after':after}
        return dict(beforeBlackPixels=before,afterBlackPixels=after)
    test('Canvas rendering removes the visible black Y at the corner',visual)
    def gl_visual():
        supported=js('glrInit() || !!GLR.gl')
        assert supported,'WebGL unavailable: this visual check did not execute'
        black=draw_model('fixedCornerModel','webgl','webgl-after')
        assert js('GLR.ok&&GLR.stats.frames>0'), 'WebGL renderer did not run'
        assert black==0,black
        return dict(blackPixels=black)
    test('WebGL rendering has no black corner seam',gl_visual)
    for fmt in ['binary','ascii','step']:
        def roundtrip(fmt=fmt):
            r=js("""(async()=>{const s=window.fixedCornerModel;let tris;if(FORMAT==='step'){const sets=IO.stepToTriangleSets(IO.stepText([s],'corner'),{});tris=sets.flat();}else{const ts=IO.triangles([s]),blob=FORMAT==='binary'?IO.stlBinary(ts):IO.stlAscii(ts,'corner');tris=IO.parseSTL(await blob.arrayBuffer());}const r=IO.trisToSolid(tris,1);return {bad:solidBadEdges(r),sharp:window.sharpCount(r),relativeVolumeError:Math.abs(solidVolumeQuick(r)-solidVolumeQuick(s))/solidVolumeQuick(s)}})()""".replace('FORMAT',json.dumps(fmt)))
            assert r['bad']==0 and r['sharp']==0 and r['relativeVolumeError']<1e-4,r
            return r
        test(fmt+' export/import preserves corrected geometry',roundtrip)
    results.append(dict(test='no browser runtime errors',passed=not errors,errors=errors))
    browser.close()
print(json.dumps(results,ensure_ascii=False,indent=2))
raise SystemExit(0 if all(r['passed'] for r in results) else 1)
