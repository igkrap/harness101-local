// Verify the deployed 5292/8083 site against live SQL with one owned item.
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),crypto=require('node:crypto'),cp=require('node:child_process');
const {ItemBrowserDriver,classifyItemRequest}=require('./item_browser_driver.cjs');
const {ToolbarControls}=require('./browser_item_toolbar_ui.cjs');
const {confirmDelete}=require('./item_delete_confirmation.cjs');
const {ensureAuthenticated}=require('../../local-only/harness/trusted_auth.cjs');
const base='http://127.0.0.1:5292';
function sqlRows(code){
 const sql=`SELECT row_to_json(t) FROM (SELECT id, item_code AS "itemCode", item_name AS "itemName", COALESCE(specification,'') AS specification, COALESCE(unit,'') AS unit, COALESCE(remark,'') AS remark FROM items WHERE item_code='${code}' ORDER BY id) t;`;
 const text=cp.execFileSync('docker',['exec','-i','mdi-db','sh','-c','psql -U "$POSTGRES_USER" -d mdi_local -At'],{input:sql,encoding:'utf8',timeout:10000});
 return text.trim()?text.trim().split('\n').map(line=>JSON.parse(line)):[];
}
async function verify(output){
 const out=path.resolve(output);fs.mkdirSync(out,{recursive:true});const code='LIVE-'+crypto.randomBytes(5).toString('hex').toUpperCase();
 const driver=new ItemBrowserDriver(out,{post:true,put:true,delete:true});let result,cleanup={success:false},createdId=null;
 try{
  assert.deepEqual(sqlRows(code),[]);
  const config=JSON.parse(fs.readFileSync(path.join(process.env.HOME,'.local/share/mlx-server/browser-check/runtime.json'),'utf8'));
  const {chromium}=require(config.playwrightModule);
  driver.base=base;driver.browser=await chromium.launch({headless:true});driver.page=await driver.browser.newPage({viewport:{width:1440,height:1000}});driver.page.setDefaultTimeout(7000);
  driver.page.on('pageerror',error=>driver.runtimeErrors.push(error.message));
  assert.equal(await ensureAuthenticated(driver.page.request,base),true);
  await driver.page.route('**/*',route=>{
   const request=route.request(),url=new URL(request.url()),entry={method:request.method(),path:url.pathname+url.search};
   const category=classifyItemRequest({url:request.url(),method:request.method(),resourceType:request.resourceType()},base,driver.permissions);
   if(category!=='allow'){if(category==='forbidden')driver.forbiddenRequests.push(entry);return route.abort();}
   if(url.pathname.startsWith('/api/'))driver.requests.push(entry);return route.continue();
  });
  await driver.open();const controls=new ToolbarControls(driver);
  const original=await driver.queryAll();await driver.expectGrid(original);
  const initialCount=original.length;
  await controls.click('신규');
  const draft={itemCode:code,itemName:'실사이트 검증 품목',specification:'M12',unit:'EA',remark:'자동 정리 대상'};await driver.fill(draft);
  const created=await controls.submit('POST','/api/items');assert.ok([200,201].includes(created.status()));
  const returned=await created.json();createdId=returned.id;assert.ok(Number.isSafeInteger(createdId)&&createdId>0);
  assert.equal(sqlRows(code).length,1);assert.equal(sqlRows(code)[0].id,createdId);
  const edited={...draft,itemName:'실사이트 수정 품목',specification:'M16',remark:'PUT 검증'};await driver.fill(edited);
  const updated=await controls.submit('PUT','/api/items/'+createdId);assert.equal(updated.status(),200);
  const dbUpdated=sqlRows(code);assert.equal(dbUpdated.length,1);assert.equal(dbUpdated[0].id,createdId);assert.equal(dbUpdated[0].itemName,edited.itemName);
  await driver.page.setViewportSize({width:1280,height:800});await driver.screenshot('live-item-1280.png');
  await driver.select(code);
  const remove=controls.button('삭제'),response=driver.page.waitForResponse(r=>new URL(r.url()).pathname==='/api/items/'+createdId&&r.request().method()==='DELETE');
  await confirmDelete(driver.page,remove,true);assert.ok([200,204].includes((await response).status()));
  assert.deepEqual(sqlRows(code),[]);createdId=null;
  await driver.open();const after=await driver.queryAll();assert.equal(after.length,initialCount);await driver.expectGrid(original);
  assert.deepEqual(driver.runtimeErrors,[]);assert.deepEqual(driver.forbiddenRequests,[]);
  result={passed:true,code,initialCount,postCount:driver.count('POST'),putCount:driver.count('PUT'),deleteCount:driver.count('DELETE')};
 }catch(error){result={passed:false,code,failure:String(error)};if(driver.page)try{await driver.screenshot('failure.png');}catch(_) {}}
 finally{
  const errors=[];
  if(driver.page)try{
   const rows=sqlRows(code);
   if(rows.length){
    const session=await(await driver.page.request.get(base+'/api/auth/session')).json();
    for(const row of rows){
     const response=await driver.page.request.delete(base+'/api/items/'+row.id,{headers:{[session.csrf.headerName]:session.csrf.token}});
     if(!response.ok())errors.push('Owned item cleanup HTTP '+response.status());
    }
   }
   if(sqlRows(code).length)errors.push('Owned item remained in live SQL');
  }catch(error){errors.push('Owned cleanup: '+error);}
  try{await driver.close();}catch(error){errors.push('Browser cleanup: '+error);}
  cleanup={success:!errors.length,errors};
  if(!cleanup.success){result.passed=false;result.failure=[result.failure,...errors].filter(Boolean).join('\n');}
  Object.assign(result,{cleanup,runtimeErrors:driver.runtimeErrors,forbiddenRequests:driver.forbiddenRequests,requests:driver.requests,evidence:out});
  fs.writeFileSync(path.join(out,'result.json'),JSON.stringify(result,null,2));
 }
 console.log(JSON.stringify(result));return result;
}
module.exports={verify};
if(require.main===module)verify(process.argv[2]).then(result=>{if(!result.passed)process.exitCode=1;}).catch(error=>{console.error(error);process.exitCode=1;});
