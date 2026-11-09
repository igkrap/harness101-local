"""Keep failed frontend edits in a private, freshly indexed source buffer."""
import hashlib
import json
from pathlib import Path
import tempfile
import subprocess
from types import SimpleNamespace
import uuid


def digest(source):
    return hashlib.sha256(source.encode('utf-8')).hexdigest()


class CandidateStore:
    def __init__(self, directory, project, goal):
        self.project = Path(project).resolve()
        self.goal_hash = digest(goal)
        self.file = Path(directory) / (digest(str(self.project)) + '.json')

    def load(self):
        if not self.file.is_file():
            return None
        try:
            data = json.loads(self.file.read_text())
            if not isinstance(data, dict) or data.get('goal_hash') != self.goal_hash:
                return None
            return data
        except (ValueError, OSError):
            return None

    def save(self, data):
        self.file.parent.mkdir(parents=True, exist_ok=True)
        payload = {**data, 'goal_hash': self.goal_hash}
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=self.file.parent, delete=False) as out:
            json.dump(payload, out, ensure_ascii=False)
            temporary = Path(out.name)
        temporary.replace(self.file)

    def accept(self, paths):
        data = self.load()
        if not data or data.get('path') not in paths:
            return
        target = self.project / data['path']
        if target.is_file() and digest(target.read_bytes().decode()) == digest(data['candidate_source']):
            self.file.unlink(missing_ok=True)


class CandidateBuffer:
    def __init__(self, workspace, source_editor, path, source, origin=None):
        from ast_editing import Editor
        self.workspace, self.source_editor, self.path = workspace, source_editor, path
        target = workspace.safe_path(path)
        if workspace.is_protected(target) or not path.startswith('frontend/src/') or not path.endswith(('.tsx', '.ts', '.jsx', '.js')):
            raise ValueError('Candidate buffers are limited to editable frontend source')
        self.base_source = target.read_bytes().decode('utf-8')
        self.base_hash = digest(self.base_source)
        self.origin = origin
        self.temp = tempfile.TemporaryDirectory(prefix='workshop-candidate-')
        self.root = Path(self.temp.name).resolve()
        self.file = self.root / path
        self.file.parent.mkdir(parents=True, exist_ok=True)

        def validate(rel):
            item = (self.root / rel).resolve()
            item.relative_to(self.root)
            if not item.is_file():
                raise ValueError('Unknown candidate file')
            return item

        service = SimpleNamespace(root=self.root, node=source_editor.service.node, _validate=validate,
                                  _ast=lambda rel, text: source_editor.service._ast(path, text))
        self.editor = Editor(service, allow_nested_handlers=getattr(source_editor, 'allow_nested_handlers', False))
        self.pending = None
        try:
            self.set_source(source)
        except BaseException:
            self.close()
            raise

    def close(self):
        self.temp.cleanup()

    def check_base(self):
        target = self.workspace.safe_path(self.path)
        if target.is_symlink() or target.read_bytes().decode('utf-8') != self.base_source:
            raise ValueError('Published source changed while candidate was being repaired')

    def set_source(self, source):
        from edit_limits import MAX_SOURCE_CHARS
        if not isinstance(source, str) or not source or len(source) > MAX_SOURCE_CHARS:
            raise ValueError('Candidate source exceeds the editable source limit')
        ast = self.source_editor.service._ast(self.path, source)
        if ast.get('error') or ast.get('diagnostics'):
            raise ValueError('Candidate source must parse before indexing')
        self.file.write_bytes(source.encode('utf-8'))
        self.source = source

    def snapshot(self):
        return self.editor.snapshot(self.path)

    def prepare(self, snapshot_id, edits):
        self.check_base()
        snapshot = self.editor._snapshots.get(snapshot_id)
        if snapshot is None:
            raise ValueError('Unknown current candidate snapshot')
        fragments = {'source': self.source, 'edits': edits, 'nodes': [
            {'id': nid, 'kind': node.kind, 'source': node.source, 'range': snapshot.ranges[nid],
             'handler_statement_scope': getattr(node, 'handler_statement_scope', False)}
            for nid, node in snapshot.nodes.items()]}
        check = subprocess.run([self.editor.service.node, str(Path(__file__).with_name('strict_ast_fragments.cjs'))],
                               input=json.dumps(fragments), text=True, capture_output=True, timeout=10)
        outcome = json.loads(check.stdout)
        if not outcome['ok']:
            raise ValueError(outcome['error'])
        edits = outcome['edits']
        if not edits:
            raise ValueError('No actual source changes after removing repeated existing imports/declarations. The current compiler or behavior error remains. Change the faulty dependency or its uses instead of reprinting existing code.')
        result = self.editor.apply(self.path, snapshot_id, edits)
        self.set_source(result['new_text'])
        self.prepare_publication(edits)

    def prepare_publication(self, edits=None):
        self.check_base()
        if self.source == self.base_source:
            raise ValueError('Candidate has no source changes')
        self.pending = {'token': uuid.uuid4().hex, 'edits': edits or []}

    def record(self, feedback):
        return {'path': self.path, 'base_source': self.base_source, 'base_hash': self.base_hash,
                'candidate_source': self.source, 'feedback': feedback, 'origin': self.origin}

    def bridge(self):
        buffer = self
        class SourceBridge:
            def __getattr__(self, name):
                return getattr(buffer.source_editor, name)

            def apply(self, path, snapshot_id, edits):
                buffer.check_base()
                if path != buffer.path or not buffer.pending or snapshot_id != buffer.pending['token'] or edits != buffer.pending['edits']:
                    raise ValueError('Candidate publication token or edits mismatch')
                return {'path': path, 'old_text': buffer.base_source, 'new_text': buffer.source,
                        'source_hash': buffer.base_hash, 'edited_nodes': [e['node_id'] for e in edits]}
        return SourceBridge()
