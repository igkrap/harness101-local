/**
 * Verifies sidebar collapse/expand functionality.
 * Checks if the 'Home' (홈) content heading moves horizontally when the sidebar is toggled.
 * 
 * @param {Object} ctx
 * @param {import('playwright').Page} ctx.page
 * @param {import('node:assert').strict} ctx.assert
 */
module.exports = async function check(ctx) {
  const { page, assert } = ctx;

  const expandBtn = page.getByRole('button', { name: '사이드바 펼치기', exact: true });
  const collapseBtn = page.getByRole('button', { name: '사이드바 접기', exact: true });
  
  // Navigation target to click 'Home'
  const homeBtn = page.getByRole('button', { name: /Home|홈/i }).first();
  // The content target to measure (must move when sidebar collapses)
  const homeHeading = page.getByRole('heading', { name: /Home|홈/i });

  // 1. Ensure sidebar is expanded if needed
  if (await expandBtn.isVisible()) {
    await expandBtn.click();
  }

  // 2. Navigate to Home to ensure the heading is present in the main content
  await homeBtn.waitFor({ state: 'visible' });
  await homeBtn.click();
  await homeHeading.waitFor({ state: 'visible' });

  // 3. Get initial position (Expanded) - Measuring the HEADING in content
  const expandedBox = await homeHeading.boundingBox();
  assert.ok(expandedBox, 'Could not get bounding box for Home heading');
  const expandedX = expandedBox.x;

  // 4. Collapse sidebar
  await collapseBtn.click();

  // 5. Wait for horizontal change and verify (Collapsed)
  let collapsedBox;
  for (let i = 0; i < 30; i++) {
    collapsedBox = await homeHeading.boundingBox();
    // The content heading should move LEFT (x decreases) when sidebar collapses
    if (collapsedBox && collapsedBox.x < expandedX) break;
    await page.waitForTimeout(100);
  }

  assert.ok(collapsedBox, 'Home heading could not be measured after collapse');
  assert.ok(collapsedBox.x < expandedX, `Sidebar did not collapse: content heading x moved from ${expandedX} to ${collapsedBox.x}`);

  // 6. Expand sidebar and verify return
  await expandBtn.click();

  let expandedBoxAgain;
  for (let i = 0; i < 30; i++) {
    expandedBoxAgain = await homeHeading.boundingBox();
    // the sidebar animates open: wait until the heading is back, not just moving
    if (expandedBoxAgain && Math.abs(expandedBoxAgain.x - expandedX) < 5) break;
    await page.waitForTimeout(100);
  }

  assert.ok(expandedBoxAgain, 'Home heading could not be measured after expansion');
  // Allowing a small delta for sub-pixel rendering or animation settling
  assert.ok(Math.abs(expandedBoxAgain.x - expandedX) < 5, `Sidebar did not return to original position: expected ~${expandedX}, got ${expandedBoxAgain.x}`);
};
