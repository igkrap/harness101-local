import copy
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import Mock
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'local-only/harness'))
from context_budget import extend_context,measure


class RetentionTests(unittest.TestCase):
    def runner(self):
        class Base:
            def tools(self):return []
            def fresh(self,reason=''):
                self.rebuilt+=1
                self.messages=[{'role':'system','content':'rules'},{'role':'user','content':'fallback source'}]
            def ask(self,messages,tools):
                self.sent=copy.deepcopy(messages)
                return {'message_count':len(messages)}
        r=extend_context(Base)()
        r.rebuilt=0;r.h=SimpleNamespace(log_event=Mock())
        r.read={'frontend/src/screens/Inventory.tsx'}
        r.args=SimpleNamespace(task='Change inventory layout')
        r.steps=[{'kind':'change','title':r.args.task}];r.step=0
        r.feedback='expected 400 but observed 600';r.baseline_feedback='baseline passed'
        r.requirement_gate=SimpleNamespace(context=lambda:'IMMUTABLE_CONTRACT_C1')
        r.messages=[{'role':'system','content':'s'*17000},{'role':'user','content':'stale snapshot '*2800}]
        return r

    def group(self,id='ast1',size=8000):
        return [{'role':'assistant','content':None,'tool_calls':[{'id':id,'type':'function','function':{'name':'inspect_code','arguments':'{}'}}]},
                {'role':'tool','tool_call_id':id,'content':json.dumps({'snapshot_id':id,'nodes':[{'id':'jsx9','source':'x'*size}]})}]

    def test_budget_pressure_preserves_latest_ast_and_edit_authorization(self):
        r=self.runner();group=self.group();r.messages+=group
        self.assertGreater(measure(r.messages)['pressure'],.8)
        r.ask(r.messages,[])
        self.assertEqual(r.rebuilt,0)
        self.assertEqual(r.sent[-2:],group)
        self.assertIn('IMMUTABLE_CONTRACT_C1',r.sent[1]['content'])
        self.assertIn('expected 400 but observed 600',r.sent[1]['content'])
        self.assertIn('frontend/src/screens/Inventory.tsx',r.read)
        self.assertLess(measure(r.sent)['pressure'],.8)

    def test_history_limit_reset_keeps_two_complete_tool_groups(self):
        r=self.runner();old=self.group('old',100);latest=self.group('latest',8000);prior=self.group('reference',8000)
        r.messages+=old+prior+latest
        r.fresh('context reset after repeated reads or long history')
        self.assertEqual(r.rebuilt,0)
        self.assertEqual(r.messages[-4:],prior+latest)
        self.assertNotIn('old',[m.get('tool_call_id') for m in r.messages])
        self.assertEqual(r.messages[0]['content'],'s'*17000)

    def test_repeat_ask_does_not_erase_tool_result_or_compact_forever(self):
        r=self.runner();group=self.group();r.messages+=group
        for _ in range(5):r.ask(r.messages,[])
        self.assertEqual(r.sent[-2:],group)
        self.assertEqual(r.rebuilt,0)
        self.assertEqual(r.h.log_event.call_count,1)

    def test_error_repair_rebuild_still_uses_current_source(self):
        r=self.runner();r.messages+=self.group()
        r.fresh('failed patch')
        self.assertEqual(r.rebuilt,1)
        self.assertEqual(len(r.messages),2)

    def test_unicode_is_not_counted_as_six_character_escape_sequences(self):
        messages=[{'role':'user','content':'재고 조회 조건 '*500}]
        self.assertLess(measure(messages)['estimated_input_tokens'],len(json.dumps(messages))/3)

    def test_hidden_reasoning_is_excluded_like_the_actual_client_packet(self):
        base=[{'role':'assistant','content':'visible'}]
        traced=[{**base[0],'reasoning':'x'*90000,'reasoning_content':'y'*90000}]
        self.assertEqual(measure(base)['estimated_input_tokens'],measure(traced)['estimated_input_tokens'])

    def test_actual_ast_catalog_survives_native_tool_result_serialization(self):
        from test_autonomy import native,reply_tool
        from autonomy_runtime import Runner
        import tempfile
        with tempfile.TemporaryDirectory() as temp:
            args=SimpleNamespace(task='Edit layout',workspace=temp,check='python',max_rounds=4,
                                 ponytail='off',llm_url='http://127.0.0.1:8099/v1',model='fixture')
            r=Runner(args,native.Harness)
            r.h.evidence_path=Path(temp)/'events.jsonl'
            catalog={'snapshot_id':'snapshot','nodes':[{'id':'jsx9','source':'x'*8000+'LAST_JSX_NODE'}]}
            r.apply=Mock(return_value=catalog)
            message=reply_tool('inspect_code',path='frontend/src/screens/Inventory.tsx',action='edit_ranges')['choices'][0]['message']
            r.batch(message)
            result=json.loads(r.messages[-1]['content'])
            self.assertEqual(result,catalog)

    def test_client_uses_shared_budget_dict_and_keeps_hard_guard(self):
        from test_autonomy import native
        from unittest.mock import patch
        client=native.LocalLLMClient('http://127.0.0.1:8099/v1','fixture')
        message=[{'role':'user','content':'재고 조회'*100}]
        with patch('model_transport.complete',return_value={'choices':[{'message':{'content':'ok'}}]}) as transport:
            client.chat(message,tools=[])
            transport.assert_called_once()
        with patch('context_budget.measure',return_value={'estimated_input_tokens':33000,'reserved_output_tokens':4096}),patch('model_transport.complete') as transport:
            with self.assertRaisesRegex(native.HarnessError,'Token budget exceeded'):client.chat(message,tools=[])
            transport.assert_not_called()


if __name__=='__main__':unittest.main()


_saved_context_flag = None


def setUpModule():
    """These cases cover the legacy compaction path; context_manager is tested separately."""
    global _saved_context_flag
    import os
    _saved_context_flag = os.environ.get('HARNESS_CONTEXT_MANAGEMENT')
    os.environ['HARNESS_CONTEXT_MANAGEMENT'] = '0'


def tearDownModule():
    import os
    if _saved_context_flag is None:
        os.environ.pop('HARNESS_CONTEXT_MANAGEMENT', None)
    else:
        os.environ['HARNESS_CONTEXT_MANAGEMENT'] = _saved_context_flag
