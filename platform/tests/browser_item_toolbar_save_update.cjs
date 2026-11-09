// A second header Save updates the item just created; the prior 21 cases remain fixed.
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const prior=require('./browser_item_toolbar_save_create.cjs');
const {ItemRuntime}=require('./item_crud_runtime_client.cjs');
const {ItemBrowserDriver,FIELDS}=require('./item_browser_driver.cjs');
const {canonicalRows,querySql}=require('./browser_item_query.cjs');
const {ToolbarControls,verifyCreated}=require('./browser_item_toolbar_ui.cjs');
const {verifySavedUpdate}=require('./browser_item_update_ui.cjs');
const NEW_CASE='common-header-save-created-item-updates-same-id-and-cleanup';
const CASES=[...prior.CASES,NEW_CASE];
const values=row=>Object.fromEntries(FIELDS.map(key=>[key,row[key]??'']));
async function verify(output,infrastructure={}){
 const out=path.resolve(output);fs.mkdirSync(out,{recursive:true});const cases=[],sqlProofs=[],cleanupErrors=[];
 const Runtime=infrastructure.Runtime||ItemRuntime,Driver=infrastructure.Driver||ItemBrowserDriver,Controls=infrastructure.Controls||ToolbarControls;
 let regression,runtime,driver,result;let ownCleanup={success:true,started:false};
 try{
  regression=await(infrastructure.priorVerify||prior.verify)(path.join(out,'save-create-regression'));
  assert.ok(regression?.passed===true&&regression?.cleanup?.success===true);
  assert.deepEqual([...regression.cases].sort(),[...prior.CASES].sort());cases.push(...regression.cases);
  runtime=new Runtime(path.join(out,'runtime'));const backend=await runtime.start();
  async function db(label){const rows=canonicalRows(await runtime.rows(querySql({})));sqlProofs.push({label,rows});return rows;}
  assert.deepEqual(await db('fresh-header-update-database'),[]);
  const seeded=canonicalRows(await runtime.seedQueryFixture());assert.equal(seeded.length,2);
  driver=new Driver(out,{post:true,put:true,delete:true});await driver.start(backend.base_url);await driver.open();
  const controls=new Controls(driver);assert.deepEqual(await driver.queryAll(),seeded);await driver.expectGrid(seeded);
  const posts=driver.count('POST'),puts=driver.count('PUT'),deletes=driver.count('DELETE');
  await controls.click('신규');
  const draft={itemCode:'TBR-U300',itemName:'상단 저장 생성 품목',specification:'M18x60',unit:'SET',remark:'두 번째 저장 검증'};
  await driver.fill(draft);
  const created=await controls.submit('POST','/api/items');assert.ok([200,201].includes(created.status()));
  assert.deepEqual(values(created.request().postDataJSON()),draft);
  const saved=verifyCreated(seeded,await created.json(),await db('after-header-create'),draft);
  const endpoint='/api/items/'+saved.id;
  const edited={...draft,itemName:'같은 ID 수정 품목',specification:'M20x70',unit:'BOX',remark:'상단 저장 PUT'};
  await driver.fill(edited);
  const updated=await controls.submit('PUT',endpoint);assert.equal(updated.status(),200);
  assert.deepEqual(values(updated.request().postDataJSON()),edited);
  const stored=await db('after-header-update');verifySavedUpdate(
   [...seeded,saved].sort((a,b)=>a.id-b.id),await updated.json(),stored,saved.id,edited);
  await driver.expectGrid(stored);
  assert.equal(driver.count('POST'),posts+1,'Second Save must not create a duplicate');
  assert.equal(driver.count('PUT'),puts+1);assert.equal(driver.count('DELETE'),deletes);
  await driver.open();assert.deepEqual(await driver.queryAll(),stored);await driver.expectGrid(stored);
  assert.deepEqual(await db('after-header-update-reload'),stored);
  assert.deepEqual(driver.runtimeErrors,[]);assert.deepEqual(driver.forbiddenRequests,[]);
  await driver.screenshot('item-toolbar-save-update-1440.png');result={passed:true};
 }catch(error){result={passed:false,failure:String(error)};if(driver)try{await driver.screenshot('failure.png');}catch(_) {}}
 finally{
  if(driver)try{await driver.close();}catch(error){cleanupErrors.push('browser driver: '+error);}
  if(runtime)try{ownCleanup=await runtime.close();}catch(error){cleanupErrors.push('toolbar runtime: '+error);}
  const cleanup={success:regression?.cleanup?.success===true&&ownCleanup.success===true&&!cleanupErrors.length,saveCreateRegression:regression?.cleanup,toolbarRuntime:ownCleanup,errors:cleanupErrors};
  result||={passed:false,failure:'No header Save update result'};
  if(!cleanup.success){result.passed=false;result.failure=[result.failure,'Owned cleanup failed',...cleanupErrors].filter(Boolean).join('\n');}
  if(result.passed&&(driver.runtimeErrors.length||driver.forbiddenRequests.length)){result.passed=false;result.failure='Late runtime error or forbidden request';}
  if(result.passed){cases.push(NEW_CASE);console.log('ITEM_TOOLBAR_SAVE_UPDATE_OK: '+NEW_CASE);}
  Object.assign(result,{cases,requests:driver?.requests||[],sqlProofs,runtimeErrors:driver?.runtimeErrors||[],forbiddenRequests:driver?.forbiddenRequests||[],cleanup,browserStarted:!!driver?.page,verificationMode:'browser-api-and-sql',evidence:out});
  fs.writeFileSync(path.join(out,'result.json'),JSON.stringify(result,null,2));
 }
 console.log(JSON.stringify(result));return result;
}
module.exports={verify,CASES,NEW_CASE};
if(require.main===module)verify(process.argv[2]).then(result=>{if(!result.passed)process.exitCode=1;}).catch(error=>{console.error(error);process.exitCode=1;});
