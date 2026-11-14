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
