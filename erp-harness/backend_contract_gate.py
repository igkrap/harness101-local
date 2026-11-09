import os
import re
import uuid
import base64
import shutil
import tempfile
import subprocess
from pathlib import Path
from copy import deepcopy

def verify(checker, criteria, output_dir):
    results = []
    root = checker.workspace.root
    backend_dir = root / 'backend'
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    def create_unverified(reason, evidence=None):
        return {'id': c['id'], 'status': 'unverified', 'reason': reason, 'evidence': evidence or {}}
    if not criteria:
        return {'success': False, 'results': []}
    try:
        pom_path = backend_dir / 'pom.xml'
        if not pom_path.exists():
            raise Exception('backend/pom.xml missing')
        pom_content = pom_path.read_text()
        if not re.search('<version>4\\..*</version>|<dependency>.*webmvc-test.*</dependency>', pom_content):
            raise Exception('SpringBoot 4 or webmvc-test marker not found')
        app_found = False
        (pkg_name, app_class) = ('', '')
        for java_file in backend_dir.glob('src/main/java/**/*.java'):
            content = java_file.read_text()
            if '@SpringBootApplication' in content:
                pkg_match = re.search('package\\s+([\\w\\.]+);', content)
                class_match = re.search('public\\s+class\\s+(\\w+)', content)
                if pkg_match and class_match:
                    pkg_name = pkg_match.group(1)
                    app_class = class_match.group(1)
                    app_found = True
                    break
        if not app_found:
            raise Exception('SpringBootApplication class not found')
        with tempfile.TemporaryDirectory() as tmp_dir:
            scratch = Path(tmp_dir) / 'backend'

            def ignore_func(d, files):
                d = Path(d)
                return [f for f in files if f in ('node_modules', '.git', 'target') or (d / f).is_symlink()]
            shutil.copytree(backend_dir, scratch, ignore=ignore_func, symlinks=False)
            template_path = Path(__file__).with_name('BackendContractTest.java')
            test_dir = scratch / 'src/test/java' / pkg_name.replace('.', '/')
            test_dir.mkdir(parents=True, exist_ok=True)
            test_file = test_dir / 'HarnessContractVerificationTest.java'
            if test_file.exists():
                raise Exception('Collision: Test file already exists')
            java_code = template_path.read_text()
            java_code = java_code.replace('__PACKAGE__', pkg_name).replace('__APPLICATION__', app_class)
            test_file.write_text(java_code)
            nonce = 'HC' + uuid.uuid4().hex
            envelope = {'nonce': nonce, 'criteria': criteria}
            import json
            json_path = scratch / 'verification-contract.json'
            json_path.write_text(json.dumps(envelope))
            from isolated_backend import run_backend

            def callback():
                cmd = ['docker', 'run', '--rm', '--network', 'mdi-internal', '-v', f'{scratch}:/app', '-w', '/app', '-e', 'DB_URL=' + os.environ['HARNESS_TEST_DB_URL'], '-v', 'mdi-m2:/root/.m2', 'maven:3.9-eclipse-temurin-17', 'mvn', '-q', '-B', '-o', '-Dtest=HarnessContractVerificationTest', 'test']
                res = checker._exec(cmd, cwd=str(scratch))
                return res
            run_res = run_backend(checker, callback)
            log_content = ''
            if isinstance(run_res, dict):
                log_content = run_res.get('stdout', '') + run_res.get('stderr', '')
            else:
                log_content = str(run_res)
            (output_path / 'backend_test.log').write_text(log_content)
            shutil.copy(json_path, output_path / 'verification-contract.json')
            shutil.copy(test_file, output_path / 'HarnessContractVerificationTest.java')
            if not run_res or not run_res.get('success', False):
                err_msg = 'backend failure: ' + str(run_res.get('error','')) + log_content[-500:]
                return {'success': False, 'results': [{'id': c['id'], 'status': 'unverified', 'reason': err_msg, 'evidence': None or {}} for c in criteria]}
            marker_map = {}
            seen_ids = set()
            for line in log_content.splitlines():
                if line.startswith(nonce + '|'):
                    parts = line.split('|')
                    if len(parts) == 4:
                        try:
                            cid = base64.b64decode(parts[1]).decode('utf-8')
                            status = parts[2]
                            diag = base64.b64decode(parts[3]).decode('utf-8')
                            if cid in seen_ids:
                                marker_map[cid] = {'status': 'failed', 'reason': 'duplicate id'}
                            else:
                                marker_map[cid] = {'status': status, 'reason': diag}
                                seen_ids.add(cid)
                        except:
                            continue
            final_results = []
            all_passed = True
            for c in criteria:
                cid = c['id']
                if cid in marker_map:
                    m = marker_map[cid]
                    is_pass = m['status'] == 'passed'
                    if not is_pass:
                        all_passed = False
                    final_results.append({'id': cid, 'status': m['status'], 'reason': m['reason'], 'evidence': {'transport': 'spring-mockmvc-isolated-postgres', 'observed': m['reason']}})
                else:
                    all_passed = False
                    final_results.append({'id': c['id'], 'status': 'unverified', 'reason': 'missing marker', 'evidence': None or {}})
            return {'success': all_passed, 'results': final_results}
    except Exception as e:
        err = str(e)
        return {'success': False, 'results': [{'id': c['id'], 'status': 'unverified', 'reason': err, 'evidence': None or {}} for c in criteria]}
