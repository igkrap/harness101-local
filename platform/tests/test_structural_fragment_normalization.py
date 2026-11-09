import json
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[2]


class StructuralFragments(unittest.TestCase):
    def normalize(self, source, kind, original, replacement):
        indexed = subprocess.run(['node', str(ROOT/'local-only/harness/ast_edit_ranges.cjs')],
            input=json.dumps({'path': 'fixture.tsx', 'source': source}), text=True, capture_output=True, check=True)
        nodes = [{**n, 'range': [n['start'], n['end']]} for n in json.loads(indexed.stdout)['nodes']]
        node = next(n for n in nodes if n['kind'] == kind and n['source'] == original)
        result = subprocess.run(['node', str(ROOT/'platform/strict_ast_fragments.cjs')],
            input=json.dumps({'source': source, 'nodes': nodes, 'edits': [{'node_id': node['id'], 'code': replacement}]}),
            text=True, capture_output=True)
        return json.loads(result.stdout), nodes

    def test_reprinted_import_block_is_not_a_new_candidate(self):
        source = 'import { Ghost } from "pkg/Ghost";\nimport { Real } from "pkg/Real";'
        result, _ = self.normalize(source, 'ImportDeclaration', 'import { Ghost } from "pkg/Ghost";',
                                   'import {Ghost} from "pkg/Ghost"; import {Real} from "pkg/Real";')
        self.assertTrue(result['ok'], result)
        self.assertEqual(result['edits'], [])

    def test_replacing_missing_dependency_with_existing_import_removes_only_missing_one(self):
        source = 'import { Ghost } from "pkg/Ghost";\nimport { Real } from "pkg/Real";'
        result, _ = self.normalize(source, 'ImportDeclaration', 'import { Ghost } from "pkg/Ghost";', 'import {Real} from "pkg/Real";')
        self.assertTrue(result['ok'], result)
        self.assertEqual(result['edits'], [{'node_id': 'n0', 'code': ''}])

    def test_changed_import_binding_is_preserved_for_native_checks(self):
        source = 'import { Ghost } from "pkg/Ghost";\nimport { Real } from "pkg/Real";'
        result, _ = self.normalize(source, 'ImportDeclaration', 'import { Ghost } from "pkg/Ghost";', 'import { Real as Ghost } from "pkg/Real";')
        self.assertTrue(result['ok'], result)
        self.assertIn('Real as Ghost', result['edits'][0]['code'])

    def test_import_target_cannot_receive_application_statements(self):
        result, _ = self.normalize('import x from "x";const a=1;', 'ImportDeclaration', 'import x from "x";', 'import x from "x";run();')
        self.assertFalse(result['ok'])

    def test_tag_rename_preserves_unicode_children_and_nested_same_name(self):
        source = 'const title="한글";function View(){return <Ghost><section>가나다</section><Ghost>inner</Ghost></Ghost>;}'
        result, nodes = self.normalize(source, 'JsxOpeningElement', '<Ghost>', '<main className="screen">')
        self.assertTrue(result['ok'], result)
        edit = result['edits'][0]
        self.assertEqual(next(n['kind'] for n in nodes if n['id'] == edit['node_id']), 'JsxElement')
        self.assertEqual(edit['code'], '<main className="screen"><section>가나다</section><Ghost>inner</Ghost></main>')

    def test_opening_tag_may_not_smuggle_children_or_statements(self):
        source = 'function View(){return <Ghost>keep</Ghost>;}'
        for code in ['<main>new</main>', '<main/>', '<main>new', '<main></main>;run();']:
            with self.subTest(code=code):
                result, _ = self.normalize(source, 'JsxOpeningElement', '<Ghost>', code)
                self.assertFalse(result['ok'], result)
