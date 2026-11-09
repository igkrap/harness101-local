import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from folder_dialog import choose_folder
from preview import Previews, healthy


class FolderTests(unittest.TestCase):
    def test_native_dialog_preserves_unicode_and_spaces(self):
        with tempfile.TemporaryDirectory(prefix='프로젝트 폴더 ') as name:
            result=subprocess.CompletedProcess([],0,name+'\n','')
            with patch('folder_dialog.sys.platform','darwin'),patch('folder_dialog.subprocess.run',return_value=result) as run:
                chosen=choose_folder()
            self.assertEqual(chosen['root'],str(Path(name).resolve()));self.assertEqual(chosen['name'],Path(name).name)
            self.assertEqual(run.call_args.args[0][0],'osascript');self.assertFalse(run.call_args.kwargs.get('shell',False))
    def test_cancel_does_not_select_a_folder(self):
        with patch('folder_dialog.sys.platform','darwin'),patch('folder_dialog.subprocess.run',return_value=subprocess.CompletedProcess([],1,'','User canceled. (-128)')):
            self.assertEqual(choose_folder(),{'cancelled':True})
    def test_dialog_error_is_returned_and_lock_is_released(self):
        with patch('folder_dialog.sys.platform','darwin'),patch('folder_dialog.subprocess.run',side_effect=subprocess.TimeoutExpired('osascript',600)):
            with self.assertRaises(ValueError):choose_folder()
        self.test_cancel_does_not_select_a_folder()


class PreviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.manager=Previews(self.root);self.addCleanup(self.manager.close)
    def project(self,name):
        root=self.root/name;frontend=root/'frontend';frontend.mkdir(parents=True)
        (frontend/'package.json').write_text(json.dumps({'type':'module','devDependencies':{'vite':'*'}}))
        (frontend/'index.html').write_text('<h1>'+name+'</h1>')
        (frontend/'vite.config.js').write_text('export default {server:{port:5292}}')
        (frontend/'node_modules').symlink_to(Path(__file__).resolve().parents[1]/'web/node_modules',target_is_directory=True)
        return {'id':name,'root':str(root),'preview_url':''}
    def wait_ready(self,manager,record):
        for _ in range(200):
            result=manager.status(record)
            if result['status'] in ('ready','failed'):break
            time.sleep(.05)
        self.assertEqual(result['status'],'ready',result);return result
    def test_two_projects_get_distinct_ports_and_existing_server_is_reused(self):
        one,two=self.project('one'),self.project('two')
        self.manager.ensure(one);first=self.wait_ready(self.manager,one)
        self.manager.ensure(two);second=self.wait_ready(self.manager,two)
        self.assertNotEqual(first['url'],second['url']);self.assertNotIn(':5292/',first['url']);self.assertNotIn(':5292/',second['url'])
        for name,url in [('one',first['url']),('two',second['url'])]:
            with urllib.request.urlopen(url) as response:self.assertIn('<h1>'+name+'</h1>',response.read().decode())
        (self.root/'other-state').mkdir();other=Previews(self.root/'other-state')
        try:
            other.ensure(one);existing=self.wait_ready(other,one)
            self.assertEqual(existing['url'],first['url']);self.assertFalse(existing['managed'])
        finally:other.close()
        self.assertTrue(healthy(first['url']))
        self.manager.close();self.assertFalse(healthy(first['url']));self.assertFalse(healthy(second['url']))
    def test_missing_frontend_has_specific_failure(self):
        record={'id':'missing','root':str(self.root/'missing')};self.manager.ensure(record)
        for _ in range(100):
            result=self.manager.status(record)
            if result['status']=='failed':break
            time.sleep(.01)
        self.assertEqual(result['status'],'failed');self.assertIn('package.json',result['error'])
