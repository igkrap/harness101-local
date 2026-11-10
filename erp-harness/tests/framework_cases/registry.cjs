const fs = require('fs/promises');
const path = require('path');

module.exports = async function check(ctx) {
  const { assert, page, frontend } = ctx;
  const probePath = path.resolve(frontend, 'src/screens/RegistryProbe.tsx');
  const probeDir = path.dirname(probePath);
  let createdDir = false, createdFile = false, originalContent = null;

  try {
    // Try to read existing content to restore later
    try {
      originalContent = await fs.readFile(probePath, 'utf8');
    } catch (e) {
      // File doesn't exist, that's fine
    }

    // Ensure directory exists and create file
    try {
      await fs.access(probeDir);
    } catch (e) {
      await fs.mkdir(probeDir, { recursive: true });
      createdDir = true;
    }

    const content = `export const meta = { code: 'ZZZ9999', title: '검증화면' };
import { Text } from '../framework';
export default function RegistryProbe() { return <Text>local-registry-check</Text>; }`;
    
    await fs.writeFile(probePath, content);
    createdFile = true;

    // Sidebar Navigation
    const sidebar = page.getByRole('navigation', { name: '메뉴', exact: true });
    const menuBtn = sidebar.getByRole('button', { name: '검증화면' });
    
    try {
      await menuBtn.waitFor({ state: 'visible' });
    } catch (e) {
      throw new Error('REGISTRY_MENU_MISSING');
    }
    await menuBtn.click();

    // Tabs Navigation
    const tabsNav = page.locator('[data-ui="workspace-tabs"]');
    
    // Assert exactly ONE LABEL tab named '검증화면' (allowing for repeated name if UI allows, but targeting the label)
    // and ensure it is visible.
    const labelTab = tabsNav.getByRole('tab', { name: /^검증화면/ });
    await assert.strictEqual(await labelTab.count(), 1, 'Should have exactly one label tab named 검증화면');
    await assert.strictEqual(await labelTab.isVisible(), true, 'Tab should be visible');

    // Content assertion
    await page.getByText('local-registry-check', { exact: true }).waitFor({ state: 'visible' });
    await assert.strictEqual(await page.getByText('local-registry-check', { exact: true }).isVisible(), true, 'Content mismatch');

    // Close the tab: Find button in tabs nav that contains '검증화면' AND '닫기' or 'close'
    // Since Locator.filter doesn't have name, we use the role and then filter by text or use regex in name if supported, 
    // but the prompt asks for specific button accessible name containing both.
    // We'll use a regex for the name to catch both.
    const closeBtn = tabsNav.getByRole('button', { name: /검증화면.*(닫기|close)/i });
    await closeBtn.click();

    // Assert tab disappeared
    await labelTab.waitFor({ state: 'hidden' });
    await assert.strictEqual(await labelTab.isVisible(), false, 'Tab should have disappeared after close');

  } finally {
    // Restore exact bytes
    if (originalContent !== null) {
      await fs.writeFile(probePath, originalContent);
    } else if (createdFile) {
      await fs.unlink(probePath).catch(() => {});
    }

    if (createdDir) {
      // Only remove if empty to avoid deleting existing structure
      try {
        const files = await fs.readdir(probeDir);
        if (files.length === 0) await fs.rmdir(probeDir).catch(() => {});
      } catch (e) {
        // Directory might have been filled or already gone
      }
    }
  }
};
