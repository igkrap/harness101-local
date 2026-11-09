import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'local-only/harness'))
from candidate_snippet_tools import parse_tool_patches, tool_spec


class NativeSnippetToolsTests(unittest.TestCase):
    catalog = {'n1': {}, 's2': {}}

    def response(self, args):
        return {'tool_calls': [{'function': {'name': 'apply_snippet_patch', 'arguments': args}}]}

    def test_schema_limits_targets_to_active_nodes(self):
        schema = tool_spec(self.catalog)['function']['parameters']
        self.assertEqual(schema['properties']['patches']['items']['properties']['node_id']['enum'], ['n1', 's2'])

    def test_native_message_without_content_and_multiple_calls(self):
        patch = {'node_id': 'n1', 'old_text': 'before', 'new_text': 'after'}
        response = self.response(json.dumps({'patches': [patch]}))
        response['tool_calls'] += self.response({'patches': [dict(patch, node_id='s2')]})['tool_calls']
        self.assertEqual(parse_tool_patches(response, self.catalog), [patch, dict(patch, node_id='s2')])
        self.assertIsNone(parse_tool_patches({'content': 'legacy'}, self.catalog))

    def test_actual_argument_validator_rejects_invalid_calls(self):
        patch = {'node_id': 'n1', 'old_text': 'a', 'new_text': 'b'}
        for args in [{'patches': [dict(patch, node_id='fake')]}, {'patches': [dict(patch, extra=True)]}, {'patches': [dict(patch, new_text=3)]}, {'patches': []}, {'extra': True}, {'patches': [patch] * 9}]:
            with self.subTest(args=args), self.assertRaises((ValueError, RuntimeError)):
                parse_tool_patches(self.response(json.dumps(args)), self.catalog)

    def test_duplicate_keys_and_aggregate_overflow_are_rejected(self):
        with self.assertRaises(ValueError):
            parse_tool_patches(self.response('{"patches":[],"patches":[]}'), self.catalog)
        patch = {'node_id': 'n1', 'old_text': 'a', 'new_text': 'b'}
        response = self.response({'patches': [patch] * 5})
        response['tool_calls'] *= 2
        with self.assertRaises(ValueError):
            parse_tool_patches(response, self.catalog)
