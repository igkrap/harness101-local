const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const config = JSON.parse(fs.readFileSync(path.join(process.env.HOME, '.local/share/mlx-server/browser-check/runtime.json')));
const { chromium } = require(config.playwrightModule);
const { inventoryLocators, formAction } = require('./inventory_locators.cjs');

async function verify(browser) {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  page.setDefaultTimeout(5000);
  const errors = [], writes = [];
  const records = [
    { id: 1, name: 'Steel Probe', category: 'Metal', quantity: 10, minQuantity: 2, unitPrice: 100, createdAt: '2026-01-01T00:00:00Z' },
    { id: 2, name: 'Copper Probe', category: 'Wire', quantity: 20, minQuantity: 3, unitPrice: 200, createdAt: '2026-01-01T00:00:00Z' },
  ];
  const expected = { name: 'Updated Steel Probe', category: 'Processed Metal', quantity: 17, minQuantity: 4, unitPrice: 350 };
  const newItem = { name: 'New Alloy Probe', category: 'Parts', quantity: 8, minQuantity: 1, unitPrice: 900 };
  let captured;
  const inventoryReads = [];
  let allowCreate = false, capturedPost;
  page.on('pageerror', e => errors.push(e.message));
  await page.route('**/*', async route => {
    const req = route.request(), url = new URL(req.url()), method = req.method();
    if (method === 'GET' && url.pathname === '/api/inventory') {
      inventoryReads.push(url.pathname + url.search);
      return route.fulfill({ json: records });
    }
    if (method === 'GET' && /^\/api\/inventory\/[12]$/.test(url.pathname))
      return route.fulfill({ json: records.find(record => String(record.id) === url.pathname.split('/').pop()) });
    if (method === 'PUT' && url.pathname === '/api/inventory/1') {
      captured = req.postDataJSON();
      records[0] = { ...records[0], ...captured };
      return route.fulfill({ json: records[0] });
    }
    if (allowCreate && method === 'POST' && url.pathname === '/api/inventory') {
      capturedPost = req.postDataJSON();
      const record = { ...capturedPost, id: 3, createdAt: '2026-01-01T00:00:00Z' };
      records.push(record);
      return route.fulfill({ status: 201, json: record });
    }
    if (!['GET', 'HEAD', 'OPTIONS'].includes(method)) {
      writes.push(`${method} ${url.pathname}`);
      return route.abort();
    }
    return route.continue();
  });
  try {
    await require('../../local-only/harness/trusted_auth.cjs').ensureAuthenticated(page.request, process.env.PREVIEW_URL || 'http://127.0.0.1:5292', { localProxy: !!process.env.PREVIEW_URL });
    await page.goto(process.env.PREVIEW_URL || 'http://127.0.0.1:5292', { waitUntil: 'networkidle' });
    const expand = page.getByRole('button', { name: /Expand sidebar|펼치기/i });
    if (await expand.isVisible()) await expand.click();
    await page.getByRole('navigation', { name: 'Side navigation', exact: true }).getByRole('button', { name: '재고', exact: true }).click();
    const { query, grid, form, reset } = inventoryLocators(page);
    assert.equal(await query.count(), 1, '조회 버튼과 조건을 가진 조회 폼이 하나 있어야 합니다.');
    assert.equal(await grid.count(), 1, '조회 결과 표가 하나 있어야 합니다.');
    await query.evaluate(panel => {
      panel.__queryVerificationSubmits = 0;
      panel.addEventListener('submit', () => { panel.__queryVerificationSubmits++; }, true);
    });
    assert.equal(await form.count(), 1, '등록·수정 폼이 하나 있어야 합니다.');
    const queryAction = await formAction(page, query, /^조회$/);
    const saveAction = await formAction(page, form, /저장|수정|추가|등록/);
    const fields = {
      name: form.getByLabel(/^이름/), category: form.getByLabel(/^(카테고리|분류)/),
      quantity: form.getByLabel(/^수량/), minQuantity: form.getByLabel(/^최소\s*수량/), unitPrice: form.getByLabel(/^단가/),
    };
    const before = await fields.name.inputValue();
    for (const key of ['quantity', 'minQuantity', 'unitPrice']) {
      const labels = { quantity: /^수량/, minQuantity: /^최소\s*수량/, unitPrice: /^단가/ };
      const condition = query.getByLabel(labels[key]);
      if (await condition.count() === 1 && await condition.isVisible()) {
        const draft = await fields[key].inputValue(), prior = await condition.inputValue();
        await condition.fill(String(Number(prior || 0) + 1));
        assert.equal(await fields[key].inputValue(), draft, `조회 조건의 ${key} 입력이 우측 등록·수정 값을 바꿉니다. 조회 입력은 편집 상태와 분리해야 합니다.`);
        await condition.fill(prior);
      }
    }
    await query.getByLabel(/^이름/).fill('Steel Probe');
    assert.equal(await fields.name.inputValue(), before, '조회 조건과 등록 폼이 같은 상태를 공유합니다.');
    inventoryReads.length = 0;
    await queryAction.click();
    await grid.getByText('Steel Probe', { exact: true }).waitFor();
    await grid.getByText('Copper Probe', { exact: true }).waitFor({ state: 'hidden' }).catch(async error => {
      const trace = await query.evaluate(panel => ({
        submitEvents: panel.__queryVerificationSubmits,
        buttons: [...panel.querySelectorAll('button')].map(button => ({ text: button.innerText, type: button.type })),
        inputs: [...panel.querySelectorAll('input')].map(input => ({ label: input.labels?.[0]?.innerText || input.getAttribute('aria-label'), value: input.value, required: input.required, valid: input.validity.valid })),
      }));
      throw new Error('조회 조건 이름=Steel Probe 후 Copper Probe 행이 남아 있습니다. 조회 버튼이 조건을 적용해 그리드를 필터링해야 합니다. 실제 클릭 경로: ' + JSON.stringify({ ...trace, GET: inventoryReads }), { cause: error });
    });
    await query.getByLabel(/^이름/).fill('');
    await queryAction.click();
    await grid.getByText('Copper Probe', { exact: true }).waitFor();
    const categoryBefore = await fields.category.inputValue();
    if (!await query.getByLabel(/^(카테고리|분류)/).isVisible())
      await query.getByRole('button', {name:'상세조건 펼치기', exact:true}).click();
    await query.getByLabel(/^(카테고리|분류)/).fill('Wire');
    assert.equal(await fields.category.inputValue(), categoryBefore, '조회 분류와 등록 폼의 분류가 같은 상태를 공유합니다.');
    await queryAction.click();
    await grid.getByText('Copper Probe', { exact: true }).waitFor();
    await grid.getByText('Steel Probe', { exact: true }).waitFor({ state: 'hidden' }).catch(error => {
      throw new Error('조회 분류=Wire 조건이 결과 그리드에 적용되지 않았습니다.', { cause: error });
    });
    await selectRecord(records[1]);
    await query.getByLabel(/^(카테고리|분류)/).fill('');
    await queryAction.click();
    await grid.getByText('Steel Probe', { exact: true }).waitFor();
    async function selectRecord(record) {
      const row = grid.getByRole('row').filter({ has: page.getByText(record.name, { exact: true }) });
      const action = row.getByRole('button', { name: /선택|수정|편집|Steel Probe|Copper Probe/ });
      if (await action.count()) await action.first().click();
      else await row.click();
      await page.waitForFunction(({ input, name }) => input.value === name,
        { input: await fields.name.elementHandle(), name: record.name }).catch(error => {
        throw new Error(`그리드에서 ${record.name} 행을 선택하면 우측 폼이 해당 항목의 값으로 채워져야 합니다.`, { cause: error });
      });
      for (const [key, locator] of Object.entries(fields)) assert.equal(await locator.inputValue(), String(record[key]), `${record.name} 행 선택 후 ${key} 값이 다릅니다.`);
    }
    await selectRecord(records[1]);
    await selectRecord(records[0]);
    for (const [key, value] of Object.entries(expected)) await fields[key].fill(String(value));
    const request = page.waitForRequest(r => r.method() === 'PUT' && new URL(r.url()).pathname === '/api/inventory/1');
    await saveAction.click();
    await request;
    await grid.getByText(expected.name, { exact: true }).waitFor();
    assert.deepEqual(Object.keys(captured).sort(), Object.keys(expected).sort(), '수정 요청은 API 계약의 다섯 필드만 보내야 합니다.');
    for (const [key, value] of Object.entries(expected)) assert.equal(captured[key], value, `PUT 요청의 ${key} 값이 다릅니다.`);
    if (await reset.count()) await reset.first().click();
    for (const [key, value] of Object.entries(newItem)) await fields[key].fill(String(value));
    allowCreate = true;
    const post = page.waitForRequest(r => r.method() === 'POST' && new URL(r.url()).pathname === '/api/inventory');
    await saveAction.click();
    await post.catch(error => { throw new Error('수정 후 신규 등록으로 전환하면 PUT 대신 POST 요청을 보내야 합니다.', { cause: error }); });
    await grid.getByText(newItem.name, { exact: true }).waitFor();
    assert.deepEqual(capturedPost, newItem, '신규 등록 요청의 다섯 필드가 입력값과 일치해야 합니다.');
    assert.deepEqual(writes, [], '예상하지 않은 쓰기 요청이 있습니다.');
    assert.deepEqual(errors, [], '브라우저 오류가 있습니다.');
    console.log(JSON.stringify({ success: true, checks: ['query_independence', 'query_filter', 'two_row_selection', 'PUT_payload', 'grid_refresh', 'switch_to_create', 'POST_payload'], productionWrites: 0 }));
  } finally { await page.close(); }
}

module.exports = { verify };
if (require.main === module) (async () => {
  const browser = await chromium.launch({ headless: true });
  try { await verify(browser); } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
