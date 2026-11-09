const fs=require('fs'),path=require('path'),os=require('os'),assert=require('assert/strict');
const cfg=JSON.parse(fs.readFileSync(path.join(os.homedir(),'.local/share/mlx-server/browser-check/runtime.json')));
const {chromium}=require(cfg.playwrightModule);
(async()=>{const browser=await chromium.launch({executablePath:cfg.executablePath,headless:true});try{
 for(const [width,colorScheme] of [[866,'dark'],[1536,'light']]){
  const page=await browser.newPage({viewport:{width,height:1000},colorScheme}),errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  const base=await(await page.request.get('http://127.0.0.1:5293/api/state')).json();
  const job={...base.jobs[0],id:'d'.repeat(32),kind:'agent',status:'running',goal:'조회와 수정 화면 구현'};
  let phase='running';
  const stages=[{id:'query',title:'조회 API',domain:'backend',criterion_ids:['C1'],depends_on:[],paths:['backend/src/main/java/Query.java']},
   {id:'editor',title:'수정 화면',domain:'frontend',criterion_ids:['C2'],depends_on:['query'],paths:['frontend/src/screens/Editor.tsx']},
   {id:'integration',title:'전체 결과 검증'}];
  await page.route('**/api/**',async route=>{
   assert.equal(route.request().method(),'GET');const url=new URL(route.request().url());
   if(url.pathname==='/api/state')return route.fulfill({json:{...base,maintenance:false,jobs:[job],agent_jobs:[job],latest_agent:job,active:job,events:[],agent_events:[]}});
   if(url.pathname.endsWith('/strategy'))return route.fulfill({json:{recorded:true,stages,state:{completed_stage_ids:['query'],active_stage_id:'editor',phase}}});
   if(url.pathname.endsWith('/events'))return route.fulfill({json:{events:[],total:0,next_before:null}});
   if(url.pathname.endsWith('/context'))return route.fulfill({json:{current:null,confirmed:null,counts:{},files:[]}});
   if(url.pathname.endsWith('/diff'))return route.fulfill({json:{files:[],recorded:true}});
   return route.fulfill({json:{jobs:[job],total:1,next:null,text:''}});
  });
  await page.goto('http://127.0.0.1:5293');
  await page.getByRole('navigation',{name:'Side navigation'}).getByRole('button',{name:'작업 실행',exact:true}).click();
  await page.getByRole('tab',{name:'실행 흐름',exact:true}).click();
  const panel=page.getByRole('region',{name:'작업 분할 계획'});
  await panel.getByText('단계 통과',{exact:true}).waitFor();
  await panel.getByText('수정 화면',{exact:true}).waitFor();
  await panel.getByText('선행 작업: 조회 API',{exact:true}).waitFor();
  assert.equal(await panel.getByText('전체 검증 통과',{exact:true}).count(),0);
  await panel.getByRole('button',{name:'수정 대상',exact:true}).first().click();
  await panel.getByText('backend/src/main/java/Query.java',{exact:true}).waitFor();
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
  await page.screenshot({path:path.resolve(__dirname,`../state/evidence/strategy-ui-${colorScheme}.png`),fullPage:true});
  assert.deepEqual(errors,[]);await page.close();
 }
 console.log('PASS: ordered stage plan, dependencies, source targets and partial/global distinction at narrow/dark and wide/light sizes');
}finally{await browser.close();}})().catch(e=>{console.error(e);process.exitCode=1;});
