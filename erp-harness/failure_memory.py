from __future__ import annotations
import json
import hashlib
import difflib
import re
from pathlib import Path

class FailureMemory:
    def __init__(self, root: str):
        self.root = Path(root).resolve()
        self.path = self.root / 'harness/state/failures.json'
        self.entries = self._load()

    def _load(self) -> list:
        if not self.path.exists():
            return []
        try:
            with open(self.path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return []

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.path.with_suffix('.tmp')
        with open(temp_path, 'w', encoding='utf-8') as f:
            json.dump(self.entries[-24:], f, indent=2)
        temp_path.replace(self.path)

    def _hash(self, data: bytes | None) -> str:
        if data is None:
            return hashlib.sha256(b"ABSENT_SENTINEL_UNIQUE").hexdigest()
        return hashlib.sha256(data).hexdigest()

    def _config(self) -> str:
        h = hashlib.sha256()
        for p in ['backend/pom.xml', 'frontend/package.json']:
            target = self.root / p
            h.update(target.read_bytes() if target.exists() else b"EMPTY")
        for f in sorted(['runtime_policy.py', 'java_assertion_policy.py', 'edit_limits.py', 'batch_edits.py', 'failure_memory.py']):
            target = Path(__file__).parent / f
            h.update(f.encode())
            h.update(target.read_bytes() if target.exists() else b"ABSENT_SENTINEL_UNIQUE")
        return h.hexdigest()

    def _rel(self, path: str) -> str:
        p = (self.root / path).resolve()
        if not p.is_relative_to(self.root):
            raise ValueError(f"Path {path} escapes root")
        return str(p.relative_to(self.root))

    def _dependencies(self, target: str, overrides: dict | None = None) -> str | None:
        """Failure facts only apply to the same surrounding source/resources.

        The target itself is excluded: record() sees the rejected candidate,
        whereas guard()/context() see its restored original or absent file.
        Build outputs, failure history and evidence are deliberately excluded.
        """
        proposed = {}
        if overrides is not None:
            if not isinstance(overrides, dict):
                raise ValueError('Dependency overrides must be a path-to-bytes mapping')
            for relative, content in overrides.items():
                if (not isinstance(relative, str) or not relative or '\\' in relative
                        or Path(relative).is_absolute()
                        or any(part in ('', '.', '..') for part in relative.split('/'))):
                    raise ValueError('Invalid dependency override path')
                if not isinstance(content, bytes) and content is not None:
                    raise ValueError('Dependency override content must be bytes or None')
                cursor = self.root
                for part in relative.split('/'):
                    cursor = cursor / part
                    if cursor.is_symlink():
                        raise ValueError('Dependency override cannot traverse a symlink')
                self._rel(relative)
                if relative.startswith(('frontend/src/', 'backend/src/')):
                    proposed[relative] = None if content is None else self._hash(content)
        hashes = {}
        try:
            for source in ('frontend/src', 'backend/src'):
                base = self.root / source
                if base.is_symlink():
                    return None
                for path in sorted(base.rglob('*')):
                    relative = str(path.relative_to(self.root))
                    if relative == target:
                        continue
                    if path.is_symlink():
                        # Unknown bytes outside the source tree cannot establish
                        # equivalence, and must never be followed for a hash.
                        return None
                    if relative in proposed or not path.is_file():
                        continue
                    hashes[relative] = self._hash(path.read_bytes())
        except OSError:
            # An unreadable dependency cannot establish equivalence to an old
            # failed check. Let the real checker report the current condition.
            return None
        for relative, value in proposed.items():
            if relative == target:
                continue
            if value is None:
                hashes.pop(relative, None)
            else:
                hashes[relative] = value
        stamp = hashlib.sha256()
        for relative, value in sorted(hashes.items()):
            stamp.update(relative.encode('utf-8') + b'\0' + value.encode('utf-8') + b'\0')
        return stamp.hexdigest()

    def record(self, records: dict, error: str, baseline_compiles: bool):
        config = self._config()
        for rel_path, data in records.items():
            before = data.get('before')
            expected = data.get('expected')
            if before != expected:
                b_bytes = before if isinstance(before, bytes) else b""
                e_bytes = expected if isinstance(expected, bytes) else b""
                
                diff = difflib.unified_diff(
                    b_bytes.decode('utf-8', 'replace').splitlines(),
                    e_bytes.decode('utf-8', 'replace').splitlines(),
                    fromfile='before', tofile='REJECTED'
                )
                diff_str = "\n".join(diff)[:2200]
                
                imports = []
                if rel_path.endswith('.java') and baseline_compiles:
                    if "COMPILATION ERROR" in error or "cannot find symbol" in error:
                        try:
                            lines = b_bytes.decode('utf-8', 'replace').splitlines()
                            imports = [l.strip() for l in lines if l.strip().startswith("import ")]
                        except: pass

                entry = {
                    "path": self._rel(rel_path),
                    "base_sha": self._hash(before),
                    "candidate_sha": self._hash(expected),
                    "config": config,
                    "dependencies_sha": self._dependencies(self._rel(rel_path)),
                    "error": error[:1800],
                    "diff": diff_str,
                    "imports": imports,
                    "fingerprint": hashlib.sha256(error.encode()).hexdigest()
                }
                self.entries.append(entry)
        self._save()

    def guard(self, path: str, before: bytes | None, after: bytes, tool: str, dependency_overrides: dict | None = None):
        rel = self._rel(path)
        cfg = self._config()
        b_sha = self._hash(before)
        a_sha = self._hash(after)
        dependencies = self._dependencies(rel, dependency_overrides)
        
        matches = [e for e in self.entries if e['path'] == rel and e['config'] == cfg
                   and e['base_sha'] == b_sha and dependencies is not None
                   and e.get('dependencies_sha') == dependencies]
        
        for e in matches:
            if tool == 'write_file' and before is not None and e['base_sha'] == b_sha:
                raise ValueError("Earlier rewrite failed. Keep current file; use insert_text or a small exact edit instead.")
            if a_sha == e['candidate_sha']:
                raise ValueError(f"This exact candidate already failed... {e.get('error', '')[:1500]}")
            if e['imports']:
                current_lines = (after or b'').decode('utf-8', 'replace').splitlines()
                current_imports = {l.strip() for l in current_lines if l.strip().startswith("import ")}
                missing = [imp for imp in e['imports'] if imp not in current_imports]
                if missing:
                    raise ValueError(f"Previously working imports must be retained: {', '.join(missing)}")

    def context(self) -> str:
        cfg = self._config()
        ctx = []
        dependency_cache = {}
        # We look for entries where the current file matches the failed base
        # This requires checking actual file content on disk
        for e in reversed(self.entries):
            try:
                f_path = self.root / e['path']
                current_bytes = f_path.read_bytes() if f_path.exists() else None
                if self._hash(current_bytes) != e['base_sha'] or e['config'] != cfg:
                    continue
                if e['path'] not in dependency_cache:
                    dependency_cache[e['path']] = self._dependencies(e['path'])
                dependencies = dependency_cache[e['path']]
                if dependencies is not None and e.get('dependencies_sha') == dependencies:
                    ctx.append(f"FILE: {e['path']}\nREJECTED CANDIDATE FAILURE: {e['error']}\nWORKING IMPORTS: {e['imports']}\nINSTRUCTION: This is evidence from a rejected edit; the current source is already restored. Do not recreate rejected fixture resets. Use the CURRENT SOURCE CHECK to diagnose the baseline and make a small exact change preserving existing seed rows.\n")
            except: continue
            if len(ctx) >= 4: break
            
        res = "\n".join(ctx)
        return res[:6500]
