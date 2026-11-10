// RecordGrid selection modes, multi-row editing and selection -> delete wiring, in a real browser.
const fs = require('node:fs'), path = require('node:path'), assert = require('node:assert/strict');
const { openFixture } = require('./vite_fixture.cjs');

const source = `
import React, { useState } from 'react'; import { createRoot } from 'react-dom/client';
import {AppTheme} from './src/framework';
import { RecordGrid, useEditableRows } from './src/framework';
const data = [{ id: 'A', name: 'Alpha', qty: '1' }, { id: 'B', name: 'Beta', qty: '2' }, { id: 'C', name: 'Gamma', qty: '3' }, { id: 'D', name: 'Delta', qty: '4' }];
const columns = [{ key: 'name', label: '이름' }, { key: 'qty', label: '수량' }];
window.events = {};
function Mode({ mode }) {
  const [rows, setRows] = useState(data);
  const [picked, setPicked] = useState([]);
  return <section data-mode={mode} style={{ marginBottom: 24 }}>
    <button type="button" disabled={!picked.length} onClick={() => { const keys = picked.map(r => r.id); setRows(rows.filter(r => !keys.includes(r.id))); window.events[mode + ':deleted'] = keys; }}>삭제 {mode}</button>
    <RecordGrid label={mode} rows={rows} columns={columns} keyField="id" selection={mode}
      onSelectionChange={next => { setPicked(next); window.events[mode] = next.map(r => r.id); }}
      onSelect={row => { window.events[mode + ':current'] = row.id; }} />
  </section>;
}
function Editable() {
  const grid = useEditableRows('id');
  const [picked, setPicked] = useState([]);
  React.useEffect(() => { grid.load(data); }, []);
  window.events.changed = grid.changed.map(r => r.id + '=' + r.name + '/' + r.qty);
  return <section data-mode="editable">
    <button type="button" onClick={() => { const keys = picked.map(r => r.id); grid.onRowsChange(grid.rows.filter(r => !keys.includes(r.id))); window.events['editable:deleted'] = keys; }}>삭제 editable</button>
    <RecordGrid label="editable" editable rows={grid.rows} columns={[{ key: 'name', label: '이름', editable: true }, { key: 'qty', label: '수량', editable: true }]} keyField="id"
      onRowsChange={grid.onRowsChange} onSelectionChange={next => { setPicked(next); window.events.editableSel = next.map(r => r.id); }} />
  </section>;
}
createRoot(document.getElementById('root')).render(<AppTheme>
  {['single', 'multiple', 'checkbox-single', 'checkbox-multiple'].map(mode => <Mode key={mode} mode={mode} />)}<Editable />
</AppTheme>);
`;

async function verify(browser, project) {
  const fixture = await openFixture(browser, source, { project, viewport: { width: 1200, height: 2400 } });
  const { page, errors } = fixture;
  const ev = key => page.evaluate(k => window.events[k], key);
  const grid = mode => page.locator(`section[data-mode="${mode}"]`);
  const row = (mode, name) => grid(mode).locator('tbody tr').filter({ hasText: name });
  try {
    await grid('single').locator('tbody tr').first().waitFor();
    for (const mode of ['single', 'multiple', 'checkbox-single', 'checkbox-multiple'])
      assert.equal(await grid(mode).getByRole('button', { name: '선택', exact: true }).count(), 0, `${mode}: no per-row select buttons`);

    // single: row click selects one row; arrows move the selection
    await row('single', 'Beta').click();
    assert.deepEqual(await ev('single'), ['B']); assert.equal(await ev('single:current'), 'B');
    await page.keyboard.press('ArrowDown'); assert.deepEqual(await ev('single'), ['C']);
    await row('single', 'Alpha').click(); assert.deepEqual(await ev('single'), ['A']);
    assert.equal(await row('single', 'Alpha').getAttribute('aria-selected'), 'true');

    // multiple: click, ctrl/meta toggle, shift range, ctrl+A
    await row('multiple', 'Alpha').click();
    await row('multiple', 'Gamma').click({ modifiers: ['ControlOrMeta'] }); assert.deepEqual(await ev('multiple'), ['A', 'C']);
    await row('multiple', 'Alpha').click({ modifiers: ['ControlOrMeta'] }); assert.deepEqual(await ev('multiple'), ['C']);
    await row('multiple', 'Beta').click(); await row('multiple', 'Delta').click({ modifiers: ['Shift'] }); assert.deepEqual(await ev('multiple'), ['B', 'C', 'D']);
    await page.keyboard.press('ControlOrMeta+a'); assert.deepEqual(await ev('multiple'), ['A', 'B', 'C', 'D']);
    assert.equal(await grid('multiple').locator('table').getAttribute('aria-multiselectable'), 'true');

    // checkbox-single: checkbox column without select-all; row click selects only one
    assert.equal(await grid('checkbox-single').getByRole('checkbox', { name: '전체 선택' }).count(), 0);
    await row('checkbox-single', 'Beta').click(); await row('checkbox-single', 'Delta').click();
    assert.deepEqual(await ev('checkbox-single'), ['D']);
    assert.equal(await row('checkbox-single', 'Delta').getByRole('checkbox').isChecked(), true);
    assert.equal(await row('checkbox-single', 'Beta').getByRole('checkbox').isChecked(), false);

    // checkbox-multiple: row click toggles, checkbox toggles, select-all; then delete the selection
    await row('checkbox-multiple', 'Alpha').click(); await row('checkbox-multiple', 'Gamma').getByRole('checkbox').check();
    assert.deepEqual(await ev('checkbox-multiple'), ['A', 'C']);
    await row('checkbox-multiple', 'Alpha').click(); assert.deepEqual(await ev('checkbox-multiple'), ['C']);
    await grid('checkbox-multiple').getByRole('checkbox', { name: '전체 선택' }).check(); assert.deepEqual(await ev('checkbox-multiple'), ['A', 'B', 'C', 'D']);
    await grid('checkbox-multiple').getByRole('checkbox', { name: '전체 선택' }).uncheck();
    await row('checkbox-multiple', 'Beta').click(); await row('checkbox-multiple', 'Delta').click();
    await grid('checkbox-multiple').getByRole('button', { name: '삭제 checkbox-multiple' }).click();
    assert.deepEqual(await ev('checkbox-multiple:deleted'), ['B', 'D']);
    assert.equal(await grid('checkbox-multiple').locator('tbody tr').count(), 2);
    assert.deepEqual(await ev('checkbox-multiple'), [], 'deleted rows leave the selection');

    // editable: cell focus moves with arrows, typing edits, Enter commits; checkbox selects rows
    const cell = (r, c) => grid('editable').locator(`[data-cell="${r}:${c}"]`);
    const focused = (r, c) => page.waitForFunction(sel => document.activeElement === document.querySelector(sel), `section[data-mode="editable"] [data-cell="${r}:${c}"]`, { timeout: 2000 }).then(() => true, () => false);
    await cell(0, 1).click();
    await page.keyboard.press('ArrowRight'); assert.equal(await focused(0, 2), true);
    await page.keyboard.press('ArrowDown'); assert.equal(await focused(1, 2), true);
    await page.keyboard.type('9'); await page.keyboard.press('Enter');
    assert.equal(await focused(2, 2), true, 'Enter commits and moves down');
    await page.keyboard.press('ArrowLeft'); await page.keyboard.press('F2'); await page.keyboard.press('ControlOrMeta+a'); await page.keyboard.type('감마'); await page.keyboard.press('Tab');
    await page.keyboard.press('ArrowUp'); await page.keyboard.press('Enter'); await page.keyboard.press('Escape');
    assert.deepEqual(await ev('changed'), ['B=Beta/9', 'C=감마/3']);
    await grid('editable').locator('tbody tr').filter({ hasText: 'Alpha' }).getByRole('checkbox').check();
    await cell(3, 1).click(); await page.keyboard.press('ArrowLeft'); assert.equal(await focused(3, 0), true); await page.keyboard.press(' ');
    assert.deepEqual(await ev('editableSel'), ['A', 'D']);
    await grid('editable').getByRole('button', { name: '삭제 editable' }).click();
    assert.deepEqual(await ev('editable:deleted'), ['A', 'D']);
    assert.deepEqual(errors, []);
    return { passed: true, cases: ['no-row-buttons', 'single-click-arrows', 'multiple-ctrl-shift-all', 'checkbox-single', 'checkbox-multiple-select-all', 'selection-delete', 'editable-cell-focus', 'editable-commit-tracking', 'editable-checkbox-delete'] };
  } finally { await fixture.close(); }
}
module.exports = { verify };
if (require.main === module) {
  const config = JSON.parse(fs.readFileSync(path.join(process.env.HOME, '.local/share/mlx-server/browser-check/runtime.json')));
  const { chromium } = require(config.playwrightModule);
  (async () => { const browser = await chromium.launch({ headless: true }); try { console.log(JSON.stringify(await verify(browser))); } finally { await browser.close(); } })().catch(error => { console.error(error); process.exit(1); });
}
