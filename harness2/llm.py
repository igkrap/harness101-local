"""One way to ask the local model, with everything it was given and everything it answered written down."""
import json
import time
import http.client
import urllib.parse
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
    live.model_start(name, payload['model'], messages)
    parts, usage = [], None
    where = urllib.parse.urlsplit(URL)
    connection = http.client.HTTPConnection(where.hostname, where.port or 80, timeout=900)
    try:
        live.attach(connection)                           # the stop button closes it - also while the model is still reading (no answer yet)
        live.stopping()
        connection.request('POST', where.path + '/chat/completions', body=json.dumps(payload).encode('utf-8'), headers={'Content-Type': 'application/json'})
        response = connection.getresponse()
        if response.status != 200:
            raise RuntimeError(f'모델 서버가 거절했습니다 ({response.status}): ' + response.read().decode('utf-8', 'replace')[:300])
        for raw in response:
            live.stopping()
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
    except live.Stopped:
        raise
    except Exception:
        live.stopping()                                   # a connection closed by the stop button is a stop, not a model failure
        raise
    finally:
        live.attach(None)
        connection.close()
        live.model_end(usage)
    text = ''.join(parts)
    payload = {key: value for key, value in payload.items() if key not in ('stream', 'stream_options')}
    record = Path(record_to)
    record.mkdir(parents=True, exist_ok=True)
    (record / f'{name}.json').write_text(json.dumps({'request': payload, 'answer': text, 'usage': usage, 'seconds': round(time.time() - started, 1)},
                                                    ensure_ascii=False, indent=1), encoding='utf-8')
    return text
