const fs=require('node:fs');
const path=require('node:path');
const assert=require('node:assert/strict');
const {openFixture}=require('./vite_fixture.cjs');

const source=`
import React,{useState} from 'react';
import {createRoot} from 'react-dom/client';
import {Theme} from '@astryxdesign/core/theme';
import {neutralTheme} from '@astryxdesign/theme-neutral/built';
import '@astryxdesign/core/reset.css';import '@astryxdesign/core/astryx.css';import '@astryxdesign/theme-neutral/theme.css';
import {AuthProvider,useAuth} from './src/framework/auth/AuthProvider';
import {AuthGate} from './src/framework/auth/AuthGate';
import {apiFetch} from './src/framework/auth/sessionClient';
import {WorkspaceShell} from './src/framework/workspace/WorkspaceShell';
import {RecordEditor} from './src/framework/RecordEditor';
function Edit(){return <RecordEditor fields={[{name:'name',label:'검증 이름',required:true}]} record={null} onNew={()=>{}} onSave={async values=>{
 const response=await apiFetch('/api/inventory',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:values.name,category:'Framework authentication fixture',quantity:1,minQuantity:0,unitPrice:0})});
 if(!response.ok)throw new Error('검증 저장 실패');
 }}/>;}
function Read(){const[count,setCount]=useState('');return <><button onClick={async()=>{const r=await apiFetch('/api/inventory');if(r.ok)setCount(String((await r.json()).length));}}>목록 읽기</button><output>{count}</output></>;}
const screens={Edit:{id:'Edit',meta:{title:'편집 예제',permissions:['inventory:write']},Component:Edit},Read:{id:'Read',meta:{title:'읽기 예제',permissions:['inventory:read']},Component:Read},Hidden:{id:'Hidden',meta:{title:'권한 없는 예제',permissions:['fixture:forbidden']},Component:Read}};
function Shell(){const auth=useAuth();return auth.user?<WorkspaceShell screens={screens} initialWorkspace={{tabs:['Edit','Read'],activeTab:'Edit',sidebarCollapsed:false}} user={auth.user} onLogout={auth.signOut}/>:null;}
createRoot(document.getElementById('root')).render(<Theme theme={neutralTheme}><AuthProvider><AuthGate><Shell/></AuthGate></AuthProvider></Theme>);
`;

async function verify(browser,{apiTarget='http://127.0.0.1:8084'}={}){
  const fixture=await openFixture(browser,source,{apiTarget});
  const {page,base,errors}=fixture;
  const credentials=JSON.parse(fs.readFileSync(path.resolve(__dirname,'../state/auth/local-login.json')));
  const login=page.getByRole('form',{name:'로그인',exact:true});
  async function signIn(){await login.getByLabel('아이디').fill(credentials.username);await login.getByLabel('비밀번호').fill(credentials.password);await login.getByRole('button',{name:'로그인',exact:true}).click();await page.getByRole('navigation',{name:'Side navigation',exact:true}).waitFor();}
  try{
    await login.waitFor();
    assert.equal(await page.getByRole('navigation',{name:'Side navigation',exact:true}).count(),0);
    await login.getByLabel('아이디').fill(credentials.username);
    await login.getByLabel('비밀번호').fill('incorrect-fixture-password');
    await login.getByRole('button',{name:'로그인',exact:true}).click();
    await login.getByRole('alert').filter({hasText:'올바르지'}).waitFor();
    const before=(await page.context().cookies()).find(cookie=>cookie.name==='JSESSIONID');
    await signIn();
    const after=(await page.context().cookies()).find(cookie=>cookie.name==='JSESSIONID');
    assert.ok(before && after && before.value!==after.value,'Real browser login must rotate the session cookie');
    assert.equal(after.httpOnly,true);assert.equal(after.sameSite,'Lax');
    const sidebar=page.getByRole('navigation',{name:'Side navigation',exact:true});
    const tabs=page.getByRole('navigation',{name:'Tabs',exact:true});
    assert.equal(await sidebar.getByRole('button',{name:'권한 없는 예제',exact:true}).count(),0);
    await sidebar.getByRole('button',{name:'편집 예제',exact:true}).click();
    await sidebar.getByRole('button',{name:'편집 예제',exact:true}).click();
    assert.equal(await tabs.getByRole('button',{name:'편집 예제',exact:true}).count(),1);
    let editor=page.getByRole('tabpanel',{name:'편집 예제'}).getByRole('form');
    await editor.getByLabel('검증 이름').fill('preserved draft');
    await sidebar.getByRole('button',{name:'읽기 예제',exact:true}).click();
    await page.getByRole('button',{name:'목록 읽기',exact:true}).click();
    await page.waitForFunction(()=>Number(document.querySelector('output')?.textContent)>=6);
    await sidebar.getByRole('button',{name:'편집 예제',exact:true}).click();
    assert.equal(await editor.getByLabel('검증 이름').inputValue(),'preserved draft');
    await tabs.getByRole('button',{name:'읽기 예제 닫기',exact:true}).click();
    assert.equal(await editor.isVisible(),true,'Closing an inactive tab must not switch the active tab');
    await tabs.getByLabel('저장하지 않은 변경').waitFor();
    page.once('dialog',dialog=>dialog.dismiss());
    await tabs.getByRole('button',{name:'편집 예제 닫기',exact:true}).click();
    assert.equal(await editor.isVisible(),true);
    page.once('dialog',dialog=>dialog.accept());
    await tabs.getByRole('button',{name:'편집 예제 닫기',exact:true}).click();
    await page.getByText('활성화된 탭이 없습니다.',{exact:true}).waitFor();
    await sidebar.getByRole('button',{name:'편집 예제',exact:true}).click();
    editor=page.getByRole('tabpanel',{name:'편집 예제'}).getByRole('form');
    assert.equal(await editor.getByLabel('검증 이름').inputValue(),'');
    await editor.getByLabel('검증 이름').fill('Authenticated Framework Probe');
    await editor.getByRole('button',{name:'추가',exact:true}).click();
    await editor.getByRole('status').filter({hasText:'저장되었습니다.'}).waitFor();
    await tabs.getByLabel('저장하지 않은 변경').waitFor({state:'detached'});
    await sidebar.getByRole('button',{name:'로그아웃',exact:true}).click();
    await login.waitFor();
    assert.equal((await page.request.get(base+'/api/inventory')).status(),401);
    await page.reload();await login.waitFor();
    await signIn();
    // Invalidate the server session outside the UI, then exercise automatic 401 handling.
    const session=await (await page.request.get(base+'/api/auth/session')).json();
    assert.equal((await page.request.post(base+'/api/auth/logout',{headers:{[session.csrf.headerName]:session.csrf.token}})).status(),204);
    await page.getByRole('navigation',{name:'Side navigation',exact:true}).getByRole('button',{name:'읽기 예제',exact:true}).click();
    await page.getByRole('button',{name:'목록 읽기',exact:true}).click();
    await login.waitFor();
    assert.deepEqual(errors,[]);
    return {passed:true,cases:['bad-password','real-session-login','cookie-rotation','httpOnly-sameSite','permission-menu','mdi-dedup','draft-retention','inactive-close','unsaved-cancel-confirm','csrf-save','clean-after-save','logout','server-session-loss']};
  }finally{await fixture.close();}
}
module.exports={verify};
if(require.main===module){const config=JSON.parse(fs.readFileSync(path.join(process.env.HOME,'.local/share/mlx-server/browser-check/runtime.json')));const{chromium}=require(config.playwrightModule);(async()=>{const browser=await chromium.launch({headless:true});try{console.log(JSON.stringify(await verify(browser)));}finally{await browser.close();}})().catch(error=>{console.error(error);process.exitCode=1;});}
