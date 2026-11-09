// Final workspace smoke: the item draft and query survive Home/Item MDI switching.
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const prior=require('./browser_item_toolbar_ui.cjs');
const {ItemRuntime}=require('./item_crud_runtime_client.cjs');
const {ItemBrowserDriver}=require('./item_browser_driver.cjs');
const {canonicalRows}=require('./browser_item_query.cjs');
const CASE='mdi-draft-query-and-1280-layout-retained';
const CASES=[...prior.CASES,CASE];
async function verify(output,infrastructure={}){
 const out=path.resolve(output);fs.mkdirSync(out,{recursive:true});const cases=[],cleanupErrors=[];
 const Runtime=infrastructure.Runtime||ItemRuntime,Driver=infrastructure.Driver||ItemBrowserDriver;
 let regression,runtime,driver,result;let ownCleanup={success:true,started:false};
 try{
  regression=await(infrastructure.priorVerify||prior.verify)(path.join(out,'toolbar-regression'));
  assert.ok(regression?.passed===true&&regression?.cleanup?.success===true);
  assert.deepEqual([...regression.cases].sort(),[...prior.CASES].sort());cases.push(...regression.cases);
  runtime=new Runtime(path.join(out,'runtime'));const backend=await runtime.start();
  const seeded=canonicalRows(await runtime.seedQueryFixture());assert.equal(seeded.length,2);
  driver=new Driver(out,{post:true,put:true,delete:true});await driver.start(backend.base_url);await driver.open();
  assert.deepEqual(await driver.queryAll(),seeded);await driver.expectGrid(seeded);
  const draft={itemCode:'DRAFT-ONLY',itemName:'미저장 품목',specification:'M30',unit:'EA',remark:'MDI 유지'};
  await driver.fill(draft);
  await driver.query.getByLabel(/^품번/).fill('A-100');
  const name=driver.query.getByLabel(/^품명/);if(!await name.isVisible())await driver.query.getByRole('button',{name:/상세.*조건/}).click();await name.fill('볼트');
  const beforeWrites={post:driver.count('POST'),put:driver.count('PUT'),delete:driver.count('DELETE')};
  const mdi=driver.page.getByRole('navigation').last();
  await mdi.getByRole('button',{name:'홈',exact:true}).click();
  assert.equal(await driver.screen.isVisible(),false);
  await mdi.getByRole('button',{name:'품목 등록',exact:true}).click();
  await driver.screen.waitFor({state:'visible'});
  assert.deepEqual(await driver.values(),draft);
  assert.equal(await driver.query.getByLabel(/^품번/).inputValue(),'A-100');
  assert.equal(await driver.query.getByLabel(/^품명/).inputValue(),'볼트');
  await driver.page.setViewportSize({width:1280,height:800});
  await driver.page.waitForTimeout(150);
  const heading=driver.screen.getByRole('heading',{name:'품목 등록',exact:true});
  const titleBox=await heading.boundingBox(),gridBox=await driver.grid.boundingBox(),editorBox=await driver.editor.boundingBox();
  assert.ok(titleBox&&gridBox&&editorBox&&titleBox.x>=0&&gridBox.width>400&&editorBox.width>400);
  assert.equal(driver.count('POST'),beforeWrites.post);assert.equal(driver.count('PUT'),beforeWrites.put);assert.equal(driver.count('DELETE'),beforeWrites.delete);
  assert.deepEqual(driver.runtimeErrors,[]);assert.deepEqual(driver.forbiddenRequests,[]);
  await driver.screenshot('item-mdi-1280.png');result={passed:true};
 }catch(error){result={passed:false,failure:String(error)};if(driver)try{await driver.screenshot('failure.png');}catch(_) {}}
 finally{
  if(driver)try{await driver.close();}catch(error){cleanupErrors.push('browser driver: '+error);}
  if(runtime)try{ownCleanup=await runtime.close();}catch(error){cleanupErrors.push('workspace runtime: '+error);}
  const cleanup={success:regression?.cleanup?.success===true&&ownCleanup.success===true&&!cleanupErrors.length,toolbarRegression:regression?.cleanup,workspaceRuntime:ownCleanup,errors:cleanupErrors};
  result||={passed:false,failure:'No MDI result'};
  if(!cleanup.success){result.passed=false;result.failure=[result.failure,'Owned cleanup failed',...cleanupErrors].filter(Boolean).join('\n');}
  if(result.passed&&(driver.runtimeErrors.length||driver.forbiddenRequests.length)){result.passed=false;result.failure='Late runtime error or forbidden request';}
  if(result.passed){cases.push(CASE);console.log('ITEM_MDI_OK: '+CASE);}
  Object.assign(result,{cases,requests:driver?.requests||[],runtimeErrors:driver?.runtimeErrors||[],forbiddenRequests:driver?.forbiddenRequests||[],cleanup,browserStarted:!!driver?.page,verificationMode:'browser-api-and-sql',evidence:out});
  fs.writeFileSync(path.join(out,'result.json'),JSON.stringify(result,null,2));
 }
 console.log(JSON.stringify(result));return result;
}
module.exports={verify,CASES,CASE};
if(require.main===module)verify(process.argv[2]).then(result=>{if(!result.passed)process.exitCode=1;}).catch(error=>{console.error(error);process.exitCode=1;});
