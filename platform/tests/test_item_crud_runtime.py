import json
import io
import contextlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from item_crud_runtime import APP, ItemRuntime, LABEL, QUERY_FIXTURE, QUERY_FIXTURE_ID, main


class ItemRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.runtime = ItemRuntime(self.temp.name, 'a' * 32)

    def test_query_uses_own_database_and_read_only_transaction(self):
        self.runtime.psql = Mock(return_value='[{"item_code":"A-1"}]')
        self.assertEqual(self.runtime.query('SELECT item_code FROM items;'), [{'item_code': 'A-1'}])
        statement, database = self.runtime.psql.call_args.args
        self.assertEqual(database, self.runtime.database)
        self.assertTrue(statement.startswith('BEGIN READ ONLY;'))
        self.assertIn("statement_timeout='5s'", statement)
        self.assertTrue(statement.endswith('ROLLBACK;'))

    def test_query_rejects_writes_and_statement_injection(self):
        self.runtime.psql = Mock()
        for query in ('DELETE FROM items', 'SELECT 1; DELETE FROM items',
                      'SELECT 1 -- trailing', 'SELECT 1 /* comment */', None, 'SELECT ' + 'x' * 16000):
            with self.subTest(query=str(query)[:40]), self.assertRaises(ValueError):
                self.runtime.query(query)
        self.runtime.psql.assert_not_called()

    def test_cleanup_refuses_unowned_container_and_never_touches_database(self):
        self.runtime.inspect = Mock(return_value={'Config': {'Labels': {LABEL: 'somebody-else'}}})
        self.runtime.psql = Mock()
        with patch('item_crud_runtime.command') as execute:
            report = self.runtime.close()
        self.assertFalse(report['success'])
        self.assertFalse(report['container_removed'])
        self.runtime.psql.assert_not_called()
        execute.assert_not_called()

    def test_cleanup_refuses_unowned_database_and_does_not_drop_role(self):
        self.runtime.inspect = Mock(return_value=None)
        self.runtime.psql = Mock(side_effect=['a' * 32, 'unrelated-owner'])
        report = self.runtime.close()
        self.assertFalse(report['success'])
        self.assertTrue(report['container_removed'])
        self.assertTrue(report['target_volume_removed'])
        self.assertFalse(report['database_removed'])
        self.assertFalse(any('DROP ' in call.args[0] for call in self.runtime.psql.call_args_list))

    def test_already_absent_cleanup_is_idempotent(self):
        self.runtime.inspect = Mock(return_value=None)
        self.runtime.psql = Mock(side_effect=['', '', '0', '0'])
        first = self.runtime.close()
        self.assertTrue(first['success'])
        self.assertIs(self.runtime.close(), first)
        self.assertEqual(self.runtime.psql.call_count, 4)
        saved = json.loads((Path(self.temp.name) / 'cleanup.json').read_text())
        self.assertTrue(saved['success'])

    def test_ownership_tokens_and_evidence_boundary_are_validated(self):
        with self.assertRaises(ValueError):
            ItemRuntime(self.temp.name, '../unrelated')
        with self.assertRaises(ValueError):
            ItemRuntime(APP / 'frontend', 'a' * 32)
        state = self.runtime.state()
        self.assertTrue(state['database'].startswith('mdi_item_'))
        self.assertNotIn(state['database'], ('mdi_local', 'mdi_local_test'))

    def fixture_rows(self):
        return [dict(id=index + 41, **row) for index, row in enumerate(QUERY_FIXTURE)]

    def test_seed_uses_fixed_values_generated_ids_and_atomic_owned_empty_guard(self):
        rows = self.fixture_rows()
        self.runtime.owned = Mock(return_value={'State': {'Running': True}})
        self.runtime.psql = Mock(return_value=json.dumps(rows))
        self.assertEqual(self.runtime.seed_query_fixture(), rows)
        statement, database = self.runtime.psql.call_args.args
        self.assertEqual(database, self.runtime.database)
        self.assertTrue(statement.startswith('BEGIN;'))
        self.assertTrue(statement.endswith('COMMIT;'))
        self.assertIn("shobj_description(oid,'pg_authid')", statement)
        self.assertIn('SET LOCAL ROLE ' + self.runtime.role, statement)
        self.assertLess(statement.index('LOCK TABLE public.items IN ACCESS EXCLUSIVE MODE'), statement.index('IF EXISTS (SELECT 1 FROM public.items)'))
        self.assertLess(statement.index('IF EXISTS (SELECT 1 FROM public.items)'), statement.index('INSERT INTO public.items'))
        self.assertIn('INSERT INTO public.items (item_code,item_name,specification,unit,remark)', statement)
        self.assertNotIn('INSERT INTO public.items (id', statement)
        self.assertIn('ORDER BY item_code', statement)
        self.assertNotIn('mdi_local', statement)
        self.assertIn("'A-100', '육각 볼트', 'M8x30', 'EA', '도금 볼트'", statement)
        self.assertEqual(self.runtime.psql.call_args.kwargs['timeout'], 10)

    def test_seed_cannot_target_other_database_or_unowned_runtime(self):
        self.runtime.psql = Mock()
        self.runtime.database = 'mdi_local'
        with self.assertRaisesRegex(RuntimeError, 'owned database'):
            self.runtime.seed_query_fixture()
        self.runtime.database = 'mdi_item_' + self.runtime.token
        self.runtime.owned = Mock(return_value=None)
        with self.assertRaisesRegex(RuntimeError, 'running owned runtime'):
            self.runtime.seed_query_fixture()
        self.runtime.owned = Mock(side_effect=RuntimeError('unowned container'))
        with self.assertRaisesRegex(RuntimeError, 'unowned container'):
            self.runtime.seed_query_fixture()
        self.runtime.psql.assert_not_called()

    def test_seed_propagates_nonempty_table_rejection_and_rejects_false_proof(self):
        self.runtime.owned = Mock(return_value={'State': {'Running': True}})
        self.runtime.psql = Mock(side_effect=RuntimeError('Query fixture requires an empty items table'))
        with self.assertRaisesRegex(RuntimeError, 'empty items table'):
            self.runtime.seed_query_fixture()
        for rows in ([], [{'id': 1}], [dict(id=1, **row) for row in QUERY_FIXTURE],
                     [dict(id='1', **row) for row in QUERY_FIXTURE],
                     [dict(id=2**54 + index, **row) for index, row in enumerate(QUERY_FIXTURE)]):
            self.runtime.psql = Mock(return_value=json.dumps(rows))
            with self.subTest(rows=rows), self.assertRaisesRegex(RuntimeError, 'fixture contract'):
                self.runtime.seed_query_fixture()

    def protocol(self, requests):
        runtime = Mock()
        runtime.start.return_value = {'event': 'ready'}
        runtime.seed_query_fixture.return_value = self.fixture_rows()
        runtime.close.return_value = {'success': True}
        output = io.StringIO()
        with patch('item_crud_runtime.ItemRuntime', return_value=runtime), \
                patch('item_crud_runtime.signal.signal'), \
                patch.object(sys, 'argv', ['item_crud_runtime.py', '--output', self.temp.name]), \
                patch.object(sys, 'stdin', io.StringIO('\n'.join(json.dumps(value) for value in requests))), \
                contextlib.redirect_stdout(output):
            self.assertEqual(main(), 0)
        return runtime, [json.loads(line) for line in output.getvalue().splitlines()]

    def test_protocol_seeds_only_when_explicitly_requested_and_returns_real_rows(self):
        runtime, messages = self.protocol([{'id': 'fixture', 'op': 'seed_query_fixture'}, {'id': 'done', 'op': 'close'}])
        runtime.seed_query_fixture.assert_called_once_with()
        self.assertEqual(messages[1], {'id': 'fixture', 'ok': True, 'fixture': QUERY_FIXTURE_ID, 'rows': self.fixture_rows()})
        self.assertTrue(messages[-1]['cleanup']['success'])
        runtime, messages = self.protocol([{'id': 'done', 'op': 'close'}])
        runtime.start.assert_called_once_with()
        runtime.seed_query_fixture.assert_not_called()

    def test_protocol_refuses_fixture_values_or_sql_and_still_closes(self):
        for extra in ({'query': 'DELETE FROM items'}, {'rows': []}, {'table': 'other'}):
            runtime, messages = self.protocol([{'id': 'bad', 'op': 'seed_query_fixture', **extra}, {'id': 'done', 'op': 'close'}])
            runtime.seed_query_fixture.assert_not_called()
            runtime.query.assert_not_called()
            self.assertFalse(messages[1]['ok'])
            self.assertIn('accepts no values', messages[1]['error'])
            self.assertTrue(messages[-1]['cleanup']['success'])


if __name__ == '__main__':
    unittest.main()
