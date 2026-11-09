const fs=require('fs'),path=require('path'),os=require('os'),assert=require('assert/strict');
const cfg=JSON.parse(fs.readFileSync(path.join(os.homedir(),'.local/share/mlx-server/browser-check/runtime.json')));
const {chromium}=require(cfg.playwrightModule);
const check=require('../../local-only/harness/tests/framework_cases/tabs.cjs');
(async()=>{const browser=await chromium.launch({executablePath:cfg.executablePath,headless:true});try{
 for(const broken of [false,true]){
  const page=await browser.newPage();await page.setContent(`
   <nav aria-label="Side navigation"><button id="open">재고</button></nav>
   <nav aria-label="Tabs"><button id="home">홈</button><button id="invtab" hidden>재고</button><button id="close" hidden>재고 닫기</button></nav>
   <h2 id="heading">홈</h2><section id="inventory" hidden>
   <form><label>이름<input id="query" value="조회 조건"></label><button type="submit">조회</button></form>
   <form><label>이름<input id="draft"></label><button type="submit">추가</button></form></section>
   <script>
   const inv=document.querySelector('#inventory'),heading=document.querySelector('#heading'),tab=document.querySelector('#invtab'),close=document.querySelector('#close');
   document.querySelector('#open').onclick=()=>{inv.hidden=false;heading.hidden=true;tab.hidden=false;close.hidden=false;};
   document.querySelector('#home').onclick=()=>{inv.hidden=true;heading.hidden=false;${broken?"document.querySelector('#draft').value='';":''}};
   close.onclick=()=>{inv.hidden=true;heading.hidden=false;tab.hidden=true;close.hidden=true;};
   document.querySelectorAll('form').forEach(f=>f.onsubmit=e=>e.preventDefault());
   </script>`);
  if(broken)await assert.rejects(()=>check({page,assert}),/Draft value did not persist/);
  else{await check({page,assert});assert.equal(await page.locator('#query').inputValue(),'조회 조건');}
  await page.close();
 }
 console.log('PASS: duplicate query/registration labels supported; broken draft persistence still fails');
}finally{await browser.close();}})().catch(e=>{console.error(e);process.exitCode=1;});
