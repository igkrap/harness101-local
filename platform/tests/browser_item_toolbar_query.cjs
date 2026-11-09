// One common-toolbar action on top of the unchanged eighteen-case CRUD regression.
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const prior=require('./browser_item_delete_ui.cjs');
const {ItemRuntime}=require('./item_crud_runtime_client.cjs');
const {ItemBrowserDriver}=require('./item_browser_driver.cjs');
const {canonicalRows,querySql}=require('./browser_item_query.cjs');
const {ToolbarControls}=require('./browser_item_toolbar_ui.cjs');
const NEW_CASE='common-header-query-current-conditions-and-cleanup';
const CASES=[...prior.CASES,NEW_CASE];
async function verify(output,infrastructure={}){
 const out=path.resolve(output);fs.mkdirSync(out,{recursive:true});const cases=[],sqlProofs=[],cleanupErrors=[];
 const Runtime=infrastructure.Runtime||ItemRuntime,Driver=infrastructure.Driver||ItemBrowserDriver,Controls=infrastructure.Controls||ToolbarControls;
 let regression,runtime,driver,result;let ownCleanup={success:true,started:false};
 try{
  regression=await(infrastructure.priorVerify||prior.verify)(path.join(out,'delete-regression'));
  assert.ok(regression?.passed===true&&regression?.cleanup?.success===true);
  assert.deepEqual([...regression.cases].sort(),[...prior.CASES].sort());cases.push(...regression.cases);
  runtime=new Runtime(path.join(out,'runtime'));const backend=await runtime.start();
  async function db(label,conditions){const rows=canonicalRows(await runtime.rows(querySql(conditions)));sqlProofs.push({label,rows});return rows;}
  assert.deepEqual(await db('fresh-toolbar-query-database'),[]);
  const seeded=canonicalRows(await runtime.seedQueryFixture());assert.equal(seeded.length,2);
  driver=new Driver(out,{post:true,put:true,delete:true});await driver.start(backend.base_url);await driver.open();
  const controls=new Controls(driver);assert.deepEqual(await driver.queryAll(),seeded);await driver.expectGrid(seeded);
  const heading=driver.screen.getByRole('heading',{name:'품목 등록',exact:true});const titleBox=await heading.boundingBox();assert.ok(titleBox);
  assert.ok(await heading.evaluate(element=>parseFloat(getComputedStyle(element).fontSize))<=18,'Compact screen title');
  const queryButton=controls.button('조회');await queryButton.waitFor({state:'visible'});
  const queryBox=await queryButton.boundingBox();assert.ok(queryBox&&queryBox.x>titleBox.x+titleBox.width&&Math.abs((queryBox.y+queryBox.height/2)-(titleBox.y+titleBox.height/2))<45,'Query action beside title at top right');
  const getBefore=driver.count('GET'),postBefore=driver.count('POST'),putBefore=driver.count('PUT'),deleteBefore=driver.count('DELETE');
  await controls.conditions('-10','볼');await driver.pause(300);assert.equal(driver.count('GET'),getBefore);
  const response=await controls.submit('GET','/api/items','조회');assert.equal(response.status(),200);
  const params=new URL(response.url()).searchParams;assert.equal(params.get('itemCode'),'-10');assert.equal(params.get('itemName'),'볼');
  const filtered=await db('current-header-conditions',{itemCode:'-10',itemName:'볼'});assert.equal(filtered.length,1);
  assert.deepEqual(canonicalRows(await response.json()),filtered);await driver.expectGrid(filtered);
  await controls.conditions('','');assert.equal((await controls.submit('GET','/api/items','조회')).status(),200);
  await driver.expectGrid(seeded);assert.equal(driver.count('POST'),postBefore);assert.equal(driver.count('PUT'),putBefore);assert.equal(driver.count('DELETE'),deleteBefore);
  assert.deepEqual(driver.runtimeErrors,[]);assert.deepEqual(driver.forbiddenRequests,[]);
  await driver.screenshot('item-toolbar-query-1440.png');result={passed:true};
 }catch(error){result={passed:false,failure:String(error)};if(driver)try{await driver.screenshot('failure.png');}catch(_) {}}
 finally{
  if(driver)try{await driver.close();}catch(error){cleanupErrors.push('browser driver: '+error);}
  if(runtime)try{ownCleanup=await runtime.close();}catch(error){cleanupErrors.push('toolbar runtime: '+error);}
  const cleanup={success:regression?.cleanup?.success===true&&ownCleanup.success===true&&!cleanupErrors.length,deleteRegression:regression?.cleanup,toolbarRuntime:ownCleanup,errors:cleanupErrors};
  result||={passed:false,failure:'No toolbar query result'};
  if(!cleanup.success){result.passed=false;result.failure=[result.failure,'Owned cleanup failed',...cleanupErrors].filter(Boolean).join('\n');}
  if(result.passed&&(driver.runtimeErrors.length||driver.forbiddenRequests.length)){result.passed=false;result.failure='Late runtime error or forbidden request';}
  if(result.passed){cases.push(NEW_CASE);console.log('ITEM_TOOLBAR_QUERY_OK: '+NEW_CASE);}
  Object.assign(result,{cases,requests:driver?.requests||[],sqlProofs,runtimeErrors:driver?.runtimeErrors||[],forbiddenRequests:driver?.forbiddenRequests||[],cleanup,browserStarted:!!driver?.page,verificationMode:'browser-api-and-sql',evidence:out});
  fs.writeFileSync(path.join(out,'result.json'),JSON.stringify(result,null,2));
 }
 console.log(JSON.stringify(result));return result;
}
module.exports={verify,CASES,NEW_CASE};
if(require.main===module)verify(process.argv[2]).then(result=>{if(!result.passed)process.exitCode=1;}).catch(error=>{console.error(error);process.exitCode=1;});
