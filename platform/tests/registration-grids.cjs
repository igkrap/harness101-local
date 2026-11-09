const fs = require('fs');
const path = require('path');
const os = require('os');
const assert = require('assert/strict');
const cfg = JSON.parse(fs.readFileSync(path.join(os.homedir(), '.local/share/mlx-server/browser-check/runtime.json')));
const { chromium } = require(cfg.playwrightModule);

(async () => {
  const browser = await chromium.launch({ executablePath: cfg.executablePath, headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    page.on('request', request => assert.equal(request.method(), 'GET', 'verification must remain read-only'));
    await page.goto('http://127.0.0.1:5292');
    for (const [title, endpoint] of [['품목 등록', 'inventory'], ['작업장 등록', 'work-sites']]) {
      const response = await page.request.get(`http://127.0.0.1:5292/api/${endpoint}`);
      assert.equal(response.status(), 200);
      const rows = await response.json();
      assert(rows.length > 0, `${title}: expected seeded API data`);
      await page.getByRole('navigation', { name: 'Side navigation' }).getByRole('button', { name: title, exact: true }).click();
      const table = page.locator('table:visible, [role="table"]:visible, [role="grid"]:visible').first();
      await table.waitFor({ timeout: 10000 });
      for (const row of rows) await table.getByText(row.name, { exact: true }).waitFor({ timeout: 10000 });
      assert(await page.getByRole('button', { name: '등록하기', exact: true }).isVisible(), `${title}: form must remain available`);
      console.log(`${title}: ${rows.length} API rows visible in grid; registration form preserved`);
    }
    assert.deepEqual(errors, []);
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
