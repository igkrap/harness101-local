"""Immutable before/accepted-after snapshots for a single execution."""
import difflib
import hashlib
import json
from pathlib import Path


class Changes:
    def __init__(self, project, directory):
        self.root = Path(project).resolve()
        self.folder = Path(directory) / 'changes'
        self.folder.mkdir(exist_ok=True)
        self.before, self.files, self.warnings = {}, {}, []
        self.accepted = False
        self.save()

    def source(self, rel):
        p = (self.root / rel).resolve()
        if not p.is_relative_to(self.root) or p.relative_to(self.root).parts[:1] not in (('frontend',), ('backend',)):
            raise ValueError('앱 소스 경로가 아닙니다.')
        if p.is_file():
            if p.stat().st_size > 200000:
                raise ValueError('200KB를 넘는 파일은 diff 기록에서 제외합니다.')
            return {'exists':True, 'content':p.read_bytes().decode('utf-8')}
        return {'exists':False, 'content':''}

    def capture(self, rel):
        if rel in self.before: return
        try:
            if len(self.before) >= 100: raise ValueError('실행별 diff는 최대 100개 파일입니다.')
            snapshot = self.source(rel)
            if sum(len(v['content'].encode()) for v in self.before.values()) + len(snapshot['content'].encode()) > 2000000:
                raise ValueError('실행별 diff 원본 저장 한도를 넘었습니다.')
            self.before[rel] = snapshot
        except (OSError, ValueError, UnicodeError) as error:
            self.warnings.append(str(error))
            self.save()

    def accept(self, paths):
        self.accepted = True
        for rel in paths:
            if rel not in self.before: continue
            try:
                before, after = self.before[rel], self.source(rel)
                key = hashlib.sha256(rel.encode()).hexdigest()
                if before == after:
                    self.files.pop(rel, None)
                    continue
                added = removed = 0
                for tag, i, j, k, l in difflib.SequenceMatcher(None, before['content'].splitlines(), after['content'].splitlines()).get_opcodes():
                    if tag in ('replace','delete'): removed += j-i
                    if tag in ('replace','insert'): added += l-k
                data = {'path':rel, 'before':before['content'], 'after':after['content'], 'before_exists':before['exists'], 'after_exists':after['exists']}
                target = self.folder / (key+'.json')
                temporary = target.with_suffix('.tmp')
                temporary.write_text(json.dumps(data,ensure_ascii=False)); temporary.replace(target)
                self.files[rel] = {'path':rel, 'key':key, 'revision':hashlib.sha256(json.dumps(data,ensure_ascii=False).encode()).hexdigest(), 'status':'added' if not before['exists'] else 'deleted' if not after['exists'] else 'modified', 'added':added, 'removed':removed}
            except (OSError,ValueError,UnicodeError) as error:
                self.warnings.append(str(error))
        self.save()

    def note_written(self, rel):
        """Remember what this run last wrote, so a later restore never clobbers someone else's edit."""
        if rel not in self.before:
            return
        try:
            snapshot = self.source(rel)
            self.written = getattr(self, 'written', {})
            digest = hashlib.sha256(json.dumps(snapshot, sort_keys=True).encode()).hexdigest()
            self.written[rel] = digest
            # Every version this run wrote: the harness may roll a failed patch back to an earlier one.
            self.__dict__.setdefault('written_all', {}).setdefault(rel, set()).add(digest)
        except (OSError, ValueError, UnicodeError) as error:
            self.warnings.append(str(error))

    def restore_unverified(self):
        """Put back files this run changed when the run did not succeed. Returns restored paths."""
        restored, written = [], getattr(self, 'written', {})
        for rel, before in self.before.items():
            try:
                current = self.source(rel)
                if current == before:
                    continue
                digest = hashlib.sha256(json.dumps(current, sort_keys=True).encode()).hexdigest()
                if digest not in getattr(self, 'written_all', {}).get(rel, {written.get(rel)}):
                    self.warnings.append(f'{rel}: changed outside this run; not restored')
                    continue
                path = (self.root / rel)
                if before['exists']:
                    path.write_text(before['content'], encoding='utf-8')
                elif path.exists():
                    path.unlink()
                restored.append(rel)
            except (OSError, ValueError, UnicodeError) as error:
                self.warnings.append(f'{rel}: restore failed: {error}')
        self.save()
        return restored

    def save(self):
        target = self.folder/'index.json'
        temporary = target.with_suffix('.tmp')
        temporary.write_text(json.dumps({'recorded':True,'files':list(self.files.values()),'warnings':list(dict.fromkeys(self.warnings))[:10]},ensure_ascii=False))
        temporary.replace(target)


def current_state(project, record):
    """Whether a recorded change is still what the workspace contains: applied, reverted or changed."""
    try:
        target = Path(project) / record['path']
        current = target.read_text(encoding='utf-8') if target.is_file() else None
    except (OSError, UnicodeError):
        return 'unknown'
    after = record['after'] if record.get('after_exists', True) else None
    before = record['before'] if record.get('before_exists', True) else None
    return 'applied' if current == after else 'reverted' if current == before else 'changed'


def read_changes(directory, path=None, project=None):
    folder = Path(directory)/'changes'
    index = folder/'index.json'
    if not index.exists(): return {'recorded':False, 'files':[], 'warnings':[]}
    data = json.loads(index.read_text())
    if path is None:
        files = []
        for f in data['files']:
            item = {k:v for k,v in f.items() if k!='key'}
            if project is not None:
                try:
                    item['current'] = current_state(project, json.loads((folder/(f['key']+'.json')).read_text()))
                except (OSError, ValueError, KeyError):
                    item['current'] = 'unknown'
            files.append(item)
        return {**data, 'files':files}
    match = next((f for f in data['files'] if f['path']==path), None)
    if not match: raise ValueError('이 실행의 변경 파일이 아닙니다.')
    return json.loads((folder/(match['key']+'.json')).read_text())
