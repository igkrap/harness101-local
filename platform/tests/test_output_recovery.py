import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'local-only/harness'))
from output_recovery import extend_output
from context_budget import measure

class OutputRecoveryTests(unittest.TestCase):
    def test_truncated_ast_uses_smaller_deltas_without_growing_or_applying_partial_call(self):
        tools=[{'function':{'name':'replace_ast_fragments'}}]
        partial={'content':'', 'tool_calls':[{'function':{'name':'replace_ast_fragments','arguments':'{"changes":['}}]}
        r=self.runner([('length',partial)])
        with patch.dict(os.environ,{'LOCAL_LLM_MAX_TOKENS':'4096'}):
            response=r.ask([{'role':'user','content':'fix candidate'}],tools)
            self.assertEqual(r.used,1)
            self.assertTrue(r._compact_fragment_output)
            self.assertFalse(response.get('tool_calls'))
            self.assertIn('two small fragments',response['_provider_error'])
            self.assertEqual(os.environ['LOCAL_LLM_MAX_TOKENS'],'4096')
    def runner(self,replies,limit=0):
        owner=self
        class Base:
            def __init__(self):self.used=0;self.args=SimpleNamespace(max_rounds=limit);self.h=SimpleNamespace(llm=SimpleNamespace(),log_event=Mock());self.sent=[]
            def ask(self,messages,tools):
                if self.args.max_rounds>0 and self.used>=self.args.max_rounds:raise RuntimeError('budget')
                self.used+=1;self.sent.append((messages,tools,dict(os.environ)));reason,response=replies.pop(0);self.h.llm.last_finish_reason=reason;return response
        return extend_output(Base)()
    def test_empty_truncation_retries_with_more_output_and_thinking_disabled_temporarily(self):
        result={'content':'complete','tool_calls':[]};r=self.runner([('length',{'content':''}),('stop',result)]);messages=[{'role':'user','content':'change layout'}];before=json.dumps(messages)
        with patch.dict(os.environ,{'LOCAL_LLM_MAX_TOKENS':'4096','LOCAL_LLM_THINKING':'true'}):
            self.assertIs(r.ask(messages,[]),result);self.assertEqual(r.used,2);self.assertEqual(os.environ['LOCAL_LLM_MAX_TOKENS'],'8192');self.assertEqual(os.environ['LOCAL_LLM_THINKING'],'true');self.assertEqual(r.sent[1][2]['LOCAL_LLM_THINKING'],'false');self.assertEqual(json.dumps(messages),before)
            self.assertLessEqual(measure(r.sent[1][0],[])['estimated_input_tokens']+8192,32768)
    def test_partial_or_valid_tool_output_not_retried_and_no_false_completion(self):
        result={'content':'','tool_calls':[{'function':{'name':'apply_ast_edits','arguments':'{"edits":['}}]};r=self.runner([('length',result)])
        with patch.dict(os.environ,{'LOCAL_LLM_MAX_TOKENS':'4096'}):self.assertIs(r.ask([{'role':'user','content':'task'}],[]),result);self.assertEqual(r.used,1)
    def test_explicit_round_limit_and_maximum_output_limit_remain_enforced(self):
        for output,rounds in [('4096',1),('12288',0)]:
            result={'content':''};r=self.runner([('length',result)],rounds)
            with patch.dict(os.environ,{'LOCAL_LLM_MAX_TOKENS':output}):self.assertIs(r.ask([{'role':'user','content':'task'}],[]),result);self.assertEqual(r.used,1);self.assertLessEqual(int(os.environ['LOCAL_LLM_MAX_TOKENS']),12288)
    def test_temporary_mode_restored_on_retry_failure(self):
        r=self.runner([('length',{'content':''})])
        with patch.dict(os.environ,{'LOCAL_LLM_MAX_TOKENS':'4096'},clear=True):
            with self.assertRaises(IndexError):r.ask([{'role':'user','content':'task'}],[])
            self.assertNotIn('LOCAL_LLM_THINKING',os.environ)
    def test_growth_leaves_space_for_prompt_and_retry_instruction(self):
        result={'content':'partial'};r=self.runner([('length',result)])
        messages=[{'role':'user','content':'x'*81000}]
        with patch.dict(os.environ,{'LOCAL_LLM_MAX_TOKENS':'4096'}):
            self.assertIs(r.ask(messages,[]),result);maximum=int(os.environ['LOCAL_LLM_MAX_TOKENS']);self.assertLessEqual(measure(messages,[])['estimated_input_tokens']+maximum,32768)
    def test_ordinary_mock_harness_without_finish_reason_is_unchanged(self):
        class Base:
            h=SimpleNamespace()
            def ask(self,messages,tools):return {'content':'normal'}
        self.assertEqual(extend_output(Base)().ask([],[])['content'],'normal')
