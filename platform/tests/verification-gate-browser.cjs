const http = require('http');
const assert = require('assert/strict');
const fs = require('fs');
const os = require('os');
const path = require('path');
const {verify} = require('../../local-only/harness/react_layout_inspector.cjs');

(async () => {
 let value='before', writes=0, outside=0;
 const html=`<!doctype html><html><body><main style="display:flex;width:1000px;gap:20px"><section id="left" data-testid="left" style="width:700px"><form id="query"><input id="filter"><select id="kind"><option value="a">A</option><option value="b">B</option></select><button type="button" id="search">조회</button></form><table id="rows"><tbody><tr><td>before</td></tr></tbody></table></section><aside id="right" data-testid="right" style="width:280px"><input id="name"><button id="save">저장</button></aside></main><script>document.querySelector('#search').onclick=()=>document.querySelector('td').textContent=document.querySelector('#filter').value;document.querySelector('#save').onclick=()=>fetch('/api/item',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:'changed'})});setTimeout(()=>{const e=document.createElement('p');e.id='delayed';e.textContent='ready';document.body.append(e)},150);</script></body></html>`;
 const server=http.createServer(async(req,res)=>{
  if(req.url==='/api/item'){
   if(req.method==='PUT'){writes++;let body='';for await(const chunk of req)body+=chunk;value=JSON.parse(body).name;}
   res.setHeader('Content-Type','application/json');res.end(JSON.stringify({name:value,nested:{active:true}}));
  }else if(req.url==='/api/missing'){res.statusCode=404;res.end('{}');}
  else if(req.url==='/redirect'){res.statusCode=302;res.setHeader('Location','https://example.org');res.end();}
  else {res.setHeader('Content-Type','text/html');res.end(html);}
 });
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
 const base=`http://127.0.0.1:${server.address().port}`;
 const temp=fs.mkdtempSync(path.join(os.tmpdir(),'verification-browser-'));
 const criterion=(id,check)=>({id,requirement_id:'R1',description:id,check});
 const run=async(criteria,extra={})=>verify({contract:{criteria},preview_url:base,api_url:base,output_dir:temp,allow_browser_writes:false,allow_api_writes:false,...extra});
 try {
  const correct=await run([
   criterion('wider',{op:'layout',left:'#left',right:'#right',relation:'wider_than',ratio:2}),
   criterion('left',{op:'layout',left:'#left',right:'#right',relation:'left_of'}),
   criterion('above',{op:'layout',left:'#query',right:'#rows',relation:'above'}),
   criterion('query',{op:'scenario',steps:[{action:'fill',selector:'#filter',value:'bolt'},{action:'click',selector:'#search'},{action:'expect_text',selector:'#rows',value:'bolt'}]}),
   criterion('select',{op:'scenario',steps:[{action:'select',selector:'#kind',value:'b'},{action:'expect_value',selector:'#kind',value:'b'}]}),
   criterion('async',{op:'visible',selector:'#delayed'}),
   criterion('fresh',{op:'text',selector:'#rows',contains:'before'}),
   criterion('api',{op:'api',method:'GET',path:'/api/item',status:200,json_path:['nested','active'],equals:true}),
   criterion('404',{op:'api',method:'GET',path:'/api/missing',status:404}),
  ]);
  assert.equal(correct.success,true,JSON.stringify(correct));
  assert(correct.layout.length>0,'must capture rendered DOM');
  assert(fs.existsSync(correct.screenshot),'must capture real screenshot');
  fs.mkdirSync(path.join(__dirname,'../state/evidence'),{recursive:true});
  fs.copyFileSync(correct.screenshot,path.join(__dirname,'../state/evidence/verification-layout.png'));
  const exactValue=await run([criterion('exact-value',{op:'scenario',steps:[{action:'fill',selector:'#filter',value:'bolt-extra'},{action:'expect_value',selector:'#filter',value:'bolt'}]})]);
  assert.equal(exactValue.success,false,'an input prefix is not an exact value match');
  const wrong=await run([criterion('wrong',{op:'layout',left:'#right',right:'#left',relation:'wider_than',ratio:1})]);
  assert.equal(wrong.success,false,'table presence must not imply correct layout');
  assert.equal(wrong.results[0].status,'failed');
  const unknown=await run([criterion('manual',{op:'manual',reason:'Needs human judgement'})]);
  assert.equal(unknown.success,false);
  assert.equal(unknown.results[0].status,'unverified');
  assert.equal((await run([])).success,false,'empty verification is not success');
  const wrongValue=await run([criterion('api',{op:'api',method:'GET',path:'/api/item',status:200,json_path:['name'],equals:'NOT REAL'})],{preview_url:''});
  assert.equal(wrongValue.success,false,'HTTP 200 alone does not prove response');
  const blocked=await run([criterion('write',{op:'api',method:'PUT',path:'/api/item',status:200,body:{name:'changed'},json_path:['name'],equals:'changed'})]);
  assert.equal(blocked.success,false);assert.equal(writes,0);
  const persisted=await run([
   criterion('write',{op:'api',method:'PUT',path:'/api/item',status:200,body:{name:'changed'},json_path:['name'],equals:'changed'}),
   criterion('readback',{op:'api',method:'GET',path:'/api/item',status:200,json_path:['name'],equals:'changed'}),
  ],{allow_api_writes:true,preview_url:''});
  assert.equal(persisted.success,true,JSON.stringify(persisted));assert.equal(writes,1);
  const uiWrite=await run([criterion('write',{op:'scenario',steps:[{action:'click',selector:'#save'},{action:'expect_visible',selector:'#save'}]})]);
  assert.equal(uiWrite.success,false,'blocked browser mutation cannot count as verified');assert.equal(writes,1);
  const ambiguous=await run([criterion('ambiguous',{op:'visible',selector:'input'})]);
  assert.equal(ambiguous.success,false,'ambiguous selector must not choose arbitrary match');
  const redirect=await run([criterion('redirect',{op:'api',method:'GET',path:'/redirect',status:200})],{preview_url:''});
  assert.equal(redirect.success,false);
  const crossOrigin=await run([criterion('external',{op:'api',method:'GET',path:'//example.org/',status:200})]);
  assert.equal(crossOrigin.success,false);
  console.log('PASS: real geometry, query action, isolated API write/readback; wrong layout, manual, empty, wrong JSON, unsafe writes, ambiguous selectors and redirects rejected');
  const evidence={fixture:true,correct,wrong,unknown,wrongValue,blocked,persisted,uiWrite,ambiguous,redirect,crossOrigin};
  fs.mkdirSync(path.join(__dirname,'../state/evidence'),{recursive:true});
  fs.writeFileSync(path.join(__dirname,'../state/evidence/verification-gate-browser.json'),JSON.stringify(evidence,null,2));
 } finally {await new Promise(resolve=>server.close(resolve));fs.rmSync(temp,{recursive:true,force:true});}
})().catch(error=>{console.error(error);process.exitCode=1;});
