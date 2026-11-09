from pathlib import Path
import sys,tempfile,time,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'local-only/harness'))
from test_feedback import feedback
class FeedbackTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.reports=self.root/'backend/target/surefire-reports';self.reports.mkdir(parents=True)
 def tearDown(self):self.tmp.cleanup()
 def write(self,message):
  import xml.etree.ElementTree as ET
  r=ET.Element('testsuite',tests='5',failures='1',errors='0',skipped='0');c=ET.SubElement(r,'testcase',classname='InventoryTest',name='seedList');ET.SubElement(c,'failure',message=message).text='real failure stack';ET.SubElement(r,'system-out').text='noise Error message = null';ET.ElementTree(r).write(self.reports/'TEST-InventoryTest.xml')
 def test_real_junit_failure_precedes_expected_validation_noise(self):
  self.write('expected 6 but was 20');noise=(' WARN validation error expected400 Error message = null\n')*300
  text=feedback(self.root,'backend',{'success':False,'stdout':noise+'[ERROR] tests failed','stderr':''},time.time()-1)
  self.assertIn('expected 6 but was 20',text[:800]);self.assertLessEqual(len(text),5000)
 def test_compiler_error_does_not_use_old_test_failure(self):
  self.write('old missing file');text=feedback(self.root,'backend',{'success':False,'stdout':'[ERROR] COMPILATION ERROR\n[ERROR] cannot find symbol Transactional','stderr':''},time.time()-1)
  self.assertIn('cannot find symbol',text);self.assertNotIn('old missing file',text)
 def test_missing_resource_is_reported_explicitly(self):
  self.write('Cannot read SQL script test-data.sql');text=feedback(self.root,'backend',{'success':False,'stdout':'[ERROR] test error','stderr':''},time.time()-1);self.assertIn('Cannot read SQL script test-data.sql',text)
 def test_typescript_source_error_precedes_build_noise(self):
  output='src/screens/Registration.tsx(12,3): error TS2322: unsupported prop\n'+('build detail\n'*100)
  text=feedback(self.root,'frontend',{'success':False,'stdout':output,'stderr':''},time.time())
  self.assertIn('error TS2322',text[:500])

 def test_deep_sql_cause_survives_large_context_dump(self):
  import xml.etree.ElementTree as ET
  suite=ET.Element('testsuite');case=ET.SubElement(suite,'testcase',classname='InventoryTest',name='context')
  node=ET.SubElement(case,'error',message='Failed to load ApplicationContext '+('contextCustomizers noise '*1000))
  node.text='Caused by: FlywayMigrationException\nSQL State  : 42P07\nMessage    : relation inventory already exists\nCaused by: org.postgresql.util.PSQLException: ERROR: relation inventory already exists'
  ET.ElementTree(suite).write(self.reports/'TEST-Sql.xml')
  text=feedback(self.root,'backend',{'success':False,'stdout':'large build output','stderr':''},time.time()-1)
  self.assertIn('PSQLException',text[:300]);self.assertIn('relation inventory already exists',text[:400]);self.assertLessEqual(len(text),5000)
