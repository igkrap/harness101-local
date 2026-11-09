"""Persist model endpoints and per-call settings independently of run history."""
import json
import math
import time
import uuid
import urllib.request

from workspaces import local_url


class ModelRegistry:
    def __init__(self, state, projects):
        self.path = state / 'models.json'
        if self.path.exists():
            self.records = json.loads(self.path.read_text())
        else:
            self.records = []
            for p in projects:
                if p.get('default_model') and not any(r['model'] == p['default_model'] and r['url'] == p['model_url'] for r in self.records):
                    self.records.append(self.validate({'name': p['default_model'].split('/')[-1], 'model': p['default_model'], 'url': p['model_url']}))
            self.persist()

    def persist(self):
        tmp = self.path.with_suffix('.tmp')
        tmp.write_text(json.dumps(self.records, ensure_ascii=False, indent=2))
        tmp.replace(self.path)

    def validate(self, body, key=None):
        def text(field, limit):
            value = body.get(field, '')
            if not isinstance(value, str) or not value.strip() or len(value) > limit or any(ord(c) < 32 for c in value):
                raise ValueError(f'{field} 값을 확인하세요.')
            return value.strip()
        temperature = body.get('temperature', 1.0)
        timeout = body.get('timeout', 600)
        max_tokens = body.get('max_tokens', 4096)
        if type(temperature) not in (int, float) or not math.isfinite(temperature) or not 0 <= temperature <= 2:
            raise ValueError('Temperature는 0~2 사이로 입력하세요.')
        if type(timeout) is not int or not 30 <= timeout <= 3600:
            raise ValueError('응답 대기는 30~3,600초로 입력하세요.')
        if type(max_tokens) is not int or not 64 <= max_tokens <= 12288:
            raise ValueError('최대 출력은 64~12,288 토큰으로 입력하세요.')
        return {'id': key or uuid.uuid4().hex[:16], 'name': text('name', 100), 'model': text('model', 300),
                'url': local_url(body.get('url')), 'temperature': float(temperature), 'timeout': timeout, 'max_tokens': max_tokens}

    def get(self, key):
        record = next((r for r in self.records if r['id'] == key), None)
        if record is None:
            raise ValueError('등록된 모델이 아닙니다.')
        return dict(record)

    def save(self, body):
        key = body.get('id')
        if key is not None:
            self.get(key)
        record = self.validate(body, key)
        if any(r['id'] != record['id'] and r['name'] == record['name'] for r in self.records):
            raise ValueError('이미 사용 중인 설정 이름입니다.')
        self.records = [record if r['id'] == record['id'] else r for r in self.records] if key else self.records + [record]
        self.persist()
        return record

    def remove(self, key):
        self.get(key)
        self.records = [r for r in self.records if r['id'] != key]
        self.persist()

    def test(self, body):
        record = self.validate(body)
        payload = {'model': record['model'], 'messages': [{'role': 'user', 'content': 'Reply OK only.'}],
                   'max_tokens': 8, 'temperature': 0, 'chat_template_kwargs': {'enable_thinking': False}}
        request = urllib.request.Request(record['url'] + '/chat/completions', json.dumps(payload).encode(), {'Content-Type': 'application/json'})
        started = time.monotonic()
        try:
            with urllib.request.urlopen(request, timeout=min(record['timeout'], 45)) as response:
                data = json.load(response)
            choice = data['choices'][0]['message']
            if not isinstance(choice, dict) or not (choice.get('content') or choice.get('tool_calls')):
                raise ValueError('모델 응답이 비어 있습니다.')
            return {'success': True, 'duration_ms': round((time.monotonic() - started) * 1000), 'response': str(choice.get('content') or '')[:100]}
        except (OSError, ValueError, KeyError, IndexError, TypeError) as exc:
            return {'success': False, 'error': str(exc)[:500], 'duration_ms': round((time.monotonic() - started) * 1000)}
