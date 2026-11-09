"""Failure feedback must expose runtime causes without a general artifact reader."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'local-only/harness'))
import fixed_acceptance
from completion_runner import extend_completion
from focused_context import feedback
import verification_diagnostics as diagnostics


CAUSE = '''2026-11-04T18:21:19.930Z WARN jdbc : HHH000247: ErrorCode: 0, SQLState: 42883
2026 WARN jdbc : ERROR: operator does not exist: text ~~ bytea
2026 ERROR dispatcher: failed SQL [select 'private-item-value' from confidential_table]
org.postgresql.util.PSQLException: ERROR: operator does not exist: text ~~ bytea
  Hint: No operator matches the given name and argument types.
  at org.postgresql.core.v3.QueryExecutorImpl.receiveErrorResponse(QueryExecutorImpl.java:2993)
  at org.springframework.dao.support.PersistenceExceptionTranslationInterceptor.invoke(PersistenceExceptionTranslationInterceptor.java:135)
  at org.example.orders.OrderController.search(OrderController.java:22)
'''


class DiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.output = self.base / 'current-verification'
        (self.output / 'runtime').mkdir(parents=True)
        self.log = self.output / 'runtime/backend.log'
        self.log.write_text(CAUSE)

    def test_structured_cause_and_app_frame_are_visible_without_raw_sql(self):
        text = diagnostics.backend_diagnostics(self.output)
        self.assertIn('42883', text)
        self.assertIn('operator does not exist: text ~~ bytea', text)
        self.assertIn('org.postgresql.util.PSQLException', text)
        self.assertIn('org.example.orders.OrderController.search(OrderController.java:22)', text)
        self.assertNotIn('QueryExecutorImpl', text)
        self.assertNotIn('private-item-value', text)
        self.assertNotIn('confidential_table', text)

    def test_headers_env_quoted_values_and_freeform_exception_messages_are_not_exported(self):
        secrets = ['secret-password', 'secret-token', 'secret-cookie', 'secret-env',
                   'private-row-code', 'secret-url-password', 'private-sql-literal', 'ABCDE', 'FGHIJ']
        self.log.write_text(CAUSE + '''
Authorization: Bearer secret-token
Cookie: SESSION=secret-cookie
DB_PASSWORD=secret-password
SENSITIVE_ENV=secret-env
SENSITIVE_ENV=SQLState:ABCDE
DB_PASSWORD=ERROR ErrorCode: 0, SQLState:ABCDE
jdbc:postgresql://tester:secret-url-password@database/private
DETAIL: Key (item_code)=(private-row-code) already exists.
STATEMENT: select 'private-sql-literal' from items;
STATEMENT: select 'SQLState:FGHIJ' from items;
STATEMENT: select 'ERROR ErrorCode: 0, SQLState:FGHIJ' from items;
Caused by: java.lang.IllegalStateException: secret-password secret-token private-row-code
ERROR: duplicate key value violates unique constraint "private-row-code"
''')
        text = diagnostics.backend_diagnostics(self.output)
        self.assertIn('java.lang.IllegalStateException', text)
        self.assertIn('database unique constraint violation', text)
        for secret in secrets:
            self.assertNotIn(secret, text)
        self.assertNotIn('DB_PASSWORD', text)
        self.assertNotIn('Authorization', text)

    def test_log_output_runtime_and_ancestor_symlinks_are_refused(self):
        self.log.unlink()
        outside = self.base / 'outside.log'; outside.write_text(CAUSE)
        self.log.symlink_to(outside)
        self.assertEqual(diagnostics.backend_diagnostics(self.output), '')
        self.log.unlink(); (self.output / 'runtime').rmdir()
        outside_dir = self.base / 'outside-runtime'; outside_dir.mkdir()
        (outside_dir / 'backend.log').write_text(CAUSE)
        (self.output / 'runtime').symlink_to(outside_dir, target_is_directory=True)
        self.assertEqual(diagnostics.backend_diagnostics(self.output), '')
        (self.output / 'runtime').unlink()
        (self.output / 'runtime').mkdir()
        self.log.write_text(CAUSE)
        alias = self.base / 'output-alias'; alias.symlink_to(self.output, target_is_directory=True)
        self.assertEqual(diagnostics.backend_diagnostics(alias), '')
        ancestor_alias = self.base / 'ancestor-alias'; ancestor_alias.symlink_to(self.base, target_is_directory=True)
        self.assertEqual(diagnostics.backend_diagnostics(ancestor_alias / self.output.name), '')

    def test_relative_traversal_missing_special_and_hardlinked_paths_are_refused(self):
        self.assertEqual(diagnostics.backend_diagnostics(Path('relative')), '')
        self.assertEqual(diagnostics.backend_diagnostics(self.output / '..' / self.output.name), '')
        self.log.unlink()
        self.assertEqual(diagnostics.backend_diagnostics(self.output), '')
        os.mkfifo(self.log)
        self.assertEqual(diagnostics.backend_diagnostics(self.output), '')
        self.log.unlink()
        outside = self.base / 'outside.log'; outside.write_text(CAUSE)
        os.link(outside, self.log)
        self.assertEqual(diagnostics.backend_diagnostics(self.output), '')

    def test_tail_file_and_total_output_bounds_are_enforced(self):
        self.log.write_text('SQLState: 99999\n' + 'ignored line\n' * 10000 + CAUSE)
        text = diagnostics.backend_diagnostics(self.output)
        self.assertIn('42883', text)
        self.assertNotIn('99999', text)
        self.log.write_text(CAUSE + '\n' + '\n'.join(
            'Caused by: org.example.' + ('VeryLongClass' * 8) + str(index) + 'Exception: private' +
            '\n  at org.example.' + ('LongController' * 8) + str(index) + '.search(Code.java:22)'
            for index in range(50)))
        text = diagnostics.backend_diagnostics(self.output)
        self.assertLessEqual(len(text), diagnostics.MAX_DIAGNOSTIC_CHARS)
        json.loads(text[len(diagnostics.PREFIX):])
        with self.log.open('wb') as stream:
            stream.truncate(diagnostics.MAX_LOG_BYTES + 1)
        self.assertEqual(diagnostics.backend_diagnostics(self.output), '')

    def test_unrecognized_messages_do_not_turn_into_freeform_feedback(self):
        self.log.write_text('Authorization: secret\nERROR: customer secret message\nselect secret\n')
        self.assertEqual(diagnostics.backend_diagnostics(self.output), '')


class ProbeBridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.root = self.base / 'local-only'; (self.root / 'frontend/src').mkdir(parents=True)
        self.script = self.base / 'platform/tests/oracle.cjs'
        self.script.parent.mkdir(parents=True); self.script.write_text('// immutable')
        self.spec = {'id': 'diagnostic-example-v1', 'task': 'Connect query', 'project_root': str(self.root),
                     'script': str(self.script), 'script_sha256': hashlib.sha256(self.script.read_bytes()).hexdigest(),
                     'cases': ['query']}
        self.root_patch = patch.object(fixed_acceptance, 'CHECKS_ROOT', self.script.parent)
        self.root_patch.start(); self.addCleanup(self.root_patch.stop)

    def runner(self):
        class Base:
            def __init__(base, args, harness_class):
                base.args = args; base.modes = ['frontend', 'backend', 'framework']
                base.h = SimpleNamespace(workspace=SimpleNamespace(root=self.root), log_event=Mock())
                base.accepted = True; base.steps = [{'kind': 'verify'}]; base.step = 0
                base.messages = []; base.feedback = ''

            def fresh(base, reason=''):
                base.messages = [{'role': 'system', 'content': 'model context'},
                                 {'role': 'user', 'content': feedback(base)}]

        runner = extend_completion(Base)(SimpleNamespace(task=self.spec['task'], context_profile='focused',
                                                       fixed_acceptance=self.spec), None)
        runner.requirement_gate.artifact_dir = self.base / 'evidence'
        runner.requirement_gate.prepare()
        (self.root / 'frontend/src/New.tsx').write_text('export default function New(){return null;}')
        return runner

    def executor(self, *, success=False, linked=False):
        def execute(command, **kwargs):
            out = Path(command[2]); (out / 'runtime').mkdir()
            if linked:
                outside = self.base / 'outside.log'; outside.write_text(CAUSE)
                (out / 'runtime/backend.log').symlink_to(outside)
            else:
                (out / 'runtime/backend.log').write_text(CAUSE)
            (out / 'result.json').write_text(json.dumps({'passed': success, 'cases': ['query'] if success else [],
                                                        'failure': 'GET returned HTTP 500' if not success else None}))
            return subprocess.CompletedProcess(command, 0 if success else 1, '', '')
        return execute

    def test_actual_completion_retry_feedback_contains_backend_cause_and_is_still_failed(self):
        runner = self.runner()
        with patch.object(fixed_acceptance.subprocess, 'run', side_effect=self.executor()):
            self.assertFalse(runner.verify_step())
        self.assertEqual(runner.steps[0]['kind'], 'change')
        text = runner.messages[1]['content']
        self.assertIn('HTTP 500', text)
        self.assertIn('text ~~ bytea', text)
        self.assertIn('42883', text)
        self.assertIn('OrderController.search', text)
        self.assertNotIn('private-item-value', text)
        self.assertFalse(json.loads(runner.feedback)['success'])

    def test_success_reason_and_case_coverage_are_not_changed_by_error_logs(self):
        runner = self.runner()
        criteria = json.loads(runner.requirement_gate.frozen_contract)['criteria']
        with patch.object(fixed_acceptance.subprocess, 'run', side_effect=self.executor(success=True)):
            report = runner.requirement_gate._probe(criteria)
        self.assertTrue(report['success'])
        self.assertEqual(report['results'][0]['reason'], 'All fixed browser workflow cases passed')
        self.assertNotIn('DIAGNOSTICS', json.dumps(report))

    def test_unsafe_diagnostic_log_does_not_hide_or_change_the_failed_verdict(self):
        runner = self.runner()
        criteria = json.loads(runner.requirement_gate.frozen_contract)['criteria']
        with patch.object(fixed_acceptance.subprocess, 'run', side_effect=self.executor(linked=True)):
            report = runner.requirement_gate._probe(criteria)
        self.assertFalse(report['success'])
        self.assertIn('HTTP 500', report['results'][0]['reason'])
        self.assertNotIn('DIAGNOSTICS', report['results'][0]['reason'])


if __name__ == '__main__':
    unittest.main()
