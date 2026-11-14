// The change-history page, used by hand: record, take back, work spaces, remote. Called by control_check.py --ui with the
// project to look at; prints one JSON line per step. What really happened is judged by the caller (git, database).
const fs = require('fs'), path = require('path'), os = require('os');
const [projectId, remote] = process.argv.slice(2);
const config = JSON.parse(fs.readFileSync(process.env.HARNESS_BROWSER_RUNTIME || path.join(os.homedir(), '.local/share/mlx-server/browser-check/runtime.json'), 'utf8'));
const { chromium } = require(config.playwrightModule);
const say = (step, ok, detail) => console.log(JSON.stringify({ step, ok: !!ok, detail: String(detail ?? '').slice(0, 300) }));
(async () => {
  const browser = await chromium.launch({ headless: true, executablePath: config.executablePath });
  const page = await browser.newPage({ viewport: { width: 1400, height: 900 } });
  const notice = async () => (await page.locator('.history-page [role=status], .history-page [role=alert]').allInnerTexts()).join(' | ');
  const settled = async () => { await page.waitForTimeout(400); await page.waitForFunction(() => !document.querySelector('.history-page button[disabled][data-pending]'), null, { timeout: 60000 }).catch(() => {}); await page.waitForTimeout(2500); };
  try {
    await page.goto(`http://127.0.0.1:5293/?project=${projectId}`); await page.waitForTimeout(2500);
    await page.getByRole('button', { name: '변경 이력' }).first().click(); await page.waitForTimeout(2000);
    const subjects = async () => page.locator('.history-subject').allInnerTexts();
    say('list', (await subjects()).length > 0, (await subjects()).slice(0, 3).join(' / '));

    const box = page.locator('[data-ui="history-unrecorded"]');
    say('unrecorded-shown', await box.count() === 1, await box.innerText().catch(() => ''));
    await box.getByLabel('무엇을 바꿨나요?').fill('화면에서 기록한 변경');
    await box.getByRole('button', { name: '기록하기' }).click(); await settled();
    say('record', (await subjects())[0] === '화면에서 기록한 변경' && await box.count() === 0, await notice());

    await page.locator('.history-row').first().click(); await page.waitForTimeout(500);
    await page.getByRole('button', { name: '이 변경 취소하기' }).click(); await page.waitForTimeout(500);
    await page.getByRole('alertdialog').getByRole('button', { name: '취소하기' }).click(); await settled();
    say('undo', (await subjects())[0].startsWith('취소:'), await notice());

    await page.getByText('작업 공간(브랜치)과 원격 저장소').click(); await page.waitForTimeout(500);
    await page.getByLabel('새 작업 공간 이름').fill('ui-trial');
    await page.getByRole('button', { name: '만들고 전환' }).click(); await settled();
    say('branch-create', (await page.locator('.history-page').innerText()).includes('현재: ui-trial'), await notice());
    await page.getByRole('button', { name: 'main(으)로 전환' }).click(); await settled();
    say('branch-back', (await page.locator('.history-page').innerText()).includes('현재: main'), await notice());

    await page.getByLabel(/원격 저장소 주소/).fill(remote);
    await page.getByRole('button', { name: '연결', exact: true }).click(); await settled();
    say('remote', (await page.locator('.history-page').innerText()).includes('원격: ' + remote), await notice());
    await page.getByRole('button', { name: '원격에 올리기' }).click(); await settled();
    say('push', (await notice()).includes('올렸습니다'), await notice());
  } catch (error) { say('error', false, error.message); }
  await browser.close();
})();
