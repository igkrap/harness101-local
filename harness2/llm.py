"""One way to ask the local model, with everything it was given and everything it answered written down."""
import json
import time
import urllib.request
from pathlib import Path

import live

URL = 'http://127.0.0.1:8099/v1'


def model_id():
    with urllib.request.urlopen(URL + '/models', timeout=10) as response:
        return json.load(response)['data'][0]['id']


def ask(messages, record_to, name='model', max_tokens=3000, temperature=0.2):
    """Send messages, return the answer text. request/response go to record_to/<name>.json for replay and diagnosis."""
    payload = {'model': model_id(), 'messages': messages, 'max_tokens': max_tokens, 'temperature': temperature, 'top_p': 0.8, 'top_k': 20,
               'presence_penalty': 1.5, 'repetition_penalty': 1.0, 'chat_template_kwargs': {'enable_thinking': False}}
    started = time.time()
    payload = dict(payload, stream=True, stream_options={'include_usage': True})       # written as it comes, so the platform's monitor can show it
    request = urllib.request.Request(URL + '/chat/completions', data=json.dumps(payload).encode('utf-8'), headers={'Content-Type': 'application/json'})
    live.model_start(name, payload['model'])
    parts, usage = [], None
    try:
        with urllib.request.urlopen(request, timeout=900) as response:
            for raw in response:
                line = raw.decode('utf-8', 'replace').strip()
                if not line.startswith('data:'):
                    continue
                data = line[5:].strip()
                if data == '[DONE]':
                    break
                try:
                    chunk = json.loads(data)
                except ValueError:
                    continue
                usage = chunk.get('usage') or usage
                delta = ((chunk.get('choices') or [{}])[0] or {}).get('delta') or {}
                if delta.get('content') or delta.get('reasoning_content') or delta.get('reasoning'):
                    parts.append(delta.get('content') or '')
                    live.model_chunk(delta.get('content') or '', delta.get('reasoning_content') or delta.get('reasoning') or '')
    finally:
        live.model_end(usage)
    text = ''.join(parts)
    payload = {key: value for key, value in payload.items() if key not in ('stream', 'stream_options')}
    record = Path(record_to)
    record.mkdir(parents=True, exist_ok=True)
    (record / f'{name}.json').write_text(json.dumps({'request': payload, 'answer': text, 'usage': usage, 'seconds': round(time.time() - started, 1)},
                                                    ensure_ascii=False, indent=1), encoding='utf-8')
    return text
