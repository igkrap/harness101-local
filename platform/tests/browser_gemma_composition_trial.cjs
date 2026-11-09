// Independent, pre-trial behavioral oracle. Do not change it to fit a candidate.
// Authentication uses the existing trusted helper; all business writes are blocked.
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const root = path.resolve(__dirname, '../../local-only');

async function verify(out) {
  out = path.resolve(out);
  fs.mkdirSync(out, { recursive: true });
  const cases = [], runtimeErrors = [], businessWrites = [], definitionReads = [];
  let browser, server, page, catalogReads = 0;
  const passed = name => { cases.push(name); console.log('GEMMA_COMPOSITION_OK: ' + name); };
  const persist = result => fs.writeFileSync(path.join(out, 'result.json'), JSON.stringify(result, null, 2));
  try {
    assert.ok(fs.existsSync(path.join(root, 'frontend/src/screens/EquipmentLoans.tsx')), 'Gemma must create EquipmentLoans.tsx');
    const config = JSON.parse(fs.readFileSync(path.join(process.env.HOME, '.local/share/mlx-server/browser-check/runtime.json'), 'utf8'));
    const { chromium } = require(config.playwrightModule);
    const { createServer } = await import(`file://${path.join(root, 'frontend/node_modules/vite/dist/node/index.js')}`);
    server = await createServer({ root: path.join(root, 'frontend'), logLevel: 'silent', server: { host: '127.0.0.1', port: 0, strictPort: true } });
    await server.listen();
    const base = 'http://127.0.0.1:' + server.httpServer.address().port;
    browser = await chromium.launch({ headless: true });
    page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
    page.setDefaultTimeout(7000);
    page.on('pageerror', error => runtimeErrors.push(error.message));
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
    await sidebar.getByText('Gemma 시험', { exact: true }).waitFor();
    await sidebar.getByRole('button', { name: '장비 대여 관리', exact: true }).click();
    const screen = page.getByRole('tabpanel', { name: '장비 대여 관리', exact: true });
    await screen.waitFor();
    const heading = screen.getByRole('heading', { name: '장비 대여 관리', exact: true });
    const toolbar = screen.getByRole('toolbar', { name: '업무 버튼', exact: true });
    const query = screen.locator('form[data-ui="query-panel"]');
    const editor = screen.locator('form[data-ui="record-editor"]');
    const table = screen.locator('table');
    const basicTab = screen.getByRole('tab', { name: '기본정보', exact: true });
    const infoTab = screen.getByRole('tab', { name: '안내', exact: true });
    const queryEquipment = query.getByLabel(/^장비명/), queryBorrower = query.getByLabel(/^대여자/);
    const equipment = editor.getByLabel(/^장비명/), borrower = editor.getByLabel(/^대여자/), quantity = editor.getByLabel(/^수량/);
    const loanRow = name => table.getByRole('row').filter({ has: page.getByRole('cell', { name, exact: true }) });
    // Count selectable records, not the table's decorative empty-state row.
    const countRows = async expected => assert.equal(await table.locator('tbody tr').count(), expected);
    const submitQuery = () => toolbar.getByRole('button', { name: '조회', exact: true }).click();
    const save = () => toolbar.getByRole('button', { name: '저장', exact: true }).click();
    async function fillRecord(name, person, amount) {
      await equipment.fill(name); await borrower.fill(person); await quantity.fill(String(amount));
    }
    async function expectRecord(name, person, amount) {
      assert.equal(await equipment.inputValue(), name);
      assert.equal(await borrower.inputValue(), person);
      assert.equal(await quantity.inputValue(), String(amount));
    }
    await queryEquipment.waitFor();
    await table.getByRole('cell', { name: '노트북', exact: true }).waitFor();
    await countRows(2);
    for (const name of ['조회', '신규', '저장']) await toolbar.getByRole('button', { name, exact: true }).waitFor();
    const titleBox = await heading.boundingBox(), toolbarBox = await toolbar.boundingBox();
    assert.ok(toolbarBox.x > titleBox.x && Math.abs(toolbarBox.y - titleBox.y) < 45, 'Common actions must be beside the compact title at the top');
    assert.ok(await heading.evaluate(el => parseFloat(getComputedStyle(el).fontSize) <= 18), 'Title should remain compact');
    assert.equal(await queryBorrower.isVisible(), false, 'Detailed borrower condition starts collapsed');
    passed('source-screen-menu-compact-title-common-toolbar');

    for (const [name, person, amount] of [['노트북', '김하나', 2], ['모니터', '이두리', 1]]) {
      await loanRow(name).click();
      await expectRecord(name, person, amount);
    }
    passed('two-row-selection-loads-all-fields');
    await equipment.fill('보존할 편집값');
    await queryEquipment.fill('노트');
    await countRows(2);
    await expectRecord('보존할 편집값', '이두리', 1);
    await submitQuery();
    await table.getByRole('cell', { name: '모니터', exact: true }).waitFor({ state: 'hidden' });
    await countRows(1);
    await expectRecord('보존할 편집값', '이두리', 1);
    passed('query-submit-filters-with-independent-editor-draft');
    await query.getByRole('button', { name: '상세조건 펼치기', exact: true }).click();
    await queryBorrower.fill('이두리');
    await submitQuery();
    await table.getByRole('cell', { name: '노트북', exact: true }).waitFor({ state: 'hidden' });
    await countRows(0);
    await queryEquipment.fill('');
    await query.getByRole('button', { name: '상세조건 접기', exact: true }).click();
    await submitQuery();
    await table.getByRole('cell', { name: '모니터', exact: true }).waitFor();
    await countRows(1);
    await query.getByRole('button', { name: '상세조건 펼치기', exact: true }).click();
    assert.equal(await queryBorrower.inputValue(), '이두리');
    await queryBorrower.fill(''); await submitQuery();
    await table.getByRole('cell', { name: '노트북', exact: true }).waitFor();
    await query.getByRole('button', { name: '상세조건 접기', exact: true }).click();
    passed('query-conditions-and-combination-collapsed-retention');

    await loanRow('노트북').click();
    await fillRecord('노트북 변경', '최네리', 4);
    await infoTab.click();
    await screen.getByText('저장은 현재 화면에만 반영됩니다.', { exact: true }).waitFor();
    await basicTab.click(); await expectRecord('노트북 변경', '최네리', 4);
    await infoTab.click();
    await screen.getByRole('button', { name: '편집 패널 접기', exact: true }).click();
    assert.equal(await editor.isVisible(), false);
    await save();
    await table.getByRole('cell', { name: '노트북 변경', exact: true }).waitFor();
    await countRows(2);
    await expectRecord('노트북 변경', '최네리', 4);
    assert.equal(await basicTab.getAttribute('aria-selected'), 'true');
    assert.equal(await loanRow('노트북 변경').getByRole('cell', { name: '최네리', exact: true }).count(), 1);
    assert.equal(await loanRow('노트북 변경').getByRole('cell', { name: '4', exact: true }).count(), 1);
    passed('tab-draft-retention-collapsed-save-reveals-and-updates');

    const rowBeforeInvalid = await loanRow('노트북 변경').innerText();
    for (const invalidQuantity of ['0', '-1', '1.5']) {
      await quantity.fill(invalidQuantity); await save();
      await page.waitForTimeout(150);
      assert.equal(await loanRow('노트북 변경').innerText(), rowBeforeInvalid, 'Invalid quantity must not modify a saved row: ' + invalidQuantity);
    }
    await quantity.fill('4');
    await equipment.fill(''); await save(); await page.waitForTimeout(150);
    assert.equal(await loanRow('노트북 변경').innerText(), rowBeforeInvalid, 'Required equipment must reject an empty value');
    await equipment.fill('노트북 변경'); await borrower.fill(''); await save(); await page.waitForTimeout(150);
    assert.equal(await loanRow('노트북 변경').innerText(), rowBeforeInvalid, 'Required borrower must reject an empty value');
    await borrower.fill('최네리');
    passed('required-text-and-positive-integer-validation');

    await toolbar.getByRole('button', { name: '신규', exact: true }).click();
    await basicTab.click();
    assert.equal(await equipment.inputValue(), '');
    assert.equal(await borrower.inputValue(), '');
    await save(); await page.waitForTimeout(150); await countRows(2);
    await fillRecord('태블릿', '윤다섯', 3); await save();
    await table.getByRole('cell', { name: '태블릿', exact: true }).waitFor();
    await countRows(3);
    await fillRecord('태블릿 수정', '윤다섯', 5); await save();
    await table.getByRole('cell', { name: '태블릿 수정', exact: true }).waitFor();
    await countRows(3);
    assert.equal(await loanRow('태블릿 수정').getByRole('cell', { name: '5', exact: true }).count(), 1);
    passed('new-clears-creates-and-repeat-save-updates');

    const editorPanel = screen.locator('[data-region="editor"]');
    const resultsPanel = screen.locator('[data-region="results"]');
    const editorBox = await editorPanel.boundingBox(), resultsBox = await resultsPanel.boundingBox();
    assert.ok(editorBox.y >= resultsBox.y + resultsBox.height - 1, 'Editor must be below the results');
    const separator = screen.getByRole('separator', { name: '편집 패널 높이', exact: true });
    await separator.focus(); await separator.press('ArrowUp');
    const keyboardBox = await editorPanel.boundingBox();
    assert.ok(keyboardBox.height > editorBox.height, 'Keyboard divider control must resize the editor');
    const handle = await separator.boundingBox();
    await page.mouse.move(handle.x + handle.width / 2, handle.y + handle.height / 2);
    await page.mouse.down(); await page.mouse.move(handle.x + handle.width / 2, handle.y - 24, { steps: 5 }); await page.mouse.up();
    const resizedBox = await editorPanel.boundingBox();
    assert.ok(resizedBox.height > keyboardBox.height, 'Pointer drag must resize the editor');
    await screen.getByRole('button', { name: '편집 패널 접기', exact: true }).click();
    assert.ok((await editorPanel.boundingBox()).height <= 40);
    await screen.getByRole('button', { name: '편집 패널 펼치기', exact: true }).click();
    assert.ok(Math.abs((await editorPanel.boundingBox()).height - resizedBox.height) < 2);
    passed('bottom-editor-pointer-keyboard-resize-collapse-height');
    for (const width of [1440, 1280]) {
      await page.setViewportSize({ width, height: 1000 });
      assert.ok(await screen.evaluate(el => el.scrollWidth <= el.clientWidth + 1), 'Screen must fit available width');
      await page.screenshot({ path: path.join(out, 'equipment-loans-' + width + '.png'), fullPage: true });
    }
    assert.deepEqual(runtimeErrors, []);
    assert.deepEqual(businessWrites, []);
    assert.deepEqual(definitionReads, []);
    assert.ok(catalogReads > 0);
    passed('two-widths-no-runtime-errors-no-business-writes-no-db-definition');
    const result = { passed: true, cases, runtimeErrors, businessWrites: 0, dbDefinitionReads: 0, optionalCatalog: 'empty fixture', dataPersistence: 'screen memory only', evidence: out };
    persist(result); console.log(JSON.stringify(result)); return result;
  } catch (error) {
    if (page) {
      try { await page.screenshot({ path: path.join(out, 'failure.png'), fullPage: true, timeout: 5000 }); } catch (_) { /* Preserve original failure. */ }
    }
    const result = { passed: false, cases, runtimeErrors, businessWrites, definitionReads, failure: String(error), evidence: out };
    persist(result); console.error(JSON.stringify(result)); return result;
  } finally {
    if (browser) await browser.close();
    if (server) await server.close();
  }
}

module.exports = { verify };
if (require.main === module) {
  if (!process.argv[2]) { console.error('Usage: node browser_gemma_composition_trial.cjs OUTPUT_DIRECTORY'); process.exitCode = 2; }
  else verify(process.argv[2]).then(result => { if (!result.passed) process.exitCode = 1; }).catch(error => { console.error(error); process.exitCode = 1; });
}
