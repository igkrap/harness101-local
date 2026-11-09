import json
from pathlib import Path
import subprocess
import unittest


class InspectorStdoutTests(unittest.TestCase):
    def test_cli_flushes_large_success_failure_and_parse_error_reports(self):
        inspector = Path(__file__).resolve().parents[2] / 'local-only/harness/react_layout_inspector.cjs'
        source = inspector.read_text()
        entry = source[source.index('if (require.main === module) {'):source.index('\nmodule.exports =')]
        # Execute the actual entrypoint against deterministic large reports.
        program = 'async function verify(input) { return {...input, payload: "x".repeat(262144)}; }\n' + entry
        for success in (True, False):
            result = subprocess.run(['node', '-e', 'module = require.main = {};\n' + program],
                                    input=json.dumps({'success': success}), capture_output=True, text=True, timeout=10)
            report = json.loads(result.stdout)
            self.assertEqual(result.returncode, 0 if success else 1)
            self.assertEqual(report['payload'], 'x' * 262144)
        result = subprocess.run(['node', '-e', 'module = require.main = {};\n' + program],
                                input='{', capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 1)
        self.assertFalse(json.loads(result.stdout)['success'])
