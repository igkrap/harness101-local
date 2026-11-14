"""Project registry. Existing project data stays in place; new journals are isolated."""
import hashlib
import json
from pathlib import Path
import secrets
import threading
import os
import subprocess
from urllib.parse import urlsplit


def local_url(value, optional=False):
    if optional and not value:
        return ''
    if not isinstance(value, str):
        raise ValueError('로컬 서버 주소를 입력하세요.')
    parsed = urlsplit(value)
    if parsed.scheme != 'http' or parsed.hostname not in ('localhost', '127.0.0.1') or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError('localhost 또는 127.0.0.1의 HTTP 주소를 입력하세요.')
    try:
        parsed.port
    except ValueError:
        raise ValueError('포트가 올바르지 않습니다.')
    return value.rstrip('/')


class Workspaces:
    def __init__(self, project, state, port=5293):
        from server import Platform
        self.state, self.port = Path(state).resolve(), port
        self.state.mkdir(parents=True, exist_ok=True)
        self.path = self.state / 'projects.json'
        self.lock = threading.RLock()
        self.testing_model = False
        self.chat_active = False
        self.token = secrets.token_urlsafe(32)
        self.runtime = str(Path(project).resolve() / 'harness')
        if self.path.exists():
            self.records = json.loads(self.path.read_text())
        else:
            self.records = [{'id': 'default', 'name': 'Local Inventory', 'root': str(Path(project).resolve()), 'preview_url': 'http://127.0.0.1:5292', 'model_url': 'http://127.0.0.1:8099/v1', 'default_model': 'mlx-community/Qwen3.8-27B-4bit', 'test_db_url': 'jdbc:postgresql://mdi-db:5432/mdi_local_test'}]
            self.persist()
        renamed=False
        for record in self.records:
            name=Path(record['root']).name
            if record.get('name')!=name:record['name']=name;renamed=True
        if renamed:self.persist()
        from preview import Previews
        self.previews=Previews(self.state)
        self.apps = {}
        from model_registry import ModelRegistry
        self.models = ModelRegistry(self.state, self.records)
        self.resolve()

    def configure_model(self, body, app):
        with self.lock:
            action = body.get('action', 'save')
            if action == 'save':
                result = self.models.save(body)
            elif action == 'remove':
                self.models.remove(body.get('id'))
                for record in self.records:
                    if record.get('model_config') == body.get('id'):
                        record.pop('model_config', None)
                self.persist()
                result = {'removed': True}
            elif action == 'default':
                model = self.models.get(body.get('id'))
                app.metadata.update(model_config=model['id'], default_model=model['model'], model_url=model['url'])
                self.persist()
                result = model
            else:
                raise ValueError('알 수 없는 모델 설정 요청입니다.')
            for context in self.apps.values():
                context.model_cache = None
                context.cache_time = None
            return result

    def persist(self):
        temporary = self.path.with_suffix('.tmp')
        temporary.write_text(json.dumps(self.records, ensure_ascii=False, indent=2))
        temporary.replace(self.path)

    def resolve(self, project_id=None):
        from server import Platform
        with self.lock:
            record = next((r for r in self.records if r['id'] == (project_id or self.records[0]['id'])), None)
            if record is None:
                raise ValueError('등록된 프로젝트가 아닙니다.')
            key = record['id']
            if key not in self.apps:
                state = self.state if key == self.records[0]['id'] else self.state / 'projects' / key / 'runs'
                app = Platform(record['root'], state, self.port)
                app.metadata, app.coordinator = record, self
                app.token, app.lock = self.token, self.lock
                self.apps[key] = app
            return self.apps[key]

    def catalog(self):
        with self.lock:
            import projects
            return {'kinds': projects.kinds(), 'projects': [{**r, 'available': Path(r['root']).is_dir(), 'active': next((j for j in self.apps[r['id']].jobs.values() if j['status'] in ('running', 'stopping')), None) if r['id'] in self.apps else None} for r in self.records]}

    def busy(self):
        if self.testing_model or self.chat_active or getattr(self, 'queue_planning', False): return True
        if any(any(p.poll() is None for p in app.processes.values()) for app in self.apps.values()): return True
        # Include workers from registered projects not opened in this process yet.
        result=subprocess.run(['ps','-axo','pid=,command='],capture_output=True,text=True,timeout=3)
        for line in result.stdout.splitlines():
            fields=line.strip().split(None,1)
            if len(fields)!=2 or not fields[0].isdigit() or int(fields[0])==os.getpid(): continue
            command=fields[1]
            if 'python' not in command.lower(): continue
            if any(str(Path(r['root'])/'harness/harness.py') in command or
                   (('platform/adapter.py' in command or 'platform/checks.py' in command) and '--project '+r['root'] in command)
                   for r in self.records): return True
        return False

    def add(self, body):
        with self.lock:
            raw = body.get('root', '')
            if not isinstance(raw, str) or not Path(raw).expanduser().is_absolute():
                raise ValueError('프로젝트 폴더를 선택하세요.')
            root = Path(raw).expanduser().resolve()
            if not root.is_dir() or not any((root / part).is_dir() for part in ('frontend', 'backend')):
                raise ValueError('frontend 또는 backend 폴더가 있는 프로젝트를 선택하세요.')
            for record in self.records:
                other = Path(record['root'])
                if root.is_relative_to(other) or other.is_relative_to(root):
                    raise ValueError('이미 등록된 프로젝트와 경로가 겹칩니다.')
            db = body.get('test_db_url', '')
            if not isinstance(db, str) or (db and (not db.startswith('jdbc:postgresql://') or len(db) > 500)):
                raise ValueError('PostgreSQL 테스트 DB URL을 입력하세요.')
            if db and any(r.get('test_db_url') == db for r in self.records):
                raise ValueError('프로젝트별로 별도 테스트 DB를 지정하세요.')
            record = {'id': hashlib.sha256(str(root).encode()).hexdigest()[:16], 'name': root.name, 'root': str(root), 'preview_url': '', 'model_url': local_url(body.get('model_url') or 'http://127.0.0.1:8099/v1'), 'default_model': '', 'test_db_url': db}
            self.records.append(record)
            self.persist()
            return record

    def create(self, body):
        """A new project of a chosen kind, with the base framework and a working set of its own."""
        import projects
        return projects.create(self, body)

    def rename(self, body):
        import projects
        return projects.rename(self, body.get('id'), body.get('title'), body.get('slug'))

    def remove(self, body):
        import projects
        return projects.remove(self, body.get('id'), body.get('confirm'))

    def pick(self):
        from folder_dialog import choose_folder
        return choose_folder()

    def close(self):
        self.previews.close()
