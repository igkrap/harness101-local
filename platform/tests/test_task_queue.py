"""Model-planned queue: short plan parsing, safe fallback, sequential execution that stops on failure."""
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import task_queue


class FakeApp:
    def __init__(self, root, outcomes):
        self.state = Path(root)
        self.coordinator = None
        self.processes = {}
        self.jobs = {}
        self.started = []
        self.outcomes = list(outcomes)
        self.metadata = {'default_model': 'm', 'model_url': 'http://127.0.0.1:8099/v1'}
        self.cache_time = None

    def models(self): return {'available': ['m']}
    def external(self): return []
    def tree(self): return ['frontend/src/screens/ItemMaster.tsx', 'backend/src/main/java/ItemController.java']
    def available_checks(self): return ['frontend', 'framework', 'backend']

    def start(self, body):
        job = {'id': f'job{len(self.started)}', 'status': 'running'}
        self.started.append(body)
        self.jobs[job['id']] = job
        outcome = self.outcomes.pop(0)
        threading.Timer(0.05, lambda: job.update(status=outcome)).start()
        return job

    def stop(self, job_id): self.jobs[job_id]['status'] = 'stopped'


def reply(text):
    return lambda request, timeout: io.BytesIO(json.dumps({'choices': [{'message': {'content': text}}]}).encode())


def wait(manager, qid, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        q = manager.get(qid)
        if q['status'] in ('succeeded', 'failed', 'stopped'):
            return q
        time.sleep(0.05)
    raise AssertionError('queue did not finish')


class TaskQueueTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        task_queue.time.sleep = time.sleep

    def test_parse_plan_accepts_numbered_domain_lines_only(self):
        items = task_queue.parse_plan('계획입니다\n1. [backend] V8 마이그레이션 추가\n2) [FRONTEND] 품목 화면 버튼\n- 메모\n3. [other] x')
        self.assertEqual(items, [{'domain': 'backend', 'title': 'V8 마이그레이션 추가'},
                                 {'domain': 'frontend', 'title': '품목 화면 버튼'}])
        self.assertEqual(len(task_queue.parse_plan('\n'.join(f'{i}. [frontend] t{i}' for i in range(1, 12)))), task_queue.MAX_ITEMS)

    def test_runs_items_in_order_with_domain_checks_and_profiles(self):
        app = FakeApp(self.tmp.name, ['succeeded', 'succeeded'])
        manager = task_queue.QueueManager(app)
        with patch.object(task_queue.urllib.request, 'urlopen', side_effect=reply('1. [backend] API 추가\n2. [frontend] 화면 연결')):
            q = manager.create({'goal': '품목 API와 화면'})
            q = wait(manager, q['id'])
        self.assertEqual(q['status'], 'succeeded')
        self.assertEqual([b['goal'] for b in app.started], ['API 추가', '화면 연결'])
        self.assertEqual(app.started[0]['checks'], ['backend'])
        self.assertEqual(app.started[0]['context_profile'], 'legacy')
        self.assertEqual(app.started[1]['checks'], ['frontend', 'framework'])
        self.assertEqual(app.started[1]['context_profile'], 'focused')
        self.assertEqual(app.started[1]['queue']['completed'], ['API 추가'])
        self.assertEqual([i['status'] for i in q['items']], ['succeeded', 'succeeded'])

    def test_backend_item_is_deployed_before_the_screen_item(self):
        app = FakeApp(self.tmp.name, ['succeeded', 'succeeded'])
        order = []
        app.start = (lambda start: lambda body: (order.append('job:' + body['goal']), start(body))[1])(app.start)
        app.deploy_backend = lambda label, log: (order.append('deploy'), log('build'), {'success': True, 'stamp': 's1'})[2]
        manager = task_queue.QueueManager(app)
        with patch.object(task_queue.urllib.request, 'urlopen', side_effect=reply('1. [backend] API 추가\n2. [frontend] 화면 연결')):
            q = wait(manager, manager.create({'goal': '품목 API와 화면'})['id'])
        self.assertEqual(q['status'], 'succeeded')
        self.assertEqual(order, ['job:API 추가', 'deploy', 'job:화면 연결'])
        self.assertEqual(q['items'][0]['deploy'], 'succeeded')
        self.assertNotIn('deploy', q['items'][1])

    def test_deploy_failure_stops_queue_and_resume_retries_only_the_deploy(self):
        app = FakeApp(self.tmp.name, ['succeeded', 'succeeded'])
        results = [{'success': False, 'step': 'rehearsal', 'error': 'boom'}, {'success': True}]
        app.deploy_backend = lambda label, log: results.pop(0)
        manager = task_queue.QueueManager(app)
        with patch.object(task_queue.urllib.request, 'urlopen', side_effect=reply('1. [backend] API 추가\n2. [frontend] 화면 연결')):
            q = wait(manager, manager.create({'goal': '품목 API와 화면'})['id'])
        self.assertEqual(q['status'], 'failed')
        self.assertIn('배포가 실패', q['detail'])
        self.assertEqual(len(app.started), 1)
        manager.resume(q['id'])
        q = wait(manager, q['id'])
        self.assertEqual(q['status'], 'succeeded')
        self.assertEqual([b['goal'] for b in app.started], ['API 추가', '화면 연결'])

    def test_failure_stops_queue_and_resume_retries_failed_item_only(self):
        app = FakeApp(self.tmp.name, ['succeeded', 'failed', 'succeeded', 'succeeded'])
        manager = task_queue.QueueManager(app)
        with patch.object(task_queue.urllib.request, 'urlopen', side_effect=reply('1. [frontend] a\n2. [frontend] b\n3. [frontend] c')):
            q = wait(manager, manager.create({'goal': 'abc'})['id'])
        self.assertEqual(q['status'], 'failed')
        self.assertEqual([i['status'] for i in q['items']], ['succeeded', 'failed', 'pending'])
        self.assertEqual(len(app.started), 2)
        q = wait(manager, manager.resume(q['id'])['id'])
        self.assertEqual(q['status'], 'succeeded')
        self.assertEqual([b['goal'] for b in app.started], ['a', 'b', 'b', 'c'])

    def test_unusable_plan_falls_back_to_single_original_item(self):
        app = FakeApp(self.tmp.name, ['succeeded'])
        manager = task_queue.QueueManager(app)
        with patch.object(task_queue.urllib.request, 'urlopen', side_effect=reply('잘 모르겠습니다')):
            q = wait(manager, manager.create({'goal': '편집 패널을 버튼 토글로'})['id'])
        self.assertTrue(q['plan_fallback'])
        self.assertEqual([b['goal'] for b in app.started], ['편집 패널을 버튼 토글로'])

    def test_single_item_plan_keeps_the_original_request_text(self):
        app = FakeApp(self.tmp.name, ['succeeded'])
        manager = task_queue.QueueManager(app)
        with patch.object(task_queue.urllib.request, 'urlopen', side_effect=reply('1. [frontend] 패널을 클릭할 때만 표시되게 수정')):
            q = wait(manager, manager.create({'goal': '편집 패널을 버튼 토글로만 하게 해줘'})['id'])
        self.assertEqual([b['goal'] for b in app.started], ['편집 패널을 버튼 토글로만 하게 해줘'])
        self.assertEqual(q['items'][0]['domain'], 'frontend')

    def test_model_server_crash_is_retried_automatically(self):
        app = FakeApp(self.tmp.name, ['failed', 'succeeded'])
        manager = task_queue.QueueManager(app)
        original = app.start
        def start(body):
            job = original(body)
            (app.state / job['id']).mkdir(exist_ok=True)
            (app.state / job['id'] / 'events.jsonl').write_text('{"type":"autonomy.error","data":{"error":"[Errno 61] Connection refused"}}\n' if job['id'] == 'job0' else '')
            return job
        app.start = start
        calls = iter([reply('1. [frontend] a')] + [lambda r, timeout: io.BytesIO(b'{}')] * 5)
        with patch.object(task_queue.urllib.request, 'urlopen', side_effect=lambda r, timeout: next(calls)(r, timeout)):
            q = wait(manager, manager.create({'goal': 'a'})['id'])
        self.assertEqual(q['status'], 'succeeded')
        self.assertEqual(len(app.started), 2)

    def test_rejects_second_queue_and_marks_stale_running_as_interrupted(self):
        app = FakeApp(self.tmp.name, [])
        manager = task_queue.QueueManager(app)
        manager._write({'id': 'a' * 32, 'goal': 'x', 'status': 'running', 'created_at': '1', 'items': []})
        with self.assertRaises(RuntimeError):
            manager.create({'goal': 'y'})
        self.assertEqual(task_queue.QueueManager(app).get('a' * 32)['status'], 'interrupted')


if __name__ == '__main__':
    unittest.main()
