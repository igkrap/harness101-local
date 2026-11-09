const fs=require('fs'),path=require('path'),assert=require('assert/strict');
const cfg=JSON.parse(fs.readFileSync(path.join(require('os').homedir(),'.local/share/mlx-server/browser-check/runtime.json')));
const {chromium}=require(cfg.playwrightModule);
(async()=>{
 const browser=await chromium.launch({executablePath:cfg.executablePath,headless:true});
 try{
  const page=await browser.newPage({viewport:{width:1536,height:1100}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
  const template=await(await page.request.get('http://127.0.0.1:5293/api/state')).json();
  let status='succeeded',id='a'.repeat(32),goal='성공한 최신 작업';let failureReads=[];
  const file='frontend/src/Latest.tsx';
  await page.route('**/api/**',async route=>{
   assert.equal(route.request().method(),'GET');const url=new URL(route.request().url());
   const job={id,kind:'agent',goal,status,checks:['frontend'],rounds:32,started_at:'2026-11-01T00:00:00Z',finished_at:status==='running'?null:'2026-11-01T00:01:00Z',exit_code:status==='failed'?1:0};
   if(url.pathname==='/api/state')return route.fulfill({json:{...template,agent_jobs:undefined,agent_jobs_next:undefined,agent_jobs_total:undefined,latest_agent:status==='empty'?null:job,jobs:status==='empty'?[]:[job,{...job,id:'f'.repeat(32),status:'failed',goal:'이전 실패'}],agent_events:[],events:[],active:status==='running'?job:null,jobs_next:null,jobs_total:status==='empty'?0:2}});
   if(url.pathname==='/api/projects')return route.fulfill({json:{projects:[]}});
   if(url.pathname==='/api/failure'){assert.equal(url.searchParams.get('job'),id);failureReads.push(id);return route.fulfill({json:{job,reason:'최근 작업 컴파일 오류',code:'error',used:3,limit:32,failure:{seq:1,time:job.started_at,type:'check.finished',mode:'frontend',message:'Latest.tsx: error TS2322'}}});}
   if(url.pathname.endsWith('/diff'))return route.fulfill({json:url.searchParams.has('path')?{path:file,before:'export const value = 1;',after:'export const value = 2;'}:{recorded:true,files:[{path:file,status:'modified',added:1,removed:1}],warnings:[]}});
   if(url.pathname.endsWith('/events'))return route.fulfill({json:{events:[],total:0,next_before:null}});
   if(url.pathname.endsWith('/log'))return route.fulfill({json:{text:''}});
   return route.fulfill({json:{jobs:[],next:null}});
  });
  await page.goto('http://127.0.0.1:5293');const card=page.getByRole('region',{name:'마지막 실행 결과',exact:true});
  await card.getByText('성공',{exact:true}).waitFor();await card.getByRole('region',{name:file+' 변경 비교',exact:true}).waitFor();assert.equal(failureReads.length,0);assert(!(await card.innerText()).includes('이전 실패'));
  status='failed';id='b'.repeat(32);goal='실패한 최신 작업';await card.getByText('최근 작업 컴파일 오류',{exact:true}).waitFor();assert.equal(await card.getByRole('region',{name:'코드 변경'}).count(),0);assert(failureReads.includes(id));
  await card.getByRole('button',{name:'실행 보기',exact:true}).click();await page.getByRole('region',{name:'실행 상세',exact:true}).getByRole('region',{name:'실패 원인',exact:true}).waitFor();await page.screenshot({path:path.resolve(__dirname,'../state/evidence/actions-failed.png'),fullPage:true});
  await page.getByRole('navigation',{name:'Side navigation'}).getByRole('button',{name:'개요',exact:true}).click();status='running';id='c'.repeat(32);goal='진행 중인 작업';await card.getByText('실행이 끝나면 결과를 표시합니다.',{exact:true}).waitFor();assert(!(await card.innerText()).includes('최근 작업 컴파일 오류'));
  status='empty';await card.getByText('아직 실행한 작업이 없습니다.',{exact:true}).waitFor();
  assert.equal(await page.getByText('마지막 실패',{exact:true}).count(),0);assert.deepEqual(errors,[]);
  console.log('LATEST_RESULT_OK: success diff, failed run reason pinned by ID, pending/empty, no stale failures, Actions detail, no JS errors');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
