// First human-sized common-toolbar task. The prior eighteen CRUD cases are unchanged.
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const prior=require('./browser_item_delete_ui.cjs');
const {ItemRuntime}=require('./item_crud_runtime_client.cjs');
const {ItemBrowserDriver,FIELDS}=require('./item_browser_driver.cjs');
const {canonicalRows,querySql}=require('./browser_item_query.cjs');
const {ToolbarControls,verifyCreated}=require('./browser_item_toolbar_ui.cjs');
const NEW_CASES=['common-header-query-and-always-reset-new','common-header-first-save-post-and-cleanup'];
const CASES=[...prior.CASES,...NEW_CASES];
const values=row=>Object.fromEntries(FIELDS.map(key=>[key,row[key]??'']));
async function verify(output,infrastructure={}){
 const out=path.resolve(output);fs.mkdirSync(out,{recursive:true});const cases=[],sqlProofs=[],cleanupErrors=[];
 const Runtime=infrastructure.Runtime||ItemRuntime,Driver=infrastructure.Driver||ItemBrowserDriver,Controls=infrastructure.Controls||ToolbarControls;
 let regression,runtime,driver,controls,result;let ownCleanup={success:true,started:false};
 const passed=name=>{assert.ok(NEW_CASES.includes(name));cases.push(name);console.log('ITEM_TOOLBAR_CORE_OK: '+name);};
 try{
  regression=await(infrastructure.priorVerify||prior.verify)(path.join(out,'delete-regression'));
  assert.ok(regression?.passed===true&&regression?.cleanup?.success===true);assert.deepEqual([...regression.cases].sort(),[...prior.CASES].sort());cases.push(...regression.cases);
  runtime=new Runtime(path.join(out,'runtime'));const backend=await runtime.start();
  async function db(label,conditions){const rows=canonicalRows(await runtime.rows(querySql(conditions)));sqlProofs.push({label,rows});return rows;}
  assert.deepEqual(await db('fresh-toolbar-core-database'),[]);const seeded=canonicalRows(await runtime.seedQueryFixture());assert.equal(seeded.length,2);assert.deepEqual(await db('fixed-toolbar-core-fixture'),seeded);
  driver=new Driver(out,{post:true,put:true,delete:true});await driver.start(backend.base_url);await driver.open();controls=new Controls(driver);assert.deepEqual(await driver.queryAll(),seeded);await driver.expectGrid(seeded);await controls.layout();
  const gets=driver.count('GET'),posts=driver.count('POST'),puts=driver.count('PUT'),deletes=driver.count('DELETE');
  await controls.conditions('-10','볼');await driver.pause(300);assert.equal(driver.count('GET'),gets);
  const query=await controls.submit('GET','/api/items','조회');assert.equal(query.status(),200);const params=new URL(query.url()).searchParams;assert.equal(params.get('itemCode'),'-10');assert.equal(params.get('itemName'),'볼');
  const filtered=await db('header-query-and-filter',{itemCode:'-10',itemName:'볼'});assert.equal(filtered.length,1);assert.deepEqual(canonicalRows(await query.json()),filtered);await driver.expectGrid(filtered);
  await controls.conditions('','');assert.equal((await controls.submit('GET','/api/items','조회')).status(),200);await driver.expectGrid(seeded);
  await driver.select(seeded[0].itemCode);const dirty={itemCode:'DIRTY',itemName:'미저장 초안',specification:'M30',unit:'EA',remark:'초기화 대상'};await driver.fill(dirty);await controls.collapse();await controls.click('신규');await controls.revealed();
  const empty=Object.fromEntries(FIELDS.map(k=>[k,'']));assert.deepEqual(await driver.values(),empty);assert.equal(await controls.button('삭제').isDisabled(),true);
  await driver.fill(dirty);await controls.click('신규');assert.deepEqual(await driver.values(),empty,'Repeated New must clear an already-new draft');
  assert.equal(driver.count('POST'),posts);assert.equal(driver.count('PUT'),puts);assert.equal(driver.count('DELETE'),deletes);assert.deepEqual(await db('header-new-does-not-write'),seeded);passed(NEW_CASES[0]);
  const createdValues={itemCode:'TBR-C300',itemName:'상단 버튼 신규 품목',specification:'M18x60',unit:'SET',remark:'상단 저장 영속성'};await driver.fill(createdValues);
  const created=await controls.submit('POST','/api/items');assert.ok([200,201].includes(created.status()));assert.deepEqual(values(created.request().postDataJSON()),createdValues);
  const saved=verifyCreated(seeded,await created.json(),await db('toolbar-created'),createdValues);assert.ok(saved.id>0);const stored=await db('after-toolbar-create');await driver.expectGrid(stored);assert.equal(driver.count('POST'),posts+1);assert.equal(driver.count('PUT'),puts);assert.equal(driver.count('DELETE'),deletes);
  assert.deepEqual(driver.runtimeErrors,[]);assert.deepEqual(driver.forbiddenRequests,[]);await driver.screenshot('item-toolbar-core-1440.png');result={passed:true};
 }catch(e){result={passed:false,failure:String(e)};if(driver)try{await driver.screenshot('failure.png');}catch(_) {}}
 finally{
  if(driver)try{await driver.close();}catch(e){cleanupErrors.push('browser driver: '+e);}
  if(runtime)try{ownCleanup=await runtime.close();}catch(e){cleanupErrors.push('toolbar runtime: '+e);}
  const cleanup={success:regression?.cleanup?.success===true&&ownCleanup.success===true&&!cleanupErrors.length,deleteRegression:regression?.cleanup,toolbarRuntime:ownCleanup,errors:cleanupErrors};result||={passed:false,failure:'No toolbar core result'};
  if(!cleanup.success){result.passed=false;result.failure=[result.failure,'Owned cleanup failed',...cleanupErrors].filter(Boolean).join('\n');}
  if(result.passed&&(driver.runtimeErrors.length||driver.forbiddenRequests.length)){result.passed=false;result.failure='Late runtime error or forbidden request';}
  if(result.passed)passed(NEW_CASES[1]);Object.assign(result,{cases,requests:driver?.requests||[],sqlProofs,runtimeErrors:driver?.runtimeErrors||[],forbiddenRequests:driver?.forbiddenRequests||[],cleanup,browserStarted:!!driver?.page,verificationMode:'browser-api-and-sql',evidence:out});fs.writeFileSync(path.join(out,'result.json'),JSON.stringify(result,null,2));
 }
 console.log(JSON.stringify(result));return result;
}
module.exports={verify,CASES,NEW_CASES};
if(require.main===module)verify(process.argv[2]).then(r=>{if(!r.passed)process.exitCode=1;}).catch(e=>{console.error(e);process.exitCode=1;});
