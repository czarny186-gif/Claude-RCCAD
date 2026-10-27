"""End-to-end edge selection, preview, apply, validity and responsiveness checks."""
import json
import os
from pathlib import Path
import shutil
import time
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]
HTML=Path(os.environ.get('RCCAD_HTML',ROOT/'RCCAD.html'))
results=[]
with sync_playwright() as p:
    browser=p.chromium.launch(executable_path=os.environ.get('CHROMIUM_PATH') or shutil.which('chromium'),args=['--no-sandbox'])
    page=browser.new_page(viewport={'width':1440,'height':1000})
    errors=[]
    page.on('pageerror',lambda e:errors.append(str(e)))
    source=HTML.read_text().replace('syncPlanesButton();new ResizeObserver(resize).observe(vp);resize();','window.__test=code=>eval(code);syncPlanesButton();new ResizeObserver(resize).observe(vp);resize();')
    page.route('http://rccad.test/**',lambda r:r.fulfill(body=source,content_type='text/html'))
    page.goto('http://rccad.test/')
    def js(code):return page.evaluate('(code)=>__test(code)',code)
    def test(name,fn):
        start=time.monotonic()
        try:
            detail=fn()
            results.append(dict(test=name,passed=True,ms=round((time.monotonic()-start)*1000),detail=detail))
        except Exception as e:results.append(dict(test=name,passed=False,error=str(e)))
    def setup(shape='rect',rotate=False):
        js("""(()=>{projectApply(projectBlank());const sh={type:SHAPE,plane:'XY',a:[0,0,0],b:[20,20,0],sides:6};extrudeAmount=20;extrudeDirection.value='one';extrudeOperation.value='new';const s=extrusionToolMesh(sh,solidForExtrusion(sh,true));if(ROTATE){const base=transformClone(s);transformRotateShape(base,s,[20,15,30]);}extrudeSolids.push(s);IO.fitView(s.vertices);window.original=JSON.stringify(extrudeSolids);window.volumeBefore=solidVolumeQuick(s);return true})()""".replace('SHAPE',json.dumps(shape)).replace('ROTATE',str(rotate).lower()))
    def select_visible():
        xy=js("""(()=>{const s=extrudeSolids[0];for(let f=0;f<s.faces.length;f++)for(let k=0;k<s.faces[f].length;k++){if(!s.feat[f][k])continue;const fc=s.faces[f],a=s.vertices[fc[k]],b=s.vertices[fc[(k+1)%fc.length]],p=project(V3.mul(V3.add(a,b),.5));if(p&&pickFeatureEdge(p[0],p[1]))return p.slice(0,2)}return null})()""")
        assert xy is not None
        page.mouse.click(*xy)
        assert js('modEdges.length')==1
    def apply_ui(shape,kind,rotate=False):
        setup(shape,rotate)
        page.locator('#modTool').click()
        # Select first, then change operation: this must preserve the selection.
        select_visible()
        page.locator('#modType').select_option(kind)
        assert js('modEdges.length')==1, 'Changing the operation lost the selected edge'
        page.locator('#modValue').fill('2')
        start=time.monotonic()
        page.locator('#modApply').click()
        page.wait_for_function('()=>__test("!modBusy")',timeout=5000)
        elapsed=time.monotonic()-start
        r=js('({volume:solidVolumeQuick(extrudeSolids[0]),bad:solidBadEdges(extrudeSolids[0]),before:window.volumeBefore,notice:notice.textContent,history:solidHistory.length})')
        assert r['bad']==0 and 0<r['volume']<r['before'],r
        assert r['history']==1,r
        assert elapsed<4,r
        js('undoSolids()');assert js('JSON.stringify(extrudeSolids)===window.original')
        js('redoSolids()');assert js('solidBadEdges(extrudeSolids[0])===0')
        page.keyboard.press('Escape')
        return dict(apply_ms=round(elapsed*1000),**r)
    for shape in ['rect','circle','polygon']:
        for kind in ['fillet','chamfer']:
            test('UI '+shape+' '+kind,lambda sh=shape,k=kind:apply_ui(sh,k))
    for kind in ['fillet','chamfer']:
        test('UI rotated box '+kind,lambda k=kind:apply_ui('rect',k,True))
    def multi(kind):
        setup()
        r=js("""(()=>{const s=extrudeSolids[0];modMode=true;modType=KIND;modVal.value=2;modEdges=[0,1].map(k=>({si:0,mid:edgeKeyOf(s,0,k).mid,chain:findEdgeChain(s,0,k)}));const t=performance.now();withModBudget(()=>applyModNow(),1500);return {ms:performance.now()-t,bad:solidBadEdges(extrudeSolids[0]),notice:notice.textContent,volume:solidVolumeQuick(extrudeSolids[0])}})()""".replace('KIND',json.dumps(kind)))
        assert r['bad']==0 and '(2)' in r['notice'],r
        assert r['ms']<2000,r
        page.keyboard.press('Escape')
        return r
    for kind in ['fillet','chamfer']:test('two adjacent edges '+kind,lambda k=kind:multi(k))
    def invalid():
        setup()
        r=js("""(()=>{const s=extrudeSolids[0];modMode=true;modType='fillet';modVal.value=1000;modEdges=[{si:0,mid:edgeKeyOf(s,0,0).mid,chain:findEdgeChain(s,0,0)}];const t=performance.now();withModBudget(()=>applyModNow(),1500);return {ms:performance.now()-t,unchanged:JSON.stringify(extrudeSolids)===window.original,history:solidHistory.length,notice:notice.textContent}})()""")
        assert r['unchanged'] and r['history']==0 and r['ms']<200,r
        page.keyboard.press('Escape')
        return r
    test('oversized radius rejects quickly without changing model',invalid)
    def expired():
        setup('circle')
        r=js("""(()=>{const s=extrudeSolids[0];modMode=true;modType='fillet';modVal.value=2;modEdges=[{si:0,mid:edgeKeyOf(s,0,0).mid,chain:findEdgeChain(s,0,0)}];withModBudget(()=>applyModNow(),-1);return {unchanged:JSON.stringify(extrudeSolids)===window.original,reset:modGeometryDeadline===Infinity,history:solidHistory.length,notice:notice.textContent}})()""")
        assert r['unchanged'] and r['reset'] and r['history']==0 and 'czas' in r['notice'],r
        page.keyboard.press('Escape')
        return r
    test('timeout rolls back and releases computation budget',expired)
    def preview():
        setup('circle')
        r=js("""(()=>{const s=extrudeSolids[0],c=findEdgeChain(s,0,0),t=performance.now();const p=buildEdgeTool(c,2,'fillet',true);return {ms:performance.now()-t,faces:p.faces.length,adj:!!p.adj,finite:p.vertices.every(p=>p.every(Number.isFinite))}})()""")
        assert r['finite'] and not r['adj'] and r['ms']<150,r
        return r
    test('lightweight circular edge preview',preview)
    def edge_matrix(shape,kind):
        setup(shape)
        r=js("""(()=>{const s=extrudeSolids[0],seen=new Set(),tests=[];for(let f=0;f<s.faces.length;f++)for(let k=0;k<s.faces[f].length;k++){if(!s.feat[f][k])continue;const c=findEdgeChain(s,f,k);if(!c||c.keys.some(x=>seen.has(x)))continue;c.keys.forEach(x=>seen.add(x));const t=performance.now(),r=withModBudget(()=>filletSurgery(s,c,2,KIND),1500);tests.push({ok:!!r&&solidBadEdges(r)===0&&solidVolumeQuick(r)<solidVolumeQuick(s),ms:performance.now()-t});}return tests})()""".replace('KIND',json.dumps(kind)))
        assert r and all(x['ok'] for x in r),r
        return {'edges':len(r),'max_ms':round(max(x['ms'] for x in r),2)}
    for shape in ['rect','polygon','circle']:
        for kind in ['fillet','chamfer']:
            test('all sharp edge chains '+shape+' '+kind,lambda sh=shape,k=kind:edge_matrix(sh,k))
    def rounded_neighbor(kind):
        setup()
        # A prior fillet leaves a long straight edge next to its small curved facets.
        # Selecting that straight edge must not follow the arc around the corner.
        info=js("""(()=>{const s=extrudeSolids[0],r=filletSurgery(s,findEdgeChain(s,0,0),2,'fillet');extrudeSolids[0]=r;IO.fitView(r.vertices);const mid=edgeKeyOf(s,0,1).mid,fk=findEdgeByMid(r,mid,findEdgeChain(s,0,1));window.selectedFixture={fk,mid};const c=findEdgeChain(r,...fk);return {straight:c.straight,points:c.verts.length}})()""")
        assert info['straight'] and info['points']==2,info
        page.locator('#modTool').click()
        xy=js("(()=>{const s=extrudeSolids[0],[f,k]=window.selectedFixture.fk,N=solidNormals(s),g=s.adj[f][k],d=V3.norm(V3.add(N[f],N[g]));state.el=Math.asin(d[2]);state.az=Math.atan2(d[0],d[1]);drawNow();return project(edgeKeyOf(s,f,k).mid).slice(0,2)})()")
        page.mouse.click(*xy)
        assert js('modEdges.length===1&&modEdges[0].chain.straight&&modEdges[0].chain.verts.length===2')
        page.locator('#modType').select_option(kind)
        page.locator('#modValue').fill('2')
        before=js('solidVolumeQuick(extrudeSolids[0])')
        page.locator('#modApply').click()
        page.wait_for_function('()=>__test("!modBusy")',timeout=5000)
        r=js('({notice:notice.textContent,bad:solidBadEdges(extrudeSolids[0]),volume:solidVolumeQuick(extrudeSolids[0])})')
        assert r['bad']==0 and r['volume']<before and '(1)' in r['notice'],r
        page.keyboard.press('Escape')
        return r
    for kind in ['fillet','chamfer']:
        test('select straight edge next to existing fillet '+kind,lambda k=kind:rounded_neighbor(k))
    def single_and_shift_selection():
        setup()
        page.locator('#modTool').click()
        points=js("""(()=>{const s=extrudeSolids[0],out=[],seen=new Set();for(let f=0;f<s.faces.length;f++)for(let k=0;k<s.faces[f].length;k++){if(!s.feat[f][k])continue;const p=project(edgeKeyOf(s,f,k).mid),h=p&&pickFeatureEdge(p[0],p[1]);if(!h)continue;const c=findEdgeChain(s,h.f,h.k),key=c.keys.slice().sort().join('|');if(seen.has(key))continue;seen.add(key);out.push(p.slice(0,2));}return out})()""")
        assert len(points)>=3
        page.mouse.click(*points[0]);assert js('modEdges.length')==1
        first=js('modEdges[0].chain.keys.slice().sort().join("|")')
        page.mouse.click(*points[1]);assert js('modEdges.length')==1
        assert js('modEdges[0].chain.keys.slice().sort().join("|")')!=first
        page.keyboard.down('Shift');page.mouse.click(*points[2]);page.keyboard.up('Shift')
        assert js('modEdges.length')==2
        page.keyboard.down('Shift');page.mouse.click(*points[2]);page.keyboard.up('Shift')
        assert js('modEdges.length')==1
        page.mouse.click(*points[1]);assert js('modEdges.length')==0
        page.keyboard.press('Escape')
        return True
    test('click selects one edge; Shift toggles extra edges',single_and_shift_selection)
    def hole_then_top_then_side(kind):
        # Reproduce the reported order, including an 80-segment circular hole.
        fixture=js("""(()=>{projectApply(projectBlank());const hole=Array.from({length:80},(_,i)=>[15+6*Math.cos(i*Math.PI/40),15+6*Math.sin(i*Math.PI/40),0]);const sh={type:'region',plane:'XY',a:[0,0,0],b:[30,0,0],points:[[0,0,0],[30,0,0],[30,30,0],[0,30,0]],holes:[hole]};extrudeAmount=30;extrudeDirection.value='one';extrudeOperation.value='new';let s=extrusionToolMesh(sh,solidForExtrusion(sh,true));
        const edgeAt=mid=>{for(let f=0;f<s.faces.length;f++)for(let k=0;k<s.faces[f].length;k++){if(!s.feat[f][k])continue;const a=s.vertices[s.faces[f][k]],b=s.vertices[s.faces[f][(k+1)%s.faces[f].length]],d=V3.sub(b,a),l=V3.dot(d,d),t=l?V3.dot(V3.sub(mid,a),d)/l:-1;if(t>=-1e-5&&t<=1+1e-5&&V3.len(V3.sub(mid,V3.add(a,V3.mul(d,t))))<1e-4)return [f,k];}return null;};
        let rim=null;for(let f=0;f<s.faces.length&&!rim;f++)for(let k=0;k<s.faces[f].length;k++){if(!s.feat[f][k])continue;const c=findEdgeChain(s,f,k);if(c?.closed&&c.verts.every(p=>Math.abs(p[2]-30)<1e-5)){rim=c;break;}}
        const r=withModBudget(()=>filletSurgery(s,rim,3,'fillet'),1500);if(!r)throw Error('Hole rim fillet failed');s=r;extrudeSolids.push(s);const stages=[];
        for(const mid of [[15,0,30],[30,15,30],[15,30,30],[0,15,30]]){const fk=edgeAt(mid);if(!fk)throw Error('Top edge not found');const c=tryStraightRun(s,...fk,true),v0=solidVolumeQuick(s);modMode=true;modType='fillet';modVal.value=3;modEdges=[{si:0,mid:edgeKeyOf(s,...fk).mid,chain:c}];withModBudget(()=>applyModNow(),1500);s=extrudeSolids[0];if(solidVolumeQuick(s)>=v0||solidBadEdges(s))throw Error(JSON.stringify({mid,faces:s.faces.length,notice:notice.textContent}));stages.push(s.faces.length);}
        window.fixtureEdgeAt=mid=>{s=extrudeSolids[0];return edgeAt(mid);};window.fixtureSide=edgeAt([0,0,15]);if(!window.fixtureSide)throw Error('Side edge not found');window.sideBefore=JSON.stringify(extrudeSolids);window.sideVolumeBefore=solidVolumeQuick(s);
        window.shaftDistance=()=>{const eye=[15,15,15],dir=V3.norm([.812,.583,0]),hits=meshFacePts(extrudeSolids[0]).map(f=>rayPoly(eye,dir,f,V3.norm(polyNormal(f)))).filter(x=>x!==null);return Math.min(...hits);};window.shaftBefore=window.shaftDistance();
        modMode=false;modReset();modSyncUi();IO.fitView(s.vertices);return {stages,shaft:window.shaftBefore};})()""")
        assert 5.9<fixture['shaft']<6.1,fixture
        page.locator('#modTool').click()
        xy=js("""(()=>{const s=extrudeSolids[0],[f,k]=window.fixtureSide,N=solidNormals(s),g=s.adj[f][k],d=V3.norm(V3.add(V3.add(N[f],N[g]),[0,0,.6]));state.el=Math.asin(d[2]);state.az=Math.atan2(d[0],d[1]);drawNow();return project(edgeKeyOf(s,f,k).mid).slice(0,2)})()""")
        page.mouse.click(*xy)
        assert js('modEdges.length===1&&modEdges[0].chain.straight')
        page.locator('#modType').select_option(kind)
        page.locator('#modValue').fill('3')
        start=time.monotonic()
        page.locator('#modApply').click()
        page.wait_for_function('()=>__test("!modBusy")',timeout=8000)
        r=js("""({bad:solidBadEdges(extrudeSolids[0]),volume:solidVolumeQuick(extrudeSolids[0]),before:window.sideVolumeBefore,shaft:window.shaftDistance(),shaftBefore:window.shaftBefore,notice:notice.textContent,axisHits:meshFacePts(extrudeSolids[0]).filter(f=>rayPoly([15,15,-1],[0,0,1],f,V3.norm(polyNormal(f)))!==null).length})""")
        assert r['bad']==0 and r['volume']<r['before'] and '(1)' in r['notice'],r
        assert r['axisHits']==0 and abs(r['shaft']-r['shaftBefore'])<1e-4,r
        js('undoSolids()');assert js('JSON.stringify(extrudeSolids)===window.sideBefore')
        js('redoSolids()');assert js('solidBadEdges(extrudeSolids[0])===0')
        other_sides=js("""(()=>{const results=[];for(const mid of [[30,0,15],[30,30,15],[0,30,15]]){const s=extrudeSolids[0],fk=window.fixtureEdgeAt(mid);if(!fk)throw Error('Next side not found');const c=tryStraightRun(s,...fk,true),before=solidVolumeQuick(s);modMode=true;modType=KIND;modVal.value=3;modEdges=[{si:0,mid:edgeKeyOf(s,...fk).mid,chain:c}];withModBudget(()=>applyModNow(),1500);const r=extrudeSolids[0];if(solidBadEdges(r)||solidVolumeQuick(r)>=before)throw Error(notice.textContent);results.push(r.faces.length);}return results})()""".replace('KIND',json.dumps(kind)))
        assert len(other_sides)==3
        assert js('Math.abs(window.shaftDistance()-window.shaftBefore)<1e-4')
        page.keyboard.press('Escape')
        return dict(apply_ms=round((time.monotonic()-start)*1000),other_side_faces=other_sides,**r)
    for kind in ['fillet','chamfer']:
        test('hole rim, four top fillets, then side '+kind,lambda k=kind:hole_then_top_then_side(k))
    def disconnected_caps():
        r=js("""(()=>{const square=x=>[[x,0,0],[x+1,0,0],[x+1,1,0],[x,1,0]],segments=[];for(const loop of [square(0),square(3)])for(let i=0;i<4;i++)segments.push([loop[i],loop[(i+1)%4]]);return edgeCutBoundary(segments,[0,0,1])===null})()""")
        assert r
        return r
    test('disconnected cut loops never filled as one cap',disconnected_caps)
    results.append(dict(test='no runtime errors',passed=not errors,errors=errors))
    browser.close()
print(json.dumps(results,ensure_ascii=False,indent=2))
raise SystemExit(0 if all(r['passed'] for r in results) else 1)
