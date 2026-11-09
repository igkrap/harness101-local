import copy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'local-only/harness'))
from new_file_repair_tool import TOOL, parse_response


class NewFileRepairToolTests(unittest.TestCase):
    def response(self, data=None, name='repair_new_file', content=None):
        if data is None:
            data = {'edits': [{'old_text': 'import unused;\n', 'new_text': ''}]}
        arguments = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)
        return {'role': 'assistant', 'content': content, 'tool_calls': [
            {'type': 'function', 'id': 'model-call', 'function': {'name': name, 'arguments': arguments}}
        ]}

    def test_model_source_and_empty_replacement_are_preserved_exactly(self):
        data = {'edits': [
            {'old_text': 'const title = "한글 {key:value}";\n', 'new_text': 'const title = "새 값";\n'},
            {'old_text': 'import unused;\n', 'new_text': ''},
        ]}
        returned, drafts, kind = parse_response(self.response(data))
        self.assertEqual(returned, data)
        self.assertEqual((drafts, kind), (0, 'tool'))

    def test_unknown_multiple_and_malformed_calls_cannot_fall_back_to_text(self):
        fallback = Mock(side_effect=AssertionError('must not use fallback'))
        multiple = self.response(); multiple['tool_calls'] *= 2
        malformed = self.response(); malformed['tool_calls'][0]['function']['arguments'] = {'edits': []}
        for response in [self.response(name='write_file'), multiple, malformed, {'tool_calls': {}}]:
            with self.subTest(response=response), self.assertRaises(ValueError):
                parse_response(response, legacy_parser=fallback)
        fallback.assert_not_called()

    def test_duplicate_keys_and_mixed_prose_or_drafts_are_rejected(self):
        for arguments in ['{"edits":[],"edits":[]}',
                '{"edits":[{"old_text":"a","old_text":"b","new_text":"c"}]}',
                '{"edits":[{"old_text":"a","new_text":"b"}]} trailing',
                '{"edits":[{"old_text":"a","new_text":"b"}]}{}']:
            with self.subTest(arguments=arguments), self.assertRaises(ValueError):
                parse_response(self.response(arguments))
        for content in ['Here is my repair', '{"edits":[]}']:
            with self.subTest(content=content), self.assertRaises(ValueError):
                parse_response(self.response(content=content))

    def test_shape_size_types_and_noops_are_rejected(self):
        invalid = [{}, {'edits': [], 'path': 'New.tsx'}, {'edits': []}, {'edits': {}},
            {'edits': [{'old_text': 'a', 'new_text': 'b'}] * 9}]
        for edit in [{'old_text': '', 'new_text': 'b'}, {'old_text': 'a', 'new_text': 1},
                     {'old_text': 'a', 'new_text': 'a'}, {'old_text': 'a' * 3001, 'new_text': ''},
                     {'old_text': 'a', 'new_text': 'b' * 3001},
                     {'old_text': 'a', 'new_text': 'b', 'range': [1, 2]}]:
            invalid.append({'edits': [edit]})
        for data in invalid:
            with self.subTest(data=str(data)[:100]), self.assertRaises(ValueError):
                parse_response(self.response(data))

    def test_legacy_fallback_is_explicit_and_only_for_absent_calls(self):
        from focused_repair import final_json
        content = '```json\n{"edits":[{"old_text":"a","new_text":"b"}]}\n```'
        with self.assertRaises(ValueError):
            parse_response({'content': content})
        data, drafts, kind = parse_response({'content': content}, legacy_parser=final_json)
        self.assertEqual(data, {'edits': [{'old_text': 'a', 'new_text': 'b'}]})
        self.assertEqual((drafts, kind), (1, 'legacy-json'))
        with self.assertRaises(ValueError):
            parse_response({'content': '{"edits":[],"edits":[]}'}, legacy_parser=final_json)

    def test_tool_schema_is_enforced_by_existing_argument_validator(self):
        from types import SimpleNamespace
        from tool_input_validation import validate_arguments
        runner = SimpleNamespace(tools=lambda: [TOOL])
        valid = {'edits': [{'old_text': 'old', 'new_text': ''}]}
        validate_arguments(runner, 'repair_new_file', valid)
        invalid = copy.deepcopy(valid); invalid['edits'][0]['newText'] = invalid['edits'][0].pop('new_text')
        with self.assertRaisesRegex(ValueError, 'TOOL_INPUT_INVALID'):
            validate_arguments(runner, 'repair_new_file', invalid)

    def test_provider_failure_is_not_hidden_by_an_apparently_valid_call(self):
        response = self.response(); response['_provider_error'] = 'Truncated tool source string'
        with self.assertRaisesRegex(ValueError, 'Truncated tool source string'):
            parse_response(response)


if __name__ == '__main__':
    unittest.main()
