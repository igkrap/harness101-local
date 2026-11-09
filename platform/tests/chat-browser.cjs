// Real browser check: streaming, markdown code, stats, server-side persistence across reload/origin, navigating away mid-answer, stop.
const fs=require('fs'),assert=require('assert/strict'),path=require('path'),os=require('os');
const cfg=JSON.parse(fs.readFileSync(path.join(os.homedir(),'.local/share/mlx-server/browser-check/runtime.json')));const {chromium}=require(cfg.playwrightModule);
const out=path.resolve(__dirname,'../state/evidence');const T=240000;
(async()=>{const browser=await chromium.launch({executablePath:cfg.executablePath,headless:true});const created=[];let page;try{
 page=await browser.newPage({viewport:{width:1440,height:960}});const errors=[];page.on('pageerror',e=>errors.push(e.message));
 const nav=()=>page.getByRole('navigation',{name:'Side navigation'});
 const openChat=async()=>{await nav().getByRole('button',{name:'채팅',exact:true}).click();await page.locator('.chatx-status.ok').waitFor({timeout:60000});};
 await page.goto('http://127.0.0.1:5293');await openChat();
 const before=await page.locator('.chatx-item').count();
 await page.getByRole('button',{name:'＋ 새 대화'}).click();
 const box=page.getByRole('textbox',{name:'메시지'});
 await box.fill('[테스트] 자바스크립트로 배열 합계를 구하는 한 줄 코드를 코드블록으로 보여줘');await box.press('Enter');
 // navigate away mid-answer, come back: answer must keep streaming and be stored
 await page.locator('.chatx-typing, .chatx-cursor').first().waitFor({timeout:T});
 await nav().getByRole('button',{name:'개요',exact:true}).click();await page.waitForTimeout(1500);await openChat();
 await page.locator('.chatx-assistant .md-code').waitFor({timeout:T});await page.locator('.chatx-stats').waitFor({timeout:T});
 await page.screenshot({path:path.join(out,'chat-upgrade-answer.png')});
 await box.fill('[테스트] 빈 배열이면 결과는? 한 단어로');await box.press('Enter');
 await page.locator('.chatx-assistant').nth(1).locator('.chatx-stats').waitFor({timeout:T});
 assert.equal(await page.locator('.chatx-item').count(),before+1);
 await page.waitForTimeout(800);
 // persisted on the server: a different origin (localhost) sees the same conversation after reload
 await page.goto('http://localhost:5293');await openChat();
 await page.locator('.chatx-item.active').waitFor();assert.equal(await page.locator('.chatx-msg').count(),4);
 assert.match(await page.locator('.chatx-item.active').innerText(),/테스트/);
 // stop mid-generation keeps partial answer
 await page.getByRole('button',{name:'＋ 새 대화'}).click();
 await box.fill('[테스트] 한국 역사를 아주 길고 자세하게 설명해줘');await box.press('Enter');
 await page.locator('.chatx-assistant .md p').first().waitFor({timeout:T});
 await page.getByRole('button',{name:'중단',exact:true}).click();await page.locator('.chatx-note').waitFor();
 await page.waitForTimeout(500);await page.reload();await openChat();
 await page.locator('.chatx-item').nth(before+1).waitFor();assert.equal(await page.locator('.chatx-item').count(),before+2);
 await page.screenshot({path:path.join(out,'chat-upgrade-history.png')});
 assert.deepEqual(errors,[]);console.log('CHAT_BROWSER_OK');
}finally{
 // remove the conversations this test created
 const token=(await (await fetch('http://127.0.0.1:5293/api/state')).json()).token;
 const list=(await (await fetch('http://127.0.0.1:5293/api/chats')).json()).conversations;
 for(const c of list.filter(c=>c.title.startsWith('[테스트]')))await fetch(`http://127.0.0.1:5293/api/chats/${c.id}/delete`,{method:'POST',headers:{'Content-Type':'application/json','X-Platform-Token':token},body:'{}'});
 await browser.close();}})().catch(e=>{console.error(e);process.exit(1);});
