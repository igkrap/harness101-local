const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {openFixture}=require('./vite_fixture.cjs');
const source=`
import React,{useState} from 'react';import{createRoot}from'react-dom/client';
import{Theme}from'@astryxdesign/core/theme';import{neutralTheme}from'@astryxdesign/theme-neutral/built';
import'@astryxdesign/core/reset.css';import'@astryxdesign/core/astryx.css';import'@astryxdesign/theme-neutral/theme.css';
import{BusinessWorkspace,QueryPanel,RecordEditor,RecordGrid}from'./src/framework';
window.workspaceEvents=[];
function Notes(){const[value,setValue]=useState('');return <label>메모<textarea value={value} onChange={event=>setValue(event.target.value)}/></label>;}
function Fixture(){
 const initial=[{id:1,name:'Alpha'},{id:2,name:'Beta'}];
 const[rows,setRows]=useState(initial),[selected,setSelected]=useState(null),[reset,setReset]=useState(0),[collapsed,setCollapsed]=useState(false);
 function fresh(){setSelected(null);setReset(value=>value+1);window.workspaceEvents.push({kind:'new'});}
 const actions={query:{form:'fixture-query'},create:{onClick:fresh},remove:{disabled:!selected,confirm:'선택한 항목을 삭제할까요?',onClick:()=>{window.workspaceEvents.push({kind:'delete',id:selected?.id});fresh();}},save:{form:'fixture-editor'},print:{onClick:()=>{window.workspaceEvents.push({kind:'print'});}}};
 return <main style={{height:'100vh',padding:16,boxSizing:'border-box',display:'flex'}}><BusinessWorkspace title="업무 예제" actions={actions} editorCollapsed={collapsed} onEditorCollapsedChange={setCollapsed}
 query={<QueryPanel formId="fixture-query" showActions={false} fields={[{name:'name',label:'조회 이름'}]} advancedFields={[{name:'category',label:'상세 분류'},{name:'company',label:'필수 사업장',required:true}]} initialValues={{company:'본사'}} onQuery={values=>{window.workspaceEvents.push({kind:'query',values});setRows(initial.filter(row=>row.name.includes(values.name)));}}/>}
 results={<RecordGrid rows={rows} columns={[{key:'name',label:'이름'}]} keyField="id" onSelect={row=>{setSelected({id:row.id,values:{name:row.name}});setCollapsed(false);}}/>}
 editorTabs={[{id:'basic',label:'기본정보',content:<RecordEditor formId="fixture-editor" showActions={false} compact fields={[{name:'name',label:'편집 이름',required:true}]} record={selected} resetKey={reset} onNew={fresh} onSave={async(values,id)=>{window.workspaceEvents.push({kind:'save',values,id});await new Promise(resolve=>setTimeout(resolve,120));}}/>},{id:'notes',label:'메모',content:<Notes/>}]}/></main>;
}
createRoot(document.getElementById('root')).render(<Theme theme={neutralTheme}><Fixture/></Theme>);
`;

async function verify(browser,project){
 const fixture=await openFixture(browser,source,{project});const{page,errors}=fixture;
 try{
  const toolbar=page.getByRole('toolbar',{name:'업무 버튼'}),query=page.locator('form[data-ui="query-panel"]'),editor=page.locator('form[data-ui="record-editor"]');
  await query.getByLabel('조회 이름').waitFor();
  assert.equal(await query.getByLabel('필수 사업장').isVisible(),true);
  assert.equal(await query.getByLabel('상세 분류').isVisible(),false);
  await query.getByRole('button',{name:'상세조건 펼치기'}).click();
  await query.getByLabel('상세 분류').fill('보관할 상세조건');
  await query.getByRole('button',{name:'상세조건 접기'}).click();
  assert.equal(await query.getByLabel('필수 사업장').isVisible(),true);
  await query.getByLabel('조회 이름').fill('Beta');
  await toolbar.getByRole('button',{name:'조회',exact:true}).click();
  await page.locator('table').getByText('Alpha',{exact:true}).waitFor({state:'hidden'});
  assert.equal((await page.evaluate(()=>window.workspaceEvents.find(event=>event.kind==='query'))).values.category,'보관할 상세조건');
  await query.getByRole('button',{name:'상세조건 펼치기'}).click();
  assert.equal(await query.getByLabel('상세 분류').inputValue(),'보관할 상세조건');
  await query.getByRole('button',{name:'상세조건 접기'}).click();
  await page.locator('table tbody tr').first().click();
  await editor.getByLabel('편집 이름').fill('편집 중인 값');
  await page.getByRole('tab',{name:'메모',exact:true}).click();
  await page.getByRole('textbox',{name:'메모',exact:true}).fill('탭 이동 후 보존');
  await page.getByRole('tab',{name:'메모',exact:true}).press('Home');
  assert.equal(await editor.getByLabel('편집 이름').inputValue(),'편집 중인 값');
  const panel=page.locator('[data-region="editor"]'),results=page.locator('[data-region="results"]');
  const before=await panel.boundingBox(),grid=await results.boundingBox();
  assert.ok(before.y>=grid.y+grid.height-1,'Editor must be BELOW the results');
  // The editor is toggled only by the button (no split handle) and animates to/from its real height.
  assert.equal(await page.getByRole('separator',{name:'편집 패널 높이'}).count(),0,'No split resize handle');
  await page.getByRole('button',{name:'편집 패널 접기'}).click();
  const midway=await panel.boundingBox();assert.ok(midway.height>before.height*0.5,`Collapse animates from the full height instead of snapping (${Math.round(midway.height)} of ${Math.round(before.height)})`);
  await page.waitForTimeout(450);
  assert.ok((await panel.boundingBox()).height<=1,'Collapsed editor takes no space');
  assert.equal(await page.getByRole('button',{name:'편집 패널 펼치기'}).isVisible(),true);
  assert.equal(await panel.evaluate(el=>[...el.querySelectorAll('button,input,textarea')].some(item=>{item.focus();return document.activeElement===item;})),false,'Collapsed controls are not focusable');
  await page.getByRole('button',{name:'편집 패널 펼치기'}).click();await page.waitForTimeout(450);
  assert.ok(Math.abs((await panel.boundingBox()).height-before.height)<2,'Expanding restores the editor height');
  assert.equal(await editor.getByLabel('편집 이름').inputValue(),'편집 중인 값');
  await page.getByRole('tab',{name:'메모',exact:true}).click();
  assert.equal(await page.getByRole('textbox',{name:'메모',exact:true}).inputValue(),'탭 이동 후 보존');
  await page.getByRole('button',{name:'편집 패널 접기'}).click();
  await toolbar.getByRole('button',{name:'저장',exact:true}).click();
  await editor.getByRole('status').filter({hasText:'저장되었습니다.'}).waitFor();
  assert.deepEqual(await page.evaluate(()=>window.workspaceEvents.find(event=>event.kind==='save')),{kind:'save',values:{name:'편집 중인 값'},id:2});
  const confirmDialog=page.getByRole('alertdialog');
  await toolbar.getByRole('button',{name:'삭제',exact:true}).click();await confirmDialog.waitFor();await confirmDialog.getByRole('button',{name:'취소',exact:true}).click();await confirmDialog.waitFor({state:'hidden'});
  assert.equal(await page.evaluate(()=>window.workspaceEvents.filter(event=>event.kind==='delete').length),0);
  await toolbar.getByRole('button',{name:'삭제',exact:true}).click();await confirmDialog.getByRole('button',{name:'삭제',exact:true}).click();
  await page.waitForFunction(()=>window.workspaceEvents.some(event=>event.kind==='delete'));
  assert.equal(await toolbar.getByRole('button',{name:'삭제',exact:true}).isDisabled(),true);
  await toolbar.getByRole('button',{name:'신규',exact:true}).click();
  assert.equal(await editor.getByLabel('편집 이름').inputValue(),'');
  await page.getByRole('tab',{name:'메모',exact:true}).click();await page.getByRole('button',{name:'편집 패널 접기'}).click();
  await toolbar.getByRole('button',{name:'저장',exact:true}).click();
  await editor.getByLabel('편집 이름').waitFor();
  assert.equal(await page.evaluate(()=>window.workspaceEvents.filter(event=>event.kind==='save').length),1,'Empty required form must not save');
  await toolbar.getByRole('button',{name:'출력',exact:true}).click();await page.waitForFunction(()=>window.workspaceEvents.some(event=>event.kind==='print'));
  assert.deepEqual(errors,[]);
  return{passed:true,cases:['primary-always-visible','required-promoted','advanced-toggle-retains-values','external-query','bottom-editor','tab-drafts','keyboard-tabs','no-split-handle','animated-collapse-restore-height','collapsed-controls-inert','external-save-reveals-tab','required-validation','delete-confirmation','new','optional-print']};
 }finally{await fixture.close();}
}
module.exports={verify};
if(require.main===module){const config=JSON.parse(fs.readFileSync(path.join(process.env.HOME,'.local/share/mlx-server/browser-check/runtime.json')));const{chromium}=require(config.playwrightModule);(async()=>{const browser=await chromium.launch({headless:true});try{console.log(JSON.stringify(await verify(browser)));}finally{await browser.close();}})().catch(error=>{console.error(error);process.exitCode=1;});}
