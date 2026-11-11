"""Backend conventions checked before the (slow) build: plain answers the model can act on.

Every business entity extends AuditedEntity, and then its table must have the four who/when
columns. Copying an older migration without them compiles and only fails on the first insert,
so this names the table and the missing columns up front.
"""
import re
from pathlib import Path

AUDIT_COLUMNS = ('created_by', 'created_at', 'updated_by', 'updated_at')
JAVA = 'backend/src/main/java'
MIGRATIONS = 'backend/src/main/resources/db/migration'


def _table_columns(sql, table):
    """Lower-case text of every statement that defines columns of table (CREATE TABLE / ALTER TABLE ... ADD)."""
    name = re.escape(table)
    found = []
    for match in re.finditer(r'CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?"?' + name + r'"?\s*\((.*?)\)\s*;', sql, re.I | re.S):
        found.append(match.group(1))
    for match in re.finditer(r'ALTER\s+TABLE\s+(?:IF\s+EXISTS\s+)?"?' + name + r'"?\s+(.*?);', sql, re.I | re.S):
        found.append(match.group(1))
    return '\n'.join(found).lower()


def violations(root):
    root = Path(root)
    sql = '\n'.join(path.read_text(encoding='utf-8', errors='replace')
                    for path in sorted((root / MIGRATIONS).glob('V*.sql')))
    problems = []
    for path in sorted((root / JAVA).rglob('*.java')):
        if '/framework/' in path.as_posix():
            continue
        source = path.read_text(encoding='utf-8', errors='replace')
        if not re.search(r'^\s*@Entity\b', source, re.M) or not re.search(r'\bextends\s+(?:[\w.]+\.)?AuditedEntity\b', source):
            continue
        table = re.search(r'@Table\s*\(\s*name\s*=\s*"([^"]+)"', source)
        if not table:
            continue
        columns = _table_columns(sql, table.group(1))
        if not columns:
            problems.append(f'{path.name}: 테이블 {table.group(1)}을(를) 만드는 마이그레이션(CREATE TABLE {table.group(1)})이 없습니다.')
            continue
        missing = [column for column in AUDIT_COLUMNS if not re.search(r'\b' + column + r'\b', columns)]
        if missing:
            problems.append(f'{path.name}: 테이블 {table.group(1)}에 등록/수정자 열이 없습니다: {", ".join(missing)}. '
                            f'이 테이블을 만드는 새 마이그레이션의 CREATE TABLE 안에 '
                            'created_by VARCHAR(100), created_at TIMESTAMP, updated_by VARCHAR(100), updated_at TIMESTAMP 를 넣으세요.')
    return problems


def check(root):
    """None when fine; otherwise a checker result in the shape Checker._exec returns."""
    problems = violations(root)
    if not problems:
        return None
    return {'success': False, 'stdout': '', 'returncode': 1,
            'stderr': 'BACKEND CONVENTION (빌드 전에 확인됨):\n' + '\n'.join('- ' + problem for problem in problems)}
