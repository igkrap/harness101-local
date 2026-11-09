import sys
from pathlib import Path
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'local-only/harness'))
from java_methods import method_arguments


class JavaMethodsTests(unittest.TestCase):
    source='package demo;\nclass T {\n String text="한글😀}";\n String json="""\n {"brace":"}"}\n """;\n @Deprecated void original() {}\n}\nrecord R(int x) {}\n'

    def call(self,code,**extra):
        return method_arguments({'path':'backend/src/test/java/demo/T.java','code':code,**extra},self.source)

    def test_jdk_ast_inserts_inside_selected_class_preserving_unicode_textblocks_and_other_types(self):
        code='@Deprecated void added() { String literal="}"; }\nvoid second() {}'
        result=self.call(code)
        self.assertEqual(result['old_text'],self.source)
        self.assertEqual(result['new_text'].replace('\n'+code+'\n','',1),self.source)
        self.assertLess(result['new_text'].index('void added'),result['new_text'].index('record R'))
        self.assertIn('void second() {}\n}\nrecord R',result['new_text'])

    def test_mixed_fields_classes_constructors_and_wrapper_escapes_are_rejected(self):
        for code in ('void ok() {} int field;','void ok() {} class Inner {}','__MemberProbe__() {}','void ok() {} } class Escape { void escaped() {}'):
            with self.subTest(code=code),self.assertRaises(ValueError):self.call(code)

    def test_duplicate_methods_are_rejected_and_legitimate_overloads_allowed(self):
        for code in ('void original() {}','void added() {} void added() {}'):
            with self.assertRaisesRegex(ValueError,'[Dd]uplicate'):self.call(code)
        self.assertIn('original(int',self.call('void original(int value) {}')['new_text'])

    def test_syntax_errors_and_missing_class_have_actionable_diagnostics(self):
        with self.assertRaises(ValueError)as caught:self.call('void broken( {')
        self.assertGreater(len(str(caught.exception)),20)
        with self.assertRaises(ValueError):self.call('void added() {}',class_name='Missing')

    def test_path_and_shared_size_bounds_are_enforced(self):
        for path in ('/tmp/T.java','backend/src/../../T.java','frontend/src/T.java'):
            with self.assertRaises(ValueError):method_arguments({'path':path,'code':'void x(){}'},self.source)
        from edit_limits import MAX_SOURCE_CHARS
        with self.assertRaises(ValueError):method_arguments({'path':'backend/src/T.java','code':'void x(){}'},'x'*(MAX_SOURCE_CHARS+1))
