import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import Mock
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'local-only/harness'))
from requirement_review import review, literal_check, review_payload


class ReviewTests(unittest.TestCase):
    def test_review_facts_preserve_executor_operand_direction(self):
        for relation,word in [('above','ABOVE'),('left_of','LEFT OF')]:
            fact=literal_check({'op':'layout','left':'#query','right':'#grid','relation':relation})
            self.assertEqual(fact['subject'],'#query')
            self.assertEqual(fact['reference'],'#grid')
            self.assertIn(word,fact['assertion'])
            self.assertEqual(fact['op'],'layout')
            self.assertEqual(fact['relation'],relation)

    def test_review_payload_separates_validated_operator_from_explanation(self):
        payload=review_payload(self.contract)
        self.assertTrue(payload['syntax_validated'])
        check=payload['criteria'][0]['check']
        self.assertEqual(check['relation'],'above')
        self.assertEqual(check['assertion'],'physically ABOVE')
        self.assertNotIn('left',check)
        self.assertNotIn('right',check)
    def setUp(self):
        self.contract={'task':'Left grid, right form','requirements':[{'id':'R1','description':'Left grid, right form'}],
                       'criteria':[{'id':'C1','requirement_id':'R1','description':'grid above form',
                                    'check':{'op':'layout','left':'#grid','right':'#form','relation':'above'}}]}
        self.runner=SimpleNamespace(ask=Mock(),h=SimpleNamespace(log_event=Mock()))

    def call(self,result):
        self.runner.ask.return_value={'content':json.dumps(result)}
        return review(self.runner,self.contract)

    def test_reviewer_receives_original_task_and_checks_in_fresh_context(self):
        result=self.call({'approved':False,'issues':[{'criterion_id':'C1','reason':'Above form is not requested; use left_of'}]})
        self.assertFalse(result['approved'])
        args=self.runner.ask.call_args
        messages=args.kwargs.get('messages',args.args[0] if args.args else [])
        self.assertIn('Left grid, right form',str(messages))
        self.assertIn('above',str(messages))
        self.assertEqual(args.kwargs.get('tools',args.args[1] if len(args.args)>1 else None),[])
        self.runner.ask.assert_called_once()

    def test_issue_naming_a_requirement_is_a_contract_issue(self):
        result=self.call({'approved':False,'issues':[{'criterion_id':'R1','reason':'요구사항 전체가 빠짐'}]})
        self.assertFalse(result['approved'])
        self.assertEqual(result['issues'][0]['criterion_id'],'contract')

    def test_only_explicit_boolean_approval_with_no_issues_passes(self):
        self.assertTrue(self.call({'approved':True,'issues':[]})['approved'])
        for result in [{'approved':'true','issues':[]},{'approved':True,'issues':[{'criterion_id':'C1','reason':'bad'}]},
                       {'approved':False,'issues':[]},{'approved':False,'issues':[{'criterion_id':'UNKNOWN','reason':'bad'}]},
                       {'approved':True,'issues':[],'ignore_checks':True}]:
            with self.subTest(result=result),self.assertRaises(ValueError):self.call(result)

    def test_malformed_review_never_defaults_to_approval(self):
        self.runner.ask.return_value={'content':'looks good'}
        with self.assertRaises(ValueError):review(self.runner,self.contract)

    def test_duplicate_approval_key_is_rejected(self):
        self.runner.ask.return_value={'content':'{"approved":false,"approved":true,"issues":[]}'}
        with self.assertRaises(ValueError):review(self.runner,self.contract)


if __name__=='__main__':unittest.main()
