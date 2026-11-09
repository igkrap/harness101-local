import json
from pathlib import Path
import subprocess
import unittest
import copy
from unittest.mock import Mock
import test_candidate_repair as fixtures
from ast_editing import editor

ROOT = Path(__file__).resolve().parents[2]
NODE = str(Path.home() / '.nvm/versions/node/v22.15.0/bin/node')
HELPER = ROOT / 'local-only/harness/candidate_duplicate_functions.cjs'


class DuplicateFunctionReflexTests(unittest.TestCase):
    def call(self, operations, name='save'):
        program = "const fs=require('fs'),ts=require(require('os').homedir()+'/.local/share/mlx-server/code-intelligence/node_modules/typescript');const v=JSON.parse(fs.readFileSync(0,'utf8'));console.log(JSON.stringify(require(process.argv[1]).deduplicate(ts,v.operations,v.name)));"
        result = subprocess.run([NODE, '-e', program, str(HELPER)], input=json.dumps({'operations': operations, 'name': name}), text=True, capture_output=True, check=True)
        return json.loads(result.stdout)

    def ops(self, function='const save = async (e: Event) => { e.preventDefault(); await submit(); };', other=None):
        return [{'node_id':'n1','is_insert':False,'code':function}, {'node_id':'s2','is_insert':True,'code':other or 'const state = "한글";\r\n// keep\r\n'+function+'\r\nconst columns = [1];'}]

    def test_only_identical_inserted_function_is_removed_with_exact_surrounding_bytes(self):
        ops=self.ops()
        before=json.dumps(ops)
        self.assertEqual(self.call(ops), [{'node_id':'s2','code':'const state = "한글";\r\n// keep\r\n\r\nconst columns = [1];'}])
        self.assertEqual(json.dumps(ops),before)

    def test_formatting_and_comments_differ_but_ast_function_is_identical(self):
        a='const save = () => { submit(); };'
        ops=self.ops(a,'const state=1;\nconst save=()=>{ /*same*/ submit(); };\n')
        self.assertEqual(self.call(ops),[{'node_id':'s2','code':'const state=1;\n\n'}])

    def test_different_behavior_is_not_merged(self):
        ops=self.ops(other='const state=1; const save = () => other();')
        self.assertEqual(self.call(ops),[])

    def test_side_effecting_initializers_and_nested_callbacks_are_not_removed(self):
        self.assertEqual(self.call(self.ops('const save = submit();')),[])
        self.assertEqual(self.call(self.ops(other='const keep = () => { const save = async (e: Event) => { e.preventDefault(); await submit(); }; };')),[])

    def test_ambiguous_or_non_insert_or_empty_remainder_is_not_changed(self):
        ops=self.ops()
        ops.append(dict(ops[0],node_id='n3'))
        self.assertEqual(self.call(ops),[])
        ops=self.ops();ops[1]['is_insert']=False
        self.assertEqual(self.call(ops),[])
        ops=self.ops();ops[1]['code']=ops[0]['code']
        self.assertEqual(self.call(ops),[])

    def test_multi_binding_and_invalid_fragments_are_not_changed(self):
        self.assertEqual(self.call(self.ops('const save = () => submit(), x = 2;')),[])
        self.assertEqual(self.call(self.ops(other='const state=1; const save = ()=> {')),[])


if __name__ == '__main__':
    unittest.main()


class DuplicateReflexIntegrationTests(unittest.TestCase):
    def setUp(self):
        fixtures.CandidateRepairTests.setUp(self)
        self.original = self.original.replace(';return (', '; return (')
        self.file.write_text(self.original)
    tearDown = fixtures.CandidateRepairTests.tearDown

    def proposal(self):
        snap = editor(self.runner.h).snapshot(self.rel)
        declaration = next(n for n in snap['nodes'] if n['source'].startswith('const save='))
        slot = next(n for n in snap['nodes'] if n['kind'] == 'insert' and 'before return' in n['label'])
        function = declaration['source']
        self.slot = slot['id']
        return dict(path=self.rel,snapshot_id=snap['snapshot_id'],source_hash=snap['source_hash'],edits=[dict(node_id=declaration['id'],code=function),dict(node_id=slot['id'],code=function+'\nconsole.log("keep");')])

    def test_runner_reflex_uses_zero_model_calls_and_regular_atomic_check(self):
        from candidate_duplicate_reflex import resolve_duplicate
        proposal = self.proposal()
        original = copy.deepcopy(proposal)
        self.runner.feedback = "src/App.tsx(1,1): error TS2451: Cannot redeclare block-scoped variable 'save'."
        self.runner._failed_ast_candidate = proposal
        self.runner.h.llm.chat = Mock(side_effect=AssertionError('No model expected'))
        response = self.runner.ask(self.runner.messages, self.runner.tools())
        self.runner.h.llm.chat.assert_not_called()
        self.assertEqual(self.runner.used, 0)
        self.assertEqual(proposal, original)
        self.assertEqual(self.file.read_text(), self.original)
        self.runner.read.add(self.rel)
        _, error, _ = self.runner.batch(response)
        self.assertFalse(error, error)
        self.assertTrue(self.runner.cp.pending)
        ok, feedback = self.runner.verify()
        self.assertTrue(ok, feedback)
        self.assertEqual(self.file.read_text().count('const save='), 1)
        self.assertIn('console.log("keep")', self.file.read_text())
        self.runner.cp.commit()

    def test_stale_or_unrelated_diagnostic_is_ignored(self):
        from candidate_duplicate_reflex import resolve_duplicate
        proposal=self.proposal()
        self.runner.feedback='Other diagnostic'
        self.assertIsNone(resolve_duplicate(self.runner,proposal))
        self.runner.feedback="src/App.tsx(1,1): error TS2451: Cannot redeclare block-scoped variable 'save'."
        self.file.write_text(self.original+'// user change')
        self.assertIsNone(resolve_duplicate(self.runner,proposal))
        self.assertIn('// user change',self.file.read_text())
