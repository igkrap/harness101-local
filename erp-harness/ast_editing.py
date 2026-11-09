import hashlib
import json
import pathlib
import subprocess
import uuid
from collections import deque
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

@dataclass(frozen=True)
class NodeInfo:
    id: str
    kind: str
    label: str
    source: str
    handler_scope: bool = False
    handler_statement_scope: bool = False

@dataclass(frozen=True)
class Snapshot:
    id: str
    path: pathlib.Path
    hash: str
    nodes: Dict[str, NodeInfo]
    ranges: Dict[str, tuple[int, int]]  # node_id -> (start_byte, end_byte)
    raw_bytes: bytes
    allow_nested_handlers: bool = False

class Editor:
    def __init__(self, service, allow_nested_handlers=False):
        self.service = service
        self.root = service.root
        self.allow_nested_handlers = allow_nested_handlers is True
        self._snapshots: Dict[str, Snapshot] = {}
        self._history: deque[str] = deque(maxlen=8)
        self._diagnostics: Dict[str, List[Any]] = {}

    def _validate(self, path):
        return self.service._validate(path)

    

    def snapshot(self, path):
        p = self.service._validate(path)
        raw = p.read_bytes()
        if len(raw) > 1048576:
            raise ValueError("File too large")
        h = hashlib.sha256(raw).hexdigest()
        for sid in reversed(self._history):
            s = self._snapshots[sid]
            if s.path == p and s.hash == h and s.allow_nested_handlers == self.allow_nested_handlers:
                return {
                    'snapshot_id': sid,
                    'path': path,
                    'source_hash': s.hash,
                    'diagnostics': self._diagnostics.get(sid, []),
                    'nodes': [self._node_data(n) for n in s.nodes.values()],
                    'cached': True
                }
        text = raw.decode('utf8')
        res = subprocess.run(
            [self.service.node, str(pathlib.Path(__file__).with_name('ast_edit_ranges.cjs'))],
            input=json.dumps({'path': str(p), 'source': text, 'allow_nested_handlers': self.allow_nested_handlers}),
            text=True, capture_output=True, timeout=10
        )
        if res.returncode != 0:
            raise RuntimeError("AST extraction failed")
        data = res.stdout.strip()
        if not data:
            raise RuntimeError("Empty AST response")
        data = json.loads(data)
        if data.get('error'):
            raise RuntimeError(f"AST error: {data.get('error')}")

        nodes = {}
        ranges = {}
        seen_ids = set()
        forbidden_kinds = {'SourceFile', 'FunctionDeclaration', 'ClassDeclaration', 'Block'}
    
        for n in data.get('nodes', []):
            nid = n['id']
            kind = n['kind']
            start, end = n['start'], n['end']
            label = n.get('label', '')
        
            handler_scope = kind == 'FunctionDeclaration' and self.allow_nested_handlers and n.get('handler_scope') is True
            if nid in seen_ids or (kind in forbidden_kinds and not handler_scope):
                continue
            if not (isinstance(start, int) and isinstance(end, int)):
                continue
            if not (0 <= start <= end <= len(raw)):
                continue
            if raw[start:end].decode('utf8') != n.get('source', ''):
                continue
            if start == 0 and end == len(raw):
                continue
            
            seen_ids.add(nid)
            statement_scope = self.allow_nested_handlers and n.get('handler_statement_scope') is True
            nodes[nid] = NodeInfo(nid, kind, label, n.get('source', ''), handler_scope, statement_scope)
            ranges[nid] = (start, end)

        sid = uuid.uuid4().hex
        snap = Snapshot(sid, p, h, nodes, ranges, raw, self.allow_nested_handlers)
    
        if len(self._history) >= 8:
            oldest_id = self._history.popleft()
            self._snapshots.pop(oldest_id, None)
            self._diagnostics.pop(oldest_id, None)
        
        self._snapshots[sid] = snap
        self._history.append(sid)
        self._diagnostics[sid] = data.get('diagnostics', [])
    
        return {
            'snapshot_id': sid,
            'path': path,
            'source_hash': snap.hash,
            'diagnostics': self._diagnostics[sid],
            'nodes': [self._node_data(n) for n in nodes.values()],
            'cached': False
        }

    @staticmethod
    def _node_data(node):
        return {'id': node.id, 'kind': node.kind, 'label': node.label, 'source': node.source,
                **({'handler_scope': True} if node.handler_scope else {}),
                **({'handler_statement_scope': True} if node.handler_statement_scope else {})}

    def apply(self, path, snapshot_id, edits):
        import hashlib
        p = self.service._validate(path)
        if not snapshot_id:
            for sid in reversed(self._history):
                if self._snapshots[sid].path == p:
                    snapshot_id = sid
                    break
        snap = self._snapshots.get(snapshot_id)
        if not snap or snap.path != p:
            latest = next((s.id for s in (self._snapshots[sid] for sid in reversed(self._history)) if s.path == p), "None")
            raise ValueError(f"Snapshot mismatch/missing for {path} (id: {snapshot_id}, latest: {latest}). Call inspect_code with action edit_ranges/path to obtain node IDs; omit snapshot_id to use latest; never invent IDs; no source changes applied.")
        if snap.allow_nested_handlers != self.allow_nested_handlers:
            raise ValueError('Snapshot policy changed; request a current snapshot')
    
        raw = p.read_bytes()
        if hashlib.sha256(raw).hexdigest() != snap.hash:
            raise ValueError("stale snapshot")
    
        if len(raw) > 1048576:
            raise ValueError("File too large")
        if not isinstance(edits,list) or not (1 <= len(edits) <= 16):
            raise ValueError("Invalid edit count")

        ops = []
        seen_starts = set()
        for edit in edits:
            if not isinstance(edit,dict) or set(edit)!={'node_id','code'}: raise ValueError('Invalid edit keys')
            nid, code = edit.get("node_id"), edit.get("code")
            if not isinstance(nid, str) or not isinstance(code, str) or len(code) > 12000:
                raise ValueError("Invalid edit format")
            if nid not in snap.nodes:
                raise ValueError(f"Node {nid} not in snapshot")
        
            start, end = snap.ranges[nid]
            if start in seen_starts:
                raise ValueError("Duplicate start position")
        
            # A parent replacement may already contain an exact child
            # replacement. In that case the child operation is redundant.
            # Preserve one atomic parent edit, without guessing how to merge
            # distinct or partially overlapping replacements.
            redundant = False
            to_drop = []
            for s_start, s_end, previous_id, previous_code in ops:
                if start == s_start or (start < s_end and s_start < end) or (start == end and s_start <= start <= s_end) or (s_start == s_end and start <= s_start <= end):
                    if (s_start < start < end < s_end and code.strip() and
                            previous_code.count(code) == 1):
                        redundant = True
                        break
                    if (start < s_start < s_end < end and previous_code.strip() and
                            code.count(previous_code) == 1):
                        to_drop.append((s_start, s_end, previous_id, previous_code))
                        continue
                    if s_start <= start and end <= s_end:
                        detail = f'{previous_id} contains {nid}; remove the {nid} edit and include its intended change in {previous_id} code'
                    elif start <= s_start and s_end <= end:
                        detail = f'{nid} contains {previous_id}; remove the {previous_id} edit and include its intended change in {nid} code'
                    else:
                        detail = 'submit separate nonoverlapping node replacements'
                    raise ValueError(f'Overlapping edits: {previous_id} and {nid}; {detail}')
            if redundant:
                continue
            for previous in to_drop:
                ops.remove(previous)
                seen_starts.remove(previous[0])
        
            # Reject zero-length insertion at/inside boundaries of existing replacements
            # (Handled by the overlap check and the start uniqueness)
        
            seen_starts.add(start)
            ops.append((start, end, nid, code))

        from ast_feedback import validate_fragments
        ops = validate_fragments(self,path,snapshot_id,snap,ops)

        # Sort descending by start to splice without invalidating indices
        ops.sort(key=lambda x: x[0], reverse=True)
    
        candidate_bytes = bytearray(raw)
        edited_ids = []
        for start, end, nid, code in ops:
            edited_ids.append(nid)
            # Requirement: Reject empty/whitespace insertion
            if start == end and not code.strip():
                raise ValueError("Empty or whitespace insertion")
        
            # Requirement: wrap insertion ONLY with '\n'+code+'\n' if it's an insertion
            # But the prompt says "replacement exactcode". 
            # Interpreting: if start==end, it's an insertion. If start!=end, it's a replacement.
            # However, the prompt says: "wrap insertion ONLY with '\n'+code+'\n'; replacement exactcode."
            if start == end:
                replacement = f"\n{code}\n".encode("utf-8")
            else:
                replacement = code.encode("utf-8")
            
            candidate_bytes[start:end] = replacement

        if len(candidate_bytes)>1048576: raise ValueError('Candidate too large')
        candidate = candidate_bytes.decode("utf-8")
        if candidate == raw.decode("utf-8"):
            raise ValueError("No-op edit")

        actual = self.service._ast(path, candidate)
        if "error" in actual or actual.get("diagnostics"):
            raise ValueError(f"AST Error: {actual.get('diagnostics')}")

        return {
            'path': path,
            'old_text': raw.decode('utf-8'),
            'new_text': candidate,
            'edited_nodes': sorted(edited_ids),
            'source_hash': snap.hash
        }

def editor(h):
    focused = getattr(getattr(h, 'args', None), 'context_profile', 'legacy') == 'focused'
    if not hasattr(h, '_ast_editor') or h._ast_editor.allow_nested_handlers != focused:
        from cycle_context import cycle_context
        h._ast_editor = Editor(cycle_context.service(h), allow_nested_handlers=focused)
    return h._ast_editor

TOOL = {
    "type": "function",
    "function": {
        "name": "apply_ast_edits",
        "description": "Apply only AST node IDs from inspect_code action edit_ranges; source hash is verified, no raw offsets or old_text; edits checked before write",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string"
                },
                "snapshot_id": {
                    "type": "string",
                    "description": "Optional: omit to use harness latest provided snapshot for this file. Never invent an ID."
                },
                "edits": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 16,
                    "items": {
                        "type": "object",
                        "properties": {
                            "node_id": {
                                "type": "string"
                            },
                            "code": {
                                "type": "string"
                            }
                        },
                        "required": [
                            "node_id",
                            "code"
                        ],
                        "additionalProperties": False
                    }
                }
            },
            "required": [
                "path",
                "edits"
            ],
            "additionalProperties": False
        }
    }
}
