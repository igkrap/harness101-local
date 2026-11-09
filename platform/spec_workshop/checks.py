import contextlib
import http.cookiejar
import json
import os
import pathlib
import shutil
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from .store import ROOT


def command(args, log, timeout=120, cwd=None):
    result = subprocess.run(args, cwd=cwd or ROOT, text=True, capture_output=True, timeout=timeout)
    log.write_text(result.stdout + result.stderr)
    if result.returncode:
        raise RuntimeError(log.read_text()[-6500:])
    return result.stdout.strip()


def package(log):
    command(['docker','run','--rm','--network','mdi-internal','-v',str(ROOT/'local-only/backend')+':/app','-w','/app',
             '-v','mdi-m2:/root/.m2','maven:3.9-eclipse-temurin-17','mvn','-B','-o','-DskipTests','clean','package'],log)
    artifact = ROOT/'local-only/backend/target/local-inventory-0.0.1-SNAPSHOT.jar'
    if not artifact.is_file():
        raise RuntimeError('Expected packaged backend jar not found')
    return artifact


@contextlib.contextmanager
def probe(jar, folder):
    suffix = uuid.uuid4().hex[:10]
    database, container = 'spec_probe_'+suffix, 'spec-probe-'+suffix
    def docker(*args):
        return subprocess.check_output(['docker',*args],text=True).strip()
    docker('exec','mdi-db','psql','-U','mdi','-d','postgres','-c',f'CREATE DATABASE {database};')
    artifact = folder/'app.jar'; shutil.copyfile(jar,artifact)
    started = False
    try:
        docker('run','-d','--name',container,'--network','mdi-internal','-p','127.0.0.1::8080',
               '--env-file',str(ROOT/'platform/state/auth/server.env'),'-e',f'DB_URL=jdbc:postgresql://mdi-db:5432/{database}',
               '-v',str(artifact)+':/app/app.jar:ro','maven:3.9-eclipse-temurin-17','java','-jar','/app/app.jar')
        started = True
        docker('network','connect','mdi-public',container)
        port = docker('port',container,'8080/tcp').rsplit(':',1)[1]
        base = 'http://127.0.0.1:'+port
        for _ in range(100):
            try:
                with urllib.request.urlopen(base+'/api/auth/session',timeout=2) as response:
                    if json.load(response).get('csrf'): break
            except (OSError,ValueError): time.sleep(.3)
        else:
            raise RuntimeError('Probe did not start: '+docker('logs',container)[-5000:])
        yield {'base':base,'database':database,'container':container}
    finally:
        if started:
            subprocess.run(['docker','rm','-f',container],capture_output=True)
        subprocess.run(['docker','exec','mdi-db','psql','-U','mdi','-d','postgres','-c',f'DROP DATABASE {database} WITH (FORCE);'],capture_output=True)


class Api:
    def __init__(self, base):
        self.base = base
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.csrf = {}
        self.revision = None

    def request(self, path, method='GET', body=None, form=False):
        headers = {'Accept':'application/json'}
        if self.revision is not None and path.startswith('/api/screens/'):
            headers['X-Screen-Revision'] = str(self.revision)
        data = None
        if body is not None:
            headers['Content-Type'] = 'application/x-www-form-urlencoded' if form else 'application/json'
            data = (urllib.parse.urlencode(body) if form else json.dumps(body)).encode()
        if method not in ('GET','HEAD'): headers.update(self.csrf)
        request = urllib.request.Request(self.base+path,data=data,headers=headers,method=method)
        try: response = self.opener.open(request,timeout=10)
        except urllib.error.HTTPError as error: response = error
        with response:
            raw = response.read().decode()
            try: value = json.loads(raw) if raw else None
            except ValueError: value = raw
            return response.status,value

    def login(self, username=None):
        account = json.loads((ROOT/'platform/state/auth/local-login.json').read_text())
        status,session = self.request('/api/auth/session')
        assert status == 200
        self.csrf = {session['csrf']['headerName']:session['csrf']['token']}
        status,_ = self.request('/api/auth/login','POST',{'username':username or account['username'],'password':account['password']},form=True)
        if status != 200: raise AssertionError('Trusted test login HTTP '+str(status))
        _,session = self.request('/api/auth/session'); self.csrf = {session['csrf']['headerName']:session['csrf']['token']}


def verify_api(bundle, instance):
    """Independent contract checks; generated source cannot change this oracle."""
    code = bundle['screen']['code']; path = '/api/screens/'+code+'/records'
    api = Api(instance['base']); cases = []
    def expect(name, expected, method='GET', payload=None, suffix=''):
        status,value = api.request(path+suffix,method,payload)
        if status != expected: raise AssertionError(f'{name}: expected HTTP {expected}, got {status}: {str(value)[:1800]}')
        cases.append(name); return value
    expect('anonymous-denied',401)
    api.login()
    api.revision = 1
    expect('required-query-input',400)
    tag = 'QA-'+uuid.uuid4().hex[:8]
    one = {'displayName':'Alpha '+tag,'department':tag,'email':'alpha@example.invalid','quota':10}
    two = dict(one,displayName='Beta '+tag,email='beta@example.invalid',quota=20)
    other = dict(one,displayName='Other '+tag,department='Elsewhere-'+tag)
    created = expect('create',201,'POST',one)
    if set(created) != set(bundle['operations']['create']['result']): raise AssertionError('Create result keys differ from contract: '+str(created))
    if not isinstance(created['id'],int) or not created['createdAt']: raise AssertionError('Missing server-owned ID/timestamp')
    expect('create-second',201,'POST',two);expect('create-other-department',201,'POST',other)
    def query(**values): return '?'+urllib.parse.urlencode(values)
    rows = expect('department-filter',200,suffix=query(department=tag))
    if len(rows)!=2: raise AssertionError('Required equality filter did not isolate department')
    rows = expect('contains-filter',200,suffix=query(department=tag,name='alpha'))
    if len(rows)!=1 or rows[0]['id']!=created['id']: raise AssertionError('Contains must be case-insensitive literal substring')
    rows = expect('literal-query-input',200,suffix=query(department=tag,name="%' OR 1=1 --"))
    if rows: raise AssertionError('Query parameter was interpreted as SQL/pattern')
    rows = expect('advanced-numeric-filter',200,suffix=query(department=tag,minQuota=15))
    if len(rows)!=1 or rows[0]['quota']!=20: raise AssertionError('Advanced gte filter not applied')
    expect('invalid-query-number',400,suffix=query(department=tag,minQuota='abc'))
    expect('unknown-query-input',400,suffix=query(department=tag,undeclared='value'))
    updated = dict(one,displayName='Updated '+tag,quota=30)
    actual = expect('update',200,'PUT',updated,'/'+str(created['id']))
    for field,value in updated.items():
        if actual[field]!=value: raise AssertionError('Update result differs: '+field)
    if actual['createdAt']!=created['createdAt']: raise AssertionError('Update changed server-owned createdAt')
    expect('missing-update-target',404,'PUT',updated,'/9223372036854775806')
    for name,changes in [('blank-name',{'displayName':''}),('missing-email',{'email':None}),('invalid-email',{'email':'invalid'}),
                         ('negative-integer',{'quota':-1}),('fractional-integer',{'quota':1.5}),('wrong-type',{'quota':True}),
                         ('overlength',{'displayName':'x'*81}),('server-owned-input',{'id':99999})]:
        expect(name,400,'POST',dict(one,**changes))
        expect('update-'+name,400,'PUT',dict(one,**changes),'/'+str(created['id']))
    csrf=api.csrf;api.csrf={}
    expect('csrf-required',403,'POST',one);api.csrf=csrf
    # User with only inventory read permission must not reach generated operations.
    subprocess.run(['docker','exec','mdi-db','psql','-U','mdi','-d',instance['database'],'-v','ON_ERROR_STOP=1','-c',
        "INSERT INTO workspace_users(username,password_hash,display_name,permissions,enabled) SELECT 'spec-reader',password_hash,'reader','inventory:read',true FROM workspace_users LIMIT 1"],check=True,capture_output=True)
    reader = Api(instance['base']);reader.login('spec-reader')
    status,_ = reader.request(path+query(department=tag))
    if status!=403: raise AssertionError('Generated endpoint did not enforce operation permission')
    cases.append('authority-enforced')
    return {'passed':True,'cases':cases,'fixtureDepartment':tag,'resultKeys':bundle['operations']['query']['result']}
