"""One way to ask the local model, with everything it was given and everything it answered written down."""
import json
import time
import urllib.request
from pathlib import Path

URL = 'http://127.0.0.1:8099/v1'


def model_id():
    with urllib.request.urlopen(URL + '/models', timeout=10) as response:
        return json.load(response)['data'][0]['id']


def ask(messages, record_to, name='model', max_tokens=3000, temperature=0.2):
    """Send messages, return the answer text. request/response go to record_to/<name>.json for replay and diagnosis."""
    payload = {'model': model_id(), 'messages': messages, 'max_tokens': max_tokens, 'temperature': temperature, 'top_p': 0.8, 'top_k': 20,
               'presence_penalty': 1.5, 'repetition_penalty': 1.0, 'chat_template_kwargs': {'enable_thinking': False}}
    started = time.time()
    request = urllib.request.Request(URL + '/chat/completions', data=json.dumps(payload).encode('utf-8'), headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(request, timeout=900) as response:
        reply = json.load(response)
    text = (reply.get('choices') or [{}])[0].get('message', {}).get('content') or ''
    record = Path(record_to)
    record.mkdir(parents=True, exist_ok=True)
    (record / f'{name}.json').write_text(json.dumps({'request': payload, 'answer': text, 'usage': reply.get('usage'), 'seconds': round(time.time() - started, 1)},
                                                    ensure_ascii=False, indent=1), encoding='utf-8')
    return text
