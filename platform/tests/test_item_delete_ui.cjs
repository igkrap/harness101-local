const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const {confirmDelete}=require('./item_delete_confirmation.cjs');
const oracle=require('./browser_item_delete_ui.cjs'),prior=require('./browser_item_update_ui.cjs');
const {classifyItemRequest}=require('./item_browser_driver.cjs');
function confirmationEnvironment(mode,type='confirm') {
 const listeners=new Map(),state={accepted:0,dismissed:0,hidden:false};
 const dialog={count:async()=>mode==='custom'&&!state.hidden?1:0,getByRole:(role,{name})=>({count:async()=>name.test('확인')||name.test('취소')?1:0,click:async()=>{state.hidden=true;if(name.test('확인'))state.accepted++;else state.dismissed++;}}),waitFor:async()=>assert.ok(state.hidden)};
 const page={on:(event,fn)=>listeners.set(event,fn),off:event=>listeners.delete(event),waitForTimeout:async()=>{},locator:()=>dialog};
 const button={click:async()=>{if(mode==='native')listeners.get('dialog')({type:()=>type,message:()=> '정말 삭제?',accept:async()=>{state.accepted++;},dismiss:async()=>{state.dismissed++;}});}};
 return {page,button,state,listeners};
}
for(const mode of ['native','custom'])for(const accept of [true,false])test(mode+' confirmation '+accept,async()=>{const s=confirmationEnvironment(mode);const result=await confirmDelete(s.page,s.button,accept);assert.equal(result.mode,mode);assert.equal(s.state.accepted,accept?1:0);assert.equal(s.state.dismissed,accept?0:1);assert.equal(s.listeners.size,0);});
test('no confirmation is rejected and listener removed',async()=>{const s=confirmationEnvironment('none');await assert.rejects(confirmDelete(s.page,s.button,true));assert.equal(s.listeners.size,0);});
test('an alert cannot replace a cancellable confirmation',async()=>{const s=confirmationEnvironment('native','alert');await assert.rejects(confirmDelete(s.page,s.button,false));assert.equal(s.listeners.size,0);});
const a={id:1,itemCode:'A',itemName:'품목A',specification:'M8',unit:'EA',remark:'A'},b={...a,id:2,itemCode:'B',remark:'B'},clone=v=>JSON.parse(JSON.stringify(v));
test('exact selected-row deletion preserves every other value',()=>assert.deepEqual(oracle.verifyDeletedRows([a,b],[b],1),[b]));
for(const rows of [[],[a],[a,b],[{...b,remark:'changed'}]])test('rejects incorrect delete SQL '+JSON.stringify(rows),()=>assert.throws(()=>oracle.verifyDeletedRows([a,b],rows,1)));
const base='http://127.0.0.1:45432';
for(const [url,permissions,wanted] of [[base+'/api/items/1',{delete:true},'allow'],[base+'/api/items/1',{},'forbidden'],[base+'/api/items/0',{delete:true},'forbidden'],['http://127.0.0.1:8083/api/items/1',{delete:true},'forbidden'],[base+'/api/items/9007199254740992',{delete:true},'forbidden']])test('DELETE boundary '+url+' '+JSON.stringify(permissions),()=>assert.equal(classifyItemRequest({url,method:'DELETE',resourceType:'fetch'},base,permissions),wanted));
async function scenario(options={}) {
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'delete-ui-oracle-'));let rows=[],closed=false;
 class Runtime{async start(){return {base_url:base};}async rows(){return clone(rows);}async seedQueryFixture(){rows=clone([a,b]);return clone(rows);}async close(){closed=true;return {success:!options.cleanupFailure};}}
 class Driver {
  constructor(){this.requests=[];this.runtimeErrors=[];this.forbiddenRequests=[];this.base=base;this.opens=0;this.page={owner:this,waitForResponse:predicate=>new Promise(resolve=>{this.waiter=r=>{assert.ok(predicate(r));resolve(r);};})};this.editor={getAttribute:async()=>this.selected?'수정':'신규 등록'};
   this.button={count:async()=>1,isDisabled:async()=>options.enabledWithoutSelection?false:!this.selected,isEnabled:async()=>!!this.selected,waitFor:async()=>{}};
   this.screen={getByRole:()=>({getByRole:()=>this.button})};
  }
  async start(){}async open(){this.opens++;}async queryAll(){const current=options.reloadGhost&&this.opens>1?[a,b]:rows;this.rendered=clone(current);return clone(current);}
  async expectGrid(expected){assert.deepEqual(this.rendered,expected);}async select(code){this.selected=rows.find(r=>r.itemCode===code);this.draft=Object.fromEntries(Object.entries(this.selected).filter(([key])=>key!=='id'));}async values(){return clone(this.draft);}count(method){return this.requests.filter(r=>r.method===method).length;}
  async pause(){}async screenshot(){}async close(){if(options.closeFailure)throw Error('close failed');}
  async remove(accept){if(!accept&&!options.cancelDeletes)return {accepted:false,mode:'mock'};const id=this.selected.id;this.requests.push({method:'DELETE'});if(options.wrongTarget)rows=rows.filter(r=>r.id!==2);else if(!options.noPersist)rows=rows.filter(r=>r.id!==id);if(!options.staleGrid)this.rendered=clone(rows);if(!options.keepSelection)this.selected=null;
   const response={status:()=>options.wrongStatus?200:204,url:()=>base+'/api/items/'+id,request:()=>({method:()=> 'DELETE'})};if(this.waiter)this.waiter(response);return {accepted:true,mode:'mock'};
  }
 }
 const log=console.log;console.log=()=>{};
 try{const result=await oracle.verify(dir,{Runtime,Driver,confirm:async(page,button,accept)=>page.owner.remove(accept),updateVerify:async()=>({passed:!options.regressionFailure,cases:options.regressionCoverage?prior.CASES.slice(1):prior.CASES,cleanup:{success:true}})});assert.deepEqual(JSON.parse(fs.readFileSync(path.join(dir,'result.json'))),result);return {result,closed};}
 finally{console.log=log;fs.rmSync(dir,{recursive:true,force:true});}
}
test('full mock browser flow verifies all18 and cleanup',async()=>{const s=await scenario();assert.equal(s.result.passed,true);assert.deepEqual(s.result.cases,oracle.CASES);assert.ok(s.closed);});
for(const option of ['cancelDeletes','wrongTarget','noPersist','staleGrid','keepSelection','enabledWithoutSelection','wrongStatus','reloadGhost','closeFailure','cleanupFailure','regressionFailure','regressionCoverage'])test('full flow fails closed for '+option,async()=>{const s=await scenario({[option]:true});assert.equal(s.result.passed,false);assert.ok(!s.result.cases.includes('delete-ui-owned-resources-cleanup'));if(!option.startsWith('regression'))assert.ok(s.closed);});
