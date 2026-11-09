"""Exercise the real completion loop and HTTP verifier with deterministic model replies."""
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'local-only/harness'))
from test_autonomy import native, reply_tool, reply_text


class CompletionLoopTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.path='backend/src/main/java/Fixture.java'
        self.file=self.root/self.path
        self.file.parent.mkdir(parents=True)
        self.file.write_text('class Fixture { String value = "old"; }')
        owner=self
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                body=json.dumps({'value':'new' if '"new"' in owner.file.read_text() else 'old'}).encode()
                self.send_response(200)
                self.send_header('Content-Type','application/json')
                self.end_headers()
                self.wfile.write(body)
            def log_message(self,*args): pass
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()
        self.events=[]
        self.calls=[]
        self.script=[]
        class LLM:
            def chat(self,messages,tools=None):
                owner.calls.append(messages)
                if not owner.script:raise RuntimeError('Unexpected extra model call')
                return owner.script.pop(0)
        class Harness(native.Harness):
            def __init__(self,args):
                super().__init__(args)
                self.llm=LLM()
                self.checker.run_check=lambda mode:{'success':True,'stdout':'compiler checks passed','stderr':''}
                self.evidence_path=owner.root/'events.jsonl'
            def log_event(self,kind,data):owner.events.append((kind,data))
        self.Harness=Harness
        self.args=SimpleNamespace(task='Set backend value to new',workspace=str(self.root),check='backend',max_rounds=5,
                                  ponytail='off',llm_url='http://127.0.0.1:8099/v1',model='fixture')
        self.contract={'criteria':[{'id':'C1','requirement_id':'R1','description':'API returns updated value',
                                   'check':{'op':'api','method':'GET','path':'/api/value','status':200,'json_path':['value'],'equals':'new'}}]}

    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join()
        self.temp.cleanup()

    def run_loop(self):
        from autonomy_runtime import Runner
        # The real review parser receives a separate model response in its own context.
        self.script.insert(1,reply_text(json.dumps({'approved':True,'issues':[]})))
        env={'HARNESS_VERIFICATION_API_URL':f'http://127.0.0.1:{self.server.server_port}'}
        with patch.dict(os.environ,env), patch('verification_gate.Path.home',return_value=self.root):
            runner=Runner(self.args,self.Harness)
            return runner,runner.run()

    def test_compiler_pass_without_work_is_not_completion(self):
        self.args.max_rounds=3
        self.script=[reply_text(json.dumps(self.contract)),reply_tool('finish')]
        runner,ok=self.run_loop()
        self.assertFalse(ok)
        self.assertEqual(runner.step,0)
        self.assertFalse(any(k=='autonomy.step_finished' for k,_ in self.events))
        reports=[v for k,v in self.events if k=='verification.finished']
        self.assertTrue(reports)
        self.assertFalse(reports[-1]['success'])

    def test_verified_mutation_with_wrong_behavior_still_cannot_finish(self):
        self.script=[reply_text(json.dumps(self.contract)),reply_tool('read_file',path=self.path),
                     reply_tool('edit_file',path=self.path,old_text='"old"',new_text='"cosmetic"'),reply_tool('finish')]
        runner,ok=self.run_loop()
        self.assertTrue(runner.accepted)
        self.assertFalse(ok)
        report=[v for k,v in self.events if k=='verification.finished'][-1]
        self.assertEqual(next(r['status'] for r in report['results'] if r['id']=='C1'),'failed')

    def test_actual_requested_behavior_is_verified_after_change(self):
        self.script=[reply_text(json.dumps(self.contract)),reply_tool('read_file',path=self.path),
                     reply_tool('edit_file',path=self.path,old_text='"old"',new_text='"new"')]
        runner,ok=self.run_loop()
        self.assertTrue(ok,runner.feedback)
        kinds=[k for k,_ in self.events]
        self.assertLess(kinds.index('autonomy.accepted'),kinds.index('verification.finished'))
        self.assertLess(kinds.index('verification.finished'),kinds.index('autonomy.step_finished'))
        self.assertEqual(len(self.calls),4)
        self.assertIn('IMMUTABLE',str(self.calls[-1]))

    def test_atomic_finish_is_verified_after_commit_without_another_model_call(self):
        self.args.max_rounds=4
        atomic=reply_tool('edit_file',path=self.path,old_text='"old"',new_text='"new"')
        atomic['choices'][0]['message']['tool_calls'] += reply_tool('finish')['choices'][0]['message']['tool_calls']
        self.script=[reply_text(json.dumps(self.contract)),reply_tool('read_file',path=self.path),atomic]
        runner,ok=self.run_loop()
        self.assertTrue(ok,runner.feedback)
        kinds=[k for k,_ in self.events]
        self.assertLess(kinds.index('autonomy.accepted'),kinds.index('verification.finished'))
        self.assertEqual(len(self.calls),4)


if __name__=='__main__':unittest.main()
