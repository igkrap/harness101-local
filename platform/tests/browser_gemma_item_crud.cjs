// Independent full-stack oracle, frozen before each Gemma run. No business HTTP mocks.
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const { ItemRuntime } = require('./item_crud_runtime_client.cjs');
const root = path.resolve(__dirname, '../../local-only');

const CASES = [
  'source-menu-layout-toolbar',
  'api-required-trim-and-duplicate',
  'ui-new-create-and-db-persistence',
  'row-selection-loads-all-fields',
  'query-submit-and-independent-draft',
  'query-and-collapsed-condition-retention',
  'ui-update-repeat-save-and-db',
  'ui-required-validation-and-duplicate-rejection',
  'bottom-editor-resize-collapse',
  'delete-cancel-confirm-and-db',
  'reload-persist-updates-delete',
  'responsive-no-runtime-errors-real-api-only',
];
const FIELDS = ['itemCode', 'itemName', 'specification', 'unit', 'remark'];
const LABELS = ['품번', '품명', '규격', '단위', '비고'];
const sqlItems = 'SELECT id, item_code AS "itemCode", item_name AS "itemName", COALESCE(specification,\'\') AS specification, COALESCE(unit,\'\') AS unit, COALESCE(remark,\'\') AS remark FROM items ORDER BY id';
const values = row => Object.fromEntries(FIELDS.map(key => [key, row[key] ?? '']));
const byCode = (rows, code) => rows.find(row => row.itemCode === code);

async function verify(output) {
  const out = path.resolve(output);
  fs.mkdirSync(out, { recursive: true });
  const cases = [], runtimeErrors = [], requests = [], sqlProofs = [], forbiddenRequests = [], browserWriteStarts = [];
  let runtime, backend, browser, server, page, result, cleanup = { success: true, started: false };
  const passed = name => { assert.ok(CASES.includes(name)); cases.push(name); console.log('ITEM_CRUD_OK: ' + name); };
  try {
    const missing = ['frontend/src/screens/ItemMaster.tsx', 'backend/src/main/resources/db/migration/V6__create_items.sql'].filter(relative => !fs.existsSync(path.join(root, relative)));
    const javaDirectory = 'backend/src/main/java/com/example/localinventory/items';
    if (!fs.existsSync(path.join(root, javaDirectory)) || !fs.readdirSync(path.join(root, javaDirectory)).some(name => name.endsWith('.java')))
      missing.push(javaDirectory + '/*.java');
    assert.deepEqual(missing, [], 'Required implementation files are missing: ' + missing.join(', '));
    runtime = new ItemRuntime(path.join(out, 'runtime'));
    backend = await runtime.start();
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
    const session = await (await page.request.get(base + '/api/auth/session')).json();
    assert.ok(session.authenticated && session.csrf?.token && session.csrf.headerName === 'X-CSRF-TOKEN');
    const headers = { [session.csrf.headerName]: session.csrf.token };
    async function api(method, suffix, body) {
      const response = await page.request.fetch(base + '/api/items' + suffix, { method, headers, data: body, timeout: 10000 });
      const text = await response.text();
      requests.push({ origin: 'oracle-api', method, path: '/api/items' + suffix, status: response.status() });
      return { response, status: response.status(), text, json: () => JSON.parse(text) };
    }
    async function db(label) {
      const rows = await runtime.rows(sqlItems);
      sqlProofs.push({ label, rows });
      return rows;
    }
    async function list(suffix = '') {
      const result = await api('GET', suffix);
      assert.equal(result.status, 200, 'List endpoint failed: ' + result.text.slice(0, 500));
      const rows = result.json();
      assert.ok(Array.isArray(rows), 'GET /api/items must return an array');
      return rows;
    }
    const initialDb = await db('fresh-isolated-database');
    assert.equal(initialDb.length, 0, 'New items migration must not seed business rows');
    const unique = await runtime.rows("SELECT EXISTS (SELECT 1 FROM pg_index i JOIN pg_attribute a ON a.attrelid=i.indrelid AND a.attnum=ANY(i.indkey) WHERE i.indrelid='items'::regclass AND i.indisunique AND i.indisvalid AND i.indpred IS NULL AND i.indexprs IS NULL AND i.indnkeyatts=1 AND a.attname='item_code') AS unique_item_code");
    assert.equal(unique[0]?.unique_item_code, true, 'Database must enforce a unique item_code, not only an application lookup');
    sqlProofs.push({ label: 'database-unique-item-code', rows: unique });
    const first = { itemCode: 'A-100', itemName: '육각 볼트', specification: 'M8×30', unit: 'EA', remark: '아연 도금' };
    const second = { itemCode: 'B-200', itemName: '육각 너트', specification: 'M10', unit: 'BOX', remark: '잠금형' };
    for (const record of [first, second]) {
      const created = await api('POST', '', { ...record, itemCode: ' ' + record.itemCode + ' ', itemName: ' ' + record.itemName + ' ' });
      assert.ok([200, 201].includes(created.status), 'Create endpoint failed: ' + created.status + ' ' + created.text.slice(0, 500));
      assert.ok(created.json().id != null, 'Create response must identify the saved record');
    }
    const initial = await list();
    assert.equal(initial.length, 2);
    assert.deepEqual(values(byCode(initial, first.itemCode)), first);
    assert.deepEqual(values(byCode(initial, second.itemCode)), second);
    const firstId = byCode(initial, first.itemCode).id, secondId = byCode(initial, second.itemCode).id;
    assert.notEqual(String(firstId), String(secondId));
    const validDb = await db('api-created-two-real-rows');
    assert.equal(validDb.length, 2);
    assert.deepEqual(values(byCode(validDb, first.itemCode)), first);
    assert.deepEqual(values(byCode(validDb, second.itemCode)), second);
    const trimmedUpdate = await api('PUT', '/' + firstId, { ...first, itemCode: ' ' + first.itemCode + ' ', itemName: ' ' + first.itemName + ' ' });
    assert.equal(trimmedUpdate.status, 200, 'Update endpoint must return the saved object');
    assert.deepEqual(values(trimmedUpdate.json()), first, 'Updated required fields must be trimmed');
    for (const field of ['itemCode', 'itemName']) {
      for (const blank of ['', '   ']) {
        const invalid = { ...first, itemCode: 'INVALID-' + field, [field]: blank };
        const rejected = await api('POST', '', invalid);
        assert.ok([400, 422].includes(rejected.status), `Server must reject blank ${field}: ${rejected.status}`);
        const update = await api('PUT', '/' + firstId, { ...first, [field]: blank });
        assert.ok([400, 422].includes(update.status), `Server must reject blank ${field} on update: ${update.status}`);
      }
    }
    for (const [method, suffix] of [['POST', ''], ['PUT', '/' + secondId]]) {
      const duplicate = await api(method, suffix, { ...second, itemCode: ' ' + first.itemCode + ' ' });
      assert.ok([400, 409, 422].includes(duplicate.status), 'Duplicate item code must be rejected: ' + duplicate.status);
      assert.ok(duplicate.text.trim(), 'Duplicate rejection must explain the error');
    }
    assert.deepEqual(await db('server-rejected-invalid-and-duplicate-writes'), validDb);
    assert.deepEqual((await list('?itemCode=A-&itemName=' + encodeURIComponent('볼트'))).map(row => row.itemCode), ['A-100']);
    assert.equal((await list('?itemCode=A-&itemName=' + encodeURIComponent('너트'))).length, 0, 'Query conditions must combine with AND');
    passed('api-required-trim-and-duplicate');

    // Allow only the isolated preview and its proxy; a hardcoded live API cannot receive a write.
    await page.route('**/*', route => {
      const request = route.request(), url = new URL(request.url());
      if (['http:', 'https:'].includes(url.protocol) && url.origin !== base) {
        forbiddenRequests.push(request.method() + ' ' + url.origin + url.pathname);
        return route.abort();
      }
      if (url.pathname.startsWith('/api/') && !/^\/api\/(?:auth(?:\/|$)|items(?:\/|$)|screens$)/.test(url.pathname)) {
        forbiddenRequests.push(request.method() + ' ' + url.pathname);
        return route.abort();
      }
      return route.continue();
    });
    page.on('response', response => {
      const url = new URL(response.url());
      if (url.pathname === '/api/items' || url.pathname.startsWith('/api/items/'))
        requests.push({ origin: 'browser', method: response.request().method(), path: url.pathname + url.search, status: response.status() });
    });
    page.on('request', request => {
      const url = new URL(request.url());
      if ((url.pathname === '/api/items' || url.pathname.startsWith('/api/items/')) && ['POST', 'PUT', 'DELETE'].includes(request.method()))
        browserWriteStarts.push({ method: request.method(), path: url.pathname });
    });
    await page.goto(base);
    const meta = await page.evaluate(async () => (await import('/src/screens/ItemMaster.tsx')).meta);
    assert.equal(meta?.code, 'MST0001'); assert.equal(meta?.title, '품목 관리'); assert.equal(meta?.group, '기준정보');
    assert.ok(Array.isArray(meta.permissions) && meta.permissions.includes('workspace:admin'));
    const catalog = await page.request.get(base + '/api/screens');
    assert.ok(catalog.ok()); assert.deepEqual(await catalog.json(), [], 'Business screen must come from source registration');
    const sidebar = page.getByRole('navigation', { name: 'Side navigation', exact: true });
    await sidebar.getByText('기준정보', { exact: true }).waitFor();
    async function openScreen() { await sidebar.getByRole('button', { name: '품목 관리', exact: true }).click(); }
    await openScreen();
    const screen = page.getByRole('tabpanel', { name: '품목 관리', exact: true });
    const heading = screen.getByRole('heading', { name: '품목 관리', exact: true });
    const toolbar = screen.getByRole('toolbar', { name: '업무 버튼', exact: true });
    const query = screen.locator('form[data-ui="query-panel"]');
    const editor = screen.locator('form[data-ui="record-editor"]');
    const table = screen.locator('table');
    const basicTab = screen.getByRole('tab', { name: '기본정보', exact: true });
    const controls = Object.fromEntries(FIELDS.map((key, index) => [key, editor.getByLabel(new RegExp('^' + LABELS[index]))]));
    const queryCode = query.getByLabel(/^품번/), queryName = query.getByLabel(/^품명/);
    const row = code => table.getByRole('row').filter({ has: page.getByRole('cell', { name: code, exact: true }) });
    const select = code => row(code).click();
    async function countRows(expected) {
      const count = () => table.locator('tbody tr').count();
      for (let tries = 0; tries < 30 && await count() !== expected; tries++) await page.waitForTimeout(50);
      assert.equal(await count(), expected, 'Unexpected number of selectable item rows');
    }
    async function fill(record) { for (const key of FIELDS) await controls[key].fill(record[key] ?? ''); }
    async function expectRecord(record) { for (const key of FIELDS) assert.equal(await controls[key].inputValue(), record[key] ?? '', key + ' draft differs'); }
    async function browserWrite(action, method) {
      const response = page.waitForResponse(res => new URL(res.url()).pathname.startsWith('/api/items') && res.request().method() === method);
      const [res] = await Promise.all([response, action()]);
      return res;
    }
    async function submitQuery() {
      const response = page.waitForResponse(res => new URL(res.url()).pathname === '/api/items' && res.request().method() === 'GET');
      const [res] = await Promise.all([response, toolbar.getByRole('button', { name: '조회', exact: true }).click()]);
      assert.equal(res.status(), 200);
    }
    const saveClick = () => toolbar.getByRole('button', { name: '저장', exact: true }).click();
    const newClick = () => toolbar.getByRole('button', { name: '신규', exact: true }).click();
    await queryCode.waitFor(); await submitQuery(); await row(first.itemCode).waitFor(); await countRows(2);
    assert.equal(await editor.count(), 1, 'One basic record editor is required');
    for (const label of ['조회', '신규', '삭제', '저장']) await toolbar.getByRole('button', { name: label, exact: true }).waitFor();
    for (const label of LABELS) await table.getByRole('columnheader', { name: label, exact: true }).waitFor();
    const titleBox = await heading.boundingBox(), toolbarBox = await toolbar.boundingBox();
    assert.ok(toolbarBox.x > titleBox.x && Math.abs(toolbarBox.y - titleBox.y) < 45, 'Common actions must be beside the title');
    assert.ok(await heading.evaluate(el => parseFloat(getComputedStyle(el).fontSize) <= 18), 'Title must remain compact');
    const queryBox = await query.boundingBox(), resultsBox = await screen.locator('[data-region="results"]').boundingBox();
    const editorPanel = screen.locator('[data-region="editor"]'), editorBox = await editorPanel.boundingBox();
    assert.ok(resultsBox.y >= queryBox.y + queryBox.height - 1, 'Results must be below query conditions');
    assert.ok(editorBox.y >= resultsBox.y + resultsBox.height - 1, 'Editor must be at the bottom');
    assert.equal(await queryName.isVisible(), false, 'Detailed name condition starts collapsed');
    await basicTab.waitFor();
    passed('source-menu-layout-toolbar');

    for (const record of [first, second]) { await select(record.itemCode); await expectRecord(record); }
    passed('row-selection-loads-all-fields');
    const draft = { ...second, itemName: '보존할 품명', remark: '아직 저장하지 않음' };
    await fill(draft);
    const otherTab = screen.getByRole('tab').filter({ hasNotText: '기본정보' }).first();
    if (await otherTab.count()) { await otherTab.click(); await basicTab.click(); await expectRecord(draft); }
    await queryCode.fill('A-'); await countRows(2); await expectRecord(draft);
    await submitQuery(); await row(second.itemCode).waitFor({ state: 'hidden' }); await countRows(1); await expectRecord(draft);
    passed('query-submit-and-independent-draft');
    await query.getByRole('button', { name: '상세조건 펼치기', exact: true }).click();
    await queryName.fill('너트'); await submitQuery(); await row(first.itemCode).waitFor({ state: 'hidden' }); await countRows(0);
    await queryCode.fill(''); await query.getByRole('button', { name: '상세조건 접기', exact: true }).click();
    await submitQuery(); await row(second.itemCode).waitFor(); await countRows(1); await expectRecord(draft);
    await query.getByRole('button', { name: '상세조건 펼치기', exact: true }).click(); assert.equal(await queryName.inputValue(), '너트');
    await queryName.fill(''); await submitQuery(); await row(first.itemCode).waitFor(); await countRows(2);
    await query.getByRole('button', { name: '상세조건 접기', exact: true }).click();
    passed('query-and-collapsed-condition-retention');

    await newClick(); await basicTab.click(); await expectRecord({});
    const third = { itemCode: 'C-300', itemName: '평 와셔', specification: 'M12', unit: 'EA', remark: '신규 등록 확인' };
    await fill({ ...third, itemCode: ' ' + third.itemCode + ' ', itemName: ' ' + third.itemName + ' ' });
    const created = await browserWrite(saveClick, 'POST'); assert.ok([200, 201].includes(created.status()));
    await row(third.itemCode).waitFor(); await countRows(3);
    let stored = await db('ui-created-third-item'); assert.equal(stored.length, 3); assert.deepEqual(values(byCode(stored, third.itemCode)), third);
    const thirdId = byCode(stored, third.itemCode).id;
    passed('ui-new-create-and-db-persistence');
    const thirdUpdated = { ...third, itemName: '평 와셔 수정', specification: 'M14', unit: 'SET', remark: '같은 행 두 번째 저장' };
    await fill(thirdUpdated);
    const updated = await browserWrite(saveClick, 'PUT'); assert.ok(updated.ok());
    await row(third.itemCode).getByRole('cell', { name: thirdUpdated.itemName, exact: true }).waitFor(); await countRows(3);
    stored = await db('ui-repeat-save-updated-same-id'); assert.equal(stored.length, 3);
    assert.equal(String(byCode(stored, third.itemCode).id), String(thirdId)); assert.deepEqual(values(byCode(stored, third.itemCode)), thirdUpdated);
    const firstUpdated = { ...first, itemName: '육각 볼트 수정', specification: 'M8×40', unit: 'PACK', remark: 'DB 영속성 확인' };
    await select(first.itemCode); await fill(firstUpdated);
    await screen.getByRole('button', { name: '편집 패널 접기', exact: true }).click();
    assert.equal(await editor.isVisible(), false);
    const collapsedSave = await browserWrite(saveClick, 'PUT'); assert.ok(collapsedSave.ok());
    await row(first.itemCode).getByRole('cell', { name: firstUpdated.itemName, exact: true }).waitFor();
    await expectRecord(firstUpdated); assert.equal(await basicTab.getAttribute('aria-selected'), 'true');
    stored = await db('ui-selected-update-and-collapsed-save'); assert.deepEqual(values(byCode(stored, first.itemCode)), firstUpdated);
    passed('ui-update-repeat-save-and-db');

    const beforeInvalid = await db('before-ui-invalid-writes');
    await newClick(); await expectRecord({});
    for (const field of ['itemCode', 'itemName']) {
      for (const blank of ['', '   ']) {
        await fill({ ...third, itemCode: 'INVALID-UI-' + field, [field]: blank });
        const priorWrites = browserWriteStarts.length;
        await saveClick(); await page.waitForTimeout(150);
        assert.equal(browserWriteStarts.length, priorWrites, 'Frontend must reject blank ' + field + ' before sending a write');
        assert.ok(await controls[field].evaluate(el => !el.checkValidity()) || await controls[field].getAttribute('aria-invalid') === 'true' || await editor.getByRole('alert').count() > 0, 'Frontend must explain the required field error');
        assert.deepEqual(await db('ui-rejected-' + field + '-' + (blank ? 'spaces' : 'empty')), beforeInvalid);
      }
    }
    await fill({ ...third, itemCode: first.itemCode });
    const duplicate = await browserWrite(saveClick, 'POST'); assert.ok([400, 409, 422].includes(duplicate.status()));
    await editor.getByRole('alert').first().waitFor();
    assert.ok((await editor.getByRole('alert').allTextContents()).some(text => text.trim()), 'UI must display duplicate error');
    assert.deepEqual(await db('ui-duplicate-create-no-db-change'), beforeInvalid); await countRows(3);
    await select(second.itemCode); await fill({ ...second, itemCode: first.itemCode });
    const duplicateUpdate = await browserWrite(saveClick, 'PUT'); assert.ok([400, 409, 422].includes(duplicateUpdate.status()));
    await editor.getByRole('alert').first().waitFor();
    assert.ok((await editor.getByRole('alert').allTextContents()).some(text => text.trim()), 'UI must display duplicate update error');
    assert.deepEqual(await db('ui-duplicate-update-no-db-change'), beforeInvalid);
    // The optional fields may all be empty; save/update still uses the existing row.
    await select(third.itemCode); await fill({ ...thirdUpdated, specification: '', unit: '', remark: '' });
    assert.ok((await browserWrite(saveClick, 'PUT')).ok());
    stored = await db('optional-empty-fields-accepted');
    assert.deepEqual(values(byCode(stored, third.itemCode)), { ...thirdUpdated, specification: '', unit: '', remark: '' });
    passed('ui-required-validation-and-duplicate-rejection');

    const beforeResize = await editorPanel.boundingBox();
    const separator = screen.getByRole('separator', { name: '편집 패널 높이', exact: true });
    await separator.focus(); await separator.press('ArrowUp');
    const keyboardBox = await editorPanel.boundingBox(); assert.ok(keyboardBox.height > beforeResize.height);
    const handle = await separator.boundingBox();
    await page.mouse.move(handle.x + handle.width / 2, handle.y + handle.height / 2); await page.mouse.down();
    await page.mouse.move(handle.x + handle.width / 2, handle.y - 24, { steps: 5 }); await page.mouse.up();
    const dragged = await editorPanel.boundingBox(); assert.ok(dragged.height > keyboardBox.height);
    await screen.getByRole('button', { name: '편집 패널 접기', exact: true }).click(); assert.ok((await editorPanel.boundingBox()).height <= 40);
    await screen.getByRole('button', { name: '편집 패널 펼치기', exact: true }).click(); assert.ok(Math.abs((await editorPanel.boundingBox()).height - dragged.height) < 2);
    passed('bottom-editor-resize-collapse');

    await select(third.itemCode);
    const deleteButton = toolbar.getByRole('button', { name: '삭제', exact: true });
    const beforeDelete = await db('before-delete');
    const confirmBox = page.getByRole('alertdialog');
    await deleteButton.click(); await confirmBox.getByRole('button', { name: '취소', exact: true }).click(); await page.waitForTimeout(150);
    assert.deepEqual(await db('cancelled-delete-keeps-row'), beforeDelete); await countRows(3);
    await deleteButton.click();
    const deleted = await browserWrite(() => confirmBox.getByRole('button', { name: '삭제', exact: true }).click(), 'DELETE'); assert.ok(deleted.ok());
    await row(third.itemCode).waitFor({ state: 'hidden' }); await countRows(2);
    const finalDb = await db('confirmed-delete-removed-real-row');
    assert.equal(finalDb.length, 2); assert.equal(byCode(finalDb, third.itemCode), undefined);
    assert.deepEqual(values(byCode(finalDb, first.itemCode)), firstUpdated); assert.deepEqual(values(byCode(finalDb, second.itemCode)), second);
    passed('delete-cancel-confirm-and-db');

    await page.reload(); await openScreen(); await submitQuery(); await row(first.itemCode).waitFor(); await countRows(2);
    assert.equal(await row(third.itemCode).count(), 0);
    await select(first.itemCode); await expectRecord(firstUpdated);
    await select(second.itemCode); await expectRecord(second);
    assert.deepEqual(await db('fresh-browser-load-keeps-updates-and-delete'), finalDb);
    const apiFinal = await list(); assert.equal(apiFinal.length, 2); assert.deepEqual(values(byCode(apiFinal, first.itemCode)), firstUpdated);
    passed('reload-persist-updates-delete');
    for (const width of [1440, 1280]) {
      await page.setViewportSize({ width, height: 1000 });
      assert.ok(await screen.evaluate(el => el.scrollWidth <= el.clientWidth + 1), 'Screen must fit available width');
      await page.screenshot({ path: path.join(out, 'item-master-' + width + '.png'), fullPage: true });
    }
    assert.deepEqual(runtimeErrors, []); assert.deepEqual(forbiddenRequests, []);
    for (const method of ['GET', 'POST', 'PUT', 'DELETE']) assert.ok(requests.some(request => request.origin === 'browser' && request.method === method && request.status >= 200 && request.status < 300), 'Missing real browser API ' + method);
    passed('responsive-no-runtime-errors-real-api-only');
    assert.equal(cases.length, CASES.length);
    result = { passed: true, cases, runtimeErrors, requests, forbiddenRequests, sqlProofs, database: backend.db_name, evidence: out };
  } catch (error) {
    if (page) try { await page.screenshot({ path: path.join(out, 'failure.png'), fullPage: true, timeout: 5000 }); } catch (_) { /* Preserve original failure. */ }
    result = { passed: false, cases, runtimeErrors, requests, forbiddenRequests, sqlProofs, failure: String(error), evidence: out };
  } finally {
    const failures = [];
    if (browser) try { await browser.close(); } catch (error) { failures.push('browser: ' + error); }
    if (server) try { await server.close(); } catch (error) { failures.push('preview: ' + error); }
    if (runtime) try { cleanup = await runtime.close(); } catch (error) { failures.push('isolated backend: ' + error); cleanup = { success: false, error: String(error) }; }
    result = result || { passed: false, cases, failure: 'Oracle did not produce a result', evidence: out };
    result.cleanup = cleanup;
    if (failures.length || cleanup.success !== true) {
      result.passed = false;
      result.failure = [result.failure, ...failures].filter(Boolean).join('\n');
    }
    fs.writeFileSync(path.join(out, 'result.json'), JSON.stringify(result, null, 2));
  }
  console.log(JSON.stringify(result));
  return result;
}

module.exports = { verify, CASES };
if (require.main === module) {
  if (!process.argv[2]) { console.error('Usage: node browser_gemma_item_crud.cjs OUTPUT_DIRECTORY'); process.exitCode = 2; }
  else verify(process.argv[2]).then(result => { if (!result.passed) process.exitCode = 1; }).catch(error => { console.error(error); process.exitCode = 1; });
}
