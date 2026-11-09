// UI create only: preserve the independent query regression and its owned runtime.
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const queryOracle = require('./browser_item_query.cjs');
const { ItemRuntime } = require('./item_crud_runtime_client.cjs');
const { ensureAuthenticated } = require('../../local-only/harness/trusted_auth.cjs');
const ROOT = path.resolve(__dirname, '../../local-only');
const FIELDS = ['itemCode', 'itemName', 'specification', 'unit', 'remark'];
const LABELS = ['품번', '품명', '규격', '단위', '비고'];
const NEW_CASES = ['ui-new-reset-and-required-validation', 'ui-create-browser-post-sql-and-grid',
  'ui-create-reload-query-persistence', 'ui-create-server-rejection-and-owned-cleanup'];
const CASES = [...queryOracle.CASES, ...NEW_CASES];
function classifyRequest(request, base) {
  const url = new URL(request.url);
  if (url.origin === base && url.pathname === '/api/items' && request.method === 'POST') return 'allow';
  return queryOracle.classifyRequest(request, base);
}
function errorReasons(body) {
  let value;
  try { value = JSON.parse(body); } catch (_) { return body.trim() ? [body.trim()] : []; }
  if (!value || typeof value !== 'object') return [];
  return ['detail', 'message', 'error', 'title'].map(key => value[key]).filter(text => typeof text === 'string' && text.trim());
}
async function verify(output) {
  const out = path.resolve(output); fs.mkdirSync(out, { recursive: true });
  const cases = [], requests = [], sqlProofs = [], forbiddenRequests = [], runtimeErrors = [], cleanupErrors = [];
  let queryResult, runtime, backend, browser, server, page, result;
  let ownCleanup = { success: true, started: false };
  const passed = name => { assert.ok(NEW_CASES.includes(name)); cases.push(name); console.log('ITEM_CREATE_UI_OK: ' + name); };
  try {
    queryResult = await queryOracle.verify(path.join(out, 'query-regression'));
    assert.ok(queryResult.passed && queryResult.cleanup.success, 'Unchanged query regression and cleanup must pass');
    assert.deepEqual([...queryResult.cases].sort(), [...queryOracle.CASES].sort());
    cases.push(...queryResult.cases);
    runtime = new ItemRuntime(path.join(out, 'runtime')); backend = await runtime.start();
    assert.deepEqual(queryOracle.canonicalRows(await runtime.rows(queryOracle.querySql())), [], 'Fresh items table must be empty');
    const seeded = queryOracle.canonicalRows(await runtime.seedQueryFixture());
    async function db(label) {
      const rows = queryOracle.canonicalRows(await runtime.rows(queryOracle.querySql()));
      sqlProofs.push({ label, rows }); return rows;
    }
    const config = JSON.parse(fs.readFileSync(path.join(process.env.HOME, '.local/share/mlx-server/browser-check/runtime.json'), 'utf8'));
    const { chromium } = require(config.playwrightModule);
    const { createServer } = await import(`file://${path.join(ROOT, 'frontend/node_modules/vite/dist/node/index.js')}`);
    server = await createServer({ root: path.join(ROOT, 'frontend'), logLevel: 'silent', server: {
      host: '127.0.0.1', port: 0, strictPort: true, proxy: { '/api': { target: backend.base_url, changeOrigin: true } } } });
    await server.listen(); const base = 'http://127.0.0.1:' + server.httpServer.address().port;
    browser = await chromium.launch({ headless: true }); page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
    page.setDefaultTimeout(7000); page.on('pageerror', error => runtimeErrors.push(error.message));
    assert.equal(await ensureAuthenticated(page.request, base, { localProxy: true }), true);
    await page.route('**/*', route => {
      const req = route.request(), url = new URL(req.url());
      const entry = { method: req.method(), path: url.pathname + url.search };
      const category = classifyRequest({ url: req.url(), method: req.method(), resourceType: req.resourceType() }, base);
      if (category !== 'allow') { if (category === 'forbidden') forbiddenRequests.push(entry); return route.abort(); }
      if (url.pathname.startsWith('/api/')) requests.push(entry);
      return route.continue();
    });
    let screen, editor, grid, query;
    async function open() {
      await page.goto(base);
      const meta = await page.evaluate(async () => (await import('/src/screens/ItemMaster.tsx')).meta);
      assert.equal(meta.code, 'MST0001');
      const nav = page.getByRole('navigation', { name: 'Side navigation', exact: true });
      const expand = nav.getByRole('button', { name: 'Expand sidebar', exact: true });
      if (await expand.isVisible()) await expand.click();
      await nav.getByRole('button', { name: meta.title, exact: true }).click();
      screen = page.getByRole('tabpanel', { name: meta.title, exact: true });
      editor = screen.locator('form[data-ui="record-editor"]'); grid = screen.locator('table'); query = screen.locator('form[data-ui="query-panel"]');
      await editor.waitFor();
    }
    async function queryAll() {
      await query.getByLabel(/^품번/).fill('');
      const name = query.getByLabel(/^품명/);
      if (!await name.isVisible()) await query.getByRole('button', { name: /상세.*조건/ }).click();
      await name.fill('');
      const local = query.getByRole('button', { name: '조회', exact: true });
      const button = await local.count() ? local : screen.getByRole('toolbar', { name: '업무 버튼', exact: true }).getByRole('button', { name: '조회', exact: true });
      const [response] = await Promise.all([page.waitForResponse(r => new URL(r.url()).origin === base && new URL(r.url()).pathname === '/api/items' && r.request().method() === 'GET'), button.click()]);
      assert.equal(response.status(), 200); return queryOracle.canonicalRows(await response.json());
    }
    async function gridRows() {
      const headers = (await grid.getByRole('columnheader').allTextContents()).map(t => t.trim());
      const indices = LABELS.map(label => headers.indexOf(label)); assert.ok(indices.every(i => i >= 0));
      const rows = [];
      for (const row of await grid.getByRole('row').all()) {
        const cells = row.getByRole('cell');
        if (await cells.count() <= Math.max(...indices)) continue;
        const texts = (await cells.allTextContents()).map(t => t.trim());
        rows.push(Object.fromEntries(FIELDS.map((key, i) => [key, texts[indices[i]]])));
      }
      return queryOracle.displayRows(rows);
    }
    async function expectGrid(rows) {
      const wanted = queryOracle.displayRows(rows); let actual;
      for (let i = 0; i < 80; i++) { actual = await gridRows(); if (JSON.stringify(actual) === JSON.stringify(wanted)) return; await page.waitForTimeout(50); }
      assert.deepEqual(actual, wanted, 'Visible grid must match all persisted values');
    }
    async function fill(values) { for (let i = 0; i < LABELS.length; i++) await editor.getByLabel(new RegExp('^' + LABELS[i])).fill(values[FIELDS[i]] ?? ''); }
    const postCount = () => requests.filter(r => r.method === 'POST' && r.path === '/api/items').length;
    await open(); await queryAll(); await expectGrid(seeded);
    await fill(Object.fromEntries(FIELDS.map(key => [key, 'draft'])));
    await editor.getByRole('button', { name: '신규', exact: true }).click();
    for (const label of LABELS) assert.equal(await editor.getByLabel(new RegExp('^' + label)).inputValue(), '', 'New must clear all editor fields');
    const valid = { itemCode: 'UI-C300', itemName: '화면 신규 품목', specification: 'M16x50', unit: 'SET', remark: '브라우저 신규 저장' };
    const beforeInvalid = postCount();
    for (const field of ['itemCode', 'itemName']) {
      for (const value of ['', '   ']) {
        await fill({ ...valid, [field]: value }); await editor.getByRole('button', { name: '추가', exact: true }).click();
        await page.waitForTimeout(300);
        assert.equal(postCount(), beforeInvalid, 'Invalid required input must not send POST');
        assert.deepEqual(await db('required-rejection-' + field), seeded);
      }
    }
    passed('ui-new-reset-and-required-validation');
    await fill(valid);
    const [response] = await Promise.all([page.waitForResponse(r => new URL(r.url()).origin === base && new URL(r.url()).pathname === '/api/items' && r.request().method() === 'POST'), editor.getByRole('button', { name: '추가', exact: true }).click()]);
    assert.ok([200, 201].includes(response.status()), 'UI must create via actual successful POST');
    const payload = response.request().postDataJSON();
    for (const field of FIELDS) assert.equal(payload[field], valid[field], 'Wire payload must map ' + field);
    const saved = queryOracle.canonicalRows([await response.json()])[0];
    assert.ok(Number.isSafeInteger(saved.id) && saved.id > 0 && !seeded.some(row => row.id === saved.id));
    assert.deepEqual(Object.fromEntries(FIELDS.map(key => [key, saved[key]])), valid);
    const stored = await db('created-from-browser'); assert.deepEqual(stored, [...seeded, saved].sort((a,b) => a.id-b.id));
    assert.equal(postCount(), beforeInvalid + 1, 'One submission must send exactly one POST');
    await expectGrid(stored); passed('ui-create-browser-post-sql-and-grid');
    const afterCreatePosts = postCount();
    await open(); assert.deepEqual(await queryAll(), stored); await expectGrid(stored);
    assert.equal(postCount(), afterCreatePosts); assert.deepEqual(await db('reload-and-query'), stored);
    passed('ui-create-reload-query-persistence');
    await editor.getByRole('button', { name: '신규', exact: true }).click(); await fill({ ...valid, itemName: '중복 요청 보존 확인' });
    const beforeErrorText = await page.locator('body').innerText();
    const [duplicate] = await Promise.all([page.waitForResponse(r => new URL(r.url()).origin === base && new URL(r.url()).pathname === '/api/items' && r.request().method() === 'POST'), editor.getByRole('button', { name: '추가', exact: true }).click()]);
    assert.ok(duplicate.status() >= 400 && duplicate.status() < 500, 'Duplicate must reach real server rejection');
    const reasons = errorReasons(await duplicate.text()); assert.ok(reasons.length, 'Server rejection must supply a reason');
    let visible = '';
    for (let i=0;i<80;i++) {
      visible = await page.locator('body').innerText();
      if (visible !== beforeErrorText && (reasons.some(reason => visible.includes(reason)) || /중복|이미.*존재|already exists|duplicate|conflict/i.test(visible.replace(beforeErrorText, '')))) break;
      await page.waitForTimeout(50);
    }
    assert.ok(visible !== beforeErrorText && (reasons.some(reason => visible.includes(reason)) || /중복|이미.*존재|already exists|duplicate|conflict/i.test(visible.replace(beforeErrorText, ''))), 'A new visible explanation of the server rejection is required');
    assert.deepEqual(await db('duplicate-preserves-all-rows'), stored); await expectGrid(stored);
    assert.deepEqual(runtimeErrors, []); assert.deepEqual(forbiddenRequests, []);
    await page.screenshot({ path: path.join(out, 'item-create-1440.png'), fullPage: true });
    result = { passed: true };
  } catch (error) {
    result = { passed: false, failure: String(error) };
    if (page) try { await page.screenshot({ path: path.join(out, 'failure.png'), fullPage: true, timeout: 5000 }); } catch (_) {}
  } finally {
    for (const [label, resource] of [['browser', browser], ['preview', server], ['runtime', runtime]]) {
      if (resource) try { const report = await resource.close(); if (label === 'runtime') ownCleanup = report; }
      catch (error) { cleanupErrors.push(label + ': ' + error); }
    }
    const cleanup = { success: queryResult?.cleanup?.success === true && ownCleanup.success === true && !cleanupErrors.length, queryRegression: queryResult?.cleanup, createRuntime: ownCleanup, errors: cleanupErrors };
    result ||= { passed: false, failure: 'No verification result' };
    if (result.passed && (runtimeErrors.length || forbiddenRequests.length)) {
      result.passed = false; result.failure = 'Unexpected runtime error or forbidden request before shutdown';
    }
    if (!cleanup.success) { result.passed = false; result.failure = [result.failure, 'Owned cleanup failed', ...cleanupErrors].filter(Boolean).join('\n'); }
    if (result.passed) passed('ui-create-server-rejection-and-owned-cleanup');
    Object.assign(result, { cases, requests, sqlProofs, runtimeErrors, forbiddenRequests, cleanup, browserStarted: !!page, verificationMode: 'browser-api-and-sql', evidence: out });
    fs.writeFileSync(path.join(out, 'result.json'), JSON.stringify(result, null, 2));
  }
  console.log(JSON.stringify(result)); return result;
}
module.exports = { verify, CASES, NEW_CASES, classifyRequest, errorReasons };
if (require.main === module) verify(process.argv[2]).then(r => { if (!r.passed) process.exitCode = 1; }).catch(e => { console.error(e); process.exitCode = 1; });
