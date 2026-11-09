import unittest
from types import SimpleNamespace

import test_candidate_repair
from candidate_blocks import parse_blocks, format_candidate_context


class CandidateBlockTests(unittest.TestCase):
    def test_raw_code_preserves_unicode_quotes_newlines_and_backslashes(self):
        code = '<VStack>\r\n  <Text title="이름 😀">{String.raw`\\n`}</Text>\r\n</VStack>'
        result = parse_blocks('EDIT n33\n```tsx\n' + code + '\n```\nREMOVE n4\n')
        self.assertEqual(result, {'changes':[{'node_id':'n33','code':code}], 'remove':['n4']})

    def test_headers_inside_code_remain_literal_and_multiple_blocks_keep_order(self):
        code = 'const sample = `\nEDIT n99\nREMOVE n88\n`;'
        result = parse_blocks('EDIT s1\n```ts\n'+code+'\n```\n\nEDIT n8\n```\n<div/>\n```\n')
        self.assertEqual(result['changes'][0]['code'], code)
        self.assertEqual([e['node_id'] for e in result['changes']], ['s1','n8'])
        self.assertEqual(result['remove'], [])

    def test_bad_or_ambiguous_blocks_fail_atomically(self):
        valid = 'EDIT n1\n```tsx\n<div/>\n```\n'
        cases = ['', 'prose\n'+valid, 'EDIT n1\n<div/>', 'EDIT n1\n```tsx\n<div/>', 'EDIT n1\n```tsx\n \n```', valid+valid, valid+'REMOVE n1\n', 'REMOVE n1\nREMOVE n1\n', 'EDIT ../bad\n```tsx\n<div/>\n```', 'EDIT /bad\n```tsx\n<div/>\n```', 'EDIT n1\n```python\n<div/>\n```', 'EDIT n1\n```tsx extra\n<div/>\n```', valid+'unexpected text']
        for case in cases:
            with self.subTest(case=case), self.assertRaises(ValueError):
                parse_blocks(case)

    def test_bounds_and_nonstring_are_rejected(self):
        for response in [None, {}, 'EDIT n1\n```tsx\n'+'x'*12001+'\n```', ''.join(f'EDIT n{i}\n```tsx\n<div/>\n```\n' for i in range(9)), ''.join(f'REMOVE n{i}\n' for i in range(9))]:
            with self.subTest(response=str(response)[:80]), self.assertRaises(ValueError):
                parse_blocks(response)

    def test_readable_context_includes_real_code_retained_companions_and_feedback(self):
        runner = SimpleNamespace(args=SimpleNamespace(task='우측 등록 폼'), feedback='two forms', _candidate_focus_error='wrong node kind')
        source = '<form onSubmit={save}>\n<TextInput label="이름"/>\n</form>'
        proposal = dict(path='frontend/src/App.tsx',snapshot_id='s',source_hash='h',edits=[dict(node_id='n3',code=source)])
        catalog = [dict(id='n3',kind='JsxElement',label='register form',source=source),dict(id='s1',kind='insert',label='local statements only',source='')]
        text = format_candidate_context(runner,proposal,catalog)
        self.assertIn(source,text)
        self.assertIn('two forms',text)
        self.assertIn('wrong node kind',text)
        self.assertIn('local statements only',text)
        self.assertIn('frontend/src/App.tsx',text)

    def test_explicit_drop_edit_alias_keeps_legacy_protocol_and_rejects_duplicate_cancellation(self):
        self.assertEqual(parse_blocks('DROP_EDIT s2\n'),{'changes':[],'remove':['s2']})
        self.assertEqual(parse_blocks('REMOVE s2\n'),{'changes':[],'remove':['s2']})
        with self.assertRaises(ValueError):
            parse_blocks('REMOVE s2\nDROP_EDIT s2\n')
