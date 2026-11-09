// DELETE-only stage, retaining the unchanged twelve-case GET/POST/PUT oracle.
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const updateOracle=require('./browser_item_api_update.cjs');
const postOracle=require('./browser_item_api_create.cjs');
const {trustedRequest,protectedResponse,within}=require('./browser_item_api_query.cjs');
const {canonicalRows,querySql}=require('./browser_item_query.cjs');
const {ItemRuntime}=require('./item_crud_runtime_client.cjs');
const {ensureAuthenticated}=require('../../local-only/harness/trusted_auth.cjs');
const DELETE_CASES=['delete-target-only-and-query-sql','delete-missing-id-preserves-data','delete-session-csrf-and-relogin-persistence','delete-owned-resources-cleanup'];
const CASES=[...updateOracle.CASES,...DELETE_CASES];
async function createApiContext(base) {
 const config=JSON.parse(fs.readFileSync(path.join(process.env.HOME,'.local/share/mlx-server/browser-check/runtime.json'),'utf8'));
 return require(config.playwrightModule).request.newContext({baseURL:base,timeout:10000});
}
async function boundedContext(make,base) {
 let accepted=true;const pending=Promise.resolve().then(()=>make(base));pending.then(c=>{if(!accepted)return c.dispose().catch(()=>{});},()=>{});
 try{return await within(pending,15000,'API context startup exceeded 15 seconds');}catch(e){accepted=false;throw e;}
}
async function dispose(context){return within(Promise.resolve().then(()=>context.dispose()),10000,'API context cleanup exceeded 10 seconds');}
async function deleteItem(context,base,requests,id,headers,actor='authenticated') {
 trustedRequest(context,base,[]);assert.ok(Number.isSafeInteger(id)&&id>0,'DELETE requires a positive safe numeric id');
 const entry={actor,method:'DELETE',path:'/api/items/'+id};requests.push(entry);
 const response=await context.delete(new URL(entry.path,base).toString(),{headers,timeout:10000,maxRedirects:0});entry.status=response.status();return response;
}
async function verify(output,infrastructure={}) {
 const out=path.resolve(output);fs.mkdirSync(out,{recursive:true});const cases=[],requests=[],sqlProofs=[],errors=[];
 const Runtime=infrastructure.Runtime||ItemRuntime,make=infrastructure.createContext||createApiContext;
 let regression,runtime,backend,context,anonymous,relogin,result;let ownedCleanup={success:true,started:false};
 const passed=name=>{assert.ok(DELETE_CASES.includes(name));cases.push(name);console.log('ITEM_API_DELETE_OK: '+name);};
 try {
  regression=await (infrastructure.updateVerify||updateOracle.verify)(path.join(out,'update-regression'));
  assert.ok(regression?.passed===true&&regression?.cleanup?.success===true,'Unchanged GET/POST/PUT regression and cleanup must pass');
  assert.deepEqual([...regression.cases].sort(),[...updateOracle.CASES].sort(),'Exact regression case coverage required');cases.push(...regression.cases);
  runtime=new Runtime(path.join(out,'runtime'));backend=await runtime.start();
  async function db(label,conditions){const rows=canonicalRows(await runtime.rows(querySql(conditions)));sqlProofs.push({label,conditions,rows});return rows;}
  assert.deepEqual(await db('fresh-delete-database'),[]);const seeded=canonicalRows(await runtime.seedQueryFixture());assert.equal(seeded.length,2);assert.deepEqual(await db('fixed-delete-fixture'),seeded);
  context=await boundedContext(make,backend.base_url);const request=trustedRequest(context,backend.base_url,requests);
  assert.equal(await ensureAuthenticated(request,backend.base_url,{localProxy:true}),true);
  const session=await(await request.get(new URL('/api/auth/session',backend.base_url).toString())).json();assert.ok(session.authenticated&&session.csrf?.token&&session.csrf.headerName==='X-CSRF-TOKEN');
  const headers={[session.csrf.headerName]:session.csrf.token};
  const initial={itemCode:'LIFE-DELETE-300',itemName:'삭제 대상 품목',specification:'M12',unit:'EA',remark:'삭제 전 생성'};
  const createdResponse=await postOracle.postItem(context,backend.base_url,requests,initial,headers);assert.ok([200,201].includes(createdResponse.status()));
  const created=postOracle.savedRecord(await createdResponse.json());assert.deepEqual({...created,id:undefined},{...initial,id:undefined});assert.ok(!seeded.some(r=>r.id===created.id));assert.deepEqual(await db('created-delete-target'),[...seeded,created].sort((a,b)=>a.id-b.id));
  const changed={...initial,itemCode:'LIFE-UPDATED-300',itemName:'수정 후 삭제 대상',remark:'삭제 전 수정 보존'};
  const updatedResponse=await updateOracle.putItem(context,backend.base_url,requests,created.id,changed,headers);assert.equal(updatedResponse.status(),200);
  const updated=postOracle.savedRecord(await updatedResponse.json());assert.equal(updated.id,created.id);assert.deepEqual({...updated,id:undefined},{...changed,id:undefined});
  const beforeDelete=[...seeded,updated].sort((a,b)=>a.id-b.id);assert.deepEqual(await db('updated-delete-target'),beforeDelete);
  anonymous=await boundedContext(make,backend.base_url);const anon=trustedRequest(anonymous,backend.base_url,requests,'anonymous');
  const anonSession=await(await anon.get(new URL('/api/auth/session',backend.base_url).toString())).json();assert.equal(anonSession.authenticated,false);assert.ok(anonSession.csrf?.token&&anonSession.csrf.headerName==='X-CSRF-TOKEN');
  const denied=await deleteItem(anonymous,backend.base_url,requests,updated.id,{[anonSession.csrf.headerName]:anonSession.csrf.token},'anonymous');assert.ok(protectedResponse(denied,backend.base_url),'Anonymous DELETE must not authorize deletion');assert.deepEqual(await db('anonymous-delete-rejected'),beforeDelete);
  const noCsrf=await deleteItem(context,backend.base_url,requests,updated.id,{});assert.equal(noCsrf.status(),403);assert.deepEqual(await db('missing-csrf-delete-rejected'),beforeDelete);
  const deleted=await deleteItem(context,backend.base_url,requests,updated.id,headers);assert.equal(deleted.status(),204,'DELETE must return204 for its existing target');assert.deepEqual(await db('deleted-target-only'),seeded,'DELETE must preserve both original fixture rows and all values');
  for(const conditions of [{},{itemCode:changed.itemCode},{itemName:changed.itemName},{itemCode:'A-100',itemName:'볼'}]){
   const url=new URL('/api/items',backend.base_url);url.search=new URLSearchParams(conditions).toString();const response=await request.get(url.toString());assert.equal(response.status(),200);assert.deepEqual(canonicalRows(await response.json()),await db('get-after-delete',conditions));
  }
  passed('delete-target-only-and-query-sql');
  for(const id of [updated.id,Math.max(...beforeDelete.map(r=>r.id))+100000]){
   const response=await deleteItem(context,backend.base_url,requests,id,headers);assert.equal(response.status(),404,'Absent id must return404, including repeated DELETE');assert.deepEqual(await db('missing-delete-preserves-all'),seeded);
  }
  passed('delete-missing-id-preserves-data');await dispose(context);context=null;
  relogin=await boundedContext(make,backend.base_url);const again=trustedRequest(relogin,backend.base_url,requests,'relogin');assert.equal(await ensureAuthenticated(again,backend.base_url,{localProxy:true}),true);
  const persisted=await again.get(new URL('/api/items',backend.base_url).toString());assert.equal(persisted.status(),200);assert.deepEqual(canonicalRows(await persisted.json()),seeded);assert.deepEqual(await db('delete-relogin-persistence'),seeded);passed('delete-session-csrf-and-relogin-persistence');result={passed:true};
 }catch(e){result={passed:false,failure:String(e)};}
 finally {
  for(const c of [context,anonymous,relogin])if(c)try{await dispose(c);}catch(e){errors.push('API context: '+e);}
  if(runtime)try{ownedCleanup=await runtime.close();}catch(e){errors.push('DELETE runtime: '+e);}
  const cleanup={success:regression?.cleanup?.success===true&&ownedCleanup.success===true&&!errors.length,updateRegression:regression?.cleanup,deleteRuntime:ownedCleanup,errors};
  result||={passed:false,failure:'No DELETE verification result'};if(!cleanup.success){result.passed=false;result.failure=[result.failure,'Owned cleanup failed',...errors].filter(Boolean).join('\n');}
  if(result.passed)passed('delete-owned-resources-cleanup');Object.assign(result,{cases,requests,sqlProofs,cleanup,verificationMode:'api-and-sql-only',browserStarted:false,databaseStarted:!!runtime,evidence:out});fs.writeFileSync(path.join(out,'result.json'),JSON.stringify(result,null,2));
 }
 console.log(JSON.stringify(result));return result;
}
module.exports={verify,CASES,DELETE_CASES,deleteItem};
if(require.main===module)verify(process.argv[2]).then(r=>{if(!r.passed)process.exitCode=1;}).catch(e=>{console.error(e);process.exitCode=1;});
