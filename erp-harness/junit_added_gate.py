import os

import hashlib

import xml.etree.ElementTree as ET

import time

import shutil

from typing import Dict, Any, List, Optional, Union, Protocol

DSL_GUIDE = """
junit_added {
    op: 'junit_added',
    suite: fully qualified Java Test Class (e.g., 'com.org.MyTest'),
    count: minimum ADDED executed test count,
    preserve_main?: bool (true for test-only tasks)
}
"""

def _get_hash(path: str) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(65536), b''):
            h.update(chunk)
    return h.hexdigest()

def _count_xml(path: str, suite: str, root_name: str) -> Optional[int]:
    if not os.path.isfile(path) or os.path.islink(path):
        return None
    try:
        tree = ET.parse(path)
        root = tree.getroot()
        if root.tag != 'testsuite' or root.get('name') != root_name:
            return None
        # Check file size via stat if needed, but ET handles parsing
        count = 0
        for tc in root.findall('.//testcase'):
            if tc.find('skipped') is None:
                count += 1
        return count
    except Exception:
        return None

def capture_baseline(root: str) -> Dict[str, Any]:
    baseline = {'suites': {}, 'main_hashes': {}}
    test_root = os.path.join(root, 'backend/src/test/java')
    report_dir = os.path.join(root, 'backend/target/surefire-reports')
    main_root = os.path.join(root, 'backend/src/main')

    if os.path.exists(test_root):
        for dp, _, filenames in os.walk(test_root):
            for f in filenames:
                if f.endswith('.java') and not os.path.islink(os.path.join(dp, f)):
                    full_p = os.path.join(dp, f)
                    if os.path.getsize(full_p) <= 1048576:
                        rel = os.path.relpath(full_p, test_root)
                        suite = rel[:-5].replace(os.sep, '.')
                        exec_count = None
                        if os.path.exists(report_dir):
                            rep_p = os.path.join(report_dir, f"TEST-{suite}.xml")
                            exec_count = _count_xml(rep_p, suite, suite)
                        baseline['suites'][suite] = {'executed': exec_count, 'source_hash': _get_hash(full_p)}

    if os.path.exists(main_root):
        for dp, _, filenames in os.walk(main_root):
            for f in filenames:
                full_p = os.path.join(dp, f)
                if not os.path.islink(full_p) and os.path.getsize(full_p) <= 1048576:
                    baseline['main_hashes'][os.path.relpath(full_p, root)] = _get_hash(full_p)
    return baseline

from junit_added_spec import validate_spec

from junit_added_executor import verify
