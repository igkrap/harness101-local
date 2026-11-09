"""Reversible deployment of a backend artifact with passing framework evidence."""
import datetime
import hashlib
import json
import pathlib
import shutil
import subprocess
import time
import urllib.request
import uuid
from .contracts import require
from .store import ROOT


def deploy(evidence):
    folder=pathlib.Path(evidence).resolve();result=json.loads((folder/'result.json').read_text());manifest=json.loads((folder/'manifest.json').read_text())
    require(result.get('status')=='succeeded' and result.get('dbOnlyChangesVerified'), 'Passing framework evidence required')
    artifact=folder/'app.jar'
    require(hashlib.sha256(artifact.read_bytes()).hexdigest()==result['artifactSha256'],'Artifact differs from validated binary')
    for relative,stamp in manifest['sources'].items():
        if relative.startswith('local-only/backend/'):
            require(hashlib.sha256((ROOT/relative).read_bytes()).hexdigest()==stamp,'Backend source changed since validation: '+relative)
    def docker(*args): return subprocess.check_output(['docker',*args],text=True).strip()
    old=json.loads(docker('inspect','mdi-local-api'))[0]
    target=pathlib.Path.home()/'.local/share/local-workshop/artifacts/local-only/backend/app-defined-screens.jar'
    # Do not replace a jar mounted by a running JVM; each deployment gets a new path.
    target=target.with_stem(target.stem+'-'+folder.name[:8]+'-'+uuid.uuid4().hex[:6]);shutil.copyfile(artifact,target)
    backup='mdi-local-api-before-defined-'+datetime.datetime.now().strftime('%Y%m%d%H%M%S')
    env=[value for value in old['Config']['Env'] if value.startswith('DB_URL=')]
    if not env: env=['DB_URL=jdbc:postgresql://mdi-db:5432/mdi_local']
    docker('stop','mdi-local-api');docker('rename','mdi-local-api',backup);created=None
    try:
        args=['run','-d','--name','mdi-local-api','--network','mdi-internal','-p','127.0.0.1:8083:8080','--env-file',str(ROOT/'platform/state/auth/server.env'),'-v',str(target)+':/app/app.jar:ro']
        for value in env: args.extend(['-e',value])
        created=docker(*args,old['Image'],'java','-jar','/app/app.jar');docker('network','connect','mdi-public',created)
        for _ in range(100):
            try:
                if json.load(urllib.request.urlopen('http://127.0.0.1:8083/api/auth/session',timeout=2)).get('csrf'):break
            except (OSError,ValueError): time.sleep(.3)
        else: raise RuntimeError('Deployed backend did not become ready')
        report={'container':created,'rollbackContainer':backup,'artifact':str(target),'evidence':str(folder),'port':8083}
        (ROOT/'platform/state/auth/defined-deployment.json').write_text(json.dumps(report,indent=2));return report
    except BaseException:
        if created: docker('rm','-f',created)
        docker('rename',backup,'mdi-local-api');docker('start','mdi-local-api');raise
