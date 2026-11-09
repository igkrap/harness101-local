from pathlib import Path
import sys, unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[2]/'local-only/harness'))
from test_isolation import isolation_arguments

class SpringIsolationTests(unittest.TestCase):
 def setUp(self):
  self.current='import working.Valid;\n@SpringBootTest\nclass Fixture {\n @Test void existing() { assertTrue(true); }\n}\n'
  self.path='backend/src/test/java/Fixture.java'
 def test_scoped_sql_keeps_original_test_and_imports(self):
  sql="DELETE FROM inventory WHERE category = '테스트'"
  patch=isolation_arguments({'path':self.path,'cleanup_sql':sql},self.current)
  updated=self.current.replace(patch['old_text'],patch['new_text'])
  self.assertIn('import working.Valid;',updated);self.assertIn('@Test void existing() { assertTrue(true); }',updated)
  self.assertIn('@org.springframework.transaction.annotation.Transactional',updated)
  self.assertIn('statements = "'+sql+'"',updated);self.assertNotIn('\\"',updated)
 def test_one_terminal_semicolon_is_accepted(self):
  patch=isolation_arguments({'path':self.path,'cleanup_sql':" DELETE FROM inventory WHERE id > 6; "},self.current)
  self.assertIn('statements = "DELETE FROM inventory WHERE id > 6"',patch['new_text'])
 def test_quoted_predicate_is_encoded_once(self):
  sql='DELETE FROM inventory WHERE name = \'a"b\''
  patch=isolation_arguments({'path':self.path,'cleanup_sql':sql},self.current)
  self.assertIn('a\\"b',patch['new_text'])
 def test_unscoped_or_multiple_statements_are_rejected(self):
  for sql in ['DELETE FROM inventory','TRUNCATE inventory','DELETE FROM inventory WHERE 1=1','DELETE FROM inventory WHERE TRUE','DELETE FROM inventory WHERE name=\'x\'; DROP TABLE inventory','INSERT INTO inventory VALUES (1)']:
   with self.subTest(sql=sql),self.assertRaises(ValueError):isolation_arguments({'path':self.path,'cleanup_sql':sql},self.current)
 def test_requires_spring_java_test(self):
  for path,current in [('app.tsx',self.current),(self.path,'class Fixture {}')]:
   with self.assertRaises(ValueError):isolation_arguments({'path':path,'cleanup_sql':"DELETE FROM inventory WHERE category='테스트'"},current)
