const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const oracle=require('./browser_item_api_update.cjs'),post=require('./browser_item_api_create.cjs');
const clone=v=>JSON.parse(JSON.stringify(v));
const response=(status,value)=>({status:()=>status,ok:()=>status>=200&&status<300,json:async()=>clone(value),text:async()=>JSON.stringify(value),headers:()=>({})});
async function scenario(options={}) {
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'put-oracle-'));let rows=[],closed=false,contexts=[],calls=[];
 class Runtime {
  async start(){return {base_url:'http://127.0.0.1:45432'};}
  async rows(sql){let found=rows;for(const [,value,col] of sql.matchAll(/POSITION\('([^']*)' IN (item_code|item_name)\) > 0/g))found=found.filter(r=>r[col==='item_code'?'itemCode':'itemName'].includes(value));return clone(found);}
  async seedQueryFixture(){rows=[{id:11,itemCode:'A-100',itemName:'육각 볼트',specification:'M8',unit:'EA',remark:'첫 행'},{id:29,itemCode:'B-200',itemName:'육각 너트',specification:'M10',unit:'BOX',remark:'보존 행'}];return clone(rows);}
  async close(){closed=true;return {success:!options.cleanupFailure};}
 }
 async function createContext(){
  const anonymous=contexts.length===1;
  const context={disposed:false,
   async get(address){const u=new URL(address);if(u.pathname==='/api/auth/session')return response(200,{authenticated:!anonymous,csrf:{token:'unit-token',headerName:'X-CSRF-TOKEN'}});const code=u.searchParams.get('itemCode')||'',name=u.searchParams.get('itemName')||'';return response(200,rows.filter(r=>r.itemCode.includes(code)&&r.itemName.includes(name)));},
   async put(address,opts){assert.equal(opts.maxRedirects,0);assert.equal(opts.timeout,10000);const id=Number(new URL(address).pathname.split('/').pop()),body=opts.data;calls.push(clone(body));
    if(anonymous&&!options.allowAnonymous)return response(401,{error:'auth'});
    if(opts.headers['X-CSRF-TOKEN']!=='unit-token'&&!options.ignoreCsrf)return response(403,{error:'csrf'});
    const existing=rows.find(r=>r.id===id);if(!existing)return response(options.upsertMissing?200:404,{error:'not found'});
    if(['itemCode','itemName'].some(k=>typeof body[k]!=='string'||!body[k].trim())&&!options.acceptInvalid)return response(400,{error:'required'});
    const code=String(body.itemCode??'').trim(),name=String(body.itemName??'').trim();
    if(rows.some(r=>r.id!==id&&r.itemCode===code)&&!options.allowDuplicate)return response(409,{error:'duplicate code'});
    const next={id:options.changeId?id+1:id,itemCode:options.noTrim?body.itemCode:code,itemName:name,specification:body.specification??null,unit:body.unit??null,remark:body.remark??null};
    if(!options.noPersist)rows=rows.map(r=>r.id===id?next:r);
    if(options.alterOther)rows[1].remark='corrupted';return response(200,next);
   },async dispose(){this.disposed=true;if(options.contextCleanupFailure)throw Error('dispose failed');}};
  contexts.push(context);return context;
 }
 const log=console.log;console.log=()=>{};
 try{
  const result=await oracle.verify(dir,{Runtime,createContext,postVerify:async()=>({passed:!options.regressionFailure,cases:options.regressionCoverage?post.CASES.slice(1):post.CASES,cleanup:{success:!options.regressionCleanup}})});
  assert.deepEqual(JSON.parse(fs.readFileSync(path.join(dir,'result.json'))),clone(result));return {result,closed,contexts,calls};
 }finally{console.log=log;fs.rmSync(dir,{recursive:true,force:true});}
}
test('PUT full flow preserves identity and row count and cleans all contexts',async()=>{const s=await scenario();assert.equal(s.result.passed,true);assert.deepEqual(s.result.cases,oracle.CASES);assert.equal(s.result.browserStarted,false);assert.ok(s.closed&&s.contexts.every(c=>c.disposed));assert.equal(s.calls.length,16);});
for(const option of ['changeId','noTrim','noPersist','alterOther','acceptInvalid','allowDuplicate','upsertMissing','allowAnonymous','ignoreCsrf','cleanupFailure','contextCleanupFailure','regressionFailure','regressionCoverage','regressionCleanup'])test('rejects '+option,async()=>{const s=await scenario({[option]:true});assert.equal(s.result.passed,false);assert.ok(!s.result.cases.includes('put-owned-resources-cleanup'));if(!option.startsWith('regression'))assert.equal(s.closed,true);});
for(const id of [0,-1,NaN,Number.MAX_SAFE_INTEGER+1,'1/../../api/screens'])test('rejects unsafe PUT id '+id,async()=>{let called=false;await assert.rejects(oracle.putItem({put:async()=>{called=true;}},'http://127.0.0.1:45432',[],id,{},{}));assert.equal(called,false);});
test('PUT helper rejects non-owned origin',async()=>{await assert.rejects(oracle.putItem({},'https://example.com',[],1,{},{}));});
