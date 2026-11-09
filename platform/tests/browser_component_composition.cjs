// Exercise the real source-registered screens through the authenticated app.
// Sample saves are in-memory. Block business writes and remove the optional DB catalog.
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const root = path.resolve(__dirname, '../../local-only');
const out = path.resolve(process.argv[2] || path.join(__dirname, '../state/evidence', 'component-composition-' + Date.now()));
const config = JSON.parse(fs.readFileSync(path.join(process.env.HOME, '.local/share/mlx-server/browser-check/runtime.json'), 'utf8'));
const { chromium } = require(config.playwrightModule);

async function run() {
  fs.mkdirSync(out, { recursive: true });
  const { createServer } = await import(`file://${path.join(root, 'frontend/node_modules/vite/dist/node/index.js')}`);
  const server = await createServer({ root: path.join(root, 'frontend'), logLevel: 'silent', server: { host: '127.0.0.1', port: 0, strictPort: true } });
  let browser;
  const cases = [], errors = [], businessWrites = [], definitionReads = [];
  let catalogReads = 0;
  const passed = name => { cases.push(name); console.log('COMPOSITION_OK: ' + name); };
  try {
    await server.listen();
    const base = 'http://127.0.0.1:' + server.httpServer.address().port;
    browser = await chromium.launch({ headless: true });
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
    page.setDefaultTimeout(7000);
    page.on('pageerror', error => errors.push(error.message));
    await require('../../local-only/harness/trusted_auth.cjs').ensureAuthenticated(page.request, base, { localProxy: true });
    await page.route('**/api/**', route => {
      const request = route.request(), pathname = new URL(request.url()).pathname;
      if (!['GET', 'HEAD', 'OPTIONS'].includes(request.method())) {
        businessWrites.push(request.method() + ' ' + pathname);
        return route.abort();
      }
      if (pathname === '/api/screens') {
        catalogReads++;
        return route.fulfill({ json: [] });
      }
      if (pathname.startsWith('/api/screens/') || pathname.startsWith('/api/specs/')) {
        definitionReads.push(pathname);
        return route.abort();
      }
      return route.continue();
    });
    await page.goto(base);
    const sidebar = page.getByRole('navigation', { name: 'Side navigation', exact: true });
    const screen = kind => page.locator(`[data-demo="${kind}"]:visible`);
    async function open(title, kind) {
      await sidebar.getByRole('button', { name: title, exact: true }).click();
      const node = screen(kind);
      await node.waitFor();
      await node.getByText('예제 데이터 · 저장은 현재 화면에만 반영됩니다.', { exact: true }).waitFor();
      return node;
    }
    async function snapshot(name) {
      await page.screenshot({ path: path.join(out, name + '.png'), fullPage: true });
    }
    async function assertText(locator, expected) {
      await locator.filter({ hasText: expected }).waitFor();
    }
    function queryParts(node) {
      return { query: node.locator('form[data-ui="query-panel"]'), toolbar: node.getByRole('toolbar', { name: '업무 버튼' }) };
    }

    const queryOnly = await open('조회 조합', 'query');
    const q = queryParts(queryOnly), queryTable = queryOnly.locator('table');
    assert.equal(await queryTable.getByRole('row').count(), 4);
    assert.equal(await queryOnly.locator('form[data-ui="record-editor"]').count(), 0);
    await q.query.getByLabel(/^이름/).fill('김');
    assert.equal(await queryTable.getByRole('row').count(), 4, 'Query draft must not filter before submission');
    await q.toolbar.getByRole('button', { name: '조회', exact: true }).click();
    await queryTable.getByText('이두리', { exact: true }).waitFor({ state: 'hidden' });
    assert.equal(await queryTable.getByRole('row').count(), 2);
    passed('query-only-explicit-submit');
    await q.query.getByLabel(/^이름/).fill('');
    await q.query.getByRole('button', { name: '상세조건 펼치기', exact: true }).click();
    await q.query.getByLabel(/^부서/).fill('영업팀');
    await q.query.getByRole('button', { name: '상세조건 접기', exact: true }).click();
    await q.toolbar.getByRole('button', { name: '조회', exact: true }).click();
    await queryTable.getByText('박세나', { exact: true }).waitFor();
    assert.equal(await queryTable.getByRole('row').count(), 3);
    await q.query.getByRole('button', { name: '상세조건 펼치기', exact: true }).click();
    assert.equal(await q.query.getByLabel(/^부서/).inputValue(), '영업팀');
    passed('collapsed-advanced-filter-retains-and-applies');
    await snapshot('query-only-1440');

    const split = await open('다중 그리드 조합', 'split');
    const primary = split.getByRole('region', { name: '기본 목록', exact: true });
    const detail = split.getByRole('region', { name: '상세 목록', exact: true });
    await primary.getByRole('row').filter({ hasText: '김하나' }).click();
    const firstDetails = await detail.innerText();
    assert.ok(await detail.locator('tbody tr').count() > 0);
    await primary.getByRole('row').filter({ hasText: '이두리' }).click();
    assert.notEqual(await detail.innerText(), firstDetails, 'Detail data must follow master selection');
    const selectedDetails = await detail.innerText();
    let p = await primary.boundingBox(), d = await detail.boundingBox();
    assert.ok(d.x >= p.x + p.width - 1, 'Horizontal layout must place detail to the right');
    await split.getByLabel('배치 방향', { exact: true }).selectOption({ label: '상하' });
    p = await primary.boundingBox(); d = await detail.boundingBox();
    assert.ok(d.y >= p.y + p.height - 1, 'Vertical layout must place detail below');
    assert.equal(await detail.innerText(), selectedDetails);
    passed('master-detail-and-direction-switch-preserve-selection');
    const splitHandle = split.getByRole('separator');
    const splitBefore = await splitHandle.getAttribute('aria-valuenow');
    await splitHandle.focus(); await splitHandle.press('ArrowDown');
    assert.ok(Number(await splitHandle.getAttribute('aria-valuenow')) > Number(splitBefore));
    passed('stacked-grid-keyboard-resize');
    await snapshot('split-vertical-1440');
    await split.getByLabel('배치 방향', { exact: true }).selectOption({ label: '좌우' });
    await page.setViewportSize({ width: 1280, height: 1000 });
    await snapshot('split-horizontal-1280');

    const editorScreen = await open('편집 탭 조합', 'editor');
    const edit = queryParts(editorScreen), rows = editorScreen.locator('[data-region="results"] table');
    const basicTab = editorScreen.getByRole('tab', { name: '기본정보', exact: true });
    const additionalTab = editorScreen.getByRole('tab', { name: '추가정보', exact: true });
    const basic = editorScreen.getByRole('tabpanel', { name: '기본정보', exact: true }).locator('form');
    const extra = editorScreen.getByRole('tabpanel', { name: '추가정보', exact: true }).locator('form');
    const nameInput = basic.getByLabel(/^이름/), quotaInput = extra.getByLabel(/^허용량/);
    await rows.getByRole('row').filter({ hasText: '김하나' }).click();
    assert.equal(await nameInput.inputValue(), '김하나');
    await nameInput.fill('김하나 수정');
    await additionalTab.click();
    const initialQuota = await quotaInput.inputValue();
    await quotaInput.fill('73');
    await editorScreen.getByRole('button', { name: '편집 패널 접기', exact: true }).click();
    await edit.toolbar.getByRole('button', { name: '저장', exact: true }).click();
    await rows.getByText('김하나 수정', { exact: true }).waitFor();
    assert.equal(await basicTab.getAttribute('aria-selected'), 'true');
    assert.equal(await nameInput.inputValue(), '김하나 수정');
    const changedRow = rows.getByRole('row').filter({ hasText: '김하나 수정' });
    assert.equal(await changedRow.getByRole('cell', { name: initialQuota, exact: true }).count(), 1, 'Basic save must not save another tab');
    await additionalTab.click();
    assert.equal(await quotaInput.inputValue(), '73', 'Saving one tab must preserve another tab draft');
    passed('explicit-save-scope-and-other-tab-draft-retention');
    await quotaInput.fill('-1');
    await extra.getByRole('button', { name: '저장', exact: true }).click();
    await assertText(extra.getByRole('alert'), '0 이상이어야 합니다.');
    assert.equal(await changedRow.getByRole('cell', { name: initialQuota, exact: true }).count(), 1);
    await quotaInput.fill('73');
    await extra.getByRole('button', { name: '저장', exact: true }).click();
    await changedRow.getByRole('cell', { name: '73', exact: true }).waitFor();
    passed('additional-tab-validation-and-independent-save');
    await basicTab.click();
    await nameInput.fill('보존할 이름');
    await edit.query.getByLabel(/^이름/).fill('없는 결과');
    await edit.toolbar.getByRole('button', { name: '조회', exact: true }).click();
    await rows.getByText('김하나 수정', { exact: true }).waitFor({ state: 'hidden' });
    assert.equal(await nameInput.inputValue(), '보존할 이름');
    await open('조회 조합', 'query');
    await open('편집 탭 조합', 'editor');
    assert.equal(await nameInput.inputValue(), '보존할 이름');
    passed('query-and-mdi-switch-preserve-editor-draft');
    const tabs = page.getByRole('navigation', { name: 'Tabs', exact: true });
    let dirtyClose = false;
    page.once('dialog', async dialog => { dirtyClose = true; await dialog.dismiss(); });
    await tabs.getByRole('button', { name: '편집 탭 조합 닫기', exact: true }).click();
    assert.equal(dirtyClose, true);
    assert.equal(await editorScreen.isVisible(), true);
    passed('dirty-close-guard');
    await edit.query.getByLabel(/^이름/).fill('');
    await edit.toolbar.getByRole('button', { name: '조회', exact: true }).click();
    await rows.getByText('김하나 수정', { exact: true }).waitFor();
    await edit.toolbar.getByRole('button', { name: '신규', exact: true }).click();
    assert.equal(await nameInput.inputValue(), '');
    await additionalTab.click();
    assert.equal(await quotaInput.isDisabled(), true, 'Additional save must wait for a master record');
    await edit.toolbar.getByRole('button', { name: '저장', exact: true }).click();
    await nameInput.waitFor();
    assert.equal(await rows.getByRole('row').count(), 4, 'Required empty form must not create');
    await nameInput.fill('신규 예제');
    await basic.getByLabel(/^이메일/).fill('new@example.invalid');
    await edit.toolbar.getByRole('button', { name: '저장', exact: true }).click();
    await rows.getByText('신규 예제', { exact: true }).waitFor();
    assert.equal(await rows.getByRole('row').count(), 5);
    await nameInput.fill('신규 예제 수정');
    await edit.toolbar.getByRole('button', { name: '저장', exact: true }).click();
    await rows.getByText('신규 예제 수정', { exact: true }).waitFor();
    assert.equal(await rows.getByRole('row').count(), 5, 'Saving a new record twice must update its assigned ID');
    passed('new-resets-required-validation-and-save-updates');
    const resultsRegion = editorScreen.locator('[data-region="results"]'), editorRegion = editorScreen.locator('[data-region="editor"]');
    const resultBox = await resultsRegion.boundingBox(), editorBox = await editorRegion.boundingBox();
    assert.ok(editorBox.y >= resultBox.y + resultBox.height - 1);
    const bottomHandle = editorScreen.getByRole('separator', { name: '편집 패널 높이' });
    await bottomHandle.focus(); await bottomHandle.press('ArrowUp');
    const resized = await editorRegion.boundingBox();
    assert.ok(resized.height > editorBox.height);
    const handleBox = await bottomHandle.boundingBox();
    await page.mouse.move(handleBox.x + handleBox.width / 2, handleBox.y + handleBox.height / 2);
    await page.mouse.down(); await page.mouse.move(handleBox.x + handleBox.width / 2, handleBox.y - 25, { steps: 5 }); await page.mouse.up();
    const dragged = await editorRegion.boundingBox();
    assert.ok(dragged.height > resized.height);
    await editorScreen.getByRole('button', { name: '편집 패널 접기', exact: true }).click();
    assert.ok((await editorRegion.boundingBox()).height <= 40);
    await editorScreen.getByRole('button', { name: '편집 패널 펼치기', exact: true }).click();
    assert.ok(Math.abs((await editorRegion.boundingBox()).height - dragged.height) < 2);
    passed('bottom-editor-resize-collapse-restores-height');
    for (const width of [1280, 1440]) {
      await page.setViewportSize({ width, height: 1000 });
      assert.ok(await editorScreen.evaluate(el => el.scrollWidth <= el.clientWidth + 1), 'Screen must fit available width');
      await snapshot('editor-tabs-' + width);
    }
    assert.deepEqual(businessWrites, []);
    assert.deepEqual(definitionReads, []);
    assert.ok(catalogReads > 0, 'Optional DB catalog must have been replaced with an empty catalog');
    assert.deepEqual(errors, []);
    passed('source-screens-with-empty-db-catalog-no-business-writes');
    const result = { passed: true, cases, businessWrites: 0, dbDefinitionReads: 0, optionalCatalog: 'empty fixture', modelCalls: 0, dataPersistence: 'screen memory only', evidence: out };
    fs.writeFileSync(path.join(out, 'result.json'), JSON.stringify(result, null, 2));
    console.log(JSON.stringify(result));
  } catch (error) {
    fs.writeFileSync(path.join(out, 'result.json'), JSON.stringify({ passed: false, cases, errors, businessWrites, definitionReads, failure: String(error) }, null, 2));
    throw error;
  } finally {
    if (browser) await browser.close();
    await server.close();
  }
}
run().catch(error => { console.error(error); process.exitCode = 1; });
