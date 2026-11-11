"""Model-planned task queue: split one request into small items, then run each as an ordinary agent job in order."""
import json
import re
import threading
import time
import urllib.error
import urllib.request
import uuid

from chat_service import _model

MAX_ITEMS = 6
_LINE = re.compile(r'^\s*(\d{1,2})\s*[.)]\s*\[(frontend|backend)\]\s*(.+?)\s*$', re.I)
TERMINAL = ('succeeded', 'failed', 'stopped', 'interrupted')


def now():
    return time.strftime('%Y-%m-%dT%H:%M:%S')


def planner_prompt(goal, inventory, code='', schema=''):
    return (
        '아래 요청을 순서대로 할 작업 목록으로 나눠줘.\n'
        '- 작은 변경이면 한 줄이면 된다.\n'
        '- 한 줄은 끝났을 때 화면이나 API로 확인할 수 있는 결과가 있어야 한다. '
        '그래서 새 기능은 보통 "[backend] 부서 API" 다음 "[frontend] 부서 등록 화면" 두 줄이다(API 줄에서 테이블·엔티티까지 같이 만든다).\n'
        '- 요청에 없는 기능은 더하지 말고 사용자 표현을 그대로 쓴다. 항목(필드)을 정해주지 않았으면 그 업무에서 흔히 쓰는 것으로 정한다.\n'
        '- 새 화면은 frontend/src/screens 에 파일 하나만 만들면 메뉴에 자동으로 나온다(App.tsx, Home.tsx 수정 불필요).\n'
        '- 줄 끝에 " || 방향: " 뒤로 고칠 파일과 방법을 쓴다. 화면 props로 안 되고 공통 컴포넌트를 고쳐야 하면 그 파일을 같은 줄에 적는다.\n'
        f'- 최대 {MAX_ITEMS}줄, 다른 말 없이 이 형식으로만:\n'
        '1. [backend] 할 일 || 방향: 파일과 방법\n'
        '2. [frontend] 할 일 || 방향: 파일과 방법\n\n'
        f'프로젝트 파일 일부:\n{inventory}\n\n'
        + (f'관련 코드 (참고용):\n{code}\n\n' if code else '')
        + (f'DB 상태: {schema}\n\n' if schema else '')
        + f'요청: {goal}\n'
    )


def parse_plan(text):
    items = []
    for line in (text or '').splitlines():
        match = _LINE.match(line)
        if match:
            text = re.sub(r'\s+', ' ', match.group(3)).strip()
            title, _, approach = text.partition('||')
            approach = re.sub(r'^\s*방향\s*:\s*', '', approach).strip()[:600]
            title = title.strip()[:600]
            if title:
                items.append({'domain': match.group(2).lower(), 'title': title, **({'approach': approach} if approach else {})})
    return items[:MAX_ITEMS]


def schema_note(app):
    """Which tables exist now (old migration files of dropped tables mislead the planner)."""
    try:
        import sys
        runtime = str(app.runtime_root())
        if runtime not in sys.path:
            sys.path.insert(0, runtime)
        import schema_state
        return schema_state.note(app.project)
    except Exception:
        return ''


def code_context(app, goal):
    """Target screen source and the components it renders, via the harness import graph."""
    try:
        import sys
        runtime = str(app.runtime_root())
        if runtime not in sys.path:
            sys.path.insert(0, runtime)
        from import_graph import planner_context
        return planner_context(app.project, goal)
    except Exception:  # context is an aid; planning must still work without it
        return ''


def inventory(app):
    try:
        paths = app.tree()
    except (OSError, ValueError):
        return ''
    keep = [p for p in paths if re.search(r'(frontend/src/(screens|framework)/[^/]+\.tsx?$|Controller\.java$|db/migration/V[^/]+\.sql$)', p)]
    return '\n'.join(keep)[:2500]


class QueueManager:
    def __init__(self, app):
        self.app = app
        self.dir = app.state / 'queues'
        self.dir.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.deploy_lock = threading.Lock()
        self.threads = {}
        for path in self.dir.glob('*.json'):
            queue = self._read(path)
            if queue and queue.get('status') in ('planning', 'running', 'stopping'):
                queue.update(status='interrupted', detail='플랫폼 재시작으로 큐 진행이 멈췄습니다. 이어서 실행할 수 있습니다.')
                self._write(queue)

    # storage
    def _read(self, path):
        try:
            return json.loads(path.read_text())
        except (OSError, ValueError):
            return None

    def _write(self, queue):
        path = self.dir / (queue['id'] + '.json')
        temp = path.with_suffix('.tmp')
        temp.write_text(json.dumps(queue, ensure_ascii=False))
        temp.replace(path)

    def get(self, queue_id):
        if not re.fullmatch(r'[a-f0-9]{32}', queue_id or ''):
            raise ValueError('큐 ID가 올바르지 않습니다.')
        queue = self._read(self.dir / (queue_id + '.json'))
        if not queue:
            raise ValueError('큐를 찾을 수 없습니다.')
        return queue

    def list(self, limit=20):
        items = [q for q in (self._read(p) for p in self.dir.glob('*.json')) if q]
        items.sort(key=lambda q: q.get('created_at', ''), reverse=True)
        return items[:limit]

    def active(self):
        return next((q for q in self.list(50) if q.get('status') in ('planning', 'running', 'stopping')), None)

    def latest(self):
        items = self.list(1)
        return items[0] if items else None

    # lifecycle
    def create(self, body):
        goal = body.get('goal', '').strip() if isinstance(body.get('goal'), str) else ''
        if not 1 <= len(goal) <= 16000:
            raise ValueError('요청 내용을 입력하세요. 최대 16,000자입니다.')
        model = body.get('model')
        hub = self.app.coordinator
        with self.lock:
            if self.active():
                raise RuntimeError('이미 실행 중인 작업 큐가 있습니다.')
            busy = hub.busy() if hub else any(p.poll() is None for p in self.app.processes.values())
            if busy or self.app.external():
                raise RuntimeError('실행 중인 작업이 있습니다. 완료 또는 중지 후 시작하세요.')
            queue = {'id': uuid.uuid4().hex, 'goal': goal, 'model': model, 'status': 'planning', 'created_at': now(),
                     'finished_at': None, 'items': [], 'plan_raw': '', 'detail': '',
                     'options': {k: body[k] for k in ('rounds', 'thinking', 'edit_format', 'origin') if k in body}}
            self._write(queue)
            if hub is not None:
                hub.queue_planning = True
        self._spawn(queue['id'], plan=True)
        return queue

    def resume(self, queue_id):
        with self.lock:
            queue = self.get(queue_id)
            if queue['status'] not in ('failed', 'stopped', 'interrupted'):
                raise RuntimeError('멈춘 큐만 이어서 실행할 수 있습니다.')
            if self.active():
                raise RuntimeError('이미 실행 중인 작업 큐가 있습니다.')
            for item in queue['items']:
                if item['status'] in ('failed', 'stopped', 'interrupted'):
                    item.update(status='pending', job_id=None, attempts=item.get('attempts', 0))
            queue.update(status='running', detail='', finished_at=None)
            self._write(queue)
        self._spawn(queue_id, plan=not queue['items'])
        return queue

    def stop(self, queue_id):
        with self.lock:
            queue = self.get(queue_id)
            if queue['status'] not in ('planning', 'running'):
                raise RuntimeError('실행 중인 큐가 아닙니다.')
            queue['status'] = 'stopping'
            self._write(queue)
            running = next((i for i in queue['items'] if i['status'] == 'running' and i.get('job_id')), None)
        if running:
            try:
                self.app.stop(running['job_id'])
            except ValueError:
                pass
        return queue

    def _spawn(self, queue_id, plan):
        thread = threading.Thread(target=self._run, args=(queue_id, plan), daemon=True)
        self.threads[queue_id] = thread
        thread.start()

    def _update(self, queue_id, **changes):
        with self.lock:
            queue = self.get(queue_id)
            queue.update(changes)
            self._write(queue)
            self.app.cache_time = None
            return queue

    def _stopping(self, queue_id):
        return self.get(queue_id)['status'] == 'stopping'

    def _finish(self, queue_id, status, detail=''):
        self._update(queue_id, status=status, detail=detail, finished_at=now())

    def _run(self, queue_id, plan):
        hub = self.app.coordinator
        try:
            if plan:
                try:
                    items = self._plan(queue_id)
                finally:
                    if hub is not None:
                        hub.queue_planning = False
                if self._stopping(queue_id):
                    return self._finish(queue_id, 'stopped', '사용자가 중지했습니다.')
                self._update(queue_id, items=items, status='running')
            elif hub is not None:
                hub.queue_planning = False
            queue = self.get(queue_id)
            done = []
            for index in range(len(queue['items'])):
                queue = self.get(queue_id)
                item = queue['items'][index]
                if queue['status'] == 'stopping':
                    return self._finish(queue_id, 'stopped', '사용자가 중지했습니다.')
                if item['status'] != 'succeeded':
                    status = self._run_item(queue_id, index, done)
                    if status != 'succeeded':
                        label = {'stopped': '중지됨', 'failed': '실패'}.get(status, status)
                        current = self.get(queue_id)
                        detail = current.get('detail') if current['items'][index].get('note') == '앱 서버 응답 없음' else ''
                        return self._finish(queue_id, 'stopped' if status == 'stopped' else 'failed',
                                            detail or f'{index + 1}번 항목 {label}. 이어서 실행하면 이 항목부터 다시 시도합니다.')
                if (item['domain'] == 'backend' and item.get('deploy') not in ('succeeded', 'skipped')
                        and getattr(self.app, 'deploy_backend', None)):
                    # Later screen items and the user need the new API in the running app, not only in the test DB.
                    result = self._deploy(queue_id, index)
                    if not result.get('success'):
                        return self._finish(queue_id, 'failed',
                                            f"{index + 1}번 항목은 검증됐지만 실행 중인 백엔드 배포가 실패했습니다"
                                            f"({result.get('step')}): {str(result.get('error', ''))[:300]} "
                                            '기존 서버는 그대로입니다. 이어서 실행하면 배포부터 다시 시도합니다.')
                done.append(item['title'])
            self._finish(queue_id, 'succeeded')
        except Exception as error:  # keep the queue record truthful on unexpected errors
            if hub is not None:
                hub.queue_planning = False
            self._finish(queue_id, 'failed', '큐 실행 오류: ' + str(error)[:300])

    def _plan(self, queue_id):
        queue = self.get(queue_id)
        goal = queue['goal']
        started = time.time()
        raw, error = '', ''
        try:
            model, url, timeout, _ = _model(self.app.coordinator, self.app, queue.get('model'))
            # Planning runs once per queue and decides where every later edit goes; reasoning is worth
            # a few minutes here (without it the planner misread which component hard-codes the split).
            payload = {'model': model, 'max_tokens': 4000, 'temperature': 0.3,
                       'chat_template_kwargs': {'enable_thinking': True},
                       # Brief reasoning keeps the planner accurate (it still checks which file hard-codes the
                       # behavior) while cutting ~1,800 thinking tokens to ~600-1,400 (3-5 min instead of 5-9).
                       'messages': [{'role': 'system', 'content': 'Think briefly: at most 8 short lines of reasoning. Decide which file actually hard-codes the behavior, then answer.'},
                                    {'role': 'user', 'content': planner_prompt(goal, inventory(self.app), code_context(self.app, goal), schema_note(self.app))}]}
            request = urllib.request.Request(url + '/chat/completions', json.dumps(payload, ensure_ascii=False).encode(),
                                             {'Content-Type': 'application/json'})
            with urllib.request.urlopen(request, timeout=1500) as response:
                raw = json.load(response)['choices'][0]['message']['content'] or ''
        except (OSError, ValueError, KeyError, IndexError, TypeError) as exc:
            error = str(exc)[:300]
        items = parse_plan(raw)
        fallback = not items
        if len(items) == 1:
            # A single item is the request itself; a model paraphrase only adds or loses conditions.
            items = [{**items[0], 'title': goal}]
        if fallback:
            # Never block the run on a bad plan: run the original request as a single item.
            items = [{'domain': 'backend' if self._backend_only(goal) else 'frontend', 'title': goal}]
        checks = self.app.available_checks()
        result = []
        for item in items:
            wanted = ['backend'] if item['domain'] == 'backend' else ['frontend', 'framework']
            selected = [c for c in wanted if c in checks] or [c for c in ('frontend',) if c in checks] or list(checks)[:1]
            result.append({**item, 'checks': selected, 'status': 'pending', 'job_id': None, 'attempts': 0})
        self._update(queue_id, plan_raw=raw[:4000], plan_seconds=round(time.time() - started, 1),
                     plan_fallback=fallback, plan_error=error)
        return result

    @staticmethod
    def _backend_only(goal):
        text = goal.casefold()
        return any(t in text for t in ('api', '백엔드', 'sql', '마이그레이션')) and not any(t in text for t in ('화면', '버튼', '패널'))

    def _infra_failure(self, job_id):
        """True when the job died because the model server went away, not because of its own work."""
        try:
            lines = (self.app.state / job_id / 'events.jsonl').read_text().splitlines()[-12:]
        except OSError:
            return False
        text = ' '.join(lines)
        return any(marker in text for marker in ('Connection refused', 'Connection reset', 'RemoteDisconnected'))

    def _wait_for_model(self, queue_id, seconds=600):
        try:
            _, url, _, _ = _model(self.app.coordinator, self.app, self.get(queue_id).get('model'))
        except (ValueError, OSError):
            url = 'http://127.0.0.1:8099/v1'
        end = time.time() + seconds
        while time.time() < end and not self._stopping(queue_id):
            try:
                with urllib.request.urlopen(url + '/models', timeout=5):
                    return True
            except OSError:
                time.sleep(5)
        return False

    def _run_item(self, queue_id, index, done):
        for _ in range(3):
            status, job_id = self._run_item_once(queue_id, index, done)
            if status == 'failed' and job_id and self._infra_failure(job_id) and self._wait_for_model(queue_id):
                self._set_item(queue_id, index, note='모델 서버 중단으로 자동 재시도')
                continue
            return status
        return status

    def _app_down(self):
        """Why the app under test cannot be used (backend/DB down), or '' when it answers."""
        base = (getattr(self.app, 'metadata', None) or {}).get('preview_url')
        if not base:
            return ''
        try:
            with urllib.request.urlopen(base.rstrip('/') + '/api/auth/session', timeout=10) as response:
                return '' if response.status < 500 else f'HTTP {response.status}'
        except urllib.error.HTTPError as error:
            return '' if error.code < 500 else f'HTTP {error.code}'
        except OSError as error:
            return str(error)[:120]

    def _run_item_once(self, queue_id, index, done):
        queue = self.get(queue_id)
        item = queue['items'][index]
        down = self._app_down()
        if down:
            # Checks log in to the running app; without it every run fails for reasons the model cannot fix.
            self._set_item(queue_id, index, status='failed', note='앱 서버 응답 없음')
            self._update(queue_id, detail=f'앱 서버(백엔드·DB)가 응답하지 않아 시작하지 않았습니다 ({down}). Docker와 앱 서버를 켠 뒤 이어서 실행하세요.')
            return 'failed', None
        body = {'kind': 'agent', 'goal': item['title'], 'checks': item['checks'], 'model': queue.get('model'),
                'context_profile': 'legacy' if item['domain'] == 'backend' else 'focused',
                'queue': {'id': queue_id, 'index': index, 'total': len(queue['items']), 'goal': queue['goal'][:2000],
                          'completed': done[-6:], **({'approach': item['approach']} if item.get('approach') else {})},
                **queue.get('options', {})}
        if not body['model']:
            body.pop('model')
        job = None
        while job is None:
            if self._stopping(queue_id):
                return 'stopped', None
            try:
                job = self.app.start(body)
            except RuntimeError:
                time.sleep(5)  # chat or another process holds the model; wait instead of failing the queue
        self._set_item(queue_id, index, status='running', job_id=job['id'], attempts=item.get('attempts', 0) + 1,
                       started_at=now())
        while True:
            status = self.app.jobs.get(job['id'], {}).get('status')
            if status in TERMINAL:
                break
            time.sleep(2)
        self._set_item(queue_id, index, status=status, finished_at=now())
        return status, job['id']

    def _deploy(self, queue_id, index):
        steps = {'build': 'JAR 빌드', 'backup': 'DB 백업', 'rehearsal': '백업 사본에서 업그레이드 시험', 'swap': '서버 교체'}
        self._set_item(queue_id, index, deploy='running', deploy_note='배포 준비')
        with self.deploy_lock:
            result = self.app.deploy_backend(label=f'queue-{queue_id[:8]}-{index + 1}',
                                             log=lambda step: self._set_item(queue_id, index, deploy_note=steps.get(step, step)))
        status = 'skipped' if result.get('skipped') else 'succeeded' if result.get('success') else 'failed'
        self._set_item(queue_id, index, deploy=status, deploy_note=result.get('detail') or result.get('error', '')[:300] or '실행 중인 서버에 반영됨',
                       deploy_record=result.get('stamp'))
        return result

    def _set_item(self, queue_id, index, **changes):
        with self.lock:
            queue = self.get(queue_id)
            queue['items'][index].update(changes)
            self._write(queue)
            self.app.cache_time = None
