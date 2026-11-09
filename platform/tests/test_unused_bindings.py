"""TypeScript codefix removes only unused, side-effect-free destructured parameter properties."""
import json
from pathlib import Path
import subprocess
import unittest

SCRIPT = Path(__file__).resolve().parents[2] / 'local-only/harness/ast_unused_bindings.cjs'
PROBE = Path(__file__).resolve().parents[2] / 'local-only/frontend/src/framework/__probe__.tsx'


def run(source):
    proc = subprocess.run(['node', str(SCRIPT)], input=json.dumps({'source': source, 'path': str(PROBE)}),
                          capture_output=True, text=True, timeout=60)
    return json.loads(proc.stdout)


class UnusedBindingTests(unittest.TestCase):
    def test_removes_unused_literal_default_and_keeps_side_effect_default(self):
        source = ('type P = { title: string; ratio?: number };\n'
                  'export function W({ title, ratio = 0.6 }: P) { return <div>{title}</div>; }\n'
                  'export function K({ a, b = make() }: { a: string; b?: number }) { return <i>{a}</i>; }\n'
                  'function make() { return 1; }\n')
        result = run(source)
        self.assertEqual(result['removed'], ['ratio'])
        self.assertIn('function W({ title }: P)', result['source'])
        self.assertIn('b = make()', result['source'])

    def test_untouched_when_everything_is_used(self):
        source = 'export function W({ a }: { a: string }) { return <div>{a}</div>; }\n'
        self.assertFalse(run(source)['changed'])


if __name__ == '__main__':
    unittest.main()
