// Stage 1 checks layout only. Business queries and writes belong to later stages.
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const root = path.resolve(__dirname, '../../local-only');
const CASES = ['query-grid-bottom-editor-layout', 'five-item-columns-and-edit-inputs', 'editor-collapse-resize-no-runtime-errors'];

function classifyRequest({ url: address, method, resourceType }, base) {
  const url = new URL(address);
  const external = ['http:', 'https:'].includes(url.protocol) && url.origin !== base;
  // main.tsx loads these font assets through the existing neutral theme.
  // They remain blocked; only their evidence category differs from business traffic.
  const themeFont = method === 'GET' && (
    (url.origin === 'https://fonts.googleapis.com' && resourceType === 'stylesheet') ||
    (url.origin === 'https://fonts.gstatic.com' && resourceType === 'font')
  );
  if (external && themeFont) return 'blocked-static';
  const frameworkApi = url.pathname.startsWith('/api/auth/') ||
    (url.pathname === '/api/screens' && ['GET', 'HEAD', 'OPTIONS'].includes(method));
  return external || (url.pathname.startsWith('/api/') && !frameworkApi) ? 'business' : 'allow';
}

async function verify(output) {
  const out = path.resolve(output);
  fs.mkdirSync(out, { recursive: true });
  const cases = [], runtimeErrors = [], businessRequests = [], blockedStaticRequests = [], cleanupErrors = [];
  let browser, server, page, result;
  const passed = name => { cases.push(name); console.log('ITEM_LAYOUT_OK: ' + name); };
  try {
    assert.ok(fs.existsSync(path.join(root, 'frontend/src/screens/ItemMaster.tsx')), 'Create the new screen frontend/src/screens/ItemMaster.tsx');
    const config = JSON.parse(fs.readFileSync(path.join(process.env.HOME, '.local/share/mlx-server/browser-check/runtime.json'), 'utf8'));
    const { chromium } = require(config.playwrightModule);
    const { createServer } = await import(`file://${path.join(root, 'frontend/node_modules/vite/dist/node/index.js')}`);
    server = await createServer({ root: path.join(root, 'frontend'), logLevel: 'silent',
      server: { host: '127.0.0.1', port: 0, strictPort: true, proxy: { '/api': { target: 'http://127.0.0.1:8083', changeOrigin: true } } } });
    await server.listen();
    const base = 'http://127.0.0.1:' + server.httpServer.address().port;
    browser = await chromium.launch({ headless: true });
    page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
    page.setDefaultTimeout(7000);
    page.on('pageerror', error => runtimeErrors.push(error.message));
    // The helper reads the current private login file on every invocation.
    assert.equal(await require('../../local-only/harness/trusted_auth.cjs').ensureAuthenticated(page.request, base, { localProxy: true }), true);
    await page.route('**/*', route => {
      const request = route.request(), url = new URL(request.url());
      const category = classifyRequest({ url: request.url(), method: request.method(), resourceType: request.resourceType() }, base);
      if (category !== 'allow') {
        const evidence = category === 'blocked-static' ? blockedStaticRequests : businessRequests;
        evidence.push(request.method() + ' ' + url.origin + url.pathname);
        return route.abort();
      }
      return route.continue();
    });
    await page.goto(base);
    const meta = await page.evaluate(async () => (await import('/src/screens/ItemMaster.tsx')).meta);
    assert.equal(meta?.code, 'MST0001', 'Screen code must be MST0001');
    assert.ok(typeof meta?.title === 'string' && meta.title.trim() && meta.title.includes('품목'), 'Provide a nonempty item screen title');
    const sidebar = page.getByRole('navigation', { name: 'Side navigation', exact: true });
    const expandSidebar = sidebar.getByRole('button', { name: 'Expand sidebar', exact: true });
    if (await expandSidebar.isVisible()) await expandSidebar.click();
    await sidebar.getByRole('button', { name: meta.title, exact: true }).click();
    const screen = page.getByRole('tabpanel', { name: meta.title, exact: true });
    await screen.waitFor();
    const query = screen.locator('form[data-ui="query-panel"]');
    const grid = screen.locator('table');
    const editor = screen.locator('form[data-ui="record-editor"]');
    assert.equal(await query.count(), 1, 'Use one shared query panel');
    assert.equal(await grid.count(), 1, 'Show one result grid');
    assert.equal(await editor.count(), 1, 'Use one shared item editor');
    await query.waitFor(); await grid.waitFor(); await editor.waitFor();
    assert.ok(await query.locator('input, select, textarea').count() > 0, 'The upper query panel needs a condition input');
    const queryBox = await query.boundingBox(), gridBox = await grid.boundingBox(), editorBox = await editor.boundingBox();
    assert.ok(gridBox.y >= queryBox.y + queryBox.height - 1, 'Place the result grid below the query panel');
    assert.ok(editorBox.y >= gridBox.y + gridBox.height - 1, 'Place the item editor below the result grid');
    passed('query-grid-bottom-editor-layout');

    for (const label of ['품번', '품명', '규격', '단위', '비고']) {
      await grid.getByRole('columnheader', { name: label, exact: true }).waitFor();
      const input = editor.getByLabel(new RegExp('^' + label));
      assert.equal(await input.count(), 1, 'Show one editor input for ' + label);
      await input.waitFor();
    }
    // Empty results and disabled/unconnected action buttons are valid in this stage.
    passed('five-item-columns-and-edit-inputs');

    const split = screen.locator('[data-ui="split-pane"]:has(form[data-ui="record-editor"])').last();
    assert.equal(await split.count(), 1, 'Reuse the shared split pane for the bottom editor');
    const separator = split.locator(':scope > [role="separator"][aria-orientation="horizontal"]');
    assert.equal(await separator.count(), 1, 'The bottom editor needs a horizontal resize handle');
    const editorRegion = split.locator(':scope > div').last();
    const before = await editorRegion.boundingBox();
    await separator.focus();
    await separator.press(Number(await separator.getAttribute('aria-valuenow')) > 20 ? 'ArrowUp' : 'ArrowDown');
    const keyboard = await editorRegion.boundingBox();
    assert.ok(Math.abs(keyboard.height - before.height) > 2, 'Keyboard resizing must change editor height');
    const handle = await separator.boundingBox();
    const delta = Number(await separator.getAttribute('aria-valuenow')) > 25 ? -24 : 24;
    await page.mouse.move(handle.x + handle.width / 2, handle.y + handle.height / 2);
    await page.mouse.down(); await page.mouse.move(handle.x + handle.width / 2, handle.y + delta, { steps: 5 }); await page.mouse.up();
    const resized = await editorRegion.boundingBox();
    assert.ok(Math.abs(resized.height - keyboard.height) > 3, 'Dragging must change editor height');
    await screen.getByRole('button', { name: /편집.*접기/ }).click();
    assert.equal(await editor.isVisible(), false, 'Collapse must hide the editor form');
    assert.ok((await editorRegion.boundingBox()).height < resized.height, 'Collapse must release editor space');
    await screen.getByRole('button', { name: /편집.*펼치기/ }).click();
    await editor.waitFor();
    assert.ok(Math.abs((await editorRegion.boundingBox()).height - resized.height) < 3, 'Expanding must restore the editor height');
    assert.deepEqual(runtimeErrors, [], 'The screen must render without runtime errors');
    assert.deepEqual(businessRequests, [], 'This stage must not connect business API queries or writes');
    passed('editor-collapse-resize-no-runtime-errors');
    await page.screenshot({ path: path.join(out, 'item-layout-1440.png'), fullPage: true });
    result = { passed: true, cases, runtimeErrors, businessRequests, blockedStaticRequests, databaseStarted: false, evidence: out };
  } catch (error) {
    if (page) try { await page.screenshot({ path: path.join(out, 'failure.png'), fullPage: true, timeout: 5000 }); } catch (_) { /* Preserve original failure. */ }
    result = { passed: false, cases, runtimeErrors, businessRequests, blockedStaticRequests, databaseStarted: false, failure: String(error), evidence: out };
  } finally {
    if (browser) try { await browser.close(); } catch (error) { cleanupErrors.push('browser: ' + error); }
    if (server) try { await server.close(); } catch (error) { cleanupErrors.push('preview: ' + error); }
    result = result || { passed: false, cases, failure: 'Layout check did not produce a result', evidence: out };
    result.cleanup = { success: cleanupErrors.length === 0, errors: cleanupErrors };
    if (cleanupErrors.length) { result.passed = false; result.failure = [result.failure, ...cleanupErrors].filter(Boolean).join('\n'); }
    fs.writeFileSync(path.join(out, 'result.json'), JSON.stringify(result, null, 2));
  }
  console.log(JSON.stringify(result));
  return result;
}

module.exports = { verify, CASES, classifyRequest };
if (require.main === module) {
  if (!process.argv[2]) { console.error('Usage: node browser_gemma_item_layout.cjs OUTPUT_DIRECTORY'); process.exitCode = 2; }
  else verify(process.argv[2]).then(result => { if (!result.passed) process.exitCode = 1; }).catch(error => { console.error(error); process.exitCode = 1; });
}
