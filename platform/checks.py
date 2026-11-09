"""Run fixed checks only; never invokes a generation model."""
import argparse
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import time
from server import file_signature
from quality import checked_result


def execute(project, directory):
    root, folder = Path(project).resolve(), Path(directory).resolve()
    request = json.loads((folder/'request.json').read_text())
    sequence = 0
    def emit(kind, data):
        nonlocal sequence
        sequence += 1
        event = {'seq':sequence,'time':datetime.now(timezone.utc).isoformat(),'type':kind,'data':data}
        with (folder/'events.jsonl').open('a') as f:f.write(json.dumps(event,ensure_ascii=False)+'\n')
    runtime=Path(request.get('harness_root') or root/'harness').resolve()
    sys.path.insert(0,str(runtime))
    if request.get('test_db_url'):
        import os
        os.environ['HARNESS_TEST_DB_URL']=request['test_db_url']
    spec=importlib.util.spec_from_file_location('checked_local_harness',runtime/'harness.py')
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    checker=m.Checker(m.WorkspaceManager(root))
    modes=['harness'] if request['kind']=='harness' else request['checks']
    emit('run.started',{'kind':'checks','checks':modes})
    success=True
    for mode in modes:
        before=file_signature(root,mode);started=time.monotonic();emit('check.started',{'mode':mode})
        try:
            if mode=='harness':
                p=subprocess.run([sys.executable,'-m','unittest','discover','-s',str(runtime/'tests'),'-p','test_*.py'],cwd=runtime.parent,capture_output=True,text=True,timeout=120)
                result={'success':p.returncode==0,'stdout':p.stdout,'stderr':p.stderr,'exit_code':p.returncode}
                if p.returncode == 0:
                    q=subprocess.run([sys.executable,'-m','unittest','discover','-s',str(Path(__file__).parent/'tests'),'-p','test_*.py'],cwd=root,capture_output=True,text=True,timeout=120)
                    result={'success':q.returncode==0,'stdout':p.stdout+q.stdout,'stderr':p.stderr+q.stderr,'exit_code':q.returncode}
            else:result=checked_result(mode, checker.run_check(mode))
            unchanged=before==file_signature(root,mode)
            if not unchanged:result.update(success=False,stderr=result.get('stderr','')+'\n검사 중 소스가 변경되어 다시 확인해야 합니다.')
            emit('check.finished',{'mode':mode,**result,'source_hash':before,'duration_ms':round((time.monotonic()-started)*1000)})
            print(mode, 'PASS' if result['success'] else 'FAIL',flush=True)
            success=success and result['success']
        except Exception as exc:
            success=False;emit('check.finished',{'mode':mode,'success':False,'error':str(exc),'duration_ms':round((time.monotonic()-started)*1000)})
    emit('run.finished',{'success':success})
    return 0 if success else 1

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--project',required=True);p.add_argument('--job-dir',required=True);a=p.parse_args();sys.exit(execute(a.project,a.job_dir))
