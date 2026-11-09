const fs=require('fs'),path=require('path'),os=require('os'),assert=require('assert/strict'),{spawn}=require('child_process');
const cfg=JSON.parse(fs.readFileSync(path.join(os.homedir(),'.local/share/mlx-server/browser-check/runtime.json')));
const {chromium}=require(cfg.playwrightModule);
(async()=>{
 const temporary=fs.mkdtempSync(path.join(os.tmpdir(),'platform-workspaces-'));
 const code=`
import sys,json,signal
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from server import Handler,ThreadingHTTPServer
from workspaces import Workspaces
from changes import Changes
base=Path(sys.argv[2])
for name in ['one','two']:
 p=base/name/'frontend/src';p.mkdir(parents=True)
 (p/'App.tsx').write_text('export const project = "'+name+'";\\n')
 (p.parent/'package.json').write_text(json.dumps({'type':'module','devDependencies':{'vite':'*'}}))
 (p.parent/'node_modules').symlink_to(Path(sys.argv[1])/'web/node_modules',target_is_directory=True)
 (p.parent/'index.html').write_text('<h1>'+name+' preview</h1>')
hub=Workspaces(base/'one',base/'state',0)
picks=[0]
def pick():
 picks[0]+=1
 return {'cancelled':True} if picks[0]==1 else {'cancelled':False,'root':str((base/'two').resolve()),'name':'two'}
hub.pick=pick
app=hub.resolve();key='d'*32;folder=app.state/key;folder.mkdir()
changes=Changes(app.project,folder);changes.capture('frontend/src/App.tsx')
(app.project/'frontend/src/App.tsx').write_text('export const project = "updated";\\n')
changes.accept(['frontend/src/App.tsx'])
job={'id':key,'kind':'agent','goal':'변경 비교 검증','status':'succeeded','checks':['frontend'],'rounds':32,'started_at':'2026-11-01T00:00:00Z','finished_at':'2026-11-01T00:00:01Z','exit_code':0}
app.jobs[key]=job;app.save(job)
(folder/'events.jsonl').write_text('');(folder/'output.log').write_text('')
server=ThreadingHTTPServer(('127.0.0.1',0),Handler);hub.port=server.server_address[1];app.port=hub.port;server.platform=hub
def terminate(*args):raise KeyboardInterrupt
signal.signal(signal.SIGTERM,terminate)
print(hub.port,flush=True)
try:server.serve_forever()
except KeyboardInterrupt:pass
finally:hub.close();server.server_close()
`;
 const child=spawn('python3',['-u','-c',code,path.resolve(__dirname,'..'),temporary],{stdio:['ignore','pipe','pipe']});let stderr='';child.stderr.on('data',d=>stderr+=d);
 let browser;
 try{
  const port=await new Promise((resolve,reject)=>{child.stdout.once('data',d=>resolve(Number(String(d).trim())));child.once('exit',()=>reject(Error(stderr)));});
  browser=await chromium.launch({executablePath:cfg.executablePath,headless:true});const page=await browser.newPage({viewport:{width:1536,height:1100}}),errors=[];page.on('pageerror',e=>errors.push(e.message));const url=`http://127.0.0.1:${port}`;
  await page.goto(url);
  const registry=await(await page.request.get(url+'/api/model-configs')).json();const config=registry.models.find(m=>m.model==='mlx-community/gemma-4-26B-A4B-it-OptiQ-4bit');
  assert.equal(await page.getByRole('heading',{name:'검사 상태',exact:true}).count(),0);
  const changes=page.getByRole('region',{name:'코드 변경',exact:true});await changes.getByRole('button',{name:'frontend/src/App.tsx',exact:true}).click();
  const diff=page.getByRole('region',{name:'frontend/src/App.tsx 변경 비교',exact:true});await diff.locator('.monaco-diff-editor').waitFor();await page.waitForTimeout(700);
  assert((await diff.innerText()).includes('updated'));await changes.getByRole('button',{name:'나란히 보기',exact:true}).click();assert.equal(await diff.locator('.monaco-editor .view-lines').count(),2);
  await diff.screenshot({path:path.resolve(__dirname,'../state/evidence/diff.png')});
  const nav=page.getByRole('navigation',{name:'Side navigation'});await nav.getByRole('button',{name:'작업 실행',exact:true}).click();
  await page.locator('.workspace-toolbar').getByRole('button',{name:'새 작업',exact:true}).click();const model=page.getByRole('combobox',{name:'모델',exact:true});await model.click();const option=page.getByRole('option',{name:new RegExp(config.name.replace(/[.*+?^${}()|[\]\\]/g,'\\$&'))});await option.click();
  await page.getByRole('textbox',{name:'만들거나 고칠 내용'}).fill('모델 선택 검증');let captured;
  await page.route('**/api/jobs?**',async route=>{if(route.request().method()!=='POST')return route.continue();captured=route.request().postDataJSON();assert.equal(new URL(route.request().url()).searchParams.get('project'),'default');return route.fulfill({status:400,json:{error:'검증용 실행 차단'}});});
  await page.getByRole('button',{name:'모델 실행',exact:true}).click();await page.getByText('Error: 검증용 실행 차단',{exact:true}).waitFor();assert.equal(captured.model,'config:'+config.id);
  await nav.getByRole('button',{name:'프로젝트',exact:true}).click();assert.equal(await page.getByRole('textbox',{name:'프로젝트 이름',exact:true}).count(),0);assert.equal(await page.getByRole('textbox',{name:'미리보기 주소',exact:true}).count(),0);await page.getByRole('button',{name:'폴더 선택',exact:true}).click();await page.getByRole('button',{name:'폴더 선택',exact:true}).waitFor({state:'visible'});assert(!new URL(page.url()).searchParams.has('project'));await page.getByRole('button',{name:'폴더 선택',exact:true}).click();await page.waitForURL('**/?project=*');
  await page.getByText('two',{exact:true}).first().waitFor();
  const state=await(await page.request.get(url+'/api/state'+new URL(page.url()).search)).json();assert.equal(state.jobs_total,0);assert.equal(state.project.name,'two');assert.equal(state.project.root,fs.realpathSync(path.join(temporary,'two')));assert.deepEqual(state.project.checks,['frontend']);
  await page.getByRole('navigation',{name:'Side navigation'}).getByRole('button',{name:'프로젝트 소스',exact:true}).click();await page.getByRole('treeitem',{name:'frontend/src/App.tsx',exact:true}).click();await page.locator('.monaco-editor .view-line').filter({hasText:'two'}).first().waitFor();
  await page.getByRole('navigation',{name:'Side navigation'}).getByRole('button',{name:'미리보기',exact:true}).click();await page.frameLocator('iframe').getByRole('heading',{name:'two preview',exact:true}).waitFor();const preview=await(await page.request.get(url+'/api/preview'+new URL(page.url()).search)).json();assert.equal(preview.status,'ready');assert(!preview.url.includes(':5292/'));
  assert.deepEqual(errors,[]);console.log('WORKSPACES_BROWSER_OK: folder picker cancel and selection, folder name, auto Vite preview, scoped source/history, model payload, Monaco diff, no JS errors');
 }finally{if(browser)await browser.close();child.kill('SIGTERM');await new Promise(resolve=>child.once('exit',resolve));fs.rmSync(temporary,{recursive:true,force:true});}
})().catch(e=>{console.error(e);process.exitCode=1;});
