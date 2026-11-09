import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import urllib.request
import urllib.error
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server import Platform, Handler, ThreadingHTTPServer, default_context_profile, file_signature
from adapter import execute

class PlatformTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)/'project';self.root.mkdir()
        for part in ('frontend/src','backend/src','harness/tests'):(self.root/part).mkdir(parents=True)
        (self.root/'frontend/src/App.tsx').write_text('hello')
        self.app=Platform(self.root,Path(self.tmp.name)/'state',0)
    def tearDown(self):self.tmp.cleanup()
    def test_source_boundary_and_symlink(self):
        outside=Path(self.tmp.name)/'secret.py';outside.write_text('secret')
        (self.root/'harness/link.py').symlink_to(outside)
        (self.root/'harness/core.py').write_text('internal harness')
        for path in ('../secret.py','harness/link.py','harness/core.py','.env','frontend/src/../../../../secret.py'):
            with self.assertRaises(ValueError):self.app.source(path)
        self.assertEqual(self.app.source('frontend/src/App.tsx')['content'],'hello')
        self.assertTrue(all(not p.startswith('harness/') for p in self.app.tree()))
    def test_success_requires_executed_backend_tests(self):
        from quality import checked_result
        for text in ('BUILD SUCCESS','Tests run: 0, Failures: 0, Errors: 0, Skipped: 0','Tests run: 5, Failures: 0, Errors: 0, Skipped: 5'):
            self.assertFalse(checked_result('backend',{'success':True,'stdout':text})['success'])
        self.assertTrue(checked_result('backend',{'success':True,'stdout':'Tests run: 5, Failures: 0, Errors: 0, Skipped: 0'})['success'])
    def test_invalid_requests_never_start(self):
        for body in ({'checks':['shell']},{'checks':[{}]},{'rounds':True},{'rounds':100},{'kind':'agent'},{'kind':'delete'},{'checks':[]}):
            with self.assertRaises(ValueError):self.app.start(body)
        self.assertFalse(self.app.jobs)
    def test_ui_context_defaults_without_changing_data_tasks(self):
        self.assertEqual(default_context_profile('품목 등록 화면 편집 패널을 버튼으로 접게 해줘'), 'focused')
        self.assertEqual(default_context_profile('품목 등록 화면 저장 API와 DB 테이블을 만들어줘'), 'legacy')
        self.assertEqual(default_context_profile('백엔드 품목 삭제 기능을 추가해줘'), 'legacy')
    def test_stale_gate_after_source_change(self):
        key='a'*32;folder=self.app.state/key;folder.mkdir()
        job={'id':key,'status':'failed','started_at':'2026-10-31T00:00:00+00:00'};self.app.jobs[key]=job
        event={'type':'check.finished','time':'2026-10-31T00:00:00+00:00','data':{'mode':'frontend','success':True,'source_hash':file_signature(self.root,'frontend')}}
        (folder/'events.jsonl').write_text(json.dumps(event)+'\n{"partial":')
        with patch.object(self.app,'external',return_value=[]),patch('server.urllib.request.urlopen',side_effect=OSError):
            self.assertEqual(next(g for g in self.app.snapshot()['gates'] if g['mode']=='frontend')['state'],'passed')
            (self.root/'frontend/src/App.tsx').write_text('changed');self.app.cache_time=None
            self.assertEqual(next(g for g in self.app.snapshot()['gates'] if g['mode']=='frontend')['state'],'stale')
    def test_snapshot_is_bounded_and_large_details_are_lazy(self):
        for i in range(45):
            key=f'{i:032x}';folder=self.app.state/key;folder.mkdir();self.app.jobs[key]={'id':key,'status':'succeeded','started_at':f'2026-11-01T00:00:{i:02}+00:00'}
            events=[{'seq':1,'type':'model.response','time':'2026-11-01T00:00:00Z','data':{'text':'large'*1000}}, {'seq':2,'type':'check.finished','time':'2026-11-01T00:00:00Z','data':{'mode':'frontend','success':True,'source_hash':file_signature(self.root,'frontend'),'stdout':'large'*1000}}]
            (folder/'events.jsonl').write_text(''.join(json.dumps(e)+'\n' for e in events))
        with patch.object(self.app,'external',return_value=[]),patch('server.urllib.request.urlopen',side_effect=OSError):
            state=self.app.snapshot();self.assertEqual(len(state['jobs']),20);self.assertEqual(state['jobs_total'],45);self.assertTrue(state['jobs_next']);self.assertNotIn('text',state['events'][0]['data']);self.assertTrue(state['events'][0]['data']['has_text']);self.assertNotIn('stdout',state['events'][1]['data']);self.app.cache_time=None
            with patch('server.json_lines',side_effect=AssertionError('archive should not be reparsed')):self.app.snapshot()
        self.assertEqual(len(self.app.job_page(state['jobs_next'])['jobs']),20)
    def test_start_reaps_owned_process_and_updates_catalog(self):
        child=subprocess.Popen([sys.executable,'-c','pass'],start_new_session=True)
        with patch.object(self.app,'external',return_value=[]),patch('server.subprocess.Popen',return_value=child):
            job=self.app.start({'kind':'checks','checks':['frontend']})
        child.wait(timeout=3)
        for _ in range(100):
            if self.app.jobs[job['id']]['status']=='succeeded' and job['id'] not in self.app.processes:break
            time.sleep(.01)
        self.assertEqual(self.app.jobs[job['id']]['status'],'succeeded');self.assertEqual(self.app.jobs[job['id']]['exit_code'],0);self.assertEqual(job['rounds'],0);self.assertNotIn(job['id'],self.app.processes);self.assertEqual(self.app.job_page()['jobs'][0]['status'],'succeeded')
    def test_stop_only_owned_process(self):
        with self.assertRaises(ValueError):self.app.stop('unowned')
        process=subprocess.Popen([sys.executable,'-c','import time;time.sleep(20)'],start_new_session=True)
        key='b'*32;self.app.processes[key]=process;self.app.jobs[key]={'id':key,'status':'running'}
        threading.Thread(target=self.app.reap,args=(key,),daemon=True).start()
        self.app.stop(key);process.wait(timeout=3)
        for _ in range(30):
            if self.app.jobs[key]['status']=='stopped':break
            time.sleep(.01)
        self.assertEqual(self.app.jobs[key]['status'],'stopped')
    def test_update_blocks_launch(self):
        (self.app.state/'maintenance.json').write_text('{}')
        with self.assertRaises(RuntimeError):self.app.start({'kind':'checks'})
    def test_restart_marks_running_interrupted(self):
        key='c'*32;self.app.save({'id':key,'status':'running'})
        restarted=Platform(self.root,self.app.state)
        self.assertEqual(restarted.jobs[key]['status'],'interrupted')
    def test_second_reader_preserves_live_job_and_observes_exit(self):
        key='d'*32
        job_dir=self.app.state/key
        job_dir.mkdir()
        child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(20)',
                                str(Path(__file__).resolve().parents[1]/'adapter.py'),
                                '--job-dir',str(job_dir)])
        try:
            self.app.save({'id':key,'status':'running','pid':child.pid,
                           'started_at':'2026-11-05T00:00:00+00:00'})
            reader=Platform(self.root,self.app.state)
            self.assertEqual(reader.jobs[key]['status'],'running')
            self.assertEqual(reader.history.jobs()['jobs'][0]['status'],'running')
            child.terminate();child.wait(timeout=5)
            deadline=time.monotonic()+5
            while reader.jobs[key]['status']=='running' and time.monotonic()<deadline:
                time.sleep(0.1)
            self.assertEqual(reader.jobs[key]['status'],'interrupted')
        finally:
            if child.poll() is None:child.kill();child.wait()
    def test_http_token_origin_and_missing_route(self):
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler);server.platform=self.app
        threading.Thread(target=server.serve_forever,daemon=True).start()
        base='http://127.0.0.1:'+str(server.server_port)
        try:
            req=urllib.request.Request(base+'/api/jobs',b'{}',{'Content-Type':'application/json'})
            with self.assertRaises(urllib.error.HTTPError) as err:urllib.request.urlopen(req)
            self.assertEqual(err.exception.code,403)
            req=urllib.request.Request(base+'/api/state',headers={'Origin':'https://example.com'})
            with self.assertRaises(urllib.error.HTTPError) as err:urllib.request.urlopen(req)
            self.assertEqual(err.exception.code,403)
            with self.assertRaises(urllib.error.HTTPError) as err:urllib.request.urlopen(base+'/api/missing')
            self.assertEqual(err.exception.code,404)
            for kind in ('checks','harness'):
                req=urllib.request.Request(base+'/api/jobs',json.dumps({'kind':kind}).encode(),{'Content-Type':'application/json','X-Platform-Token':self.app.token})
                with self.assertRaises(urllib.error.HTTPError) as err:urllib.request.urlopen(req)
                self.assertEqual(err.exception.code,400)
        finally:server.shutdown();server.server_close()
    def test_adapter_observes_native_hooks_without_source_changes(self):
        source='''
DEFAULT_MODEL='local-fixture'
class LLM:
 def chat(self,messages,tools=None):return {'choices':[{'message':{'content':'reply'},'finish_reason':'stop'}],'usage':{'completion_tokens':3}}
class Check:
 def run_check(self,mode):return {'success':False,'exit_code':1,'stdout':'real failure','stderr':''}
class Harness:
 def __init__(self,args):self.args=args;self.llm=LLM();self.checker=Check()
 def _execute_tool(self,name,args):return {'status':'ok','content':'backend/src/InventoryController.java:32','truncated':False}
 def run(self):
  self.llm.chat([{'role':'user','content':self.args.task}],tools=[])
  self._execute_tool('read_file',{'path':'frontend/src/App.tsx'})
  self._execute_tool('search_code',{'query':'품목 저장','mode':'hybrid','scope':'backend'})
  self.checker.run_check('frontend')
  return False
def run_task(args):return Harness(args).run()
'''
        path=self.root/'harness/harness.py';path.write_text(source);job=Path(self.tmp.name)/'observed'
        with patch.dict(os.environ):result=execute(self.root,job,{'goal':'test','checks':['frontend'],'rounds':1})
        events=[json.loads(line) for line in (job/'events.jsonl').read_text().splitlines()]
        self.assertEqual(result,1);self.assertEqual(path.read_text(),source)
        self.assertEqual([e['type'] for e in events],['run.started','attempt.started','model.request','model.response','tool.started','tool.finished','tool.started','tool.finished','check.started','check.finished','attempt.finished','run.finished'])
        self.assertEqual(events[7]['data']['query'],'품목 저장')
        self.assertEqual(events[7]['data']['search_mode'],'hybrid')
        self.assertEqual(json.loads(events[7]['data']['stdout'])['content'],'backend/src/InventoryController.java:32')
        self.assertEqual(json.loads(events[4]['data']['text'])['path'],'frontend/src/App.tsx')
        self.assertEqual(json.loads(events[5]['data']['stdout'])['content'],'backend/src/InventoryController.java:32')
        self.assertFalse(events[7]['data']['changed'])
        self.assertFalse(events[-1]['data']['success']);self.assertFalse(events[-3]['data']['success'])
        self.assertEqual(events[3]['data']['usage']['completion_tokens'],3)

if __name__=='__main__':unittest.main()
