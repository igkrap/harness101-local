"""Loopback-only development platform: managed jobs, real evidence, static UI."""
import argparse
from collections import Counter
from history import History
from failure import describe_failure
from datetime import datetime, timezone
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
import os
from pathlib import Path
import re
import secrets
import signal
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.request
from urllib.parse import urlsplit, parse_qs
import uuid
import xml.etree.ElementTree as ET
import chat_store
from task_queue import QueueManager
from chat_service import ChatUpstreamError, answer as chat_answer, stream as chat_stream

BASE = Path(__file__).resolve().parent
MODES = {'frontend', 'framework', 'backend'}


def default_context_profile(goal):
    """Keep ordinary UI requests small without narrowing their selected checks."""
    text = goal.casefold() if isinstance(goal, str) else ''
    ui_terms = ('화면', '패널', '버튼', '스플릿', '레이아웃', '탭', '사이드바', '그리드',
                'screen', 'panel', 'button', 'layout', 'sidebar', 'grid')
    data_terms = ('백엔드', '데이터베이스', 'database', 'api', '엔드포인트', 'sql',
                  '저장', '조회', '삭제', 'crud', '마이그레이션', '테이블', '스키마', 'db')
    return 'focused' if any(term in text for term in ui_terms) and not any(term in text for term in data_terms) else 'legacy'


def now():
    return datetime.now(timezone.utc).isoformat()


def read_json(path, fallback=None):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return fallback


def json_lines(path):
    try:
        with Path(path).open(encoding='utf-8', errors='replace') as f:
            return [v for line in f if line.strip() for v in parse_line(line)]
    except OSError:
        return []


def parse_line(line):
    try:
        value = json.loads(line)
        return [value] if isinstance(value, dict) else []
    except ValueError:
        return []


def compact_event(event):
    data=dict(event.get('data') or {})
    for key in ('contract','results','layout'):
        if key in data:
            data['has_output']=True
            data.pop(key)
    if data.get('stdout') or data.get('stderr'): data['has_output']=True
    if data.get('text'): data['has_text']=True
    for key in ('stdout','stderr','text','tool_calls'): data.pop(key,None)
    for key in ('reason','error'):
        if isinstance(data.get(key),str): data[key]=data[key][:1800]
    return {**event,'data':data}


def file_signature(root, category):
    runtime=root/'harness'
    if category=='harness' and not (runtime/'harness.py').is_file(): runtime=BASE.parent/'local-only/harness'
    paths = [*sorted(runtime.glob('*.py')), *sorted((runtime/'tests').glob('*.py'))] if category == 'harness' else sorted((root/'frontend/src').rglob('*')) + [root/'frontend/package.json', root/'frontend/tsconfig.json', root/'frontend/vite.config.ts'] if category in ('frontend','framework') else sorted((root/'backend/src').rglob('*')) + [root/'backend/pom.xml']
    digest = hashlib.sha256()
    for path in paths:
        if path.is_file() and '__pycache__' not in path.parts:
            digest.update(str(Path('harness')/path.relative_to(runtime) if category=='harness' else path.relative_to(root)).encode()); digest.update(path.read_bytes())
    if category == 'frontend':
        checker_root = runtime if (runtime/'harness.py').is_file() else BASE.parent/'local-only/harness'
        for name in ('eslint.config.cjs','lint_frontend.py','frontend_checks.py'):
            checker = checker_root/name
            if checker.is_file():
                digest.update(('checker/'+name).encode());digest.update(checker.read_bytes())
    return digest.hexdigest()


class Platform:
    def __init__(self, project, state, port=5293):
        self.project, self.state, self.port = Path(project).resolve(), Path(state).resolve(), port
        self.state.mkdir(parents=True, exist_ok=True)
        self.token = secrets.token_urlsafe(32)
        self.lock = threading.RLock()
        self.processes = {}
        self.orphans = {}
        self.jobs = {}
        self.cache = None
        self.cache_time = None
        self.legacy_cache = None
        self.legacy_stamp = None
        self.metadata = {}
        self.coordinator = None
        self.model_cache = None
        self.model_cache_time = 0
        for path in self.state.glob('*/job.json'):
            job = read_json(path)
            if job:
                if job.get('status') in ('running','stopping'):
                    if self.orphan_alive(job):
                        self.orphans[job['id']] = job['pid']
                    else:
                        job['status'] = 'interrupted'
                        job['detail'] = '플랫폼 재시작으로 종료 결과를 확인하지 못했습니다.'
                self.jobs[job['id']] = job
        self.history = History(self.state)
        for job in self.jobs.values(): self.history.sync(job)
        self.catalogued = set(self.jobs)
        for job_id in self.orphans:
            threading.Thread(target=self.watch_orphan, args=(job_id,), daemon=True).start()
        self.definition_route = True   # definition-type requests go through harness2 (see task_queue._definition_route)
        self.queues = QueueManager(self)

    def orphan_alive(self, job):
        pid = job.get('pid')
        if type(pid) is not int or pid <= 0:
            return False
        try:
            result = subprocess.run(['ps', '-p', str(pid), '-o', 'command='],
                                    capture_output=True, text=True, timeout=3)
        except (OSError, subprocess.TimeoutExpired):
            return False
        command = result.stdout.strip()
        return (result.returncode == 0 and
                (str(BASE/'adapter.py') in command or str(BASE/'checks.py') in command) and
                '--job-dir '+str(self.state/job['id']) in command)

    def watch_orphan(self, job_id):
        while True:
            time.sleep(2)
            disk = read_json(self.state/job_id/'job.json')
            with self.lock:
                if job_id not in self.orphans:
                    return
                if disk and disk.get('status') not in ('running', 'stopping'):
                    self.jobs[job_id] = disk
                elif not self.orphan_alive(self.jobs[job_id]):
                    job = self.jobs[job_id]
                    job.update(status='interrupted', finished_at=now(),
                               detail='실행 프로세스가 종료됐지만 결과를 확인하지 못했습니다.')
                else:
                    continue
                self._persist_lifecycle(self.jobs[job_id], 'orphan-observed')
                self.orphans.pop(job_id, None)
                return

    def sync_history(self):
        # Startup indexes existing journals once; polling reads only appended bytes.
        if len(self.jobs) != len(self.catalogued):
            for key in self.jobs.keys()-self.catalogued: self.history.sync(self.jobs[key])
            self.catalogued = set(self.jobs)

    def job_page(self, before=None, limit=20, kind=None):
        with self.lock:
            self.sync_history()
            return self.history.jobs(before,limit,kind)

    def save(self, job):
        directory = self.state/job['id']; directory.mkdir(exist_ok=True)
        target = directory/'job.json'; temp = directory/'job.json.tmp'
        temp.write_text(json.dumps(job, ensure_ascii=False, indent=2)); temp.replace(target)

    def external(self):
        result = subprocess.run(['ps','-axo','pid=,etime=,command='], capture_output=True, text=True, timeout=3)
        found = []
        owned = {p.pid for p in self.processes.values() if p.poll() is None}
        for line in result.stdout.splitlines():
            parts = line.strip().split(None, 2)
            if len(parts) != 3 or not parts[0].isdigit(): continue
            pid, elapsed, command = int(parts[0]), parts[1], parts[2]
            if pid in owned or pid == os.getpid(): continue
            native = str(self.project/'harness/harness.py') in command
            orphan = str(BASE/'adapter.py') in command and '--project '+str(self.project) in command
            check = str(BASE/'checks.py') in command and '--project '+str(self.project) in command
            if (native or orphan or check) and re.search(r'python(?:\d|\.|\s|/)', command, re.I):
                found.append({'pid':pid,'elapsed':elapsed,'label':'외부에서 실행한 하네스'})
        return found

    def resumed_contract(self, body, goal, checks):
        source = body.get('contract_from_job')
        if source is None:
            return None
        if not isinstance(source, str) or not re.fullmatch(r'[a-f0-9]{32}', source):
            raise ValueError('이어받을 실행 번호가 올바르지 않습니다.')
        previous = self.jobs.get(source)
        if not previous or previous.get('status') in ('running', 'stopping'):
            raise ValueError('완료되거나 중지된 실행만 이어받을 수 있습니다.')
        if (previous.get('goal') != goal or set(previous.get('checks', [])) != set(checks)
                or previous.get('project_id') != self.metadata.get('id')):
            raise ValueError('같은 프로젝트, 요청, 검사 항목의 실행만 이어받을 수 있습니다.')
        self.history.sync(previous)
        event = self.history.last_event(source, 'requirement.contract')
        data = event.get('data', {}) if event else {}
        if not isinstance(data.get('contract'), dict) or not isinstance(data.get('contract_hash'), str):
            raise ValueError('이전 실행에 확정된 요구사항 정의가 없습니다.')
        return {'source_job': source, 'contract': data['contract'], 'contract_hash': data['contract_hash']}

    def start(self, body):
        if (self.state/'maintenance.json').exists():
            raise RuntimeError('하네스 업데이트 중입니다. 검증이 끝나면 실행할 수 있습니다.')
        kind = body.get('kind', 'agent')
        checks = body.get('checks', ['frontend','framework'])
        if kind == 'harness': checks = ['frontend']
        if not isinstance(checks,list) or not checks or any(not isinstance(x,str) or x not in MODES for x in checks): raise ValueError('올바른 검사 항목을 선택하세요.')
        if kind not in ('agent','checks','harness'): raise ValueError('알 수 없는 실행 종류입니다.')
        rounds = body.get('rounds',0)
        if type(rounds) is not int or not 0 <= rounds <= 64: raise ValueError('호출 횟수는 0(제한 없음) 또는 1~64로 입력하세요.')
        goal = body.get('goal','').strip() if isinstance(body.get('goal',''),str) else ''
        context_profile = body.get('context_profile', default_context_profile(goal))
        if not isinstance(context_profile, str) or context_profile not in ('legacy', 'focused'):
            raise ValueError('알 수 없는 context profile입니다.')
        if kind == 'agent' and not 1 <= len(goal) <= 16000: raise ValueError('요청 내용을 입력하세요. 최대 16,000자입니다.')
        queue_ref = body.get('queue')
        active_queue = self.queues.active() if hasattr(self, 'queues') else None
        if active_queue and (not isinstance(queue_ref, dict) or queue_ref.get('id') != active_queue['id']):
            raise RuntimeError('작업 큐가 실행 중입니다. 큐가 끝나거나 중지된 뒤 시작하세요.')
        fixed_acceptance = None
        if 'fixed_acceptance' in body:
            if kind != 'agent' or body.get('contract_from_job') is not None:
                raise ValueError('고정 검사는 새 에이전트 실행에서만 선택할 수 있습니다.')
            from fixed_acceptance_registry import load_fixed_acceptance
            fixed_acceptance = load_fixed_acceptance(body['fixed_acceptance'], goal, self.project)
        resume_contract = self.resumed_contract(body, goal, checks) if kind == 'agent' else None
        available = self.available_checks()
        if self.metadata and kind != 'harness' and any(mode not in available for mode in checks):
            raise ValueError('이 프로젝트에서 사용할 수 없는 검사입니다. 백엔드는 별도 테스트 DB 설정이 필요합니다.')
        selected_model = body.get('model') or ('config:'+self.metadata['model_config'] if self.metadata.get('model_config') else self.metadata.get('default_model')) or 'mlx-community/Qwen3.8-27B-4bit'
        model_config = None
        if self.coordinator and isinstance(selected_model, str) and selected_model.startswith('config:'):
            model_config = self.coordinator.models.get(selected_model[7:])
            selected_model = model_config['model']
        if kind == 'agent' and not model_config and (not isinstance(selected_model, str) or selected_model not in self.models()['available']):
            raise ValueError('모델 서버에서 사용 가능한 모델을 선택하세요.')
        with self.lock:
            if (self.coordinator.busy() if self.coordinator else any(p.poll() is None for p in self.processes.values()) or self.external()): raise RuntimeError('실행 중인 하네스가 있습니다. 완료 또는 중지 후 시작하세요.')
            job_id = uuid.uuid4().hex
            directory = self.state/job_id; directory.mkdir()
            request = {'kind':kind,'goal':goal if kind == 'agent' else '',
                       'checks':['harness'] if kind == 'harness' else list(dict.fromkeys(checks)),
                       'rounds':rounds,'thinking':bool(body.get('thinking',False))}
            if kind == 'agent': request['completion_policy']='requirement-contract-v1'
            if kind == 'agent' and (context_profile != 'legacy' or 'context_profile' in body):
                request['context_profile'] = context_profile
            if fixed_acceptance is not None:
                request.update(fixed_acceptance=fixed_acceptance, completion_policy='fixed-acceptance-v1')
            if resume_contract is not None: request['resume_contract'] = resume_contract
            if kind == 'agent' and body.get('edit_format') in ('auto', 'diff'): request['edit_format'] = body['edit_format']
            if body.get('origin') == 'bench': request['origin'] = 'bench'  # measurement runs stay out of user statistics
            if isinstance(queue_ref, dict): request['queue'] = {k: queue_ref[k] for k in ('id', 'index', 'total', 'goal', 'completed', 'approach') if k in queue_ref}
            if self.metadata:
                request.update(project_id=self.metadata['id'], model=selected_model, llm_url=self.metadata['model_url'],
                               harness_root=str(self.runtime_root()), test_db_url=self.metadata.get('test_db_url', ''),
                               preview_url=self.metadata.get('preview_url', ''), api_url=self.metadata.get('api_url', ''))
            if model_config:
                request.update(model_config=dict(model_config), model=selected_model, llm_url=model_config['url'])
            (directory/'request.json').write_text(json.dumps(request, ensure_ascii=False))
            job = {'id':job_id,**request,'status':'running','started_at':now(),'finished_at':None,'exit_code':None,'pid':None}
            env = {**os.environ,'PYTHONUNBUFFERED':'1','PATH':'/Applications/Docker.app/Contents/Resources/bin:'+os.environ.get('PATH','')}
            command = [sys.executable,str(BASE/'adapter.py'),'--project',str(self.project),'--job-dir',str(directory)]
            if kind != 'agent':
                command = [sys.executable,str(BASE/'checks.py'),'--project',str(self.project),'--job-dir',str(directory)]
            if kind == 'agent':
                try:
                    from project_git import before_run
                    job['baseline_commit'] = before_run(self.project, goal)
                except Exception as error:
                    job['git_error'] = str(error)[:300]
            with (directory/'output.log').open('w') as output:
                # Required launch records must be writable before a child can run.
                self.save(job)
                self.history.sync(job)
                try:
                    process = subprocess.Popen(command,cwd=self.project,env=env,stdout=output,stderr=subprocess.STDOUT,start_new_session=True)
                except OSError as error:
                    job.update(status='failed', finished_at=now(), detail='Process launch failed: '+str(error))
                    self.jobs[job_id] = job
                    self._persist_lifecycle(job, 'launch-failed')
                    raise
                job['pid'] = process.pid
                self.jobs[job_id], self.processes[job_id] = job, process
                try:
                    threading.Thread(target=self.reap,args=(job_id,),daemon=True).start()
                except RuntimeError:
                    # A child without a reaper must not be left running.
                    try: os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError: pass
                    code = process.wait(timeout=5)
                    job.update(status='failed', exit_code=code, finished_at=now(), force_killed=True,
                               detail='Could not start process reaper')
                    self.processes.pop(job_id, None)
                    self._persist_lifecycle(job, 'reaper-start-failed')
                    raise
            self._persist_lifecycle(job, 'started')
            return job

    def runtime_root(self):
        own = self.project / 'harness'
        return own if (own / 'harness.py').is_file() else Path(self.coordinator.runtime) if self.coordinator else own

    def screen_titles(self):
        """User-facing titles of the project's screens (meta.title), for examples and hints."""
        titles = []
        for path in sorted((self.project / 'frontend/src/screens').glob('*.tsx'))[:40]:
            try:
                head = path.read_text(encoding='utf-8')[:4000]
            except (OSError, UnicodeError):
                continue
            match = re.search(r'''export\s+const\s+meta\s*=\s*\{[^{}]*?\btitle\s*:\s*['"]([^'"]{1,40})['"]''', head)
            if match and match.group(1) not in ('홈', 'Home'):
                titles.append(match.group(1))
        return titles

    def require_idle(self, action):
        """Project files must not change under a running model job or queue."""
        running = any(p.poll() is None for p in self.processes.values())
        queue = self.queues.active() if getattr(self, 'queues', None) else None
        if running or queue:
            raise RuntimeError(f'AI 작업이 진행 중이라 {action}을 할 수 없습니다. 작업이 끝난 뒤 다시 시도하세요.')

    def deploy_backend(self, label='manual', log=None):
        """Put verified backend sources live on 8083 (build, DB backup, rehearsal on a copy, swap with rollback kept)."""
        from backend_deploy import deploy
        if not (self.project/'backend/pom.xml').is_file():
            return {'success': True, 'skipped': True, 'detail': '백엔드 없음'}
        from project_git import commit, tag, head
        try:
            commit(self.project, '배포 직전 변경 사항')  # the deployed jar is built from this exact commit
        except Exception:
            pass
        result = deploy(self.project, self.state, label=label, log=log)
        if result.get('success') and not result.get('skipped'):
            try:
                tag(self.project, 'deploy-' + result['stamp'], f"8083 배포 {result['stamp']} ({label})\njar: {result.get('jar', '')}")
                result['project_commit'] = head(self.project)
            except Exception as error:
                result['git_error'] = str(error)[:300]
        return result

    def available_checks(self):
        modes = []
        if (self.project/'frontend/package.json').is_file(): modes.append('frontend')
        if (self.project/'harness/tests/framework_browser.cjs').is_file(): modes.append('framework')
        if (self.project/'backend/pom.xml').is_file() and (not self.metadata or self.metadata.get('test_db_url')): modes.append('backend')
        return modes

    def models(self):
        if self.model_cache is not None and time.monotonic()-self.model_cache_time < 3:
            return self.model_cache
        url = self.metadata.get('model_url', 'http://127.0.0.1:8099/v1')
        result = {'online':False, 'name':self.metadata.get('default_model') or 'mlx-community/Qwen3.8-27B-4bit',
                  'url':url, 'runtime':str(Path.home()/'.local/share/mlx-server'), 'available':[], 'unavailable':{}}
        try:
            with urllib.request.urlopen(url+'/models',timeout=1) as response:
                data = json.load(response)
                result['available'] = list(dict.fromkeys(m['id'] for m in data.get('data', []) if isinstance(m, dict) and isinstance(m.get('id'), str) and 0 < len(m['id']) <= 300))[:100]
                result['online'] = response.status == 200 and bool(result['available'])
                health=read_json((self.coordinator.state if self.coordinator else self.state)/'model-health.json',{})
                result['unavailable']={key:value.get('error','지원되지 않는 모델입니다.') for key,value in health.get(url,{}).items() if value.get('supported') is False and key in result['available']}
                result['available']=[key for key in result['available'] if key not in result['unavailable']]
        except (OSError, ValueError, TypeError): pass
        if self.coordinator:
            result['configs'] = [dict(r) for r in self.coordinator.models.records]
            result['default_config'] = self.metadata.get('model_config', '')
        self.model_cache, self.model_cache_time = result, time.monotonic()
        return result

    def _persist_lifecycle(self, job, phase):
        """Disk failure cannot prevent process control; keep bounded error evidence."""
        self.cache_time = None
        for operation, write in (('job', lambda: self.save(job)), ('history', lambda: self.history.sync(job))):
            try:
                write()
                if operation == 'history': self.catalogued.add(job['id'])
            except (OSError, sqlite3.OperationalError) as error:
                if isinstance(error, sqlite3.OperationalError):
                    code = getattr(error, 'sqlite_errorcode', None)
                    storage_error = (code is not None and code & 255 in (5, 6, 8, 10, 13, 14)) or any(
                        text in str(error).lower() for text in ('database or disk is full', 'disk i/o error',
                        'readonly database', 'unable to open database file', 'database is locked', 'database table is locked'))
                    if not storage_error: raise
                evidence = {'phase': phase, 'operation': operation, 'error': str(error)[:500], 'time': now()}
                job['persistence_errors'] = (job.get('persistence_errors', []) + [evidence])[-8:]

    def reap(self, job_id):
        process = self.processes[job_id]; code = process.wait()
        job = self.jobs.get(job_id) or {}
        if code == 0 and job.get('kind') == 'agent' and job.get('status') != 'stopping':
            # Commit before the job reads as succeeded, so a queue step after it (deploy) sees the commit.
            try:
                from project_git import after_run
                job['commit'] = after_run(self.project, job)
            except Exception as error:
                job['git_error'] = str(error)[:300]
        with self.lock:
            try:
                job = self.jobs[job_id]
                stopped = job['status'] == 'stopping'
                if stopped:
                    job.update(stop_reason='user', clean_stop=code == 0 and not job.get('force_killed', False),
                               detail='정리 대기 후 강제로 중지했습니다.' if job.get('force_killed') else '사용자가 중지했습니다.' if code == 0 else '사용자 요청으로 중지했으나 정리가 완료되지 않았습니다.')
                job.update(status='stopped' if stopped else 'succeeded' if code==0 else 'failed',exit_code=code,finished_at=now())
                self._persist_lifecycle(job, 'reaped')
            finally:
                self.processes.pop(job_id,None)
                self.cache_time = None

    def stop(self, job_id):
        with self.lock:
            process=self.processes.get(job_id)
            if process is None or process.poll() is not None: raise ValueError('이 플랫폼이 관리 중인 실행만 중지할 수 있습니다.')
            job = self.jobs[job_id]
            if job['status'] == 'stopping' and job.get('stop_signal_sent') and job.get('stop_watch_started'):
                return job
            job.update(status='stopping', stop_reason='user')
            job.setdefault('stop_requested_at', now())
            if not job.get('stop_signal_sent'):
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                    job['stop_signal_sent'] = True
                except ProcessLookupError: pass
            if not job.get('stop_watch_started'):
                threading.Thread(target=self.finish_stop, args=(job_id,process), daemon=True).start()
                job['stop_watch_started'] = True
            self._persist_lifecycle(job, 'stop-requested')
            return job

    def finish_stop(self, job_id, process, grace=60):
        try:
            process.wait(timeout=grace)
        except subprocess.TimeoutExpired:
            with self.lock:
                if process.poll() is not None: return
                job = self.jobs[job_id]
                job['force_killed'] = True
                try: os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError: pass
                self._persist_lifecycle(job, 'force-killed')

    def events(self, job_id):
        if job_id not in self.jobs: raise ValueError('실행 기록을 찾을 수 없습니다.')
        return self.event_page(job_id)['events']

    def event_page(self, job_id, before=None, after=None, limit=80, kind=None):
        with self.lock:
            if job_id not in self.jobs: raise ValueError('실행 기록을 찾을 수 없습니다.')
            self.history.sync(self.jobs[job_id])
            result=self.history.events(job_id,before,after,limit,kind)
            return {**result,'events':[compact_event(e) for e in result['events']]}

    def failure(self, job_id=None):
        with self.lock:
            self.sync_history()
            if job_id is not None and job_id not in self.jobs: raise ValueError('실행 기록을 찾을 수 없습니다.')
            job=self.jobs[job_id] if job_id is not None else self.history.latest_failed()
            if not job: return {'job':None,'failure':None}
            self.history.sync(job)
            return describe_failure(job,self.history.last_failure(job['id']),self.history.counts(job['id']),
                self.history.last_event(job['id'],'autonomy.plan'),self.history.last_event(job['id'],'autonomy.accepted'),
                self.history.last_event(job['id'],'autonomy.strategy_state'))

    def source(self, rel):
        path=(self.project/rel).resolve()
        if not path.is_relative_to(self.project) or any(x in path.parts for x in ('node_modules','target','.git','__pycache__')) or any(x.startswith('.') for x in Path(rel).parts):
            raise ValueError('프로젝트 소스 경로만 열 수 있습니다.')
        if path.relative_to(self.project).parts[:1] not in (('frontend',),('backend',)):
            raise ValueError('앱 소스만 열 수 있습니다.')
        if path.suffix not in ('.py','.tsx','.ts','.json','.java','.sql','.properties','.md','.xml','.html'): raise ValueError('지원하지 않는 소스 형식입니다.')
        if not path.is_file() or path.stat().st_size>200000: raise ValueError('파일이 없거나 보기 제한을 넘었습니다.')
        return {'path':rel,'content':path.read_text()}

    def tree(self):
        files=[]
        for section in ('frontend/src','backend/src'):
            for path in (self.project/section).rglob('*'):
                if path.is_file() and not any(x in path.parts for x in ('__pycache__','node_modules','target')) and path.suffix in ('.py','.ts','.tsx','.java','.sql','.properties','.json'):
                    files.append(str(path.relative_to(self.project)))
        return sorted(files)

    def snapshot(self):
        with self.lock:
            if self.cache and self.cache_time is not None and time.monotonic()-self.cache_time<1.5: return self.cache
            self.sync_history()
            page=self.history.jobs(limit=20)
            agent_page=self.history.jobs(limit=20,kind='agent')
            jobs=page['jobs']
            latest=jobs[0] if jobs else None
            latest_agent=self.history.latest_agent()
            agent_events=self.event_page(latest_agent['id'])['events'] if latest_agent else []
            recent=self.event_page(latest['id']) if latest else {'events':[],'total':0,'counts':{}}
            events=recent['events']
            native_path=self.project/'harness_evidence.log'
            stamp=native_path.stat().st_mtime_ns if native_path.exists() else 0
            if self.legacy_cache is None or self.legacy_stamp!=stamp:
                legacy={}
                for e in json_lines(native_path):
                    if e.get('type')!='check':continue
                    data=e.get('data',{});r=data.get('result',{});mode=data.get('mode');out=r.get('stdout','')+r.get('stderr','')
                    authentic=(mode=='frontend' and ('vite v' in out or 'src/' in out)) or (mode=='framework' and ('FRAMEWORK_OK:' in out or 'framework_cases/' in out)) or (mode=='backend' and ('[INFO]' in out or '[ERROR]' in out))
                    if authentic: legacy[mode]={'mode':mode,'success':bool(r.get('success')),'time':e.get('timestamp'),'stdout':r.get('stdout','')[-7000:],'stderr':r.get('stderr','')[-7000:],'source':'기존 실행 기록'}
                self.legacy_cache,self.legacy_stamp=legacy,stamp
            legacy=self.legacy_cache
            gates={}
            for mode,label in [('harness','하네스 자체 검사'),('frontend','프론트 빌드'),('framework','화면 동작 5개'),('backend','백엔드 통합 검사')]:
                current_hash=file_signature(self.project,mode)
                evidence=self.history.evidence(mode,current_hash) or legacy.get(mode)
                gate={'mode':mode,'label':label,'state':'unknown','evidence':evidence}
                if evidence:
                    gate['state']='passed' if evidence['success'] else 'failed'
                    if evidence.get('source_hash') and evidence['source_hash']!=current_hash:gate['state']='stale'
                    elif not evidence.get('source_hash') and evidence.get('time'):
                        try:
                            stamp=datetime.fromisoformat(evidence['time']).timestamp()
                            roots=[self.project/'frontend/src'] if mode in ('frontend','framework') else [self.project/'backend/src']
                            newest=max((p.stat().st_mtime for root in roots for p in root.rglob('*') if p.is_file() and '__pycache__' not in p.parts),default=0)
                            if newest>stamp+1:gate['state']='stale'
                        except ValueError:gate['state']='stale'
                gates[mode]=gate
            model=self.models()
            reports={'tests':0,'failures':0,'errors':0,'skipped':0}
            for p in (self.project/'backend/target/surefire-reports').glob('TEST-*.xml'):
                try:
                    attrs=ET.parse(p).getroot().attrib
                    for k in reports:reports[k]+=int(attrs.get(k,0))
                except (ET.ParseError,ValueError):pass
            counts=recent['counts']
            active=next((j for j in jobs if j['status'] in ('running','stopping')),None)
            phase='idle'
            if active:
                active_events=self.events(active['id']);last=active_events[-1]['type'] if active_events else ''
                phase='model' if last=='model.request' else 'check' if last=='check.started' else 'tool' if last=='tool.started' else 'running'
            self.cache={'time':now(),'maintenance':(self.state/'maintenance.json').exists() or bool(self.coordinator and (self.coordinator.state/'maintenance.json').exists()),'project':{'name':self.metadata.get('name','Local Inventory'),'root':str(self.project),'preview_url':self.metadata.get('preview_url','http://127.0.0.1:5292'),'id':self.metadata.get('id','default'),'checks':self.available_checks()},'model':model,
                        'jobs':jobs,'jobs_next':page['next'],'jobs_total':page['total'],'active':active,'phase':phase,'external':self.external(),'gates':list(gates.values()),'reports':reports,
                        'events':events,'event_total':recent['total'],'counts':dict(counts),'token':self.token,
                        'workspace_busy': bool(self.coordinator and self.coordinator.busy()),
                        'chat_active': bool(self.coordinator and getattr(self.coordinator,'chat_active',False)),
                        'queue': self.queues.latest(),
                        'screens': self.screen_titles()}
            self.cache.update(latest_agent=latest_agent,agent_events=agent_events,agent_jobs=agent_page['jobs'],agent_jobs_next=agent_page['next'],agent_jobs_total=agent_page['total'])
            self.cache_time=time.monotonic()
            return self.cache


class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def send_json(self,value,status=200):
        data=json.dumps(value,ensure_ascii=False,default=str).encode(); self.send_response(status); self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
    def allowed(self):
        host=self.headers.get('Host','').split(':')[0]
        if host not in ('127.0.0.1','localhost'):return False
        origin=self.headers.get('Origin')
        return not origin or origin in (f'http://127.0.0.1:{self.server.platform.port}',f'http://localhost:{self.server.platform.port}','http://127.0.0.1:5295','http://localhost:5295')
    def context(self, query):
        hub = self.server.platform
        return hub.resolve(query.get('project',[None])[0]) if hasattr(hub,'resolve') else hub
    def do_GET(self):
        if not self.allowed():self.send_json({'error':'허용되지 않은 접근입니다.'},403);return
        parsed=urlsplit(self.path);query=parse_qs(parsed.query)
        try:
            if parsed.path=='/api/projects' and hasattr(self.server.platform,'catalog'):
                self.send_json(self.server.platform.catalog());return
            app=self.context(query)
            if parsed.path=='/api/chats':self.send_json(chat_store.list_chats(app));return
            if parsed.path=='/api/queues':self.send_json({'queues':app.queues.list()});return
            match=re.fullmatch(r'/api/queues/([a-f0-9]{32})',parsed.path)
            if match:self.send_json(app.queues.get(match.group(1)));return
            match=re.fullmatch(r'/api/chats/([a-z0-9]{6,40})',parsed.path)
            if match:self.send_json(chat_store.get_chat(app,match.group(1)));return
            if parsed.path=='/api/model-configs' and hasattr(self.server.platform,'models'):
                self.send_json({'models':self.server.platform.models.records,'default':app.metadata.get('model_config','')});return
            if parsed.path=='/api/state':self.send_json(app.snapshot());return
            if parsed.path=='/api/models':self.send_json(app.models());return
            if parsed.path=='/api/preview' and hasattr(self.server.platform,'previews'):
                self.send_json(self.server.platform.previews.status(app.metadata));return
            if parsed.path=='/api/failure':self.send_json(app.failure(query.get('job',[None])[0]));return
            if parsed.path=='/api/jobs':self.send_json(app.job_page(query.get('before',[None])[0],query.get('limit',[20])[0],query.get('kind',[None])[0]));return
            if parsed.path.startswith('/api/history'):
                import project_git as vcs
                if parsed.path=='/api/history':
                    self.send_json({'status':vcs.status(app.project),'commits':vcs.history(app.project,query.get('limit',[60])[0])});return
                if parsed.path=='/api/history/working':
                    path=query.get('path',[None])[0]
                    self.send_json(vcs.working_file(app.project,path) if path else {'files':vcs.working_files(app.project)});return
                match=re.fullmatch(r'/api/history/([0-9a-f]{7,40})',parsed.path)
                if match:
                    path=query.get('path',[None])[0]
                    self.send_json(vcs.commit_file(app.project,match.group(1),path) if path else {'files':vcs.commit_files(app.project,match.group(1))});return
            if parsed.path=='/api/source/tree':self.send_json({'files':app.tree()});return
            if parsed.path=='/api/source':self.send_json(app.source(query.get('path',[''])[0]));return
            match=re.fullmatch(r'/api/jobs/([a-f0-9]{32})/strategy',parsed.path)
            if match:
                job=match.group(1)
                with app.lock:
                    if job not in app.jobs: raise ValueError('실행 기록이 없습니다.')
                    app.history.sync(app.jobs[job])
                    from strategy_report import strategy_report
                    self.send_json(strategy_report(app.history,app.jobs[job]))
                return
            match=re.fullmatch(r'/api/jobs/([a-f0-9]{32})/verification',parsed.path)
            if match:
                job=match.group(1)
                with app.lock:
                    if job not in app.jobs: raise ValueError('실행 기록이 없습니다.')
                    app.history.sync(app.jobs[job])
                    from verification_report import verification_report
                    self.send_json(verification_report(app.history,app.jobs[job]))
                return
            match=re.fullmatch(r'/api/jobs/([a-f0-9]{32})/context',parsed.path)
            if match:
                job=match.group(1)
                with app.lock:
                    if job not in app.jobs: raise ValueError('실행 기록이 없습니다.')
                    app.history.sync(app.jobs[job])
                    from context_report import context_report
                    report=context_report(app.history,app.jobs[job])
                    try: report['management']=json.loads((app.state/job/'context'/'state.json').read_text(encoding='utf-8'))
                    except (OSError,ValueError): report['management']=None
                    self.send_json(report)
                return
            match=re.fullmatch(r'/api/jobs/([a-f0-9]{32})/(events|log)',parsed.path)
            if match:
                job,kind=match.groups()
                if job not in app.jobs:raise ValueError('실행 기록이 없습니다.')
                if kind=='events':
                    if 'at' in query:
                        app.event_page(job,limit=1)
                        self.send_json({'event':app.history.event(job,query['at'][0])});return
                    self.send_json(app.event_page(job,query.get('before',[None])[0],query.get('after',[None])[0],query.get('limit',[80])[0],query.get('kind',[None])[0]));return
                with (app.state/job/'output.log').open('rb') as stream:
                    stream.seek(0,2);stream.seek(max(0,stream.tell()-60000));output=stream.read().decode('utf-8','replace')
                self.send_json({'text':output});return
            match=re.fullmatch(r'/api/jobs/([a-f0-9]{32})/diff',parsed.path)
            if match:
                job=match.group(1)
                if job not in app.jobs: raise ValueError('실행 기록이 없습니다.')
                from changes import read_changes
                self.send_json(read_changes(app.state/job,query.get('path',[None])[0],app.project));return
            if parsed.path.startswith('/api/'):
                self.send_json({'error':'경로가 없습니다.'},404);return
            path=(BASE/'web/dist'/parsed.path.lstrip('/')).resolve();dist=(BASE/'web/dist').resolve()
            if not path.is_relative_to(dist):raise ValueError('올바르지 않은 경로입니다.')
            if not path.is_file():path=dist/'index.html'
            if not path.exists():self.send_json({'error':'먼저 platform/web에서 npm run build를 실행하세요.'},503);return
            data=path.read_bytes();self.send_response(200);self.send_header('Content-Type',mimetypes.guess_type(path)[0] or 'application/octet-stream');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
        except (ValueError,OSError) as exc:self.send_json({'error':str(exc)},400)
    def do_POST(self):
        hub=self.server.platform
        if not self.allowed() or self.headers.get('X-Platform-Token')!=hub.token:self.send_json({'error':'유효하지 않은 실행 요청입니다.'},403);return
        try:
            parsed=urlsplit(self.path);app=self.context(parse_qs(parsed.query))
            length=int(self.headers.get('Content-Length','0'))
            if not 0<length<=(4500000 if parsed.path.startswith('/api/chat') else 100000):raise ValueError('요청 크기가 올바르지 않습니다.')
            if self.headers.get('Content-Type','').split(';')[0]!='application/json':raise ValueError('JSON 요청이 필요합니다.')
            body=json.loads(self.rfile.read(length))
            if not isinstance(body,dict):raise ValueError('JSON 객체가 필요합니다.')
            if parsed.path=='/api/model-configs' and hasattr(hub,'configure_model'):
                self.send_json(hub.configure_model(body,app));return
            if parsed.path=='/api/model-configs/test' and hasattr(hub,'models'):
                with hub.lock:
                    if hub.busy():raise RuntimeError('작업이 실행 중입니다. 종료 후 모델 연결을 확인하세요.')
                    hub.testing_model=True
                try: result=hub.models.test(body)
                finally:
                    with hub.lock:hub.testing_model=False
                self.send_json(result);return
            if parsed.path=='/api/projects/pick' and hasattr(hub,'pick'):self.send_json(hub.pick());return
            if parsed.path=='/api/projects' and hasattr(hub,'add'):self.send_json(hub.add(body),201);return
            if parsed.path=='/api/preview' and hasattr(hub,'previews'):self.send_json(hub.previews.ensure(app.metadata),202);return
            if parsed.path=='/api/chat':self.send_json(chat_answer(hub,app,body));return
            match=re.fullmatch(r'/api/chats/([a-z0-9]{6,40})(/delete)?',parsed.path)
            if match:self.send_json(chat_store.delete_chat(app,match.group(1)) if match.group(2) else chat_store.save_chat(app,match.group(1),body));return
            if parsed.path=='/api/chat/stream':
                def start():
                    self.send_response(200);self.send_header('Content-Type','application/x-ndjson; charset=utf-8');self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.send_header('Connection','close');self.end_headers();self.close_connection=True
                def emit(data):self.wfile.write(data);self.wfile.flush()
                chat_stream(hub,app,body,start,emit);return
            if parsed.path.startswith('/api/history/'):
                import project_git as vcs
                app.require_idle('변경 이력을 바꾸는 작업')
                action=parsed.path.rsplit('/',1)[1]
                if action=='record':self.send_json({'sha':vcs.commit_now(app.project,body.get('message'))});return
                if action=='undo':self.send_json({'sha':vcs.revert(app.project,body.get('sha'))});return
                if action=='branch':self.send_json(vcs.switch(app.project,body.get('name'),bool(body.get('create'))));return
                if action=='push':self.send_json(vcs.push(app.project));return
            if parsed.path=='/api/queues':self.send_json(app.queues.create(body),201);return
            match=re.fullmatch(r'/api/queues/([a-f0-9]{32})/(stop|resume)',parsed.path)
            if match:self.send_json(app.queues.stop(match.group(1)) if match.group(2)=='stop' else app.queues.resume(match.group(1)));return
            if parsed.path=='/api/jobs':
                body.pop('queue',None)
                if body.get('kind','agent')!='agent':raise ValueError('검사는 모델 작업의 완료 확인 과정에서 자동 실행합니다.')
                self.send_json(app.start(body),201);return
            match=re.fullmatch(r'/api/jobs/([a-f0-9]{32})/stop',parsed.path)
            if match:self.send_json(app.stop(match.group(1)));return
            self.send_json({'error':'경로가 없습니다.'},404)
        except ChatUpstreamError as exc:self.send_json({'error':str(exc)},502)
        except RuntimeError as exc:self.send_json({'error':str(exc)},409)
        except (ValueError,OSError) as exc:self.send_json({'error':str(exc)},400)


def main():
    p=argparse.ArgumentParser();p.add_argument('--project',default=str(BASE.parent/'local-only'));p.add_argument('--state',default=str(BASE/'state'));p.add_argument('--port',type=int,default=5293);a=p.parse_args()
    from workspaces import Workspaces
    server=ThreadingHTTPServer(('127.0.0.1',a.port),Handler)
    try:app=Workspaces(a.project,a.state,a.port)
    except BaseException:server.server_close();raise
    server.platform=app
    def terminate(signum,frame):raise KeyboardInterrupt
    signal.signal(signal.SIGTERM,terminate)
    print(f'Local development platform: http://127.0.0.1:{a.port}',flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:app.close();server.server_close()

if __name__=='__main__':main()
