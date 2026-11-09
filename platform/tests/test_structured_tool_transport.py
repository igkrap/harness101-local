import json
import sys
import unittest
from pathlib import Path
from urllib.request import Request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from structured_tool_transport import require_fragment_tool, capture_gemma_tools


class StructuredToolTransportTests(unittest.TestCase):
    def request(self, tools, url='http://127.0.0.1:8099/v1/chat/completions'):
        payload = {'model': 'selected-model', 'messages': [{'role': 'user', 'content': '원래 작업'}],
                   'tools': tools, 'tool_choice': 'auto', 'max_tokens': 4096, 'temperature': .2}
        return Request(url, json.dumps(payload).encode(), {'Content-Type': 'application/json'})

    def test_ast_action_uses_named_tool_without_altering_model_or_task(self):
        request = self.request([{'type': 'function', 'function': {'name': 'replace_ast_fragments', 'parameters': {'type': 'object'}}}])
        original = json.loads(request.data)
        self.assertTrue(require_fragment_tool(request))
        current = json.loads(request.data)
        self.assertEqual(current['tool_choice'], {'type': 'function', 'function': {'name': 'replace_ast_fragments'}})
        self.assertEqual({k: v for k, v in current.items() if k != 'tool_choice'}, {k: v for k, v in original.items() if k != 'tool_choice'})

    def test_planning_and_normal_tool_selection_are_unchanged(self):
        for tools in [[], [{'function': {'name': 'read_file'}}], [{'function': {'name': 'replace_ast_fragments'}}, {'function': {'name': 'finish'}}]]:
            request = self.request(tools)
            original = request.data
            self.assertFalse(require_fragment_tool(request))
            self.assertEqual(request.data, original)

    def test_new_file_repair_uses_named_tool_without_changing_task(self):
        request = self.request([{'type': 'function', 'function': {'name': 'repair_new_file', 'parameters': {'type': 'object'}}}])
        original = json.loads(request.data)
        self.assertTrue(require_fragment_tool(request))
        current = json.loads(request.data)
        self.assertEqual(current['tool_choice'], {'type': 'function', 'function': {'name': 'repair_new_file'}})
        self.assertEqual({k: v for k, v in current.items() if k != 'tool_choice'}, {k: v for k, v in original.items() if k != 'tool_choice'})

    def test_nonlocal_request_is_unchanged(self):
        request = self.request([{'function': {'name': 'replace_ast_fragments'}}], 'https://example.invalid/v1/chat/completions')
        original = request.data
        self.assertFalse(require_fragment_tool(request))
        self.assertEqual(request.data, original)

    def test_local_gemma_action_preserves_generated_tokens_for_lossless_recovery(self):
        request = self.request([{'function': {'name': 'replace_ast_fragments'}}])
        payload = json.loads(request.data)
        payload['model'] = 'mlx-community/gemma-4-26B-A4B-it-OptiQ-4bit'
        request.data = json.dumps(payload).encode()
        self.assertTrue(require_fragment_tool(request))
        self.assertTrue(json.loads(request.data)['logprobs'])

    def test_normal_gemma_tools_capture_chosen_tokens_without_changing_tool_selection(self):
        request = self.request([{'function':{'name':'write_file','parameters':{'type':'object'}}},
                                {'function':{'name':'read_file','parameters':{'type':'object'}}}])
        payload = json.loads(request.data); payload.update(model='local/gemma4-model', top_logprobs=3)
        request.data = json.dumps(payload).encode()
        captured = capture_gemma_tools(request)
        self.assertTrue(captured['logprobs'])
        self.assertEqual(captured['top_logprobs'], 0)
        self.assertEqual(captured['tool_choice'], 'auto')
        self.assertEqual({k:v for k,v in captured.items() if k not in ('logprobs','top_logprobs')},
                         {k:v for k,v in payload.items() if k not in ('logprobs','top_logprobs')})

    def test_capture_leaves_planning_non_gemma_and_nonlocal_requests_unchanged(self):
        for tools, model, url in [([], 'local/gemma-4-model', 'http://127.0.0.1:8099/v1/chat/completions'),
                ([{'function':{'name':'read_file'}}], 'other-model', 'http://127.0.0.1:8099/v1/chat/completions'),
                ([{'function':{'name':'read_file'}}], 'local/gemma-4-model', 'https://example.invalid/v1/chat/completions')]:
            request = self.request(tools, url); payload = json.loads(request.data); payload['model'] = model
            request.data = json.dumps(payload).encode(); original = request.data
            self.assertIsNone(capture_gemma_tools(request))
            self.assertEqual(request.data, original)
