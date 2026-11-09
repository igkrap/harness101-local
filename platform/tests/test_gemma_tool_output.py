import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gemma_tool_output import DELIMITER, recover_call, recover_calls


def call(body, ending='<tool_call|><|tool_response>'):
    return '<|tool_call>call:replace_ast_fragments' + body + ending


class GemmaToolOutputTests(unittest.TestCase):
    def test_native_source_strings_are_preserved_exactly(self):
        code = 'const f = () => ({name: "한글", nested: {value: "}"}});\nconst literal="{bare:key}";'
        body = '{changes:[{node_id:' + DELIMITER + 'n4' + DELIMITER + ',code:' + DELIMITER + code + DELIMITER + '}]}'
        result, repaired = recover_call(call(body))
        self.assertEqual(result['arguments'], {'changes': [{'node_id': 'n4', 'code': code}]})
        self.assertFalse(repaired)

    def test_only_missing_outer_object_is_closed(self):
        body = '{changes:[{node_id:' + DELIMITER + 'n4' + DELIMITER + ',code:' + DELIMITER + '<Text>ok</Text>' + DELIMITER + '}]'
        result, repaired = recover_call(call(body, '<turn|>'))
        self.assertTrue(repaired)
        self.assertEqual(result['arguments']['changes'][0]['code'], '<Text>ok</Text>')

    def test_standard_json_strings_are_also_preserved(self):
        args = {'changes': [{'node_id': 'n1', 'code': 'const x="{not:a_key}";\n<Text>"한글"</Text>'}]}
        result, repaired = recover_call(call(json.dumps(args)))
        self.assertEqual(result['arguments'], args)
        self.assertFalse(repaired)

    def test_truncated_source_or_inner_data_is_never_completed(self):
        for body in ['{changes:[{code:' + DELIMITER + 'unfinished', '{changes:[{code:"unfinished', '{changes:[{node_id:"n1",code:"ok"', '{changes:[']:
            with self.subTest(body=body), self.assertRaises(ValueError):
                recover_call(call(body, '<turn|>'))

    def test_duplicate_keys_and_multiple_calls_are_rejected(self):
        for raw in [call('{changes:[],changes:[]}'), call('{changes:[]}') + call('{changes:[]}'), call('{changes:[]} trailing')]:
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                recover_call(raw)

    def test_unknown_function_and_non_tool_text_are_rejected(self):
        for raw in ['<|tool_call>call:run_shell{command:"bad"}<turn|>', 'Explanation ' + call('{changes:[]}'), 'plain text']:
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                recover_call(raw)

    def test_generic_whitespace_keys_and_literal_source_are_preserved(self):
        source = 'const x = {unquoted: "값", brace: "}"};\nreturn <p>{x.unquoted}</p>;'
        raw = '<|tool_call>call:write_file{ path:' + DELIMITER + 'frontend/src/Test.tsx' + DELIMITER + ',\n content: ' + DELIMITER + source + DELIMITER + '}<tool_call|>'
        self.assertEqual(recover_calls(raw, {'write_file'}), [{'name': 'write_file', 'arguments': {'path': 'frontend/src/Test.tsx', 'content': source}}])

    def test_generic_json_source_delimiters_and_multiple_complete_calls_are_preserved(self):
        source = 'const delimiter = \'<|"|>\';\nconst inner = "{field:value}";'
        first = '<|tool_call>call:read_file{path:' + DELIMITER + 'a.tsx' + DELIMITER + '}<tool_call|>'
        second = '<|tool_call>call:write_file' + json.dumps({'path': 'b.tsx', 'content': source}) + '<turn|>'
        calls = recover_calls(first + '\n' + second, {'read_file', 'write_file'})
        self.assertEqual([c['name'] for c in calls], ['read_file', 'write_file'])
        self.assertEqual(calls[1]['arguments']['content'], source)
        self.assertEqual(len(recover_calls('<|tool_call>call:finish{}\ncall:finish{}<turn|>', {'finish'})), 2)

    def test_generic_unknown_duplicate_trailing_and_truncated_calls_are_rejected(self):
        raws = ['<|tool_call>call:run_shell{command:"bad"}<turn|>',
                '<|tool_call>call:write_file{path:"a",path:"b",content:"ok"}<turn|>',
                '<|tool_call>call:write_file{path:"a",content:"complete"<turn|>',
                '<|tool_call>call:write_file{path:"a",content:' + DELIMITER + 'unfinished<turn|>',
                '<|tool_call>call:write_file{path:"a",content:"ok",extra:[1,2}<turn|>',
                '<|tool_call>call:write_file{path:"a",content:"ok"} explanation',
                '<|tool_call>call:write_file{path:"a",content:"ok"} call:run_shell{}',
                '<|tool_call>call:write_file{path:"a",content:"ok"} call:',
                '<|tool_call>call:write_file{path:"a",content:"ok"}<tool_call|><|tool_call>',
                '<|tool_call>call:write_file{path:"a",content:"ok"}<tool_call|><|tool_call><tool_call|>',
                '<|tool_call>call:write_file{path:"a",content:NaN}']
        for raw in raws:
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                recover_calls(raw, {'write_file'})
