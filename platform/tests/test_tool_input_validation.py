import copy
import sys
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'local-only/harness'))
from patch_edits import PATCH_TOOL
import test_candidate_repair as fixtures


class ToolInputValidationTests(unittest.TestCase):
    def setUp(self):
        self.runner=SimpleNamespace(tools=lambda:[PATCH_TOOL])

    def test_actual_broken_backend_call_reports_missing_fields_without_mutating_input(self):
        from tool_input_validation import validate_arguments
        args={'edits':[{'content':'public void save() {}','file':'backend/Controller.java'}]}
        before=copy.deepcopy(args)
        with self.assertRaises(ValueError) as caught:validate_arguments(self.runner,'apply_edits',args)
        message=str(caught.exception)
        for key in ('TOOL_INPUT_INVALID','path','old_text','new_text','Expected arguments schema'):
            self.assertIn(key,message)
        self.assertNotIn('public void save()',message)
        self.assertEqual(args,before)

    def test_actual_valid_edit_shape_and_unknown_tool_preserve_existing_handling(self):
        from tool_input_validation import validate_arguments
        args={'path':'backend/Controller.java','edits':[{'old_text':'old','new_text':'new'}]}
        self.assertIsNone(validate_arguments(self.runner,'apply_edits',args))
        self.assertIsNone(validate_arguments(self.runner,'unknown',args))

    def test_ajv_rejects_wrong_types_and_does_not_coerce_or_strip_fields(self):
        from tool_input_validation import validate_arguments
        for args in ({'path':None,'edits':[]},{'path':4,'edits':[]},{'path':'x','edits':[{'old_text':'old','new_text':False}]}):
            before=copy.deepcopy(args)
            with self.assertRaises(ValueError):validate_arguments(self.runner,'apply_edits',args)
            self.assertEqual(args,before)

    def test_bare_tool_definition_and_enums_are_validated(self):
        from tool_input_validation import validate_arguments
        self.runner.tools=lambda:[{'name':'choice','parameters':{'type':'object','properties':{'mode':{'enum':['before','after']}},'required':['mode'],'additionalProperties':False}}]
        validate_arguments(self.runner,'choice',{'mode':'after'})
        for args in ({'mode':'middle'},{'mode':'after','extra':1}):
            with self.assertRaises(ValueError):validate_arguments(self.runner,'choice',args)


class ToolValidationIntegrationTests(unittest.TestCase):
    setUp=fixtures.CandidateRepairTests.setUp
    tearDown=fixtures.CandidateRepairTests.tearDown

    def test_model_tool_shape_error_is_reported_before_file_access_or_checkpoint(self):
        self.runner.modes=['backend']
        response={'content':'','tool_calls':[{'id':'bad','function':{'name':'apply_edits','arguments':'{"edits":[{"file":"backend/Controller.java","content":"code"}]}'}}]}
        paths,error,finished=self.runner.batch(response)
        self.assertIn('TOOL_INPUT_INVALID',error)
        self.assertIn('old_text',error)
        self.assertIn('new_text',error)
        self.assertNotIn('NoneType',error)
        self.assertFalse(paths)
        self.assertFalse(finished)
        self.assertFalse(self.runner.cp.pending)
        self.assertEqual(self.file.read_text(),self.original)
