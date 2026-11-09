const fs=require('fs'),path=require('path'),assert=require('assert/strict');
const cfg=JSON.parse(fs.readFileSync(path.join(require('os').homedir(),'.local/share/mlx-server/browser-check/runtime.json')));
const {chromium}=require(cfg.playwrightModule);
(async()=>{
  const browser=await chromium.launch({executablePath:cfg.executablePath,headless:true});
  try{
    const page=await browser.newPage({viewport:{width:1536,height:1100}}),errors=[];
    page.on('pageerror',e=>errors.push(e.message));
    const state=await(await page.request.get('http://127.0.0.1:5293/api/state')).json();
    const job={...state.jobs[0],id:'e'.repeat(32),status:'succeeded',kind:'agent',goal:'검색 결과 표시 검사'};
    const event={seq:1,time:new Date().toISOString(),type:'tool.finished',data:{name:'search_code',search_mode:'hybrid',scope:'backend',query:'품목 저장',success:true,has_output:true}};
    let details=0;
    await page.route('**/api/**',async route=>{
      assert.equal(route.request().method(),'GET');
      const url=new URL(route.request().url());
      if(url.pathname==='/api/state')return route.fulfill({json:{...state,agent_jobs:undefined,agent_jobs_next:undefined,agent_jobs_total:undefined,jobs:[job],latest_agent:job,jobs_next:null,jobs_total:1,active:null,external:[],events:[event]}});
      if(url.pathname.endsWith('/events')){
        if(url.searchParams.has('at')){details++;return route.fulfill({json:{event:{...event,data:{...event.data,stdout:'backend/src/InventoryController.java:32 @PostMapping'}}}});}
        return route.fulfill({json:{events:[event],total:1,next_before:null}});
      }
      if(url.pathname==='/api/failure')return route.fulfill({json:{job:null}});
      if(url.pathname.endsWith('/log'))return route.fulfill({json:{text:''}});
      return route.fulfill({json:{jobs:[],next:null}});
    });
    await page.goto('http://127.0.0.1:5293');
    await page.getByRole('navigation',{name:'Side navigation'}).getByRole('button',{name:'작업 실행',exact:true}).click();
    await page.getByText('코드 검색 · 의미',{exact:false}).first().waitFor();
    await page.getByText('품목 저장',{exact:true}).first().waitFor();
    assert.equal(details,0);
    await page.getByRole('button',{name:'코드 검색 · 의미 상세',exact:true}).first().click();
    await page.getByText('backend/src/InventoryController.java:32 @PostMapping',{exact:true}).waitFor();
    assert.equal(details,1);
    assert.deepEqual(errors,[]);
    console.log('SEARCH_BROWSER_OK: query, mode, lazy result fetch, no JS errors');
  }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
