// Backend stage only: actual authenticated GET responses and owned SQL evidence.
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const { ItemRuntime } = require('./item_crud_runtime_client.cjs');
const { canonicalRows, querySql, missingImplementation } = require('./browser_item_query.cjs');
const { ensureAuthenticated } = require('../../local-only/harness/trusted_auth.cjs');
const PROJECT = path.resolve(__dirname, '../../local-only');
const CASES = ['fresh-items-and-generated-fixture', 'optional-query-api-matches-sql',
  'partial-and-query-api-matches-sql', 'read-only-query-and-cleanup'];

function missingBackendImplementation(root) {
  // Reuse the existing migration rule while leaving frontend prerequisites to
  // the unchanged six-case UI integration acceptance.
  return missingImplementation(root).filter(condition => !condition.startsWith('frontend/'));
}

async function within(promise, milliseconds, message) {
  let timer;
  try {
    return await Promise.race([promise, new Promise((_, reject) => {
      timer = setTimeout(() => reject(new Error(message)), milliseconds);
    })]);
  } finally { clearTimeout(timer); }
}

function trustedRequest(context, base, requests, actor = 'authenticated') {
  const origin = new URL(base);
  assert.ok(origin.protocol === 'http:' && ['127.0.0.1', 'localhost', '[::1]'].includes(origin.hostname)
    && !origin.username && !origin.password && origin.pathname === '/' && !origin.search && !origin.hash,
  'Use the owned backend loopback origin');
  async function send(method, address, options = {}) {
    const url = new URL(address, origin);
    assert.ok(url.origin === origin.origin && !url.username && !url.password && !url.hash,
      'Requests must remain on the owned backend origin');
    const allowed = method === 'GET' && ['/api/items', '/api/auth/session'].includes(url.pathname)
      || method === 'POST' && url.pathname === '/api/auth/login';
    assert.ok(allowed, 'Only item GET queries and trusted authentication requests are allowed');
    const entry = { actor, method, path: url.pathname + url.search };
    requests.push(entry);
    const response = await context[method.toLowerCase()](url.toString(),
      { ...options, timeout: 10000, maxRedirects: 0 });
    entry.status = response.status();
    return response;
  }
  return { get: (url, options) => send('GET', url, options), post: (url, options) => send('POST', url, options) };
}

async function createApiContext(base) {
  const config = JSON.parse(fs.readFileSync(path.join(process.env.HOME,
    '.local/share/mlx-server/browser-check/runtime.json'), 'utf8'));
  return require(config.playwrightModule).request.newContext({ baseURL: base, timeout: 10000 });
}

async function boundedContext(makeContext, base) {
  let accepted = true;
  const pending = Promise.resolve().then(() => makeContext(base));
  pending.then(created => {
    if (!accepted) return Promise.resolve().then(() => created.dispose()).catch(() => {});
  }, () => {});
  try { return await within(pending, 15000, 'API request context startup exceeded 15 seconds'); }
  catch (error) { accepted = false; throw error; }
}

function protectedResponse(response, base) {
  if ([401, 403].includes(response.status())) return true;
  if (![302, 303, 307, 308].includes(response.status())) return false;
  const location = response.headers().location;
  if (!location) return false;
  const url = new URL(location, base);
  return url.origin === new URL(base).origin && !url.username && !url.password
    && ['/login', '/api/auth/login'].includes(url.pathname);
}

async function verify(output, infrastructure = {}) {
  const out = path.resolve(output), root = infrastructure.projectRoot || PROJECT;
  fs.mkdirSync(out, { recursive: true });
  const cases = [], requests = [], sqlProofs = [], cleanupErrors = [];
  const Runtime = infrastructure.Runtime || ItemRuntime;
  const makeContext = infrastructure.createContext || createApiContext;
  let runtime, backend, context, anonymousContext, result, databaseStarted = false;
  let cleanup = { success: true, started: false };
  const passed = name => { assert.ok(CASES.includes(name)); cases.push(name); console.log('ITEM_API_QUERY_OK: ' + name); };
  try {
    const missing = missingBackendImplementation(root);
    assert.deepEqual(missing, [], 'Required backend query implementation is missing: ' + missing.join(', '));
    runtime = new Runtime(path.join(out, 'runtime'));
    databaseStarted = true;
    backend = await runtime.start();
    const initial = canonicalRows(await runtime.rows(querySql()));
    assert.deepEqual(initial, [], 'A fresh migrated items table must be empty; do not seed application items');
    sqlProofs.push({ label: 'fresh-empty-items', rows: initial });
    anonymousContext = await boundedContext(makeContext, backend.base_url);
    const anonymous = trustedRequest(anonymousContext, backend.base_url, requests, 'anonymous');
    const denied = await anonymous.get(new URL('/api/items', backend.base_url).toString());
    assert.ok(protectedResponse(denied, backend.base_url), 'Preserve the existing login/session boundary for item queries');
    context = await boundedContext(makeContext, backend.base_url);
    const request = trustedRequest(context, backend.base_url, requests);
    assert.equal(await ensureAuthenticated(request, backend.base_url, { localProxy: true }), true,
      'Authenticate to the owned backend using the existing session contract');

    async function expectedFor(label, conditions) {
      const rows = canonicalRows(await runtime.rows(querySql(conditions)));
      sqlProofs.push({ label, conditions, rows });
      return rows;
    }
    async function compareQuery(label, conditions) {
      const url = new URL('/api/items', backend.base_url);
      url.search = new URLSearchParams(conditions).toString();
      const response = await request.get(url.toString());
      assert.equal(response.status(), 200, 'GET item query must succeed: ' + (await response.text()).slice(0, 400));
      const observed = canonicalRows(await response.json());
      const expected = await expectedFor(label, conditions);
      assert.deepEqual(observed, expected, 'API result differs from owned SQL for ' + JSON.stringify(conditions));
    }
    // Exercise absent conditions even before rows exist; an empty table must
    // still execute a valid query and return an array.
    await compareQuery('empty-table-query', {});
    const fixture = canonicalRows(await runtime.seedQueryFixture());
    const seeded = canonicalRows(await runtime.rows(querySql()));
    assert.equal(fixture.length, 2);
    assert.deepEqual(seeded, fixture, 'Fixed fixture values and generated IDs must match SQL');
    sqlProofs.push({ label: 'owned-query-fixture', rows: seeded });
    passed('fresh-items-and-generated-fixture');

    for (const conditions of [{}, { itemCode: '', itemName: '' }]) await compareQuery('optional-query', conditions);
    passed('optional-query-api-matches-sql');
    for (const conditions of [{ itemCode: '-10' }, { itemName: '너' }, { itemName: '육각' },
      { itemCode: '-10', itemName: '볼' }, { itemCode: '-10', itemName: '너' }])
      await compareQuery('partial-and-query', conditions);
    passed('partial-and-query-api-matches-sql');
    const finalRows = canonicalRows(await runtime.rows(querySql()));
    sqlProofs.push({ label: 'after-api-queries', rows: finalRows });
    assert.deepEqual(finalRows, seeded, 'Querying must leave all item rows unchanged');
    assert.ok(requests.filter(item => item.path.startsWith('/api/items')).every(item => item.method === 'GET'));
    result = { passed: true };
  } catch (error) {
    result = { passed: false, failure: String(error) };
  } finally {
    for (const [label, ownedContext] of [['authenticated', context], ['anonymous', anonymousContext]]) {
      if (ownedContext) try {
        await within(Promise.resolve().then(() => ownedContext.dispose()), 10000,
          'API request context cleanup exceeded 10 seconds');
      } catch (error) { cleanupErrors.push(label + ' API context: ' + error); }
    }
    if (runtime) try { cleanup = await runtime.close(); }
    catch (error) { cleanupErrors.push('isolated runtime: ' + error); }
    cleanup = { ...cleanup, success: cleanup.success === true && cleanupErrors.length === 0, errors: cleanupErrors };
    result = result || { passed: false, failure: 'API query check did not produce a result' };
    if (!cleanup.success) {
      result.passed = false;
      result.failure = [result.failure, ...cleanupErrors, 'Owned runtime cleanup was not verified'].filter(Boolean).join('\n');
    }
    if (result.passed) passed('read-only-query-and-cleanup');
    Object.assign(result, { cases, requests, sqlProofs, verificationMode: 'api-and-sql-only',
      browserStarted: false, databaseStarted, database: backend?.db_name, cleanup, evidence: out });
    fs.writeFileSync(path.join(out, 'result.json'), JSON.stringify(result, null, 2));
  }
  console.log(JSON.stringify(result));
  return result;
}

module.exports = { verify, CASES, missingBackendImplementation, trustedRequest, protectedResponse, within };
if (require.main === module) {
  if (!process.argv[2]) { console.error('Usage: node browser_item_api_query.cjs OUTPUT_DIRECTORY'); process.exitCode = 2; }
  else verify(process.argv[2]).then(result => { if (!result.passed) process.exitCode = 1; })
    .catch(error => { console.error(error); process.exitCode = 1; });
}
