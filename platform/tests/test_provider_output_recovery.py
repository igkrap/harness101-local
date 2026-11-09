import json
from pathlib import Path
import sys
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from provider_output_recovery import recover_empty


class ProviderOutputRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)
        self.model = 'mlx-community/gemma-4-fixture'
        tokenizer = self.home / '.cache/huggingface/hub/models--mlx-community--gemma-4-fixture/snapshots/one/tokenizer.json'
        tokenizer.parent.mkdir(parents=True)
        tokenizer.write_text('{}')

    def reply(self):
        return {'choices': [{'message': {'role': 'assistant'}, 'finish_reason': 'stop', 'logprobs': {'content': [{'id': 48}, {'id': 49}]}}]}

    def test_generated_tokens_recover_an_explicit_call_and_only_outer_brace(self):
        raw = '<|tool_call>call:replace_ast_fragments{changes:[{node_id:<|"|>n1<|"|>,code:<|"|><Text>한글</Text><|"|>}]<turn|>'
        with patch('provider_output_recovery.Path.home', return_value=self.home), patch('provider_output_recovery.subprocess.run', return_value=SimpleNamespace(stdout=json.dumps({'text': raw}))) as decode:
            result = recover_empty(self.reply(), self.model)
        self.assertTrue(result['provider_recovery']['recovered'])
        self.assertTrue(result['provider_recovery']['outer_brace_completed'])
        self.assertEqual(result['choices'][0]['finish_reason'], 'tool_calls')
        args = json.loads(result['choices'][0]['message']['tool_calls'][0]['function']['arguments'])
        self.assertEqual(args, {'changes': [{'node_id': 'n1', 'code': '<Text>한글</Text>'}]})
        self.assertEqual(json.loads(decode.call_args.kwargs['input'])['ids'], [48, 49])

    def test_unfinished_source_is_an_explicit_error_and_never_a_tool_action(self):
        raw = '<|tool_call>call:replace_ast_fragments{changes:[{code:<|"|>unfinished<turn|>'
        with patch('provider_output_recovery.Path.home', return_value=self.home), patch('provider_output_recovery.subprocess.run', return_value=SimpleNamespace(stdout=json.dumps({'text': raw}))):
            result = recover_empty(self.reply(), self.model)
        self.assertFalse(result['provider_recovery']['recovered'])
        message = result['choices'][0]['message']
        self.assertIn('Truncated tool source string', message['_provider_error'])
        self.assertNotIn('tool_calls', message)

    def test_valid_action_is_unchanged_without_decoding(self):
        reply = {'choices': [{'message': {'role': 'assistant', 'tool_calls': [{'function': {'name': 'replace_ast_fragments', 'arguments': '{}'}}]}}]}
        with patch('provider_output_recovery.subprocess.run', side_effect=AssertionError('unexpected decoding')):
            self.assertIs(recover_empty(reply, self.model), reply)

    def test_missing_token_ids_is_reported_without_regenerating_or_fabricating_source(self):
        result = recover_empty({'choices': [{'message': {'role': 'assistant'}}]}, self.model)
        self.assertFalse(result['provider_recovery']['recovered'])
        self.assertIn('omitted generated token IDs', result['choices'][0]['message']['content'])

    def write_tools(self):
        return [{'type':'function','function':{'name':'write_file','parameters':{
            'type':'object','properties':{'path':{'type':'string'},'content':{'type':'string'}},
            'required':['path','content'],'additionalProperties':False}}}]

    def recover_generic(self, raw, tools=None):
        # Decode fixture tokens without loading a model; exercise the real schema validator.
        run = subprocess.run
        def fake_decode(command, **kwargs):
            if str(command[1]).endswith('mlx_token_decode.py'):
                return SimpleNamespace(stdout=json.dumps({'text':raw}), returncode=0)
            return run(command, **kwargs)
        with patch('provider_output_recovery.Path.home', return_value=self.home), \
                patch('provider_output_recovery.subprocess.run', side_effect=fake_decode):
            return recover_empty(self.reply(), self.model, tools or self.write_tools())

    def test_generic_whitespace_output_recovers_offered_call_and_exact_content(self):
        source = 'export default function X(){return <p>{"한글"}</p>;}\n'
        raw = '<|tool_call>call:write_file{ path:<|"|>frontend/src/X.tsx<|"|>, content:<|"|>' + source + '<|"|>}<turn|>'
        result = self.recover_generic(raw)
        self.assertTrue(result['provider_recovery']['recovered'])
        self.assertFalse(result['provider_recovery']['outer_brace_completed'])
        calls = result['choices'][0]['message']['tool_calls']
        self.assertEqual(json.loads(calls[0]['function']['arguments'])['content'], source)

    def test_unknown_schema_invalid_and_truncated_calls_never_become_actions(self):
        for raw in ['<|tool_call>call:run_shell{}<turn|>',
                    '<|tool_call>call:write_file{path:9,content:"ok"}<turn|>',
                    '<|tool_call>call:write_file{path:"a"}<turn|>',
                    '<|tool_call>call:write_file{path:"a",content:"ok",extra:true}<turn|>',
                    '<|tool_call>call:write_file{path:"a",content:"ok"<turn|>']:
            with self.subTest(raw=raw):
                result = self.recover_generic(raw)
                self.assertFalse(result['provider_recovery']['recovered'])
                self.assertNotIn('tool_calls', result['choices'][0]['message'])

    def test_multiple_calls_require_all_calls_to_match_offered_schemas(self):
        tools = self.write_tools() + [{'function':{'name':'read_file','parameters':{
            'type':'object','properties':{'path':{'type':'string'}},'required':['path']}}}]
        raw = '<|tool_call>call:read_file{path:"a"}\ncall:write_file{path:"b",content:"model source"}<turn|>'
        result = self.recover_generic(raw, tools)
        self.assertEqual(result['provider_recovery']['tool_names'], ['read_file','write_file'])
        bad = self.recover_generic(raw.replace('content:"model source"', 'content:17'), tools)
        self.assertFalse(bad['provider_recovery']['recovered'])
        self.assertNotIn('tool_calls', bad['choices'][0]['message'])

    def test_plain_content_reasoning_and_existing_calls_are_never_redecoded(self):
        for message in [{'role':'assistant','content':'answer'}, {'role':'assistant','reasoning':'thinking'},
                        {'role':'assistant','tool_calls':[{'function':{'name':'read_file','arguments':'{}'}}]}]:
            reply = {'choices':[{'message':message}]}
            with patch('provider_output_recovery.subprocess.run', side_effect=AssertionError('must not decode')):
                self.assertIs(recover_empty(reply, self.model, self.write_tools()), reply)

    def test_boolean_token_id_is_rejected_before_decode(self):
        reply = self.reply(); reply['choices'][0]['logprobs']['content'][0]['id'] = True
        with patch('provider_output_recovery.subprocess.run', side_effect=AssertionError('must not decode')):
            result = recover_empty(reply, self.model, self.write_tools())
        self.assertFalse(result['provider_recovery']['recovered'])
