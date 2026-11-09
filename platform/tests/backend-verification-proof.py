"""Opt-in integration proof: real MockMvc + disposable PostgreSQL, no production writes."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'local-only/harness'))
from backend_contract_gate import verify


def production_rows():
    with urllib.request.urlopen('http://127.0.0.1:5292/api/inventory', timeout=10) as response:
        return json.load(response)


def databases():
    result = subprocess.run(['docker','exec','mdi-db','psql','-U','mdi','-d','postgres','-At','-c',
                             "SELECT datname FROM pg_database WHERE datname LIKE 'mdi_gate_%' ORDER BY datname"],
                            capture_output=True, text=True, check=True)
    return result.stdout


def criterion(id, **check):
    return {'id':id,'requirement_id':'R1','description':id,'check':{'op':'api',**check}}


def main():
    os.environ['PATH'] = '/Applications/Docker.app/Contents/Resources/bin:' + os.environ.get('PATH','')
    spec = importlib.util.spec_from_file_location('backend_gate_native', ROOT/'local-only/harness/harness.py')
    native = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(native)
    checker = native.Checker(native.WorkspaceManager(ROOT/'local-only'))
    before_rows, before_databases = production_rows(), databases()
    output = ROOT/'platform/state/evidence/backend-contract-proof'
    body = {'name':'Contract proof item','category':'fixture','quantity':2,'minQuantity':1,'unitPrice':100}
    positive = verify(checker, [
        criterion('create',method='POST',path='/api/inventory',status=201,body=body,json_path=['name'],equals=body['name']),
        criterion('readback',method='GET',path='/api/inventory/7',status=200,json_path=['name'],equals=body['name']),
        criterion('missing',method='GET',path='/api/inventory/99999',status=404),
    ], output/'positive')
    negative = verify(checker, [
        criterion('missing-update',method='PUT',path='/api/inventory/1',status=200,body=body,json_path=['name'],equals=body['name']),
    ], output/'negative')
    assert positive['success'] is True, json.dumps(positive, ensure_ascii=False)
    assert all(r['status']=='passed' for r in positive['results']), positive
    assert negative['success'] is False, negative
    assert any(r['id']=='missing-update' and r['status']=='failed' for r in negative['results']), negative
    assert production_rows() == before_rows, 'Production data changed during verification'
    assert databases() == before_databases, 'Disposable database was not cleaned up'
    result={'real_docker_postgres':True,'production_rows_unchanged':True,'test_databases_cleaned':True,
            'positive':positive,'negative':negative}
    output.mkdir(parents=True,exist_ok=True)
    (output/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
    print('PASS: real create/readback/404; missing update rejected; production rows unchanged; disposable databases cleaned')


if __name__=='__main__':main()
