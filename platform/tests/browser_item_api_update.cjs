// PUT stage; unchanged GET/POST regression owns separate resources.
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const postOracle = require('./browser_item_api_create.cjs');
const queryOracle = require('./browser_item_api_query.cjs');
const { canonicalRows, querySql } = require('./browser_item_query.cjs');
const { ItemRuntime } = require('./item_crud_runtime_client.cjs');
const { ensureAuthenticated } = require('../../local-only/harness/trusted_auth.cjs');
const { trustedRequest, protectedResponse, within } = queryOracle;
const PUT_CASES = ['put-update-id-repeat-and-query-sql', 'put-required-duplicate-and-not-found-preserve-data',
  'put-session-csrf-and-relogin-persistence', 'put-owned-resources-cleanup'];
const CASES = [...postOracle.CASES, ...PUT_CASES];
async function createApiContext(base) {
  const config = JSON.parse(fs.readFileSync(path.join(process.env.HOME, '.local/share/mlx-server/browser-check/runtime.json'), 'utf8'));
  return require(config.playwrightModule).request.newContext({ baseURL: base, timeout: 10000 });
}
async function boundedContext(make, base) {
  let accepted = true; const pending = Promise.resolve().then(() => make(base));
  pending.then(c => { if (!accepted) return c.dispose().catch(() => {}); }, () => {});
  try { return await within(pending,15000,'API context startup exceeded 15 seconds'); }
  catch(e) { accepted=false;throw e; }
}
async function dispose(context) { return within(Promise.resolve().then(() => context.dispose()),10000,'API context cleanup exceeded 10 seconds'); }
async function putItem(context, base, requests, id, body, headers, actor='authenticated') {
  trustedRequest(context,base,[]);
  assert.ok(Number.isSafeInteger(id) && id>0,'PUT requires a positive safe numeric id');
  const entry={actor,method:'PUT',path:'/api/items/'+id};requests.push(entry);
  const response=await context.put(new URL(entry.path,base).toString(),{data:body,headers,timeout:10000,maxRedirects:0});
  entry.status=response.status();return response;
}
async function verify(output,infrastructure={}) {
  const out=path.resolve(output);fs.mkdirSync(out,{recursive:true});
  const cases=[],requests=[],sqlProofs=[],errors=[];
  const Runtime=infrastructure.Runtime||ItemRuntime, make=infrastructure.createContext||createApiContext;
  let regression,runtime,backend,context,anonymous,relogin,result;
  let ownCleanup={success:true,started:false}, regressionAttempted=false;
  const passed=name=>{assert.ok(PUT_CASES.includes(name));cases.push(name);console.log('ITEM_API_UPDATE_OK: '+name);};
  try {
    regressionAttempted=true;
    regression=await (infrastructure.postVerify||postOracle.verify)(path.join(out,'create-regression'));
    assert.ok(regression?.passed===true && regression?.cleanup?.success===true,'Unchanged GET/POST regression and cleanup must pass');
    assert.deepEqual([...regression.cases].sort(),[...postOracle.CASES].sort(),'GET/POST regression requires exact case coverage');
    cases.push(...regression.cases);
    runtime=new Runtime(path.join(out,'runtime'));backend=await runtime.start();
    async function db(label,conditions) { const rows=canonicalRows(await runtime.rows(querySql(conditions)));sqlProofs.push({label,conditions,rows});return rows; }
    assert.deepEqual(await db('fresh-update-database'),[]);
    const seeded=canonicalRows(await runtime.seedQueryFixture());assert.deepEqual(await db('fixed-update-fixture'),seeded);assert.equal(seeded.length,2);
    context=await boundedContext(make,backend.base_url);const request=trustedRequest(context,backend.base_url,requests);
    assert.equal(await ensureAuthenticated(request,backend.base_url,{localProxy:true}),true);
    const session=await (await request.get(new URL('/api/auth/session',backend.base_url).toString())).json();
    assert.ok(session.authenticated && session.csrf?.token && session.csrf.headerName==='X-CSRF-TOKEN');
    const headers={[session.csrf.headerName]:session.csrf.token},id=seeded[0].id;
    let expected=seeded;
    async function update(payload,wanted,label) {
      const response=await putItem(context,backend.base_url,requests,id,payload,headers);
      assert.equal(response.status(),200,'PUT must return its saved object: '+response.status()+' '+(await response.text()).slice(0,400));
      const saved=postOracle.savedRecord(await response.json());assert.equal(saved.id,id,'PUT must preserve its original numeric id');
      assert.deepEqual({...saved,id:undefined},{...wanted,id:undefined});
      expected=expected.map(row=>row.id===id?saved:row);
      assert.deepEqual(await db(label),expected,'PUT must change exactly the target row and preserve row count');
    }
    const full={itemCode:'UPD-A300',itemName:'수정 품목',specification:'M20x80',unit:'SET',remark:'API 수정 저장'};
    await update({...full,itemCode:'  '+full.itemCode+'  ',itemName:'  '+full.itemName+'  '},full,'updated-full-item');
    await update(full,full,'repeated-save-same-id');
    for (const conditions of [{},{itemCode:'UPD-',itemName:'수정'},{itemCode:'A-100'},{itemCode:'UPD-',itemName:'너'}]) {
      const url=new URL('/api/items',backend.base_url);url.search=new URLSearchParams(conditions).toString();
      const response=await request.get(url.toString());assert.equal(response.status(),200);
      assert.deepEqual(canonicalRows(await response.json()),await db('updated-get-query',conditions));
    }
    const blank={itemCode:full.itemCode,itemName:full.itemName,specification:'',unit:'',remark:''};
    await update(blank,blank,'updated-empty-options');
    await update({itemCode:full.itemCode,itemName:full.itemName},blank,'updated-omitted-options');
    passed('put-update-id-repeat-and-query-sql');
    const unchanged=await db('before-invalid-updates');
    for(const field of ['itemCode','itemName']) for(const [kind,value] of [['missing'],['null',null],['empty',''],['spaces','   ']]) {
      const payload={...full};if(kind==='missing')delete payload[field];else payload[field]=value;
      const response=await putItem(context,backend.base_url,requests,id,payload,headers);
      assert.ok(response.status()>=400 && response.status()<500,'PUT must reject '+kind+' '+field+' with 4xx');
      assert.deepEqual(await db('rejected-required-'+field+'-'+kind),unchanged);
    }
    const duplicate=await putItem(context,backend.base_url,requests,id,{...full,itemCode:'  '+seeded[1].itemCode+'  '},headers);
    assert.ok(duplicate.status()>=400 && duplicate.status()<500,'PUT duplicate must return 4xx');
    assert.ok((await duplicate.text()).trim(),'Duplicate must include an error reason');assert.deepEqual(await db('rejected-duplicate'),unchanged);
    const missingId=Math.max(...unchanged.map(row=>row.id))+100000;
    const missing=await putItem(context,backend.base_url,requests,missingId,{...full,itemCode:'MISSING-ROW'},headers);
    assert.equal(missing.status(),404,'PUT must not upsert an absent id');assert.deepEqual(await db('rejected-missing-id'),unchanged);
    passed('put-required-duplicate-and-not-found-preserve-data');
    anonymous=await boundedContext(make,backend.base_url);const anon=trustedRequest(anonymous,backend.base_url,requests,'anonymous');
    const anonSession=await (await anon.get(new URL('/api/auth/session',backend.base_url).toString())).json();
    assert.equal(anonSession.authenticated,false);assert.ok(anonSession.csrf?.token && anonSession.csrf.headerName==='X-CSRF-TOKEN');
    const unauthorized=await putItem(anonymous,backend.base_url,requests,id,full,{[anonSession.csrf.headerName]:anonSession.csrf.token},'anonymous');
    assert.ok(protectedResponse(unauthorized,backend.base_url));assert.deepEqual(await db('rejected-anonymous-put'),unchanged);
    const noCsrf=await putItem(context,backend.base_url,requests,id,full,{});assert.equal(noCsrf.status(),403);assert.deepEqual(await db('rejected-no-csrf'),unchanged);
    await dispose(context);context=null;relogin=await boundedContext(make,backend.base_url);const again=trustedRequest(relogin,backend.base_url,requests,'relogin');
    assert.equal(await ensureAuthenticated(again,backend.base_url,{localProxy:true}),true);
    const persisted=await again.get(new URL('/api/items',backend.base_url).toString());assert.equal(persisted.status(),200);
    assert.deepEqual(canonicalRows(await persisted.json()),unchanged);assert.deepEqual(await db('put-relogin-persistence'),unchanged);
    passed('put-session-csrf-and-relogin-persistence');result={passed:true};
  }catch(e){result={passed:false,failure:String(e)};}
  finally{
    for(const c of [context,anonymous,relogin])if(c)try{await dispose(c);}catch(e){errors.push('API context: '+e);}
    if(runtime)try{ownCleanup=await runtime.close();}catch(e){errors.push('PUT runtime: '+e);}
    const cleanup={success:(regression?.cleanup?.success===true||!regressionAttempted)&&ownCleanup.success===true&&!errors.length,createRegression:regression?.cleanup,putRuntime:ownCleanup,errors};
    result ||= {passed:false,failure:'No PUT verification result'};
    if(!cleanup.success){result.passed=false;result.failure=[result.failure,'Owned resources cleanup failed',...errors].filter(Boolean).join('\n');}
    if(result.passed)passed('put-owned-resources-cleanup');
    Object.assign(result,{cases,requests,sqlProofs,cleanup,verificationMode:'api-and-sql-only',browserStarted:false,databaseStarted:!!runtime,evidence:out});
    fs.writeFileSync(path.join(out,'result.json'),JSON.stringify(result,null,2));
  }
  console.log(JSON.stringify(result));return result;
}
module.exports={verify,CASES,PUT_CASES,putItem};
if(require.main===module)verify(process.argv[2]).then(r=>{if(!r.passed)process.exitCode=1;}).catch(e=>{console.error(e);process.exitCode=1;});
