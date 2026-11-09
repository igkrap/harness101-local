// Common toolbar integration; retain the preceding eighteen actual browser cases.
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const prior=require('./browser_item_delete_ui.cjs');
const {ItemRuntime}=require('./item_crud_runtime_client.cjs');
const {ItemBrowserDriver,FIELDS}=require('./item_browser_driver.cjs');
const {canonicalRows,querySql}=require('./browser_item_query.cjs');
const {verifySavedUpdate}=require('./browser_item_update_ui.cjs');
const NEW_CASES=['common-header-query-and-always-reset-new','header-save-create-and-repeat-update','collapsed-header-save-and-required-validation','toolbar-reload-and-owned-resources-cleanup'];
const CASES=[...prior.CASES,...NEW_CASES];
const values=row=>Object.fromEntries(FIELDS.map(key=>[key,row[key]??'']));
function verifyCreated(before,value,stored,expected){
 const saved=canonicalRows([value])[0];assert.ok(Number.isSafeInteger(saved.id)&&saved.id>0&&!before.some(r=>r.id===saved.id),'POST returns a new positive numeric identity');
 assert.deepEqual(values(saved),expected);assert.deepEqual(stored,[...before,saved].sort((a,b)=>a.id-b.id),'POST inserts exactly one row and preserves other values');return saved;
}
class ToolbarControls {
 constructor(driver){this.d=driver;}
 button(label){return this.d.screen.getByRole('toolbar',{name:'업무 버튼',exact:true}).getByRole('button',{name:label,exact:true});}
 async layout(){
  const heading=this.d.screen.getByRole('heading',{name:'품목 등록',exact:true});const box=await heading.boundingBox();assert.ok(box);
  assert.ok(await heading.evaluate(e=>parseFloat(getComputedStyle(e).fontSize))<=18,'Compact screen title');
  for(const label of ['조회','신규','삭제','저장']){
   const button=this.button(label);await button.waitFor({state:'visible'});const b=await button.boundingBox();assert.ok(b&&b.x>box.x+box.width&&Math.abs((b.y+b.height/2)-(box.y+box.height/2))<45,'Common actions beside the title at top right');
  }
 }
 async click(label){await this.button(label).click();}
 async conditions(code,name){
  await this.d.query.getByLabel(/^품번/).fill(code);const input=this.d.query.getByLabel(/^품명/);
  if(!await input.isVisible())await this.d.query.getByRole('button',{name:/상세.*조건/}).click();await input.fill(name);
 }
 async submit(method,pathname,label='저장'){
  const [response]=await Promise.all([this.d.page.waitForResponse(r=>new URL(r.url()).origin===this.d.base&&new URL(r.url()).pathname===pathname&&r.request().method()===method),this.click(label)]);return response;
 }
 async collapse(){await this.d.screen.getByRole('button',{name:'편집 패널 접기',exact:true}).click();assert.equal(await this.d.editor.isVisible(),false);}
 async revealed(){await this.d.editor.waitFor({state:'visible'});}
 async requiredVisible(){
  const input=this.d.editor.getByLabel(/^품명/);assert.equal(await input.isVisible(),true);
  const observed=await input.evaluate(e=>({invalid:e.getAttribute('aria-invalid')==='true'||!e.validity.valid,validation:e.validationMessage}));
  const alerts=this.d.editor.getByRole('alert');let explained=observed.invalid||!!observed.validation;
  for(const alert of await alerts.all())if(await alert.isVisible()&&(await alert.innerText()).trim())explained=true;
  assert.ok(explained,'Reveal a visible required-field validation indication');
 }
}
async function verify(output,infrastructure={}){
 const out=path.resolve(output);fs.mkdirSync(out,{recursive:true});const cases=[],sqlProofs=[],cleanupErrors=[];
 const Runtime=infrastructure.Runtime||ItemRuntime,Driver=infrastructure.Driver||ItemBrowserDriver,Controls=infrastructure.Controls||ToolbarControls;
 let regression,runtime,driver,controls,result;let ownedCleanup={success:true,started:false};
 const passed=name=>{assert.ok(NEW_CASES.includes(name));cases.push(name);console.log('ITEM_TOOLBAR_UI_OK: '+name);};
 try{
  regression=await(infrastructure.priorVerify||prior.verify)(path.join(out,'delete-regression'));
  assert.ok(regression?.passed===true&&regression?.cleanup?.success===true,'Unchanged eighteen-case CRUD browser regression must pass');assert.deepEqual([...regression.cases].sort(),[...prior.CASES].sort());cases.push(...regression.cases);
  runtime=new Runtime(path.join(out,'runtime'));const backend=await runtime.start();
  async function db(label,conditions){const rows=canonicalRows(await runtime.rows(querySql(conditions)));sqlProofs.push({label,rows});return rows;}
  assert.deepEqual(await db('fresh-toolbar-database'),[]);const seeded=canonicalRows(await runtime.seedQueryFixture());assert.equal(seeded.length,2);assert.deepEqual(await db('fixed-toolbar-fixture'),seeded);
  driver=new Driver(out,{post:true,put:true,delete:true});await driver.start(backend.base_url);await driver.open();controls=new Controls(driver);assert.deepEqual(await driver.queryAll(),seeded);await driver.expectGrid(seeded);await controls.layout();
  const gets=driver.count('GET'),posts=driver.count('POST'),puts=driver.count('PUT'),deletes=driver.count('DELETE');
  await controls.conditions('-10','볼');await driver.pause(300);assert.equal(driver.count('GET'),gets,'Typing conditions alone must not query');
  const query=await controls.submit('GET','/api/items','조회');assert.equal(query.status(),200);const params=new URL(query.url()).searchParams;assert.equal(params.get('itemCode'),'-10');assert.equal(params.get('itemName'),'볼');
  const filtered=await db('header-query-and-filter',{itemCode:'-10',itemName:'볼'});assert.equal(filtered.length,1);assert.deepEqual(canonicalRows(await query.json()),filtered);await driver.expectGrid(filtered);
  await controls.conditions('','');assert.equal((await controls.submit('GET','/api/items','조회')).status(),200);await driver.expectGrid(seeded);
  await driver.select(seeded[0].itemCode);const dirty={itemCode:'DIRTY',itemName:'미저장 초안',specification:'M30',unit:'EA',remark:'초기화 대상'};await driver.fill(dirty);await controls.collapse();await controls.click('신규');await controls.revealed();
  const empty=Object.fromEntries(FIELDS.map(k=>[k,'']));assert.deepEqual(await driver.values(),empty,'New clears an existing selection and all five draft fields');
  assert.equal(await controls.button('삭제').isDisabled(),true);await driver.fill(dirty);await controls.click('신규');assert.deepEqual(await driver.values(),empty,'Repeated New also clears an already-new draft');
  assert.equal(driver.count('POST'),posts);assert.equal(driver.count('PUT'),puts);assert.equal(driver.count('DELETE'),deletes);assert.deepEqual(await db('header-new-does-not-write'),seeded);passed(NEW_CASES[0]);
  const createdValues={itemCode:'TBR-C300',itemName:'상단 버튼 신규 품목',specification:'M18x60',unit:'SET',remark:'상단 저장 영속성'};await driver.fill(createdValues);
  const created=await controls.submit('POST','/api/items');assert.ok([200,201].includes(created.status()));assert.deepEqual(values(created.request().postDataJSON()),createdValues);
  const saved=verifyCreated(seeded,await created.json(),await db('toolbar-created'),createdValues);let stored=await db('after-toolbar-create');await driver.expectGrid(stored);assert.equal(driver.count('POST'),posts+1);
  const id=saved.id,endpoint='/api/items/'+id,edited={...createdValues,itemName:'동일 ID 재저장',specification:'M20x70',unit:'BOX',remark:'POST 이후 PUT'};await driver.fill(edited);
  async function saveUpdate(label,expected){
   const before=await db(label+'-before'),count=driver.count('PUT'),response=await controls.submit('PUT',endpoint);assert.equal(response.status(),200);assert.deepEqual(values(response.request().postDataJSON()),expected);
   const row=verifySavedUpdate(before,await response.json(),await db(label+'-after'),id,expected);assert.equal(driver.count('PUT'),count+1);assert.equal(driver.count('POST'),posts+1,'Further save must update, never POST again');await driver.expectGrid(await db(label+'-grid'));return row;
  }
  await saveUpdate('new-record-next-save',edited);await saveUpdate('new-record-repeat-save',edited);stored=await db('after-repeat');passed(NEW_CASES[1]);
  const collapsed={...edited,itemName:'접힌 패널의 현재 초안',specification:'M24x80',remark:'접혀도 저장'};await driver.fill(collapsed);await controls.collapse();await saveUpdate('collapsed-header-save',collapsed);await controls.revealed();stored=await db('after-collapsed-save');
  await driver.fill({...collapsed,itemName:'   '});await controls.collapse();const invalidPuts=driver.count('PUT');await controls.click('저장');await controls.revealed();await driver.pause(300);await controls.requiredVisible();
  assert.equal(driver.count('PUT'),invalidPuts,'Invalid required draft must not send PUT');assert.equal(driver.count('POST'),posts+1);assert.deepEqual(await db('collapsed-required-preserves-data'),stored);await driver.expectGrid(stored);passed(NEW_CASES[2]);
  await driver.open();assert.deepEqual(await driver.queryAll(),stored);await driver.expectGrid(stored);assert.deepEqual(await db('toolbar-reload-persistence'),stored);assert.equal(driver.count('POST'),posts+1);assert.equal(driver.count('PUT'),puts+3);assert.equal(driver.count('DELETE'),deletes);
  assert.deepEqual(driver.runtimeErrors,[]);assert.deepEqual(driver.forbiddenRequests,[]);await driver.screenshot('item-toolbar-1440.png');result={passed:true};
 }catch(e){result={passed:false,failure:String(e)};if(driver)try{await driver.screenshot('failure.png');}catch(_) {}}
 finally{
  if(driver)try{await driver.close();}catch(e){cleanupErrors.push('browser driver: '+e);}
  if(runtime)try{ownedCleanup=await runtime.close();}catch(e){cleanupErrors.push('toolbar runtime: '+e);}
  const cleanup={success:regression?.cleanup?.success===true&&ownedCleanup.success===true&&!cleanupErrors.length,deleteRegression:regression?.cleanup,toolbarRuntime:ownedCleanup,errors:cleanupErrors};result||={passed:false,failure:'No toolbar result'};
  if(!cleanup.success){result.passed=false;result.failure=[result.failure,'Owned cleanup failed',...cleanupErrors].filter(Boolean).join('\n');}
  if(result.passed&&(driver.runtimeErrors.length||driver.forbiddenRequests.length)){result.passed=false;result.failure='Late runtime error or forbidden request';}
  if(result.passed)passed(NEW_CASES[3]);Object.assign(result,{cases,requests:driver?.requests||[],sqlProofs,runtimeErrors:driver?.runtimeErrors||[],forbiddenRequests:driver?.forbiddenRequests||[],cleanup,browserStarted:!!driver?.page,verificationMode:'browser-api-and-sql',evidence:out});fs.writeFileSync(path.join(out,'result.json'),JSON.stringify(result,null,2));
 }
 console.log(JSON.stringify(result));return result;
}
module.exports={verify,CASES,NEW_CASES,ToolbarControls,verifyCreated};
if(require.main===module)verify(process.argv[2]).then(r=>{if(!r.passed)process.exitCode=1;}).catch(e=>{console.error(e);process.exitCode=1;});
