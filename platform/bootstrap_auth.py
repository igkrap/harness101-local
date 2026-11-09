"""Create a private local administrator credential and a BCrypt-only server env file."""
import json
import os
from pathlib import Path
import re
import subprocess


def provision():
    folder = Path(__file__).resolve().parent / 'state/auth'
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    folder.chmod(0o700)
    credentials = folder / 'local-login.json'
    server = folder / 'server.env'
    if credentials.is_file() and server.is_file():
        return {'username': json.loads(credentials.read_text())['username'], 'credentials': str(credentials), 'server_env': str(server)}
    account = {'username': 'admin', 'password': 'admin'}
    process_env = dict(os.environ, WORKSPACE_NEW_PASSWORD=account['password'])
    script = 'System.out.println("HASH=" + org.springframework.security.crypto.bcrypt.BCrypt.hashpw(System.getenv("WORKSPACE_NEW_PASSWORD"), org.springframework.security.crypto.bcrypt.BCrypt.gensalt(12)));\n/exit\n'
    result = subprocess.run(['docker', 'run', '--rm', '-i', '-e', 'WORKSPACE_NEW_PASSWORD', '-v', 'mdi-m2:/root/.m2:ro',
        'maven:3.9-eclipse-temurin-17', 'jshell', '--class-path', '/root/.m2/repository/org/springframework/security/spring-security-crypto/7.1.2/spring-security-crypto-7.1.2.jar'],
        input=script, text=True, capture_output=True, env=process_env, timeout=40)
    match = re.search(r'HASH=(\$2[aby]\$\d\d\$[./A-Za-z0-9]{53})', result.stdout)
    if result.returncode or not match:
        raise RuntimeError('Could not generate the administrator password hash; no credentials were stored')
    for path, content in [(credentials, json.dumps(account, indent=2) + '\n'),
                          (server, 'WORKSPACE_ADMIN_USERNAME=' + account['username'] + '\nWORKSPACE_ADMIN_PASSWORD_HASH={bcrypt}' + match[1] + '\n')]:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, 'w') as stream:
            stream.write(content)
    return {'username': account['username'], 'credentials': str(credentials), 'server_env': str(server)}


if __name__ == '__main__':
    print(json.dumps(provision(), ensure_ascii=False))
