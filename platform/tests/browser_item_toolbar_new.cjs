// Header New is a separate task; preserve the preceding nineteen browser cases.
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const prior=require('./browser_item_toolbar_query.cjs');
const {ItemRuntime}=require('./item_crud_runtime_client.cjs');
const {ItemBrowserDriver,FIELDS}=require('./item_browser_driver.cjs');
const {canonicalRows,querySql}=require('./browser_item_query.cjs');
const {ToolbarControls}=require('./browser_item_toolbar_ui.cjs');
const NEW_CASE='common-header-new-repeated-reset-reveal-no-write-and-cleanup';
const CASES=[...prior.CASES,NEW_CASE];
async function verify(output,infrastructure={}){
 const out=path.resolve(output);fs.mkdirSync(out,{recursive:true});const cases=[],sqlProofs=[],cleanupErrors=[];
 const Runtime=infrastructure.Runtime||ItemRuntime,Driver=infrastructure.Driver||ItemBrowserDriver,Controls=infrastructure.Controls||ToolbarControls;
 let regression,runtime,driver,result;let ownCleanup={success:true,started:false};
 try{
  regression=await(infrastructure.priorVerify||prior.verify)(path.join(out,'query-regression'));
  assert.ok(regression?.passed===true&&regression?.cleanup?.success===true);
  assert.deepEqual([...regression.cases].sort(),[...prior.CASES].sort());cases.push(...regression.cases);
  runtime=new Runtime(path.join(out,'runtime'));const backend=await runtime.start();
  async function db(label){const rows=canonicalRows(await runtime.rows(querySql({})));sqlProofs.push({label,rows});return rows;}
  assert.deepEqual(await db('fresh-header-new-database'),[]);
  const seeded=canonicalRows(await runtime.seedQueryFixture());assert.equal(seeded.length,2);
  driver=new Driver(out,{post:true,put:true,delete:true});await driver.start(backend.base_url);await driver.open();
  const controls=new Controls(driver);assert.deepEqual(await driver.queryAll(),seeded);await driver.expectGrid(seeded);
  const heading=driver.screen.getByRole('heading',{name:'품목 등록',exact:true});const titleBox=await heading.boundingBox();assert.ok(titleBox);
  const newButton=controls.button('신규');await newButton.waitFor({state:'visible'});
  const newBox=await newButton.boundingBox();assert.ok(newBox&&newBox.x>titleBox.x+titleBox.width&&Math.abs((newBox.y+newBox.height/2)-(titleBox.y+titleBox.height/2))<45,'New action beside title at top right');
  const posts=driver.count('POST'),puts=driver.count('PUT'),deletes=driver.count('DELETE');
  await driver.select(seeded[0].itemCode);
  const dirty={itemCode:'DIRTY',itemName:'미저장 초안',specification:'M30',unit:'EA',remark:'초기화 대상'};
  await driver.fill(dirty);await controls.collapse();await controls.click('신규');await controls.revealed();
  const empty=Object.fromEntries(FIELDS.map(key=>[key,'']));assert.deepEqual(await driver.values(),empty);
  assert.equal(await controls.button('삭제').isDisabled(),true);
  await driver.fill(dirty);await controls.click('신규');assert.deepEqual(await driver.values(),empty,'Repeated New clears an already-new draft');
  assert.equal(driver.count('POST'),posts);assert.equal(driver.count('PUT'),puts);assert.equal(driver.count('DELETE'),deletes);
  assert.deepEqual(await db('header-new-does-not-write'),seeded);assert.deepEqual(driver.runtimeErrors,[]);assert.deepEqual(driver.forbiddenRequests,[]);
  await driver.screenshot('item-toolbar-new-1440.png');result={passed:true};
 }catch(error){result={passed:false,failure:String(error)};if(driver)try{await driver.screenshot('failure.png');}catch(_) {}}
 finally{
  if(driver)try{await driver.close();}catch(error){cleanupErrors.push('browser driver: '+error);}
  if(runtime)try{ownCleanup=await runtime.close();}catch(error){cleanupErrors.push('toolbar runtime: '+error);}
  const cleanup={success:regression?.cleanup?.success===true&&ownCleanup.success===true&&!cleanupErrors.length,queryRegression:regression?.cleanup,toolbarRuntime:ownCleanup,errors:cleanupErrors};
  result||={passed:false,failure:'No toolbar New result'};
  if(!cleanup.success){result.passed=false;result.failure=[result.failure,'Owned cleanup failed',...cleanupErrors].filter(Boolean).join('\n');}
  if(result.passed&&(driver.runtimeErrors.length||driver.forbiddenRequests.length)){result.passed=false;result.failure='Late runtime error or forbidden request';}
  if(result.passed){cases.push(NEW_CASE);console.log('ITEM_TOOLBAR_NEW_OK: '+NEW_CASE);}
  Object.assign(result,{cases,requests:driver?.requests||[],sqlProofs,runtimeErrors:driver?.runtimeErrors||[],forbiddenRequests:driver?.forbiddenRequests||[],cleanup,browserStarted:!!driver?.page,verificationMode:'browser-api-and-sql',evidence:out});
  fs.writeFileSync(path.join(out,'result.json'),JSON.stringify(result,null,2));
 }
 console.log(JSON.stringify(result));return result;
}
module.exports={verify,CASES,NEW_CASE};
if(require.main===module)verify(process.argv[2]).then(result=>{if(!result.passed)process.exitCode=1;}).catch(error=>{console.error(error);process.exitCode=1;});
