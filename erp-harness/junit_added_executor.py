import time
import shutil
from pathlib import Path
from xml.etree import ElementTree as ET
from junit_added_spec import validate_spec

def verify(checker, criteria, baseline, output_dir):
    root = Path(checker.workspace.root).resolve()
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    
    started = time.time()
    run_result = checker.run_check('backend')
    
    results = []
    
    if run_result.get('success') is not True:
        import test_feedback
        return {'success': False, 'results': [{'id': c['id'], 'status': 'failed', 'reason': test_feedback.feedback(root, 'backend', run_result, started), 'evidence': None or {}} for c in criteria]}

    for c in criteria:
        c_id = c['id']
        chk = c['check']
        try:
            validate_spec(chk)
        except Exception as e:
            results.append({'id': c_id, 'status': 'unverified', 'reason': f'Spec error: {str(e)}'})
            continue

        suite = chk['suite']
        count_req = chk['count']
        preserve_main = chk.get('preserve_main', False)
        
        # Path logic
        suite_path_str = suite.replace('.', '/') + '.java'
        src_file = root / 'backend' / 'src' / 'test' / 'java' / suite_path_str
        report_file = root / 'backend' / 'target' / 'surefire-reports' / f'TEST-{suite}.xml'

        # Security/Constraint Guards
        def is_safe(p):
            try:
                current = root
                parts = p.relative_to(root).parts
                for part in parts:
                    current = current / part
                    if current.exists() and current.is_symlink():
                        raise ValueError('Symlink detected in path hierarchy')
                return p.resolve().is_relative_to(root)
            except Exception: return False

        if not is_safe(src_file):
            results.append({'id': c_id, 'status': 'unverified', 'reason': 'Unsafe source path'})
            continue
        if not src_file.exists():
            results.append({'id': c_id, 'status': 'unverified', 'reason': 'Missing source file'})
            continue
        if src_file.stat().st_size > 1024 * 1024:
            results.append({'id': c_id, 'status': 'unverified', 'reason': 'Oversized source'})
            continue
        
        if not is_safe(report_file):
            results.append({'id': c_id, 'status': 'unverified', 'reason': 'Unsafe report path'})
            continue
        if not report_file.exists():
            results.append({'id': c_id, 'status': 'unverified', 'reason': 'Missing report file'})
            continue
        if report_file.stat().st_size > 5 * 1024 * 1024:
            results.append({'id': c_id, 'status': 'unverified', 'reason': 'Oversized report'})
            continue

        if report_file.stat().st_mtime < (started - 2):
            results.append({'id': c_id, 'status': 'unverified', 'reason': 'Stale report'})
            continue

        # Baseline lookup
        b_suites = baseline.get('suites', {})
        if suite not in b_suites:
            b_suite_data = {'executed': 0, 'source_hash': None}
        else:
            b_suite_data = b_suites[suite]

        if not isinstance(b_suite_data, dict):
            results.append({'id': c_id, 'status': 'unverified', 'reason': 'Malformed baseline'})
            continue

        b_exec = b_suite_data.get('executed')
        b_src_hash = b_suite_data.get('source_hash')
        if b_exec is None:
            results.append({'id': c_id, 'status': 'unverified', 'reason': 'Unknown executed count'})
            continue

        # Hash and Main check
        from junit_added_gate import _get_hash, capture_baseline
        current_src_hash = _get_hash(src_file)
        src_changed = current_src_hash != b_src_hash

        main_ok = True
        if preserve_main:
            current_baseline = capture_baseline(root)
            if current_baseline['main_hashes'] != baseline.get('main_hashes', {}):
                main_ok = False

        # XML Parsing
        try:
            tree = ET.parse(report_file)
            root_xml = tree.getroot()
            if root_xml.tag != 'testsuite' or root_xml.attrib.get('name') != suite:
                raise ValueError("XML mismatch")
            
            exec_count = 0
            skip_count = 0
            fail_count = 0
            err_count = 0
            
            for tc in root_xml.findall('.//testcase'):
                if tc.find('skipped') is not None:
                    skip_count += 1
                else:
                    exec_count += 1
                    if tc.find('failure') is not None: fail_count += 1
                    if tc.find('error') is not None: err_count += 1
            
            # Validation Logic
            passed = (exec_count >= b_exec + count_req and 
                      fail_count == 0 and err_count == 0 and 
                      src_changed and main_ok)
            
            reason = ""
            if not passed:
                if not src_changed: reason += "source unchanged; "
                if not main_ok: reason += "main changed; "
                if exec_count < b_exec + count_req: reason += f"exec {exec_count}<{b_exec+count_req}; "
                if fail_count > 0 or err_count > 0: reason += f"failures/errors: {fail_count+err_count}; "

            status = 'passed' if passed else 'failed'
            
            evidence_path = out_path / report_file.name
            shutil.copy2(report_file, evidence_path)

            results.append({
                'id': c_id,
                'status': status,
                'reason': reason.strip(),
                'evidence': {
                    'transport': 'maven-junit-surefire',
                    'baseline_tests': b_exec,
                    'executed': exec_count,
                    'added_tests': exec_count - b_exec,
                    'required_added': count_req,
                    'skipped': skip_count,
                    'source_changed': src_changed,
                    'report': str(evidence_path)
                }
            })
        except Exception as e:
            results.append({'id': c_id, 'status': 'unverified', 'reason': f'Parse error: {str(e)}'})

    return {'success': all(r['status'] == 'passed' for r in results) and len(results) > 0, 'results': results}
