import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'local-only/harness'))
import component_catalog as catalog
from component_source_contracts import existing_composition


class ExistingCompositionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = 'frontend/src/screens/OrderEntry.tsx'
        self.names = {'current-workspace': 'CurrentWorkspace', 'query-form': 'QueryForm',
                      'result-table': 'ResultTable', 'edit-panel': 'EditPanel', 'other-workspace': 'OtherWorkspace'}
        slots = {'query': ['query-form'], 'results': ['result-table'], 'editor': ['edit-panel']}
        for cid, name in self.names.items():
            self.put('frontend/src/components/' + name + '.tsx',
                     f'export type {name}Props={{title:string}}; export function {name}(props:{name}Props){{return <section>{{props.title}}</section>;}}')
            descriptor = {'id': cid, 'kind': 'pattern' if cid.endswith('workspace') else 'composite',
                          'version': '1', 'source': 'frontend/src/components/' + name + '.tsx', 'export': name,
                          'props_type': name + 'Props', 'summary': 'Reusable UI', 'intents': [], 'capabilities': [],
                          'uses': [], 'example': f'<{name} title="example"/>'}
            if cid == 'current-workspace':
                descriptor.update(layout={'editor': 'bottom'}, slots=slots, uses=list(self.names)[1:4])
            self.put('frontend/src/components/' + cid + '.component.json', json.dumps(descriptor))
        self.put('frontend/src/components/index.ts', '\n'.join(
            f"export {{{name}}} from './{name}';" for name in self.names.values()))
        self.original = """import {CurrentWorkspace as Shell, QueryForm, ResultTable, EditPanel} from '../components';
export default function OrderEntry(){return <Shell title="items"><QueryForm/><ResultTable/><EditPanel/></Shell>;}"""
        self.put(self.source, self.original)
        self.hit = {'success': True, 'content': '#1 matchedBy=vector frontend/src/components/other-workspace.component.json:1-10'}

    def put(self, relative, text):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def runner(self, task='OrderEntry 조회를 GET /api/orders에 연결해줘. 기존 배치는 유지해.', profile='focused'):
        return SimpleNamespace(args=SimpleNamespace(task=task, context_profile=profile),
                               h=SimpleNamespace(workspace=SimpleNamespace(root=self.root), log_event=Mock()))

    def packet(self, runner):
        text = catalog.context_for_task(runner)
        self.assertLessEqual(len(text), 12000)
        self.assertNotIn('REFERENCE COMPOSITION SOURCE DATA', text)
        return json.loads(text.split('\n', 2)[-1])

    def test_existing_target_uses_real_alias_barrel_contracts_without_semantic_search(self):
        runner = self.runner()
        with patch('code_search.search_code', return_value=self.hit) as search:
            packet = self.packet(runner)
        search.assert_not_called()
        self.assertEqual(packet['retrieval'], 'local/typescript-imports')
        self.assertEqual(packet['current_source'], self.source)
        self.assertEqual([item['id'] for item in packet['components']], list(self.names)[:4])
        self.assertFalse(packet['missing_slot_contracts'])
        for item in packet['components']:
            self.assertIn(item['export'] + 'Props', item['props'])
        self.assertIsNone(runner._component_recipe)
        self.assertFalse(hasattr(runner, 'read'), 'Contract retrieval must not grant source-read authority')

    def test_namespace_and_reexport_aliases_resolve_to_declared_sources(self):
        self.put('frontend/src/components/barrel.ts', "export {CurrentWorkspace as Layout} from './CurrentWorkspace';")
        self.put(self.source, "import * as UI from '../components/barrel'; export default function OrderEntry(){return <UI.Layout/>;}")
        entries, _ = catalog.descriptors(self.root)
        found = existing_composition(self.root, 'Edit OrderEntry query', entries)
        self.assertEqual(found['components'], ['current-workspace'])

    def test_type_only_unused_external_and_commented_imports_are_not_existing_contracts(self):
        self.put(self.source, """import {CurrentWorkspace} from '../components';
import type {QueryForm} from '../components'; import {ResultTable} from '@external/widgets';
import {OtherWorkspace} from '../components';
// import {EditPanel} from '../components';
const text = '<OtherWorkspace/>';
export default function OrderEntry(){return <CurrentWorkspace><QueryForm/><ResultTable/><EditPanel/></CurrentWorkspace>;}""")
        entries, _ = catalog.descriptors(self.root)
        self.assertEqual(existing_composition(self.root, 'Edit OrderEntry', entries)['components'], ['current-workspace'])

    def test_shadowed_jsx_import_cannot_claim_actual_component_origin(self):
        entries, _ = catalog.descriptors(self.root)
        for declaration in ('function OrderEntry(CurrentWorkspace){return <CurrentWorkspace/>;}',
                            'function OrderEntry(){const CurrentWorkspace=()=>null;return <CurrentWorkspace/>;}',
                            'function OrderEntry({CurrentWorkspace}){return <CurrentWorkspace/>;}'):
            with self.subTest(declaration=declaration):
                self.put(self.source, "import {CurrentWorkspace} from '../components'; export default " + declaration)
                self.assertIsNone(existing_composition(self.root, 'Edit OrderEntry', entries))

    def test_redesign_different_pattern_and_new_target_keep_semantic_discovery(self):
        for task in ('OrderEntry 레이아웃을 변경해줘.', 'OrderEntry 편집 패널을 우측으로 옮겨줘.',
                     'OrderEntry 화면에 새 패턴을 적용해줘.',
                     'OrderEntry 화면을 OtherWorkspace로 바꿔줘.', 'Redesign OrderEntry.',
                     'OrderEntry 참고해서 NewScreen.tsx 화면을 만들어줘.'):
            with self.subTest(task=task), patch('code_search.search_code', return_value=self.hit) as search:
                text = catalog.context_for_task(self.runner(task))
                search.assert_called_once()
                self.assertIn('local/potion-multilingual-128m:hybrid-fts-vector', text)

    def test_layout_preservation_is_not_a_redesign_request(self):
        for task in ('OrderEntry 레이아웃 변경 없이 실제 조회만 연결해줘.',
                     'Connect OrderEntry query without changing the layout.'):
            with self.subTest(task=task), patch('code_search.search_code', return_value=self.hit) as search:
                self.packet(self.runner(task))
                search.assert_not_called()

    def test_ambiguous_target_and_symlink_fall_back_without_choosing_a_screen(self):
        self.put('frontend/src/legacy/OrderEntry.tsx', self.original)
        (self.root / 'frontend/src/screens/Linked.tsx').symlink_to(self.root / self.source)
        for task in ('Edit OrderEntry query', 'Edit Linked query'):
            with self.subTest(task=task), patch('code_search.search_code', return_value=self.hit) as search:
                packet = self.packet(self.runner(task))
                search.assert_called_once()
                self.assertIsNone(packet['current_source'])

    def test_barrel_symlink_and_ambiguous_star_export_are_not_trusted(self):
        entries, _ = catalog.descriptors(self.root)
        barrel = self.root / 'frontend/src/components/index.ts'
        barrel.unlink(); barrel.symlink_to(self.root / 'frontend/src/components/CurrentWorkspace.tsx')
        self.assertIsNone(existing_composition(self.root, 'Edit OrderEntry', entries))
        barrel.unlink()
        self.put('frontend/src/components/Alternative.tsx', 'export function CurrentWorkspace(){return null;}')
        self.put('frontend/src/components/index.ts', "export * from './CurrentWorkspace'; export * from './Alternative';")
        self.assertIsNone(existing_composition(self.root, 'Edit OrderEntry', entries))

    def test_changed_target_imports_invalidate_cached_packet(self):
        runner = self.runner()
        with patch('code_search.search_code', return_value=self.hit) as search:
            before = self.packet(runner)
            self.put(self.source, "import {OtherWorkspace} from '../components'; export default function OrderEntry(){return <OtherWorkspace/>;}")
            after = self.packet(runner)
        self.assertNotEqual(before, after)
        self.assertEqual([item['id'] for item in after['components']], ['other-workspace'])
        search.assert_not_called()

    def test_changed_barrel_binding_invalidates_packet_without_changing_target(self):
        runner = self.runner()
        source_before = (self.root / self.source).read_bytes()
        with patch('code_search.search_code', return_value=self.hit) as search:
            before = self.packet(runner)
            barrel = self.root / 'frontend/src/components/index.ts'
            barrel.write_text(barrel.read_text().replace(
                "export {CurrentWorkspace} from './CurrentWorkspace';",
                "export {OtherWorkspace as CurrentWorkspace} from './OtherWorkspace';"))
            after = self.packet(runner)
        self.assertEqual((self.root / self.source).read_bytes(), source_before)
        self.assertEqual(before['components'][0]['id'], 'current-workspace')
        self.assertEqual(after['components'][0]['id'], 'other-workspace')
        search.assert_not_called()

    def test_large_contracts_are_omitted_explicitly_instead_of_truncated(self):
        with patch('component_catalog.actual_props', side_effect=lambda root, item: item['id'] + 'x' * 3800):
            packet = self.packet(self.runner())
        self.assertIn('edit-panel', packet['missing_slot_contracts'])
        self.assertTrue(all(len(item['props']) >= 3800 for item in packet['components']))

    def test_explicit_search_and_legacy_context_keep_existing_behavior(self):
        with patch('code_search.search_code', return_value=self.hit) as search:
            result = catalog.search_components(self.root, {'query': '새로운 패턴', 'context_profile': 'focused'})
            search.assert_called_once()
        self.assertEqual(result['components'][0]['id'], 'other-workspace')
        with patch('code_search.search_code', return_value=self.hit) as search:
            catalog.context_for_task(self.runner(profile='legacy'))
            search.assert_called_once()


if __name__ == '__main__':
    unittest.main()
