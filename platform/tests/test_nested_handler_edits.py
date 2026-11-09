"""Real AST, TypeScript compilation and mocked network for bounded handler edits."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'local-only/harness'))
from ast_editing import Editor, editor
from code_intelligence import Service
from test_autonomy import native


SOURCE = '''// Preserve unrelated source and metadata.
export const meta = {code: 'EXAMPLE'};
type Row = {id: number; code: string};
export function screenModel() {
  let rows: Row[] = [];
  function handleQuery(code: string) { rows = rows.filter(row => row.code.includes(code)); }
  return {handleQuery, getRows: () => rows};
}
'''
ASYNC_HANDLER = '''async function handleQuery(code: string) {
  const response = await fetch('/fixture?code=' + encodeURIComponent(code));
  if (!response.ok) throw new Error('query failed');
  rows = await response.json() as Row[];
}'''


class NestedHandlerTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.rel = 'frontend/src/screens/Example.tsx'
        self.file = self.root / self.rel
        self.file.parent.mkdir(parents=True)
        self.file.write_text(SOURCE)
        self.service = Service(native.WorkspaceManager(self.root))
        self.addCleanup(self.service.close)
        self.editor = Editor(self.service, allow_nested_handlers=True)

    def handler(self):
        snapshot = self.editor.snapshot(self.rel)
        function = next(node for node in snapshot['nodes'] if node['kind'] == 'FunctionDeclaration')
        return snapshot, function

    def apply(self, code):
        snapshot, node = self.handler()
        return self.editor.apply(self.rel, snapshot['snapshot_id'], [{'node_id': node['id'], 'code': code}])

    def test_opt_in_exposes_nested_handler_but_no_module_root_component_or_generator(self):
        source = SOURCE + '''
export default function Root() {
  function localEvent() { return 1; }
  function Child() { return <section/>; }
  function renderChild() { return <span/>; }
  function Constructor() { return 1; }
  function* generator() { yield 1; }
  return <main/>;
}
'''
        self.file.write_text(source)
        snapshot = self.editor.snapshot(self.rel)
        functions = [node for node in snapshot['nodes'] if node['kind'] == 'FunctionDeclaration']
        self.assertEqual(len(functions), 2)
        self.assertTrue(all(node['handler_scope'] for node in functions))
        self.assertTrue(any('function handleQuery' in node['source'] for node in functions))
        self.assertTrue(any('function localEvent' in node['source'] for node in functions))
        self.assertFalse(any(node['source'] in (source, '<main/>') for node in functions))
        legacy = Editor(self.service).snapshot(self.rel)
        self.assertFalse(any(node['kind'] == 'FunctionDeclaration' for node in legacy['nodes']))

    def test_async_handler_candidate_compiles_and_fetches_through_mocked_network(self):
        result = self.apply(ASYNC_HANDLER)
        self.assertEqual(result['new_text'], SOURCE.replace(self.handler()[1]['source'], ASYNC_HANDLER))
        self.assertEqual(self.file.read_text(), SOURCE, 'Editor returns a candidate without writing source')
        candidate = self.root / 'candidate.ts'
        candidate.write_text(result['new_text'])
        script = r'''
const path=require('node:path'),assert=require('node:assert/strict');
const ts=require(path.join(require('node:os').homedir(),'.local/share/mlx-server/code-intelligence/node_modules/typescript'));
const file=process.argv[1],out=process.argv[2];
const program=ts.createProgram([file],{strict:true,types:[],target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS,
  lib:['lib.es2022.d.ts','lib.dom.d.ts'],outDir:out,noEmitOnError:true,skipLibCheck:true});
const diagnostics=ts.getPreEmitDiagnostics(program);
assert.deepEqual(diagnostics.map(d=>ts.flattenDiagnosticMessageText(d.messageText,'\n')),[]);
assert.equal(program.emit().emitSkipped,false);
let requested;
globalThis.fetch=async url=>{requested=url;return {ok:true,json:async()=>[{id:7,code:'part'}]};};
(async()=>{const view=require(path.join(out,'candidate.js')).screenModel();await view.handleQuery('part value');
assert.equal(requested,'/fixture?code=part%20value');assert.deepEqual(view.getRows(),[{id:7,code:'part'}]);
console.log(JSON.stringify({compiled:true,mocked_fetch:true,rows:view.getRows()}));})().catch(e=>{console.error(e);process.exitCode=1;});
'''
        checked = subprocess.run(['node', '-e', script, str(candidate), str(self.root / 'compiled')],
                                 text=True, capture_output=True, timeout=15)
        self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
        self.assertTrue(json.loads(checked.stdout)['mocked_fetch'])
        self.assertEqual(self.file.read_text(), SOURCE)

    def test_handler_identity_parameter_and_type_signature_changes_are_rejected(self):
        proposals = [ASYNC_HANDLER.replace('handleQuery', 'differentHandler'),
                     ASYNC_HANDLER.replace('code: string', 'different: string'),
                     ASYNC_HANDLER.replace('code: string', 'code: number'),
                     ASYNC_HANDLER.replace('code: string', 'code: string, extra: string'),
                     ASYNC_HANDLER.replace('code: string', 'code: string = "value"'),
                     ASYNC_HANDLER.replace('(code: string)', '<T>(code: string)'),
                     ASYNC_HANDLER.replace('(code: string)', '(code: string): Promise<void>')]
        for code in proposals:
            with self.subTest(code=code), self.assertRaisesRegex(ValueError, 'identity and parameters'):
                self.apply(code)
        self.assertEqual(self.file.read_text(), SOURCE)

    def test_exports_default_component_bodies_and_multiple_functions_are_rejected(self):
        proposals = ['export ' + ASYNC_HANDLER, 'export default ' + ASYNC_HANDLER,
                     'function handleQuery(code: string) { return <main/>; }',
                     'function handleQuery(code: string) { function hidden(){ return <main/>; } }',
                     'function handleQuery(code: string) { export const hidden = 1; }',
                     "function handleQuery(code: string) { import {hidden} from 'outside'; }",
                     'function* handleQuery(code: string) { yield 1; }',
                     ASYNC_HANDLER + '\nfunction extra() {}', '']
        for code in proposals:
            with self.subTest(code=code), self.assertRaises(ValueError):
                self.apply(code)
        self.assertEqual(self.file.read_text(), SOURCE)

    def test_handler_source_and_replacement_are_bounded(self):
        with self.assertRaisesRegex(ValueError, '3000-character'):
            self.apply(ASYNC_HANDLER[:-1] + '/*' + 'x' * 3000 + '*/}')
        self.file.write_text(SOURCE.replace('rows = rows.filter', '/*' + 'x' * 3000 + '*/ rows = rows.filter'))
        snapshot = self.editor.snapshot(self.rel)
        self.assertFalse(any(node['kind'] == 'FunctionDeclaration' for node in snapshot['nodes']))

    def test_stale_source_and_policy_change_cannot_reuse_function_scope(self):
        snapshot, node = self.handler()
        self.file.write_text(SOURCE + '\n// concurrent change')
        with self.assertRaisesRegex(ValueError, 'stale snapshot'):
            self.editor.apply(self.rel, snapshot['snapshot_id'], [{'node_id': node['id'], 'code': ASYNC_HANDLER}])
        self.file.write_text(SOURCE)
        self.editor.allow_nested_handlers = False
        with self.assertRaisesRegex(ValueError, 'policy changed'):
            self.editor.apply(self.rel, snapshot['snapshot_id'], [{'node_id': node['id'], 'code': ASYNC_HANDLER}])
        legacy = self.editor.snapshot(self.rel)
        self.assertNotEqual(legacy['snapshot_id'], snapshot['snapshot_id'])
        self.assertFalse(any(node['kind'] == 'FunctionDeclaration' for node in legacy['nodes']))

    def test_real_runner_current_context_inspect_and_profile_switch_respect_opt_in(self):
        from autonomy_runtime import Runner
        gate = SimpleNamespace(enabled=False, prepare=lambda: None, context=lambda: 'Frozen checks remain required')
        args = SimpleNamespace(task='Example 화면의 조회 연결', workspace=str(self.root), check='frontend',
                               context_profile='legacy', max_rounds=2, ponytail='off',
                               llm_url='http://127.0.0.1:1/v1', model='fixture')
        with patch('completion_runner.Gate', return_value=gate):
            runner = Runner(args, native.Harness)
        runner.h.log_event = Mock()
        self.addCleanup(lambda: runner.h._code_intelligence.close())
        legacy = runner.apply('inspect_code', {'path': self.rel, 'action': 'edit_ranges'}, {})
        self.assertFalse(any(node['kind'] == 'FunctionDeclaration' for node in legacy['nodes']))
        args.context_profile = 'focused'
        current, paths = runner.current_context()
        self.assertIn('nested handler function handleQuery', current)
        self.assertIn(self.rel, paths)
        focused_editor = editor(runner.h)
        self.assertTrue(focused_editor.allow_nested_handlers)
        focused = runner.apply('inspect_code', {'path': self.rel, 'action': 'edit_ranges'}, {})
        node = next(node for node in focused['nodes'] if node['kind'] == 'FunctionDeclaration')
        self.assertEqual(node['source'], self.handler()[1]['source'])
        with self.assertRaisesRegex(ValueError, 'Existing frontend source requires'):
            runner.apply('write_file', {'path': self.rel, 'content': 'raw rewrite'}, {})
        args.context_profile = 'legacy'
        again = runner.apply('inspect_code', {'path': self.rel, 'action': 'edit_ranges'}, {})
        self.assertFalse(editor(runner.h).allow_nested_handlers)
        self.assertIsNot(editor(runner.h), focused_editor)
        self.assertFalse(any(node['kind'] == 'FunctionDeclaration' for node in again['nodes']))
        self.assertEqual(self.file.read_text(), SOURCE)


if __name__ == '__main__':
    unittest.main()
