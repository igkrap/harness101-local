import os,signal,subprocess,sys,tempfile,threading,time,unittest,json
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from server import Platform

class GracefulStopTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.app=Platform(self.root,self.root/'state',0);self.process=None
 def tearDown(self):
  if self.process and self.process.poll() is None:os.killpg(self.process.pid,signal.SIGKILL);self.process.wait()
  if self.process and self.process.stdout:self.process.stdout.close()
  self.tmp.cleanup()
 def start(self,script):
  self.process=subprocess.Popen([sys.executable,'-u','-c',script],stdout=subprocess.PIPE,text=True,start_new_session=True)
  self.assertEqual(self.process.stdout.readline().strip(),'ready')
  key='c'*32;self.app.processes[key]=self.process;self.app.jobs[key]={'id':key,'status':'running'}
  threading.Thread(target=self.app.reap,args=(key,),daemon=True).start();return key
 def wait_result(self,key):
  self.process.wait(timeout=3)
  for _ in range(100):
   if self.app.jobs[key]['status']=='stopped':return self.app.jobs[key]
   time.sleep(.01)
  self.fail('job was not marked stopped')
 def test_repeated_stop_allows_cleanup_and_zero_exit(self):
  done=self.root/'cleanup'
  script='import signal,time,sys\nfrom pathlib import Path\ndef stop(*a):sys.exit(0)\nsignal.signal(signal.SIGTERM,stop)\nprint("ready",flush=True)\ntry:\n while True:time.sleep(1)\nfinally:\n time.sleep(.15)\n Path('+repr(str(done))+').write_text("clean")\n'
  key=self.start(script)
  with patch('server.os.killpg',wraps=os.killpg) as send:
   self.app.stop(key);self.app.stop(key);self.assertEqual(send.call_count,1)
  job=self.wait_result(key);self.assertTrue(job['clean_stop']);self.assertEqual(job['exit_code'],0);self.assertEqual(job['stop_reason'],'user');self.assertEqual(done.read_text(),'clean')
 def test_unresponsive_process_escalation_is_explicit(self):
  key=self.start('import signal,time\nsignal.signal(signal.SIGTERM,signal.SIG_IGN)\nprint("ready",flush=True)\ntime.sleep(30)')
  self.app.stop(key);self.app.finish_stop(key,self.process,grace=.03)
  job=self.wait_result(key);self.assertTrue(job['force_killed']);self.assertFalse(job['clean_stop']);self.assertEqual(job['status'],'stopped');self.assertEqual(job['exit_code'],-signal.SIGKILL)

 def test_adapter_reports_user_stop_as_zero_exit_without_claiming_success(self):
  from adapter import execute
  harness=self.root/'harness';harness.mkdir()
  (harness/'harness.py').write_text("DEFAULT_MODEL='fixture'\nclass Harness:\n def __init__(self,args):self.args=args;self.llm=type('LLM',(),{'chat':lambda *a:None})();self.checker=type('Checker',(),{'run_check':lambda *a:None})()\n def log_event(self,*a):pass\n")
  (harness/'supervisor.py').write_text("def run_supervised(args,cls):\n args.stop_requested=True\n cls(args).log_event('autonomy.stopped',{})\n return False\n")
  with patch.dict(os.environ):result=execute(self.root,self.root/'observed',{'goal':'fixture','checks':['frontend'],'rounds':0})
  events=[json.loads(l) for l in (self.root/'observed/events.jsonl').read_text().splitlines()]
  self.assertEqual(result,0);self.assertTrue(events[-1]['data']['stopped']);self.assertFalse(events[-1]['data']['success'])

 def test_adapter_respects_profile_output_limit(self):
  from adapter import execute
  harness=self.root/'harness';harness.mkdir()
  (harness/'harness.py').write_text("import os\nDEFAULT_MODEL='fixture'\nclass LLM:\n def chat(self,*a,**k):return {'choices':[{'message':{'content':os.environ['LOCAL_LLM_MAX_TOKENS']},'finish_reason':'stop'}],'usage':{'prompt_tokens':1,'completion_tokens':1}}\nclass Checker:\n def run_check(self,*a):return {'success':True}\nclass Harness:\n def __init__(self,args):self.args=args;self.llm=LLM();self.checker=Checker()\n def log_event(self,*a):pass\n def run(self):return self.llm.chat([])['choices'][0]['message']['content']=='512'\n")
  with patch.dict(os.environ):result=execute(self.root,self.root/'limit-job',{'goal':'fixture','checks':['frontend'],'rounds':0,'model_config':{'max_tokens':512}})
  es=[json.loads(l)for l in(self.root/'limit-job/events.jsonl').read_text().splitlines()];self.assertEqual(result,1);self.assertEqual(next(e['data']['text']for e in es if e['type']=='model.response'),'512')
  self.assertEqual(next(e['data']['stage'] for e in es if e['type']=='run.error'),'completion_gate')
