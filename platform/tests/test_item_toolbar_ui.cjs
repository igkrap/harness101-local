const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const oracle=require('./browser_item_toolbar_ui.cjs'),prior=require('./browser_item_delete_ui.cjs');
const {FIELDS}=require('./item_browser_driver.cjs');
const clone=x=>JSON.parse(JSON.stringify(x)),empty=()=>Object.fromEntries(FIELDS.map(k=>[k,'']));
const a={id:1,itemCode:'A-100',itemName:'육각 볼트',specification:'M8x30',unit:'EA',remark:'도금 볼트'},b={id:2,itemCode:'B-200',itemName:'육각 너트',specification:'M10',unit:'BOX',remark:'스테인리스 너트'};
async function scenario(options={}){
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'toolbar-ui-oracle-'));let rows=[],closed=false,driverClosed=false;
 class Runtime{
  async start(){return {base_url:'http://127.0.0.1:45432'};}
  async rows(sql){return clone(sql.includes('POSITION(')?rows.filter(r=>r.itemCode.includes('-10')&&r.itemName.includes('볼')):rows);}
  async seedQueryFixture(){rows=clone([a,b]);return clone(rows);}
  async close(){closed=true;return {success:!options.cleanupFailure};}
 }
 class Driver{
  constructor(){this.requests=[];this.runtimeErrors=[];this.forbiddenRequests=[];this.page={};this.base='http://127.0.0.1:45432';this.draft=empty();this.selected=null;this.collapsed=false;this.conditions={};this.opens=0;}
  async start(){}async open(){this.opens++;this.selected=null;this.draft=empty();this.conditions={};}
  async queryAll(){this.rendered=clone(options.reloadGhost&&this.opens>1?[a,b]:rows);this.requests.push({method:'GET'});return clone(this.rendered);}
  async expectGrid(expected){assert.deepEqual(this.rendered,expected);}
  async select(code){this.selected=rows.find(r=>r.itemCode===code);this.draft=Object.fromEntries(FIELDS.map(k=>[k,this.selected[k]]));}
  async values(){return clone(this.draft);}async fill(v){this.draft=clone(v);}count(method){return this.requests.filter(r=>r.method===method).length;}
  async pause(){}async screenshot(){}async close(){driverClosed=true;if(options.closeFailure)throw Error('close failure');if(options.lateError)this.runtimeErrors.push('late error');if(options.forbidden)this.forbiddenRequests.push({path:'/api/other'});}
 }
 class Controls{
  constructor(driver){this.d=driver;}
  async layout(){assert.ok(!options.missingHeader,'Missing header action');}
  button(){return {isDisabled:async()=>!this.d.selected};}
  async conditions(code,name){this.d.conditions={code,name};if(options.autoQuery)this.d.requests.push({method:'GET'});}
  async collapse(){this.d.collapsed=true;}
  async revealed(){assert.equal(this.d.collapsed,false,'Editor must be revealed');}
  async requiredVisible(){assert.ok(!options.hiddenValidation);}
  async click(label){
   if(label==='신규'){const selected=this.d.selected;this.d.selected=null;if(!options.noReveal)this.d.collapsed=false;if(!options.staleNew||selected)this.d.draft=empty();}
   else if(label==='저장'){if(!options.noReveal)this.d.collapsed=false;if(options.invalidWrites)this.d.requests.push({method:'PUT'});}
  }
  async submit(method,pathname,label='저장'){
   if(method==='GET'){
    const {code,name}=this.d.conditions;let result=rows.filter(r=>(!code||r.itemCode.includes(code))&&(!name||r.itemName.includes(name)));
    if(options.wrongFilter&&code)result=rows;this.d.rendered=clone(result);this.d.requests.push({method});const params=new URLSearchParams();if(code)params.set('itemCode',code);if(name)params.set('itemName',name);
    return {url:()=>this.d.base+'/api/items?'+params,status:()=>200,json:async()=>clone(result)};
   }
   if(!options.noReveal)this.d.collapsed=false;
   if(options.repost&&method==='PUT')throw Error('Expected PUT received POST');
   const payload=clone(options.staleSave&&this.d.collapsed?this.d.selected:this.d.draft),body=Object.fromEntries(FIELDS.map(k=>[k,payload[k]]));
   let saved;
   if(method==='POST'){saved={id:options.reusedId?1:3,...body};rows.push(saved);this.d.selected=saved;}
   else{const id=Number(pathname.split('/').pop());saved={id,...body};rows=rows.map(r=>r.id===id?saved:r);this.d.selected=saved;if(options.corruptOther)rows[0].remark='changed';}
   this.d.requests.push({method});this.d.rendered=clone(options.staleGrid?[a,b]:rows);
   return {status:()=>method==='POST'?201:200,request:()=>({postDataJSON:()=>body}),json:async()=>clone(saved)};
  }
 }
 const original=console.log;console.log=()=>{};
 try{
  const result=await oracle.verify(dir,{Runtime,Driver,Controls,priorVerify:async()=>({passed:!options.regressionFailure,cases:options.regressionCoverage?prior.CASES.slice(1):prior.CASES,cleanup:{success:!options.regressionCleanup}})});
  assert.deepEqual(JSON.parse(fs.readFileSync(path.join(dir,'result.json'))),result);return {result,closed,driverClosed};
 }finally{console.log=original;fs.rmSync(dir,{recursive:true,force:true});}
}
test('all22 include unchanged prior18 and SQL/browser toolbar flow',async()=>{const s=await scenario();assert.equal(s.result.passed,true,s.result.failure);assert.deepEqual(s.result.cases,oracle.CASES);assert.ok(s.closed&&s.driverClosed);});
for(const option of ['missingHeader','autoQuery','wrongFilter','staleNew','noReveal','reusedId','repost','corruptOther','staleGrid','invalidWrites','hiddenValidation','reloadGhost','closeFailure','cleanupFailure','lateError','forbidden','regressionFailure','regressionCoverage','regressionCleanup'])test('rejects '+option+' and cleans owned resources',async()=>{const s=await scenario({[option]:true});assert.equal(s.result.passed,false,option);assert.ok(!s.result.cases.includes(oracle.NEW_CASES[3]));if(!option.startsWith('regression'))assert.ok(s.closed&&s.driverClosed);});
test('creation proof rejects nonpersisted and altered other rows',()=>{
 const fields=Object.fromEntries(FIELDS.map(k=>[k,a[k]])),saved={id:3,...fields};
 assert.throws(()=>oracle.verifyCreated([a,b],saved,[a,b],fields));assert.throws(()=>oracle.verifyCreated([a,b],saved,[{...a,remark:'changed'},b,saved],fields));
 assert.deepEqual(oracle.verifyCreated([a,b],saved,[a,b,saved],fields),saved);
});
