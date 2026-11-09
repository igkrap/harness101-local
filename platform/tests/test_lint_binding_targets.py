import sys
import unittest
from pathlib import Path
from copy import deepcopy

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'local-only/harness'))


class LintBindingTargetTests(unittest.TestCase):
    def setUp(self):
        self.path = 'frontend/src/Screen.tsx'
        self.error = self.path + ":50:9 error @typescript-eslint/no-unused-vars 'handleSubmit' is assigned a value but never used."
        self.catalog = [
            {'id': 'n1', 'kind': 'VariableStatement', 'label': 'Screen 50:68 body statement [bindings: handleSubmit]', 'source': 'const handleSubmit = () => 1;'},
            {'id': 'n2', 'kind': 'JsxElement', 'label': 'Screen return JSX', 'source': '<form onSubmit={handleSaveSubmit}/>'},
            {'id': 'n3', 'kind': 'VariableStatement', 'label': 'Screen body statement [bindings: [count, setCount]]', 'source': 'const [count, setCount] = useState(0);'},
        ]

    def test_exact_existing_declaration_is_identified_without_mutation(self):
        from lint_binding_targets import unused_binding_targets
        original = deepcopy(self.catalog)
        ids, hint = unused_binding_targets(self.path, self.error, self.catalog)
        self.assertEqual(ids, ['n1'])
        self.assertIn('n1', hint)
        self.assertIn('handleSubmit', hint)
        self.assertEqual(self.catalog, original)

    def test_destructured_binding_and_duplicate_errors(self):
        from lint_binding_targets import unused_binding_targets
        error = self.error.replace('handleSubmit', 'setCount')
        ids, _ = unused_binding_targets(self.path, error + '\n' + error, self.catalog)
        self.assertEqual(ids, ['n3'])

    def test_unrelated_diagnostics_and_source_mentions_do_not_create_targets(self):
        from lint_binding_targets import unused_binding_targets
        for error in (self.error.replace('Screen.tsx', 'Other.tsx'), self.error.replace(' error ', ' warning '), self.error.replace('handleSubmit', 'handleSaveSubmit'), "handleSubmit is unused", self.error.replace('no-unused-vars', 'no-unsafe-call')):
            self.assertEqual(unused_binding_targets(self.path, error, self.catalog), ([], ''), error)

    def test_ambiguous_bindings_are_not_guessed(self):
        from lint_binding_targets import unused_binding_targets
        self.catalog.append(dict(self.catalog[0], id='n9'))
        self.assertEqual(unused_binding_targets(self.path, self.error, self.catalog), ([], ''))

    def test_absolute_compiler_path_and_frontend_prefix(self):
        from lint_binding_targets import unused_binding_targets
        ids, _ = unused_binding_targets(self.path, '[frontend] /project/' + self.error, self.catalog)
        self.assertEqual(ids, ['n1'])

    def test_actual_eslint_explanation_suffix_and_relative_frontend_prefix(self):
        from lint_binding_targets import unused_binding_targets
        error = self.error + ' Allowed unused vars must match /^_/u.'
        for text in (error, '[frontend] ' + error):
            ids, _ = unused_binding_targets(self.path, text, self.catalog)
            self.assertEqual(ids, ['n1'])


if __name__ == '__main__':
    unittest.main()
