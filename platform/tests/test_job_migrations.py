"""Same-job unpublished migration edits, using real temporary checkpoints."""
import hashlib
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'local-only/harness'))
from checkpoints import Checkpoint
from job_migrations import JobMigrationProvenance
from test_autonomy import native


PREFIX = 'backend/src/main/resources/db/migration/'
BASE = PREFIX + 'V1__foundation.sql'
NEW = PREFIX + 'V2__new_constraint.sql'
INITIAL = b'CREATE TABLE widgets (id BIGINT PRIMARY KEY);\n'
ADDITION = b'ALTER TABLE widgets ADD CONSTRAINT widgets_id_unique UNIQUE (id);\n'
REVISED = b'ALTER TABLE widgets ADD COLUMN note TEXT;\n'


def sha(data):
    return hashlib.sha256(data).hexdigest()


class JobMigrationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.workspace = native.WorkspaceManager(self.root)
        self.put(BASE, INITIAL)
        self.ledger = JobMigrationProvenance.capture(self.workspace, True, True)
        self.cp = self.ledger.wrap_checkpoint(Checkpoint(self.workspace))

    def put(self, path, data):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return target

    def write(self, path, data, *, operation='write_file'):
        target = self.root / path
        before = target.read_bytes() if target.exists() else None
        if before is not None:
            self.ledger.require_edit(path, before, sha(before), operation)
        self.cp.stage(path)
        self.put(path, data)
        self.cp.record(path)
        self.ledger.record_write(path, before, data)

    def create(self, *, commit=False):
        self.write(NEW, ADDITION)
        if commit:
            self.cp.commit()

    def allowed(self, path=NEW, operation='write_file'):
        data = (self.root / path).read_bytes()
        self.ledger.require_edit(path, data, sha(data), operation)

    def test_own_new_migration_can_be_read_and_corrected_before_first_commit(self):
        self.create()
        self.write(NEW, REVISED, operation='edit_file')
        self.assertEqual((self.root / NEW).read_bytes(), REVISED)
        self.allowed()
        self.assertEqual(self.cp._records[NEW]['before'], None)

    def test_commit_retains_job_ownership_after_checkpoint_records_are_cleared(self):
        self.create(commit=True)
        self.assertFalse(self.cp.pending)
        self.assertEqual(self.cp._records, {})
        self.write(NEW, REVISED)
        self.cp.commit()
        self.allowed(operation='edit_file')

    def test_failed_revision_rollback_restores_accepted_bytes_and_edit_authority(self):
        self.create(commit=True)
        self.write(NEW, REVISED)
        self.assertEqual(self.cp.rollback(), [NEW])
        self.assertEqual((self.root / NEW).read_bytes(), ADDITION)
        self.write(NEW, REVISED, operation='edit_file')
        self.cp.commit()
        self.allowed()

    def test_multiple_pending_revisions_rollback_to_last_accepted_state(self):
        self.create(commit=True)
        self.write(NEW, REVISED)
        self.write(NEW, REVISED + b'-- second draft\n')
        self.cp.rollback()
        self.assertEqual((self.root / NEW).read_bytes(), ADDITION)
        self.allowed()

    def test_failed_tool_without_success_record_can_rollback_an_accepted_migration(self):
        self.create(commit=True)
        self.allowed()
        self.cp.stage(NEW)
        self.put(NEW, REVISED)
        self.cp.record(NEW)
        # Simulate a tool returning an error: successful-write hook is skipped.
        self.cp.rollback()
        self.assertEqual((self.root / NEW).read_bytes(), ADDITION)
        self.allowed()

    def test_new_creation_rollback_removes_file_and_phantom_authority(self):
        self.create()
        self.write(NEW, REVISED)
        self.cp.rollback()
        self.assertFalse((self.root / NEW).exists())
        self.put(NEW, ADDITION)  # A later external creation has no model provenance.
        with self.assertRaises(ValueError):
            self.allowed()

    def test_model_can_create_again_after_its_new_creation_was_rolled_back(self):
        self.create()
        self.cp.rollback()
        self.create(commit=True)
        self.allowed()

    def test_following_job_treats_previously_owned_migration_as_immutable_baseline(self):
        self.create(commit=True)
        following = JobMigrationProvenance.capture(self.workspace, True, True)
        with self.assertRaises(ValueError):
            following.require_edit(NEW, ADDITION, sha(ADDITION), 'edit_file')

    def test_following_job_can_revise_exact_approved_unpublished_migration(self):
        self.create(commit=True)
        following = JobMigrationProvenance.capture(self.workspace, True, True, {NEW: sha(ADDITION)})
        checkpoint = following.wrap_checkpoint(Checkpoint(self.workspace))
        following.require_edit(NEW, ADDITION, sha(ADDITION), 'edit_file')
        checkpoint.stage(NEW)
        self.put(NEW, REVISED)
        checkpoint.record(NEW)
        following.record_write(NEW, ADDITION, REVISED)
        checkpoint.commit()
        self.assertEqual((self.root / NEW).read_bytes(), REVISED)
        with self.assertRaises(ValueError):
            following.require_edit(BASE, INITIAL, sha(INITIAL), 'edit_file')

    def test_prior_authority_rejects_wrong_sha_and_foundation_inode_alias(self):
        with self.assertRaises(ValueError):
            JobMigrationProvenance.capture(self.workspace, True, True, {BASE: sha(REVISED)})
        self.create(commit=True)
        with self.assertRaises(ValueError):
            JobMigrationProvenance.capture(self.workspace, True, True, {NEW: sha(REVISED)})
        following = JobMigrationProvenance.capture(self.workspace, True, True, {NEW: sha(ADDITION)})
        (self.root / NEW).unlink()
        (self.root / BASE).rename(self.root / NEW)
        with self.assertRaises(ValueError):
            following.require_edit(NEW, INITIAL, sha(INITIAL), 'edit_file')

    def test_prior_owned_inode_cannot_be_renamed_into_a_new_migration(self):
        self.create(commit=True)
        following = JobMigrationProvenance.capture(self.workspace, True, True, {NEW: sha(ADDITION)})
        renamed = PREFIX + 'V3__moved.sql'
        (self.root / NEW).rename(self.root / renamed)
        with self.assertRaises(ValueError):
            following.record_write(renamed, None, ADDITION)

    def test_every_job_start_migration_is_immutable_even_after_deletion_and_recreation(self):
        for operation in ('write_file', 'edit_file', 'delete_file'):
            with self.subTest(operation=operation), self.assertRaises(ValueError):
                self.ledger.require_edit(BASE, INITIAL, sha(INITIAL), operation)
        (self.root / BASE).unlink()
        self.put(BASE, REVISED)
        with self.assertRaises(ValueError):
            self.ledger.record_write(BASE, None, REVISED)

    def test_renamed_baseline_inode_cannot_be_promoted_as_a_new_migration(self):
        (self.root / BASE).rename(self.root / NEW)
        with self.assertRaises(ValueError):
            self.ledger.record_write(NEW, None, INITIAL)

    def test_default_shared_unknown_and_truthy_nonboolean_capabilities_do_not_enable(self):
        for enabled, fresh in [(False, True), (True, False), (True, None),
                               (True, 'fresh-owned'), ('true', True), (1, True), (True, 1)]:
            with self.subTest(enabled=enabled, fresh=fresh):
                ledger = JobMigrationProvenance.capture(self.workspace, enabled, fresh)
                self.assertFalse(ledger.enabled)
                self.put(NEW, ADDITION)
                ledger.record_write(NEW, None, ADDITION)
                with self.assertRaises(ValueError):
                    ledger.require_edit(NEW, ADDITION, sha(ADDITION), 'write_file')
        default = JobMigrationProvenance.capture(self.workspace)
        self.assertFalse(default.enabled)

    def test_external_new_file_is_not_owned_even_if_read_with_matching_sha(self):
        self.put(NEW, ADDITION)
        with self.assertRaises(ValueError):
            self.allowed()
        self.put(NEW, REVISED)
        with self.assertRaises(ValueError):
            self.ledger.record_write(NEW, ADDITION, REVISED)

    def test_complete_read_sha_and_current_bytes_are_both_required(self):
        self.create(commit=True)
        cases = [(ADDITION, None), (ADDITION, sha(INITIAL)), (ADDITION[:12], sha(ADDITION[:12])),
                 (ADDITION.decode(), sha(ADDITION))]
        for data, read_sha in cases:
            with self.subTest(data=data, read_sha=read_sha), self.assertRaises(ValueError):
                self.ledger.require_edit(NEW, data, read_sha, 'edit_file')
        self.allowed()  # Stale read proof does not destroy otherwise valid ownership.

    def test_current_hash_drift_revokes_ownership_and_old_bytes_do_not_resurrect_it(self):
        self.create(commit=True)
        self.put(NEW, REVISED)
        with self.assertRaises(ValueError):
            self.ledger.require_edit(NEW, ADDITION, sha(ADDITION), 'write_file')
        self.put(NEW, ADDITION)
        with self.assertRaises(ValueError):
            self.allowed()

    def test_recreated_same_bytes_with_different_inode_is_not_owned(self):
        self.create(commit=True)
        replacement = self.put(NEW + '.replacement', ADDITION)
        os.replace(replacement, self.root / NEW)
        with self.assertRaises(ValueError):
            self.allowed()

    def test_existing_write_must_have_require_edit_authorization(self):
        self.create(commit=True)
        self.put(NEW, REVISED)
        with self.assertRaises(ValueError):
            self.ledger.record_write(NEW, ADDITION, REVISED)

    def test_successful_write_bytes_must_match_actual_regular_file(self):
        self.put(NEW, REVISED)
        with self.assertRaises(ValueError):
            self.ledger.record_write(NEW, None, ADDITION)
        with self.assertRaises(ValueError):
            self.ledger.record_write(NEW, None, None)

    def test_delete_and_unrecognized_operations_remain_forbidden(self):
        self.create(commit=True)
        for operation in ('delete_file', 'insert_text', 'apply_edits', '', None):
            with self.subTest(operation=operation), self.assertRaises(ValueError):
                self.allowed(operation=operation)

    def test_noncanonical_absolute_outside_and_nonmigration_paths_are_rejected(self):
        self.create(commit=True)
        for path in ('./' + NEW, NEW.replace('/V2', '/../migration/V2'),
                     str(self.root / NEW), '../outside.sql', NEW.replace('/', '\\'),
                     NEW.replace('/V2', '//V2'), 'backend/other.sql'):
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.ledger.require_edit(path, ADDITION, sha(ADDITION), 'write_file')

    def test_file_and_ancestor_symlinks_are_rejected(self):
        self.create(commit=True)
        alias = self.root / (PREFIX + 'V3__alias.sql')
        alias.symlink_to(self.root / NEW)
        with self.assertRaises(ValueError):
            self.ledger.record_write(str(alias.relative_to(self.root)), None, ADDITION)
        with self.assertRaises(ValueError):
            JobMigrationProvenance.capture(self.workspace, True, True)
        alias.unlink()
        linked = self.root / PREFIX / 'linked'
        linked.symlink_to(self.root / PREFIX, target_is_directory=True)
        with self.assertRaises(ValueError):
            self.ledger.record_write(PREFIX + 'linked/V2__new_constraint.sql', None, ADDITION)

    def test_hardlink_aliases_cannot_gain_or_retain_authority(self):
        self.create(commit=True)
        alias = self.root / (PREFIX + 'V3__alias.sql')
        os.link(self.root / NEW, alias)
        with self.assertRaises(ValueError):
            self.ledger.record_write(str(alias.relative_to(self.root)), None, ADDITION)
        with self.assertRaises(ValueError):
            self.allowed()

    def test_rollback_conflict_preserves_external_bytes_and_revokes_pending_authority(self):
        self.create(commit=True)
        self.write(NEW, REVISED)
        self.put(NEW, b'-- concurrent external change\n')
        with self.assertRaises(RuntimeError):
            self.cp.rollback()
        self.assertEqual((self.root / NEW).read_bytes(), b'-- concurrent external change\n')
        self.put(NEW, ADDITION)
        with self.assertRaises(ValueError):
            self.allowed()

    def test_commit_drift_is_rejected_before_checkpoint_records_are_cleared(self):
        self.create()
        self.put(NEW, REVISED)
        with self.assertRaises(ValueError):
            self.cp.commit()
        self.assertTrue(self.cp.pending)
        with self.assertRaises(ValueError):
            self.allowed()

    def test_proxy_preserves_nonmigration_checkpoint_behavior_and_unrelated_owned_files(self):
        self.create(commit=True)
        other = 'backend/src/main/java/example/Widget.java'
        self.cp.stage(other)
        self.put(other, b'class Widget {}')
        self.cp.record(other)
        self.ledger.record_write(other, None, b'class Widget {}')
        self.assertTrue(self.cp.pending)
        self.assertEqual(self.cp.rollback(), [other])
        self.assertFalse((self.root / other).exists())
        self.allowed()
        self.assertIs(self.ledger.wrap_checkpoint(self.cp), self.cp)

    def test_other_workspace_checkpoint_cannot_be_wrapped(self):
        with tempfile.TemporaryDirectory() as other:
            with self.assertRaises(ValueError):
                self.ledger.wrap_checkpoint(Checkpoint(native.WorkspaceManager(other)))

    def test_checker_capability_matches_actual_isolated_backend_dispatch(self):
        checker = native.Checker(self.workspace)
        self.assertEqual(checker.schema_application_scope, 'fresh-owned')
        result = {'success': True, 'fixture': 'no real DB'}
        with patch('isolated_backend.run_backend', return_value=result) as run_backend:
            self.assertIs(checker.run_check('backend'), result)
        run_backend.assert_called_once_with(checker, checker._check_backend_unisolated)


if __name__ == '__main__':
    unittest.main()
