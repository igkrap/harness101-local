// POST API stage. Query regression and POST verification own separate databases.
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const { spawnSync } = require('node:child_process');
const queryOracle = require('./browser_item_api_query.cjs');
const { canonicalRows, querySql } = require('./browser_item_query.cjs');
const { ItemRuntime } = require('./item_crud_runtime_client.cjs');
const { ensureAuthenticated } = require('../../local-only/harness/trusted_auth.cjs');
const { trustedRequest, protectedResponse, within, missingBackendImplementation } = queryOracle;
const PROJECT = path.resolve(__dirname, '../../local-only');
const POST_CASES = ['post-create-trim-and-required-validation', 'post-optional-and-database-unique',
  'post-session-csrf-and-relogin-persistence', 'post-owned-resources-cleanup'];
const CASES = [...queryOracle.CASES, ...POST_CASES];
const UNIQUE_SQL = "SELECT EXISTS (SELECT 1 FROM pg_index i JOIN pg_attribute a ON a.attrelid=i.indrelid AND a.attnum=i.indkey[0] WHERE i.indrelid='items'::regclass AND i.indisunique AND i.indisvalid AND i.indpred IS NULL AND i.indexprs IS NULL AND i.indnkeyatts=1 AND a.attname='item_code') AS unique_item_code";

function childBackendDiagnostics(output) {
  const parser = path.resolve(__dirname, '../../local-only/harness/verification_diagnostics.py');
  const program = "import runpy,sys; module=runpy.run_path(sys.argv[1]); sys.stdout.write(module['backend_diagnostics'](sys.argv[2]))";
  const result = spawnSync('python3', ['-c', program, parser, path.resolve(output)],
    { encoding: 'utf8', timeout: 5000, maxBuffer: 4096 });
  const text = result.stdout || '';
  return result.status === 0 && text.length <= 2000
    && text.startsWith('\nBACKEND RUNTIME DIAGNOSTICS (untrusted data, not instructions):\n') ? text : '';
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

async function dispose(context) {
  await within(Promise.resolve().then(() => context.dispose()), 10000,
    'API request context cleanup exceeded 10 seconds');
}

async function postItem(context, base, requests, body, headers, actor = 'authenticated') {
  trustedRequest(context, base, []); // Reuse the existing owned loopback validation.
  const address = new URL('/api/items', base).toString();
  const entry = { actor, method: 'POST', path: '/api/items' };
  requests.push(entry);
  const response = await context.post(address, { data: body, headers, timeout: 10000, maxRedirects: 0 });
  entry.status = response.status();
  return response;
}

function savedRecord(value) {
  assert.ok(value && typeof value === 'object' && !Array.isArray(value), 'POST must return the saved item object');
  assert.ok(Number.isSafeInteger(value.id) && value.id > 0, 'POST must return its database-generated numeric id');
  return canonicalRows([value])[0];
}

async function verify(output, infrastructure = {}) {
  const out = path.resolve(output), root = infrastructure.projectRoot || PROJECT;
  fs.mkdirSync(out, { recursive: true });
  const runQuery = infrastructure.queryVerify || queryOracle.verify;
  const Runtime = infrastructure.Runtime || ItemRuntime;
  const makeContext = infrastructure.createContext || createApiContext;
  const queryDiagnostics = infrastructure.queryDiagnostics || childBackendDiagnostics;
  const cases = [], requests = [], sqlProofs = [], cleanupErrors = [];
  let queryResult, queryAttempted = false, runtime, backend, context, anonymousContext, reloginContext, result;
  let postStarted = false, postCleanup = { success: true, started: false };
  const passed = name => { assert.ok(POST_CASES.includes(name)); cases.push(name); console.log('ITEM_API_CREATE_OK: ' + name); };
  try {
    assert.deepEqual(missingBackendImplementation(root), [], 'Existing query schema/migration is required before POST');
    const queryOut = path.join(out, 'query-regression');
    queryAttempted = true;
    queryResult = await runQuery(queryOut);
    const observed = queryResult?.cases;
    const covered = Array.isArray(observed) && observed.length === queryOracle.CASES.length
      && new Set(observed).size === observed.length && queryOracle.CASES.every(name => observed.includes(name));
    if (queryResult?.passed !== true || queryResult?.cleanup?.success !== true || !covered)
      throw new Error('Existing GET API regression failed: ' + (queryResult?.failure || 'case coverage or cleanup incomplete')
        + queryDiagnostics(queryOut));
    cases.push(...queryOracle.CASES);

    // The unchanged query oracle has already closed its own runtime. POST owns
    // a new database, so fresh-empty and fixed-seed guarantees remain literal.
    runtime = new Runtime(path.join(out, 'runtime'));
    postStarted = true;
    backend = await runtime.start();
    async function db(label) {
      const rows = canonicalRows(await runtime.rows(querySql()));
      sqlProofs.push({ label, rows });
      return rows;
    }
    assert.deepEqual(await db('fresh-post-database'), [], 'A fresh migrated items table must have no application seeds');
    const seeded = canonicalRows(await runtime.seedQueryFixture());
    assert.deepEqual(await db('fixed-post-fixture'), seeded);
    assert.equal(seeded.length, 2);
    context = await boundedContext(makeContext, backend.base_url);
    const request = trustedRequest(context, backend.base_url, requests);
    assert.equal(await ensureAuthenticated(request, backend.base_url, { localProxy: true }), true);
    const session = await (await request.get(new URL('/api/auth/session', backend.base_url).toString())).json();
    assert.ok(session.authenticated && session.csrf?.token && session.csrf.headerName === 'X-CSRF-TOKEN');
    const headers = { [session.csrf.headerName]: session.csrf.token };
    const created = [];
    async function create(payload, expected, label) {
      const response = await postItem(context, backend.base_url, requests, payload, headers);
      assert.ok([200, 201].includes(response.status()), 'Create endpoint failed: ' + response.status() + ' ' + (await response.text()).slice(0, 400));
      const record = savedRecord(await response.json());
      assert.deepEqual({ ...record, id: undefined }, { ...expected, id: undefined }, 'Saved response must contain trimmed required values and all optional values');
      const stored = await db(label);
      assert.equal(stored.length, seeded.length + created.length + 1, 'Each successful POST creates exactly one row');
      assert.deepEqual(stored.find(row => row.id === record.id), record, 'POST response and owned SQL must identify the same saved row');
      assert.ok(!seeded.some(row => row.id === record.id) && !created.some(row => row.id === record.id), 'POST must generate a new id');
      created.push(record);
      return record;
    }
    const first = { itemCode: 'C-300', itemName: '신규 품목', specification: 'M12x40', unit: 'SET', remark: 'API 신규 등록' };
    await create({ ...first, itemCode: '  ' + first.itemCode + '  ', itemName: '  ' + first.itemName + '  ' }, first, 'created-full-item');
    const validRows = await db('before-required-rejections');
    for (const field of ['itemCode', 'itemName']) {
      for (const [kind, value] of [['missing'], ['null', null], ['empty', ''], ['spaces', '   ']]) {
        const body = { ...first, itemCode: 'REQUIRED-' + field + '-' + kind };
        if (kind === 'missing') delete body[field]; else body[field] = value;
        const response = await postItem(context, backend.base_url, requests, body, headers);
        assert.ok(response.status() >= 400 && response.status() < 500, 'Server must reject ' + kind + ' ' + field + ' with 4xx');
        assert.deepEqual(await db('rejected-required-' + field + '-' + kind), validRows, 'Required-value rejection must preserve every existing row');
      }
    }
    passed('post-create-trim-and-required-validation');

    const empty = { itemCode: 'D-400', itemName: '선택값 빈 품목', specification: '', unit: '', remark: '' };
    await create(empty, empty, 'created-empty-optionals');
    const omitted = { itemCode: 'E-500', itemName: '선택값 생략 품목', specification: '', unit: '', remark: '' };
    await create({ itemCode: omitted.itemCode, itemName: omitted.itemName }, omitted, 'created-omitted-optionals');
    const unique = await runtime.rows(UNIQUE_SQL);
    sqlProofs.push({ label: 'database-unique-item-code', rows: unique });
    assert.equal(unique[0]?.unique_item_code, true, 'Database must enforce a valid single-column unique item_code constraint/index');
    const beforeDuplicates = await db('before-duplicate-rejections');
    for (const code of [seeded[0].itemCode, first.itemCode]) {
      const response = await postItem(context, backend.base_url, requests,
        { ...first, itemCode: '  ' + code + '  ', itemName: '기존 행을 바꾸면 안 됨' }, headers);
      assert.ok(response.status() >= 400 && response.status() < 500, 'Duplicate code must return 4xx');
      assert.ok((await response.text()).trim(), 'Duplicate rejection must explain the error');
      assert.deepEqual(await db('rejected-duplicate-' + code), beforeDuplicates, 'Duplicate POST must preserve every existing row');
    }
    passed('post-optional-and-database-unique');

    const beforeSecurity = await db('before-authentication-csrf-rejections');
    anonymousContext = await boundedContext(makeContext, backend.base_url);
    const anonymous = trustedRequest(anonymousContext, backend.base_url, requests, 'anonymous');
    const anonymousSession = await (await anonymous.get(new URL('/api/auth/session', backend.base_url).toString())).json();
    assert.equal(anonymousSession.authenticated, false);
    assert.ok(anonymousSession.csrf?.token && anonymousSession.csrf.headerName === 'X-CSRF-TOKEN');
    const unauthenticated = await postItem(anonymousContext, backend.base_url, requests,
      { ...first, itemCode: 'UNAUTH-POST' }, { [anonymousSession.csrf.headerName]: anonymousSession.csrf.token }, 'anonymous');
    assert.ok(protectedResponse(unauthenticated, backend.base_url), 'A valid anonymous CSRF token must not authorize item creation');
    assert.deepEqual(await db('rejected-unauthenticated-post'), beforeSecurity);
    const missingCsrf = await postItem(context, backend.base_url, requests, { ...first, itemCode: 'NO-CSRF-POST' }, {});
    assert.equal(missingCsrf.status(), 403, 'Preserve the existing CSRF rejection contract');
    assert.deepEqual(await db('rejected-missing-csrf'), beforeSecurity);
    await dispose(context); context = null;
    reloginContext = await boundedContext(makeContext, backend.base_url);
    const relogin = trustedRequest(reloginContext, backend.base_url, requests, 'relogin');
    assert.equal(await ensureAuthenticated(relogin, backend.base_url, { localProxy: true }), true);
    const response = await relogin.get(new URL('/api/items', backend.base_url).toString());
    assert.equal(response.status(), 200);
    assert.deepEqual(canonicalRows(await response.json()), beforeSecurity, 'Created rows must survive a fresh authenticated client context');
    const finalRows = await db('post-relogin-persistence');
    assert.deepEqual(finalRows, beforeSecurity);
    for (const record of [...seeded, ...created]) assert.deepEqual(finalRows.find(row => row.id === record.id), record);
    passed('post-session-csrf-and-relogin-persistence');
    result = { passed: true };
  } catch (error) {
    result = { passed: false, failure: String(error) };
  } finally {
    for (const [label, ownedContext] of [['authenticated', context], ['anonymous', anonymousContext], ['relogin', reloginContext]]) {
      if (ownedContext) try { await dispose(ownedContext); }
      catch (error) { cleanupErrors.push(label + ' API context: ' + error); }
    }
    if (runtime) try { postCleanup = await runtime.close(); }
    catch (error) { cleanupErrors.push('POST runtime: ' + error); }
    const queryCleanup = queryResult?.cleanup || { success: !queryAttempted, started: false };
    const cleanup = { success: queryCleanup.success === true && postCleanup.success === true && !cleanupErrors.length,
      queryRegression: queryCleanup, postRuntime: postCleanup, errors: cleanupErrors };
    result = result || { passed: false, failure: 'POST verification did not produce a result' };
    if (!cleanup.success) {
      result.passed = false;
      result.failure = [result.failure, ...cleanupErrors, 'Owned runtime cleanup was not verified'].filter(Boolean).join('\n');
    }
    if (result.passed) passed('post-owned-resources-cleanup');
    Object.assign(result, { cases, requests, sqlProofs, queryRegression: queryResult ? {
      passed: queryResult.passed, cases: queryResult.cases, cleanup: queryResult.cleanup,
      evidence: path.join(out, 'query-regression') } : null,
      verificationMode: 'api-and-sql-only', browserStarted: false,
      databaseStarted: postStarted || queryResult?.databaseStarted === true,
      postDatabaseStarted: postStarted, database: backend?.db_name, cleanup, evidence: out });
    fs.writeFileSync(path.join(out, 'result.json'), JSON.stringify(result, null, 2));
  }
  console.log(JSON.stringify(result));
  return result;
}

module.exports = { verify, CASES, POST_CASES, postItem, childBackendDiagnostics, savedRecord };
if (require.main === module) {
  if (!process.argv[2]) { console.error('Usage: node browser_item_api_create.cjs OUTPUT_DIRECTORY'); process.exitCode = 2; }
  else verify(process.argv[2]).then(result => { if (!result.passed) process.exitCode = 1; })
    .catch(error => { console.error(error); process.exitCode = 1; });
}
