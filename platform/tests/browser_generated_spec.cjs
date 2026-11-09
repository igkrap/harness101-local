const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const bundle=JSON.parse(fs.readFileSync(process.argv[2],'utf8')),apiTarget=process.argv[3],out=process.argv[4];
const root=path.resolve(__dirname,'../../local-only'),endpoint='/api/screens/'+bundle.screen.code+'/records';
const config=JSON.parse(fs.readFileSync(path.join(process.env.HOME,'.local/share/mlx-server/browser-check/runtime.json')));
const{chromium}=require(config.playwrightModule);
(async()=>{
 const{createServer}=await import(`file://${path.join(root,'frontend/node_modules/vite/dist/node/index.js')}`);
 const server=await createServer({root:path.join(root,'frontend'),logLevel:'silent',server:{host:'127.0.0.1',port:0,strictPort:true,proxy:{'/api':{target:apiTarget,changeOrigin:true}}}});
 let browser;
 try{
  await server.listen();const base='http://127.0.0.1:'+server.httpServer.address().port;
  browser=await chromium.launch({headless:true});const page=await browser.newPage({viewport:{width:1440,height:1000}});page.setDefaultTimeout(7000);
  const errors=[],unexpected=[],writes=[];
  page.on('pageerror',error=>errors.push(error.message));
  await require('../../local-only/harness/trusted_auth.cjs').ensureAuthenticated(page.request,base,{localProxy:true});
  await page.route('**/*',route=>{
   const request=route.request(),url=new URL(request.url());
   if(!['GET','HEAD','OPTIONS'].includes(request.method())){
    if(url.pathname===endpoint||url.pathname.startsWith(endpoint+'/')) writes.push({method:request.method(),path:url.pathname,body:request.postDataJSON()});
    else{unexpected.push(request.method()+' '+url.pathname);return route.abort();}
   }
   return route.continue();
  });
  await page.goto(base);await page.getByRole('navigation',{name:'Side navigation',exact:true}).getByRole('button',{name:bundle.screen.title,exact:true}).click();
  const workspace=page.locator('[data-ui="business-workspace"]:visible'),toolbar=workspace.getByRole('toolbar',{name:'업무 버튼'}),query=workspace.locator('form[data-ui="query-panel"]'),editor=workspace.locator('form[data-ui="record-editor"]'),grid=workspace.locator('table');
  await query.getByLabel('부서',{exact:false}).waitFor();
  if(process.argv.includes('--metadata-only')){
    assert.equal(await query.getByLabel(/^이름/).isVisible(),false);
    assert.equal(await query.getByLabel(/^부서/).isVisible(),true);
    await query.getByRole('button',{name:'상세조건 펼치기',exact:true}).click();
    assert.equal(await query.getByLabel(/^이름/).isVisible(),true);
    assert.equal(await workspace.getByRole('tab',{name:bundle.screen.editorTabs[0].label,exact:true}).isVisible(),true);
    await page.screenshot({path:path.join(out,'db-revision-changed.png'),fullPage:true});
    assert.deepEqual(errors,[]);console.log(JSON.stringify({passed:true,cases:['title-from-db','query-visibility-from-db','editor-tab-from-db'],sourceChanges:0}));return;
  }
  const tag='Browser-'+Date.now();
  await query.getByLabel(/^부서/).fill(tag);await toolbar.getByRole('button',{name:'조회',exact:true}).click();
  assert.equal(await editor.getByLabel(/^이름/).inputValue(),'');
  const one={displayName:'Alpha '+tag,department:tag,email:'alpha@example.invalid',quota:10};
  const two={displayName:'Beta '+tag,department:tag,email:'beta@example.invalid',quota:50};
  async function fill(values){await editor.getByLabel(/^이름/).fill(values.displayName);await editor.getByLabel(/^부서/).fill(values.department);await editor.getByLabel(/^이메일/).fill(values.email);await editor.getByLabel(/^허용량/).fill(String(values.quota));}
  await fill(one);await toolbar.getByRole('button',{name:'저장',exact:true}).click();await grid.getByText(one.displayName,{exact:true}).waitFor();
  const repeatSave=page.waitForRequest(request=>request.method()==='PUT'&&new URL(request.url()).pathname.startsWith(endpoint+'/'));
  await toolbar.getByRole('button',{name:'저장',exact:true}).click();await repeatSave;
  await page.waitForFunction(()=>!document.querySelector('[role="toolbar"] button:last-child')?.disabled);
  assert.equal(writes.filter(write=>write.method==='POST').length,1,'Saving an already-created record must update rather than create another row');
  assert.equal(writes.filter(write=>write.method==='PUT').length,1);
  await toolbar.getByRole('button',{name:'신규',exact:true}).click();assert.equal(await editor.getByLabel(/^이름/).inputValue(),'');
  await fill(two);await toolbar.getByRole('button',{name:'저장',exact:true}).click();await grid.getByText(two.displayName,{exact:true}).waitFor();
  assert.deepEqual(writes.filter(write=>write.method==='POST').map(write=>write.body),[one,two]);
  await query.getByLabel(/^이름/).fill('Alpha');assert.equal(await editor.getByLabel(/^이름/).inputValue(),two.displayName);
  await toolbar.getByRole('button',{name:'조회',exact:true}).click();await grid.getByText(two.displayName,{exact:true}).waitFor({state:'hidden'});
  await grid.getByRole('row').filter({hasText:one.displayName}).click();
  for(const[label,key]of[[/^이름/,'displayName'],[/^부서/,'department'],[/^이메일/,'email'],[/^허용량/,'quota']])assert.equal(await editor.getByLabel(label).inputValue(),String(one[key]));
  await editor.getByLabel(/^이름/).fill('Updated '+one.displayName);await editor.getByLabel(/^허용량/).fill('37');
  await workspace.getByRole('button',{name:'편집 패널 접기',exact:true}).click();await toolbar.getByRole('button',{name:'저장',exact:true}).click();await grid.getByText('Updated '+one.displayName,{exact:true}).waitFor();
  assert.deepEqual(writes.filter(write=>write.method==='PUT').at(-1).body,{...one,displayName:'Updated '+one.displayName,quota:37});
  await query.getByLabel(/^이름/).fill('');await query.getByRole('button',{name:'상세조건 펼치기',exact:true}).click();await query.getByLabel(/^허용량/).fill('40');await toolbar.getByRole('button',{name:'조회',exact:true}).click();
  await grid.getByText('Updated '+one.displayName,{exact:true}).waitFor({state:'hidden'});await grid.getByText(two.displayName,{exact:true}).waitFor();
  await query.getByRole('button',{name:'상세조건 접기',exact:true}).click();await query.getByRole('button',{name:'상세조건 펼치기',exact:true}).click();assert.equal(await query.getByLabel(/^허용량/).inputValue(),'40');
  const q=await query.boundingBox(),g=await grid.boundingBox(),e=await workspace.locator('[data-region="editor"]').boundingBox();assert.ok(q.y+q.height<=g.y+1&&e.y>=g.y+g.height);
  const before=writes.length;await toolbar.getByRole('button',{name:'신규',exact:true}).click();await toolbar.getByRole('button',{name:'저장',exact:true}).click();await page.waitForTimeout(150);assert.equal(writes.length,before,'Invalid empty editor must not send a request');
  for(const width of[1440,1280]){await page.setViewportSize({width,height:1000});await page.screenshot({path:path.join(out,'generated-'+width+'.png'),fullPage:true});}
  assert.deepEqual(errors,[]);assert.deepEqual(unexpected,[]);
  console.log(JSON.stringify({passed:true,cases:['real-session','new-screen-code-menu','real-create-two-records','save-after-create-updates','exact-numeric-payload','new-resets-draft','query-editor-isolation','query-filter','full-row-selection','real-update','save-opens-collapsed-editor','advanced-filter','advanced-draft-retention','bottom-layout','required-editor-validation','two-widths'],realApiWrites:writes.length,unrelatedWrites:0}));
 }finally{if(browser)await browser.close();await server.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
