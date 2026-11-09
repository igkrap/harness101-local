const fs=require('fs'),path=require('path'),os=require('os'),http=require('http'),assert=require('assert/strict');
const cfg=JSON.parse(fs.readFileSync(path.join(os.homedir(),'.local/share/mlx-server/browser-check/runtime.json')));
const {chromium}=require(cfg.playwrightModule),check=require('../../local-only/harness/tests/framework_cases/registration.cjs');
let actualWrites=0;
const fields=[['name','이름'],['category','카테고리'],['quantity','수량'],['minQuantity','최소 수량'],['unitPrice','단가']];
function form(id,button,select=false){return `<form id="${id}">${fields.map(([key,label])=>`<label for="${id}_${key}">${label}</label>`+(select&&key==='category'?`<select id="${id}_${key}" name="${key}"><option value="">선택</option><option value="stock">재고</option></select>`:`<input id="${id}_${key}" name="${key}" value="${key==='name'?'원래 초안':key==='category'?'기존 분류':'0'}">`)).join('')}<button type="submit">${button}</button></form>`;}
const server=http.createServer((req,res)=>{
 if(!['GET','HEAD','OPTIONS'].includes(req.method)){actualWrites++;res.writeHead(500);res.end('real writes forbidden');return;}
 if(req.url.startsWith('/api/')){res.writeHead(200,{'Content-Type':'application/json'});res.end('[]');return;}
 const mode=new URL(req.url,'http://local').searchParams.get('mode')||'left';const right=mode!=='left';
 res.writeHead(200,{'Content-Type':'text/html; charset=utf-8'});res.end(`<!doctype html><nav aria-label="Side navigation"><button>재고</button></nav>${right&&mode!=='deadright'?'<form><label>이름<input id="query_name" value="조회 초안"></label><button>조회</button></form>':form('old','추가')}<aside data-testid="side-panel">${right?form('right','저장',mode==='selectright'):'상세 정보'}</aside><table><tbody></tbody></table><script>
 document.querySelectorAll('form').forEach(f=>f.onsubmit=async e=>{e.preventDefault();if('${mode}'==='deadright'&&f.id==='right')return;const body=Object.fromEntries(new FormData(f));for(const key of ['quantity','minQuantity','unitPrice'])body[key]=Number(body[key]);if('${mode}'==='badvalue')body.quantity=99;try{const response=await fetch('${mode}'==='wrongwrite'?'/api/else':'/api/inventory',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});if(!response.ok)return;const items=await(await fetch('/api/inventory')).json();document.querySelector('tbody').innerHTML=items.map(x=>'<tr><td>'+x.name+'</td></tr>').join('');}catch(e){}});
 </script>`);
});
(async()=>{await new Promise(r=>server.listen(0,'127.0.0.1',r));const browser=await chromium.launch({executablePath:cfg.executablePath,headless:true});try{
 const context=await browser.newContext();const page=await context.newPage();
 for(const mode of ['left','right','selectright','deadright','badvalue','wrongwrite']){
  await page.goto('http://127.0.0.1:'+server.address().port+'/?mode='+mode);
  if(['left','right','selectright'].includes(mode))await check({page,assert});else await assert.rejects(()=>check({page,assert}));
  assert.equal(actualWrites,0,'No method may write actual backend data');
  assert.equal(await page.locator('#'+(mode==='left'?'old':'right')+'_name').inputValue(),'원래 초안','Original page draft must remain unchanged');
  assert.equal(context.pages().length,1,'Isolated gate page must close after pass and failure');
 }
 console.log('PASS: left and right registration flows; dead editor, wrong values and wrong endpoint rejected; no real writes or draft mutation');
}finally{await browser.close();await new Promise(r=>server.close(r));}})().catch(e=>{console.error(e);server.close();process.exitCode=1});
