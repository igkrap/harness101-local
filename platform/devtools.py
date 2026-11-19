"""Looking inside a project while it is being made: its screens as definitions (and how they changed between
records), the records its development site holds, and what its server wrote to its log. Read only - nothing here
changes the project; changing goes through requests and the controls in release.py.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

import project_git as vcs
import release
from sites import DB_CONTAINER, DB_USER, site

KINDS = {'text': '글자', 'number': '숫자', 'date': '날짜', 'time': '시각', 'yesno': '예/아니오', 'memo': '긴 글', 'code': '공통 코드', 'ref': '다른 화면 자료', 'serial': '자동 번호'}


def _harness():
    folder = str(Path(__file__).resolve().parents[1] / 'harness2')
    if folder not in sys.path:
        sys.path.insert(0, folder)
    import define
    return define


def _at(project, key, rev):
    """A screen's definition as a record of git holds it (None when it was not there then)."""
    shown = subprocess.run(['git', 'show', f'{vcs._sha(project, rev)}:release/definitions/{key}.json'], cwd=project, capture_output=True, text=True, timeout=60)
    return json.loads(shown.stdout)['definition'] if shown.returncode == 0 else None


def _field(field):
    notes = [KINDS.get(field.get('type', 'text'), field.get('type', ''))]
    if field.get('required'): notes.append('필수')
    if field.get('unique'): notes.append('중복 불가')
    if field.get('codeGroup'): notes.append(f"코드 {field['codeGroup']}")
    if field.get('ref'): notes.append(f"→ {field['ref'].get('entity')}")
    if field.get('prefix'): notes.append(f"머리글 {field['prefix']}")
    if field.get('formula'): notes.append(f"계산 {field['formula']}")
    if field.get('sum'): notes.append(f"줄 합계 {field['sum']}")
    if field.get('min') is not None or field.get('max') is not None: notes.append(f"{'' if field.get('min') is None else field['min']}~{'' if field.get('max') is None else field['max']}")
    if field.get('decimals') is not None: notes.append(f"소수 {field['decimals']}자리")
    if field.get('search'): notes.append('조회 조건')
    return {'name': field['name'], 'label': field['label'], 'notes': notes}


def screens(project):
    """Every screen of the development site: what it is, how many records it holds, when git last recorded a change of it."""
    # Each screen keeps its records in a table of its own (r_<key>; its lines in r_<key>__<lines>).
    tables = [name for name in release._psql(site().db, "SELECT to_json(table_name) FROM information_schema.tables WHERE table_schema = current_schema() AND table_name LIKE 'r\\_%' AND table_name NOT LIKE '%\\_\\_%'", rows=True)
              if re.fullmatch(r'r_[a-z][a-z0-9_]{1,39}', name)]
    counts = dict(release._psql(site().db, ' UNION ALL '.join(f"SELECT json_build_array('{name[2:]}', (SELECT COUNT(*) FROM {name}))" for name in tables), rows=True)) if tables else {}
    out = []
    for item in release.screens():
        last = vcs._git(project, 'log', '-1', '--date=format:%m-%d %H:%M', '--format=%ad|%s', '--', f"release/definitions/{item['key']}.json", check=False) if (Path(project) / '.git').exists() else ''
        out.append({**item, 'records': counts.get(item['key'], 0), 'last': dict(zip(('when', 'subject'), last.split('|', 1))) if '|' in last else None})
    return out


def screen(project, key, rev=None):
    """One screen in full: its fields and other parts in plain words, the definition itself, and the records of git that changed it.
    rev: as that record held it, with what differs from the site now."""
    held = release._definitions(site().db).get(key)
    now = held['definition'] if held else None
    definition = _at(project, key, rev) if rev else now
    if definition is None and now is None:
        raise ValueError('그런 화면이 없습니다: ' + str(key)[:60])
    rows = vcs._git(project, 'log', '-30', '--date=format:%m-%d %H:%M', '--format=%H|%ad|%an|%s', '--', f'release/definitions/{key}.json', check=False).splitlines()
    history = [dict(zip(('sha', 'when', 'who', 'subject'), row.split('|', 3))) for row in rows if row.count('|') >= 3]
    out = {'key': key, 'rev': rev, 'exists_now': now is not None, 'history': history, 'definition': definition}
    if definition:
        parts = []
        if definition.get('lines'): parts.append(f"줄 표 \"{definition['lines'].get('label', '')}\"")
        if definition.get('status'): parts.append('상태: ' + ' → '.join(value['label'] for value in definition['status'].get('values', [])))
        for name, label in (('rules', '규칙'), ('checks', '비교 규칙'), ('limits', '한도'), ('effects', '자동 처리')):
            if definition.get(name): parts.append(f"{label} {len(definition[name])}개")
        for name, label in (('summary', '집계'), ('dashboard', '현황판'), ('over', '업무 화면'), ('print', '출력 양식')):
            if definition.get(name): parts.append(label)
        out.update(title=definition.get('title'), type=definition.get('type'), parts=parts, fields=[_field(field) for field in definition.get('fields') or []],
                   lines=[_field(field) for field in (definition.get('lines') or {}).get('fields') or []])
    if rev:        # from that record to now, in plain words
        if definition is None:
            out['differences'] = ['그 기록에는 이 화면이 없었습니다 (그 뒤에 만들어졌습니다).']
        elif now is None:
            out['differences'] = ['지금은 이 화면이 없습니다 (그 뒤에 지워졌습니다).']
        else:
            out['differences'] = _harness().differences(definition, now)[0] or ['그 기록과 지금이 같습니다.']
    return out


def records(key, limit=50):
    """The newest records of a screen as the development site holds them (read only)."""
    limit = max(1, min(200, int(limit)))
    if not re.fullmatch(r'[a-z][a-z0-9_]{1,39}', str(key)):
        raise ValueError('그런 화면이 없습니다: ' + str(key)[:60])
    table = 'r_' + key
    if not release._psql(site().db, f"SELECT 1 FROM information_schema.tables WHERE table_schema = current_schema() AND table_name = '{table}'").strip():
        return {'key': key, 'table': None, 'total': 0, 'rows': []}       # a screen that keeps no records of its own (a summary, a work screen ...)
    total = int(release._psql(site().db, f'SELECT COUNT(*) FROM {table}').strip() or 0)
    # data: the row's own columns as the table holds them (f_<field>); lines are in the tables named in line_tables
    rows = release._psql(site().db, f"""SELECT json_build_object('id', t.id, 'status', t.status, 'data', to_jsonb(t) - 'id' - 'status' - 'created_by' - 'created_at' - 'updated_by' - 'updated_at',
        'updated_by', t.updated_by, 'updated_at', t.updated_at) FROM {table} t ORDER BY t.id DESC LIMIT {limit}""", rows=True)
    lines = release._psql(site().db, f"SELECT to_json(table_name) FROM information_schema.tables WHERE table_schema = current_schema() AND left(table_name, {len(table) + 2}) = '{table}__'", rows=True)
    return {'key': key, 'table': table, 'line_tables': lines, 'total': total, 'rows': rows}


def server_log(lines=300):
    """The last lines the project's development server wrote (what it refused, what failed)."""
    lines = max(10, min(2000, int(lines)))
    done = subprocess.run(['docker', 'logs', '--tail', str(lines), site().api_container], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=30)
    text = done.stdout if done.returncode == 0 else f'서버 기록을 읽지 못했습니다: {done.stdout[-300:]}'
    state = subprocess.run(['docker', 'inspect', '-f', '{{.State.Status}} (시작 {{.State.StartedAt}})', site().api_container], capture_output=True, text=True, timeout=15).stdout.strip()
    return {'container': site().api_container, 'state': state, 'url': site().api_url, 'database': site().db, 'lines': text.splitlines()[-lines:]}


def process():
    """The project's processes as its framework reads them off the screen definitions (the 업무 안내서): flows, master data by layer,
    every screen in sentences. The same text the model reads before it makes or changes a screen."""
    _harness()
    from framework import Framework
    return Framework().ok('GET', '/api/meta/process')


def graph():
    """The screens as one graph (GET /api/meta/graph): entities with their states and steps, and how later ones come of earlier ones."""
    _harness()
    from framework import Framework
    return Framework().ok('GET', '/api/meta/graph')


def made(project, sha):
    """What a definition change made in the running system, screen by screen: its tables and their columns (the fields this change
    added marked), the API addresses it answers on, its program and where it sits in the menus, the code groups it declares. Read
    from the commit (which screens it touched) and the development database as it is now."""
    names = subprocess.run(['git', 'show', '--format=', '--name-status', sha], cwd=project, capture_output=True, text=True, timeout=60).stdout.splitlines()
    out = []
    for line in names:
        parts = line.split('\t')
        if len(parts) < 2 or not parts[-1].startswith('release/definitions/') or not parts[-1].endswith('.json'):
            continue
        key = Path(parts[-1]).stem
        status = {'A': '새로 만듦', 'D': '지움'}.get(parts[0][:1], '고침')
        after = _at(project, key, sha)
        parent = subprocess.run(['git', 'rev-parse', '--verify', '--quiet', sha + '^'], cwd=project, capture_output=True, text=True).stdout.strip()
        before = _at(project, key, parent) if status != '새로 만듦' and parent else None
        screen = {'key': key, 'title': (after or before or {}).get('title', key), 'change': status}
        if after:
            def names_of(definition):
                found = {field['name'] for field in definition.get('fields') or []}
                for lines in [definition.get('lines')] + list(definition.get('moreLines') or []):
                    found |= {field['name'] for field in (lines or {}).get('fields') or []}
                return found
            added = names_of(after) - (names_of(before) if before else set())
            tables = release._psql(site().db, f"""SELECT json_build_object('table', c.table_name, 'columns', json_agg(json_build_object('name', c.column_name, 'type', c.data_type) ORDER BY c.ordinal_position))
                FROM information_schema.columns c WHERE c.table_schema = current_schema() AND (c.table_name = 'r_{key}' OR c.table_name LIKE 'r\\_{key}\\_\\_%' OR c.table_name = 'h_{key}')
                GROUP BY c.table_name ORDER BY c.table_name""", rows=True)
            for table in tables:
                for column in table['columns']:
                    column['added'] = column['name'].startswith('f_') and _camel(column['name'][2:]) in added
            screen['tables'] = tables
            kind = next((part for part in ('over', 'take', 'summary', 'calendar', 'tree', 'dashboard', 'ledgerView') if after.get(part)), None)
            base = {'over': '/api/over/', 'take': '/api/take/', 'summary': '/api/summary/', 'calendar': '/api/calendar/', 'tree': '/api/tree/'}.get(kind, '/api/data/')
            api = [f'GET {base}{key}', f'GET {base}{key}/{{id}}'] if base == '/api/data/' else [f'GET {base}{key}']
            if base == '/api/data/':
                api += [f'POST {base}{key}', f'PUT {base}{key}/{{id}}', f'DELETE {base}{key}/{{id}}', f'GET {base}{key}/{{id}}/history']
                api += [f"POST {base}{key}/{{id}}/actions/{action['name']}  ({action.get('label', '')})" for action in ((after.get('status') or {}).get('actions') or [])]
            elif kind in ('over', 'take'):
                api += [f'POST {base}{key}']
            screen['api'] = api
            program = release._psql(site().db, f"""SELECT json_build_object('code', p.program_code, 'name', p.program_name, 'menu',
                (SELECT string_agg(COALESCE(parent.menu_name || ' › ', '') || m.menu_name, ', ') FROM sys_menus m LEFT JOIN sys_menus parent ON parent.menu_id = m.parent_id WHERE m.program_code = p.program_code))
                FROM sys_programs p JOIN app_definitions d ON d.program_code = p.program_code WHERE d.entity_key = '{key}'""", rows=True)
            screen['program'] = program[0] if program else None
            screen['codeGroups'] = [f"{group.get('name')} ({group.get('code')}): " + ', '.join(value.get('name', '') for value in group.get('values') or []) for group in after.get('codeGroups') or []]
        out.append(screen)
    return {'screens': out}


def _camel(snake):
    head, *rest = snake.split('_')
    return head + ''.join(part[:1].upper() + part[1:] for part in rest)
