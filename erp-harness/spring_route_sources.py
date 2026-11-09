"""Conservative, read-only facts for literal Spring controller routes.

This is not a Java compiler or a route-pattern matcher. Unsupported expressions
never become guessed routes, and HTTP verbs do not select a different owner.
"""
import hashlib
import os
from pathlib import Path
import re
import stat

MAX_FILES = 1000
MAX_SOURCE_BYTES = 200000
MAX_TOTAL_BYTES = 8 * 1024 * 1024
_IDENTIFIER = re.compile(r'[A-Za-z_$][A-Za-z0-9_$]*')
_PATH = re.compile(r'[A-Za-z0-9_./~-]*')
_WEB = 'org.springframework.web.bind.annotation.'
_MAPPINGS = {'RequestMapping', 'GetMapping', 'PostMapping', 'PutMapping', 'PatchMapping', 'DeleteMapping'}
_ANNOTATIONS = {_WEB + name for name in _MAPPINGS | {'RestController'}} | {'org.springframework.stereotype.Controller'}
_MODIFIERS = {'public', 'protected', 'private', 'static', 'final', 'abstract', 'strictfp',
              'sealed', 'non', '-', 'transient', 'volatile', 'synchronized', 'native', 'default'}


def _lex(text):
    if re.search(r'\\u+', text):
        raise ValueError('Java Unicode preprocessing is unsupported')
    tokens, index = [], 0
    while index < len(text):
        if text[index].isspace():
            index += 1
        elif text.startswith('//', index):
            end = text.find('\n', index + 2)
            index = len(text) if end < 0 else end + 1
        elif text.startswith('/*', index):
            end = text.find('*/', index + 2)
            if end < 0:
                raise ValueError('Unclosed comment')
            index = end + 2
        elif text.startswith('"""', index):
            end = index + 3
            while True:
                end = text.find('"""', end)
                if end < 0:
                    raise ValueError('Unclosed text block')
                preceding = len(text[:end]) - len(text[:end].rstrip('\\'))
                if preceding % 2 == 0:
                    break
                end += 3
            tokens.append(('text', ''))
            index = end + 3
        elif text[index] in ('"', "'"):
            quote, end = text[index], index + 1
            while end < len(text) and text[end] != quote:
                if text[end] in '\r\n':
                    raise ValueError('Unclosed literal')
                end += 2 if text[end] == '\\' else 1
            if end >= len(text):
                raise ValueError('Unclosed literal')
            tokens.append(('string' if quote == '"' else 'char', text[index + 1:end]))
            index = end + 1
        else:
            identifier = _IDENTIFIER.match(text, index)
            if identifier:
                tokens.append(('id', identifier.group()))
                index = identifier.end()
            else:
                tokens.append(('symbol', text[index]))
                index += 1
    return tokens


def _group(tokens, start, opening, closing):
    depth = 0
    for index in range(start, len(tokens)):
        if tokens[index] == ('symbol', opening):
            depth += 1
        elif tokens[index] == ('symbol', closing):
            depth -= 1
            if depth == 0:
                return tokens[start + 1:index], index + 1
    raise ValueError('Unbalanced Java group')


def _annotation(tokens, start):
    index, pieces = start + 1, []
    if index >= len(tokens) or tokens[index][0] != 'id':
        raise ValueError('Unsupported annotation declaration')
    pieces.append(tokens[index][1]); index += 1
    while index + 1 < len(tokens) and tokens[index] == ('symbol', '.') and tokens[index + 1][0] == 'id':
        pieces.extend(('.', tokens[index + 1][1])); index += 2
    args = []
    if index < len(tokens) and tokens[index] == ('symbol', '('):
        args, index = _group(tokens, index, '(', ')')
    return (''.join(pieces), args), index


def _split(tokens):
    result, part, depth = [], [], 0
    for token in tokens:
        if token[0] == 'symbol' and token[1] in '({[':
            depth += 1
        if token[0] == 'symbol' and token[1] in ')}]':
            depth -= 1
        if token == ('symbol', ',') and depth == 0:
            result.append(part); part = []
        else:
            part.append(token)
    if part:
        result.append(part)
    return result


def _path(value):
    if not _PATH.fullmatch(value) or '//' in value or any(part in ('.', '..') for part in value.split('/')):
        return None
    return '/' + value if value and not value.startswith('/') else value


def _literal_paths(expression):
    if expression and expression[0] == ('symbol', '{'):
        contents, end = _group(expression, 0, '{', '}')
        if end != len(expression):
            return None
        parts = _split(contents)
    else:
        parts = [expression]
    if not parts:
        return ['']
    if len(parts) > 16 or any(len(part) != 1 or part[0][0] != 'string' for part in parts):
        return None
    values = [_path(part[0][1]) for part in parts]
    return None if any(value is None for value in values) else list(dict.fromkeys(values))


def _paths(args):
    if not args:
        return ['']
    if args[0][0] == 'string' or args[0] == ('symbol', '{'):
        return _literal_paths(args)
    paths = []
    for part in _split(args):
        if len(part) < 3 or part[0][0] != 'id' or part[1] != ('symbol', '='):
            return None
        if part[0][1] in ('path', 'value'):
            paths.append(_literal_paths(part[2:]))
    return [''] if not paths else paths[0] if len(paths) == 1 else None


def _declared_names(tokens):
    return {tokens[index + 1][1] for index, token in enumerate(tokens[:-1])
            if token[0] == 'id' and token[1] in ('class', 'interface', 'enum', 'record')
            and tokens[index + 1][0] == 'id'}


def _package_name(tokens):
    for index, token in enumerate(tokens):
        if token == ('id', 'package'):
            end = next((j for j in range(index + 1, len(tokens)) if tokens[j] == ('symbol', ';')), len(tokens))
            return ''.join(value for _, value in tokens[index + 1:end])
    return ''


def _spring(name, imports, wildcards, local_names=(), package_names=()):
    if name.split('.')[0] in local_names:
        return None
    if '.' in name:
        return name if name in _ANNOTATIONS else None
    explicit = imports.get(name)
    if explicit is not None:
        return next(iter(explicit)) if len(explicit) == 1 and next(iter(explicit)) in _ANNOTATIONS else None
    if name in package_names:
        return None
    if any(not prefix.startswith('java.') and prefix not in ('org.springframework.web.bind.annotation', 'org.springframework.stereotype')
           for prefix in wildcards):
        return None  # An unknown wildcard could bind the same annotation name.
    choices = {prefix + '.' + name for prefix in wildcards} & _ANNOTATIONS
    return next(iter(choices)) if len(choices) == 1 else None


def _method_annotations(tokens, class_name):
    pending, header, index = [], [], 0
    while index < len(tokens):
        token = tokens[index]
        if token == ('symbol', '@'):
            annotation, index = _annotation(tokens, index)
            pending.append(annotation)
            continue
        if token == ('symbol', '('):
            arguments, end = _group(tokens, index, '(', ')')
            header.append(('symbol', '(')); header.extend(arguments); header.append(('symbol', ')'))
            index = end
            continue
        if token in (('symbol', ';'), ('symbol', '{')):
            values = [value for _, value in header]
            prefix = values[:values.index('(')] if '(' in values else []
            is_method = bool(prefix) and '=' not in prefix and not any(word in prefix for word in ('class', 'interface', 'enum', 'record'))
            if is_method and values[values.index('(') - 1] != class_name:
                yield pending
            pending, header = [], []
            if token == ('symbol', '{'):
                _, index = _group(tokens, index, '{', '}')
            else:
                index += 1
            continue
        header.append(token); index += 1


def _facts(text, route, package_names=(), tokens=None):
    tokens = _lex(text) if tokens is None else tokens
    index, package, imports, wildcards, pending = 0, '', {}, set(), []
    local_names = _declared_names(tokens)
    def spring(name):
        return _spring(name, imports, wildcards, local_names, package_names)
    found = []
    while index < len(tokens):
        kind, value = tokens[index]
        if kind == 'id' and value in ('package', 'import'):
            end = next((j for j in range(index + 1, len(tokens)) if tokens[j] == ('symbol', ';')), len(tokens))
            if end == len(tokens) or end == index + 1:
                raise ValueError('Incomplete package or import declaration')
            declaration = ''.join(part for _, part in tokens[index + 1:end])
            if value == 'package':
                package = declaration
            elif tokens[index + 1] == ('id', 'static'):
                target = ''.join(part for _, part in tokens[index + 2:end])
                if target.endswith('.*'):
                    wildcards.add('static:' + target[:-2])
                else:
                    imports.setdefault(target.rsplit('.', 1)[-1], set()).add('static:' + target)
            else:
                if declaration.endswith('.*'):
                    wildcards.add(declaration[:-2])
                else:
                    imports.setdefault(declaration.rsplit('.', 1)[-1], set()).add(declaration)
            pending = []; index = end + 1
        elif (kind, value) == ('symbol', '@'):
            annotation, index = _annotation(tokens, index)
            pending.append(annotation)
        elif (kind, value) == ('id', 'class'):
            if index + 1 >= len(tokens) or tokens[index + 1][0] != 'id':
                return []
            name = tokens[index + 1][1]
            end = next((j for j in range(index + 2, len(tokens)) if tokens[j] == ('symbol', '{')), len(tokens))
            body, next_index = _group(tokens, end, '{', '}')
            annotations = [(spring(annotation), args) for annotation, args in pending]
            marker = any(annotation in (_WEB + 'RestController', 'org.springframework.stereotype.Controller') for annotation, _ in annotations)
            unknown_mapping = any(annotation.rsplit('.', 1)[-1] in _MAPPINGS and spring(annotation) is None
                                  for annotation, _ in pending)
            inherited = any(token in (('id', 'extends'), ('id', 'implements')) for token in tokens[index + 2:end])
            bases = [args for annotation, args in annotations if annotation == _WEB + 'RequestMapping']
            bases = _paths(bases[0]) if len(bases) == 1 else [''] if not bases else None
            matched, match_kind = set(), 'method-path'
            if marker and bases is not None and not unknown_mapping and not inherited:
                if route in bases and route:
                    matched.add(route); match_kind = 'class-base'
                for annotations in _method_annotations(body, name):
                    if any(annotation.rsplit('.', 1)[-1] in _MAPPINGS and spring(annotation) is None
                           for annotation, _ in annotations):
                        continue
                    mappings = [args for annotation, args in annotations
                                if (spring(annotation) or '').rsplit('.', 1)[-1] in _MAPPINGS]
                    paths = _paths(mappings[0]) if len(mappings) == 1 else None
                    if paths is not None:
                        for base in bases:
                            for relative in paths:
                                effective = (base or '/') if not relative else (base.rstrip('/') + '/' + relative.lstrip('/'))
                                if effective == route:
                                    matched.add(route)
                if matched:
                    found.append({'class_name': (package + '.' if package else '') + name,
                                  'matched_routes': sorted(matched), 'match_kind': match_kind})
            pending = []; index = next_index
        elif (kind, value) == ('symbol', '{'):
            _, index = _group(tokens, index, '{', '}'); pending = []
        else:
            if kind != 'id' or value not in _MODIFIERS:
                pending = []
            index += 1
    return found


def route_owners(root, route):
    """Return exact static controller facts; callers promote only one owner."""
    if not isinstance(route, str) or not route.startswith('/') or _path(route) != route:
        return []
    root = Path(root).absolute()
    if '..' in root.parts or any(path.is_symlink() for path in (root, *root.parents)):
        return []
    base = root / 'backend/src/main/java'
    if not base.is_dir() or any(path.is_symlink() for path in (base, *base.parents)):
        return []
    result, sources, package_names, count, total = [], [], {}, 0, 0
    try:
        for parent, directories, files in os.walk(base, followlinks=False):
            directories[:] = sorted(name for name in directories if not (Path(parent) / name).is_symlink())
            for name in sorted(files):
                source = Path(parent) / name
                if source.suffix != '.java' or source.is_symlink():
                    continue
                source.resolve().relative_to(root)
                descriptor = os.open(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
                try:
                    info = os.fstat(descriptor)
                    if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_SOURCE_BYTES:
                        return []
                    raw = b''
                    while len(raw) <= MAX_SOURCE_BYTES:
                        chunk = os.read(descriptor, min(16384, MAX_SOURCE_BYTES + 1 - len(raw)))
                        if not chunk:
                            break
                        raw += chunk
                finally:
                    os.close(descriptor)
                count += 1; total += len(raw)
                if count > MAX_FILES or total > MAX_TOTAL_BYTES or len(raw) > MAX_SOURCE_BYTES:
                    return []
                text = raw.decode('utf-8')
                tokens = _lex(text)
                package = _package_name(tokens)
                package_names.setdefault(package, set()).update(_declared_names(tokens))
                sources.append((source, raw, text, tokens, package))
        for source, raw, text, tokens, package in sources:
            for fact in _facts(text, route, package_names[package], tokens):
                result.append({'source': source.relative_to(root).as_posix(),
                               'sha256': hashlib.sha256(raw).hexdigest(), **fact})
    except (OSError, ValueError, UnicodeError):
        return []
    return result
