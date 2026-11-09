from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'local-only/harness'))
from test_autonomy import native
from autonomy_runtime import Runner

class ToolArgumentDuplicateTests(unittest.TestCase):
    def test_duplicate_keys_at_any_depth_are_rejected_before_tool_dispatch(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);file=root/'frontend/src/App.tsx';file.parent.mkdir(parents=True);source='export default function App(){return <main/>;}';file.write_text(source)
            args=SimpleNamespace(task='레이아웃 수정',workspace=str(root),check='frontend',max_rounds=0,ponytail='off',llm_url='http://127.0.0.1:8099/v1',model='fixture')
            runner=Runner(args,native.Harness);runner.h.evidence_path=root/'events.jsonl'
            try:
                for arguments in ['{"path":"frontend/src/App.tsx","path":"frontend/src/Other.tsx","edits":[]}',
                                  '{"path":"frontend/src/App.tsx","edits":[{"node_id":"n1","code":"<main/>","code":"<aside/>"}]}']:
                    message={'role':'assistant','content':'','tool_calls':[{'id':'duplicate','type':'function','function':{'name':'apply_ast_edits','arguments':arguments}}]}
                    with patch.object(runner,'apply',side_effect=AssertionError('must not dispatch ambiguous args')) as apply:
                        paths,error,finished=runner.batch(message)
                    self.assertIn('Duplicate key',error);apply.assert_not_called();self.assertFalse(paths);self.assertFalse(finished);self.assertFalse(runner.cp.pending);self.assertEqual(file.read_text(),source)
            finally:
                service=getattr(runner.h,'_code_intelligence',None)
                if service:service.close()
