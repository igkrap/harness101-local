"""One real DB/API/browser proof of a framework-only screen, without LLM calls."""
import copy
import hashlib
import json
import pathlib
import sys
import time
import uuid
from .contracts import canonical, digest, require
from .store import ROOT, Store, literal
from .checks import Api, command, package, probe, verify_api


def source_hashes():
    paths = list((ROOT/'platform/spec_workshop').glob('*.py'))+[ROOT/'platform/tests/browser_generated_spec.cjs',ROOT/'local-only/frontend/src/App.tsx']
    paths += [p for p in (ROOT/'local-only/frontend/src/framework').rglob('*') if p.is_file()]
    paths += list((ROOT/'local-only/backend/src/main/java/com/example/localinventory/framework').rglob('*.java'))
    return {str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def verify(code='ZDE0001', revision=1, database='mdi_local'):
    require(code=='ZDE0001' and revision==1,'Independent business oracle currently targets demo ZDE0001@1')
    store=Store(database);bundle=store.load(code,revision)
    run_id=uuid.uuid4().hex;out=ROOT/'platform/state/spec-validations'/run_id;out.mkdir(parents=True)
    before=source_hashes();started=time.time()
    def save(name,value): (out/name).write_text(json.dumps(value,ensure_ascii=False,indent=2))
    save('manifest.json',{'id':run_id,'executor':'framework-only','modelCalls':0,'specSha256':digest(bundle),'sources':before})
    save('bundle.json',bundle)
    store.sql(f"INSERT INTO development_validation_runs(run_id,screen_code,revision,spec_sha256,executor,status) VALUES ({literal(run_id)},{literal(code)},{revision},{literal(digest(bundle))},'framework-only','running');")
    result={'id':run_id,'status':'running','modelCalls':0};save('progress.json',result)
    try:
        command(['npm','run','build'],out/'frontend-build.log',cwd=ROOT/'local-only/frontend')
        jar=package(out/'backend-package.log')
        with probe(jar,out) as instance:
            isolated=Store(instance['database']);isolated.initialize();isolated.release(bundle,1);isolated.activate(code,1,provision=True)
            result['api']=verify_api(bundle,instance);save('api-report.json',result['api']);save('progress.json',result)
            command(['node',str(ROOT/'platform/tests/browser_generated_spec.cjs'),str(out/'bundle.json'),instance['base'],str(out)],out/'browser.log')
            # Change only DB definitions: title, optional query section, editor-tab label.
            changed=copy.deepcopy(bundle);changed['screen']['title']+=' · DB 변경';changed['screen']['editorTabs'][0]['label']='DB에서 변경한 정보'
            changed['operations']['query']['inputs'][1]['section']='advanced'
            isolated.release(changed,2);isolated.activate(code,2)
            api=Api(instance['base']);api.login();api.revision=1
            status,_=api.request('/api/screens/'+code+'/records','POST',{'displayName':'stale','department':'stale','email':'stale@example.invalid','quota':0})
            require(status==409,'Stale screen revision must not write against a newer definition')
            result['staleRevisionRejected']=True
            save('bundle-revision-2.json',changed)
            command(['node',str(ROOT/'platform/tests/browser_generated_spec.cjs'),str(out/'bundle-revision-2.json'),instance['base'],str(out),'--metadata-only'],out/'db-change-browser.log')
            require(digest(isolated.load(code,1))==digest(bundle),'Old release changed')
            try: isolated.put('entity',bundle['entity']['id'],1,dict(bundle['entity'],table='spec_changed'))
            except ValueError: result['immutableRevisionRejected']=True
            else: raise AssertionError('Existing document revision was overwritten')
        require(before==source_hashes(),'Source changed during DB-only validation')
        require(not (ROOT/f'local-only/frontend/src/screens/{code}.tsx').exists(),'Per-screen frontend source unexpectedly exists')
        require(not (ROOT/f'local-only/backend/src/main/java/com/example/localinventory/generated/{code}Controller.java').exists(),'Per-screen backend source unexpectedly exists')
        result.update(status='succeeded',sourceChanges=0,perScreenSourceFiles=0,dbOnlyChangesVerified=True,artifact=str(out/'app.jar'),artifactSha256=hashlib.sha256((out/'app.jar').read_bytes()).hexdigest())
    except BaseException as error:
        result.update(status='failed',error=str(error))
    result['elapsedSeconds']=round(time.time()-started);save('result.json',result);save('progress.json',result)
    store.sql(f"UPDATE development_validation_runs SET status={literal(result['status'])},evidence={literal(canonical(result))}::jsonb WHERE run_id={literal(run_id)};")
    print(canonical(result),flush=True)
    return result
