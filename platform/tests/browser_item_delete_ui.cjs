// UI deletion stage; prior fourteen browser/query/create/update cases remain unchanged.
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const updateOracle=require('./browser_item_update_ui.cjs');
const {ItemRuntime}=require('./item_crud_runtime_client.cjs');
const {ItemBrowserDriver,FIELDS}=require('./item_browser_driver.cjs');
const {canonicalRows,querySql}=require('./browser_item_query.cjs');
const {confirmDelete}=require('./item_delete_confirmation.cjs');
const NEW_CASES=['delete-selection-cancel-preserves-data','browser-delete-target-only-and-editor-clear','delete-reload-query-persistence','delete-ui-owned-resources-cleanup'];
const CASES=[...updateOracle.CASES,...NEW_CASES];
function verifyDeletedRows(before,after,id){assert.ok(Number.isSafeInteger(id)&&id>0&&before.some(r=>r.id===id));const expected=before.filter(r=>r.id!==id);assert.deepEqual(after,expected,'Delete exactly the selected persisted row; preserve all other values');return expected;}
async function verify(output,infrastructure={}) {
 const out=path.resolve(output);fs.mkdirSync(out,{recursive:true});const cases=[],sqlProofs=[],confirmations=[],cleanupErrors=[];
 const Runtime=infrastructure.Runtime||ItemRuntime,Driver=infrastructure.Driver||ItemBrowserDriver,confirm=infrastructure.confirm||confirmDelete;
 let regression,runtime,backend,driver,result;let ownedCleanup={success:true,started:false};
 const passed=name=>{assert.ok(NEW_CASES.includes(name));cases.push(name);console.log('ITEM_DELETE_UI_OK: '+name);};
 try {
  regression=await(infrastructure.updateVerify||updateOracle.verify)(path.join(out,'update-regression'));
  assert.ok(regression?.passed===true&&regression?.cleanup?.success===true,'Unchanged query/create/update browser regression and cleanup must pass');assert.deepEqual([...regression.cases].sort(),[...updateOracle.CASES].sort());cases.push(...regression.cases);
  runtime=new Runtime(path.join(out,'runtime'));backend=await runtime.start();
  async function db(label){const rows=canonicalRows(await runtime.rows(querySql()));sqlProofs.push({label,rows});return rows;}
  assert.deepEqual(await db('fresh-delete-ui-database'),[]);const seeded=canonicalRows(await runtime.seedQueryFixture());assert.equal(seeded.length,2);assert.deepEqual(await db('fixed-delete-ui-fixture'),seeded);
  driver=new Driver(out,{post:true,put:true,delete:true});await driver.start(backend.base_url);await driver.open();assert.deepEqual(await driver.queryAll(),seeded);await driver.expectGrid(seeded);
  const remove=()=>driver.screen.getByRole('toolbar',{name:'업무 버튼',exact:true}).getByRole('button',{name:'삭제',exact:true});
  if(await remove().count())assert.equal(await remove().isDisabled(),true,'No selected item must disable deletion');
  const posts=driver.count('POST'),puts=driver.count('PUT'),deletes=driver.count('DELETE'),target=seeded[0];await driver.select(target.itemCode);
  const selected=await driver.values();assert.deepEqual(selected,Object.fromEntries(FIELDS.map(key=>[key,target[key]])));await db('selected-delete-target');
  await remove().waitFor({state:'visible'});assert.equal(await remove().isEnabled(),true,'Enable delete for selected item');
  confirmations.push(await confirm(driver.page,remove(),false));await driver.pause(300);
  assert.equal(driver.count('DELETE'),deletes,'Cancel must not emit DELETE');assert.deepEqual(await db('cancel-preserves-all-rows'),seeded);await driver.expectGrid(seeded);assert.deepEqual(await driver.values(),selected,'Cancel must preserve editor selection and values');passed('delete-selection-cancel-preserves-data');
  const endpoint='/api/items/'+target.id;
  const [response,confirmation]=await Promise.all([
   driver.page.waitForResponse(r=>new URL(r.url()).origin===driver.base&&new URL(r.url()).pathname===endpoint&&r.request().method()==='DELETE'),
   confirm(driver.page,remove(),true),
  ]);confirmations.push(confirmation);assert.equal(response.status(),204,'Confirm must perform a real successful DELETE');
  const remaining=verifyDeletedRows(seeded,await db('confirmed-delete-target-only'),target.id);await driver.expectGrid(remaining);assert.equal(driver.count('DELETE'),deletes+1);assert.equal(driver.count('POST'),posts);assert.equal(driver.count('PUT'),puts);
  assert.equal(await driver.editor.getAttribute('aria-label'),'신규 등록','After deletion the editor must leave selected-record mode');
  if(await remove().count())assert.equal(await remove().isDisabled(),true,'Cleared selection must disable deletion');passed('browser-delete-target-only-and-editor-clear');
  await driver.open();assert.deepEqual(await driver.queryAll(),remaining);await driver.expectGrid(remaining);assert.deepEqual(await db('reload-query-delete-persistence'),remaining);assert.equal(driver.count('DELETE'),deletes+1);assert.equal(driver.count('POST'),posts);assert.equal(driver.count('PUT'),puts);passed('delete-reload-query-persistence');
  assert.deepEqual(driver.runtimeErrors,[]);assert.deepEqual(driver.forbiddenRequests,[]);await driver.screenshot('item-delete-1440.png');result={passed:true};
 }catch(e){result={passed:false,failure:String(e)};if(driver)try{await driver.screenshot('failure.png');}catch(_) {}}
 finally {
  if(driver)try{await driver.close();}catch(e){cleanupErrors.push('browser driver: '+e);}
  if(runtime)try{ownedCleanup=await runtime.close();}catch(e){cleanupErrors.push('DELETE UI runtime: '+e);}
  const cleanup={success:regression?.cleanup?.success===true&&ownedCleanup.success===true&&!cleanupErrors.length,updateRegression:regression?.cleanup,deleteRuntime:ownedCleanup,errors:cleanupErrors};
  result||={passed:false,failure:'No UI DELETE result'};
  if(!cleanup.success){result.passed=false;result.failure=[result.failure,'Owned cleanup failed',...cleanupErrors].filter(Boolean).join('\n');}
  if(result.passed&&(driver.runtimeErrors.length||driver.forbiddenRequests.length)){result.passed=false;result.failure='Late runtime error or forbidden request';}
  if(result.passed)passed('delete-ui-owned-resources-cleanup');Object.assign(result,{cases,requests:driver?.requests||[],sqlProofs,confirmations,runtimeErrors:driver?.runtimeErrors||[],forbiddenRequests:driver?.forbiddenRequests||[],cleanup,browserStarted:!!driver?.page,verificationMode:'browser-api-and-sql',evidence:out});fs.writeFileSync(path.join(out,'result.json'),JSON.stringify(result,null,2));
 }
 console.log(JSON.stringify(result));return result;
}
module.exports={verify,CASES,NEW_CASES,verifyDeletedRows};
if(require.main===module)verify(process.argv[2]).then(r=>{if(!r.passed)process.exitCode=1;}).catch(e=>{console.error(e);process.exitCode=1;});
