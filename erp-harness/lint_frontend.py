import json
import shutil
from pathlib import Path

def run_lint(checker):
    try:
        root = Path(checker.workspace.root)
        config = Path(__file__).with_name('eslint.config.cjs')
        src = root / 'frontend' / 'src'
        
        node = shutil.which('node')
        if not node:
            node_path = Path('~/.local/share/mlx-server/code-intelligence/node_modules/eslint/bin/eslint.js').expanduser()
            if node_path.exists():
                node = 'node' # Fallback logic assumes node is needed to run the js
            else:
                return {'success': False, 'exit_code': 1, 'stdout': '', 'stderr': 'Node not found', 'lint': {}}

        eslint_bin = Path('~/.local/share/mlx-server/code-intelligence/node_modules/eslint/bin/eslint.js').expanduser()
        cmd = [node, str(eslint_bin), '--config', str(config), '--format', 'json', str(src.absolute())]
        
        res = checker._exec(cmd, cwd=str(root / 'frontend'))
        
        if not res['success'] and not res['stdout']:
            return {'success': False, 'exit_code': res['exit_code'], 'stdout': '', 'stderr': res['stderr'], 'lint': {}}

        try:
            data = json.loads(res['stdout'])
        except json.JSONDecodeError:
            return {'success': False, 'exit_code': res['exit_code'], 'stdout': res['stdout'], 'stderr': res['stderr'], 'lint': {}}

        if not data:
            return {'success': False, 'exit_code': res['exit_code'], 'stdout': '', 'stderr': 'ESLint inspected no files', 'lint': {}}

        n_files = len(data)
        errors = sum(f.get('errorCount', 0) for f in data)
        warnings = sum(f.get('warningCount', 0) for f in data)
        
        msgs = []
        for f in data:
            for m in f.get('messages', []):
                rel = Path(f.get('filePath', '')).relative_to(root)
                lvl = 'error' if m.get('severity') == 2 else 'warning'
                msgs.append(f"{rel}:{m.get('line')}:{m.get('column')} {lvl} {m.get('ruleId')} {m.get('message')}")

        out_str = f"ESLint: {n_files} files, {errors} errors, {warnings} warnings\n" + "\n".join(msgs[:40])
        
        return {
            'success': res['success'] and errors == 0,
            'exit_code': res['exit_code'] if errors > 0 or not res['success'] else 0,
            'stdout': out_str,
            'stderr': res['stderr'],
            'lint': {'files': n_files, 'errors': errors, 'warnings': warnings}
        }
    except Exception as e:
        return {'success': False, 'exit_code': 1, 'stdout': '', 'stderr': str(e), 'lint': {}}
