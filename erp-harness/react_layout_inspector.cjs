const fs = require('fs');
const path = require('path');
const os = require('os');
const api = require('./verification_api.cjs');
const dom = require('./verification_dom.cjs');
const uiRequirements = require('./native_ui_requirements.cjs');

async function verify(input) {
  const report = { success: false, results: [], layout: [], screenshot: null };
  let browser, context;
  let systemErrors = [];

  try {
    const { contract, preview_url, api_url, output_dir, allow_browser_writes, allow_api_writes } = input; const criteria = contract.criteria;
    fs.mkdirSync(output_dir, { recursive: true });

    const isUI = criteria.some(c => ['visible', 'absent', 'inventory', 'count', 'text', 'layout', 'scenario'].includes(c.check.op));
    if (isUI) {
      const cfgPath = process.env.HARNESS_BROWSER_RUNTIME || path.join(os.homedir(), '.local/share/mlx-server/browser-check/runtime.json');
      const cfg = JSON.parse(fs.readFileSync(cfgPath, 'utf8'));
      const playwright = require(cfg.playwrightModule);
      browser = await playwright.chromium.launch({ executablePath: cfg.executablePath, headless: true });
      context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
      await require('./trusted_auth.cjs').ensureAuthenticated(context.request, preview_url);
    }

    for (const c of criteria) {
      const res = { id: c.id, status: 'unverified', reason: 'not call api/dom', evidence: {} };
      try {
        if (c.check.op === 'api') {
          const apiRes = await api.run(c.check, api_url, allow_api_writes);
          Object.assign(res, apiRes);
        } else if (isUI) {
          const page = await context.newPage();
          const blocked = [];
          await page.route('**/*', async (route) => {
            const req = route.request();
            const newURL = new URL(req.url()); const targetURL = new URL(preview_url); const isSameOrigin = newURL.origin === targetURL.origin; const isReadonly = ['GET', 'HEAD', 'OPTIONS'].includes(req.method()); const isStatic = ['font', 'stylesheet', 'image', 'script'].includes(req.resourceType()); const isAllowed = (isSameOrigin && (isReadonly || allow_browser_writes)) || (isStatic && isReadonly);
            if (!isAllowed) {
              blocked.push({ method: req.method(), path: req.url() });
              return route.abort();
            }
            await route.continue();
          });

          try {
            const urlObj = new URL(preview_url); const isLocal = ['localhost', '127.0.0.1', '[::1]'].includes(urlObj.hostname); if (!['http:', 'https:'].includes(urlObj.protocol) || !isLocal) throw new Error('invalid preview_url'); await page.goto(preview_url, { waitUntil: 'domcontentloaded', timeout: 10000 }); await page.waitForLoadState('networkidle', { timeout: 10000 });
            if (input.open_screen) {
              // Open the task's target screen from the app menu so checks run where the change is.
              const entry = page.locator('nav').getByText(input.open_screen, { exact: true }).first();
              await entry.click({ timeout: 5000 }).catch(() => { throw new Error(`target screen '${input.open_screen}' could not be opened from the menu`); });
              await page.waitForLoadState('networkidle', { timeout: 10000 }).catch(() => {});
            }
            const domRes = await dom.run(page, c.check);
            Object.assign(res, domRes);
            if (res.status === 'passed') {
              try {
                const requirement = (contract.requirements || []).find(r => r.id === c.requirement_id);
                // The target screen's own name (e.g. '품목 등록') is not a capability request; drop it before
                // keyword classification so every request about that screen is not read as 'build an editor form'.
                const description = String(requirement?.description || '');
                const cleaned = input.open_screen ? description.split(input.open_screen).join(' ') : description;
                const facts = await uiRequirements.verify(page, c, cleaned, blocked);
                res.evidence.capabilities = Object.assign(res.evidence.capabilities || {}, facts);
              } catch (error) {
                res.status = 'failed';
                res.reason = 'Native UI requirement: ' + error.message;
              }
            }
            
            const inspectData = await dom.inspect(page);
            report.layout.push(inspectData);
            const ssPath = path.join(output_dir, `layout.png`);
            await page.screenshot({ path: ssPath });
            if (!report.screenshot) report.screenshot = ssPath;

            await page.waitForLoadState('networkidle', { timeout: 1000 }).catch(() => {});
            if (blocked.length > 0) {
              res.status = 'unverified';
              res.reason = 'blocked_requests';
              res.evidence.blocked = blocked;
            }
          } catch (e) {
            res.status = 'failed';
            res.reason = e.message;
          } finally {
            await page.close();
          }
        }
      } catch (err) {
        res.status = 'unverified';
        res.reason = `browser_error: ${err.message}`;
      }
      report.results.push(res);
    }
  } catch (err) {
    systemErrors.push({ id: `system:${Date.now()}`, status: 'failed', reason: err.message });
  } finally {
    if (browser) await browser.close();
    report.results.push(...systemErrors);
    report.success = report.results.length > 0 && report.results.every(r => r.status === 'passed');
  }
  return report;
}

if (require.main === module) {
  let inputData = '';
  process.stdin.on('data', chunk => { inputData += chunk; });
  process.stdin.on('end', async () => {
    const exit = (code) => {
      process.stdout.write('', () => process.exit(code));
    };
    try {
      const input = JSON.parse(inputData);
      const report = await verify(input);
      process.stdout.write(JSON.stringify(report, null, 2), () => {
        exit(report.success ? 0 : 1);
      });
    } catch (e) {
      process.stdout.write(JSON.stringify({ success: false, error: e.message }), () => {
        exit(1);
      });
    }
  });
}
module.exports = { verify, inspect: dom.inspect };
