"""What the database looks like now, read from the Flyway migrations in order.

Old migration files stay in the repository forever, also for tables that a later migration dropped.
A planner or author that reads V10__create_employees.sql believes the table exists. This says plainly
which tables exist now and which are gone.
"""
import re
from pathlib import Path

MIGRATIONS = 'backend/src/main/resources/db/migration'


def tables(root):
    """(existing, dropped): table -> migration file name that created / dropped it, replayed in version order."""
    existing, dropped = {}, {}
    files = [p for p in (Path(root) / MIGRATIONS).glob('V*.sql') if re.match(r'V\d+__', p.name)]
    for path in sorted(files, key=lambda item: int(re.match(r'V(\d+)', item.name).group(1))):
        sql = re.sub(r'--[^\n]*', '', path.read_text(encoding='utf-8', errors='replace'))
        for match in re.finditer(r'\b(CREATE\s+TABLE(?:\s+IF\s+NOT\s+EXISTS)?|DROP\s+TABLE(?:\s+IF\s+EXISTS)?|ALTER\s+TABLE(?:\s+IF\s+EXISTS)?)\s+"?(\w+)"?(\s+RENAME\s+TO\s+"?(\w+)"?)?',
                                 sql, re.I):
            verb, name, renamed = match.group(1).upper(), match.group(2).lower(), match.group(4)
            if verb.startswith('CREATE'):
                existing[name] = path.name; dropped.pop(name, None)
            elif verb.startswith('DROP'):
                if name in existing:
                    del existing[name]
                dropped[name] = path.name
            elif renamed and name in existing:
                existing[renamed.lower()] = existing.pop(name)
    return existing, dropped


def note(root, business_only=True):
    """One paragraph for a prompt; '' when nothing was ever dropped (then the files tell the truth)."""
    existing, dropped = tables(root)
    if not dropped:
        return ''
    names = sorted(name for name in existing if not (business_only and name.startswith(('sys_', 'development_', 'workspace_', 'flyway_'))))
    gone = ', '.join(f'{name}({created}에서 삭제됨)' for name, created in sorted(dropped.items()))
    return (f"지금 DB에 있는 업무 테이블: {', '.join(names) or '없음'}. 지금은 없는 테이블: {gone}. 지워진 테이블을 만들던 옛 마이그레이션 파일이 "
            '남아 있어도 그 테이블은 없다. 필요하면 새 마이그레이션에서 CREATE TABLE 로 새로 만든다(옛 파일은 읽을 필요도, 따를 필요도 없다).')
