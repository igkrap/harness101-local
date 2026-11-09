const fs=require('fs'),os=require('os'),path=require('path'),http=require('http'),assert=require('assert/strict');
const cfg=JSON.parse(fs.readFileSync(path.join(os.homedir(),'.local/share/mlx-server/browser-check/runtime.json')));
const {chromium}=require(cfg.playwrightModule);
const guard=require('../../local-only/harness/native_ui_requirements.cjs');
let posts=0,queries=0;
const server=http.createServer((req,res)=>{
 if(req.url.startsWith('/api/')){if(req.method==='POST')posts++;else queries++;res.writeHead(200,{'Content-Type':'application/json'});res.end('[]');return;}
 const u=new URL(req.url,'http://localhost');const mode=u.searchParams.get('mode')||'good';
 const rowMode=['rows2','rows3','bloatedRows2'].includes(mode);
 res.writeHead(200,{'Content-Type':'text/html; charset=utf-8'});res.end(`<!doctype html><style>body{margin:0}#query{position:absolute;left:40px;top:60px;width:900px;height:${mode==='tall'?'200':mode==='bloatedRows2'?'260':rowMode?'160':'120'}px}input{height:28px}${rowMode?'#query input{height:20px;box-sizing:border-box}#query .row{height:60px}':''}${mode==='overflowquery'?'#query form{position:relative;top:100px}':''}#grid{position:absolute;left:40px;top:200px;width:900px;height:${mode==='short'?'265':mode==='overflowgrid'?'900':'760'}px}#editor{position:absolute;left:1050px;top:60px;width:300px;height:700px}</style>
 ${mode==='toolbar'?'<header style="position:absolute;top:0;right:0"><button type="submit" form="query-form">조회</button></header>':''}<section id="query"><form id="query-form">${rowMode?'<div class="row">':''}<label>이름<input required></label>${mode==='toolbar'?'':`<button type="submit">${mode==='combined'?'조회/추가':'조회'}</button>`}${rowMode?'<\/div><div class="row"><label>분류<input></label></div>':''}${mode==='rows3'?'<div class="row"><label>구분<input></label></div>':''}</form></section>
 <section id="grid">${mode==='emptygrid'?'결과 영역':'<table><tr><th>이름</th></tr><tr><td>품목</td></tr></table>'}</section>
 <aside id="editor">${mode==='empty'?'상세 정보: 선택한 항목이 표시됩니다.':`<form><label>이름<input ${mode==='staticeditor'?`oninput="this.value=''"`:mode==='readonlyeditor'?'readonly':''}></label><button type="submit">추가</button></form>`}</aside>
 <script>document.querySelector('#query-form').onsubmit=e=>{e.preventDefault();fetch('/api/inventory',{method:'${mode==='write'?'POST':'GET'}'});};document.querySelector('#editor form')?.addEventListener('submit',e=>e.preventDefault());</script>`);
});
(async()=>{await new Promise(r=>server.listen(0,'127.0.0.1',r));const base='http://127.0.0.1:'+server.address().port;const browser=await chromium.launch({executablePath:cfg.executablePath,headless:true});try{
 async function pageFor(mode){const page=await browser.newPage({viewport:{width:1440,height:1000}});const blocked=[];await page.route('**/*',route=>{const req=route.request();if(!['GET','HEAD','OPTIONS'].includes(req.method())){blocked.push({method:req.method(),path:req.url()});return route.abort();}return route.continue();});await page.goto(base+'/?mode='+mode,{waitUntil:'networkidle'});return{page,blocked};}
 const q={id:'C3',check:{op:'layout',relation:'above',left:'#query',right:'#grid'}};
 const g={id:'C4',check:{op:'layout',relation:'above',left:'#query',right:'#grid'}};
 const e={id:'C5',check:{op:'visible',selector:'#editor'}};
 const qr='좌측 상단 높이 2줄 정도의 조회 조건, 조회버튼 패널',gr='좌측 하단 나머지 높이의 조회결과 그리드',er='우측 신규 등록 및 수정 패널';
 let fixture=await pageFor('good');await guard.verify(fixture.page,q,qr,fixture.blocked);await guard.verify(fixture.page,g,gr,fixture.blocked);await guard.verify(fixture.page,{id:'C4',check:{op:'layout',relation:'left_of',left:'#grid',right:'#editor'}},gr,fixture.blocked);await guard.verify(fixture.page,e,er,fixture.blocked);assert.ok(queries>=1);assert.equal(posts,0);await fixture.page.close();
 for(const [mode,c,r] of [['empty',e,er],['tall',q,qr],['short',g,gr],['overflowgrid',g,gr],['combined',q,qr],['emptygrid',g,gr]]){fixture=await pageFor(mode);await assert.rejects(()=>guard.verify(fixture.page,c,r,fixture.blocked),undefined,'Must reject '+mode);await fixture.page.close();}
 fixture=await pageFor('short');await assert.rejects(()=>guard.verify(fixture.page,g,gr,fixture.blocked),err=>err.message.includes('ancestors=')&&err.message.includes('heightStyle')&&err.message.includes('actual_height=265')&&err.message.includes('allowed_height_min=704')&&err.message.includes('allowed_height_max=824')&&err.message.includes('recommended_height=776'));await fixture.page.close();
 fixture=await pageFor('tall');await assert.rejects(()=>guard.verify(fixture.page,q,qr,fixture.blocked),err=>err.message.includes('max=')&&err.message.includes('200'));await fixture.page.close();
 fixture=await pageFor('overflowquery');await assert.rejects(()=>guard.verify(fixture.page,q,qr,fixture.blocked),err=>err.message.includes('query_controls_overflow'));await fixture.page.close();
 fixture=await pageFor('toolbar');const before=queries;await guard.verify(fixture.page,q,qr,fixture.blocked);assert.ok(queries>before,'shared toolbar 조회 runs the query form');await fixture.page.close();
 fixture=await pageFor('rows2');await guard.verify(fixture.page,q,qr,fixture.blocked);await fixture.page.close();
 fixture=await pageFor('rows3');await assert.rejects(()=>guard.verify(fixture.page,q,qr,fixture.blocked),err=>err.message.includes('query_rows_exceeded'));await fixture.page.close();
 fixture=await pageFor('bloatedRows2');await assert.rejects(()=>guard.verify(fixture.page,q,qr,fixture.blocked),err=>err.message.includes('height_exceeded'));await fixture.page.close();
 for(const mode of ['staticeditor','readonlyeditor']){fixture=await pageFor(mode);await assert.rejects(()=>guard.verify(fixture.page,e,er,fixture.blocked),err=>/editor_input_not_/.test(err.message));await fixture.page.close();}
 fixture=await pageFor('good');await fixture.page.locator('#editor input').fill('기존 초안');await guard.verify(fixture.page,e,er,fixture.blocked);assert.equal(await fixture.page.locator('#editor input').inputValue(),'기존 초안');assert.equal(posts,0);await fixture.page.close();
 fixture=await pageFor('write');await assert.rejects(()=>guard.verify(fixture.page,q,qr,fixture.blocked));assert.ok(fixture.blocked.some(r=>r.method==='POST'));assert.equal(posts,0,'Query probe must never write actual data');await fixture.page.close();
 console.log('PASS: real query, editor controls and remaining grid height; placeholders/combined submit/tall query/short or empty grid rejected; POST intercepted before server');
}finally{await browser.close();await new Promise(r=>server.close(r));}})().catch(e=>{console.error(e);server.close();process.exitCode=1});
