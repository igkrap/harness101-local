"""Real file edits and HTTP evidence across serial stages; model replies are fixtures."""
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

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'local-only/harness'))
from test_autonomy import native, reply_tool, reply_text


class DivideLoopTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.paths = {name: f'backend/src/main/java/{name.title()}.java' for name in ('query', 'editor')}
        for name, rel in self.paths.items():
            p = self.root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(f'class {name.title()} {{ String value = "old"; }}')
        owner = self
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                key = self.path.rsplit('/', 1)[-1]
                value = 'new' if '"new"' in (owner.root / owner.paths[key]).read_text() else 'old'
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'value': value}).encode())
            def log_message(self, *args): pass
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.events, self.calls, self.script = [], [], []
        class LLM:
            def chat(self, messages, tools=None):
                owner.calls.append(json.loads(json.dumps(messages)))
                if not owner.script: raise RuntimeError('Unexpected extra model call')
                return owner.script.pop(0)
        class Harness(native.Harness):
            def __init__(self, args):
                super().__init__(args)
                self.llm = LLM()
                self.checker.run_check = lambda mode: {'success': True, 'stdout': 'checks passed', 'stderr': ''}
                self.evidence_path = owner.root / 'events.jsonl'
            def log_event(self, kind, data): owner.events.append((kind, data))
        self.Harness = Harness
        self.args = SimpleNamespace(task='조회 API 값 변경\n수정 API 값 변경', workspace=str(self.root),
                                    check='backend', max_rounds=5, ponytail='off',
                                    llm_url='http://127.0.0.1:8099/v1', model='fixture')
        self.contract = {'criteria': [
            {'id': f'C{i}', 'requirement_id': f'R{i}', 'description': f'{name} value',
             'check': {'op': 'api', 'method': 'GET', 'path': '/api/' + name, 'status': 200,
                       'json_path': ['value'], 'equals': 'new'}}
            for i, name in enumerate(('query', 'editor'), 1)]}
        self.plan = {'stages': [
            {'id': name, 'title': name, 'instructions': f'Change {name} value to new', 'domain': 'backend',
             'criterion_ids': [f'C{i}'], 'paths': [self.paths[name]], 'references': [],
             'depends_on': [] if i == 1 else ['query']}
            for i, name in enumerate(('query', 'editor'), 1)]}

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join()
        self.temp.cleanup()

    def atomic(self, name, old='old', new='new'):
        msg = reply_tool('edit_file', path=self.paths[name], old_text=f'"{old}"', new_text=f'"{new}"')
        msg['choices'][0]['message']['tool_calls'] += reply_tool('finish')['choices'][0]['message']['tool_calls']
        return msg

    def run_loop(self, edits):
        from autonomy_runtime import Runner
        self.script = [reply_text(json.dumps(self.contract)),
                       reply_text(json.dumps({'approved': True, 'issues': []})),
                       reply_text(json.dumps(self.plan)), *edits]
        with patch.dict(os.environ, {'HARNESS_VERIFICATION_API_URL': f'http://127.0.0.1:{self.server.server_port}'}), \
             patch('verification_gate.Path.home', return_value=self.root):
            runner = Runner(self.args, self.Harness)
            return runner, runner.run()

    def test_fresh_stages_and_only_final_global_completion(self):
        runner, ok = self.run_loop([self.atomic('query'), self.atomic('editor')])
        self.assertTrue(ok, runner.feedback)
        self.assertEqual(runner.used, 5)
        self.assertEqual(len(self.calls), 5)
        kinds = [k for k, _ in self.events]
        accepted = [i for i, k in enumerate(kinds) if k == 'autonomy.accepted']
        finals = [i for i, k in enumerate(kinds) if k == 'verification.finished']
        self.assertEqual(len(finals), 1)
        self.assertLess(max(accepted), finals[0])
        self.assertEqual([d['stage_id'] for k, d in self.events if k == 'autonomy.stage_started'],
                         ['query', 'editor', 'integration'])
        self.assertIn('verified-evidence', json.dumps(self.calls[-1], ensure_ascii=False))
        self.assertFalse(any(m.get('role') == 'assistant' for m in self.calls[-1]))

    def test_every_accepted_edit_runs_native_gate_without_model_finish_or_verify(self):
        edits=[reply_tool('edit_file',path=self.paths['query'],old_text='"old"',new_text='"partial"'),
               reply_tool('edit_file',path=self.paths['query'],old_text='"partial"',new_text='"new"'),
               reply_tool('edit_file',path=self.paths['editor'],old_text='"old"',new_text='"new"')]
        self.args.max_rounds=6
        runner,ok=self.run_loop(edits)
        self.assertTrue(ok,runner.feedback);self.assertEqual(runner.used,6);self.assertEqual(len(self.calls),6)
        self.assertIn('partial',json.dumps(self.calls[4]))
        query_reports=[d for k,d in self.events if k=='autonomy.stage_verified' and d['stage_id']=='query']
        self.assertTrue(any(not d['success'] for d in query_reports));self.assertTrue(query_reports[-1]['success'])
        self.assertTrue(any(k=='autonomy.strategy' and d.get('reason')=='automatic_requirement_verification' for k,d in self.events))

    def test_already_satisfied_stage_uses_probe_without_cosmetic_edit(self):
        p = self.root / self.paths['query']
        p.write_text(p.read_text().replace('"old"', '"new"'))
        runner, ok = self.run_loop([self.atomic('editor')])
        self.assertTrue(ok, runner.feedback)
        self.assertEqual(runner.used, 4)

    def test_upstream_regression_cannot_pass_later_stage(self):
        self.args.max_rounds = 6
        edit = self.atomic('editor')
        edit['choices'][0]['message']['tool_calls'].insert(1,
            self.atomic('query', old='new', new='broken')['choices'][0]['message']['tool_calls'][0])
        self.plan['stages'][1]['references'] = [self.paths['query']]
        runner, ok = self.run_loop([self.atomic('query'), edit, self.atomic('query', old='broken')])
        self.assertTrue(ok, runner.feedback)
        reports = [d for k, d in self.events if k == 'autonomy.stage_verified' and d['stage_id'] == 'editor']
        self.assertTrue(any(not d['success'] for d in reports))
        self.assertTrue(reports[-1]['success'])

    def test_final_integration_rewinds_to_owner_and_revalidates_dependents(self):
        from verification_gate import Gate
        original = Gate.verify
        calls = []
        def regressed_once(gate):
            if not calls:
                p = self.root / self.paths['query']
                p.write_text(p.read_text().replace('"new"','"old"'))
            calls.append(True)
            return original(gate)
        self.args.max_rounds=6
        with patch.object(Gate,'verify',regressed_once):
            runner,ok=self.run_loop([self.atomic('query'),self.atomic('editor'),self.atomic('query')])
        self.assertTrue(ok,runner.feedback)
        starts=[d['stage_id'] for k,d in self.events if k=='autonomy.stage_started']
        self.assertEqual(starts,['query','editor','integration','query','editor','integration'])
        repairs=[d for k,d in self.events if k=='autonomy.integration_failed']
        self.assertEqual(repairs[0]['repair_stage_id'],'query')
        self.assertEqual(runner.used,6)

    def test_user_stop_rolls_back_current_stage_only(self):
        from autonomy_runtime import StopLoop
        from supervisor import run_supervised
        self.script=[reply_text(json.dumps(self.contract)),reply_text(json.dumps({'approved':True,'issues':[]})),
                     reply_text(json.dumps(self.plan)),self.atomic('query'),self.atomic('editor')]
        original_harness=self.Harness
        owner=self
        class InterruptedHarness(original_harness):
            def __init__(self,args):
                super().__init__(args)
                def check(mode):
                    if '"new"' in (owner.root/owner.paths['editor']).read_text():
                        owner.args.stop_requested=True
                        raise StopLoop()
                    return {'success':True,'stdout':'passed','stderr':''}
                self.checker.run_check=check
        with patch.dict(os.environ,{'HARNESS_VERIFICATION_API_URL':f'http://127.0.0.1:{self.server.server_port}'}),\
             patch('verification_gate.Path.home',return_value=self.root):
            self.assertFalse(run_supervised(self.args,InterruptedHarness))
        self.assertTrue(self.args.stop_requested)
        self.assertFalse(self.args.stop_cleanup_failed)
        self.assertIn('"new"',(self.root/self.paths['query']).read_text())
        self.assertIn('"old"',(self.root/self.paths['editor']).read_text())
        self.assertFalse(any(k=='verification.finished' and d.get('success') for k,d in self.events))

    def test_all_conditions_already_met_cannot_claim_a_new_change(self):
        for rel in self.paths.values():
            p=self.root/rel;p.write_text(p.read_text().replace('"old"','"new"'))
        runner,ok=self.run_loop([])
        self.assertFalse(ok)
        self.assertEqual(runner.used,3)
        self.assertTrue(any(k=='autonomy.blocked' for k,_ in self.events))


if __name__ == '__main__': unittest.main()
