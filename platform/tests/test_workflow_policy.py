"""Exercise trusted policy capture without constructing an application harness."""
from dataclasses import FrozenInstanceError
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'local-only/harness'))
import fixed_acceptance
import workflow_policy


class WorkflowPolicyTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.tests = self.root / 'platform/tests'
        self.tests.mkdir(parents=True)
        self.workspace = self.root / 'project'
        self.workspace.mkdir()
        self.script = self.tests / 'workflow.cjs'
        self.script.write_text('// repository-owned verifier fixture')
        self.spec = {'id': 'receipt-create-v1', 'task': 'Add record creation',
                     'project_root': str(self.workspace), 'script': str(self.script),
                     'script_sha256': hashlib.sha256(self.script.read_bytes()).hexdigest(),
                     'cases': ['persist-record']}
        self.path = self.root / 'platform/acceptance/policies/receipt-create-v1.json'
        self.path.parent.mkdir(parents=True)
        self.data = {'version': 1, 'acceptance_id': self.spec['id'],
                     'script_sha256': self.spec['script_sha256'], 'database_scope': 'fresh-owned',
                     'job_created_migration_edits': True, 'fixture_owner': 'checker',
                     'discovery_round_limit': 8}
        self.write()
        self.patcher = patch.object(fixed_acceptance, 'CHECKS_ROOT', self.tests)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def write(self, data=None):
        self.path.write_text(json.dumps(self.data if data is None else data))

    def runner(self, *, profile='focused', modes=('backend',), scope='fresh-owned', spec=None):
        return SimpleNamespace(args=SimpleNamespace(context_profile=profile,
                              task=self.spec['task'], fixed_acceptance=dict(self.spec) if spec is None else spec),
                               modes=list(modes), h=SimpleNamespace(
                                   workspace=SimpleNamespace(root=self.workspace),
                                   checker=SimpleNamespace(schema_application_scope=scope)))

    def test_valid_capabilities_are_bound_to_repository_oracle_and_immutable(self):
        policy = workflow_policy.get_policy(self.runner())
        self.assertTrue(policy.enabled)
        self.assertTrue(policy.job_created_migration_edits)
        self.assertEqual((policy.fixture_owner, policy.discovery_round_limit), ('checker', 8))
        self.assertEqual(policy.authority.policy_sha256, hashlib.sha256(self.path.read_bytes()).hexdigest())
        with self.assertRaises(FrozenInstanceError):
            policy.fixture_owner = 'legacy'
        with self.assertRaises(FrozenInstanceError):
            policy.authority.acceptance_id = 'another-task'
        exported = policy.to_manifest()
        exported['authority']['policy_sha256'] = 'changed'
        self.assertNotEqual(policy.authority.policy_sha256, 'changed')

    def test_prior_migration_requires_pin_and_live_unapplied_version(self):
        path = 'backend/src/main/resources/db/migration/V6__create_records.sql'
        self.write({**self.data, 'prior_unpublished_migrations': {path: 'a' * 64}})
        with patch.object(workflow_policy, 'live_applied_migration_versions', return_value=frozenset({'1', '5'})):
            policy = workflow_policy.get_policy(self.runner())
        self.assertTrue(policy.enabled)
        self.assertEqual(dict(policy.prior_unpublished_migrations), {path: 'a' * 64})
        with patch.object(workflow_policy, 'live_applied_migration_versions', return_value=frozenset({'6'})):
            self.assertFalse(workflow_policy.get_policy(self.runner()).enabled)
        self.write({**self.data, 'prior_unpublished_migrations': {path: 'wrong'}})
        self.assertFalse(workflow_policy.get_policy(self.runner()).enabled)

    def test_default_legacy_frontend_mixed_and_shared_checkers_are_not_opted_in(self):
        options = ({'profile': 'legacy'}, {'modes': ('frontend',)},
                   {'modes': ('backend', 'frontend')}, {'scope': 'shared'}, {'scope': None})
        for changes in options:
            with self.subTest(changes=changes):
                policy = workflow_policy.get_policy(self.runner(**changes))
                self.assertFalse(policy.enabled)
                self.assertFalse(policy.job_created_migration_edits)
                self.assertEqual(policy.fixture_owner, 'legacy')
                self.assertEqual(policy.discovery_round_limit, 0)

    def test_policy_requires_fixed_acceptance_not_just_a_focused_profile(self):
        runner = self.runner()
        runner.args.fixed_acceptance = None
        self.assertFalse(workflow_policy.get_policy(runner).enabled)

    def test_unknown_or_mismatched_capability_fields_fail_closed(self):
        changes = ({'acceptance_id': 'different-v1'}, {'script_sha256': '0' * 64},
                   {'database_scope': 'shared'}, {'job_created_migration_edits': 'true'},
                   {'fixture_owner': 'unverified'}, {'discovery_round_limit': True},
                   {'discovery_round_limit': -1}, {'discovery_round_limit': 17},
                   {'version': True}, {'unexpected': True})
        for change in changes:
            with self.subTest(change=change):
                self.write({**self.data, **change})
                self.assertFalse(workflow_policy.get_policy(self.runner()).enabled)

    def test_missing_fields_and_duplicate_json_keys_do_not_grant_capabilities(self):
        data = dict(self.data)
        del data['database_scope']
        self.write(data)
        self.assertFalse(workflow_policy.get_policy(self.runner()).enabled)
        text = json.dumps(self.data)
        self.path.write_text(text[:-1] + ', "fixture_owner": "checker"}')
        self.assertFalse(workflow_policy.get_policy(self.runner()).enabled)

    def test_oracle_changed_or_bound_to_another_task_is_rejected(self):
        runner = self.runner()
        runner.args.task = 'another request'
        self.assertFalse(workflow_policy.get_policy(runner).enabled)
        self.script.write_text('// changed repository verifier')
        self.assertFalse(workflow_policy.get_policy(self.runner()).enabled)

    def test_script_inside_model_workspace_cannot_authorize_policy(self):
        script = self.workspace / 'workflow.cjs'
        script.write_text('// model-owned')
        spec = {**self.spec, 'script': str(script),
                'script_sha256': hashlib.sha256(script.read_bytes()).hexdigest()}
        self.write({**self.data, 'script_sha256': spec['script_sha256']})
        self.assertFalse(workflow_policy.get_policy(self.runner(spec=spec)).enabled)

    def test_capture_is_fixed_even_if_policy_is_removed_or_modified(self):
        runner = self.runner()
        captured = workflow_policy.get_policy(runner)
        self.path.unlink()
        self.assertIs(workflow_policy.get_policy(runner), captured)
        self.write({**self.data, 'discovery_round_limit': 3})
        self.assertIs(workflow_policy.get_policy(runner), captured)
        self.assertEqual(captured.discovery_round_limit, 8)

    def test_missing_policy_is_not_activated_mid_job(self):
        self.path.unlink()
        runner = self.runner()
        self.assertFalse(workflow_policy.get_policy(runner).enabled)
        self.write()
        self.assertFalse(workflow_policy.get_policy(runner).enabled)
        self.assertTrue(workflow_policy.get_policy(self.runner()).enabled)

    def test_changed_task_or_checker_cannot_reuse_captured_capabilities(self):
        runner = self.runner()
        self.assertTrue(workflow_policy.get_policy(runner).enabled)
        runner.args.task = 'different task'
        self.assertFalse(workflow_policy.get_policy(runner).enabled)
        runner = self.runner()
        self.assertTrue(workflow_policy.get_policy(runner).enabled)
        runner.h.checker.schema_application_scope = 'shared'
        self.assertFalse(workflow_policy.get_policy(runner).enabled)

    def test_first_disabled_profile_capture_cannot_be_upgraded_mid_job(self):
        for changes in ({'profile': 'legacy'}, {'modes': ('frontend', 'backend')}):
            with self.subTest(changes=changes):
                runner = self.runner(**changes)
                self.assertFalse(workflow_policy.get_policy(runner).enabled)
                runner.args.context_profile = 'focused'
                runner.modes = ['backend']
                self.assertFalse(workflow_policy.get_policy(runner).enabled)

    def test_symlinks_hardlinks_and_oversize_files_are_rejected(self):
        raw = self.path.read_bytes()
        actual = self.path.parent / 'actual.json'
        actual.write_bytes(raw)
        self.path.unlink()
        self.path.symlink_to(actual)
        self.assertFalse(workflow_policy.get_policy(self.runner()).enabled)
        self.path.unlink()
        os.link(actual, self.path)
        self.assertFalse(workflow_policy.get_policy(self.runner()).enabled)
        self.path.unlink()
        self.path.write_bytes(raw + b' ' * 8193)
        self.assertFalse(workflow_policy.get_policy(self.runner()).enabled)

    def test_symlinked_policy_directory_is_not_followed(self):
        raw = self.path.read_bytes()
        self.path.unlink()
        self.path.parent.rmdir()
        outside = self.root / 'external-policy'
        outside.mkdir()
        (outside / self.path.name).write_bytes(raw)
        self.path.parent.symlink_to(outside, target_is_directory=True)
        self.assertFalse(workflow_policy.get_policy(self.runner()).enabled)


if __name__ == '__main__':
    unittest.main()
