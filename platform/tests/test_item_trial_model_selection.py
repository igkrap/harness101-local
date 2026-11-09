"""Mock services and model replies; exercise actual supervisor restoration/locks."""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import item_crud_trial as trial
import item_stage_trial as stages
import trial_safety as safety


def config(identifier='selected', tokens=8192):
    return {'id': identifier, 'name': 'Fixture local model', 'model': 'fixture/' + identifier,
            'url': 'http://127.0.0.1:8123/v1', 'temperature': .2, 'timeout': 600, 'max_tokens': tokens}


class Response(io.StringIO):
    status = 200


class SelectionTests(unittest.TestCase):
    def test_default_and_explicit_selection_never_depend_on_registry_order(self):
        registered = {'default': 'selected', 'models': [config('other'), config()]}
        self.assertEqual(trial.select_model_config(registered, {})['id'], 'selected')
        self.assertEqual(trial.select_model_config(registered, {'model_config': 'other'})['id'], 'other')

    def test_missing_or_stale_default_is_not_replaced_by_an_arbitrary_model(self):
        for registered in ({'models': [config()]}, {'default': 'gone', 'models': [config()]}):
            with self.subTest(registry=registered), self.assertRaises(ValueError):
                trial.select_model_config(registered, {})

    def test_output_budget_is_stage_policy_not_model_identity(self):
        registered = {'default': 'selected', 'models': [config(tokens=4096)]}
        self.assertEqual(trial.select_model_config(registered, {})['max_tokens'], 4096)
        with self.assertRaisesRegex(ValueError, '8192'):
            trial.select_model_config(registered, stages.STAGES['layout'])

    def test_query_ui_manifest_reuses_the_complete_original_query_oracle(self):
        directory = Path(__file__).resolve().parents[1] / 'acceptance'
        original = json.loads((directory / 'item-master-query-v1.json').read_text())
        ui = json.loads((directory / 'item-master-query-ui-v1.json').read_text())
        self.assertEqual(ui['script'], original['script'])
        self.assertEqual(ui['script_sha256'], original['script_sha256'])
        self.assertEqual(ui['cases'], original['cases'])
        self.assertEqual(hashlib.sha256((directory.parents[1] / ui['script']).read_bytes()).hexdigest(), ui['script_sha256'])
        self.assertEqual(stages.STAGES['query-ui']['checks'], ['frontend', 'framework'])
        self.assertEqual(stages.STAGES['api-query']['checks'], ['backend'])


class SupervisorModelTests(unittest.TestCase):
    def run_case(self, *, prior_stage=False, native_status='succeeded', extra=False,
                 active=False, changed_frozen=False, model_race=False, explicit=False,
                 stage_name='layout', backend_change=False, shadow_frontend=False,
                 frontend_change=None, new_backend_extra=False, new_frontend_extra=False,
                 ownership_paths=None, ownership_error=False, owned_backend_change=False,
                 migration_change=False, owned_backend_delete=False):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            app, state = root / 'local-only', root / 'platform/state'
            for relative in ('frontend/src/screens', 'backend/src', 'harness/state'):
                (app / relative).mkdir(parents=True)
            state.mkdir(parents=True)
            (app / 'frontend/src/screens/Home.tsx').write_text('home baseline')
            (app / 'frontend/src/workspace.json').write_text('workspace baseline')
            (app / 'frontend/src/framework').mkdir()
            (app / 'frontend/src/framework/index.ts').write_text('framework baseline')
            backend_existing = 'backend/src/main/java/com/example/localinventory/Application.java'
            (app / backend_existing).parent.mkdir(parents=True)
            (app / backend_existing).write_text('existing backend baseline')
            (app / 'harness/state/failures.json').write_text('["prior failure"]')
            (app / 'harness_evidence.log').write_text('prior evidence')
            if prior_stage:
                (app / trial.TARGET).write_text('passed earlier layout')
            retained_java = 'backend/src/main/java/com/example/localinventory/read/ExistingReadRows.java'
            retained_migration = 'backend/src/main/resources/db/migration/V8_2__read_rows.sql'
            if stage_name in ('query-ui', 'api-create'):
                # Prior verified API can have any valid source/migration names.
                for path in ('backend/src/main/java/com/example/localinventory/read/ExistingReadRows.java',
                             'backend/src/main/resources/db/migration/V8_2__read_rows.sql'):
                    (app / path).parent.mkdir(parents=True, exist_ok=True)
                    (app / path).write_text('passed earlier query API')
            acceptance = root / 'platform/acceptance'
            acceptance.mkdir()
            (acceptance / ('item-master-' + stage_name + '-v1.json')).write_text(json.dumps({'task': 'short fixture task'}))
            before = {str(p.relative_to(app)): p.read_bytes() for p in app.rglob('*') if p.is_file()}
            stage = {**stages.STAGES[stage_name], 'pointer': str(root / 'pointer'), 'require_clean_start': not prior_stage}
            if explicit:
                stage['model_config'] = 'other'
            chosen = config('other' if explicit else 'selected')
            posted, contacted, checks = [], [], []
            stamp = {'value': 'frozen'}
            captures = []

            def capture(stage_value, sources):
                captures.append((stage_value, dict(sources)))
                if ownership_error:
                    raise ValueError('Unapproved source lineage')
                if ownership_paths is None:
                    return None
                permitted = frozenset(ownership_paths)
                class Captured:
                    def allows_existing(self, path):
                        return path in permitted

                    def to_manifest(self):
                        return {'editable_existing': sorted(permitted), 'fixture': 'pinned'}
                return Captured()

            def urlopen(request, timeout=None):
                url = request if isinstance(request, str) else request.full_url
                contacted.append(url)
                if url.endswith('/api/state'):
                    return Response(json.dumps({'project': {'root': str(app)}, 'token': 'fixture-token',
                        'active': {'id': 'busy'} if active else None, 'external': []}))
                if url.endswith('/api/model-configs'):
                    return Response(json.dumps({'default': 'selected', 'models': [config('other'), config()]}))
                if url == chosen['url'] + '/models':
                    return Response('{}')
                if url.endswith('/api/jobs'):
                    posted.append(json.loads(request.data))
                    if frontend_change is True or (frontend_change is None and stage_name not in ('api-query', 'api-create')):
                        (app / trial.TARGET).write_text('model candidate')
                    if stage_name in ('query', 'api-query', 'api-create'):
                        for path in ('backend/src/main/java/com/example/localinventory/catalog/ItemController.java',
                                     'backend/src/test/java/com/example/localinventory/catalog/ItemQueryTest.java',
                                     'backend/src/main/resources/db/migration/V5_1__items.sql'):
                            (app / path).parent.mkdir(parents=True, exist_ok=True)
                            (app / path).write_text('new query source')
                    if stage_name in ('query', 'query-ui') or new_frontend_extra:
                        path = app / 'frontend/src/features/catalog/useItems.ts'
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_text('new frontend query helper')
                    if new_backend_extra:
                        path = app / 'backend/src/main/java/com/example/localinventory/NewExtra.java'
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_text('new backend query source')
                    if backend_change:
                        (app / backend_existing).write_text('changed protected backend')
                    if owned_backend_change:
                        (app / retained_java).write_text('changed model-owned backend')
                    if owned_backend_delete:
                        (app / retained_java).unlink()
                    if migration_change:
                        (app / retained_migration).write_text('changed applied migration')
                    if shadow_frontend:
                        (app / 'frontend/src/framework.ts').write_text('shadow framework baseline')
                    if extra:
                        (app / 'backend/src/Unexpected.java').write_text('out of scope')
                    job = state / 'fixture-job'
                    job.mkdir()
                    actual = {**chosen, 'max_tokens': 1234} if model_race else chosen
                    (job / 'job.json').write_text(json.dumps({'id': 'fixture-job', 'status': native_status,
                        'pid': 7777, 'exit_code': 0, 'finished_at': 'now', 'model': actual['model'],
                        'llm_url': actual['url'], 'model_config': actual}))
                    return Response('{"id":"fixture-job"}')
                raise AssertionError('Unexpected actual service request: ' + url)

            def check(command, cwd, timeout):
                checks.append(command)
                if command[0] == 'node':
                    output = Path(command[-1])
                    output.mkdir(parents=True)
                    observed = {'passed': True, 'cases': ['layout-case']}
                    if stage_name in ('api-query', 'api-create'):
                        observed.update(verificationMode='api-and-sql-only', browserStarted=False)
                    (output / 'result.json').write_text(json.dumps(observed))
                    if changed_frozen:
                        stamp['value'] = 'changed'
                return True, 'fixture successful check'

            with contextlib.ExitStack() as stack:
                for name, value in [('ROOT', root), ('APP', app), ('STATE', state)]:
                    stack.enter_context(patch.object(trial, name, value))
                stack.enter_context(patch.object(trial.urllib.request, 'urlopen', side_effect=urlopen))
                stack.enter_context(patch.object(trial, 'load_fixed_acceptance', return_value={
                    'script': str(root / 'oracle.cjs'), 'script_sha256': 'fixture-hash', 'cases': ['layout-case']}))
                stack.enter_context(patch.object(trial, 'frozen', side_effect=lambda: dict(stamp)))
                stack.enter_context(patch.object(trial, 'capture_stage_ownership', side_effect=capture))
                stack.enter_context(patch.object(trial, 'check', side_effect=check))
                stack.enter_context(patch.object(trial, 'events', return_value=[]))
                stack.enter_context(patch.object(trial.signal, 'signal'))
                stack.enter_context(patch.object(trial, 'require_free_space'))
                stack.enter_context(patch.object(trial, 'stop_and_confirm', return_value={'safe_to_restore': True}))
                stack.enter_context(patch.object(safety, 'stop_and_confirm', return_value={'safe_to_restore': True}))
                stack.enter_context(patch.object(safety.TrialEvidence, 'arm_reserve', lambda self, *args: self.reserve.write_bytes(b'reserve')))
                stdout = io.StringIO()
                with contextlib.redirect_stdout(stdout):
                    if active:
                        with self.assertRaisesRegex(AssertionError, 'Existing job active'):
                            trial.main(stage)
                        self.assertEqual(posted, [])
                        self.assertEqual({str(p.relative_to(app)): p.read_bytes() for p in app.rglob('*') if p.is_file()}, before)
                        return
                    if stage.get('required_paths') and not prior_stage:
                        with self.assertRaisesRegex(ValueError, 'Required prior-stage sources are missing'):
                            trial.main(stage)
                        self.assertEqual(posted, [])
                        self.assertEqual({str(p.relative_to(app)): p.read_bytes() for p in app.rglob('*') if p.is_file()}, before)
                        return
                    if ownership_error:
                        with self.assertRaisesRegex(ValueError, 'Unapproved source lineage'):
                            trial.main(stage)
                        self.assertEqual(posted, [])
                        self.assertEqual({str(p.relative_to(app)): p.read_bytes() for p in app.rglob('*') if p.is_file()}, before)
                        return
                    trial.main(stage)
                result = json.loads(stdout.getvalue().splitlines()[-1])
            self.assertEqual(len(posted), 1)
            self.assertEqual(posted[0], {'kind': 'agent', 'goal': 'short fixture task',
                'checks': stage['checks'], 'rounds': stage['max_calls'], 'thinking': stage['thinking'],
                'model': 'config:' + chosen['id'], 'fixed_acceptance': stage['acceptance'], 'context_profile': 'focused'})
            self.assertIn(chosen['url'] + '/models', contacted)
            out = Path(result['evidence'])
            self.assertTrue(out.name.startswith(stage['evidence_prefix']))
            self.assertEqual((root / 'pointer').read_text(), str(out))
            manifest = json.loads((out / 'manifest.json').read_text())
            self.assertEqual(manifest['model_config'], chosen)
            self.assertEqual(len(captures), 1)
            if ownership_paths is not None:
                self.assertEqual(manifest['source_ownership']['editable_existing'], sorted(ownership_paths))
                self.assertEqual(manifest['source_ownership']['permitted_existing_for_stage'], sorted(
                    path for path in ownership_paths if stage['allowed'](path)))
                self.assertEqual(manifest['source_ownership']['existing_deletion_policy'], 'forbidden')
                for path in ownership_paths:
                    self.assertEqual(captures[0][1][path], before[path])
            self.assertEqual(manifest['limits']['max_tokens'], 8192)
            self.assertIn(chosen['model'], manifest['implementation_author'])
            self.assertEqual(manifest['launched_model']['model_config']['max_tokens'], 1234 if model_race else 8192)
            self.assertEqual(result['model'], chosen['model'])
            self.assertEqual((app / 'harness/state/failures.json').read_text(), '["prior failure"]')
            self.assertEqual((app / 'harness_evidence.log').read_text(), 'prior evidence')
            self.assertTrue(result['cleanup_ok'])
            if result['success']:
                self.assertTrue(result['candidate_retained'])
                self.assertEqual((app / trial.TARGET).read_text(),
                                 'passed earlier layout' if stage_name in ('api-query', 'api-create') else 'model candidate')
                if stage_name == 'api-query':
                    self.assertTrue((app / 'backend/src/test/java/com/example/localinventory/catalog/ItemQueryTest.java').is_file())
                    self.assertFalse((app / 'frontend/src/features/catalog/useItems.ts').exists())
                if stage_name == 'query-ui':
                    self.assertEqual((app / 'backend/src/main/java/com/example/localinventory/read/ExistingReadRows.java').read_text(),
                                     'passed earlier query API')
                if stage_name == 'api-create':
                    self.assertEqual((app / retained_java).read_text(),
                                     'changed model-owned backend' if owned_backend_change else 'passed earlier query API')
            else:
                self.assertFalse(result['candidate_retained'])
                self.assertTrue(result['baseline_restored'])
                self.assertEqual({str(p.relative_to(app)): p.read_bytes() for p in app.rglob('*') if p.is_file()}, before)
            if model_race:
                self.assertEqual(checks, [])
                self.assertTrue(result['infrastructure_failure'])
            return result

    def test_default_model_request_manifest_and_success_retention(self):
        self.assertTrue(self.run_case()['success'])

    def test_explicit_registered_selection_overrides_default(self):
        self.assertTrue(self.run_case(explicit=True)['success'])

    def test_failed_later_stage_restores_previous_passed_stage(self):
        self.assertFalse(self.run_case(prior_stage=True, native_status='failed')['success'])

    def test_scope_and_frozen_protection_are_unchanged(self):
        self.assertFalse(self.run_case(extra=True)['success'])
        self.assertFalse(self.run_case(changed_frozen=True)['success'])

    def test_changed_model_configuration_cannot_be_reported_as_pinned(self):
        self.assertFalse(self.run_case(model_race=True)['success'])

    def test_active_native_job_blocks_before_source_mutation(self):
        self.run_case(active=True)

    def test_query_keeps_prior_layout_and_accepts_new_backend_and_fractional_migration(self):
        self.assertTrue(self.run_case(stage_name='query', prior_stage=True)['success'])

    def test_failed_query_restores_prior_layout_and_removes_new_backend_sources(self):
        self.assertFalse(self.run_case(stage_name='query', prior_stage=True, native_status='failed')['success'])

    def test_query_cannot_change_existing_backend(self):
        result = self.run_case(stage_name='query', prior_stage=True, backend_change=True)
        self.assertFalse(result['success'])
        self.assertFalse(result['scope_respected'])

    def test_query_cannot_shadow_a_foundation_barrel_with_a_new_file(self):
        result = self.run_case(stage_name='query', prior_stage=True, shadow_frontend=True)
        self.assertFalse(result['success'])
        self.assertFalse(result['scope_respected'])

    def test_query_requires_retained_layout_before_launch(self):
        self.run_case(stage_name='query')

    def test_query_new_source_scope_accepts_flyway_versions_without_path_traversal(self):
        for version in ('6', '5_1', '5.1', '5_0_1'):
            self.assertTrue(stages.query_new_source('backend/src/main/resources/db/migration/V' + version + '__items.sql'))
        for path in ('backend/src/main/java/com/example/localinventory/../Other.java',
                     'frontend/src/features/../../framework/Changed.tsx',
                     'frontend/src/framework/NewFramework.tsx',
                     'frontend/src/unchecked.d.ts',
                     'backend/src/main/resources/application.properties',
                     'backend/src/main/resources/db/migration/R__items.sql'):
            self.assertFalse(stages.query_new_source(path))

    def test_query_new_sources_allow_feature_helpers_and_tests(self):
        for path in ('frontend/src/features/catalog/useItems.ts',
                     'frontend/src/screens/parts/ItemFields.tsx',
                     'backend/src/test/java/com/example/localinventory/catalog/ItemQueryTest.java'):
            self.assertTrue(stages.query_new_source(path))

    def test_api_query_keeps_layout_and_retains_new_java_test_and_migration(self):
        result = self.run_case(stage_name='api-query', prior_stage=True)
        self.assertTrue(result['success'])
        self.assertEqual(result['verification_mode'], 'api-and-sql-only')
        self.assertIs(result['browser_started'], False)

    def test_api_query_failure_restores_layout_and_removes_new_backend(self):
        self.assertFalse(self.run_case(stage_name='api-query', prior_stage=True, native_status='failed')['success'])

    def test_api_query_rejects_frontend_and_existing_backend_changes(self):
        for changes in ({'frontend_change': True}, {'new_frontend_extra': True}, {'backend_change': True}):
            with self.subTest(changes=changes):
                result = self.run_case(stage_name='api-query', prior_stage=True, **changes)
                self.assertFalse(result['success'])
                self.assertFalse(result['scope_respected'])

    def test_query_ui_retains_frontend_change_and_preserves_arbitrarily_named_api(self):
        self.assertTrue(self.run_case(stage_name='query-ui', prior_stage=True)['success'])

    def test_query_ui_failure_restores_verified_api_and_layout(self):
        self.assertFalse(self.run_case(stage_name='query-ui', prior_stage=True, native_status='failed')['success'])

    def test_query_ui_rejects_new_and_existing_backend_and_module_shadow(self):
        for changes in ({'new_backend_extra': True}, {'backend_change': True}, {'shadow_frontend': True}):
            with self.subTest(changes=changes):
                result = self.run_case(stage_name='query-ui', prior_stage=True, **changes)
                self.assertFalse(result['success'])
                self.assertFalse(result['scope_respected'])

    def test_split_stages_require_prior_layout_and_keep_independent_scope(self):
        for name in ('api-query', 'query-ui'):
            with self.subTest(stage=name):
                self.run_case(stage_name=name)
        self.assertFalse(stages.api_query_change(trial.TARGET))
        self.assertFalse(stages.backend_new_source('frontend/src/features/useItems.ts'))
        self.assertFalse(stages.frontend_new_source('backend/src/main/java/com/example/localinventory/New.java'))

    def test_api_create_edits_captured_model_backend_and_keeps_frontend(self):
        owned = {'backend/src/main/java/com/example/localinventory/read/ExistingReadRows.java'}
        result = self.run_case(stage_name='api-create', prior_stage=True,
                               ownership_paths=owned, owned_backend_change=True)
        self.assertTrue(result['success'])
        self.assertEqual(result['verification_mode'], 'api-and-sql-only')
        self.assertIs(result['browser_started'], False)

    def test_api_create_failed_stage_restores_prior_model_backend(self):
        owned = {'backend/src/main/java/com/example/localinventory/read/ExistingReadRows.java'}
        result = self.run_case(stage_name='api-create', prior_stage=True, ownership_paths=owned,
                               owned_backend_change=True, native_status='failed')
        self.assertFalse(result['success'])
        self.assertTrue(result['baseline_restored'])

    def test_api_create_intersects_ownership_with_backend_only_scope(self):
        owned = {'backend/src/main/java/com/example/localinventory/read/ExistingReadRows.java',
                 'backend/src/main/resources/db/migration/V8_2__read_rows.sql', trial.TARGET}
        for changes in ({'backend_change': True}, {'frontend_change': True}, {'migration_change': True}):
            with self.subTest(changes=changes):
                result = self.run_case(stage_name='api-create', prior_stage=True,
                                       ownership_paths=owned, **changes)
                self.assertFalse(result['success'])
                self.assertFalse(result['scope_respected'])

    def test_ownership_rejection_happens_before_job_or_state_mutation(self):
        self.run_case(stage_name='api-create', prior_stage=True, ownership_error=True)

    def test_owned_source_deletion_cannot_create_an_unusable_success_lineage(self):
        owned = {'backend/src/main/java/com/example/localinventory/read/ExistingReadRows.java'}
        result = self.run_case(stage_name='api-create', prior_stage=True, ownership_paths=owned,
                               owned_backend_delete=True)
        self.assertFalse(result['success'])
        self.assertFalse(result['scope_respected'])
        self.assertTrue(result['baseline_restored'])

    def test_ownership_configuration_is_optional_but_never_empty(self):
        self.assertIsNone(trial.capture_stage_ownership({}, {}))
        with self.assertRaisesRegex(ValueError, 'approved successful stages'):
            trial.capture_stage_ownership({'approved_success_dirs': ()}, {})

    def test_new_module_resolution_preserves_existing_stems_and_barrels(self):
        for new, existing in (
            ('frontend/src/App.ts', 'frontend/src/App.tsx'),
            ('frontend/src/app.ts', 'frontend/src/App.tsx'),
            ('frontend/src/framework.ts', 'frontend/src/framework/index.ts'),
            ('frontend/src/Framework.ts', 'frontend/src/framework/index.ts'),
            ('frontend/src/framework.tsx', 'frontend/src/framework/index.ts'),
            ('frontend/src/features/items/index.ts', 'frontend/src/features/items.ts'),
            ('frontend/src/workspace.ts', 'frontend/src/workspace.json'),
        ):
            self.assertFalse(trial.new_source_does_not_shadow(new, {existing: b'baseline'}))
        self.assertTrue(trial.new_source_does_not_shadow(
            'frontend/src/features/items/useItems.ts', {'frontend/src/framework/index.ts': b'baseline'}))

    def test_full_and_stage_share_lock_and_release_after_exception(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(trial, 'STATE', Path(temp)):
            def while_locked(stage):
                script = ('import sys;from pathlib import Path;sys.path.insert(0,sys.argv[2]);'
                          'import item_crud_trial as t;t.STATE=Path(sys.argv[1]);t._main=lambda stage:0;t.main()')
                process = subprocess.run([sys.executable, '-c', script, temp, str(Path(trial.__file__).parent)],
                                         capture_output=True, text=True, timeout=5)
                self.assertNotEqual(process.returncode, 0)
                self.assertIn('Another item trial supervisor is still active', process.stderr)
                raise ValueError('fixture failure')
            with patch.object(trial, '_main', side_effect=while_locked):
                with self.assertRaisesRegex(ValueError, 'fixture failure'):
                    trial.main(stages.STAGES['layout'])
            with patch.object(trial, '_main', return_value=32):
                self.assertEqual(trial.main(), 32)


if __name__ == '__main__':
    unittest.main()
