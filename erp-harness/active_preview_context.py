import json
import re
from types import SimpleNamespace
from divide_context import snapshot

def active_screen_context(runner) -> str:
    """Returns the source text of the currently active screen in the workspace."""
    try:
        root = runner.h.workspace.root
        # 1. Validate workspace metadata
        meta_text, meta_readset = snapshot(
            SimpleNamespace(h=runner.h), 
            {'paths': [], 'references': ['frontend/src/workspace.json'], 'domain': 'backend'}
        )
        if 'frontend/src/workspace.json' not in meta_readset:
            return ''
        
        ws_data = json.loads((root / 'frontend/src/workspace.json').read_text(encoding='utf-8'))
        if not isinstance(ws_data, dict):
            return ''
            

        # 2. Identify active tab
        active = ws_data.get('activeTab')
        if not isinstance(active, str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*', active):
            return ''
            
        rel_path = f'frontend/src/screens/{active}.tsx'
        if not (root / rel_path).is_file() and re.fullmatch(r'[A-Z]{3}[0-9]{4}', active):
            matches = []
            for candidate in (root / 'frontend/src/screens').glob('*.tsx'):
                if candidate.is_symlink() or candidate.stat().st_size > 200000:
                    continue
                declaration = re.search(r'export\s+const\s+meta\s*=\s*\{([^}]+)\}', candidate.read_text(encoding='utf-8'))
                code = re.search(r'''\bcode\s*:\s*['"]([A-Z]{3}[0-9]{4})['"]''', declaration[1]) if declaration else None
                if code and code[1] == active:
                    matches.append(candidate.relative_to(root).as_posix())
            if len(matches) != 1:
                return ''
            rel_path = matches[0]
        
        # 3. Snapshot the actual screen file
        screen_text, screen_readset = snapshot(
            SimpleNamespace(h=runner.h),
            {'paths': [], 'references': [rel_path, 'frontend/src/workspace.json'], 'domain': 'backend'}
        )
        
        if rel_path not in screen_readset:
            return ''

        # 4. Final safety: Ensure the path was actually part of the snapshot's read set
        # and is contained within the workspace structure via the snapshot logic.
        return (
            f"ACTIVE PREVIEW SCREEN (current user focus): {rel_path}\n"
            f"Reuse actual existing selectors, labels, handlers from this complete source. "
            f"Do not invent alternate data-testid names or rebuild working UI just to give tests markers. "
            f"Shell/sidebar tasks may still target App.tsx from remaining context.\n"
            f"{screen_text}\n"
        )

    except (ValueError, OSError, TypeError, json.JSONDecodeError):
        return ''
