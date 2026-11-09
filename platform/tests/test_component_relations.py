import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'local-only/harness'))
import component_catalog as catalog
from component_relations import requested_layout
from recipe_context import build_recipe


class ComponentRelationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.folder = self.root / 'frontend/src/components'
        self.folder.mkdir(parents=True)
        (self.root / 'frontend/src/screens').mkdir()
        (self.folder / 'Internal.tsx').write_text('export function Internal(){ return null; }')
        for cid in ('query-form', 'row-table', 'edit-form', 'collapse-options'):
            self.component(cid, 'primitive' if cid == 'collapse-options' else 'composite')
        slots = {'query': ['query-form'], 'results': ['row-table'], 'editor': ['edit-form']}
        for cid, position in (('lower-workspace', 'bottom'), ('side-workspace', 'right')):
            self.component(cid, 'pattern', layout={'editor': position}, slots=slots,
                           uses=['collapse-options', 'query-form', 'row-table', 'edit-form'])
        self.hit = {'success': True, 'content': '\n'.join(
            f'#{i} matchedBy=fts+vector frontend/src/components/{cid}.component.json:1-20'
            for i, cid in enumerate(('collapse-options', 'side-workspace'), 1))}

    def component(self, cid, kind, **extra):
        name = ''.join(word.title() for word in cid.split('-'))
        source = f"import {{Internal}} from './Internal'; export type {name}Props={{title:string}}; export function {name}(props:{name}Props){{return <section>{{props.title}}<Internal/></section>;}}"
        (self.folder / (name + '.tsx')).write_text(source)
        data = {'id': cid, 'kind': kind, 'version': '1', 'source': 'frontend/src/components/' + name + '.tsx',
                'export': name, 'props_type': name + 'Props', 'summary': 'Reusable component',
                'intents': [], 'capabilities': [], 'uses': [], 'example': f'<{name} title="example"/>', **extra}
        (self.folder / (cid + '.component.json')).write_text(json.dumps(data))

    def search(self, query):
        with patch('code_search.search_code', return_value=self.hit) as search:
            result = catalog.search_components(self.root, {'query': query, 'context_profile': 'focused'})
        search.assert_called_once()
        return result

    def test_bottom_constraint_recovers_compatible_pattern_outside_vector_hits(self):
        result = self.search('위에는 조회조건, 가운데 결과 그리드, 아래에는 접고 늘릴 수 있는 편집 패널.')
        self.assertEqual([item['id'] for item in result['components'][:4]],
                         ['lower-workspace', 'query-form', 'row-table', 'edit-form'])
        self.assertNotIn('side-workspace', [item['id'] for item in result['components']])
        self.assertEqual(result['layout_constraints'], {'editor': 'bottom'})
        self.assertEqual(result['matched_components'], ['collapse-options', 'side-workspace'])

    def test_right_and_ambiguous_requests_do_not_force_bottom_pattern(self):
        result = self.search('우측 편집 패널과 왼쪽 목록')
        self.assertEqual(result['components'][0]['id'], 'side-workspace')
        self.assertEqual(requested_layout('하단 편집 패널 또는 우측 편집 패널'), {})
        result = self.search('generic query components')
        self.assertEqual(result['components'][0]['id'], 'collapse-options')

    def test_unknown_slot_ids_are_rejected_as_invalid_metadata(self):
        path = self.folder / 'lower-workspace.component.json'
        data = json.loads(path.read_text())
        data['slots']['editor'] = ['undeclared']
        path.write_text(json.dumps(data))
        entries, errors = catalog.descriptors(self.root)
        self.assertNotIn('lower-workspace', entries)
        self.assertTrue(any('Slot contracts' in item['error'] for item in errors))

    def test_focus_preserves_all_slot_contracts_and_omits_internal_implementation(self):
        (self.root / 'frontend/src/framework').mkdir()
        (self.root / 'frontend/src/framework/API.txt').write_text(
            'LOWER WORKSPACE\n <LowerWorkspace title="x"/> places query/results/editor.\n\nUNRELATED\n nothing here\n')
        runner = SimpleNamespace(args=SimpleNamespace(task='하단 편집 패널 화면 NewScreen.tsx를 구성해줘', context_profile='focused'),
                                 h=SimpleNamespace(workspace=SimpleNamespace(root=self.root), log_event=Mock()))
        with patch('code_search.search_code', return_value=self.hit):
            text = catalog.context_for_task(runner)
        self.assertLessEqual(len(text), 12000)
        packet_text, usage_text = text.split('\nFRAMEWORK USAGE')
        packet = json.loads(packet_text.split('\n', 2)[-1])
        self.assertEqual([item['id'] for item in packet['components']],
                         ['lower-workspace', 'query-form', 'row-table', 'edit-form'])
        self.assertFalse(packet['missing_slot_contracts'])
        for component in packet['components']:
            self.assertIn(component['export'] + 'Props', component['props'])
        # Usage comes from the API document; no implementation source is injected.
        self.assertIn('<LowerWorkspace title="x"/>', usage_text)
        self.assertNotIn('UNRELATED', usage_text)
        self.assertNotIn('export function', usage_text)
        self.assertNotIn('Internal', text.split('"props"')[0] + usage_text)
        self.assertEqual(runner._component_recipe['files'], [])

    def test_missing_slot_contract_is_explicit_and_disables_recipe(self):
        runner = SimpleNamespace(args=SimpleNamespace(task='하단 편집 패널 화면 NewScreen.tsx를 구성해줘', context_profile='focused'),
                                 h=SimpleNamespace(workspace=SimpleNamespace(root=self.root), log_event=Mock()))
        with patch('code_search.search_code', return_value=self.hit), \
                patch('component_catalog.actual_props', side_effect=lambda root, item: item['id'] + 'x' * 3800):
            text = catalog.context_for_task(runner)
        self.assertLessEqual(len(text), 12000)
        self.assertNotIn('REFERENCE COMPOSITION SOURCE DATA', text)
        packet = json.loads(text.split('\n', 2)[-1])
        self.assertIn('edit-form', packet['missing_slot_contracts'])
        self.assertIsNone(runner._component_recipe)

    def test_recipe_skips_explicitly_incompatible_layout(self):
        entries, _ = catalog.descriptors(self.root)
        patterns = [entries[cid] | {'validation': {'status': 'unverified'}} for cid in ('side-workspace', 'lower-workspace')]
        recipe = build_recipe(self.root, patterns,
                              layout_constraints={'editor': 'bottom'})
        self.assertEqual(recipe['id'], 'lower-workspace')
        self.assertTrue(any('contradicts' in item['reason'] for item in recipe['omitted']))


if __name__ == '__main__':
    unittest.main()
