import json
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[2]


class DeclarationGroups(unittest.TestCase):
    def normalize(self, source, edits):
        indexed = subprocess.run(['node', str(ROOT/'local-only/harness/ast_edit_ranges.cjs')],
            input=json.dumps({'path': 'fixture.tsx', 'source': source}), text=True, capture_output=True, check=True)
        nodes = [{**n, 'range': [n['start'], n['end']]} for n in json.loads(indexed.stdout)['nodes']]
        selected = [{'node_id': next(n['id'] for n in nodes if n['kind'] == 'VariableStatement' and n['source'] == original),
                     'code': code} for original, code in edits]
        result = subprocess.run(['node', str(ROOT/'platform/strict_ast_fragments.cjs')],
            input=json.dumps({'source': source, 'nodes': nodes, 'edits': selected}), text=True, capture_output=True)
        return json.loads(result.stdout), nodes

    def test_unicode_byte_ranges_and_semicolonless_declarations(self):
        source = 'const title="한글"; function Screen(){\nconst first=1\nconst peer=2\nreturn first+peer\n}'
        result, nodes = self.normalize(source, [('const first=1', 'const first=1; const added=3; const peer=2;')])
        self.assertTrue(result['ok'], result)
        self.assertEqual(len(result['edits']), 1)
        self.assertIn('const added=3;', result['edits'][0]['code'])
        self.assertNotIn('peer', result['edits'][0]['code'])

    def test_exact_repeated_effect_is_not_executed_twice(self):
        source = 'function Screen(){const first=1; runEffect(); return first;}'
        result, _ = self.normalize(source, [('const first=1;', 'const first=1; runEffect(); const added=3;')])
        self.assertTrue(result['ok'], result)
        self.assertNotIn('runEffect', result['edits'][0]['code'])

    def test_peer_changes_stay_in_the_same_block(self):
        source = 'function Screen(){const first=1;const peer=2;const nested=()=>{const peer=99;return peer;};return first+peer+nested();}'
        result, nodes = self.normalize(source, [('const first=1;', 'const first=3;const peer=4;')])
        self.assertTrue(result['ok'], result)
        touched = {e['node_id'] for e in result['edits']}
        self.assertIn(next(n['id'] for n in nodes if n['source'] == 'const peer=2;'), touched)
        self.assertNotIn(next(n['id'] for n in nodes if n['source'].startswith('const nested=')), touched)

    def test_ambiguous_or_out_of_scope_group_is_rejected(self):
        source = 'function Screen(param){const first=1;const peer=2;return first+peer;}'
        for code in ['const added=3;const other=4;', 'const first=1;sideEffect();',
                     'const first=1;export const added=3;', 'const first=1;const first=2;',
                     'const first=1;const param=2;', 'const first=1;return <main/>;']:
            with self.subTest(code=code):
                result, _ = self.normalize(source, [('const first=1;', code)])
                self.assertFalse(result['ok'], result)

    def test_conflicting_explicit_peer_edits_are_rejected(self):
        source = 'function Screen(){const first=1;const peer=2;return first+peer;}'
        result, _ = self.normalize(source, [('const first=1;', 'const first=1;const peer=3;'), ('const peer=2;', 'const peer=4;')])
        self.assertFalse(result['ok'])
        self.assertIn('Conflicting', result['error'])

    def test_module_metadata_is_not_a_local_declaration_group(self):
        result, _ = self.normalize('export const meta={title:"A"};', [('export const meta={title:"A"};', 'export const meta={title:"B"};const extra=1;')])
        self.assertFalse(result['ok'])

    def test_explicit_contiguous_reorder_preserves_the_model_order(self):
        source = 'function Screen(){const id=1;const selected=items[0];const items=[];return selected;}'
        result, nodes = self.normalize(source, [('const id=1;', 'const id=1;const items=[];const selected=items[0];')])
        self.assertTrue(result['ok'], result)
        replacements = {e['node_id']: e['code'] for e in result['edits']}
        declarations = [replacements.get(n['id'], n['source']) for n in nodes if n['kind'] == 'VariableStatement']
        self.assertEqual(declarations, ['const id=1;', 'const items=[];', 'const selected=items[0];'])

    def test_reorder_cannot_cross_omitted_effects(self):
        cases = [
            ('function Screen(){const id=1;const selected=items[0];effect();const items=[];return selected;}',
             'const id=1;const items=[];const selected=items[0];'),
            ('function Screen(){const id=1;const selected=items[0];const omitted=3;const items=[];return selected;}',
             'const id=1;const items=[];const selected=items[0];'),
        ]
        for source, code in cases:
            with self.subTest(source=source):
                result, _ = self.normalize(source, [('const id=1;', code)])
                self.assertFalse(result['ok'], result)
                self.assertIn('contiguous', result['error'])

    def test_same_reorder_repeated_at_each_covered_node_is_deduplicated(self):
        source = 'function Screen(){const id=1;const selected=items[0];const items=[];return selected;}'
        ordered = 'const id=1;const items=[];const selected=items[0];'
        result, _ = self.normalize(source, [(original, ordered) for original in ['const id=1;', 'const selected=items[0];', 'const items=[];']])
        self.assertTrue(result['ok'], result)
        self.assertEqual(len(result['edits']), 2)
