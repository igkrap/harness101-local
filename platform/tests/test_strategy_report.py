import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from history import History
from strategy_report import strategy_report


class StrategyReportTests(unittest.TestCase):
    def test_indexed_state_survives_paged_log_window(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            key = 'a' * 32
            job = {'id': key, 'status': 'running'}
            (root / key).mkdir()
            events = [
                {'seq': 1, 'type': 'autonomy.plan', 'data': {'source': 'divide-and-conquer', 'steps': [{'id': 'api'}]}},
                {'seq': 2, 'type': 'autonomy.strategy_state', 'data': {'active_stage_id': 'api', 'completed_stage_ids': []}}]
            events += [{'seq': i, 'type': 'model.response', 'data': {}} for i in range(3, 1100)]
            (root / key / 'events.jsonl').write_text(''.join(json.dumps(e) + '\n' for e in events))
            history = History(root)
            try:
                history.sync(job)
                report = strategy_report(history, job)
                self.assertTrue(report['recorded'])
                self.assertEqual(report['state']['active_stage_id'], 'api')
                self.assertEqual(report['stages'], [{'id': 'api'}])
            finally: history.close()

    def test_legacy_plan_and_stale_state(self):
        class Fake:
            def __init__(self): self.events = {}
            def last_event(self, job, kind): return self.events.get(kind)
        history = Fake()
        self.assertFalse(strategy_report(history, {'id': 'x'})['recorded'])
        history.events = {'autonomy.plan': {'seq': 20, 'data': {'source': 'divide-and-conquer', 'steps': []}},
                          'autonomy.strategy_state': {'seq': 1, 'data': {'phase': 'success'}}}
        self.assertEqual(strategy_report(history, {'id': 'x'})['state'], {})

    def test_invalidated_stages_do_not_inflate_completion_count(self):
        from failure import describe_failure
        report=describe_failure({'id':'x','status':'running'},None,{'autonomy.step_finished':5},
            plan={'data':{'steps':[{}, {}, {}]}},
            strategy={'data':{'completed_stage_ids':['query'],'phase':'running'}})
        self.assertEqual(report['completed_steps'],1)


if __name__ == '__main__': unittest.main()
