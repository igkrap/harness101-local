// Trusted infrastructure smoke: any schema below exists only in its owned DB.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { execFileSync } = require('node:child_process');
const { ItemRuntime } = require('./item_crud_runtime_client.cjs');

async function main() {
  const output = path.resolve(process.argv[2]);
  const runtime = new ItemRuntime(output);
  const proof = { passed: false, real_model_calls: 0 };
  try {
    const info = await runtime.start();
    const state = JSON.parse(fs.readFileSync(info.state_file, 'utf8'));
    assert.match(state.token, /^[0-9a-f]{32}$/);
    assert.equal(info.db_name, 'mdi_item_' + state.token);
    assert.equal(state.database, info.db_name);
    assert.equal(state.role, info.db_name);
    proof.database = info.db_name;
    const existing = await runtime.rows("SELECT to_regclass('public.items') AS target");
    proof.test_fixture_schema_created = existing[0].target === null;
    if (proof.test_fixture_schema_created) {
      // The baseline app has no item migration yet. This table is deliberately
      // not written to application sources and disappears during cleanup.
      execFileSync('docker', ['exec', '-i', 'mdi-db', 'psql', '-X', '-qAt', '-U', 'mdi', '-d', info.db_name, '-v', 'ON_ERROR_STOP=1'], {
        encoding: 'utf8', timeout: 10000,
        input: `BEGIN; SET LOCAL ROLE ${state.role}; CREATE TABLE public.items (
          id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
          item_code varchar(40) NOT NULL UNIQUE, item_name varchar(120) NOT NULL,
          specification varchar(120), unit varchar(20), remark varchar(200)); COMMIT;`,
      });
    }
    assert.deepEqual(await runtime.rows('SELECT count(*) AS count FROM public.items'), [{ count: 0 }]);
    const rows = await runtime.seedQueryFixture();
    assert.deepEqual(rows.map(({ id, ...values }) => values), [
      { itemCode: 'A-100', itemName: '육각 볼트', specification: 'M8x30', unit: 'EA', remark: '도금 볼트' },
      { itemCode: 'B-200', itemName: '육각 너트', specification: 'M10', unit: 'BOX', remark: '스테인리스 너트' },
    ]);
    proof.rows = rows;
    proof.common = await runtime.rows("SELECT count(*) AS count FROM public.items WHERE item_name LIKE '%육각%'");
    proof.individual = await runtime.rows("SELECT count(*) AS count FROM public.items WHERE item_code = 'A-100'");
    proof.and_mismatch = await runtime.rows("SELECT count(*) AS count FROM public.items WHERE item_code = 'A-100' AND item_name LIKE '%너트%'");
    assert.deepEqual(proof.common, [{ count: 2 }]);
    assert.deepEqual(proof.individual, [{ count: 1 }]);
    assert.deepEqual(proof.and_mismatch, [{ count: 0 }]);
    await assert.rejects(runtime.seedQueryFixture(), /empty items table/);
    await assert.rejects(runtime.request('seed_query_fixture', { query: 'DELETE FROM items' }), /accepts no values/);
    await assert.rejects(runtime.rows('DELETE FROM public.items'), /read-only SELECT/);
    const persisted = await runtime.rows('SELECT id, item_code AS "itemCode", item_name AS "itemName", specification, unit, remark FROM public.items ORDER BY item_code');
    assert.deepEqual(persisted, rows);
    proof.repeat_rejected = true;
    proof.write_sql_rejected = true;
    proof.persisted_unchanged = true;
    proof.passed = true;
  } finally {
    proof.cleanup = await runtime.close();
    fs.mkdirSync(output, { recursive: true });
    fs.writeFileSync(path.join(output, 'fixture-smoke.json'), JSON.stringify(proof, null, 2) + '\n');
  }
  console.log(JSON.stringify(proof));
}

main().catch(error => { console.error(error.message); process.exitCode = 1; });
