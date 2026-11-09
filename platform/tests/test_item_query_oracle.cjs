const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { classifyRequest, canonicalRows, displayRows, querySql, missingImplementation } = require('./browser_item_query.cjs');
const base = 'http://127.0.0.1:52999';
const policy = (address, method = 'GET', resourceType = 'fetch') => classifyRequest({ url: address, method, resourceType }, base);

test('only local item GET plus existing framework endpoints are allowed', () => {
  assert.equal(policy(base + '/api/items?itemCode=A&itemName=볼트'), 'allow');
  assert.equal(policy(base + '/api/auth/session'), 'allow');
  assert.equal(policy(base + '/api/screens'), 'allow');
  assert.equal(policy(base + '/src/main.tsx', 'GET', 'script'), 'allow');
  for (const method of ['POST', 'PUT', 'PATCH', 'DELETE']) {
    assert.equal(policy(base + '/api/items', method), 'forbidden', method);
  }
  assert.equal(policy(base + '/api/items/1'), 'forbidden');
  assert.equal(policy(base + '/api/inventory'), 'forbidden');
  assert.equal(policy(base + '/api/screens', 'POST'), 'forbidden');
  assert.equal(policy('http://127.0.0.1:8083/api/items'), 'forbidden');
});

test('known theme fonts remain blocked separately; other external traffic fails', () => {
  assert.equal(policy('https://fonts.googleapis.com/css2?family=Figtree', 'GET', 'stylesheet'), 'blocked-static');
  assert.equal(policy('https://fonts.gstatic.com/font.woff2', 'GET', 'font'), 'blocked-static');
  for (const origin of ['https://fonts.googleapis.com', 'https://fonts.gstatic.com']) {
    for (const type of ['fetch', 'xhr', 'script']) assert.equal(policy(origin + '/css2', 'GET', type), 'forbidden');
  }
  assert.equal(policy('https://fonts.googleapis.com/css2', 'POST', 'stylesheet'), 'forbidden');
  assert.equal(policy('https://cdn.example.com/site.css', 'GET', 'stylesheet'), 'forbidden');
  assert.equal(policy('https://fonts.gstatic.com.example.com/font.woff2', 'GET', 'font'), 'forbidden');
});

test('row comparison ignores order but detects every business field and requires numeric API ids', () => {
  const a = { id: 1, itemCode: 'A', itemName: '품목 A', specification: '규격 A', unit: 'EA', remark: '비고 A' };
  const b = { id: 2, itemCode: 'B', itemName: '품목 B', specification: '규격 B', unit: 'BOX', remark: '비고 B' };
  assert.deepEqual(canonicalRows([b, a]), canonicalRows([a, b]));
  assert.deepEqual(displayRows([b, a]), displayRows([a, b]));
  for (const field of ['itemCode', 'itemName', 'specification', 'unit', 'remark']) {
    assert.notDeepEqual(displayRows([a]), displayRows([{ ...a, [field]: 'incorrect' }]), field);
  }
  assert.throws(() => canonicalRows([{ ...a, id: '1' }]), /numeric id/);
  assert.throws(() => canonicalRows({ rows: [a] }), /JSON array/);
});

test('SQL comparison uses optional literal substring conditions joined with AND', () => {
  assert.equal(querySql(), querySql({ itemCode: '', itemName: '' }));
  assert.match(querySql({ itemCode: '-10', itemName: '너' }), /POSITION\('-10' IN item_code\) > 0 AND POSITION\('너' IN item_name\) > 0/);
  assert.match(querySql({ itemName: "O'Ring_%" }), /POSITION\('O''Ring_%' IN item_name\) > 0/);
  assert.doesNotMatch(querySql({ itemCode: '-10' }), /item_name\) > 0/);
});

test('preflight accepts new migration names without imposing a Java package or exact filename', t => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'item-query-preflight-'));
  t.after(() => fs.rmSync(directory, { recursive: true, force: true }));
  const screen = path.join(directory, 'frontend/src/screens/ItemMaster.tsx');
  const migrations = path.join(directory, 'backend/src/main/resources/db/migration');
  assert.equal(missingImplementation(directory).length, 2);
  fs.mkdirSync(path.dirname(screen), { recursive: true });
  fs.writeFileSync(screen, '');
  fs.mkdirSync(migrations, { recursive: true });
  fs.writeFileSync(path.join(migrations, 'V5__existing.sql'), '');
  assert.equal(missingImplementation(directory).length, 1);
  fs.writeFileSync(path.join(migrations, 'V6__items_query.sql'), '');
  assert.deepEqual(missingImplementation(directory), []);
});
