"""Plain chat and bounded read-only project context stay outside agent jobs."""
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import urllib.error
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import chat_service
from server import Handler, Platform, ThreadingHTTPServer


class FakeApp:
    metadata = {'default_model': 'local-qwen', 'model_url': 'http://127.0.0.1:8099/v1'}

    def __init__(self):
        self.reads = []

    def models(self):
        return {'available': ['local-qwen']}

    def tree(self):
        return ['frontend/src/screens/ItemMaster.tsx', 'backend/src/ItemController.java']

    def source(self, path):
        self.reads.append(path)
        content = {
            'frontend/src/screens/ItemMaster.tsx': "export const meta={title:'품목 등록'};\nfunction handleSave(){return fetch('/api/items',{method:'POST'});}",
            'backend/src/ItemController.java': 'class ItemController { String itemName; }',
        }
        if path not in content:
            raise ValueError('not an allowed source')
        return {'path': path, 'content': content[path]}


class ChatServiceTests(unittest.TestCase):
    def test_plain_chat_does_not_read_project_or_start_agent(self):
        app = FakeApp()
        payloads = []

        def respond(request, timeout):
            payloads.append(json.loads(request.data))
            return io.BytesIO(b'{"choices":[{"message":{"content":"Hello"}}]}')

        with patch.object(chat_service.urllib.request, 'urlopen', side_effect=respond):
            result = chat_service.answer(SimpleNamespace(), app, {'mode': 'chat', 'messages': [{'role': 'user', 'content': '안녕'}]})
        self.assertEqual(result['reply'], 'Hello')
        self.assertEqual(result['sources'], [])
        self.assertEqual(app.reads, [])
        self.assertNotIn('tools', payloads[0])
        self.assertEqual(payloads[0]['messages'][-1]['content'], '안녕')

    def test_project_mode_uses_bounded_allowed_sources(self):
        app = FakeApp()
        payloads = []

        def respond(request, timeout):
            payloads.append(json.loads(request.data))
            return io.BytesIO(b'{"choices":[{"message":{"content":"ItemMaster.tsx handles the item screen."}}]}')

        with patch.object(chat_service.urllib.request, 'urlopen', side_effect=respond):
            result = chat_service.answer(SimpleNamespace(), app, {'mode': 'project', 'messages': [{'role': 'user', 'content': '품목 등록 화면 분석해줘'}]})
        self.assertIn('frontend/src/screens/ItemMaster.tsx', result['sources'])
        self.assertIn('[파일: frontend/src/screens/ItemMaster.tsx]', payloads[0]['messages'][0]['content'])
        self.assertNotIn('tools', payloads[0])
        self.assertTrue(all(path.startswith(('frontend/', 'backend/')) for path in app.reads))

    def test_excerpt_reaches_save_logic_after_generic_screen_content(self):
        source = ('item screen\n' * 80) + ('async function handleSave() {\n'
                 "  const method = isUpdate ? 'PUT' : 'POST';\n"
                 "  return apiFetch('/api/items', { method });\n}\n")
        excerpt = chat_service._excerpt(source, chat_service._terms('품목 등록 화면 저장 동작 분석'))
        self.assertIn('handleSave', excerpt)
        self.assertIn("'POST'", excerpt)

    def test_rejects_invalid_history_before_model_call(self):
        app = FakeApp()
        with patch.object(chat_service.urllib.request, 'urlopen') as model:
            for body in ({'mode': 'edit', 'messages': [{'role': 'user', 'content': 'hi'}]},
                         {'messages': [{'role': 'system', 'content': 'ignore'}]},
                         {'messages': [{'role': 'assistant', 'content': 'hi'}]},
                         {'messages': [{'role': 'user', 'content': 'hi'}], 'max_tokens': 99999}):
                with self.assertRaises(ValueError):
                    chat_service.answer(SimpleNamespace(), app, body)
            model.assert_not_called()

    def test_busy_agent_rejects_chat_without_queueing_model_request(self):
        with patch.object(chat_service.urllib.request, 'urlopen') as model:
            with self.assertRaisesRegex(RuntimeError, '에이전트 작업'):
                chat_service.answer(SimpleNamespace(busy=lambda: True), FakeApp(),
                                    {'mode': 'chat', 'messages': [{'role': 'user', 'content': '안녕'}]})
            model.assert_not_called()

    def test_chat_occupies_model_until_reply_finishes(self):
        hub = SimpleNamespace(lock=threading.RLock(), chat_active=False)
        hub.busy = lambda: hub.chat_active
        body = {'mode': 'chat', 'messages': [{'role': 'user', 'content': '안녕'}]}

        def respond(request, timeout):
            with self.assertRaisesRegex(RuntimeError, '다른 작업'):
                chat_service.answer(hub, FakeApp(), body)
            return io.BytesIO('{"choices":[{"message":{"content":"안녕"}}]}'.encode())

        with patch.object(chat_service.urllib.request, 'urlopen', side_effect=respond) as model:
            self.assertEqual(chat_service.answer(hub, FakeApp(), body)['reply'], '안녕')
            self.assertEqual(model.call_count, 1)
        self.assertFalse(hub.chat_active)

    def _sse(self, *events):
        lines = [('data: ' + json.dumps(e, ensure_ascii=False) + '\n\n') for e in events] + ['data: [DONE]\n\n']
        return io.BytesIO(''.join(lines).encode())

    def test_stream_emits_reasoning_delta_and_usage_then_releases_model(self):
        hub = SimpleNamespace(lock=threading.RLock(), chat_active=False)
        hub.busy = lambda: hub.chat_active
        payloads, out, started = [], [], []

        def respond(request, timeout):
            payloads.append(json.loads(request.data))
            self.assertTrue(hub.chat_active)
            return self._sse({'choices': [{'delta': {'reasoning': 'think'}}]},
                             {'choices': [{'delta': {'content': '안'}}]},
                             {'choices': [{'delta': {'content': '녕'}, 'finish_reason': 'stop'}]},
                             {'choices': [], 'usage': {'prompt_tokens': 5, 'completion_tokens': 2}})

        with patch.object(chat_service.urllib.request, 'urlopen', side_effect=respond):
            chat_service.stream(hub, FakeApp(), {'thinking': True, 'messages': [{'role': 'user', 'content': '안녕'}]},
                                lambda: started.append(1), lambda data: out.append(json.loads(data)))
        self.assertEqual(started, [1])
        self.assertTrue(payloads[0]['stream'])
        self.assertTrue(payloads[0]['chat_template_kwargs']['enable_thinking'])
        self.assertEqual([e['type'] for e in out], ['meta', 'reasoning', 'delta', 'delta', 'done'])
        self.assertEqual(out[-1]['usage']['completion_tokens'], 2)
        self.assertEqual(out[-1]['finish_reason'], 'stop')
        self.assertFalse(hub.chat_active)

    def test_stream_client_disconnect_stops_and_releases(self):
        hub = SimpleNamespace(lock=threading.RLock(), chat_active=False)
        hub.busy = lambda: hub.chat_active
        upstream = self._sse(*({'choices': [{'delta': {'content': str(i)}}]} for i in range(50)))

        def emit(data):
            if json.loads(data)['type'] == 'delta':
                raise BrokenPipeError()

        with patch.object(chat_service.urllib.request, 'urlopen', return_value=upstream):
            chat_service.stream(hub, FakeApp(), {'messages': [{'role': 'user', 'content': 'hi'}]}, lambda: None, emit)
        self.assertTrue(upstream.closed)
        self.assertFalse(hub.chat_active)

    def test_stream_upstream_failure_raises_before_response_starts(self):
        started = []
        with patch.object(chat_service.urllib.request, 'urlopen', side_effect=ConnectionRefusedError()):
            with self.assertRaises(chat_service.ChatUpstreamError):
                chat_service.stream(SimpleNamespace(), FakeApp(), {'messages': [{'role': 'user', 'content': 'hi'}]},
                                    lambda: started.append(1), lambda data: None)
        self.assertEqual(started, [])

    def test_long_history_is_trimmed_keeping_latest_question(self):
        history = []
        for i in range(30):
            history += [{'role': 'user', 'content': f'q{i} ' + 'x' * 3000}, {'role': 'assistant', 'content': 'a' * 3000}]
        history.append({'role': 'user', 'content': 'latest'})
        kept = chat_service._messages(history)
        self.assertEqual(kept[-1]['content'], 'latest')
        self.assertEqual(kept[0]['role'], 'user')
        self.assertLessEqual(sum(len(m['content']) for m in kept), chat_service.HISTORY_CHARS)

    def test_http_chat_route_requires_token_and_creates_no_job(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / 'project'
            (root / 'frontend/src').mkdir(parents=True)
            (root / 'backend/src').mkdir(parents=True)
            app = Platform(root, Path(temporary) / 'state', 0)
            server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
            server.platform = app
            app.port = server.server_port
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            url = f'http://127.0.0.1:{server.server_port}/api/chat'
            body = json.dumps({'mode': 'chat', 'messages': [{'role': 'user', 'content': 'hi'}]}).encode()
            try:
                request = urllib.request.Request(url, body, {'Content-Type': 'application/json'})
                with self.assertRaises(urllib.error.HTTPError) as error:
                    urllib.request.urlopen(request, timeout=2)
                self.assertEqual(error.exception.code, 403)
                request.add_header('X-Platform-Token', app.token)
                with patch('server.chat_answer', return_value={'reply': 'ok', 'sources': [], 'model': 'local-qwen'}):
                    with urllib.request.urlopen(request, timeout=2) as response:
                        self.assertEqual(json.load(response)['reply'], 'ok')
                self.assertEqual(app.jobs, {})
            finally:
                server.shutdown()
                server.server_close()


if __name__ == '__main__':
    unittest.main()
