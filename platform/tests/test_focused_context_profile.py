import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'platform'))
sys.path.insert(0, str(ROOT / 'local-only/harness'))
from server import Platform
from test_autonomy import native
from autonomy_runtime import Runner
from project_context import project_context


class FocusedProfileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.put('frontend/src/workspace.json', '{}')
        self.put('backend/src/main/java/sample/SecretController.java', '@PostMapping BACKEND_ONLY_SENTINEL')
        self.put('backend/src/main/resources/db/migration/V1__base.sql', 'SCHEMA_ONLY_SENTINEL')

    def put(self, path, text):
        p = self.root / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)

    def runner(self, profile='focused', check='frontend|framework'):
        args = SimpleNamespace(task='등록 화면의 조회패널과 결과그리드를 구성하세요 UNIQUE_TASK.',
                               workspace=str(self.root), check=check, context_profile=profile,
                               max_rounds=4, ponytail='full', llm_url='http://127.0.0.1:8099/v1', model='fixture')
        runner = Runner(args, native.Harness)
        runner.h.log_event = Mock()
        runner.steps = [{'title': args.task, 'kind': 'change'}]
        runner.feedback = json.dumps({'task': args.task, 'results': [{'id': 'C1', 'status': 'failed'}]}, ensure_ascii=False)
        runner.requirement_gate = SimpleNamespace(enabled=True, context=lambda: 'FROZEN C1 must pass')
        runner.current_context = lambda: ('CURRENT FILE frontend/src/workspace.json\n{}', {'frontend/src/workspace.json'})
        runner.memory.context = lambda: ''
        return runner

    def fresh(self, runner):
        skill = self.root / 'skill.txt'
        skill.write_text('PONYTAIL_ONLY_SENTINEL')
        with patch.dict(os.environ, {'PONYTAIL_SKILL_PATH': str(skill)}), \
                patch('component_catalog.context_for_task', return_value='ACTUAL_COMPONENT_PROPS'):
            runner.fresh('completion evidence missing')
        return '\n'.join(m['content'] for m in runner.messages)

    def test_focused_frontend_excludes_backend_and_ponytail_without_losing_checks_or_read_state(self):
        runner = self.runner()
        context = self.fresh(runner)
        self.assertEqual(context.count(runner.args.task), 1)
        self.assertIn('Current step: 1/1', context)
        for omitted in ('BACKEND_ONLY_SENTINEL', 'SCHEMA_ONLY_SENTINEL', 'PONYTAIL_ONLY_SENTINEL', 'Flyway', 'EXISTING POST'):
            self.assertNotIn(omitted, context)
        self.assertIn('FROZEN C1 must pass', context)
        self.assertIn('Read existing files before editing', context)
        self.assertIn('ACTUAL_COMPONENT_PROPS', context)
        self.assertEqual(runner.read, {'frontend/src/workspace.json'})
        self.assertIn('"status": "failed"', context)
        self.assertEqual(runner.modes, ['frontend', 'framework'])

    def test_legacy_prompt_retains_prior_context_and_ponytail(self):
        runner = self.runner('legacy')
        context = self.fresh(runner)
        self.assertGreater(context.count(runner.args.task), 1)
        self.assertIn('BACKEND_ONLY_SENTINEL', context)
        self.assertIn('PONYTAIL_ONLY_SENTINEL', context)
        self.assertIn('Flyway', context)

    def test_backend_stage_keeps_schema_and_backend_contract(self):
        context = self.fresh(self.runner(check='backend'))
        self.assertIn('SCHEMA_ONLY_SENTINEL', context)
        self.assertIn('BACKEND_ONLY_SENTINEL', context)
        self.assertIn('Flyway', context)
        scoped = project_context(self.root, scope=['backend'])
        self.assertNotIn('frontend/src/workspace.json', scoped)
        self.assertNotIn('UI Conventions', scoped)

    def test_compaction_preserves_single_task_and_frozen_completion_contract(self):
        from recent_context import compact
        runner = self.runner()
        self.fresh(runner)
        runner.messages += [
            {'role': 'assistant', 'tool_calls': [{'id': 'docs', 'function': {'name': 'astryx_docs', 'arguments': '{}'}}]},
            {'role': 'tool', 'tool_call_id': 'docs', 'content': 'actual component documentation'}]
        self.assertTrue(compact(runner, [], 8192, 32768, 'long history'))
        context = '\n'.join(str(m.get('content', '')) for m in runner.messages)
        self.assertEqual(context.count(runner.args.task), 1)
        self.assertIn('FROZEN C1 must pass', context)
        self.assertIn('frontend/src/workspace.json', runner.read)

    def test_request_profile_validation_and_opt_in_persistence(self):
        app = Platform(self.root, self.root / 'state', 0)
        self.addCleanup(app.history.db.close)
        app.models = Mock(return_value={'available': ['fixture']})
        app.external = Mock(return_value=[])
        for invalid in (None, True, [], {}, 'small', 1):
            with self.subTest(invalid=invalid), patch('server.subprocess.Popen') as launch:
                with self.assertRaises(ValueError):
                    app.start({'kind': 'agent', 'goal': 'Task', 'context_profile': invalid})
                launch.assert_not_called()
        for profile in (None, 'legacy', 'focused'):
            app.processes.clear()
            body = {'kind': 'agent', 'goal': 'Task', 'model': 'fixture'}
            if profile is not None:
                body['context_profile'] = profile
            with patch('server.subprocess.Popen', return_value=Mock(pid=12345)), patch('server.threading.Thread'):
                job = app.start(body)
            request = json.loads((app.state / job['id'] / 'request.json').read_text())
            if profile is None:
                self.assertNotIn('context_profile', request)
            else:
                self.assertEqual(request['context_profile'], profile)
            self.assertEqual(request['completion_policy'], 'requirement-contract-v1')
        app.processes.clear()
        with patch('server.subprocess.Popen', return_value=Mock(pid=12346)), patch('server.threading.Thread'):
            job = app.start({'kind': 'agent', 'goal': '품목 등록 화면의 편집 패널을 버튼으로 접게 해줘', 'model': 'fixture'})
        request = json.loads((app.state / job['id'] / 'request.json').read_text())
        self.assertEqual(request['context_profile'], 'focused')
        self.assertEqual(request['checks'], ['frontend', 'framework'])

    def test_adapter_transfers_profile_and_disables_ponytail_only_for_focused(self):
        import adapter
        self.put('harness/harness.py', '# fake isolated harness module')
        original_path = list(sys.path)
        self.addCleanup(lambda: sys.path.__setitem__(slice(None), original_path))
        for profile, ponytail in ((None, 'full'), ('legacy', 'full'), ('focused', 'off')):
            module = SimpleNamespace(Harness=type('Harness', (), {}), DEFAULT_MODEL='fixture', run_task=Mock(return_value=False))
            loader = SimpleNamespace(loader=SimpleNamespace(exec_module=Mock()))
            request = {'kind': 'agent', 'goal': 'Task', 'checks': ['frontend', 'framework'], 'rounds': 4}
            if profile is not None:
                request['context_profile'] = profile
            with patch.dict(os.environ), patch('adapter.importlib.util.spec_from_file_location', return_value=loader), \
                    patch('adapter.importlib.util.module_from_spec', return_value=module):
                self.assertEqual(adapter.execute(self.root, self.root / ('job-' + str(profile)), request), 1)
            args = module.run_task.call_args.args[0]
            self.assertEqual(args.context_profile, profile or 'legacy')
            self.assertEqual(args.ponytail, ponytail)
            self.assertEqual(args.check, 'frontend|framework')

    def test_focused_rag_shared_budget_preserves_whole_props_and_usage_docs(self):
        import component_catalog
        source = 'export function Pattern(){ return <section>actual source</section>; }' + ' ' * 3900
        self.put('frontend/src/Pattern.tsx', source)
        self.put('frontend/src/framework/API.txt', 'PATTERN USAGE\n <Pattern/> composes the screen.\n')
        components = []
        for i in range(6):
            components.append({'id': str(i), 'kind': 'pattern' if i == 0 else 'primitive', 'export': 'Pattern',
                               'source': 'frontend/src/Pattern.tsx', 'props': 'actual_prop_' + str(i) + 'x' * 1400,
                               'fingerprint': 'fingerprint', 'validation': {'status': 'unverified'}})
        runner = self.runner()
        runner.args.task = 'Create frontend/src/screens/New.tsx with a query panel'
        with patch('component_catalog.descriptors', return_value=({'pattern': {'fingerprint': 'f'}}, [])), \
                patch('component_catalog.search_components', return_value={'success': True, 'components': components, 'retrieval': 'fixture'}):
            focused = component_catalog.context_for_task(runner)
            runner.args.context_profile = 'legacy'
            legacy = component_catalog.context_for_task(runner)
        self.assertLessEqual(len(focused), 12000)
        self.assertGreater(len(legacy), len(focused))
        before, usage = focused.split('\nFRAMEWORK USAGE')
        packet = json.loads(before.split('\n', 2)[-1])
        for entry in packet['components']:
            self.assertEqual(entry['props'], components[int(entry['id'])]['props'])
        self.assertIn('<Pattern/> composes the screen.', usage)
        self.assertNotIn('actual source', focused)

    def test_short_screen_basename_uses_existing_project_convention_only_when_unambiguous(self):
        from recipe_context import missing_frontend_targets
        (self.root / 'frontend/src/screens').mkdir()
        task = '등록 화면부터 구성해줘. 화면 파일은 ShortScreen.tsx야.'
        expected = {'frontend/src/screens/ShortScreen.tsx'}
        self.assertEqual(missing_frontend_targets(self.root, task, allow_basename=True), expected)
        self.assertEqual(missing_frontend_targets(self.root, task), set())
        for ambiguous in ('Create a screen with First.tsx and Second.tsx',
                          'Create a screen ../Outside.tsx', 'ShortScreen.tsx 수정해줘'):
            self.assertEqual(missing_frontend_targets(self.root, ambiguous, allow_basename=True), set())
        self.put('frontend/src/components/ShortScreen.tsx', 'already exists')
        self.assertEqual(missing_frontend_targets(self.root, task, allow_basename=True), set())
        (self.root / 'frontend/src/components/ShortScreen.tsx').unlink()
        self.put('frontend/src/screens/ShortScreen.tsx', 'already exists')
        self.assertEqual(missing_frontend_targets(self.root, task, allow_basename=True), set())


if __name__ == '__main__':
    unittest.main()
