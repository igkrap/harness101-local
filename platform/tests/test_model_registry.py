import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from model_registry import ModelRegistry

class ModelRegistryTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.registry=ModelRegistry(self.root,[])
  self.body={'name':'Gemma 26B','model':'local/gemma26','url':'http://127.0.0.1:8099/v1','temperature':.2,'max_tokens':2048,'timeout':90}
 def tearDown(self):self.tmp.cleanup()
 def test_register_edit_reload_delete(self):
  m=self.registry.save(self.body);self.assertEqual(self.registry.get(m['id'])['temperature'],.2)
  self.registry.save({**self.body,'id':m['id'],'name':'Updated','timeout':120})
  restored=ModelRegistry(self.root,[]);self.assertEqual(restored.get(m['id'])['name'],'Updated');self.assertEqual(len(restored.records),1)
  restored.remove(m['id']);self.assertEqual(ModelRegistry(self.root,[]).records,[])
 def test_invalid_settings_do_not_persist(self):
  for field,value in [('url','https://outside.example/v1'),('url','http://user:pass@127.0.0.1:8099/v1'),('model',''),('temperature',float('nan')),('temperature',True),('timeout',0),('timeout',90.1),('max_tokens',999999),('max_tokens',True)]:
   with self.subTest(field=field,value=value),self.assertRaises(ValueError):self.registry.save({**self.body,field:value})
  self.assertEqual(self.registry.records,[])
 def test_test_calls_actual_chat_endpoint(self):
  response=io.BytesIO(json.dumps({'choices':[{'message':{'content':'OK'}}]}).encode())
  with patch('model_registry.urllib.request.urlopen',return_value=response) as send:
   result=self.registry.test(self.body)
  self.assertTrue(result['success']);request=send.call_args.args[0];self.assertEqual(request.full_url,self.body['url']+'/chat/completions');self.assertEqual(json.loads(request.data)['model'],self.body['model']);self.assertLessEqual(send.call_args.kwargs['timeout'],45)
  self.assertEqual(self.registry.records,[])
 def test_empty_response_is_not_success(self):
  with patch('model_registry.urllib.request.urlopen',return_value=io.BytesIO(b'{"choices":[]}')):
   self.assertFalse(self.registry.test(self.body)['success'])
 def test_duplicate_name_and_unknown_id_rejected(self):
  self.registry.save(self.body)
  with self.assertRaises(ValueError):self.registry.save(self.body)
  with self.assertRaises(ValueError):self.registry.save({**self.body,'id':'missing'})

class RuntimePolicyTests(unittest.TestCase):
 def setUp(self):
  sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'local-only/harness'))
 def test_explicit_sample_name_updates_preserve_assertions(self):
  from runtime_policy import preserve_java_assertions
  old='@Test\n.andExpect(status().isOk())\n.andExpect(jsonPath("$[0].name").value("고춧가루"))\n.andExpect(jsonPath("$.length()").value(6))'
  new=old.replace('고춧가루','알루미늄 판재')
  self.assertTrue(preserve_java_assertions(old,new,'제조업체 예시로 변경'))
  self.assertFalse(preserve_java_assertions(old,new,'다른 버그 수정'))
  for bad in [new.replace('isOk','isBadRequest'),new.replace('$[0].name','$[1].name'),new.replace('.value(6)','.value(1)'),new.replace('@Test',''),new.split('\n',1)[1],new.replace('.andExpect(status().isOk())','')]:
   self.assertFalse(preserve_java_assertions(old,bad,'예시 변경'))
 def test_escaped_value_and_path(self):
  from runtime_policy import preserve_java_assertions
  old='@Test\n.andExpect(jsonPath("$.name").value("a\\\"b"))'
  self.assertTrue(preserve_java_assertions(old,old.replace('a\\\"b','c\\\"d'),'sample rename'))
  self.assertFalse(preserve_java_assertions(old,old.replace('$.name','$.other'),'sample rename'))
 def test_generation_limits_and_compact_context(self):
  from runtime_policy import generation_settings,frontend_contract,plan_prompt
  with patch.dict(os.environ,{'LOCAL_LLM_TEMPERATURE':'.2','LOCAL_LLM_TIMEOUT':'90'}):self.assertEqual(generation_settings(),{'temperature':.2,'timeout':90})
  with patch.dict(os.environ,{'LOCAL_LLM_TIMEOUT':'9999'}),self.assertRaises(ValueError):generation_settings()
  self.assertLess(len(frontend_contract(['frontend'])),500);self.assertEqual(frontend_contract(['backend']),'');self.assertIn('실제 요청',plan_prompt('실제 요청','feedback'))

class LongWaitPolicyTests(unittest.TestCase):
 def test_registry_accepts_one_hour_without_changing_default(self):
  with tempfile.TemporaryDirectory() as directory:
   registry=ModelRegistry(Path(directory),[])
   body={'name':'Long local generation','model':'local/26b','url':'http://127.0.0.1:8099/v1'}
   self.assertEqual(registry.validate(body)['timeout'],600)
   self.assertEqual(registry.validate({**body,'timeout':3600})['timeout'],3600)
   with self.assertRaises(ValueError):registry.validate({**body,'timeout':3601})
