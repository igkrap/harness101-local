from pathlib import Path
import sys,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'local-only/harness'))
from java_annotations import annotation_arguments

class JavaAnnotationTests(unittest.TestCase):
 def test_annotations_are_before_class_without_import_changes(self):
  current='import good.Valid;\n@SpringBootTest\nclass Fixture {\n void test() {}\n}\n'
  a=annotation_arguments({'path':'Fixture.java','annotations':['org.springframework.transaction.annotation.Transactional','org.springframework.test.context.jdbc.Sql(statements = "DELETE FROM items WHERE category=\'test\'")']},current)
  after=current.replace(a['old_text'],a['new_text'],1)
  self.assertTrue(after.startswith('import good.Valid;'));self.assertEqual(after.count('class Fixture {'),1);self.assertIn('@org.springframework.transaction.annotation.Transactional\n',after);self.assertLess(after.index('@org.springframework.transaction'),after.index('class Fixture'));self.assertIn('void test() {}',after)
 def test_ambiguous_or_missing_class_rejected(self):
  for current in ('interface Fixture {}','class A {}\nclass B {}'):
   with self.assertRaises(ValueError):annotation_arguments({'path':'x','annotations':['a.b.C']},current)
 def test_unqualified_duplicate_or_multiline_annotation_rejected(self):
  for annotations in (['Transactional'],['a.b.C\ncode'],['a.b.C','a.b.C']):
   with self.assertRaises(ValueError):annotation_arguments({'path':'x','annotations':annotations},'class A {}')
