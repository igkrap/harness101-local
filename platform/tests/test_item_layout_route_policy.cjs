const test = require('node:test');
const assert = require('node:assert/strict');
const { classifyRequest } = require('./browser_gemma_item_layout.cjs');
const base = 'http://127.0.0.1:52999';
const policy = (url, resourceType, method = 'GET') => classifyRequest({ url, resourceType, method }, base);

test('existing theme font requests stay blocked in a separate evidence category', () => {
  assert.equal(policy('https://fonts.googleapis.com/css2?family=Figtree:wght@400;500;600;700&display=swap', 'stylesheet'), 'blocked-static');
  assert.equal(policy('https://fonts.gstatic.com/s/figtree/v5/example.woff2', 'font'), 'blocked-static');
});

test('font origins do not exempt fetch, XHR, scripts, writes, or mismatched resource types', () => {
  for (const origin of ['https://fonts.googleapis.com', 'https://fonts.gstatic.com']) {
    for (const type of ['fetch', 'xhr', 'script', 'image', 'document']) {
      assert.equal(policy(origin + '/css2', type), 'business', origin + ' ' + type);
    }
  }
  assert.equal(policy('https://fonts.googleapis.com/css2', 'stylesheet', 'POST'), 'business');
  assert.equal(policy('https://fonts.gstatic.com/font.woff2', 'font', 'PUT'), 'business');
  assert.equal(policy('https://fonts.googleapis.com/font.woff2', 'font'), 'business');
  assert.equal(policy('https://fonts.gstatic.com/css2', 'stylesheet'), 'business');
});

test('other external assets and lookalike origins still fail', () => {
  for (const url of ['https://cdn.example.com/font.woff2', 'https://fonts.gstatic.com.example.com/font.woff2', 'http://fonts.gstatic.com/font.woff2']) {
    assert.equal(policy(url, 'font'), 'business', url);
  }
  assert.equal(policy('https://cdn.example.com/site.css', 'stylesheet'), 'business');
});

test('local business queries and writes remain forbidden while framework traffic is allowed', () => {
  for (const method of ['GET', 'POST', 'PUT', 'DELETE']) {
    assert.equal(policy(base + '/api/items', 'fetch', method), 'business', method);
  }
  assert.equal(policy(base + '/api/screens', 'fetch', 'POST'), 'business');
  assert.equal(policy(base + '/api/screens', 'fetch'), 'allow');
  assert.equal(policy(base + '/api/auth/session', 'fetch'), 'allow');
  assert.equal(policy(base + '/src/main.tsx', 'script'), 'allow');
});
