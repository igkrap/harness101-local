// Shared infrastructure for new item browser acceptance stages. No application writes.
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const queryOracle=require('./browser_item_query.cjs');
const {trustedRequest,within}=require('./browser_item_api_query.cjs');
const {ensureAuthenticated}=require('../../local-only/harness/trusted_auth.cjs');
const {errorReasons}=require('./browser_item_create_ui.cjs');
const ROOT=path.resolve(__dirname,'../../local-only');
const FIELDS=['itemCode','itemName','specification','unit','remark'],LABELS=['품번','품명','규격','단위','비고'];
function classifyItemRequest(request,base,permissions={}) {
 const url=new URL(request.url);
 if(url.username||url.password)return 'forbidden';
 if(url.origin===base&&!url.username&&!url.password) {
  if(permissions.post&&request.method==='POST'&&url.pathname==='/api/items')return 'allow';
  const match=/^\/api\/items\/([1-9][0-9]*)$/.exec(url.pathname);
  if(match&&Number.isSafeInteger(Number(match[1]))&&((permissions.put&&request.method==='PUT')||(permissions.delete&&request.method==='DELETE')))return 'allow';
 }
 return queryOracle.classifyRequest(request,base);
}
class ItemBrowserDriver {
 constructor(output,permissions={}) {this.output=output;this.permissions=permissions;this.requests=[];this.runtimeErrors=[];this.forbiddenRequests=[];}
 async start(backendBase) {
  trustedRequest({},backendBase,[]);
  const config=JSON.parse(fs.readFileSync(path.join(process.env.HOME,'.local/share/mlx-server/browser-check/runtime.json'),'utf8'));
  const {chromium}=require(config.playwrightModule);
  const {createServer}=await import(`file://${path.join(ROOT,'frontend/node_modules/vite/dist/node/index.js')}`);
  this.server=await createServer({root:path.join(ROOT,'frontend'),logLevel:'silent',server:{host:'127.0.0.1',port:0,strictPort:true,proxy:{'/api':{target:backendBase,changeOrigin:true}}}});
  await this.server.listen();this.base='http://127.0.0.1:'+this.server.httpServer.address().port;
  this.browser=await chromium.launch({headless:true});this.page=await this.browser.newPage({viewport:{width:1440,height:1000}});this.page.setDefaultTimeout(7000);
  this.page.on('pageerror',error=>this.runtimeErrors.push(error.message));
  assert.equal(await ensureAuthenticated(this.page.request,this.base,{localProxy:true}),true);
  await this.page.route('**/*',route=>{
   const req=route.request(),url=new URL(req.url()),entry={method:req.method(),path:url.pathname+url.search};
   const category=classifyItemRequest({url:req.url(),method:req.method(),resourceType:req.resourceType()},this.base,this.permissions);
   if(category!=='allow'){if(category==='forbidden')this.forbiddenRequests.push(entry);return route.abort();}
   if(url.pathname.startsWith('/api/'))this.requests.push(entry);return route.continue();
  });
 }
 async open() {
  await this.page.goto(this.base);const meta=await this.page.evaluate(async()=>(await import('/src/screens/ItemMaster.tsx')).meta);assert.equal(meta.code,'MST0001');
  const nav=this.page.getByRole('navigation',{name:'Side navigation',exact:true}),expand=nav.getByRole('button',{name:'Expand sidebar',exact:true});if(await expand.isVisible())await expand.click();
  await nav.getByRole('button',{name:meta.title,exact:true}).click();this.screen=this.page.getByRole('tabpanel',{name:meta.title,exact:true});
  this.editor=this.screen.locator('form[data-ui="record-editor"]');this.query=this.screen.locator('form[data-ui="query-panel"]');this.grid=this.screen.locator('table');await this.editor.waitFor();
 }
 async queryAll() {
  await this.query.getByLabel(/^품번/).fill('');const name=this.query.getByLabel(/^품명/);if(!await name.isVisible())await this.query.getByRole('button',{name:/상세.*조건/}).click();await name.fill('');
  const local=this.query.getByRole('button',{name:'조회',exact:true});const button=await local.count()?local:this.screen.getByRole('toolbar',{name:'업무 버튼',exact:true}).getByRole('button',{name:'조회',exact:true});
  const [response]=await Promise.all([this.page.waitForResponse(r=>new URL(r.url()).origin===this.base&&new URL(r.url()).pathname==='/api/items'&&r.request().method()==='GET'),button.click()]);assert.equal(response.status(),200);return queryOracle.canonicalRows(await response.json());
 }
 async select(code) {
  const row=this.grid.getByRole('row').filter({has:this.page.getByRole('cell',{name:code,exact:true})});assert.equal(await row.count(),1,'Select a unique persisted item');
  const button=row.getByRole('button',{name:'선택',exact:true});if(await button.count())await button.click();else await row.click();
 }
 async values() {return Object.fromEntries(await Promise.all(FIELDS.map(async(key,i)=>[key,await this.editor.getByLabel(new RegExp('^'+LABELS[i])).inputValue()])));}
 async fill(values) {for(let i=0;i<FIELDS.length;i++)await this.editor.getByLabel(new RegExp('^'+LABELS[i])).fill(values[FIELDS[i]]??'');}
 async clickSave() {const local=this.editor.getByRole('button',{name:'저장',exact:true});const button=await local.count()?local:this.screen.getByRole('toolbar',{name:'업무 버튼',exact:true}).getByRole('button',{name:'저장',exact:true});await button.click();}
 async saveResponse(method,pathname) {
  const [response]=await Promise.all([this.page.waitForResponse(r=>new URL(r.url()).origin===this.base&&new URL(r.url()).pathname===pathname&&r.request().method()===method),this.clickSave()]);return response;
 }
 count(method) {return this.requests.filter(r=>r.method===method&&/^\/api\/items(?:\/[0-9]+)?(?:\?|$)/.test(r.path)).length;}
 async gridRows() {
  const headers=(await this.grid.getByRole('columnheader').allTextContents()).map(s=>s.trim()),indices=LABELS.map(label=>headers.indexOf(label));assert.ok(indices.every(i=>i>=0));const rows=[];
  for(const row of await this.grid.getByRole('row').all()){const cells=row.getByRole('cell');if(await cells.count()<=Math.max(...indices))continue;const values=(await cells.allTextContents()).map(s=>s.trim());rows.push(Object.fromEntries(FIELDS.map((key,i)=>[key,values[indices[i]]])));}
  return queryOracle.displayRows(rows);
 }
 async expectGrid(rows) {const wanted=queryOracle.displayRows(rows);let actual;for(let i=0;i<80;i++){actual=await this.gridRows();if(JSON.stringify(actual)===JSON.stringify(wanted))return;await this.pause(50);}assert.deepEqual(actual,wanted,'Rendered grid must match owned SQL');}
 async text() {return this.page.locator('body').innerText();}
 async pause(ms) {await this.page.waitForTimeout(ms);}
 async expectError(response,before) {
  const reasons=errorReasons(await response.text());assert.ok(reasons.length,'Server must supply an error reason');
  const explained=after=>reasons.some(reason=>!before.includes(reason)&&after.includes(reason))||(/중복|이미.*존재|already exists|duplicate|conflict/i.test(after)&&!/중복|이미.*존재|already exists|duplicate|conflict/i.test(before));
  let after='';for(let i=0;i<80;i++){after=await this.text();if(explained(after))return;await this.pause(50);}assert.ok(explained(after),'Display a new server rejection explanation');
 }
 async screenshot(name) {if(this.page)await this.page.screenshot({path:path.join(this.output,name),fullPage:true,timeout:5000});}
 async close() {const errors=[];if(this.browser)try{await within(this.browser.close(),15000,'Browser cleanup timeout');}catch(e){errors.push('browser: '+e);}if(this.server)try{await within(this.server.close(),10000,'Preview cleanup timeout');}catch(e){errors.push('preview: '+e);}if(errors.length)throw Error(errors.join('\n'));}
}
module.exports={ItemBrowserDriver,classifyItemRequest,FIELDS,LABELS};
