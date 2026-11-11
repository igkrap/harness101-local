"""Where a standard registration screen must change when its fields change.

A standard screen keeps every field in five places: the row type, the edit fields, the grid columns, toRow
(API answer -> row) and the save payload. Adding a field means touching all five; a model reliably forgets one.
This finds the places (line numbers) and says what goes into each, and after an edit says which place still
lacks the field - before the slower type check, and in plainer words than a type error.
"""
import re

SITES = (('row_type', '행 타입'), ('edit_fields', '편집 필드 목록(editFields)'), ('grid_columns', '그리드 열 목록(gridColumns)'),
         ('to_row', 'toRow(서버 응답 → 화면 행)'), ('payload', '저장 payload'))


def sites(source):
    """{site: (first line, last line)} (1-based) for the sites this screen has."""
    lines = source.splitlines()
    found = {}

    def block(start_pattern, end_pattern, key):
        for index, line in enumerate(lines):
            if re.search(start_pattern, line):
                for end in range(index, min(index + 60, len(lines))):
                    if re.search(end_pattern, lines[end]):
                        found[key] = (index + 1, end + 1)
                        return
                return

    block(r'^type \w+Row\s*=\s*\{', r'\};\s*$', 'row_type')
    block(r'^const editFields\b', r'^\];', 'edit_fields')
    block(r'^const gridColumns\b', r'^\];', 'grid_columns')
    block(r'^function toRow\b', r'^\}', 'to_row')
    block(r'\bconst payload\s*=\s*\{', r'\};\s*$', 'payload')
    return found


def _text(source, span):
    return '\n'.join(source.splitlines()[span[0] - 1:span[1]])


def snippet(site, field):
    """What to put into a site for this field."""
    name, label = field['name'], field['label']
    number, ref = field.get('type') == 'number', field.get('ref')
    if site == 'row_type':
        return f'{name}: string;'
    if site == 'edit_fields':
        extra = f", lookup: {{ api: '{ref['path']}', label: '{ref['label']}' }}" if ref else ", type: 'integer'" if number else ''
        return f"{{ name: '{name}', label: '{label}'{', required: true' if field['required'] else ''}, group: '{'basic' if field['required'] else 'extra'}'{extra} }},"
    if site == 'grid_columns':
        return f"{{ key: '{name}', label: '{label}', width: 130 }},   // 수정자 열 앞에"
    if site == 'to_row':
        return f'{name}: text(data.{name}),'
    return f'{name}: Number(values.{name}) || null,' if (number or ref) else f'{name}: values.{name}.trim() || null,'


def missing(source, field):
    """Sites of this screen that do not mention the field yet."""
    out = []
    for site, span in sites(source).items():
        text = _text(source, span)
        present = re.search(r'\b' + re.escape(field['name']) + r'\b', text) or (site == 'grid_columns' and field['label'] in text)
        if not present:
            out.append(site)
    return out


def plan(source, added, changed=(), removed=()):
    """Numbered instructions: line, place, what to write."""
    spans, names, steps = sites(source), dict(SITES), []
    for field in added:
        for site, _ in SITES:
            if site in spans and site in missing(source, field):
                first, last = spans[site]
                where = f'{first}행' if first == last else f'{first}~{last}행'
                steps.append(f"{where} {names[site]}: `{snippet(site, field)}` 추가")
    lines = source.splitlines()
    for field in changed:
        for index, line in enumerate(lines):
            if re.search(r"name:\s*'" + re.escape(field['name']) + "'", line) and 'edit_fields' in spans and spans['edit_fields'][0] <= index + 1 <= spans['edit_fields'][1]:
                steps.append(f"{index + 1}행 편집 필드 {field['label']}: 이 줄을 `{snippet('edit_fields', field)}` 로 바꾼다")
    for field in removed:
        hits = [str(index + 1) for index, line in enumerate(lines) if re.search(r'\b' + re.escape(field['name']) + r'\b', line)]
        if hits:
            steps.append(f"{', '.join(hits)}행에서 {field['name']}({field['label']}) 을(를) 지운다")
    return [f'{number}. {step}' for number, step in enumerate(steps, 1)]


# The change the current run is expected to make to one screen file: checked before the type check.
EXPECTED = {}


def expect(path, fields):
    EXPECTED.clear()
    EXPECTED.update(path=path, fields=list(fields))


def precheck(root):
    """None when the expected fields are in every site; otherwise a checker failure naming the gaps."""
    if not EXPECTED:
        return None
    from pathlib import Path
    try:
        source = (Path(root) / EXPECTED['path']).read_text(encoding='utf-8')
    except OSError:
        return None
    spans, names, gaps = sites(source), dict(SITES), []
    for field in EXPECTED['fields']:
        for site in missing(source, field):
            first, last = spans[site]
            gaps.append(f"- {EXPECTED['path']} {first}~{last}행 {names[site]} 에 {field['name']}({field['label']}) 이(가) 없다. 넣을 내용: `{snippet(site, field)}`")
    if not gaps:
        return None
    return {'success': False, 'stdout': '', 'returncode': 1,
            'stderr': '항목이 빠진 자리가 있다(다른 자리는 이미 고쳐졌으니 그대로 두고 아래 자리만 고친다):\n' + '\n'.join(gaps)}
