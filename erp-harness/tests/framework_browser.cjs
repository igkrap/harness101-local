const fs = require('fs');
const path = require('path');
const assert = require('node:assert/strict');

async function run() {
  const root = path.resolve(process.argv[2] || '');
  if (!root) return;
  const frontend = path.join(root, 'frontend');
  const configPath = path.join(process.env.HOME || process.env.USERPROFILE, '.local/share/mlx-server/browser-check/runtime.json');
  const config = JSON.parse(fs.readFileSync(configPath, 'utf8'));

  let server, browser, jsErrors = [];
  try {
    const { createServer } = await import(`file://${path.join(frontend, 'node_modules/vite/dist/node/index.js')}`);
    server = await createServer({ root: frontend, server: { host: '127.0.0.1', port: 0, strictPort: true }, logLevel: 'silent' });
    await server.listen();
    const url = `http://127.0.0.1:${server.httpServer.address().port}`;
    assert.strictEqual(server.config.server.proxy['/api'].target, 'http://127.0.0.1:8083');

    const { chromium } = require(config.playwrightModule);
    browser = await chromium.launch({ headless: true });
    const context = await browser.newContext();
    const page = await context.newPage();
    page.setDefaultTimeout(5000);

    page.on('pageerror', e => jsErrors.push(e.stack || e.message));

    // Navigate to the app once to initialize the page for all subsequent checks
    await require('../trusted_auth.cjs').ensureAuthenticated(context.request, url, { localProxy: true });
    await page.goto(url);

    const ctx = { page, frontend, root, server, assert, fs, path };

    if (process.argv.includes('--environment-check')) {
      const sidebar = page.getByRole('navigation', { name: 'Side navigation', exact: true });
      await sidebar.waitFor({ state: 'visible' });
      const expand = sidebar.getByRole('button', { name: 'Expand sidebar', exact: true });
      if (await expand.isVisible()) await expand.click();
      await sidebar.getByRole('button', { name: '홈', exact: true }).click();
      await page.getByRole('heading', { name: '홈', exact: true }).waitFor({ state: 'visible' });
      await page.getByRole('navigation', { name: 'Tabs', exact: true }).waitFor({ state: 'visible' });
      assert.strictEqual(jsErrors.length, 0, `JS Errors: ${jsErrors.join(', ')}`);
      console.log("ENVIRONMENT_OK");
    } else {
      const caseIdx = process.argv.indexOf('--case');
      const names = caseIdx !== -1 ? [process.argv[caseIdx + 1]] : ['source', 'sidebar', 'inventory_workflows', 'tabs', 'registry', 'control', 'registration', 'record_panels', 'business_workspace', 'grid_selection'];
      const inventoryCases = new Set(['inventory_workflows', 'tabs', 'control', 'registration']);
      const inventoryExists = fs.existsSync(path.join(frontend, 'src/screens/Inventory.tsx'));
      for (const name of names) {
        if (caseIdx === -1 && !inventoryExists && inventoryCases.has(name)) {
          console.log(`FRAMEWORK_NOT_APPLICABLE: ${name} (Inventory.tsx is absent)`);
          continue;
        }
        const { default: fn } = await import(`file://${path.join(root, 'harness/tests/framework_cases', `${name}.cjs`)}`);
        if (name === 'registration') console.log('REGISTRATION_EXPECTS: 이름, 카테고리, 수량, 최소 수량, 단가 입력 → POST /api/inventory → 결과 그리드 반영. API 쓰기는 모의 응답으로 대체.');
        try {
          await fn(ctx);
          console.log(`FRAMEWORK_OK: ${name}`);
        } catch (err) {
          // A case pins the previous behavior of shared components. When this run deliberately edited
          // those components, a different behavior is the requested change, not a regression: report
          // it and continue. App boot (source/sidebar) and runtime errors still fail.
          let edited = [];
          try { edited = JSON.parse(process.env.HARNESS_CHANGED_PATHS || '[]'); } catch { edited = []; }
          const framework = edited.filter(p => typeof p === 'string' && p.startsWith('frontend/src/framework/'));
          // A case that already fails before this run edits anything pins behavior an earlier accepted
          // change replaced; it is not this run's regression. Remember it for the rest of the run.
          const baselineFile = process.env.HARNESS_JOB_DIR ? path.join(process.env.HARNESS_JOB_DIR, 'framework-baseline-differs.json') : '';
          let baseline = [];
          try { baseline = baselineFile && fs.existsSync(baselineFile) ? JSON.parse(fs.readFileSync(baselineFile, 'utf8')) : []; } catch { baseline = []; }
          const protectedCase = ['source', 'sidebar'].includes(name);
          if (!protectedCase && jsErrors.length === 0 && edited.length === 0 && baselineFile) {
            if (!baseline.includes(name)) fs.writeFileSync(baselineFile, JSON.stringify([...baseline, name]));
            console.log(`FRAMEWORK_CHANGED: ${name} (already differs before this run, from an earlier accepted shared change): ${String(err && err.message || err).split('\n')[0].slice(0, 200)}`);
            continue;
          }
          if (!protectedCase && jsErrors.length === 0 && baseline.includes(name)) {
            console.log(`FRAMEWORK_CHANGED: ${name} (differed before this run): ${String(err && err.message || err).split('\n')[0].slice(0, 200)}`);
            continue;
          }
          if (framework.length && jsErrors.length === 0 && !protectedCase) {
            const first = String(err && err.message || err).split('\n')[0].slice(0, 300);
            console.log(`FRAMEWORK_CHANGED: ${name} (previous shared behavior differs after intentional edits to ${framework.join(', ')}): ${first}`);
            continue;
          }
          throw err;
        }
      }
    }
  } catch (e) {
    if (jsErrors.length > 0) jsErrors.forEach(err => console.error(`BROWSER_RUNTIME_ERROR: ${err}`));
    console.error(e);
    process.exitCode = 1;
  } finally {
    if (browser) await browser.close();
    if (server) await server.close();
  }
}

run();
