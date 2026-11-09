const assert = require('node:assert/strict');
const test = require('node:test');
const { ItemRuntime } = require('./item_crud_runtime_client.cjs');

test('fixed query fixture request has no caller-supplied values', async () => {
  const runtime = new ItemRuntime('/tmp/item-runtime-client-fixture');
  const rows = [{ id: 41 }, { id: 42 }];
  runtime.request = async (...args) => {
    assert.deepEqual(args, ['seed_query_fixture']);
    return { fixture: 'item-query-v1', rows };
  };
  assert.deepEqual(await runtime.seedQueryFixture(), rows);
});

test('fixture method rejects missing marker and invalid generated IDs', async () => {
  const runtime = new ItemRuntime('/tmp/item-runtime-client-fixture');
  for (const response of [{ rows: [{ id: 1 }, { id: 2 }] },
    { fixture: 'item-query-v1', rows: [] },
    { fixture: 'item-query-v1', rows: [{ id: 1 }, { id: 1 }] },
    { fixture: 'item-query-v1', rows: [{ id: '1' }, { id: 2 }] }]) {
    runtime.request = async () => response;
    await assert.rejects(runtime.seedQueryFixture(), /fixture proof is invalid/);
  }
});
