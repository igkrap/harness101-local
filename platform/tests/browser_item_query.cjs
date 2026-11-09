// Query stage: real isolated SQL/API/browser evidence, without business write endpoints.
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const { ItemRuntime } = require('./item_crud_runtime_client.cjs');
const root = path.resolve(__dirname, '../../local-only');
const FIELDS = ['itemCode', 'itemName', 'specification', 'unit', 'remark'];
const LABELS = ['품번', '품명', '규격', '단위', '비고'];
const CASES = ['query-grid-bottom-editor-layout', 'five-item-columns-and-edit-inputs',
  'editor-collapse-resize-no-runtime-errors', 'api-query-matches-isolated-sql',
  'query-button-renders-five-fields', 'read-only-query-and-cleanup'];
const SQL_ITEMS = 'SELECT id, item_code AS "itemCode", item_name AS "itemName", specification, unit, remark FROM public.items';

function missingImplementation(directory) {
  const missing = [];
  if (!fs.existsSync(path.join(directory, 'frontend/src/screens/ItemMaster.tsx')))
    missing.push('frontend/src/screens/ItemMaster.tsx');
  const migrations = path.join(directory, 'backend/src/main/resources/db/migration');
  const newer = fs.existsSync(migrations) && fs.readdirSync(migrations).some(name => {
    const match = /^V(\d+(?:[._]\d+)*)__.+\.sql$/.exec(name);
    if (!match) return false;
    const version = match[1].split(/[._]/).map(Number);
    return version[0] > 5 || (version[0] === 5 && version.slice(1).some(part => part > 0));
  });
  if (!newer) missing.push('a new Flyway migration after V5 in backend/src/main/resources/db/migration');
  return missing;
}

function classifyRequest({ url: address, method, resourceType }, base) {
  const url = new URL(address);
  const external = ['http:', 'https:'].includes(url.protocol) && url.origin !== base;
  if (external && method === 'GET' && (
    (url.origin === 'https://fonts.googleapis.com' && resourceType === 'stylesheet') ||
    (url.origin === 'https://fonts.gstatic.com' && resourceType === 'font'))) return 'blocked-static';
  const framework = url.pathname.startsWith('/api/auth/') ||
    (url.pathname === '/api/screens' && ['GET', 'HEAD', 'OPTIONS'].includes(method));
  const itemQuery = url.pathname === '/api/items' && method === 'GET';
  return external || (url.pathname.startsWith('/api/') && !framework && !itemQuery) ? 'forbidden' : 'allow';
}

function canonicalRows(rows) {
  assert.ok(Array.isArray(rows), 'GET /api/items must return a JSON array');
  return rows.map(row => {
    assert.ok(row && typeof row.id === 'number' && Number.isFinite(row.id), 'Each item needs a numeric id');
    return { id: row.id, ...Object.fromEntries(FIELDS.map(field => [field, row[field] ?? ''])) };
  }).sort((a, b) => a.id - b.id);
}

const displayRows = rows => rows.map(row => Object.fromEntries(FIELDS.map(field => [field, row[field] ?? ''])))
  .sort((a, b) => JSON.stringify(a).localeCompare(JSON.stringify(b)));
const sqlLiteral = value => "'" + value.replaceAll("'", "''") + "'";
function querySql({ itemCode = '', itemName = '' } = {}) {
  const conditions = [['item_code', itemCode], ['item_name', itemName]]
    .filter(([, value]) => value !== '')
    .map(([column, value]) => `POSITION(${sqlLiteral(value)} IN ${column}) > 0`);
  return SQL_ITEMS + (conditions.length ? ' WHERE ' + conditions.join(' AND ') : '') + ' ORDER BY id';
}

async function verify(output) {
  const out = path.resolve(output);
  fs.mkdirSync(out, { recursive: true });
  const cases = [], runtimeErrors = [], requests = [], sqlProofs = [], forbiddenRequests = [], blockedStaticRequests = [], cleanupErrors = [];
  let runtime, backend, browser, server, page, result;
  let databaseStarted = false, cleanup = { success: true, started: false };
  const passed = name => { assert.ok(CASES.includes(name)); cases.push(name); console.log('ITEM_QUERY_OK: ' + name); };
  try {
    const missing = missingImplementation(root);
    assert.deepEqual(missing, [], 'Required query implementation is missing: ' + missing.join(', '));
    runtime = new ItemRuntime(path.join(out, 'runtime'));
    databaseStarted = true;
    backend = await runtime.start();
    const fixture = await runtime.seedQueryFixture();
    assert.equal(fixture.length, 2, 'The isolated query fixture must contain exactly two rows');
    const seeded = canonicalRows(await runtime.rows(querySql()));
    assert.deepEqual(seeded, canonicalRows(fixture), 'Seed evidence must match the owned database');
    sqlProofs.push({ label: 'owned-query-fixture', rows: seeded });

    const config = JSON.parse(fs.readFileSync(path.join(process.env.HOME, '.local/share/mlx-server/browser-check/runtime.json'), 'utf8'));
    const { chromium } = require(config.playwrightModule);
    const { createServer } = await import(`file://${path.join(root, 'frontend/node_modules/vite/dist/node/index.js')}`);
    server = await createServer({ root: path.join(root, 'frontend'), logLevel: 'silent',
      server: { host: '127.0.0.1', port: 0, strictPort: true, proxy: { '/api': { target: backend.base_url, changeOrigin: true } } } });
    await server.listen();
    const base = 'http://127.0.0.1:' + server.httpServer.address().port;
    browser = await chromium.launch({ headless: true });
    page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
    page.setDefaultTimeout(7000);
    page.on('pageerror', error => runtimeErrors.push(error.message));
    assert.equal(await require('../../local-only/harness/trusted_auth.cjs').ensureAuthenticated(page.request, base, { localProxy: true }), true);
    await page.route('**/*', route => {
      const request = route.request(), url = new URL(request.url());
      const entry = { method: request.method(), path: url.origin + url.pathname + url.search, resourceType: request.resourceType() };
      const category = classifyRequest({ url: request.url(), method: request.method(), resourceType: request.resourceType() }, base);
      if (category !== 'allow') {
        (category === 'blocked-static' ? blockedStaticRequests : forbiddenRequests).push(entry);
        return route.abort();
      }
      if (url.pathname.startsWith('/api/')) requests.push({ origin: 'browser', ...entry });
      return route.continue();
    });

    async function expectedFor(label, conditions) {
      const rows = canonicalRows(await runtime.rows(querySql(conditions)));
      sqlProofs.push({ label, conditions, rows });
      return rows;
    }
    const apiConditions = [{}, { itemCode: '', itemName: '' }, { itemCode: '-10' },
      { itemName: '너' }, { itemName: '육각' }, { itemCode: '-10', itemName: '볼' }, { itemCode: '-10', itemName: '너' }];
    for (const conditions of apiConditions) {
      const suffix = new URLSearchParams(conditions).toString();
      const response = await page.request.get(base + '/api/items' + (suffix ? '?' + suffix : ''), { timeout: 10000 });
      requests.push({ origin: 'oracle-api', method: 'GET', path: '/api/items' + (suffix ? '?' + suffix : ''), status: response.status() });
      assert.equal(response.status(), 200, 'GET item query must succeed: ' + (await response.text()).slice(0, 400));
      assert.deepEqual(canonicalRows(await response.json()), await expectedFor('api-query', conditions), 'API result differs from SQL for ' + JSON.stringify(conditions));
    }
    assert.deepEqual(canonicalRows(await runtime.rows(querySql())), seeded, 'API queries must not change item data');
    passed('api-query-matches-isolated-sql');

    await page.goto(base);
    const meta = await page.evaluate(async () => (await import('/src/screens/ItemMaster.tsx')).meta);
    assert.equal(meta?.code, 'MST0001', 'Preserve the existing screen code');
    assert.equal(meta?.title, '품목 등록', 'Preserve the existing screen title');
    const sidebar = page.getByRole('navigation', { name: 'Side navigation', exact: true });
    const expand = sidebar.getByRole('button', { name: 'Expand sidebar', exact: true });
    if (await expand.isVisible()) await expand.click();
    await sidebar.getByRole('button', { name: meta.title, exact: true }).click();
    const screen = page.getByRole('tabpanel', { name: meta.title, exact: true });
    const query = screen.locator('form[data-ui="query-panel"]');
    const grid = screen.locator('table');
    const editor = screen.locator('form[data-ui="record-editor"]');
    for (const [locator, label] of [[query, 'query panel'], [grid, 'result grid'], [editor, 'item editor']]) {
      assert.equal(await locator.count(), 1, 'Preserve one shared ' + label);
      await locator.waitFor();
    }
    const queryBox = await query.boundingBox(), gridBox = await grid.boundingBox(), editorBox = await editor.boundingBox();
    assert.ok(gridBox.y >= queryBox.y + queryBox.height - 1, 'Keep the result grid below the query panel');
    assert.ok(editorBox.y >= gridBox.y + gridBox.height - 1, 'Keep the editor below the result grid');
    passed('query-grid-bottom-editor-layout');
    for (const label of LABELS) {
      await grid.getByRole('columnheader', { name: label, exact: true }).waitFor();
      const input = editor.getByLabel(new RegExp('^' + label));
      assert.equal(await input.count(), 1, 'Keep one editor input for ' + label);
      await input.waitFor();
    }
    passed('five-item-columns-and-edit-inputs');

    const codeInput = query.getByLabel(/^품번/), nameInput = query.getByLabel(/^품명/);
    if (!await nameInput.isVisible()) await query.getByRole('button', { name: /상세.*조건/ }).click();
    await codeInput.waitFor(); await nameInput.waitFor();
    const localQueryButton = query.getByRole('button', { name: '조회', exact: true });
    const queryButton = await localQueryButton.count() ? localQueryButton : screen.getByRole('toolbar', { name: '업무 버튼', exact: true }).getByRole('button', { name: '조회', exact: true });
    async function actualGridRows() {
      const headers = (await grid.getByRole('columnheader').allTextContents()).map(value => value.trim());
      const indices = LABELS.map(label => headers.indexOf(label));
      assert.ok(indices.every(index => index >= 0), 'All five item columns must remain visible');
      const values = [];
      for (const row of await grid.getByRole('row').all()) {
        const cells = row.getByRole('cell');
        if (await cells.count() <= Math.max(...indices)) continue;
        const texts = (await cells.allTextContents()).map(value => value.trim());
        values.push(Object.fromEntries(FIELDS.map((field, index) => [field, texts[indices[index]]])));
      }
      return displayRows(values);
    }
    async function expectGrid(expected) {
      const target = displayRows(expected);
      let actual;
      for (let attempt = 0; attempt < 60; attempt++) {
        actual = await actualGridRows();
        if (JSON.stringify(actual) === JSON.stringify(target)) return;
        await page.waitForTimeout(50);
      }
      assert.deepEqual(actual, target, 'The visible five item columns differ from SQL');
    }
    const uiConditions = [{ itemCode: '', itemName: '' }, { itemCode: '-10', itemName: '' },
      { itemCode: '', itemName: '너' }, { itemCode: '-10', itemName: '볼' },
      { itemCode: '-10', itemName: '너' }, { itemCode: '', itemName: '' }];
    for (const conditions of uiConditions) {
      await codeInput.fill(conditions.itemCode); await nameInput.fill(conditions.itemName);
      const [request] = await Promise.all([
        page.waitForRequest(request => new URL(request.url()).origin === base && new URL(request.url()).pathname === '/api/items' && request.method() === 'GET'),
        queryButton.click(),
      ]);
      const requested = new URL(request.url()).searchParams;
      assert.equal(requested.get('itemCode') || '', conditions.itemCode, 'Submit the current item code condition');
      assert.equal(requested.get('itemName') || '', conditions.itemName, 'Submit the current item name condition');
      let response, responseTimer;
      try {
        response = await Promise.race([request.response(), new Promise((_, reject) => {
          responseTimer = setTimeout(() => reject(new Error('Item query response exceeded 10 seconds')), 10000);
        })]);
      } finally { clearTimeout(responseTimer); }
      assert.ok(response && response.status() === 200, 'The query button must complete a real successful GET');
      const expected = await expectedFor('browser-query', conditions);
      assert.deepEqual(canonicalRows(await response.json()), expected, 'Browser query response differs from SQL');
      await expectGrid(expected);
    }
    passed('query-button-renders-five-fields');

    const split = screen.locator('[data-ui="split-pane"]:has(form[data-ui="record-editor"])').last();
    assert.equal(await split.count(), 1, 'Keep the shared bottom editor split pane');
    const separator = split.locator(':scope > [role="separator"][aria-orientation="horizontal"]');
    assert.equal(await separator.count(), 1, 'Keep the horizontal editor resize handle');
    const region = split.locator(':scope > div').last();
    const before = await region.boundingBox();
    await separator.focus();
    await separator.press(Number(await separator.getAttribute('aria-valuenow')) > 20 ? 'ArrowUp' : 'ArrowDown');
    const keyboard = await region.boundingBox();
    assert.ok(Math.abs(keyboard.height - before.height) > 2, 'Keyboard resize must change editor height');
    const handle = await separator.boundingBox();
    const delta = Number(await separator.getAttribute('aria-valuenow')) > 25 ? -24 : 24;
    await page.mouse.move(handle.x + handle.width / 2, handle.y + handle.height / 2);
    await page.mouse.down(); await page.mouse.move(handle.x + handle.width / 2, handle.y + delta, { steps: 5 }); await page.mouse.up();
    const resized = await region.boundingBox();
    assert.ok(Math.abs(resized.height - keyboard.height) > 3, 'Dragging must resize the editor');
    await screen.getByRole('button', { name: /편집.*접기/ }).click();
    assert.equal(await editor.isVisible(), false, 'Collapse must hide the editor');
    assert.ok((await region.boundingBox()).height < resized.height, 'Collapse must release editor space');
    await screen.getByRole('button', { name: /편집.*펼치기/ }).click();
    await editor.waitFor();
    assert.ok(Math.abs((await region.boundingBox()).height - resized.height) < 3, 'Expanding must restore editor height');
    assert.deepEqual(runtimeErrors, [], 'The screen must render without JavaScript errors');
    passed('editor-collapse-resize-no-runtime-errors');
    const finalRows = canonicalRows(await runtime.rows(querySql()));
    sqlProofs.push({ label: 'after-browser-queries', rows: finalRows });
    assert.deepEqual(finalRows, seeded, 'Querying must leave all item data unchanged');
    assert.deepEqual(forbiddenRequests, [], 'Only framework requests and GET /api/items are allowed');
    await page.screenshot({ path: path.join(out, 'item-query-1440.png'), fullPage: true });
    result = { passed: true };
  } catch (error) {
    if (page) try { await page.screenshot({ path: path.join(out, 'failure.png'), fullPage: true, timeout: 5000 }); } catch (_) { /* Preserve the original failure. */ }
    result = { passed: false, failure: String(error) };
  } finally {
    if (browser) try { await browser.close(); } catch (error) { cleanupErrors.push('browser: ' + error); }
    if (server) try { await server.close(); } catch (error) { cleanupErrors.push('preview: ' + error); }
    if (runtime) try { cleanup = await runtime.close(); } catch (error) { cleanupErrors.push('isolated runtime: ' + error); }
    cleanup = { ...cleanup, success: cleanup.success === true && cleanupErrors.length === 0, errors: cleanupErrors };
    result = result || { passed: false, failure: 'Query check did not produce a result' };
    if (!cleanup.success) { result.passed = false; result.failure = [result.failure, ...cleanupErrors].filter(Boolean).join('\n'); }
    if (result.passed && (runtimeErrors.length || forbiddenRequests.length)) {
      result.passed = false;
      result.failure = 'Unexpected JavaScript errors or forbidden requests occurred before browser shutdown';
    }
    if (result.passed) passed('read-only-query-and-cleanup');
    Object.assign(result, { cases, runtimeErrors, requests, sqlProofs, forbiddenRequests, blockedStaticRequests,
      databaseStarted, database: backend?.db_name, cleanup, evidence: out });
    fs.writeFileSync(path.join(out, 'result.json'), JSON.stringify(result, null, 2));
  }
  console.log(JSON.stringify(result));
  return result;
}

module.exports = { verify, CASES, classifyRequest, canonicalRows, displayRows, querySql, missingImplementation };
if (require.main === module) {
  if (!process.argv[2]) { console.error('Usage: node browser_item_query.cjs OUTPUT_DIRECTORY'); process.exitCode = 2; }
  else verify(process.argv[2]).then(result => { if (!result.passed) process.exitCode = 1; }).catch(error => { console.error(error); process.exitCode = 1; });
}
