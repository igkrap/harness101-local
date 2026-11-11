import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'local-only/harness'))
import component_catalog as catalog
from recipe_context import build_recipe, missing_frontend_targets, prefer_recipe


class ComponentRecipeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.src = self.root / 'frontend/src'
        self.src.mkdir(parents=True)
        self.pattern = {'id': 'example', 'kind': 'pattern', 'fingerprint': 'source-bound',
                        'source': 'frontend/src/Example.tsx',
                        'validation': {'status': 'verified', 'implementation_author': 'frontier'}}

    def write(self, rel, text):
        path = self.src / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def test_top_ranked_pattern_includes_whole_source_and_exact_direct_dependencies(self):
        text = "import React from 'react'; import {data} from './data.js'; export {Panel} from './parts'; export default function Example(){return <div>{data}</div>;}"
        self.write('Example.tsx', text)
        self.write('data.ts', 'export const data=42;')
        self.write('parts/index.ts', "export {Panel} from './Panel';")
        self.write('parts/Panel.tsx', 'export function Panel(){return null;}')
        packet = build_recipe(self.root, [{'kind': 'primitive'}, self.pattern, self.pattern | {'id': 'weaker'}])
        self.assertEqual(packet['id'], 'example')
        self.assertEqual([f['path'] for f in packet['files']], ['frontend/src/Example.tsx', 'frontend/src/data.ts', 'frontend/src/parts/index.ts'])
        self.assertEqual(packet['files'][0]['source'], text)
        self.assertEqual(packet['files'][0]['sha256'], hashlib.sha256(text.encode()).hexdigest())
        self.assertEqual(packet['validation']['implementation_author'], 'frontier')
        self.assertFalse(packet['omitted'])

    def test_import_like_comments_strings_and_external_modules_are_not_followed(self):
        self.write('Example.tsx', "/* import {secret} from './private'; */ const text=\"import './private'\"; import {x} from 'external'; export default function Example(){return text;}")
        self.write('private.ts', 'PRIVATE_MARKER')
        packet = build_recipe(self.root, [self.pattern])
        self.assertEqual(len(packet['files']), 1)
        self.assertNotIn('PRIVATE_MARKER', json.dumps(packet))
        self.assertFalse(packet['imports'])

    def test_outside_sources_missing_modules_and_symlinks_fail_closed(self):
        outside = self.root / 'outside.ts'
        outside.write_text('PRIVATE_MARKER')
        self.write('link.ts', '').unlink()
        (self.src / 'link.ts').symlink_to(outside)
        self.write('Example.tsx', "import './link'; import '../../outside'; import './absent'; export default function Example(){return null;}")
        packet = build_recipe(self.root, [self.pattern])
        self.assertEqual(len(packet['files']), 1)
        self.assertEqual(len(packet['omitted']), 3)
        self.assertNotIn('PRIVATE_MARKER', json.dumps(packet))
        packet = build_recipe(self.root, [self.pattern | {'source': 'frontend/src/link.ts'}])
        self.assertFalse(packet['files'])

    def test_bounds_omit_whole_files_and_do_not_follow_transitive_graph(self):
        self.write('Example.tsx', "import './a';import './b';import './c';export default function Example(){return null;}")
        for name in ('a', 'b', 'c'):
            self.write(name + '.ts', "export const " + name + "='" + ('x' * 1200) + "';")
        packet = build_recipe(self.root, [self.pattern])
        self.assertEqual(len(packet['files']), 3)
        self.assertTrue(any(o['reason'] == 'file count limit' for o in packet['omitted']))
        bounded = build_recipe(self.root, [self.pattern], max_chars=2200)
        self.assertLessEqual(len(json.dumps(bounded, ensure_ascii=False)), 2200)
        self.assertTrue(any('packet limit' in o['reason'] for o in bounded['omitted']))
        for f in bounded['files']:
            self.assertEqual(f['source'], (self.root / f['path']).read_text())
        oversized = build_recipe(self.root, [self.pattern], max_file_chars=40)
        self.assertFalse(oversized['files'])
        self.assertTrue(oversized['omitted'])

    def test_unusable_first_pattern_falls_back_without_truncating_or_hiding_omissions(self):
        self.write('Example.tsx', 'export default function Example(){return null;}' + ' ' * 6100)
        text = 'export function Alternate(){return <section>actual source</section>;}'
        self.write('Alternate.tsx', text)
        alternate = self.pattern | {'id': 'alternate', 'source': 'frontend/src/Alternate.tsx', 'validation': {'status': 'stale-source'}}
        packet = build_recipe(self.root, [self.pattern, alternate])
        self.assertEqual(packet['id'], 'alternate')
        self.assertEqual(packet['files'][0]['source'], text)
        self.assertEqual(packet['validation'], {'status': 'stale-source'})
        self.assertIn({'path': self.pattern['source'], 'reason': 'whole file exceeds per-file limit'}, packet['omitted'])
        self.assertLessEqual(len(json.dumps(packet, ensure_ascii=False)), 11000)
        self.write('Example.tsx', 'export default function Example(){return <div>;}')
        packet = build_recipe(self.root, [self.pattern, alternate])
        self.assertEqual(packet['id'], 'alternate')
        self.assertTrue(any('syntax errors' in item['reason'] for item in packet['omitted']))

    def test_missing_target_preference_excludes_existing_app_and_unsafe_paths(self):
        self.write('Example.tsx', 'export default function Example(){return null;}')
        self.write('App.tsx', 'export default function App(){return null;}')
        task = 'Create frontend/src/screens/New.tsx'
        runner = SimpleNamespace(args=SimpleNamespace(task=task), h=SimpleNamespace(workspace=SimpleNamespace(root=self.root)), _component_recipe=build_recipe(self.root, [self.pattern]))
        self.assertEqual(missing_frontend_targets(self.root, task), {'frontend/src/screens/New.tsx'})
        self.assertTrue(prefer_recipe(runner))
        runner.args.task += ' and modify frontend/src/App.tsx'
        self.assertFalse(prefer_recipe(runner))
        runner.args.task = task
        self.write('screens/New.tsx', 'export default function New(){return null;}')
        self.assertFalse(prefer_recipe(runner))
        self.assertFalse(missing_frontend_targets(self.root, 'frontend/src/../../outside.tsx'))
        self.assertIsNone(build_recipe(self.root, [{'kind': 'primitive'}]))

    def test_korean_particles_are_boundaries_but_filename_continuations_are_not(self):
        target = 'frontend/src/screens/New.tsx'
        for particle in ('에', '를', '에서'):
            with self.subTest(particle=particle):
                self.assertEqual(missing_frontend_targets(self.root, '새 파일 ' + target + particle + ' 구현하세요.'), {target})
        for suffix in ('.bak', 'Other', '/child', '_backup', '-backup'):
            with self.subTest(suffix=suffix):
                self.assertFalse(missing_frontend_targets(self.root, target + suffix))

    def test_catalog_usage_cache_tracks_api_doc_and_target_creation(self):
        self.write('Example.tsx', "import {data} from './data';export default function Example(){return data;}")
        self.write('data.ts', 'export const data=1;')
        doc = self.root / 'frontend/src/framework/API.txt'
        doc.parent.mkdir(parents=True, exist_ok=True)
        doc.write_text('EXAMPLE USAGE\n <Example/> version one\n')
        descriptor = self.pattern | {'version': '1', 'export': 'Example', 'summary': 'Example composition', 'example': '<Example/>', 'intents': [], 'capabilities': [], 'uses': []}
        self.write('example.component.json', json.dumps(descriptor))
        runner = SimpleNamespace(args=SimpleNamespace(task='Create frontend/src/screens/New.tsx'), h=SimpleNamespace(workspace=SimpleNamespace(root=self.root), log_event=Mock()))
        hit = {'success': True, 'content': '#1 matchedBy=vector frontend/src/example.component.json:1-8\n'}
        with patch('code_search.search_code', return_value=hit) as search:
            first = catalog.context_for_task(runner)
            self.assertIn('FRAMEWORK USAGE', first)
            self.assertIn('version one', first)
            self.assertNotIn('export const data', first)
            self.assertEqual(catalog.context_for_task(runner), first)
            self.assertEqual(search.call_count, 1)
            doc.write_text('EXAMPLE USAGE\n <Example/> version two\n')
            self.assertIn('version two', catalog.context_for_task(runner))
            self.write('screens/New.tsx', 'export default function New(){return null;}')
            self.assertNotIn('FRAMEWORK USAGE', catalog.context_for_task(runner))
            self.assertIsNone(runner._component_recipe)
        events = [call.args for call in runner.h.log_event.call_args_list if call.args[0] == 'autonomy.component_recipe']
        self.assertEqual(len(events), 2)
        self.assertTrue(all(event[1]['model_calls'] == 0 and event[1]['usage_chars'] for event in events))

    def test_actual_composition_reference_and_dependencies_fit_without_contract_loss(self):
        root = ROOT / 'local-only'
        entries, _ = catalog.descriptors(root)
        # Use the real registered Korean task; English-only probes missed the
        # attached particle and falsely suggested the live run received source.
        task = json.loads((ROOT / 'platform/acceptance/item-master-crud-v1.json').read_text())['task']
        original_target = 'frontend/src/screens/ItemMaster.tsx'
        self.assertIn(original_target + '에', task)
        # A completed prior stage may now retain the original target. Keep this
        # new-screen regression independent of that live business source.
        target = 'frontend/src/screens/RecipeRegression.tsx'
        task = task.replace(original_target, target)
        self.assertFalse((root / target).exists())
        self.assertEqual(missing_frontend_targets(root, task), {target})
        runner = SimpleNamespace(args=SimpleNamespace(task=task), h=SimpleNamespace(workspace=SimpleNamespace(root=root), log_event=Mock()))
        ids = ['registration-status', 'screen-actions', 'query-sections', 'query-panel', 'defined-screen']
        hit = {'success': True, 'content': '\n'.join('#%d matchedBy=vector %s:1-8' % (i + 1, entries[cid]['manifest']) for i, cid in enumerate(ids))}
        with patch('code_search.search_code', return_value=hit):
            text = catalog.context_for_task(runner)
        contracts = json.loads(text.split('\nFRAMEWORK USAGE')[0].split('\n', 2)[2])
        self.assertEqual([c['id'] for c in contracts['components']], ['registration-status', 'screen-actions', 'query-panel', 'record-grid', 'record-editor', 'tabbed-panel'])
        self.assertLessEqual(len(json.dumps(contracts['components'], ensure_ascii=False)), 9200)  # field options (codeGroup, lookup) added ~150 chars
        recipe = runner._component_recipe
        self.assertEqual(recipe['id'], 'registration-status')
        self.assertEqual(recipe['files'], [])
        # The real API document supplies usage; framework implementation source is not injected.
        self.assertIn('COMPOSITION GUIDE', recipe['usage'])
        self.assertIn('COMMON ACTIONS', recipe['usage'])
        self.assertIn('<RecordGrid', recipe['usage'])
        self.assertNotIn('export function BusinessWorkspace', text)
        self.assertNotIn('export function ScreenActions', text)
        self.assertLessEqual(len(recipe['usage']), 11000)
        self.assertTrue(prefer_recipe(runner))
        events = [call.args for call in runner.h.log_event.call_args_list if call.args[0] == 'autonomy.component_recipe']
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0][1]['model_calls'], 0)
        self.assertFalse((root / target).exists())

    def test_invalid_recipe_syntax_does_not_replace_a_current_source_snapshot(self):
        self.write('Example.tsx', 'export default function Example(){return <div>;}')
        packet = build_recipe(self.root, [self.pattern])
        self.assertFalse(packet['files'])
        self.assertIn('syntax errors', packet['omitted'][0]['reason'])


if __name__ == '__main__':
    unittest.main()
