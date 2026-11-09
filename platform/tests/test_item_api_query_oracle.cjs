const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { verify, CASES, missingBackendImplementation, trustedRequest, protectedResponse, within }
  = require('./browser_item_api_query.cjs');

const FIXTURE = [
  { id: 11, itemCode: 'A-100', itemName: '육각 볼트', specification: 'M8x30', unit: 'EA', remark: '도금 볼트' },
  { id: 29, itemCode: 'B-200', itemName: '육각 너트', specification: 'M10', unit: 'BOX', remark: '스테인리스 너트' },
];
const clone = value => JSON.parse(JSON.stringify(value));
const response = (status, data, headers = {}) => ({ status: () => status, ok: () => status >= 200 && status < 300,
  json: async () => clone(data), text: async () => JSON.stringify(data), headers: () => headers });

async function scenario(options = {}) {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'item-api-oracle-'));
  const migration = path.join(directory, 'project/backend/src/main/resources/db/migration');
  fs.mkdirSync(migration, { recursive: true });
  if (!options.missing) fs.writeFileSync(path.join(migration, 'V5_1__catalog.sql'), '-- fixture migration');
  const credentials = path.join(directory, 'account.json');
  fs.writeFileSync(credentials, JSON.stringify({ username: 'unit-user', password: 'unit-password' }));
  const previous = process.env.HARNESS_LOGIN_CREDENTIALS;
  process.env.HARNESS_LOGIN_CREDENTIALS = credentials;
  const previousLog = console.log;
  console.log = () => {};
  const state = { instances: [], contexts: [], rows: [], gets: [], posts: [], closed: false };
  class Runtime {
    constructor(output) { this.output = output; state.instances.push(this); }
    async start() { return { base_url: 'http://127.0.0.1:45432', db_name: 'mdi_item_unit', container_id: 'unit' }; }
    async rows(sql) {
      let rows = state.rows;
      const clauses = [...sql.matchAll(/POSITION\('((?:[^']|'')*)' IN (item_code|item_name)\) > 0/g)];
      for (const [, value, column] of clauses) rows = rows.filter(row =>
        row[column === 'item_code' ? 'itemCode' : 'itemName'].includes(value.replaceAll("''", "'")));
      return clone(rows);
    }
    async seedQueryFixture() { assert.equal(state.rows.length, 0); state.rows = clone(FIXTURE); return clone(state.rows); }
    async close() { state.closed = true; return { success: !options.cleanupFailure, container_removed: true,
      database_removed: !options.cleanupFailure, role_removed: true, target_volume_removed: true }; }
  }
  async function createContext() {
    const context = { authenticated: false, disposed: false,
      async get(address, requestOptions) {
        state.gets.push({ address, options: requestOptions });
        assert.equal(requestOptions.maxRedirects, 0); assert.equal(requestOptions.timeout, 10000);
        const url = new URL(address);
        if (url.pathname === '/api/auth/session') return response(200,
          { authenticated: this.authenticated, csrf: { token: 'unit-csrf', headerName: 'X-CSRF-TOKEN' } });
        assert.equal(url.pathname, '/api/items');
        if (!this.authenticated && !options.openEndpoint) return response(401, { error: 'authentication required' });
        if (options.emptyFailure && state.rows.length === 0) return response(500, { error: 'database query failed' });
        const code = url.searchParams.get('itemCode') || '', name = url.searchParams.get('itemName') || '';
        const rows = state.rows.filter(row => options.orInsteadOfAnd && code && name
          ? row.itemCode.includes(code) || row.itemName.includes(name)
          : (!code || row.itemCode.includes(code)) && (!name || row.itemName.includes(name)));
        if (options.mutate && state.rows.length) state.rows[0].remark = 'changed during GET';
        return response(200, rows);
      },
      async post(address, requestOptions) {
        assert.equal(new URL(address).pathname, '/api/auth/login');
        assert.equal(requestOptions.maxRedirects, 0); assert.equal(requestOptions.timeout, 10000);
        assert.deepEqual(requestOptions.form, { username: 'unit-user', password: 'unit-password' });
        assert.equal(requestOptions.headers['X-CSRF-TOKEN'], 'unit-csrf');
        state.posts.push(address); this.authenticated = true; return response(200, { authenticated: true });
      },
      async dispose() { this.disposed = true; if (options.contextCleanupFailure) throw new Error('unit dispose failure'); },
    };
    state.contexts.push(context); return context;
  }
  try {
    const result = await verify(path.join(directory, 'evidence'),
      { projectRoot: path.join(directory, 'project'), Runtime, createContext });
    assert.deepEqual(JSON.parse(fs.readFileSync(path.join(directory, 'evidence/result.json'), 'utf8')), clone(result));
    return { result, state };
  } finally {
    console.log = previousLog;
    if (previous === undefined) delete process.env.HARNESS_LOGIN_CREDENTIALS;
    else process.env.HARNESS_LOGIN_CREDENTIALS = previous;
    fs.rmSync(directory, { recursive: true, force: true });
  }
}

test('API-only positive run uses real auth protocol, all SQL comparisons and both context cleanup', async () => {
  const { result, state } = await scenario();
  assert.equal(result.passed, true);
  assert.deepEqual(result.cases, CASES);
  assert.equal(result.verificationMode, 'api-and-sql-only');
  assert.equal(result.browserStarted, false);
  assert.equal(state.posts.length, 1);
  assert.equal(state.contexts.length, 2);
  assert.ok(state.contexts.every(context => context.disposed));
  assert.equal(state.closed, true);
  assert.deepEqual(state.rows, FIXTURE);
  assert.ok(result.sqlProofs.some(proof => proof.label === 'empty-table-query' && proof.rows.length === 0));
  assert.ok(result.sqlProofs.some(proof => proof.conditions?.itemCode === '-10'
    && proof.conditions?.itemName === '너' && proof.rows.length === 0));
});

test('backend preflight has no frontend prerequisite and stops before runtime if migration is absent', async () => {
  const { result, state } = await scenario({ missing: true });
  assert.equal(result.passed, false);
  assert.equal(state.instances.length, 0);
  assert.equal(result.databaseStarted, false);
  assert.deepEqual(result.cases, []);
  assert.match(result.failure, /migration after V5/);
});

test('empty-table SQL error is a failed query and still closes owned resources', async () => {
  const { result, state } = await scenario({ emptyFailure: true });
  assert.equal(result.passed, false); assert.match(result.failure, /500 !== 200/);
  assert.equal(state.closed, true); assert.ok(state.contexts.every(context => context.disposed));
});

test('an OR implementation cannot pass the required partial AND comparisons', async () => {
  const { result } = await scenario({ orInsteadOfAnd: true });
  assert.equal(result.passed, false); assert.match(result.failure, /API result differs from owned SQL/);
  assert.ok(!result.cases.includes('partial-and-query-api-matches-sql'));
});

test('GET mutation cannot pass the independent final database snapshot', async () => {
  const { result, state } = await scenario({ mutate: true });
  assert.equal(result.passed, false); assert.match(result.failure, /Querying must leave all item rows unchanged/);
  assert.equal(state.closed, true);
});

test('an unprotected item endpoint cannot pass by returning an empty array before seeding', async () => {
  const { result, state } = await scenario({ openEndpoint: true });
  assert.equal(result.passed, false); assert.match(result.failure, /login\/session boundary/);
  assert.equal(state.posts.length, 0); assert.equal(state.closed, true);
});

test('failed runtime or API-context cleanup keeps the stage failed', async () => {
  for (const options of [{ cleanupFailure: true }, { contextCleanupFailure: true }]) {
    const { result, state } = await scenario(options);
    assert.equal(result.passed, false); assert.equal(result.cleanup.success, false);
    assert.ok(!result.cases.includes('read-only-query-and-cleanup'));
    assert.equal(state.closed, true);
  }
});

test('request gate rejects external, business writes, unexpected paths and userinfo before transport', async () => {
  let calls = 0;
  const request = trustedRequest({ get: async () => { calls++; }, post: async () => { calls++; } },
    'http://127.0.0.1:45432', []);
  for (const [method, url] of [['get', 'http://example.com/api/items'], ['post', 'http://127.0.0.1:45432/api/items'],
    ['get', 'http://127.0.0.1:45432/api/other'], ['get', 'http://user:password@127.0.0.1:45432/api/items']])
    await assert.rejects(request[method](url));
  assert.equal(calls, 0);
});

test('existing authentication denial supports same-origin login redirects without following them', () => {
  assert.equal(protectedResponse(response(401, {}), 'http://127.0.0.1:45432'), true);
  assert.equal(protectedResponse(response(403, {}), 'http://127.0.0.1:45432'), true);
  assert.equal(protectedResponse(response(302, {}, { location: '/login' }), 'http://127.0.0.1:45432'), true);
  assert.equal(protectedResponse(response(302, {}, { location: 'https://example.com/login' }), 'http://127.0.0.1:45432'), false);
  assert.equal(protectedResponse(response(500, {}), 'http://127.0.0.1:45432'), false);
});

test('timeout helper rejects instead of leaving a pending operation unbounded', async () => {
  await assert.rejects(within(new Promise(() => {}), 5, 'bounded operation timeout'), /bounded operation timeout/);
});
