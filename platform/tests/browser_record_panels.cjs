const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const root = path.resolve(__dirname, '../../local-only');
const fixture = `
import React, {useState} from 'react';
import {createRoot} from 'react-dom/client';
import {Theme} from '@astryxdesign/core/theme';
import {neutralTheme} from '@astryxdesign/theme-neutral/built';
import '@astryxdesign/core/reset.css';
import '@astryxdesign/core/astryx.css';
import '@astryxdesign/theme-neutral/theme.css';
import {DataWorkspace,QueryPanel,RecordGrid,RecordEditor} from './src/framework';
const contacts=[{id:'a',name:'Alpha',quota:4,region:'east'},{id:'b',name:'Beta',quota:9,region:'west'}];
const contactFields=[{name:'name',label:'연락처명',required:true},{name:'quota',label:'허용량',type:'integer',min:0,required:true},
 {name:'region',label:'권역',render:({value,onChange,disabled})=><select aria-label="권역" value={value} disabled={disabled} onChange={e=>onChange(e.target.value)}><option value="east">동부</option><option value="west">서부</option></select>}];
window.panelEvents=[];
function Fixture(){
 const [rows,setRows]=useState(contacts),[filter,setFilter]=useState(''),[selected,setSelected]=useState(null),[fail,setFail]=useState(false);
 return <><button onClick={()=>setFail(v=>!v)}>저장 오류 전환</button><main style={{height:680,display:'flex'}}>
 <DataWorkspace query={<QueryPanel fields={[{name:'term',label:'조회어'}]} onQuery={values=>{window.panelEvents.push({kind:'query',values});setFilter(values.term)}}/>}
 results={<RecordGrid rows={rows.filter(row=>row.name.includes(filter))} columns={[{key:'name',label:'연락처'},{key:'quota',label:'한도'}]} keyField="id" onSelect={row=>setSelected({id:row.id,values:{name:row.name,quota:String(row.quota),region:row.region}})}/>}
 editor={<RecordEditor fields={contactFields} record={selected} defaults={{quota:'0',region:'east'}} onNew={()=>setSelected(null)} onSave={async(values,id)=>{
  window.panelEvents.push({kind:'contact-save',values,id});await new Promise(resolve=>setTimeout(resolve,250));
  if(fail)throw new Error('저장 거절 테스트');
  setRows(prior=>id===null?[...prior,{...values,quota:Number(values.quota),id:'new'}]:prior.map(row=>row.id===id?{...row,...values,quota:Number(values.quota)}:row));
  if(id===null)setSelected({id:'new',values:{}});
 }}/>} />
 </main><section aria-label="작업장 예제"><RecordEditor fields={[{name:'title',label:'작업장명',required:true},{name:'location',label:'위치',required:true}]} record={null} onNew={()=>{}} onSave={async(values,id)=>{window.panelEvents.push({kind:'site-save',values,id})}}/></section></>;
}
createRoot(document.getElementById('root')).render(<Theme theme={neutralTheme}><Fixture/></Theme>);
`;

async function verify(browser, project = root) {
  const frontend = path.join(project, 'frontend');
  const virtualFile = path.join(frontend, '__record_panel_fixture__.tsx');
  const {createServer} = await import(`file://${path.join(frontend, 'node_modules/vite/dist/node/index.js')}`);
  const server = await createServer({root: frontend, logLevel: 'silent', server: {host:'127.0.0.1',port:0,strictPort:true}, plugins:[{
    name:'record-panel-fixture',
    resolveId(id){if(id==='/__record_panel_fixture__.tsx'||id===virtualFile)return virtualFile;},
    load(id){if(id===virtualFile)return fixture;},
    configureServer(vite){vite.middlewares.use(async(req,res,next)=>{
      if(req.url!=='/fixture.html')return next();
      const html=await vite.transformIndexHtml('/fixture.html','<!doctype html><html><body><div id="root"></div><script type="module" src="/__record_panel_fixture__.tsx"></script></body></html>');
      res.setHeader('Content-Type','text/html');res.end(html);
    });},
  }]});
  let page;
  try {
    await server.listen();
    await server.transformRequest('/__record_panel_fixture__.tsx');
    const base = `http://127.0.0.1:${server.httpServer.address().port}`;
    page = await browser.newPage({viewport:{width:1440,height:1100}});
    page.setDefaultTimeout(5000);
    const errors=[];
    page.on('pageerror',error=>errors.push(error.message));
    page.on('console',message=>{if(message.type()==='error')errors.push(message.text());});
    await page.goto(base+'/fixture.html');
    const query=page.locator('main form[data-ui="query-panel"]');
    const editor=page.locator('main form[data-ui="record-editor"]');
    const grid=page.locator('main table');
    await editor.getByLabel('연락처명').waitFor().catch(async error=>{throw new Error(error.message+'\nBrowser errors: '+errors.join('\n')+'\n'+(await page.content()).slice(0,1800));});
    await query.getByLabel('조회어').fill('Beta');
    assert.equal(await editor.getByLabel('연락처명').inputValue(),'');
    await query.getByLabel('조회어').press('Enter');
    await grid.getByRole('row').filter({hasText:'Beta'}).click();
    await page.waitForFunction(()=>document.querySelector('main form[data-ui="record-editor"] input')?.value==='Beta');
    assert.equal(await editor.getByLabel('허용량').inputValue(),'9');
    assert.equal(await editor.getByLabel('권역').inputValue(),'west');
    await editor.getByLabel('연락처명').fill('Changed Beta');
    await query.getByRole('button',{name:'조건 지우기',exact:true}).click();
    assert.equal(await editor.getByLabel('연락처명').inputValue(),'Changed Beta');
    await editor.getByLabel('허용량').fill('-1');
    await editor.getByRole('button',{name:'저장',exact:true}).click();
    assert.equal(await editor.getByRole('alert').count(),1);
    assert.equal(await page.evaluate(()=>window.panelEvents.filter(e=>e.kind==='contact-save').length),0);
    await editor.getByLabel('허용량').fill('12');
    await editor.getByLabel('권역').selectOption('east');
    await editor.evaluate(form=>{form.requestSubmit();form.requestSubmit();});
    assert.equal(await editor.getByLabel('권역').isDisabled(),true);
    await editor.getByRole('status').filter({hasText:'저장되었습니다.'}).waitFor();
    let saves=await page.evaluate(()=>window.panelEvents.filter(e=>e.kind==='contact-save'));
    assert.deepEqual(saves,[{kind:'contact-save',values:{name:'Changed Beta',quota:'12',region:'east'},id:'b'}]);
    await page.waitForFunction(()=>![...document.querySelectorAll('main form[data-ui="record-editor"] input')].some(i=>i.disabled));
    await editor.getByLabel('허용량').fill('3');
    await grid.getByRole('row').filter({hasText:'Changed Beta'}).click();
    await page.waitForFunction(()=>document.querySelector('main form[data-ui="record-editor"] input[type]:not([type="text"]), main form[data-ui="record-editor"] input:nth-of-type(1)')!==null);
    assert.equal(await editor.getByLabel('허용량').inputValue(),'12');
    await editor.getByRole('button',{name:'신규',exact:true}).click();
    assert.equal(await editor.getByLabel('연락처명').inputValue(),'');
    assert.equal(await editor.getByLabel('허용량').inputValue(),'0');
    await editor.getByLabel('연락처명').fill('Gamma');
    await page.getByRole('button',{name:'저장 오류 전환'}).click();
    await editor.getByRole('button',{name:'추가',exact:true}).click();
    await editor.getByRole('alert').filter({hasText:'저장 거절 테스트'}).waitFor();
    assert.equal(await editor.getByLabel('연락처명').inputValue(),'Gamma');
    await page.getByRole('button',{name:'저장 오류 전환'}).click();
    await editor.getByRole('button',{name:'추가',exact:true}).click();
    await editor.getByRole('status').filter({hasText:'저장되었습니다.'}).waitFor();
    saves=await page.evaluate(()=>window.panelEvents.filter(e=>e.kind==='contact-save'));
    assert.equal(saves.length,3);
    assert.equal(saves[2].id,null);
    assert.equal(saves[2].values.name,'Gamma');
    assert.equal(await editor.getByLabel('연락처명').inputValue(),'Gamma');
    assert.equal(await editor.getAttribute('aria-label'),'수정');
    await editor.getByLabel('허용량').fill('7');
    await page.getByRole('button',{name:'저장 오류 전환'}).click();
    await page.getByRole('button',{name:'저장 오류 전환'}).click();
    assert.equal(await editor.getByLabel('허용량').inputValue(),'7');
    assert.equal(await editor.getByRole('status').filter({hasText:'저장되었습니다.'}).count(),1);
    const site=page.getByRole('region',{name:'작업장 예제'});
    await site.getByLabel('작업장명').fill('센터');
    await site.getByLabel('위치').fill('서울');
    await site.getByRole('button',{name:'추가',exact:true}).click();
    await site.getByRole('status').filter({hasText:'저장되었습니다.'}).waitFor();
    assert.deepEqual(await page.evaluate(()=>window.panelEvents.filter(e=>e.kind==='site-save')),[{kind:'site-save',values:{title:'센터',location:'서울'},id:null}]);
    for(const width of [1440,1280]){
      await page.setViewportSize({width,height:1100});
      const left=await page.locator('[data-region="left"]').boundingBox(),right=await page.locator('[data-region="editor"]').boundingBox();
      const q=await query.boundingBox(),g=await grid.boundingBox();
      assert.ok(left.width>right.width && left.x+left.width<=right.x);
      assert.ok(q.y+q.height<=g.y+1 && q.height<180);
    }
    const divider=page.locator('main [role="separator"]').first();
    await divider.focus();
    await divider.press('Home');
    assert.equal(await divider.getAttribute('aria-valuenow'),'20');
    await divider.press('End');
    assert.equal(await divider.getAttribute('aria-valuenow'),'80');
    await divider.press('ArrowLeft');
    assert.equal(await divider.getAttribute('aria-valuenow'),'78');
    const pane=await page.locator('main [data-ui="split-pane"]').first().boundingBox();
    const handle=await divider.boundingBox();
    await page.mouse.move(handle.x+handle.width/2,handle.y+handle.height/2);
    await page.mouse.down();
    await page.mouse.move(pane.x+pane.width/2,handle.y+handle.height/2,{steps:5});
    await page.mouse.up();
    assert.ok(Math.abs(Number(await divider.getAttribute('aria-valuenow'))-50)<=1);
    assert.deepEqual(errors,[]);
    return {passed:true,domains:['contacts','work-sites'],cases:['query-isolation','filtered-selection','draft-retention','validation','duplicate-submit','custom-control','update','reselect-reloads','create','saved-new-keeps-draft','error-retry','two-layout-widths','split-keyboard','split-pointer']};
  } finally {
    if(page)await page.close();
    await server.close();
  }
}
module.exports={verify};
if(require.main===module){
  const config=JSON.parse(fs.readFileSync(path.join(process.env.HOME,'.local/share/mlx-server/browser-check/runtime.json')));
  const {chromium}=require(config.playwrightModule);
  (async()=>{const browser=await chromium.launch({headless:true});try{console.log(JSON.stringify(await verify(browser)));}finally{await browser.close();}})().catch(error=>{console.error(error);process.exitCode=1;});
}
