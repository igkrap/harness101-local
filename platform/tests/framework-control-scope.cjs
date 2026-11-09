const fs=require('fs/promises'),os=require('os'),path=require('path'),assert=require('assert/strict');
const cfg=JSON.parse(require('fs').readFileSync(path.join(os.homedir(),'.local/share/mlx-server/browser-check/runtime.json')));
const {chromium}=require(cfg.playwrightModule);const check=require('../../local-only/harness/tests/framework_cases/control.cjs');
(async()=>{const dir=await fs.mkdtemp(path.join(os.tmpdir(),'control-scope-')),cwd=process.cwd(),write=fs.writeFile;const browser=await chromium.launch({executablePath:cfg.executablePath,headless:true});try{
 await fs.mkdir(path.join(dir,'frontend/src'),{recursive:true});const ws=path.join(dir,'frontend/src/workspace.json'),original='{"sidebarCollapsed":false}';await write(ws,original);
 for(const broken of [false,true]){
  const page=await browser.newPage();await page.setContent(`<nav aria-label="Side navigation"><button>재고</button></nav><nav aria-label="Tabs"><button>홈</button><button>재고</button></nav><h2 style="position:relative;left:100px">재고 관리</h2><form><label>이름<input value="조회 조건"></label><button type="submit">조회</button></form><form><label>이름<input value="등록 초안"></label><button type="submit">추가</button></form><script>document.querySelectorAll('form').forEach(f=>f.onsubmit=e=>e.preventDefault());</script>`);
  fs.writeFile=async(file,data,...args)=>{const out=await write(file,data,...args);if(await fs.realpath(file)===await fs.realpath(ws)&&!broken){await page.locator('h2').evaluate((el,collapsed)=>el.style.left=collapsed?'0px':'100px',JSON.parse(String(data)).sidebarCollapsed);}return out;};
  if(broken)await assert.rejects(()=>check({page,assert,root:dir}),/Heading x should decrease/);else await check({page,assert,root:dir});
  assert.equal(await fs.readFile(ws,'utf8'),original);await page.close();fs.writeFile=write;
 }
 console.log('PASS: query and editor name labels coexist; sidebar HMR movement still required; workspace restored');
}finally{fs.writeFile=write;process.chdir(cwd);await browser.close();await fs.rm(dir,{recursive:true,force:true});}})().catch(e=>{console.error(e);process.exitCode=1});
