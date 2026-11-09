const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const oracle=require('./browser_item_api_delete.cjs'),update=require('./browser_item_api_update.cjs');
const clone=v=>JSON.parse(JSON.stringify(v));
const response=(status,value)=>({status:()=>status,ok:()=>status>=200&&status<300,json:async()=>clone(value),text:async()=>JSON.stringify(value),headers:()=>({})});
async function scenario(options={}) {
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'delete-oracle-'));let rows=[],closed=false,contexts=[],deletedCalls=[],ghost;
 class Runtime {
  async start(){return {base_url:'http://127.0.0.1:45432'};}
  async rows(sql){let result=rows;for(const [,value,col]of sql.matchAll(/POSITION\('([^']*)' IN (item_code|item_name)\) > 0/g))result=result.filter(r=>r[col==='item_code'?'itemCode':'itemName'].includes(value));return clone(result);}
  async seedQueryFixture(){rows=[{id:11,itemCode:'A-100',itemName:'육각 볼트',specification:'M8',unit:'EA',remark:'보존1'},{id:29,itemCode:'B-200',itemName:'육각 너트',specification:'M10',unit:'BOX',remark:'보존2'}];return clone(rows);}
  async close(){closed=true;return {success:!options.cleanupFailure};}
 }
 async function createContext(){const index=contexts.length;const anonymous=index===1;
  const context={disposed:false,
   async get(address){const u=new URL(address);if(u.pathname==='/api/auth/session')return response(200,{authenticated:!anonymous,csrf:{token:'unit-token',headerName:'X-CSRF-TOKEN'}});let found=options.reloginGhost&&index===2?[...rows,ghost]:rows;const code=u.searchParams.get('itemCode')||'',name=u.searchParams.get('itemName')||'';return response(200,found.filter(r=>r.itemCode.includes(code)&&r.itemName.includes(name)));},
   async post(address,opts){assert.equal(new URL(address).pathname,'/api/items');const saved={id:101,...opts.data};rows.push(saved);return response(201,saved);},
   async put(address,opts){const id=Number(new URL(address).pathname.split('/').pop());const saved={id,...opts.data};rows=rows.map(r=>r.id===id?saved:r);ghost=clone(saved);return response(200,saved);},
   async delete(address,opts){assert.equal(opts.timeout,10000);assert.equal(opts.maxRedirects,0);const id=Number(new URL(address).pathname.split('/').pop());deletedCalls.push({id,anonymous});
    if(anonymous&&!options.allowAnonymous)return response(401,{error:'auth'});if(opts.headers['X-CSRF-TOKEN']!=='unit-token'&&!options.ignoreCsrf)return response(403,{error:'csrf'});
    if(!rows.some(r=>r.id===id))return response(options.missing204?204:404,{error:'not found'});
    if(options.deleteAll)rows=[];else if(options.wrongTarget)rows=rows.filter(r=>r.id!==11);else if(!options.noPersist)rows=rows.filter(r=>r.id!==id);
    return response(options.wrongStatus?200:204,null);
   },async dispose(){this.disposed=true;if(options.contextCleanupFailure)throw Error('dispose failed');}};contexts.push(context);return context;
 }
 const log=console.log;console.log=()=>{};
 try{const result=await oracle.verify(dir,{Runtime,createContext,updateVerify:async()=>({passed:!options.regressionFailure,cases:options.regressionCoverage?update.CASES.slice(1):update.CASES,cleanup:{success:!options.regressionCleanup}})});assert.deepEqual(JSON.parse(fs.readFileSync(path.join(dir,'result.json'))),clone(result));return {result,closed,contexts,deletedCalls};}
 finally{console.log=log;fs.rmSync(dir,{recursive:true,force:true});}
}
test('delete lifecycle logic preserves other rows and all contexts are closed',async()=>{const s=await scenario();assert.equal(s.result.passed,true);assert.deepEqual(s.result.cases,oracle.CASES);assert.equal(s.deletedCalls.length,5);assert.ok(s.closed&&s.contexts.every(c=>c.disposed));assert.equal(s.result.browserStarted,false);});
for(const key of ['noPersist','deleteAll','wrongTarget','wrongStatus','missing204','ignoreCsrf','allowAnonymous','contextCleanupFailure','cleanupFailure','regressionFailure','regressionCoverage','regressionCleanup','reloginGhost'])test('rejects '+key,async()=>{const s=await scenario({[key]:true});assert.equal(s.result.passed,false);assert.ok(!s.result.cases.includes('delete-owned-resources-cleanup'));if(!key.startsWith('regression'))assert.equal(s.closed,true);});
for(const id of [0,-1,NaN,Number.MAX_SAFE_INTEGER+1,'1/../../api/screens'])test('unsafe DELETE id '+id,async()=>{let called=false;await assert.rejects(oracle.deleteItem({delete:async()=>{called=true;}},'http://127.0.0.1:45432',[],id,{}));assert.equal(called,false);});
test('nonowned DELETE origin rejected',async()=>assert.rejects(oracle.deleteItem({},'https://example.com',[],1,{})));
