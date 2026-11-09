module.exports = async ({ page, root }) => {
  const probe = await page.context().newPage();
  let count = 0;
  try {
    await probe.goto(page.url(), { waitUntil: 'networkidle' });
    const expandBtn = probe.getByRole('button', { name: /Expand sidebar|펼치기/i });
    if (await expandBtn.isVisible()) {
      await expandBtn.click();
    }
    await probe.click('nav >> text="재고"');
    const { inventoryLocators } = require(require('node:path').resolve(root, '../platform/tests/inventory_locators.cjs'));
    const controls = inventoryLocators(probe);
    count = (await controls.query.count()) || (await probe.locator('form:visible').count() > 1 ? 1 : 0);
  } finally {
    await probe.close();
  }

  if (count === 0) {
    console.log('INVENTORY_WORKFLOW_NOT_APPLICABLE:no-editor');
    return;
  }

  const { execFile } = await import('node:child_process');
  const { promisify } = await import('node:util');
  const { resolve } = await import('node:path');

  const testPath = resolve(root, '../platform/tests/browser_inventory_workflows.cjs');
  const { stdout } = await promisify(execFile)(process.execPath, [testPath], {
    env: { ...process.env, PREVIEW_URL: page.url() },
    timeout: 60000
  });

  console.log(stdout);
};
