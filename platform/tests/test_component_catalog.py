import json
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'local-only/harness'))
import component_catalog as catalog


class ComponentCatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.folder = self.root / 'frontend/src/components'
        self.folder.mkdir(parents=True)
        (self.folder/'helper.ts').write_text('export const minimum=1;')
        (self.folder/'Panel.tsx').write_text("import {minimum} from './helper'; export type PanelProps={title:string}; export function Panel(props:PanelProps){return <section>{props.title}{minimum}</section>;}")
        self.descriptor = {'id':'panel', 'version':'1', 'kind':'primitive', 'source':'frontend/src/components/Panel.tsx',
            'export':'Panel', 'props_type':'PanelProps', 'summary':'업무 패널', 'intents':['패널'], 'capabilities':['title'],
            'uses':[], 'example':'<Panel title="제목"/>'}
        self.manifest = self.folder/'panel.component.json'
        self.manifest.write_text(json.dumps(self.descriptor))
        self.hit = {'success':True, 'content':'#1 matchedBy=fts+vector frontend/src/components/panel.component.json:1-10\n'}

    def search(self):
        with patch('code_search.search_code', return_value=self.hit):
            return catalog.search_components(self.root, {'query':'업무 패널'})

    def test_retrieval_reads_actual_props_and_does_not_claim_unchecked_success(self):
        result = self.search()
        self.assertEqual(result['components'][0]['validation'], {'status':'unverified'})
        self.assertIn('title: string', result['components'][0]['props'])
        self.assertIn('vector', result['retrieval'])

    def test_dependency_change_invalidates_trusted_validation(self):
        catalog.record_validation(self.root, ['panel'], ['fixture-browser'], 'frontier')
        before = self.search()['components'][0]
        self.assertEqual(before['validation']['implementation_author'], 'frontier')
        (self.folder/'helper.ts').write_text('export const minimum=2;')
        after = self.search()['components'][0]
        self.assertEqual(after['validation'], {'status':'stale-source'})
        self.assertNotEqual(before['fingerprint'], after['fingerprint'])

    def test_wrong_export_and_escaping_source_do_not_enter_catalog(self):
        for changes in [{'export':'Invented'}, {'source':'../secret'}, {'props_type':'MissingProps'}]:
            self.manifest.write_text(json.dumps(self.descriptor | changes))
            entries, errors = catalog.descriptors(self.root)
            self.assertFalse(entries)
            self.assertTrue(errors)

    def test_declared_composition_is_expanded_and_changes_invalidate_pattern(self):
        pattern = self.descriptor | {'id':'pattern', 'kind':'pattern', 'uses':['panel']}
        file = self.folder/'pattern.component.json'; file.write_text(json.dumps(pattern))
        self.hit['content']='#1 matchedBy=vector frontend/src/components/pattern.component.json:1-10\n'
        catalog.record_validation(self.root, ['pattern'], ['browser'], 'frontier')
        result=self.search()['components']
        self.assertEqual([r['id'] for r in result], ['pattern','panel'])
        self.manifest.write_text(json.dumps(self.descriptor | {'version':'2'}))
        self.assertEqual(self.search()['components'][0]['validation']['status'],'stale-source')

    def test_composition_cycle_cannot_be_attested(self):
        self.manifest.write_text(json.dumps(self.descriptor | {'uses':['panel']}))
        entries, errors = catalog.descriptors(self.root)
        self.assertFalse(entries)
        self.assertIn('Cyclic', errors[0]['error'])
        with self.assertRaises(ValueError):
            catalog.record_validation(self.root, ['panel'], ['browser'])

    def test_composition_contracts_precede_weaker_search_hits(self):
        for cid in ['pattern', 'editor', 'unrelated']:
            manifest = self.descriptor | {'id': cid, 'uses': ['panel', 'editor'] if cid == 'pattern' else []}
            (self.folder/(cid+'.component.json')).write_text(json.dumps(manifest))
        self.hit['content'] = '#1 matchedBy=vector frontend/src/components/pattern.component.json:1-10\n#2 matchedBy=vector frontend/src/components/unrelated.component.json:1-10\n'
        self.assertEqual([c['id'] for c in self.search()['components']][:4], ['pattern', 'panel', 'editor', 'unrelated'])

    def test_automatic_retrieval_is_cached_until_component_changes(self):
        runner=SimpleNamespace(args=SimpleNamespace(task='업무 패널'),h=SimpleNamespace(workspace=SimpleNamespace(root=self.root),log_event=Mock()))
        with patch('code_search.search_code',return_value=self.hit) as search:
            first=catalog.context_for_task(runner)
            self.assertEqual(catalog.context_for_task(runner),first)
            self.assertEqual(search.call_count,1)
            (self.folder/'helper.ts').write_text('export const minimum=3;')
            self.assertNotEqual(catalog.context_for_task(runner),first)
            self.assertEqual(search.call_count,2)

    def test_complete_ui_sentences_replace_registry_and_path_prefix_noise(self):
        prefix = "Spring backend API database storage. " + "Create frontend/src/screens/Custom.tsx and export const meta={code:'ABC0001',title:'Custom',permissions:['admin']}. "
        ui = 'Place the query panel at the top and the results grid in the middle. Add a collapsible bottom editor panel and save button.'
        query = catalog.task_query(prefix * 3 + ui)
        self.assertLessEqual(len(query), 300)
        self.assertIn('results grid', query)
        self.assertIn('bottom editor panel', query)
        self.assertNotIn('frontend/', query)
        self.assertNotIn('ABC0001', query)
        self.assertNotIn('database storage', query)
        self.assertTrue(query.endswith('.'))
        self.assertEqual(catalog.task_query('업무 패널'), '업무 패널')

    def test_compound_ui_contracts_precede_primitive_and_nonrendering_dependencies(self):
        hook = self.folder / 'useState.ts'
        hook.write_text('export function useState(){return false;}')
        entries = {
            'layout': {'kind': 'pattern', 'uses': ['hook', 'label', 'grid', 'editor', 'query', 'split']},
            'hook': {'kind': 'primitive', 'source': 'frontend/src/components/useState.ts', 'export': 'useState', 'props_type': None},
            'label': {'kind': 'primitive'}, 'grid': {'kind': 'composite'},
            'editor': {'kind': 'composite'}, 'query': {'kind': 'composite'}, 'split': {'kind': 'primitive'},
        }
        for cid, changes in entries.items():
            (self.folder / (cid + '.component.json')).write_text(json.dumps(self.descriptor | {'id': cid} | changes))
        self.hit['content'] = '#1 matchedBy=vector frontend/src/components/layout.component.json:1-10\n'
        result = self.search()
        self.assertEqual([c['id'] for c in result['components']], ['layout', 'grid', 'editor', 'query', 'label', 'split'])
        self.assertIn('hook', result['omitted_components'])
