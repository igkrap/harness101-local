"""Use native apply/checkpoint methods with file fixtures and no external services."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'local-only/harness'))
import fixed_acceptance
import workflow_policy
from autonomy_runtime import Runner
from call_budget import ask_with_recovery, snapshot
from harness import Harness, WorkspaceManager

BaseRunner = next(cls for cls in Runner.__mro__ if cls.__module__ == 'autonomy_runtime')
MIGRATIONS = 'backend/src/main/resources/db/migration/'
FIRST = MIGRATIONS + 'V1__create_records.sql'
NEW = MIGRATIONS + 'V2__unique_records.sql'
SEEDED = 'ALTER TABLE receipts ADD UNIQUE (reference);\nINSERT INTO receipts(reference) VALUES (\'DEMO\');\n'
CLEAN = 'ALTER TABLE receipts ADD UNIQUE (reference);\n'


class MigrationRuntimeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.app = self.root / 'project'
        (self.app / 'frontend/src').mkdir(parents=True)
        (self.app / MIGRATIONS).mkdir(parents=True)
        (self.app / FIRST).write_text('CREATE TABLE receipts(reference TEXT);\n')
        checks = self.root / 'platform/tests'
        checks.mkdir(parents=True)
        script = checks / 'create.cjs'
        script.write_text('// trusted isolated workflow fixture')
        self.spec = {'id': 'receipt-create-v1', 'task': 'Create receipt API',
                     'project_root': str(self.app), 'script': str(script),
                     'script_sha256': hashlib.sha256(script.read_bytes()).hexdigest(),
                     'cases': ['create-record']}
        policy = self.root / 'platform/acceptance/policies/receipt-create-v1.json'
        policy.parent.mkdir(parents=True)
        policy.write_text(json.dumps({'version': 1, 'acceptance_id': self.spec['id'],
            'script_sha256': self.spec['script_sha256'], 'database_scope': 'fresh-owned',
            'job_created_migration_edits': True, 'fixture_owner': 'checker',
            'discovery_round_limit': 8}))
        self.patch = patch.object(fixed_acceptance, 'CHECKS_ROOT', checks)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def runner(self, profile='focused', scope='fresh-owned'):
        events = []
        args = SimpleNamespace(task=self.spec['task'], check='backend', max_rounds=32,
                               context_profile=profile, fixed_acceptance=dict(self.spec), edit_format='auto')
        # Run the native tool inheritance chain while skipping service startup.
        h = Harness.__new__(Harness)
        h.workspace = WorkspaceManager(self.app)
        h.checker = SimpleNamespace(schema_application_scope=scope)
        h.args = args
        h._code_intelligence = None
        h.log_event = lambda kind, data: events.append((kind, data))
        runner = BaseRunner(args, lambda args: h)
        runner.events = events
        return runner

    def apply(self, runner, name, **arguments):
        result = BaseRunner.apply(runner, name, arguments, {})
        self.assertFalse(result.get('error'), result)
        return result

    def create(self, runner):
        self.apply(runner, 'write_file', path=NEW, content=SEEDED)
        runner.cp.commit()

    def test_model_created_migration_can_remove_its_seed_after_commit_and_full_read(self):
        runner = self.runner()
        self.create(runner)
        self.apply(runner, 'read_file', path=NEW)
        self.assertEqual(runner._migration_full_reads[NEW], hashlib.sha256(SEEDED.encode()).hexdigest())
        self.apply(runner, 'write_file', path=NEW, content=CLEAN)
        runner.cp.commit()
        self.assertEqual((self.app / NEW).read_text(), CLEAN)
        self.assertTrue(any(kind == 'workflow.policy' for kind, _ in runner.events))

    def test_current_file_snapshot_can_supply_the_actual_full_read_receipt(self):
        runner = self.runner()
        self.create(runner)
        self.assertNotIn(NEW, runner._migration_full_reads)
        runner.messages = [{'role': 'assistant', 'tool_calls': [{'function': {
            'name': 'write_file', 'arguments': json.dumps({'path': NEW, 'content': SEEDED})}}]}]
        content, paths = snapshot(runner)
        self.assertIn('CURRENT FILE ' + NEW + '\n' + SEEDED, content)
        runner.read.update(paths)
        self.apply(runner, 'write_file', path=NEW, content=CLEAN)
        self.assertEqual((self.app / NEW).read_text(), CLEAN)

    def test_atomic_edits_use_the_normalized_migration_operation(self):
        runner = self.runner()
        self.create(runner)
        self.apply(runner, 'read_file', path=NEW)
        self.apply(runner, 'apply_edits', path=NEW,
                   edits=[{'old_text': SEEDED, 'new_text': CLEAN}])
        runner.cp.commit()
        self.assertEqual((self.app / NEW).read_text(), CLEAN)

    def test_read_membership_without_actual_full_source_cannot_authorize_edit(self):
        runner = self.runner()
        self.create(runner)
        runner.read.add(NEW)
        with self.assertRaisesRegex(ValueError, 'complete current migration'):
            self.apply(runner, 'write_file', path=NEW, content=CLEAN)
        self.assertEqual((self.app / NEW).read_text(), SEEDED)

    def test_partial_read_does_not_grant_edit_permission(self):
        runner = self.runner()
        self.create(runner)
        original = runner.h._execute_tool
        runner.h._execute_tool = lambda name, args: {'content': 'ALTER', 'truncated': True} if name == 'read_file' else original(name, args)
        self.apply(runner, 'read_file', path=NEW)
        self.assertNotIn(NEW, runner.read)
        self.assertNotIn(NEW, runner._migration_full_reads)
        with self.assertRaises(ValueError):
            self.apply(runner, 'write_file', path=NEW, content=CLEAN)

    def test_baseline_migrations_and_aliases_are_always_immutable(self):
        runner = self.runner()
        self.apply(runner, 'read_file', path=FIRST)
        aliases = (FIRST, 'backend/src/main/resources/db/./migration/V1__create_records.sql')
        for path in aliases:
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.apply(runner, 'write_file', path=path, content=CLEAN)
        self.assertEqual((self.app / FIRST).read_text(), 'CREATE TABLE receipts(reference TEXT);\n')

    def test_next_job_locks_the_previous_jobs_new_migration(self):
        self.create(self.runner())
        following = self.runner()
        self.apply(following, 'read_file', path=NEW)
        with self.assertRaisesRegex(ValueError, 'Job-start Flyway'):
            self.apply(following, 'write_file', path=NEW, content=CLEAN)

    def test_next_job_can_edit_approved_unpublished_migration_with_live_proof(self):
        self.create(self.runner())
        policy = self.root / 'platform/acceptance/policies/receipt-create-v1.json'
        data = json.loads(policy.read_text())
        data['prior_unpublished_migrations'] = {NEW: hashlib.sha256(SEEDED.encode()).hexdigest()}
        policy.write_text(json.dumps(data))
        with patch.object(workflow_policy, 'live_applied_migration_versions', return_value=frozenset({'1'})):
            following = self.runner()
        self.apply(following, 'read_file', path=NEW)
        self.apply(following, 'write_file', path=NEW, content=CLEAN)
        following.cp.commit()
        self.assertEqual((self.app / NEW).read_text(), CLEAN)

    def test_shared_checker_and_legacy_profiles_keep_the_previous_lock(self):
        for changes in ({'scope': 'shared'}, {'profile': 'legacy'}):
            with self.subTest(changes=changes):
                path = self.app / NEW
                path.unlink(missing_ok=True)
                runner = self.runner(**changes)
                self.assertIsNone(runner._job_migrations)
                self.create(runner)
                self.apply(runner, 'read_file', path=NEW)
                with self.assertRaisesRegex(ValueError, 'existing Flyway migrations'):
                    self.apply(runner, 'write_file', path=NEW, content=CLEAN)

    def test_failed_edit_rollback_retains_the_previous_accepted_ownership(self):
        runner = self.runner()
        self.create(runner)
        self.apply(runner, 'read_file', path=NEW)
        self.apply(runner, 'write_file', path=NEW, content='BROKEN SQL\n')
        runner.cp.rollback()
        self.assertEqual((self.app / NEW).read_text(), SEEDED)
        self.apply(runner, 'read_file', path=NEW)
        self.apply(runner, 'write_file', path=NEW, content=CLEAN)

    def test_rolled_back_creation_cannot_authorize_an_external_replacement(self):
        runner = self.runner()
        self.apply(runner, 'write_file', path=NEW, content=SEEDED)
        runner.cp.rollback()
        self.assertFalse((self.app / NEW).exists())
        (self.app / NEW).write_text(SEEDED)
        self.apply(runner, 'read_file', path=NEW)
        with self.assertRaisesRegex(ValueError, 'model-created'):
            self.apply(runner, 'write_file', path=NEW, content=CLEAN)

    def test_external_drift_and_deletion_are_denied(self):
        runner = self.runner()
        self.create(runner)
        self.apply(runner, 'read_file', path=NEW)
        with self.assertRaisesRegex(ValueError, 'never deleted'):
            self.apply(runner, 'delete_file', path=NEW)
        (self.app / NEW).write_text('EXTERNAL SQL\n')
        with self.assertRaisesRegex(ValueError, 'model-created'):
            self.apply(runner, 'write_file', path=NEW, content=CLEAN)

    def test_trusted_policy_primary_snapshot_and_completed_replies_enter_act_phase(self):
        from workflow_progress import ANCHOR
        self.spec['task'] = 'Add registration to POST /api/receipts'
        relative = 'backend/src/main/java/org/example/ReceiptEndpoints.java'
        path = self.app / relative
        path.parent.mkdir(parents=True)
        source = ('package org.example;\nimport org.springframework.web.bind.annotation.*;\n'
                  '@RestController @RequestMapping("/api/receipts") class ReceiptEndpoints {}\n')
        path.write_text(source)
        runner = self.runner()
        runner.steps = [{'kind': 'change', 'title': self.spec['task']}]
        provided, paths = snapshot(runner)
        runner.read.update(paths)
        runner.messages = [{'role': 'user', 'content': provided}]
        tools = [{'type': 'function', 'function': {'name': 'read_file'}}]
        runner.tools = lambda: tools
        captured = []

        def complete(messages, tools):
            captured.append((json.loads(json.dumps(messages)), json.loads(json.dumps(tools))))
            return {'choices': [{'message': {'tool_calls': [{'type': 'function', 'function': {
                'name': 'read_file', 'arguments': json.dumps({'path': relative})}}]}}]}

        runner.h.llm = SimpleNamespace(chat=complete)
        for _ in range(8):
            ask_with_recovery(runner)
        self.assertFalse(any(ANCHOR in str(message) for message in captured[-1][0]))
        ask_with_recovery(runner)
        self.assertTrue(any(ANCHOR in str(message) for message in captured[-1][0]))
        transitions = [data for kind, data in runner.events if kind == 'autonomy.workflow_progress']
        self.assertEqual(len(transitions), 1)
        self.assertEqual(transitions[0]['completed_read_only_responses'], 8)
        self.assertEqual(transitions[0]['primary_source'], relative)
        self.assertTrue(all(sent_tools == tools for _, sent_tools in captured))
        self.assertIn('CURRENT FILE ' + relative + '\n' + source, captured[-1][0][0]['content'])
        self.assertEqual(runner.read, {relative})
        self.assertEqual(path.read_text(), source)
        runner.accepted = True
        ask_with_recovery(runner)
        self.assertIn('repair and verification feedback take precedence', captured[-1][0][-1]['content'])
        self.assertEqual(len([1 for kind, _ in runner.events if kind == 'autonomy.workflow_progress']), 1)


if __name__ == '__main__':
    unittest.main()
