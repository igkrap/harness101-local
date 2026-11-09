const fs = require('fs/promises');
const path = require('path');

module.exports = async function check(ctx) {
  const { assert, page } = ctx;
  const wsPath = path.resolve(ctx.root || process.cwd(), 'frontend/src/workspace.json');
  let original;
  try {
    original = await fs.readFile(wsPath);
  } catch (e) {
    throw new Error('WORKSPACE_CONTRACT_MISSING');
  }

  try {
    const sidebarNav = page.getByRole('navigation', { name: 'Side navigation', exact: true });
    const tabsNav = page.getByRole('navigation', { name: 'Tabs', exact: true });
    const inventoryHeading = page.getByRole('heading', { name: '재고 관리' });
    const inventoryForm = page.locator('form:visible').filter({has: page.getByLabel(/^최소\s*수량/)});
    const inventoryInput = inventoryForm.getByRole('textbox', { name: /^이름/ });

    // 1. Normalize expanded sidebar first
    const expandBtn = sidebarNav.getByRole('button', { name: 'Expand sidebar' });
    if (await expandBtn.isVisible()) {
      await expandBtn.click();
    }

    // 2. Click Side navigation menu button (재고) and ensure heading is visible
    await sidebarNav.getByRole('button', { name: '재고' }).click();
    await inventoryHeading.waitFor({ state: 'visible' });

    // 3. Measure expanded x
    const expandedBox = await inventoryHeading.boundingBox();
    const expandedX = expandedBox.x;

    // 4. Switch Home using label-only tabs (excluding close buttons)
    // Anchored names: 홈/홈홈, 재고/재고재고 (assuming close buttons contain extra text or different roles)
    // Requirement: exactly one Home LABEL and exactly one Inventory LABEL
    await tabsNav.getByRole('button', { name: /^(홈|홈홈)$/ }).click();

    // 5. Apply config
    await fs.writeFile(wsPath, JSON.stringify({ 
      sidebarCollapsed: true, 
      tabs: ['Home', 'Inventory'], 
      activeTab: 'Inventory' 
    }));

    // 6. HMR: Wait for inventory and name textbox, then poll for x movement
    await inventoryHeading.waitFor({ state: 'visible' });
    await inventoryInput.waitFor({ state: 'visible' });

    let collapsedX = expandedX;
    for (let i = 0; i < 20; i++) {
      const box = await inventoryHeading.boundingBox();
      if (box && box.x < expandedX) {
        collapsedX = box.x;
        break;
      }
      await new Promise(r => setTimeout(r, 100));
    }

    assert.ok(collapsedX < expandedX, `Heading x should decrease from ${expandedX} to ${collapsedX}`);

    // 7. Assert exactly one Home and one Inventory tab using anchored names
    // Filter out close buttons by being specific about the label
    const homeTab = tabsNav.getByRole('button', { name: /^(홈|홈홈)$/ });
    const inventoryTab = tabsNav.getByRole('button', { name: /^(재고|재고재고)$/ });
    
    // Checking counts specifically for these names to ensure no extra close buttons match
    // Note: if close buttons also have name '홈', we'd need more precision, 
    // but instructions say "exactly one ... using anchored names ... NEVER count all buttons"
    assert.strictEqual(await homeTab.count(), 1, 'Should have exactly one Home tab');
    assert.strictEqual(await inventoryTab.count(), 1, 'Should have exactly one Inventory tab');

  } finally {
    await fs.writeFile(wsPath, original);
  }
};
