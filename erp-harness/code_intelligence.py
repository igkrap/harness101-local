import json
import hashlib
import subprocess
import shutil
import pathlib
from typing import Any, Dict, Optional, Union

TOOL = {
    'type': 'function',
    'function': {
        'name': 'inspect_code',
        'description': 'Analyze code structure, symbols, definitions, or diagnostics.',
        'parameters': {
            'type': 'object',
            'properties': {
                'path': {'type': 'string'},
                'action': {'type': 'string', 'enum': ['outline', 'symbol', 'definition', 'references', 'hover', 'diagnostics', 'edit_ranges']},
                'symbol': {'type': 'string'},
                'line': {'type': 'integer'},
                'column': {'type': 'integer'}
            },
            'required': ['path', 'action']
        }
    }
}

class Service:
    def __init__(self, workspace):
        self.root = workspace.root.resolve()
        self.ast_helper = pathlib.Path(__file__).with_name('ast_outline.cjs')
        self.node = shutil.which('node') or str(pathlib.Path.home() / '.nvm/versions/node/v22.15.0/bin/node')
        self.client = None
        self.read_hashes = {}
        self.duplicate_reads = 0
        self.ast_cache = {}
        self.recent_queries = []
        self.query_history = []

    def _validate(self, rel):
        if not isinstance(rel, str) or not rel:
            raise ValueError("Path must be a non-empty string")
        if rel.startswith('/') or '..' in rel.split(pathlib.os.sep):
            raise ValueError("Relative path must not be absolute or contain '..'")
        if not rel.endswith(('.ts', '.tsx', '.js', '.jsx')):
            raise ValueError("Invalid file extension")
    
        parts = rel.split(pathlib.os.sep)
        if len(parts) < 3 or parts[0] != 'frontend' or parts[1] != 'src':
            raise ValueError("Path must start with 'frontend/src'")
    
        target_path = (self.root / rel).resolve()
    
        # Check symlinks on ancestors using unresolved logic
        current = self.root
        for part in parts:
            current = (current / part)
            # We check if the path exists and is a symlink before resolving
            if current.exists() and current.is_symlink():
                raise ValueError("Symlink detected in path hierarchy")
            
        if not target_path.exists() or not target_path.is_file():
            raise ValueError("Target file does not exist")
        if target_path.stat().st_size > 1024 * 1024:
            raise ValueError("File exceeds 1MiB limit")
        
        return target_path

    def _ast(self, rel: str, text: str, symbol: Optional[str] = None) -> Dict:
        h = hashlib.sha256(text.encode()).hexdigest()
        key = f"{rel}:{h}:{symbol or ''}"
        if key in self.ast_cache: return self.ast_cache[key]
        try:
            res = subprocess.run([self.node, str(self.ast_helper)], input=json.dumps({
                'path': rel, 'source': text, 'symbol': symbol
            }), text=True, capture_output=True, timeout=10, check=True)
            data = json.loads(res.stdout)
            self.ast_cache[key] = data
            if len(self.ast_cache) > 64: self.ast_cache.pop(next(iter(self.ast_cache)))
            return data
        except Exception as e:
            return {'error': str(e)}

    def run(self, args):
        try:
            import hashlib, json
            path = self._validate(args['path'])
            with open(path, 'r', encoding='utf-8') as f:
                text = f.read()
            h = hashlib.sha256(text.encode()).hexdigest()[:64]
            identity = (path, h, args['action'], args.get('symbol'), args.get('line'), args.get('column'))
            if identity not in self.query_history:
                self.duplicate_reads = 0
                self.query_history.append(identity)
            sid = str(identity)
            self.recent_queries = (self.recent_queries + [sid])[-8:]
            if args['action'] == 'outline':
                return self._ast(args['path'], text)
            if args['action'] == 'symbol':
                if not args.get('symbol'): raise ValueError("Empty symbol")
                return self._ast(args['path'], text, args.get('symbol'))
            if args['action'] in ('definition', 'references', 'hover', 'diagnostics'):
                if self.client is None:
                    from lsp_client import Client
                    self.client = Client(self.root)
                res = self.client.query(path, args['action'], args.get('line', 1), args.get('column', 1))
                return {'engine': 'typescript-lsp', 'path': args['path'], 'action': args['action'], 'result': res}
            raise ValueError(f"Unknown action: {args['action']}")
        except Exception as e:
            return {'error': str(e)}

    def read(self, rel: str) -> Dict[str, Any]:
        target = self._validate(rel)
        text = target.read_bytes().decode('utf-8')
        h = hashlib.sha256(text.encode()).hexdigest()
        
        if self.read_hashes.get(rel) == h:
            self.duplicate_reads += 1
            return {'unchanged': True, 'sha256': h, 'content': 'Source unchanged and already supplied. Use inspect_code outline/symbol or make a small exact edit; do not reread unchanged file.\n' + json.dumps(self._ast(rel, text))}
        
        # Check if any known path changed to reset duplicates
        for p, old_h in self.read_hashes.items():
            try:
                if hashlib.sha256((self.root/p).read_text().encode()).hexdigest() != old_h:
                    self.duplicate_reads = 0
                    break
            except: pass

        self.read_hashes[rel] = h
        self.duplicate_reads = 0
        return {'content': text, 'sha256': h}

    def allow_reads(self):
        try:
            for rel, old_hash in self.read_hashes.items():
                target = self.root / rel
                if target.exists():
                    new_hash = hashlib.sha256(target.read_bytes()).hexdigest()
                    if new_hash != old_hash:
                        self.duplicate_reads = 0
            return self.duplicate_reads < 3
        except OSError:
            return self.duplicate_reads < 3

    def retain_reads(self, paths):
        """An old hash alone cannot replace a source evicted from context."""
        retained = {}
        for path, expected in self.read_hashes.items():
            if path not in paths:
                continue
            try:
                if hashlib.sha256(self._validate(path).read_bytes()).hexdigest() == expected:
                    retained[path] = expected
            except (OSError, ValueError):
                pass
        if retained != self.read_hashes:
            self.duplicate_reads = 0
        self.read_hashes = retained

    def context(self, read_paths=None):
        screens = []
        search_dir = self.root / 'frontend' / 'src' / 'screens'
        if search_dir.exists():
            paths = sorted(search_dir.glob('*.tsx'))[:12]
            for p in paths:
                rel = str(p.relative_to(self.root))
                try:
                    self._validate(rel)
                    content = p.read_text(encoding='utf-8')
                    ast = self._ast(rel, content)
                    # Extracting metadata from AST structure
                    screens.append({
                        'path': rel,
                        'symbols': [s.get('name') for s in ast.get('symbols', [])],
                        'jsx_tags': ast.get('jsx_tags', []),
                        'diagnostics': ast.get('diagnostics', []),
                        'error': None
                    })
                except Exception as e:
                    screens.append({
                        'path': rel,
                        'error': str(e)
                    })
                
        return json.dumps({
            'screen_structure': screens,
            'already_read': {path: digest for path, digest in self.read_hashes.items()
                             if read_paths is None or path in read_paths},
            'recent_queries': self.recent_queries
        }, ensure_ascii=False)[:6000]

    def close(self):
        if self.client: self.client.close()

