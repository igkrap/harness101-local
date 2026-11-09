import unittest
import test_ast_edits as fixtures


class BindingMetadataTests(unittest.TestCase):
    setUp=fixtures.AstEditTests.setUp
    tearDown=fixtures.AstEditTests.tearDown

    def test_real_ast_names_existing_bindings_without_changing_source_or_scope_roles(self):
        snap=self.editor.snapshot(self.rel)
        labels=[n['label']for n in snap['nodes']if n['kind']=='VariableStatement']
        self.assertTrue(any('bindings: label'in s for s in labels),labels)
        self.assertTrue(any('bindings: [count,setCount]'in s for s in labels),labels)
        meta=next(n for n in snap['nodes']if n['source'].startswith('export const meta'))
        self.assertIn('metadata meta only',meta['label'])
        self.assertIn('bindings: meta',meta['label'])
        self.assertEqual(self.file.read_bytes(),self.original.encode())
