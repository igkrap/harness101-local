"""Derive exact SQL pins from approved lineage before a backend trial starts."""
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import item_crud_trial


class UnpublishedMigrationStageTests(unittest.TestCase):
    def test_policy_pin_is_derived_from_owned_migration_and_backend_scope(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            policy = root / 'platform/acceptance/policies/example-v1.json'
            name = 'backend/src/main/resources/db/migration/V6__items.sql'
            pin = {name: 'a' * 64}
            ownership = SimpleNamespace(unpublished_migrations=pin)
            stage = {'allow_unpublished_migrations': True, 'checks': ['backend']}
            with patch.object(item_crud_trial, 'ROOT', root):
                item_crud_trial.check_unpublished_migration_policy(
                    stage, ownership, lambda _: True, 'example-v1', 'b' * 64)
                self.assertEqual(json.loads(policy.read_text())['prior_unpublished_migrations'], pin)
                with self.assertRaisesRegex(ValueError, 'backend-only'):
                    item_crud_trial.check_unpublished_migration_policy(
                        {**stage, 'checks': ['backend', 'frontend']}, ownership,
                        lambda _: True, 'example-v1', 'b' * 64)
                data = json.loads(policy.read_text())
                data['prior_unpublished_migrations'] = {name: 'c' * 64}
                policy.write_text(json.dumps(data))
                item_crud_trial.check_unpublished_migration_policy(
                    stage, ownership, lambda _: True, 'example-v1', 'b' * 64)
                self.assertEqual(json.loads(policy.read_text())['prior_unpublished_migrations'], pin)
                with self.assertRaisesRegex(ValueError, 'No approved unpublished'):
                    item_crud_trial.check_unpublished_migration_policy(
                        stage, ownership, lambda _: False, 'example-v1', 'b' * 64)
                data = json.loads(policy.read_text())
                data['script_sha256'] = 'c' * 64
                policy.write_text(json.dumps(data))
                with self.assertRaisesRegex(ValueError, 'policy is invalid'):
                    item_crud_trial.check_unpublished_migration_policy(
                        stage, ownership, lambda _: True, 'example-v1', 'b' * 64)
                policy.write_text('{"version":1,"version":1}')
                with self.assertRaisesRegex(ValueError, 'Duplicate'):
                    item_crud_trial.check_unpublished_migration_policy(
                        stage, ownership, lambda _: True, 'example-v1', 'b' * 64)


if __name__ == '__main__':
    unittest.main()
