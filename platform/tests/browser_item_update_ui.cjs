// Browser PUT stage, preserving the unchanged ten-case query/create integration.
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const createOracle=require('./browser_item_create_ui.cjs');
const {ItemRuntime}=require('./item_crud_runtime_client.cjs');
const {ItemBrowserDriver,FIELDS}=require('./item_browser_driver.cjs');
const {canonicalRows,querySql}=require('./browser_item_query.cjs');
const NEW_CASES=['select-existing-row-and-edit-five-fields','actual-put-same-id-sql-and-grid','repeat-save-reload-query-persistence','required-server-duplicate-preserves-rows-and-owned-cleanup'];
const CASES=[...createOracle.CASES,...NEW_CASES];
function verifySavedUpdate(before,value,stored,id,values) {
 const saved=canonicalRows([value])[0];assert.ok(Number.isSafeInteger(saved.id)&&saved.id===id,'PUT must preserve numeric identity');
 assert.deepEqual(Object.fromEntries(FIELDS.map(key=>[key,saved[key]])),values,'PUT response must contain all five saved fields');
 assert.deepEqual(stored,before.map(row=>row.id===id?saved:row),'PUT must preserve every other row and row count');return saved;
}
function cleanupSuccess(regression,owned,errors) {return regression?.success===true&&owned?.success===true&&errors.length===0;}
async function verify(output,infrastructure={}) {
 const out=path.resolve(output);fs.mkdirSync(out,{recursive:true});const cases=[],sqlProofs=[],cleanupErrors=[];
 const Runtime=infrastructure.Runtime||ItemRuntime,Driver=infrastructure.Driver||ItemBrowserDriver;
 let regression,runtime,backend,driver,result;let ownedCleanup={success:true,started:false};
 const passed=name=>{assert.ok(NEW_CASES.includes(name));cases.push(name);console.log('ITEM_UPDATE_UI_OK: '+name);};
 try {
  regression=await (infrastructure.createVerify||createOracle.verify)(path.join(out,'create-regression'));
  assert.ok(regression?.passed&&regression?.cleanup?.success,'Existing query/create browser integration must pass');assert.deepEqual([...regression.cases].sort(),[...createOracle.CASES].sort());cases.push(...regression.cases);
  runtime=new Runtime(path.join(out,'runtime'));backend=await runtime.start();
  async function db(label){const rows=canonicalRows(await runtime.rows(querySql()));sqlProofs.push({label,rows});return rows;}
  assert.deepEqual(await db('fresh-update-ui-database'),[]);const seeded=canonicalRows(await runtime.seedQueryFixture());assert.deepEqual(await db('fixed-update-ui-fixture'),seeded);
  driver=new Driver(out,{post:true,put:true});await driver.start(backend.base_url);await driver.open();assert.deepEqual(await driver.queryAll(),seeded);await driver.expectGrid(seeded);
  const original=seeded[0],id=original.id,endpoint='/api/items/'+id;
  await driver.select(original.itemCode);assert.deepEqual(await driver.values(),Object.fromEntries(FIELDS.map(key=>[key,original[key]])),'Selected row must load all five editor values');
  const edited={itemCode:'UI-UPD-300',itemName:'화면 수정 품목',specification:'M24x90',unit:'SET',remark:'수정 영속성 확인'};await driver.fill(edited);passed('select-existing-row-and-edit-five-fields');
  const initialPosts=driver.count('POST'),initialPuts=driver.count('PUT');
  async function save(label) {
   const before=await db(label+'-before'),count=driver.count('PUT');const response=await driver.saveResponse('PUT',endpoint);
   assert.equal(response.status(),200,'Save must perform real successful PUT');const body=response.request().postDataJSON();for(const key of FIELDS)assert.equal(body[key],edited[key],'Wire mapping '+key);
   const saved=verifySavedUpdate(before,await response.json(),await db(label+'-after'),id,edited);assert.equal(driver.count('PUT'),count+1);assert.equal(driver.count('POST'),initialPosts,'Editing must not create rows');return saved;
  }
  const saved=await save('first-browser-update'),stored=await db('updated-state');await driver.expectGrid(stored);passed('actual-put-same-id-sql-and-grid');
  await save('repeated-browser-save');assert.equal(driver.count('PUT'),initialPuts+2);assert.deepEqual(await db('after-repeat'),stored);await driver.expectGrid(stored);
  await driver.open();assert.deepEqual(await driver.queryAll(),stored);await driver.expectGrid(stored);assert.deepEqual(await db('reload-query-persistence'),stored);assert.equal(driver.count('POST'),initialPosts);assert.equal(driver.count('PUT'),initialPuts+2);passed('repeat-save-reload-query-persistence');
  await driver.select(saved.itemCode);
  for(const field of ['itemCode','itemName'])for(const value of ['', '   ']){
   await driver.fill({...edited,[field]:value});const count=driver.count('PUT');await driver.clickSave();await driver.pause(300);assert.equal(driver.count('PUT'),count,'Invalid required field must not emit PUT');assert.equal(driver.count('POST'),initialPosts);assert.deepEqual(await db('invalid-required-'+field),stored);await driver.expectGrid(stored);
  }
  await driver.fill({...edited,itemCode:seeded[1].itemCode});const beforeError=await driver.text();const duplicate=await driver.saveResponse('PUT',endpoint);
  assert.ok(duplicate.status()>=400&&duplicate.status()<500,'Duplicate must reach the real server and return 4xx');await driver.expectError(duplicate,beforeError);assert.deepEqual(await db('duplicate-preserves-all-rows'),stored);await driver.expectGrid(stored);assert.equal(driver.count('POST'),initialPosts);
  assert.deepEqual(driver.runtimeErrors,[]);assert.deepEqual(driver.forbiddenRequests,[]);await driver.screenshot('item-update-1440.png');result={passed:true};
 }catch(e){result={passed:false,failure:String(e)};if(driver)try{await driver.screenshot('failure.png');}catch(_) {}}
 finally {
  if(driver)try{await driver.close();}catch(e){cleanupErrors.push('browser driver: '+e);}
  if(runtime)try{ownedCleanup=await runtime.close();}catch(e){cleanupErrors.push('update runtime: '+e);}
  const cleanup={success:cleanupSuccess(regression?.cleanup,ownedCleanup,cleanupErrors),createRegression:regression?.cleanup,updateRuntime:ownedCleanup,errors:cleanupErrors};
  result||={passed:false,failure:'No UI update result'};
  if(!cleanup.success){result.passed=false;result.failure=[result.failure,'Owned cleanup failed',...cleanupErrors].filter(Boolean).join('\n');}
  if(result.passed&&(driver.runtimeErrors.length||driver.forbiddenRequests.length)){result.passed=false;result.failure='Late runtime error or forbidden request';}
  if(result.passed)passed('required-server-duplicate-preserves-rows-and-owned-cleanup');
  Object.assign(result,{cases,requests:driver?.requests||[],sqlProofs,runtimeErrors:driver?.runtimeErrors||[],forbiddenRequests:driver?.forbiddenRequests||[],cleanup,browserStarted:!!driver?.page,verificationMode:'browser-api-and-sql',evidence:out});fs.writeFileSync(path.join(out,'result.json'),JSON.stringify(result,null,2));
 }
 console.log(JSON.stringify(result));return result;
}
module.exports={verify,CASES,NEW_CASES,verifySavedUpdate,cleanupSuccess};
if(require.main===module)verify(process.argv[2]).then(r=>{if(!r.passed)process.exitCode=1;}).catch(e=>{console.error(e);process.exitCode=1;});
