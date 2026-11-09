"""Approved artifact lineage, foundation boundaries and immutable launch captures."""
import base64
from dataclasses import FrozenInstanceError
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from source_ownership import ApprovedSuccess, OwnershipError, capture_owned_sources


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


class SourceOwnershipTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.app = self.root / 'app'
        self.foundation = {'frontend/package.json': b'{}', 'frontend/src/framework/index.ts': b'framework',
                           'backend/src/main/java/foundation/Base.java': b'foundation'}
        self.screen = 'frontend/src/screens/Composer.tsx'
        self.java = 'backend/src/main/java/catalog/OddEndpoint.java'
        self.sql = 'backend/src/main/resources/db/migration/V8_2__catalog.sql'
        self.after_layout = {**self.foundation, self.screen: b'local screen'}
        self.current = {**self.after_layout, self.java: b'local query API', self.sql: b'CREATE TABLE catalog();'}
        self.layout = self.artifact('layout', self.foundation, {self.screen: self.after_layout[self.screen]})
        self.api = self.artifact('api', self.after_layout, {self.java: self.current[self.java], self.sql: self.current[self.sql]})
        self.approved = (ApprovedSuccess.pin(self.layout), ApprovedSuccess.pin(self.api))
        self.write_sources(self.current)

    def write_sources(self, sources):
        for path, raw in sources.items():
            file = self.app / path
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(raw)

    def artifact(self, label, before, generated):
        folder = self.root / 'evidence' / label
        folder.mkdir(parents=True, exist_ok=True)
        config = {'id': 'local-config', 'model': 'local/example-model', 'url': 'http://127.0.0.1:1/v1'}
        manifest = {'model_config': config, 'launched_model': {'model_config': config, 'model': config['model'], 'llm_url': config['url']},
                    'request': {'kind': 'agent', 'model': 'config:' + config['id']},
                    'sources_before': {path: sha(raw) for path, raw in before.items()}, 'manual_interventions_after_start': 0}
        result = {key: True for key in ('success', 'candidate_retained', 'workspace_verified', 'cleanup_ok', 'scope_respected',
                  'frozen_unchanged', 'sources_stable_during_final_checks', 'build_passed', 'browser_passed', 'prior_state_restored', 'result_written')}
        result.update(status='succeeded', evidence=str(folder), baseline_restored=False, restore_errors=[], evidence_errors=[],
                      job_id='job-' + label, model=config['model'], model_config_id=config['id'], model_calls=1,
                      manual_interventions_after_start=0, changed_paths=list(generated), oracle_cases=['fixed-case'],
                      oracle_cleanup={'success': True}, isolated_runtime_cleanup=[],
                      cleanup_job={'job_id': 'job-' + label, 'status': 'succeeded', 'safe_to_restore': True, 'process_or_group_alive': False})
        for name, data in [('manifest.json', manifest), ('result.json', result),
                           ('restore-snapshot.json', {path: base64.b64encode(raw).decode() for path, raw in before.items()}),
                           ('generated-sources.json', {path: base64.b64encode(raw).decode() for path, raw in generated.items()})]:
            (folder / name).write_text(json.dumps(data))
        return folder

    def mutate(self, folder, name, action):
        file = folder / name
        data = json.loads(file.read_text())
        action(data)
        file.write_text(json.dumps(data))

    def capture(self, sources=None, approvals=None, applied_migration_versions=None):
        return capture_owned_sources(self.app, self.current if sources is None else sources,
                                     self.approved if approvals is None else approvals,
                                     applied_migration_versions=applied_migration_versions)

    def test_capture_grants_only_created_code_and_excludes_foundation_and_old_migration(self):
        snapshot = self.capture()
        self.assertEqual(snapshot.editable_existing, frozenset((self.screen, self.java)))
        self.assertEqual(dict(snapshot.expected_sha256), {self.screen: sha(self.current[self.screen]), self.java: sha(self.current[self.java])})
        for path in (*self.foundation, self.sql, './' + self.java, '../' + self.java):
            self.assertFalse(snapshot.allows_existing(path))
        self.assertEqual(snapshot.foundation_file_count, 3)
        self.assertEqual(snapshot.source_file_count, 6)
        self.assertEqual(len(snapshot.to_manifest()['approved_successes']), 2)

    def test_following_verified_edit_updates_ownership_and_adds_helpers_without_names(self):
        helper = 'frontend/src/features/catalog/useRemote.ts'
        generated = {self.screen: b'connected screen', helper: b'local helper'}
        ui = self.artifact('ui', self.current, generated)
        current = {**self.current, **generated}
        self.write_sources(current)
        snapshot = self.capture(current, (*self.approved, ApprovedSuccess.pin(ui)))
        self.assertTrue(snapshot.allows_existing(helper))
        self.assertEqual(snapshot.expected_sha256[self.screen], sha(b'connected screen'))

    def test_capture_and_manifest_are_independent_of_later_inputs_and_metadata(self):
        sources = dict(self.current)
        approvals = list(self.approved)
        snapshot = self.capture(sources, approvals)
        manifest = snapshot.to_manifest()
        sources[self.java] = b'changed caller data'
        approvals.clear()
        self.mutate(self.api, 'result.json', lambda data: data.update(success=False))
        manifest['editable_existing'].clear()
        manifest['expected_sha256'][self.java] = 'tampered output'
        self.assertTrue(snapshot.allows_existing(self.java))
        self.assertEqual(snapshot.expected_sha256[self.java], sha(self.current[self.java]))
        self.assertEqual(len(snapshot.provenance), 2)
        with self.assertRaises(TypeError):
            snapshot.expected_sha256[self.java] = 'mutation'
        with self.assertRaises(FrozenInstanceError):
            snapshot.editable_existing = frozenset()
        with self.assertRaisesRegex(OwnershipError, 'SHA pin changed'):
            self.capture()

    def test_failed_intervened_or_incompletely_restored_artifacts_do_not_grant_ownership(self):
        result_file = self.api / 'result.json'
        original = result_file.read_bytes()
        for changes in ({'success': False}, {'status': 'stopped'}, {'candidate_retained': False}, {'cleanup_ok': False},
                        {'frozen_unchanged': False}, {'manual_interventions_after_start': 1}, {'model_calls': 0},
                        {'baseline_restored': True}, {'scope_respected': False}):
            with self.subTest(changes=changes):
                result_file.write_bytes(original)
                self.mutate(self.api, 'result.json', lambda data: data.update(changes))
                with self.assertRaises(OwnershipError):
                    self.capture(approvals=(self.approved[0], ApprovedSuccess.pin(self.api)))
        result_file.write_bytes(original)

    def test_model_identity_and_restoration_snapshot_hash_must_match(self):
        original = (self.api / 'manifest.json').read_bytes()
        for action in (lambda data: data['model_config'].update(id='other'),
                       lambda data: data['sources_before'].update({self.screen: '0' * 64})):
            (self.api / 'manifest.json').write_bytes(original)
            self.mutate(self.api, 'manifest.json', action)
            with self.assertRaises(OwnershipError):
                self.capture(approvals=(self.approved[0], ApprovedSuccess.pin(self.api)))

    def test_complete_before_chain_and_current_baseline_must_match(self):
        changed_before = {**self.after_layout, self.screen: b'out-of-band change'}
        other = self.artifact('other-api', changed_before, {self.java: self.current[self.java], self.sql: self.current[self.sql]})
        with self.assertRaisesRegex(OwnershipError, 'before-source chain'):
            self.capture(approvals=(self.approved[0], ApprovedSuccess.pin(other)))
        for sources in ({**self.current, self.java: b'changed'},
                        {path: raw for path, raw in self.current.items() if path != self.java},
                        {**self.current, 'frontend/src/Extra.ts': b'extra'}):
            with self.assertRaisesRegex(OwnershipError, 'Launch baseline'):
                self.capture(sources)

    def test_live_files_cannot_drift_or_hide_unlisted_sources_after_the_snapshot(self):
        (self.app / self.java).write_bytes(b'not the launch bytes')
        with self.assertRaisesRegex(OwnershipError, 'Launch baseline'):
            self.capture()
        (self.app / self.java).write_bytes(self.current[self.java])
        extra = self.app / 'frontend/src/Extra.ts'
        extra.write_bytes(b'unlisted extra source')
        with self.assertRaisesRegex(OwnershipError, 'Launch baseline'):
            self.capture()

    def test_foundation_modification_cannot_be_promoted_by_success_flags(self):
        path = next(path for path in self.foundation if path.endswith('.java'))
        generated = {path: b'changed foundation'}
        fake = self.artifact('promote', self.current, generated)
        current = {**self.current, **generated}
        self.write_sources(current)
        with self.assertRaisesRegex(OwnershipError, 'Foundation'):
            self.capture(current, (*self.approved, ApprovedSuccess.pin(fake)))

    def test_model_created_migration_is_still_immutable_but_new_migration_is_not_editable(self):
        changed = self.artifact('rewrite-migration', self.current, {self.sql: b'ALTER old migration;'} )
        with self.assertRaises(OwnershipError):
            self.capture(approvals=(*self.approved, ApprovedSuccess.pin(changed)))
        new_path = 'backend/src/main/resources/db/migration/V9__more.sql'
        generated = {new_path: b'ALTER TABLE catalog ADD COLUMN extra TEXT;'}
        added = self.artifact('add-migration', self.current, generated)
        current = {**self.current, **generated}
        self.write_sources(current)
        snapshot = self.capture(current, (*self.approved, ApprovedSuccess.pin(added)))
        self.assertFalse(snapshot.allows_existing(self.sql))
        self.assertFalse(snapshot.allows_existing(new_path))

    def test_unpublished_owned_migration_editable_only_with_live_applied_version_proof(self):
        unpublished = self.capture(applied_migration_versions={'1', '2', '5'})
        self.assertTrue(unpublished.allows_existing(self.sql))
        self.assertEqual(unpublished.unpublished_migrations[self.sql], sha(self.current[self.sql]))
        self.assertFalse(self.capture(applied_migration_versions={'8.2'}).allows_existing(self.sql))
        self.assertFalse(self.capture().allows_existing(self.sql))
        self.assertFalse(unpublished.allows_existing('backend/src/main/resources/db/migration/V1__foundation.sql'))
        with self.assertRaisesRegex(OwnershipError, 'trusted live database'):
            self.capture(applied_migration_versions=['1'])

    def test_verified_revision_of_unpublished_migration_remains_owned(self):
        revised = b'CREATE TABLE catalog(id BIGINT PRIMARY KEY);'
        change = self.artifact('revise-sql', self.current, {self.sql: revised})
        current = {**self.current, self.sql: revised}
        self.write_sources(current)
        approved = (*self.approved, ApprovedSuccess.pin(change))
        snapshot = self.capture(current, approved, applied_migration_versions={'1'})
        self.assertEqual(snapshot.expected_sha256[self.sql], sha(revised))
        published = self.capture(current, approved, applied_migration_versions={'8.2'})
        self.assertFalse(published.allows_existing(self.sql))

    def test_deletion_noop_bad_base64_and_duplicate_paths_are_rejected(self):
        name = self.api / 'result.json'
        original = name.read_bytes()
        for changes in ({'changed_paths': [self.java, self.sql, self.screen]},
                        {'changed_paths': [self.java, self.java, self.sql]}):
            name.write_bytes(original)
            self.mutate(self.api, 'result.json', lambda data: data.update(changes))
            with self.assertRaisesRegex(OwnershipError, 'Changed/generated'):
                self.capture(approvals=(self.approved[0], ApprovedSuccess.pin(self.api)))
        name.write_bytes(original)
        self.mutate(self.api, 'generated-sources.json', lambda data: data.update({self.java: 'not base64?!'}))
        with self.assertRaisesRegex(OwnershipError, 'base64'):
            self.capture(approvals=(self.approved[0], ApprovedSuccess.pin(self.api)))

    def test_noncanonical_and_escaping_source_paths_are_rejected(self):
        original = (self.api / 'generated-sources.json').read_bytes()
        for path in ('../outside.java', '/backend/src/Fake.java', 'backend/src/../Fake.java',
                     'backend/src//Fake.java', 'backend/src/./Fake.java', 'backend\\src\\Fake.java'):
            with self.subTest(path=path):
                (self.api / 'generated-sources.json').write_bytes(original)
                self.mutate(self.api, 'generated-sources.json', lambda data: data.update({path: base64.b64encode(b'fake').decode()}))
                with self.assertRaises(OwnershipError):
                    self.capture(approvals=(self.approved[0], ApprovedSuccess.pin(self.api)))

    def test_source_and_artifact_symlinks_cannot_supply_provenance(self):
        alias = self.root / 'alias'
        alias.symlink_to(self.api, target_is_directory=True)
        with self.assertRaisesRegex(OwnershipError, 'Symlink'):
            ApprovedSuccess.pin(alias)
        result = self.api / 'result.json'
        saved = self.api / 'saved.json'
        result.rename(saved)
        result.symlink_to(saved)
        with self.assertRaisesRegex(OwnershipError, 'Symlink'):
            ApprovedSuccess.pin(self.api)
        result.unlink()
        saved.rename(result)
        target = self.app / self.java
        saved = target.with_name('saved.java')
        target.rename(saved)
        target.symlink_to(saved)
        with self.assertRaisesRegex(OwnershipError, 'Symlink'):
            self.capture()

    def test_duplicate_json_keys_and_duplicate_approved_jobs_are_rejected(self):
        with self.assertRaisesRegex(OwnershipError, 'Duplicate successful job'):
            self.capture(approvals=(self.approved[0], self.approved[0], self.approved[1]))
        (self.api / 'result.json').write_text('{"success":true,"success":false}')
        with self.assertRaisesRegex(OwnershipError, 'Duplicate JSON key'):
            self.capture(approvals=(self.approved[0], ApprovedSuccess.pin(self.api)))

    def test_noop_generated_content_cannot_claim_a_new_verified_revision(self):
        noop = self.artifact('noop', self.current, {self.screen: self.current[self.screen]})
        with self.assertRaisesRegex(OwnershipError, 'no-op'):
            self.capture(approvals=(*self.approved, ApprovedSuccess.pin(noop)))

    def test_capture_copies_nested_approval_pins_and_exposes_no_metadata_dependencies(self):
        mutable_pins = list(self.approved[1].metadata_sha256)
        record = ApprovedSuccess(self.api, mutable_pins)
        snapshot = self.capture(approvals=(self.approved[0], record))
        mutable_pins.clear()
        self.assertEqual(len(snapshot.provenance[1].metadata_sha256), 4)
        self.assertEqual(len(snapshot.to_manifest()['approved_successes'][1]['metadata_sha256']), 4)
        self.assertTrue(snapshot.allows_existing(self.java))

    def test_missing_or_contradictory_cleanup_and_model_schema_are_rejected(self):
        original_result = (self.api / 'result.json').read_bytes()
        for changes in ({'cleanup_job': None}, {'oracle_cleanup': None}, {'isolated_runtime_cleanup': {}},
                        {'oracle_cleanup': {'success': True, 'errors': ['not actually cleaned']}}):
            (self.api / 'result.json').write_bytes(original_result)
            self.mutate(self.api, 'result.json', lambda data: data.update(changes))
            with self.assertRaises(OwnershipError):
                self.capture(approvals=(self.approved[0], ApprovedSuccess.pin(self.api)))
        (self.api / 'result.json').write_bytes(original_result)
        self.mutate(self.api, 'manifest.json', lambda data: data.update(model_config=None))
        with self.assertRaises(OwnershipError):
            self.capture(approvals=(self.approved[0], ApprovedSuccess.pin(self.api)))


if __name__ == '__main__':
    unittest.main()
