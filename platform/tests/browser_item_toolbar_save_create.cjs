// Header Save creates one new item; existing twenty browser cases remain unchanged.
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const prior=require('./browser_item_toolbar_new.cjs');
const {ItemRuntime}=require('./item_crud_runtime_client.cjs');
const {ItemBrowserDriver,FIELDS}=require('./item_browser_driver.cjs');
const {canonicalRows,querySql}=require('./browser_item_query.cjs');
const {ToolbarControls,verifyCreated}=require('./browser_item_toolbar_ui.cjs');
const NEW_CASE='common-header-save-new-post-sql-grid-and-cleanup';
const CASES=[...prior.CASES,NEW_CASE];
const values=row=>Object.fromEntries(FIELDS.map(key=>[key,row[key]??'']));
async function verify(output,infrastructure={}){
 const out=path.resolve(output);fs.mkdirSync(out,{recursive:true});const cases=[],sqlProofs=[],cleanupErrors=[];
 const Runtime=infrastructure.Runtime||ItemRuntime,Driver=infrastructure.Driver||ItemBrowserDriver,Controls=infrastructure.Controls||ToolbarControls;
 let regression,runtime,driver,result;let ownCleanup={success:true,started:false};
 try{
  regression=await(infrastructure.priorVerify||prior.verify)(path.join(out,'new-regression'));
  assert.ok(regression?.passed===true&&regression?.cleanup?.success===true);
  assert.deepEqual([...regression.cases].sort(),[...prior.CASES].sort());cases.push(...regression.cases);
  runtime=new Runtime(path.join(out,'runtime'));const backend=await runtime.start();
  async function db(label){const rows=canonicalRows(await runtime.rows(querySql({})));sqlProofs.push({label,rows});return rows;}
  assert.deepEqual(await db('fresh-header-save-database'),[]);
  const seeded=canonicalRows(await runtime.seedQueryFixture());assert.equal(seeded.length,2);
  driver=new Driver(out,{post:true,put:true,delete:true});await driver.start(backend.base_url);await driver.open();
  const controls=new Controls(driver);assert.deepEqual(await driver.queryAll(),seeded);await driver.expectGrid(seeded);
  const heading=driver.screen.getByRole('heading',{name:'품목 등록',exact:true});const titleBox=await heading.boundingBox();assert.ok(titleBox);
  const saveButton=controls.button('저장');await saveButton.waitFor({state:'visible'});
  const saveBox=await saveButton.boundingBox();assert.ok(saveBox&&saveBox.x>titleBox.x+titleBox.width&&Math.abs((saveBox.y+saveBox.height/2)-(titleBox.y+titleBox.height/2))<45,'Save action beside title at top right');
  const posts=driver.count('POST'),puts=driver.count('PUT'),deletes=driver.count('DELETE');
  await controls.click('신규');
  const draft={itemCode:'TBR-C300',itemName:'상단 버튼 신규 품목',specification:'M18x60',unit:'SET',remark:'상단 저장 영속성'};
  await driver.fill(draft);
  const response=await controls.submit('POST','/api/items');assert.ok([200,201].includes(response.status()));
  assert.deepEqual(values(response.request().postDataJSON()),draft);
  const stored=await db('after-header-save-create');const saved=verifyCreated(seeded,await response.json(),stored,draft);assert.ok(saved.id>0);
  await driver.expectGrid(stored);assert.equal(driver.count('POST'),posts+1);assert.equal(driver.count('PUT'),puts);assert.equal(driver.count('DELETE'),deletes);
  assert.deepEqual(driver.runtimeErrors,[]);assert.deepEqual(driver.forbiddenRequests,[]);
  await driver.screenshot('item-toolbar-save-create-1440.png');result={passed:true};
 }catch(error){result={passed:false,failure:String(error)};if(driver)try{await driver.screenshot('failure.png');}catch(_) {}}
 finally{
  if(driver)try{await driver.close();}catch(error){cleanupErrors.push('browser driver: '+error);}
  if(runtime)try{ownCleanup=await runtime.close();}catch(error){cleanupErrors.push('toolbar runtime: '+error);}
  const cleanup={success:regression?.cleanup?.success===true&&ownCleanup.success===true&&!cleanupErrors.length,newRegression:regression?.cleanup,toolbarRuntime:ownCleanup,errors:cleanupErrors};
  result||={passed:false,failure:'No toolbar Save result'};
  if(!cleanup.success){result.passed=false;result.failure=[result.failure,'Owned cleanup failed',...cleanupErrors].filter(Boolean).join('\n');}
  if(result.passed&&(driver.runtimeErrors.length||driver.forbiddenRequests.length)){result.passed=false;result.failure='Late runtime error or forbidden request';}
  if(result.passed){cases.push(NEW_CASE);console.log('ITEM_TOOLBAR_SAVE_CREATE_OK: '+NEW_CASE);}
  Object.assign(result,{cases,requests:driver?.requests||[],sqlProofs,runtimeErrors:driver?.runtimeErrors||[],forbiddenRequests:driver?.forbiddenRequests||[],cleanup,browserStarted:!!driver?.page,verificationMode:'browser-api-and-sql',evidence:out});
  fs.writeFileSync(path.join(out,'result.json'),JSON.stringify(result,null,2));
 }
 console.log(JSON.stringify(result));return result;
}
module.exports={verify,CASES,NEW_CASE};
if(require.main===module)verify(process.argv[2]).then(result=>{if(!result.passed)process.exitCode=1;}).catch(error=>{console.error(error);process.exitCode=1;});
