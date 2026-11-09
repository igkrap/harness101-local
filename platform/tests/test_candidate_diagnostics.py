import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import test_autonomy
from ast_editing import editor
from candidate_diagnostics import faulty_candidate_nodes


class CandidateDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.rel = 'frontend/src/Demo.tsx'
        self.file = self.root / self.rel
        self.file.parent.mkdir(parents=True)
        self.original = '// 한글 😀\r\nexport default function Demo(){\r\nreturn <main><aside>old</aside><p>keep</p></main>;\r\n}\r\n'
        self.file.write_bytes(self.original.encode())
        self.r = SimpleNamespace(h=SimpleNamespace(workspace=test_autonomy.native.WorkspaceManager(self.root)))
        self.ed = editor(self.r.h)
        self.snap = self.ed.snapshot(self.rel)
        self.slot = next(n for n in self.snap['nodes'] if n['kind']=='insert' and 'function prologue' in n['label'])
        self.aside = next(n for n in self.snap['nodes'] if n['kind']=='JsxElement' and n['source'].startswith('<aside>'))
        self.paragraph = next(n for n in self.snap['nodes'] if n['kind']=='JsxElement' and n['source'].startswith('<p>'))

    def tearDown(self):
        self.r.h._code_intelligence.close()
        self.tmp.cleanup()

    def proposal(self, edits):
        return dict(path=self.rel,snapshot_id=self.snap['snapshot_id'],source_hash=self.snap['source_hash'],edits=edits)

    def error(self, source, needle, path='src/Demo.tsx'):
        prefix = source[:source.index(needle)]
        row = prefix.count('\n') + 1
        col = len(prefix.rsplit('\n',1)[-1].encode('utf-16-le')) // 2 + 1
        return f'{path}({row},{col}): error TS2304: Cannot find name {needle}.'

    def test_insertion_and_unicode_crlf_diagnostics_map_to_only_faulty_operation(self):
        proposal = self.proposal([dict(node_id=self.aside['id'],code='<aside>new 😀</aside>'),dict(node_id=self.slot['id'],code='const label="한글 😀"; const value=missingThing;')])
        source = self.ed.apply(self.rel,self.snap['snapshot_id'],proposal['edits'])['new_text']
        result = faulty_candidate_nodes(self.r,proposal,self.error(source,'missingThing'))
        self.assertEqual(result,[self.slot['id']])
        self.assertEqual(faulty_candidate_nodes(self.r,proposal,'[frontend] '+self.error(source,'missingThing')),[self.slot['id']])
        self.assertEqual(self.file.read_bytes(),self.original.encode())

    def test_same_line_errors_use_columns_and_do_not_blame_unchanged_companions(self):
        proposal = self.proposal([dict(node_id=self.aside['id'],code='<aside>😀 {missingA}</aside>'),dict(node_id=self.paragraph['id'],code='<p>{missingB}</p>')])
        source = self.ed.apply(self.rel,self.snap['snapshot_id'],proposal['edits'])['new_text']
        first = self.error(source,'missingB')
        self.assertEqual(faulty_candidate_nodes(self.r,proposal,first),[self.paragraph['id']])
        both = self.error(source,'missingA')+'\n'+first
        self.assertEqual(faulty_candidate_nodes(self.r,proposal,both),[self.aside['id'],self.paragraph['id']])

    def test_stale_source_and_outside_diagnostic_never_guess_node(self):
        proposal = self.proposal([dict(node_id=self.slot['id'],code='const value=missingThing;')])
        source = self.ed.apply(self.rel,self.snap['snapshot_id'],proposal['edits'])['new_text']
        self.assertEqual(faulty_candidate_nodes(self.r,proposal,self.error(source,'missingThing','/outside/frontend/src/Demo.tsx')),[])
        self.file.write_text(self.original+'// user change')
        self.assertEqual(faulty_candidate_nodes(self.r,proposal,self.error(source,'missingThing')),[])
        self.assertIn('// user change',self.file.read_text())

    def test_fragment_feedback_maps_explicit_node_and_reconstruction_mismatch_is_ignored(self):
        proposal = self.proposal([dict(node_id=self.aside['id'],code='<aside>new</aside>')])
        feedback = 'Tool failed AST_EDIT_FEEDBACK '+json.dumps(dict(node_id=self.aside['id'],error='bad fragment'))
        self.assertEqual(faulty_candidate_nodes(self.r,proposal,feedback),[self.aside['id']])
        with patch.object(self.ed,'apply',return_value={'new_text':'different normalized source'}):
            self.assertEqual(faulty_candidate_nodes(self.r,proposal,'src/Demo.tsx(1,1): error TS2304: missing'),[])

    def test_utf16_column_at_final_character_of_edit_stays_inside_that_edit(self):
        self.file.write_text('export default function Demo(){const note="😀"; const keep=1;\nreturn <main>{note}</main>;}')
        self.snap = self.ed.snapshot(self.rel)
        node = next(n for n in self.snap['nodes'] if n['source']=='const keep=1;')
        proposal = self.proposal([dict(node_id=node['id'],code='const keep=z')])
        source = self.ed.apply(self.rel,self.snap['snapshot_id'],proposal['edits'])['new_text']
        self.assertEqual(faulty_candidate_nodes(self.r,proposal,self.error(source,'z\n')),[node['id']])

    def test_utf16_position_helper_rejects_surrogate_midpoints_and_bad_bounds(self):
        from candidate_positions import utf16_column_bytes
        self.assertEqual([utf16_column_bytes('한😀x',p) for p in (1,2,4,5)],[0,3,7,8])
        for p in (0,3,6):
            with self.assertRaises(ValueError):
                utf16_column_bytes('한😀x',p)

    def test_context_prioritizes_actual_faulty_operation_without_dropping_companion(self):
        from candidate_blocks import format_candidate_context
        proposal = self.proposal([dict(node_id=self.aside['id'],code='<aside>good companion</aside>'),dict(node_id=self.slot['id'],code='const value=missingThing;')])
        source = self.ed.apply(self.rel,self.snap['snapshot_id'],proposal['edits'])['new_text']
        self.r.args = SimpleNamespace(task='repair')
        self.r.feedback = self.error(source,'missingThing')
        text = format_candidate_context(self.r,proposal,self.snap['nodes'])
        self.assertIn('FAULTY OPERATIONS: '+self.slot['id'],text)
        self.assertLess(text.index('RETAINED '+self.slot['id']),text.index('RETAINED '+self.aside['id']))
        self.assertIn('good companion',text)
        self.assertEqual(self.file.read_bytes(),self.original.encode())
