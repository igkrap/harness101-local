"""Create (or re-key) the platform's own sign-in for checking screens.

The app allows one live session per account, so the checker must not share the administrator's
account with the person using the app. This makes a separate administrator-level account
("verifier") in the live DB with a random password and keeps it in state/auth/verifier-login.json
(0600). The password never appears in argv, logs or output.
"""
import json
import os
import secrets
import subprocess
from pathlib import Path

USERNAME = 'verifier'
DISPLAY = '화면 검증 전용 (플랫폼)'
DB = ['docker', 'exec', '-i', 'mdi-db', 'psql', '-U', 'mdi', '-d', 'mdi_local', '-v', 'ON_ERROR_STOP=1', '-q']


def provision(rotate=False):
    folder = Path(__file__).resolve().parent / 'state/auth'
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    target = folder / 'verifier-login.json'
    if target.is_file() and not rotate:
        return {'username': json.loads(target.read_text())['username'], 'credentials': str(target), 'created': False}
    password = secrets.token_urlsafe(24)
    literal = "'" + password.replace("'", "''") + "'"  # token_urlsafe has no quotes; kept safe anyway
    sql = f"""
CREATE EXTENSION IF NOT EXISTS pgcrypto;
INSERT INTO workspace_users (username, password_hash, display_name, permissions, enabled, status)
SELECT '{USERNAME}', '{{bcrypt}}' || crypt({literal}, gen_salt('bf', 10)), '{DISPLAY}', permissions, TRUE, 'ACTIVE'
  FROM workspace_users WHERE username = 'admin'
ON CONFLICT (username) DO UPDATE SET password_hash = EXCLUDED.password_hash, enabled = TRUE, status = 'ACTIVE';
INSERT INTO sys_user_roles (username, role_code) VALUES ('{USERNAME}', 'ADMIN') ON CONFLICT DO NOTHING;
"""
    result = subprocess.run(DB, input=sql, capture_output=True, text=True, timeout=60)  # SQL goes through stdin, not argv
    if result.returncode != 0:
        raise RuntimeError('검증 전용 계정을 만들지 못했습니다: ' + result.stderr.replace(password, '***')[-400:])
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, 'w') as out:
        json.dump({'username': USERNAME, 'password': password}, out)
    target.chmod(0o600)
    return {'username': USERNAME, 'credentials': str(target), 'created': True}


if __name__ == '__main__':
    import sys
    print(json.dumps(provision(rotate='--rotate' in sys.argv), ensure_ascii=False))
