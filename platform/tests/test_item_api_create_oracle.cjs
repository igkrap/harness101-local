const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const createOracle = require('./browser_item_api_create.cjs');
const queryOracle = require('./browser_item_api_query.cjs');

const FIXTURE = [
  { id: 11, itemCode: 'A-100', itemName: '육각 볼트', specification: 'M8x30', unit: 'EA', remark: '도금 볼트' },
  { id: 29, itemCode: 'B-200', itemName: '육각 너트', specification: 'M10', unit: 'BOX', remark: '스테인리스 너트' },
];
const clone = value => JSON.parse(JSON.stringify(value));
const response = (status, data, headers = {}) => ({ status: () => status, ok: () => status >= 200 && status < 300,
  json: async () => clone(data), text: async () => JSON.stringify(data), headers: () => headers });

function environment(name, options = {}, onStart = () => {}) {
  const state = { instances: [], contexts: [], rows: [], nextId: 101, posts: [], uniqueQueries: [], closed: false };
  class Runtime {
    constructor(output) { this.output = output; state.instances.push(this); }
    async start() { onStart(); return { base_url: 'http://127.0.0.1:45432', db_name: 'mdi_item_unit_' + name, container_id: name }; }
    async rows(sql) {
      assert.match(sql, /^SELECT /); assert.ok(!sql.includes(';'));
      if (sql.includes('pg_index')) {
        state.uniqueQueries.push(sql);
        if (options.includedCodeOnly) {
          // PostgreSQL indkey contains both key and INCLUDE attributes. Only
          // its first attribute is unique when indnkeyatts=1.
          const index = { key: ['id'], include: ['item_code'] };
          const inspected = /a\.attnum\s*=\s*ANY\(i\.indkey\)/.test(sql)
            ? [...index.key, ...index.include]
            : /a\.attnum\s*=\s*i\.indkey\[0\]/.test(sql) ? index.key : [];
          return [{ unique_item_code: inspected.includes('item_code') }];
        }
        return [{ unique_item_code: !options.noDbUnique }];
      }
      let rows = state.rows;
      for (const [, value, column] of sql.matchAll(/POSITION\('((?:[^']|'')*)' IN (item_code|item_name)\) > 0/g))
        rows = rows.filter(row => row[column === 'item_code' ? 'itemCode' : 'itemName'].includes(value.replaceAll("''", "'")));
      return clone(rows);
    }
    async seedQueryFixture() { assert.equal(state.rows.length, 0); state.rows = clone(FIXTURE); return clone(state.rows); }
    async close() { state.closed = true; return { success: !options.cleanupFailure, database_removed: !options.cleanupFailure,
      container_removed: true, role_removed: true, target_volume_removed: true }; }
  }
  async function createContext() {
    const id = state.contexts.length + 1;
    const context = { authenticated: false, csrf: 'anonymous-' + id, disposed: false,
      async get(address, requestOptions) {
        assert.equal(requestOptions.timeout, 10000); assert.equal(requestOptions.maxRedirects, 0);
        const url = new URL(address);
        if (url.pathname === '/api/auth/session') return response(200, { authenticated: this.authenticated,
          csrf: { token: this.csrf, headerName: 'X-CSRF-TOKEN' } });
        assert.equal(url.pathname, '/api/items');
        if (!this.authenticated) return response(401, { error: 'AUTH_REQUIRED' });
        const code = url.searchParams.get('itemCode') || '', itemName = url.searchParams.get('itemName') || '';
        return response(200, state.rows.filter(row => (!code || row.itemCode.includes(code))
          && (!itemName || row.itemName.includes(itemName))));
      },
      async post(address, requestOptions) {
        assert.equal(requestOptions.timeout, 10000); assert.equal(requestOptions.maxRedirects, 0);
        const url = new URL(address);
        if (url.pathname === '/api/auth/login') {
          assert.deepEqual(requestOptions.form, { username: 'unit-user', password: 'unit-password' });
          assert.equal(requestOptions.headers['X-CSRF-TOKEN'], this.csrf);
          this.authenticated = true; this.csrf = 'authenticated-' + id; return response(200, { authenticated: true });
        }
        assert.equal(url.pathname, '/api/items');
        const body = requestOptions.data;
        state.posts.push({ context: id, authenticated: this.authenticated, body: clone(body) });
        if (!this.authenticated && !options.allowAnonymous) return response(401, { error: 'AUTH_REQUIRED' });
        if (requestOptions.headers?.['X-CSRF-TOKEN'] !== this.csrf && !options.ignoreCsrf)
          return response(403, { error: 'CSRF_REQUIRED' });
        const valid = ['itemCode', 'itemName'].every(field => typeof body[field] === 'string' && body[field].trim());
        if (!valid && !options.acceptInvalid) return response(400, { error: 'required value missing or blank' });
        const code = typeof body.itemCode === 'string' ? (options.noTrim ? body.itemCode : body.itemCode.trim()) : '';
        const itemName = typeof body.itemName === 'string' ? (options.noTrim ? body.itemName : body.itemName.trim()) : '';
        const duplicate = state.rows.find(row => row.itemCode === code);
        if (duplicate && !options.allowDuplicates) {
          if (options.updateOnDuplicate) duplicate.itemName = body.itemName;
          return response(409, { error: 'duplicate itemCode' });
        }
        const record = { id: state.nextId++, itemCode: code, itemName,
          specification: body.specification ?? null, unit: body.unit ?? null, remark: body.remark ?? null };
        if (!options.noPersist) state.rows.push(record);
        return response(201, options.stringId ? { ...record, id: String(record.id) } : record);
      },
      async dispose() { this.disposed = true; if (options.contextCleanupFailure) throw new Error('unit context cleanup failed'); },
    };
    state.contexts.push(context); return context;
  }
  return { state, Runtime, createContext };
}

async function scenario(options = {}) {
  const directory = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'item-post-oracle-')));
  const projectRoot = path.join(directory, 'project');
  const migration = path.join(projectRoot, 'backend/src/main/resources/db/migration');
  fs.mkdirSync(migration, { recursive: true }); fs.writeFileSync(path.join(migration, 'V6__query.sql'), '-- unit fixture');
  const credentials = path.join(directory, 'account.json');
  fs.writeFileSync(credentials, JSON.stringify({ username: 'unit-user', password: 'unit-password' }));
  const previousCredentials = process.env.HARNESS_LOGIN_CREDENTIALS, previousLog = console.log;
  process.env.HARNESS_LOGIN_CREDENTIALS = credentials; console.log = () => {};
  const query = environment('query');
  const post = environment('post', options, () => assert.equal(query.state.closed, true, 'Query DB must be closed before POST starts'));
  let queryCalls = 0;
  async function queryVerify(output) {
    queryCalls++;
    if (options.queryFailure || options.queryCoverage || options.queryCleanup) {
      fs.mkdirSync(path.join(output, 'runtime'), { recursive: true });
      fs.writeFileSync(path.join(output, 'runtime/backend.log'),
        '2026-11-04T18:21:19.930Z WARN jdbc : ErrorCode: 0, SQLState: 42883\n'
        + 'ERROR: operator does not exist: text ~~ bytea\n'
        + 'org.postgresql.util.PSQLException: private message\n'
        + '  at org.example.OrderController.search(OrderController.java:22)\n'
        + 'Authorization: Bearer private-token\nSTATEMENT: select private-business-value\n');
      return { passed: !options.queryFailure, cases: options.queryCoverage ? queryOracle.CASES.slice(1) : queryOracle.CASES,
        cleanup: { success: !options.queryCleanup }, failure: 'unit query regression failure', databaseStarted: true };
    }
    return queryOracle.verify(output, { projectRoot, Runtime: query.Runtime, createContext: query.createContext });
  }
  try {
    const result = await createOracle.verify(path.join(directory, 'evidence'),
      { projectRoot, Runtime: post.Runtime, createContext: post.createContext, queryVerify });
    assert.deepEqual(JSON.parse(fs.readFileSync(path.join(directory, 'evidence/result.json'), 'utf8')), clone(result));
    return { result, query: query.state, post: post.state, queryCalls };
  } finally {
    console.log = previousLog;
    if (previousCredentials === undefined) delete process.env.HARNESS_LOGIN_CREDENTIALS;
    else process.env.HARNESS_LOGIN_CREDENTIALS = previousCredentials;
    fs.rmSync(directory, { recursive: true, force: true });
  }
}

test('two real oracle flows with mock transports keep query DB separate and prove POST persistence', async () => {
  const { result, query, post, queryCalls } = await scenario();
  assert.equal(result.passed, true); assert.deepEqual(result.cases, createOracle.CASES);
  assert.equal(queryCalls, 1); assert.equal(query.instances.length, 1); assert.equal(post.instances.length, 1);
  assert.deepEqual(query.rows, FIXTURE);
  assert.equal(post.rows.length, 5); assert.ok(query.closed && post.closed);
  assert.ok([...query.contexts, ...post.contexts].every(context => context.disposed));
  assert.equal(result.verificationMode, 'api-and-sql-only'); assert.equal(result.browserStarted, false);
  assert.equal(result.sqlProofs.find(proof => proof.label === 'fresh-post-database').rows.length, 0);
  assert.deepEqual(result.sqlProofs.find(proof => proof.label === 'post-relogin-persistence').rows.map(row => row.id), [11, 29, 101, 102, 103]);
});

test('missing/null/empty/whitespace required input is tested explicitly and accepting it fails', async () => {
  const positive = await scenario();
  for (const field of ['itemCode', 'itemName']) {
    const bodies = positive.post.posts.filter(call => call.authenticated).map(call => call.body);
    assert.ok(bodies.some(body => !Object.hasOwn(body, field)));
    assert.ok(bodies.some(body => body[field] === null));
    assert.ok(bodies.some(body => body[field] === ''));
    assert.ok(bodies.some(body => body[field] === '   '));
  }
  const { result, post } = await scenario({ acceptInvalid: true });
  assert.equal(result.passed, false); assert.match(result.failure, /must reject missing itemCode with 4xx/);
  assert.equal(post.closed, true);
});

test('untrimmed values, string ids and acknowledgements without SQL persistence fail', async () => {
  for (const options of [{ noTrim: true }, { stringId: true }, { noPersist: true }]) {
    const { result, post } = await scenario(options);
    assert.equal(result.passed, false); assert.equal(post.closed, true);
    assert.ok(!result.cases.includes('post-create-trim-and-required-validation'));
  }
});

test('application duplicate lookup alone is insufficient without a database unique key', async () => {
  const { result, post } = await scenario({ noDbUnique: true });
  assert.equal(result.passed, false); assert.match(result.failure, /Database must enforce/); assert.equal(post.closed, true);
});

test('a unique id index with INCLUDE(item_code) cannot satisfy unique item_code', async () => {
  const { result, post } = await scenario({ includedCodeOnly: true });
  assert.equal(result.passed, false); assert.match(result.failure, /Database must enforce/);
  assert.equal(post.uniqueQueries.length, 1);
  assert.match(post.uniqueQueries[0], /a\.attnum=i\.indkey\[0\]/);
  assert.ok(!post.uniqueQueries[0].includes('ANY(i.indkey)'));
});

test('duplicate insertion and duplicate upsert with an error both fail', async () => {
  for (const options of [{ allowDuplicates: true }, { updateOnDuplicate: true }]) {
    const { result } = await scenario(options);
    assert.equal(result.passed, false);
    assert.ok(!result.cases.includes('post-optional-and-database-unique'));
  }
});

test('anonymous writes and missing-CSRF writes cannot pass', async () => {
  for (const options of [{ allowAnonymous: true }, { ignoreCsrf: true }]) {
    const { result, post } = await scenario(options);
    assert.equal(result.passed, false); assert.equal(post.closed, true);
    assert.ok(!result.cases.includes('post-session-csrf-and-relogin-persistence'));
  }
});

test('query failure keeps POST unstarted and forwards sanitized child runtime diagnostics', async () => {
  const { result, post } = await scenario({ queryFailure: true });
  assert.equal(result.passed, false); assert.equal(post.instances.length, 0); assert.equal(result.postDatabaseStarted, false);
  assert.match(result.failure, /text ~~ bytea/); assert.match(result.failure, /42883/);
  assert.match(result.failure, /OrderController.search/);
  assert.ok(!result.failure.includes('private-token') && !result.failure.includes('private-business-value'));
});

test('incomplete query cases or query cleanup cannot be reported as a regression pass', async () => {
  for (const options of [{ queryCoverage: true }, { queryCleanup: true }]) {
    const { result, post } = await scenario(options);
    assert.equal(result.passed, false); assert.equal(post.instances.length, 0);
    assert.ok(!result.cases.includes(createOracle.POST_CASES[0]));
  }
});

test('POST runtime and API context cleanup failures keep the whole stage failed', async () => {
  for (const options of [{ cleanupFailure: true }, { contextCleanupFailure: true }]) {
    const { result, post } = await scenario(options);
    assert.equal(result.passed, false); assert.equal(result.cleanup.success, false); assert.equal(post.closed, true);
    assert.ok(!result.cases.includes('post-owned-resources-cleanup'));
  }
});

test('POST helper cannot send credentials or a business write outside the owned loopback origin', async () => {
  let calls = 0;
  const context = { post: async () => { calls++; } };
  for (const base of ['https://example.com', 'http://user:password@127.0.0.1:45432', 'http://127.0.0.1:45432/other'])
    await assert.rejects(createOracle.postItem(context, base, [], {}, {}));
  assert.equal(calls, 0);
});
