const fs=require('fs'),path=require('path'),os=require('os'),assert=require('assert/strict');
const cfg=JSON.parse(fs.readFileSync(path.join(os.homedir(),'.local/share/mlx-server/browser-check/runtime.json')));
const {chromium}=require(cfg.playwrightModule);
(async()=>{const browser=await chromium.launch({executablePath:cfg.executablePath,headless:true});try{
 for(const [width,colorScheme] of [[866,'dark'],[1536,'light']]){
  const page=await browser.newPage({viewport:{width,height:1000},colorScheme}),errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  const base=await(await page.request.get('http://127.0.0.1:5293/api/state')).json();
  const job={...base.jobs[0],id:'e'.repeat(32),kind:'agent',status:'running',goal:'좌측 넓게, 우측 좁게'};
  let phase='failed';
  const contract={task:job.goal,requirements:[{id:'R1',description:job.goal}],criteria:[
   {id:'C1',requirement_id:'R1',description:'좌측 패널이 우측보다 넓음',check:{op:'layout',left:'#left',right:'#right',relation:'wider_than'}},
   {id:'C2',requirement_id:'R1',description:'등록 후 재조회 결과 유지',check:{op:'api',method:'GET',path:'/api/item/1',status:200,json_path:['name'],equals:'bolt'}}]};
  await page.route('**/api/**',async route=>{
   assert.equal(route.request().method(),'GET');const url=new URL(route.request().url());
   if(url.pathname==='/api/state')return route.fulfill({json:{...base,maintenance:false,jobs:[job],agent_jobs:[job],latest_agent:job,active:job,events:[],agent_events:[]}});
   if(url.pathname.endsWith('/verification'))return route.fulfill({json:{recorded:phase!=='legacy',contract:phase==='legacy'?null:contract,contract_hash:'contract-hash',result_time:new Date().toISOString(),result:{success:phase==='passed',results:[{id:'C1',status:phase==='passed'?'passed':'failed',reason:phase==='passed'?'':'좌측 400, 우측 600으로 조건 미충족',evidence:{left:400,right:600}},{id:'C2',status:phase==='passed'?'passed':'unverified',reason:phase==='passed'?'':'격리된 테스트 API 필요'}],layout:[]}}});
   if(url.pathname.endsWith('/context'))return route.fulfill({json:{current:null,confirmed:null,counts:{requests:0,compactions:0},files:[]}});
   if(url.pathname.endsWith('/events'))return route.fulfill({json:{events:[],total:0,next_before:null}});
   if(url.pathname.endsWith('/diff'))return route.fulfill({json:{files:[],recorded:true}});
   return route.fulfill({json:{jobs:[job],total:1,next:null,text:''}});
  });
  await page.goto('http://127.0.0.1:5293');
  await page.getByRole('navigation',{name:'Side navigation'}).getByRole('button',{name:'작업 실행',exact:true}).click();
  await page.getByRole('tab',{name:'완료 조건',exact:true}).click();
  const panel=page.getByRole('region',{name:'완료 조건 검증'});
  await panel.getByText('완료 조건 미충족',{exact:true}).waitFor();
  await panel.getByText('미확인',{exact:true}).waitFor();
  await panel.getByText('좌측 400, 우측 600으로 조건 미충족',{exact:true}).waitFor();
  await panel.getByRole('button',{name:'검사 조건과 관측값',exact:true}).first().click();
  await panel.getByText(/"left": 400/).waitFor();
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
  await page.screenshot({path:path.resolve(__dirname,`../state/evidence/verification-ui-${colorScheme}.png`),fullPage:true});
  phase='passed';await panel.getByText('완료 조건 확인됨',{exact:true}).waitFor();
  phase='legacy';await page.getByText('이 실행에는 완료 조건 계약이 기록되지 않았습니다.',{exact:false}).waitFor();
  assert.deepEqual(errors,[]);await page.close();
 }
 console.log('PASS: completion criteria, failed/unverified evidence, successful result and legacy unknown shown at narrow/dark and wide/light sizes');
}finally{await browser.close();}})().catch(e=>{console.error(e);process.exitCode=1;});
