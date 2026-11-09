"""Server-side chat conversation storage, one JSON file per conversation under the project state."""
import json
import os
import re
import tempfile
import threading

_ID = re.compile(r'[a-z0-9]{6,40}')
_LOCK = threading.Lock()
MAX_BYTES = 4_000_000
MAX_CONVERSATIONS = 500


def _dir(app):
    path = app.state / 'chats'
    path.mkdir(parents=True, exist_ok=True)
    return path


def _path(app, conv_id):
    if not isinstance(conv_id, str) or not _ID.fullmatch(conv_id):
        raise ValueError('대화 ID가 올바르지 않습니다.')
    return _dir(app) / (conv_id + '.json')


def _valid(conv):
    if not isinstance(conv, dict) or not isinstance(conv.get('turns'), list):
        raise ValueError('대화 형식이 올바르지 않습니다.')
    if conv.get('mode') not in ('chat', 'project') or not isinstance(conv.get('title'), str):
        raise ValueError('대화 형식이 올바르지 않습니다.')
    for turn in conv['turns']:
        if not isinstance(turn, dict) or turn.get('role') not in ('user', 'assistant') or not isinstance(turn.get('content'), str):
            raise ValueError('대화 메시지 형식이 올바르지 않습니다.')
    if not isinstance(conv.get('updatedAt'), (int, float)):
        raise ValueError('대화 형식이 올바르지 않습니다.')


def list_chats(app):
    items = []
    for path in _dir(app).glob('*.json'):
        try:
            conv = json.loads(path.read_text())
            items.append({'id': conv['id'], 'title': conv['title'], 'mode': conv['mode'],
                          'updatedAt': conv['updatedAt'], 'count': len(conv['turns'])})
        except (OSError, ValueError, KeyError, TypeError):
            continue
    items.sort(key=lambda item: -item['updatedAt'])
    return {'conversations': items}


def get_chat(app, conv_id):
    path = _path(app, conv_id)
    if not path.is_file():
        raise ValueError('대화를 찾을 수 없습니다.')
    return json.loads(path.read_text())


def save_chat(app, conv_id, conv):
    path = _path(app, conv_id)
    conv = {**conv, 'id': conv_id}
    _valid(conv)
    data = json.dumps(conv, ensure_ascii=False)
    if len(data.encode()) > MAX_BYTES:
        raise ValueError('대화가 너무 깁니다. 새 대화를 시작하세요.')
    with _LOCK:
        if not path.exists() and len(list(_dir(app).glob('*.json'))) >= MAX_CONVERSATIONS:
            raise ValueError('저장된 대화가 너무 많습니다. 오래된 대화를 삭제하세요.')
        fd, temp = tempfile.mkstemp(dir=path.parent, suffix='.tmp')
        with os.fdopen(fd, 'w') as stream:
            stream.write(data)
        os.replace(temp, path)
    return {'ok': True, 'id': conv_id}


def delete_chat(app, conv_id):
    path = _path(app, conv_id)
    with _LOCK:
        if path.exists():
            path.unlink()
    return {'ok': True}
