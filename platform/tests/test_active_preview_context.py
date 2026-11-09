import json
import pathlib
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch

sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[2]/'local-only/harness'))

class ActivePreviewContextTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=pathlib.Path(self.temp.name);self.ws=self.root/'frontend/src/workspace.json';self.ws.parent.mkdir(parents=True);self.ws.write_text(json.dumps({'activeTab':'Inventory'}))
        self.screen=self.root/'frontend/src/screens/Inventory.tsx';self.screen.parent.mkdir();self.screen.write_text('export default function Inventory(){return <main data-testid="live-main"/>;}')
        self.runner=SimpleNamespace(h=SimpleNamespace(workspace=SimpleNamespace(root=self.root)))
    def tearDown(self):self.temp.cleanup()
    def test_active_screen_source_and_existing_selectors_are_complete(self):
        from active_preview_context import active_screen_context
        text=active_screen_context(self.runner);self.assertIn(self.screen.read_text(),text);self.assertIn('frontend/src/screens/Inventory.tsx',text)
        self.ws.write_text(json.dumps({'activeTab':'Other'}));self.assertEqual(active_screen_context(self.runner),'')
    def test_invalid_ids_symlinks_and_large_sources_do_not_leak_partial_or_external_code(self):
        from active_preview_context import active_screen_context
        self.ws.write_text(json.dumps({'activeTab':'../../secret'}));self.assertEqual(active_screen_context(self.runner),'')
        self.ws.write_text(json.dumps({'activeTab':'Inventory'}));self.screen.write_text('SECRET_PARTIAL'*1000);self.assertEqual(active_screen_context(self.runner),'')
        self.screen.unlink();secret=self.root/'private.txt';secret.write_text('PRIVATE_EXTERNAL');self.screen.symlink_to(secret);self.assertEqual(active_screen_context(self.runner),'')
        self.ws.unlink();self.ws.symlink_to(secret);self.assertEqual(active_screen_context(self.runner),'')
    def test_gate_prompt_prioritizes_active_source_before_shell_context_budget(self):
        from verification_gate import Gate
        raw={'criteria':[{'id':'C1','requirement_id':'R1','description':'main','check':{'op':'visible','selector':'body'}}]}
        self.runner.args=SimpleNamespace(task='현재 화면 구성');self.runner.modes=['frontend'];self.runner.accepted=False
        self.runner.h.log_event=Mock();self.runner.current_context=lambda:('APP_ONLY_CONTEXT'+'x'*20000,set())
        self.runner.ask=Mock(return_value={'content':json.dumps(raw)})
        with patch('requirement_review.review',return_value={'approved':True,'issues':[]}):Gate(self.runner).prepare()
        prompt=self.runner.ask.call_args.kwargs['messages'][1]['content']
        self.assertLess(prompt.index('data-testid="live-main"'),prompt.index('APP_ONLY_CONTEXT'))
        self.assertEqual(prompt.count('data-testid="live-main"'),1)

    def test_screen_code_resolves_metadata_without_renaming_source(self):
        from active_preview_context import active_screen_context
        self.ws.write_text(json.dumps({'activeTab':'ABC0001'}))
        self.screen.write_text("export const meta = {code:'ABC0001',title:'재고'};\nexport default function Inventory(){return <main/>;}")
        self.assertIn('frontend/src/screens/Inventory.tsx',active_screen_context(self.runner))
        duplicate=self.screen.with_name('Duplicate.tsx');duplicate.write_text(self.screen.read_text())
        self.assertEqual(active_screen_context(self.runner),'')

if __name__=='__main__':unittest.main()
