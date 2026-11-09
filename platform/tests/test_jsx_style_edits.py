import json
import math
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

import test_ast_recovery_strategy as recovery_tests
from ast_editing import editor
from jsx_style_edits import build_styles


class StyleEditsTests(unittest.TestCase):
    tearDown = recovery_tests.RecoveryStrategyTests.tearDown
    failed = recovery_tests.RecoveryStrategyTests.failed

    def setUp(self):
        recovery_tests.RecoveryStrategyTests.setUp(self)
        self.source = '// 한글 😀\r\nexport default function Demo(){return <main style={{flex:1}}><form style={{minHeight:0}} onSubmit={save}><input/><button>등록</button></form></main>;}\r\n'
        (self.root / self.rel).write_bytes(self.source.encode())
        self.ed = editor(self.r.h)
        self.snap = self.ed.snapshot(self.rel)
        self.nodes = [n for n in self.snap['nodes'] if n['kind'] == 'JsxElement']

    def build(self, updates):
        return build_styles(self.r, self.rel, self.snap['snapshot_id'], updates)

    def converter(self, source, styles, kind='JsxElement'):
        result = subprocess.run([self.ed.service.node, str(Path(__file__).parents[2] / 'local-only/harness/jsx_style_patch.cjs')], input=json.dumps(dict(kind=kind, source=source, styles=styles)), capture_output=True, text=True)
        return result.returncode, json.loads(result.stdout)

    def test_parent_child_styles_are_disjoint_and_preserve_children_events_unicode(self):
        updates = [{'node_id': n['id'], 'styles': {'height': 'calc(100vh - 100px)'}} for n in self.nodes[:2]]
        edits = self.build(updates)
        self.assertEqual(len(edits), 2)
        actual = self.ed.apply(self.rel, self.snap['snapshot_id'], edits)['new_text']
        self.assertIn('onSubmit={save}', actual)
        self.assertIn('<input/><button>등록</button>', actual)
        self.assertTrue(actual.startswith('// 한글 😀\r\n'))
        self.assertTrue(actual.endswith('\r\n'))
        self.assertEqual((self.root / self.rel).read_bytes(), self.source.encode())

    def test_invalid_updates_never_partially_succeed(self):
        good = {'node_id': self.nodes[0]['id'], 'styles': {'height': 400}}
        for invalid in [None, {}, [], [good, good], [good, {'node_id': 'fake', 'styles': {'height': 5}}], [good, {'node_id': self.nodes[1]['id'], 'styles': {}}], [dict(good, code='evil')]]:
            with self.subTest(invalid=invalid), self.assertRaises((ValueError, TypeError)):
                self.build(invalid)
            self.assertEqual((self.root / self.rel).read_bytes(), self.source.encode())

    def test_noop_and_stale_are_rejected(self):
        with self.assertRaises(ValueError):
            self.build([{'node_id': self.nodes[0]['id'], 'styles': {'flex': 1}}])
        edits = self.build([{'node_id': self.nodes[0]['id'], 'styles': {'height': 400}}])
        (self.root / self.rel).write_bytes((self.source + '// user').encode())
        with self.assertRaises(ValueError):
            self.build([{'node_id': self.nodes[0]['id'], 'styles': {'height': 400}}])
        with self.assertRaises(ValueError):
            self.ed.apply(self.rel, self.snap['snapshot_id'], edits)

    def test_converter_preserves_nonstyle_bytes_and_rejects_dynamic_or_invalid_values(self):
        source = '<div title="한글 😀" onClick={save} style={{...base, color:theme.color, height:200}} >\r\n<em>원본</em>\r\n</div>'
        code, out = self.converter(source, {'height': 'calc(100vh - 90px)', 'marginTop': -2})
        self.assertEqual(code, 0, out)
        self.assertTrue(out['code'].startswith('<div title="한글 😀" onClick={save} '))
        self.assertTrue(out['code'].endswith(' >\r\n<em>원본</em>\r\n</div>'))
        self.assertIn('...base', out['code'])
        self.assertIn('theme.color', out['code'])
        for badsource, styles in [('<div style={theme}/>', {'height': 2}), ('<div {...props}/>', {'height': 2}), ('<div/>', {'height': True}), ('<div/>', {'height': {}}), ('<div/>', {'__proto__': 'bad'}), ('<div/>', {'height': math.inf})]:
            code, out = self.converter(badsource, styles, 'JsxSelfClosingElement')
            self.assertNotEqual(code, 0, out)

    def test_string_is_literal_and_samevalue_is_exact_noop(self):
        source = '<div style={{height:20, color:"red"}}>x</div>'
        self.assertEqual(self.converter(source, {'height': 20})[1]['code'], source)
        self.assertEqual(self.converter('<div>x</div>', {'height': None})[1]['code'], '<div>x</div>')
        _, out = self.converter(source, {'height': '"}} onClick={evil} x="'})
        self.assertTrue(out['code'].endswith('>x</div>'))
        self.assertNotIn('onClick={evil} x="', out['code'])

    def test_removal_handles_quoted_and_shorthand_names_without_losing_other_expressions(self):
        source = '<div style={{"height":20, color, minHeight:dynamic(), ...base}}>unchanged</div>'
        status, out = self.converter(source, {'height': None, 'color': 'blue'})
        self.assertEqual(status, 0, out)
        self.assertNotIn('height', out['code'])
        self.assertIn('minHeight: dynamic()', out['code'])
        self.assertIn('...base', out['code'])
        self.assertIn('"color": "blue"', out['code'])
        self.assertTrue(out['code'].endswith('>unchanged</div>'))

    def test_converter_child_mutation_is_rejected_before_application(self):
        fake = type('Result', (), {'returncode': 0, 'stdout': json.dumps({'ok': True, 'code': '<main>hijack</main>'}), 'stderr': ''})()
        with patch('jsx_style_edits.subprocess.run', return_value=fake), self.assertRaises(ValueError):
            self.build([{'node_id': self.nodes[0]['id'], 'styles': {'height': 400}}])
        self.assertEqual((self.root / self.rel).read_bytes(), self.source.encode())

    def test_focused_style_response_uses_native_ast_and_hidden_ids_are_not_model_inputs(self):
        self.failed()
        self.reply = {'content': json.dumps({'path': self.rel, 'style_updates': [{'node_id': self.nodes[0]['id'], 'styles': {'height': '100%'}}]})}
        response = self.r.ask(self.r.messages, [])
        fn = response['tool_calls'][0]['function']
        result = self.r.apply(fn['name'], json.loads(fn['arguments']))
        self.assertIn('"height": "100%"', result['new_text'])
        opening = next(n for n in self.snap['nodes'] if n['kind'] == 'JsxOpeningElement')
        self.failed()
        for payload in [dict(path=self.rel, style_updates=[dict(node_id=opening['id'], styles=dict(height=300))]), dict(path=self.rel, edits=[], style_updates=[])]:
            self.reply = {'content': json.dumps(payload)}
            self.assertFalse(self.r.ask(self.r.messages, [])['tool_calls'])

    def test_style_response_requires_exact_keys_valid_path_and_catalog_id(self):
        from style_response import normalize_response
        files = [dict(path=self.rel, catalog=self.snap['nodes'], snap_id=self.snap['snapshot_id'])]
        for data in [None, [], {}, dict(path=self.rel, edits=[], style_updates=[]), dict(path=self.rel, edits=[], surprise=True), dict(path='outside', edits=[]), dict(path=self.rel, style_updates={}), dict(path=self.rel, style_updates=[dict(node_id=[], styles=dict(height=2))])]:
            with self.subTest(data=data), self.assertRaises(ValueError):
                normalize_response(data, files, self.r)
        self.assertEqual((self.root / self.rel).read_bytes(), self.source.encode())

    def geometry_context(self):
        return json.dumps({'unresolved_checks': [{'reason': 'Native UI requirement: actual_height=265, allowed_height_min=645, allowed_height_max=765'}]})

    def test_measured_geometry_prompt_is_small_and_never_contains_child_body(self):
        from geometry_focus import geometry_prompt
        files = [dict(path=self.rel, catalog=self.snap['nodes'], snap_id=self.snap['snapshot_id'])]
        packet = geometry_prompt(self.r, files, self.geometry_context())
        self.assertIsNotNone(packet)
        text = json.dumps(packet)
        self.assertIn('style_updates', text)
        self.assertNotIn('"height":"100%"', packet[0])
        self.assertIn('onSubmit={save}', text)
        self.assertNotIn('<button>등록</button>', text)
        self.assertLess(len(text), 25000)
        for context in ('{}', 'bad JSON', json.dumps({'unresolved_checks':[{'reason':'right form missing'}]})):
            self.assertIsNone(geometry_prompt(self.r, files, context))

    def test_measured_geometry_mode_rejects_raw_copies_then_accepts_typed_values(self):
        self.failed()
        self.r.requirement_gate.context = self.geometry_context
        node = self.nodes[0]
        self.reply = {'content': json.dumps(dict(path=self.rel, edits=[dict(node_id=node['id'], code=node['source'].replace('flex:1', 'flex:2'))]))}
        self.assertFalse(self.r.ask(self.r.messages, [])['tool_calls'])
        self.reply = {'content': json.dumps(dict(path=self.rel, style_updates=[dict(node_id=node['id'], styles=dict(height='100%'))]))}
        response = self.r.ask(self.r.messages, [])
        self.assertTrue(response['tool_calls'])
        self.assertNotIn('<button>등록</button>', json.dumps(self.sent[-1][0]))
        fn = response['tool_calls'][0]['function']
        self.assertIn('"height": "100%"', self.r.apply(fn['name'], json.loads(fn['arguments']))['new_text'])

    def test_geometry_recovery_persists_until_native_clear_and_escalates_to_shared_parent(self):
        self.failed()
        self.r.requirement_gate.context = self.geometry_context
        self.reply = {'content': json.dumps(dict(path=self.rel, style_updates=[dict(node_id=self.nodes[0]['id'], styles=dict(height='100%'))]))}
        response = self.r.ask(self.r.messages, [])
        fn = response['tool_calls'][0]['function']
        self.r.apply(fn['name'], json.loads(fn['arguments']))
        self.assertTrue(self.r._geometry_recovery_active)
        self.assertGreaterEqual(self.r._ast_recovery_count, 2)
        snap = editor(self.r.h).snapshot('frontend/src/App.tsx')
        node = next(n for n in snap['nodes'] if n['kind'] == 'JsxElement')
        self.reply = {'content': json.dumps(dict(path='frontend/src/App.tsx', style_updates=[dict(node_id=node['id'], styles=dict(height='100%'))]))}
        response = self.r.ask(self.r.messages, [])
        payload = json.loads(self.sent[-1][0][1]['content'])
        self.assertEqual({n['path'] for n in payload['catalog']}, {'frontend/src/App.tsx'})
        self.assertTrue(response['tool_calls'])
        self.r.requirement_gate.context = lambda: '{}'
        self.reply = {'content': '{}'}
        self.r.ask(self.r.messages, [])
        self.assertFalse(self.r._geometry_recovery_active)

    def test_native_height_failure_enters_recovery_before_any_bad_tool_calls(self):
        self.r.requirement_gate.context = self.geometry_context
        self.r.requirement_gate.stage = {'paths': [self.rel]}
        self.reply = {'content': json.dumps(dict(path=self.rel, style_updates=[dict(node_id=self.nodes[0]['id'], styles=dict(height='100%'))]))}
        response = self.r.ask(self.r.messages, ['raw-edit-tools'])
        self.assertTrue(response['tool_calls'])
        self.assertEqual(self.sent[-1][1], [])
        self.assertTrue(self.r._geometry_recovery_active)
        self.assertEqual(self.r._ast_recovery_path, self.rel)

    def test_geometry_feedback_preserves_error_and_removes_conflicting_stage_scope(self):
        from geometry_focus import geometry_prompt
        self.r._geometry_attempts = 3
        self.r._ast_recovery_error = 'node_id main-content-area not found in catalog'
        self.r.args.task = 'CONFLICTING_PRIMARY_SCOPE'
        context = json.loads(self.geometry_context())
        context['original_task'] = 'original layout goal'
        context['stage'] = {'instructions': 'CONFLICTING_STAGE_SCOPE'}
        files = [dict(path=self.rel, catalog=self.snap['nodes'], snap_id=self.snap['snapshot_id'])]
        packet = geometry_prompt(self.r, files, json.dumps(context))
        payload = json.loads(packet[1])
        self.assertEqual(payload['last_error'], self.r._ast_recovery_error)
        self.assertEqual(payload['attempt'], 3)
        self.assertIn('original layout goal', packet[1])
        self.assertNotIn('CONFLICTING', packet[1])

    def test_geometry_catalog_tracks_real_parent_chain_in_source_order(self):
        from geometry_focus import geometry_prompt
        catalog = [n for n in self.snap['nodes'] if not (n['kind'] == 'JsxOpeningElement' and 'complete JSX node ' in n['label'])]
        files = [dict(path=self.rel, catalog=catalog, snap_id=self.snap['snapshot_id'])]
        payload = json.loads(geometry_prompt(self.r, files, self.geometry_context())[1])
        entries = {n['node_id']: n for n in payload['catalog']}
        root = self.nodes[0]
        form = self.nodes[1]
        self.assertIsNone(entries[root['id']]['parent_node_id'])
        self.assertEqual(entries[form['id']]['parent_node_id'], root['id'])
        self.assertGreater(entries[form['id']]['depth'], entries[root['id']]['depth'])
        self.assertEqual(payload['catalog'][0]['node_id'], root['id'])
        self.assertTrue(all('source_order' not in n for n in payload['catalog']))
