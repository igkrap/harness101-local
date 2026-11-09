const test=require('node:test'),assert=require('node:assert/strict');
const {classifyItemRequest}=require('./item_browser_driver.cjs');
const {verifySavedUpdate,cleanupSuccess,CASES}=require('./browser_item_update_ui.cjs');
const create=require('./browser_item_create_ui.cjs');
const base='http://127.0.0.1:45432';
for(const [method,url,permissions,wanted] of [
 ['PUT',base+'/api/items/11',{put:true},'allow'],['PUT',base+'/api/items/11',{},'forbidden'],
 ['PUT',base+'/api/items/0',{put:true},'forbidden'],['PUT',base+'/api/items/-1',{put:true},'forbidden'],
 ['PUT',base+'/api/items/9007199254740992',{put:true},'forbidden'],['PUT',base+'/api/items/11/other',{put:true},'forbidden'],
 ['PUT','http://127.0.0.1:8083/api/items/11',{put:true},'forbidden'],['PUT','https://example.com/api/items/11',{put:true},'forbidden'],
 ['POST',base+'/api/items',{post:true},'allow'],['DELETE',base+'/api/items/11',{put:true,post:true},'forbidden'],
 ['PUT',base+'/api/screens',{put:true},'forbidden'],['GET',base+'/api/auth/session',{},'allow'],
 ['GET','http://user@127.0.0.1:45432/api/auth/session',{},'forbidden']])test(method+' '+url+' '+JSON.stringify(permissions),()=>assert.equal(classifyItemRequest({method,url,resourceType:'fetch'},base,permissions),wanted));
const first={id:11,itemCode:'A',itemName:'품목',specification:'M8',unit:'EA',remark:'원본'},other={...first,id:29,itemCode:'B',remark:'보존'};
const values={itemCode:'U',itemName:'수정',specification:'M10',unit:'BOX',remark:'수정값'},saved={id:11,...values};
const clone=v=>JSON.parse(JSON.stringify(v));
test('saved response, all SQL fields and unchanged other row prove same-id update',()=>assert.deepEqual(verifySavedUpdate([first,other],saved,[saved,other],11,values),saved));
for(const fault of ['id','string-id','wrong-field','other-row','extra-row','missing-row'])test('rejects false update evidence '+fault,()=>{
 const body=clone(saved),rows=[clone(saved),clone(other)];
 if(fault==='id')body.id=12;if(fault==='string-id')body.id='11';if(fault==='wrong-field')body.unit='WRONG';if(fault==='other-row')rows[1].remark='changed';if(fault==='extra-row')rows.push({...saved,id:77});if(fault==='missing-row')rows.pop();
 assert.throws(()=>verifySavedUpdate([first,other],body,rows,11,values));
});
test('cleanup requires regression, owned resources and zero close errors',()=>{
 assert.equal(cleanupSuccess({success:true},{success:true},[]),true);
 for(const [a,b,e] of [[null,{success:true},[]],[{success:false},{success:true},[]],[{success:true},{success:false},[]],[{success:true},{success:true},['browser error']]])assert.equal(cleanupSuccess(a,b,e),false);
});
test('all ten old browser cases remain unchanged',()=>{assert.deepEqual(CASES.slice(0,10),create.CASES);assert.equal(new Set(CASES).size,14);});
const fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const oracle=require('./browser_item_update_ui.cjs');
async function fullScenario(options={}) {
 const directory=fs.mkdtempSync(path.join(os.tmpdir(),'item-ui-put-'));let rows=[],closed=false;
 const clone=v=>JSON.parse(JSON.stringify(v));
 class Runtime {async start(){return {base_url:base};}async rows(){return clone(rows);}async seedQueryFixture(){rows=clone([first,other]);return clone(rows);}async close(){closed=true;return {success:true};}}
 class Driver {
  constructor(){this.requests=[];this.runtimeErrors=[];this.forbiddenRequests=[];this.page={};this.disposed=false;}
  async start(){}async open(){}async queryAll(){this.rendered=clone(rows);return clone(rows);}
  async expectGrid(expected){assert.deepEqual(this.rendered,expected);}
  async select(code){this.draft=Object.fromEntries(Object.entries(rows.find(r=>r.itemCode===code)).filter(([k])=>k!=='id'));}
  async values(){return clone(this.draft);}async fill(values){this.draft=clone(values);}
  count(method){return this.requests.filter(r=>r.method===method).length;}
  async clickSave(){if(options.invalidRequest)this.requests.push({method:'PUT'});}
  async pause(){}async text(){return 'baseline';}
  async saveResponse(method,pathname){
   this.requests.push({method,path:pathname});const id=Number(pathname.split('/').pop()),draft=clone(this.draft);const duplicate=rows.some(r=>r.id!==id&&r.itemCode===draft.itemCode);
   if(!duplicate){const updated={id:options.changeId?id+1:id,...draft};rows=rows.map(r=>r.id===id?updated:r);this.rendered=clone(rows);}
   return {status:()=>duplicate?409:200,json:async()=>({id:options.changeId?id+1:id,...draft}),request:()=>({postDataJSON:()=>clone(draft)}),text:async()=>'{"error":"Conflict"}'};
  }
  async expectError(response){assert.equal(response.status(),409);}async screenshot(){}
  async close(){this.disposed=true;if(options.closeFailure)throw Error('browser cleanup failed');}
 }
 const log=console.log;console.log=()=>{};
 try {const result=await oracle.verify(directory,{Runtime,Driver,createVerify:async()=>({passed:true,cases:create.CASES,cleanup:{success:true}})});assert.deepEqual(JSON.parse(fs.readFileSync(path.join(directory,'result.json'))),result);return {result,closed};}
 finally{console.log=log;fs.rmSync(directory,{recursive:true,force:true});}
}
test('full browser-oracle logic with mock UI transport covers fourteen cases',async()=>{const s=await fullScenario();assert.equal(s.result.passed,true);assert.deepEqual(s.result.cases,CASES);assert.ok(s.closed);});
for(const key of ['changeId','invalidRequest','closeFailure'])test('mock flow fails closed for '+key,async()=>{const s=await fullScenario({[key]:true});assert.equal(s.result.passed,false);assert.ok(s.closed);assert.ok(!s.result.cases.includes(CASES.at(-1)));});
