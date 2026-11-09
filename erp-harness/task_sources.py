"""Resolve explicit task mentions to unique, existing project source paths."""
import os
from pathlib import Path
import re


def _source_matches(root, task):
    root = Path(root).resolve()
    task = str(task)
    sources = []
    for directory, extensions in (('frontend/src', {'.ts', '.tsx'}),
                                  ('backend/src', {'.java', '.sql'})):
        base = root / directory
        if any((root / Path(*Path(directory).parts[:index])).is_symlink()
               for index in range(1, len(Path(directory).parts) + 1)):
            continue
        if not base.is_dir():
            continue
        for parent, directories, files in os.walk(base, followlinks=False):
            directories[:] = sorted(name for name in directories
                                    if not name.startswith('.') and not (Path(parent) / name).is_symlink())
            for name in sorted(files):
                path = Path(parent) / name
                if path.suffix in extensions and path.is_file() and not path.is_symlink():
                    sources.append(path.relative_to(root).as_posix())
    explicit, aliases = [], {}
    mentioned = bool(re.search(r'[A-Za-z_$][\w$.-]*\.(?:tsx|jsx|ts|js|java|sql|json|xml|properties|yaml|yml|txt|css|html)(?![A-Za-z0-9_./\\-])', task))
    for path in sorted(sources):
        # Preserve explicit source paths immediately followed by Korean prose.
        match = re.search(r'(?<![\w./\\-])' + re.escape(path) + r'(?![A-Za-z0-9_/\\-]|\.(?=[A-Za-z0-9_./\\-]))', task)
        if match:
            explicit.append((match.start(), path))
            mentioned = True
        name = Path(path).name
        for alias in (name, Path(name).stem):
            aliases.setdefault(alias, []).append(path)
    mentions = []
    for alias, paths in aliases.items():
        # A complete filename may be directly followed by Korean prose, as
        # explicit paths already can. Stems retain identifier boundaries.
        end = (r'(?![A-Za-z0-9_/\\-]|\.(?=[A-Za-z0-9_./\\-]))'
               if all(Path(source).name == alias for source in paths)
               else r'(?![\w/\\-]|\.(?=[\w./\\-]))')
        match = re.search(r'(?<![\w./\\-])' + re.escape(alias) + end, task)
        if match:
            mentioned = True
            if len(paths) == 1:  # A name alone never disambiguates two existing sources.
                mentions.append((match.start(), paths[0]))
    named = list(dict.fromkeys(path for _, path in sorted(explicit) + sorted(mentions)))
    if named or mentioned:
        return named, mentioned
    # Screen titles are stable user-facing identifiers. A unique exact title
    # mention can resolve a screen without asking the user for its file name.
    title_matches = []
    for path in sources:
        if not path.startswith('frontend/src/screens/') or not path.endswith('.tsx'):
            continue
        try:
            with (root / path).open('rb') as stream:
                source = stream.read(8192).decode('utf-8')
        except (OSError, UnicodeError):
            continue
        meta = re.search(r'\bexport\s+const\s+meta\s*=\s*\{([^{}]{0,1000})\}', source)
        if not meta:
            continue
        title = re.search(r'\btitle\s*:\s*([\'\"])([^\'\"\r\n]{3,100})\1', meta.group(1))
        if title and title.group(2) in task:
            title_matches.append(path)
    return (title_matches if len(title_matches) == 1 else []), mentioned


def resolve_task_sources(root, task):
    return _source_matches(root, task)[0]


def _task_route(task):
    """Return one relative literal URL path; external or multiple URLs do not infer ownership."""
    from urllib.parse import urlsplit
    # Mask entire absolute URLs so their path suffix cannot become a relative target.
    task = re.sub(r'\b[A-Za-z][A-Za-z0-9+.-]*://[^\s<>\"\'`]+', ' ', str(task))
    paths = set()
    for match in re.finditer(r'(?<![A-Za-z0-9_./:-])(/[A-Za-z0-9_~%!$&()*+,;=:@/?#{}\[\].-]+)', task):
        value = match.group(1)
        if value.startswith('//'):
            continue
        try:
            path = urlsplit(value).path
        except ValueError:
            continue
        if path.startswith('/') and not path.startswith('//') and '..' not in path.split('/'):
            paths.add(path)
    return next(iter(paths)) if len(paths) == 1 else None


def resolve_runner_sources(runner):
    """Prefer explicit sources; infer one real controller only for focused backend tasks."""
    workspace = getattr(getattr(runner, 'h', None), 'workspace', None)
    root = getattr(workspace, 'root', None)
    if root is None:
        return []
    task = getattr(getattr(runner, 'args', None), 'task', '')
    explicit, mentioned = _source_matches(root, task)
    if explicit:
        return explicit
    from focused_context import enabled
    if mentioned or not enabled(runner) or set(getattr(runner, 'modes', ())) != {'backend'}:
        return []
    route = _task_route(task)
    if route is None:
        return []
    try:
        from spring_route_sources import route_owners
        owners = route_owners(root, route)
        if not isinstance(owners, list) or len(owners) != 1 or not isinstance(owners[0], dict):
            return []
        owner = owners[0]
        source = owner.get('source')
        if (not isinstance(source, str) or '\\' in source or
                not source.startswith('backend/src/main/java/') or not source.endswith('.java') or
                Path(source).is_absolute() or '..' in Path(source).parts or Path(source).as_posix() != source or
                not isinstance(owner.get('class_name'), str) or not owner['class_name'] or
                not isinstance(owner.get('matched_routes'), (list, tuple)) or route not in owner['matched_routes'] or
                owner.get('match_kind') not in ('class-base', 'method-path')):
            return []
        from source_progress import current_bytes
        import hashlib
        raw = current_bytes(runner, source)
        if raw is None or hashlib.sha256(raw).hexdigest() != owner.get('sha256'):
            return []
        return [source]
    except (ImportError, OSError, ValueError, TypeError, AttributeError):
        return []


def task_screen_title(root, task):
    """User-facing title of the single screen a task targets (by title mention or explicit screen path)."""
    root = Path(root)
    found = set()
    for path in sorted((root / 'frontend/src/screens').glob('*.tsx')):
        try:
            source = path.read_bytes()[:8192].decode('utf-8')
        except (OSError, UnicodeError):
            continue
        meta = re.search(r'\bexport\s+const\s+meta\s*=\s*\{([^{}]{0,1000})\}', source)
        title = meta and re.search(r'\btitle\s*:\s*([\'\"])([^\'\"\r\n]{2,100})\1', meta.group(1))
        if not title:
            continue
        rel = path.relative_to(root).as_posix()
        if title.group(2) in task or rel in task or path.stem in task:
            found.add(title.group(2))
    return found.pop() if len(found) == 1 else ''


REFERENCE_SCREEN = 'frontend/src/screens/ItemMaster.tsx'


def new_screen_reference(root, task):
    """Title of the reference screen when a task adds a new screen (no existing screen title in it), else ''.

    A new screen does not exist before the change; the reference screen is built from the same framework
    components, so its elements show what the new screen's query panel, grid, editor and toolbar will be."""
    root = Path(root)
    if not re.search(r'화면|screen', str(task), re.I) or task_screen_title(root, task):
        return ''
    try:
        source = (root / REFERENCE_SCREEN).read_text(encoding='utf-8')
    except (OSError, UnicodeError):
        return ''
    meta = re.search(r'\bexport\s+const\s+meta\s*=\s*\{([^{}]{0,1000})\}', source)
    title = meta and re.search(r'\btitle\s*:\s*([\'"])([^\'"\r\n]{2,100})\1', meta.group(1))
    return title.group(2) if title else ''
