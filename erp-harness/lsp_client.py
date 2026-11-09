import os
import sys
import threading
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path.home() / '.local/share/mlx-server/code-intelligence/rpc-python'))
from pylspclient import JsonRpcEndpoint, LspEndpoint

class Client:
    def __init__(self, root: str):
        self.root = Path(root).resolve()
        self.frontend = self.root / "frontend"
        self.cwd = self.frontend if self.frontend.exists() else self.root
        
        node = shutil.which("node") or os.path.expanduser("~/.nvm/versions/node/v22.15.0/bin/node")
        base_node = Path.home() / '.local/share/mlx-server/code-intelligence/node_modules'
        ts_server = base_node / 'typescript/lib/tsserver.js'
        cli = base_node / 'typescript-language-server/lib/cli.mjs'
        
        self.proc = subprocess.Popen(
            [node, str(cli), '--stdio'],
            cwd=str(self.cwd), stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
        )
        
        self.rpc = JsonRpcEndpoint(self.proc.stdin, self.proc.stdout)
        self.endpoint = LspEndpoint(self.rpc, method_callbacks={
            'workspace/configuration': lambda p: [None] * len(p.get('items', [])),
        }, notify_callbacks={
            '$/typescriptVersion': lambda p: None,
            'window/logMessage': lambda p: None,
            'window/showMessage': lambda p: None,
            'textDocument/publishDiagnostics': self._diagnostics
        }, timeout=20)
        self.endpoint.daemon = True
        self.endpoint.start()
        
        self.opened: Dict[str, str] = {}
        self.versions: Dict[str, int] = {}
        self.diagnostics: Dict[str, List[Dict]] = {}
        self.cond = threading.Condition()
        self.closed = False
        
        try:
            self.endpoint.call_method('initialize', processId=os.getpid(), rootUri=self.cwd.as_uri(),
                capabilities={'textDocument': {'publishDiagnostics': {'versionSupport': True}}},
                initializationOptions={'tsserver': {'path': str(ts_server), 'useSyntaxServer': 'never'}})
            self.endpoint.send_notification('initialized')
        except Exception:
            self.close()
            raise

    def _diagnostics(self, params: Dict):
        with self.cond:
            uri = params.get('uri')
            if uri:
                self.diagnostics[uri] = params.get('diagnostics', [])
                self.cond.notify_all()

    def open(self, path: str) -> str:
        p = Path(path).resolve()
        uri = p.as_uri()
        text = p.read_text(encoding='utf-8')
        
        with self.cond:
            if self.opened.get(uri) == text:
                return uri
            
            new_ver = self.versions.get(uri, 0) + 1
            self.versions[uri] = new_ver
            self.opened[uri] = text
            self.diagnostics.pop(uri, None)
            
            ext = p.suffix.lower()
            lang = {'.tsx': 'typescriptreact', '.ts': 'typescript', '.jsx': 'javascriptreact', '.js': 'javascript'}.get(ext, 'javascript')
            
            if new_ver == 1:
                self.endpoint.send_notification('textDocument/didOpen', **{'textDocument': {'uri': uri, 'languageId': lang, 'version': new_ver, 'text': text}})
            else:
                self.endpoint.send_notification('textDocument/didChange', **{'textDocument': {'uri': uri, 'version': new_ver}, 'contentChanges': [{'text': text}]})
            
            self.endpoint.send_notification('textDocument/didSave', **{'textDocument': {'uri': uri}})
            return uri

    def query(self, path, action, line=1, column=1, args=None):
        if not (isinstance(line, int) and line > 0 and isinstance(column, int) and column > 0):
            raise ValueError("Coordinates must be positive integers")
        if isinstance(line, bool) or isinstance(column, bool):
            raise ValueError("Coordinates cannot be boolean")

        uri = self.open(path)
    
        if action == 'diagnostics':
            self.endpoint.call_method('textDocument/documentSymbol', textDocument={'uri': uri})
            with self.cond:
                self.cond.wait_for(lambda: uri in self.diagnostics, timeout=4)
            return {'ready': uri in self.diagnostics, 'diagnostics': self.diagnostics.get(uri, [])}
    
        if action == 'symbols':
            return self.endpoint.call_method('textDocument/documentSymbol', textDocument={'uri': uri})
    
        if action in ('definition', 'references', 'hover'):
            params = {
                'textDocument': {'uri': uri},
                'position': {'line': line - 1, 'character': column - 1}
            }
            if action == 'references':
                params['context'] = {'includeDeclaration': True}
            return self.endpoint.call_method(f'textDocument/{action}', **params)
    
        raise ValueError(f"Unknown action: {action}")

    def close(self):
        if self.closed:
            return
        if self.proc.poll() is None:
            try:
                self.endpoint._timeout = 1
                self.endpoint.call_method('shutdown')
            except Exception:
                pass
            try:
                self.endpoint.send_notification('exit')
            except Exception:
                pass
            try:
                self.proc.terminate()
                self.proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=2)
            except Exception:
                pass
        self.closed = True
        self.endpoint.stop()
        for stream in [self.proc.stdin, self.proc.stdout]:
            if stream:
                try:
                    stream.close()
                except OSError:
                    pass
        import threading
        if not threading.current_thread() is threading.main_thread():
            self.endpoint.join(timeout=1)

import shutil
