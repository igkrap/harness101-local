module.exports = async function check(ctx) {
  const { page, assert } = ctx;
  const sidebar = page.getByRole('navigation', { name: 'Side navigation', exact: true });
  const tabs = page.getByRole('navigation', { name: 'Tabs', exact: true });

  const invBtn = sidebar.getByRole('button', { name: /^재고$/ }).first();
  await invBtn.click();
  await invBtn.click();

  const invTabs = tabs.getByRole('button', { name: /^(재고|재고재고)$/ });
  // Filter manual check for "닫기/close" since Playwright name regex can't negative lookahead easily in all versions
  const count = await invTabs.count();
  let validTabs = 0;
  for (let i = 0; i < count; i++) {
    const name = await invTabs.nth(i).innerText();
    if (!/닫기|close/i.test(name)) validTabs++;
  }
  await assert.strictEqual(validTabs, 1, 'Exactly one inventory tab expected');

  const { inventoryLocators } = require(require('node:path').resolve(ctx.root, '../platform/tests/inventory_locators.cjs'));
  const form = inventoryLocators(page).form;
  await assert.strictEqual(await form.count(), 1, 'Exactly one record editor form expected');
  const input = form.getByRole('textbox', { name: /^이름/ });
  await assert.strictEqual(await input.count(), 1, 'Exactly one name textbox expected in form');
  const draft = `draft_${Date.now()}`;
  await input.fill(draft);

  await tabs.getByRole('button', { name: /^홈$/ }).click();
  await invBtn.click();

  await assert.strictEqual(await input.inputValue(), draft, 'Draft value did not persist');
  console.log('DRAFT_PERSISTENCE_OK');

  const closeBtn = tabs.getByRole('button', { name: /재고.*(닫기|close)/i }).first();
  if (await closeBtn.count() === 0) throw new Error('CLOSE_TAB_MISSING');

  await closeBtn.click();

  const remainingTabsCount = await invTabs.count();
  let remainingValid = 0;
  for (let i = 0; i < remainingTabsCount; i++) {
    const name = await invTabs.nth(i).innerText();
    if (!/닫기|close/i.test(name)) remainingValid++;
  }
  await assert.strictEqual(remainingValid, 0, 'Inventory tab should be closed');
  
  const homeView = page.locator('h1, h2, h3').filter({ hasText: /^홈$/ }).first();
  await assert.ok(await homeView.isVisible(), 'Home view should be visible');
};
