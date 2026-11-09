import os
import stat
import tempfile
from pathlib import Path
from typing import Dict, List, Any, Optional

class Checkpoint:
    """Manages file snapshots for local coding agent rollbacks."""

    def __init__(self, workspace: Any):
        self.workspace = workspace
        # records[rel_str] = {'before': bytes|None, 'mode': int|None, 'expected': bytes|None}
        self._records: Dict[str, Dict[str, Any]] = {}

    @property
    def pending(self) -> bool:
        return bool(self._records)

    def _check_symlink_ancestors(self, rel: str) -> None:
            """
            Ensures that the relative path 'rel' does not traverse through any symlinks
            within the workspace root. Checks ancestors cumulatively.
            """
            if os.path.isabs(rel):
                raise ValueError(f"Path must be relative: {rel}")

            # Explicitly reject '..' to prevent directory traversal attempts
            parts = rel.split(os.sep)
            if ".." in parts:
                raise ValueError("Path contains '..' components")

            root = self.workspace.root
            current_path = root

            for part in parts:
                if not part or part == ".":
                    continue

                current_path = current_path / part

                # Check if the current component is a symlink
                # We check the component itself before moving deeper
                if current_path.is_symlink():
                    raise ValueError(f"Symlink detected at: {current_path}")

                # Safety check: ensure we haven't escaped the root via logic errors
                try:
                    current_path.relative_to(root)
                except ValueError:
                    raise ValueError(f"Path escapes workspace root: {current_path}")

    def stage(self, rel: str) -> None:
        if self.workspace.is_protected(self.workspace.safe_path(rel)):
            raise ValueError("Protected path")
        self._check_symlink_ancestors(rel)
        target = self.workspace.safe_path(rel)
        rel = str(target.relative_to(self.workspace.root))
        if target.is_symlink():
            raise ValueError("Target is a symlink")
        if target.exists() and not target.is_file():
            raise ValueError("Target is a directory")
        
        if rel not in self._records:
            before = target.read_bytes() if target.exists() and target.is_file() else None
            mode = stat.S_IMODE(target.stat().st_mode) if target.exists() and target.is_file() else None
            self._records[rel] = {'before': before, 'mode': mode, 'expected': before}
        
        if target.exists() and target.is_file() and target.stat().st_size > 1048576:
            raise ValueError("File exceeds 1MiB")

    def record(self, rel: str) -> None:
        self._check_symlink_ancestors(rel)
        target = self.workspace.safe_path(rel)
        key = str(target.relative_to(self.workspace.root))
        if key not in self._records:
            raise ValueError("Not staged")
        self._records[key]['expected'] = target.read_bytes() if target.exists() and target.is_file() else None

    def commit(self) -> None:
        self._records.clear()

    def rollback(self) -> List[str]:
        restored: List[str] = []
        conflicts: List[str] = []
        snapshot = self._records.copy()
        self._records.clear()

        for rel, data in snapshot.items():
            try:
                self._check_symlink_ancestors(rel)
                target = self.workspace.safe_path(rel)
                if target.is_symlink():
                    conflicts.append(f"{rel} is a symlink")
                    continue

                current_exists = target.exists() and target.is_file()
                current_bytes = target.read_bytes() if current_exists else None
                
                if current_bytes != data['expected']:
                    conflicts.append(f"{rel} was edited concurrently")
                    continue

                # If current matches expected, we still restore mode if it differs
                if data['before'] is None:
                    if current_exists:
                        target.unlink()
                        restored.append(rel)
                else:
                    fd, tmp_path = tempfile.mkstemp(dir=target.parent)
                    try:
                        with os.fdopen(fd, 'wb') as f:
                            f.write(data['before'])
                        if data['mode'] is not None:
                            os.chmod(tmp_path, data['mode'])
                        os.replace(tmp_path, target)
                        restored.append(rel)
                    except Exception as e:
                        if os.path.exists(tmp_path): os.remove(tmp_path)
                        raise RuntimeError(f"Restore failed: {e}")
            except Exception as e:
                conflicts.append(str(e))

        if conflicts:
            raise RuntimeError(f"Conflicts: {', '.join(conflicts)}")
        return restored
