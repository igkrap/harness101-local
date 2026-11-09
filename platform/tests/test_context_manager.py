"""Context management: threshold compaction with a mock local model, validation, archive, restore."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'erp-harness'))
import context_manager as cm

TASK = '부서 등록 화면 만들어줘'


def reply(obj, prompt_tokens=None):
    content = obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False)
    return {'choices': [{'message': {'content': content}}], 'usage': {'prompt_tokens': prompt_tokens} if prompt_tokens else {}}


def good(**over):
    base = {'goal': TASK, 'current_task': 'DepartmentRegistration.tsx 화면 작성', 'completed_tasks': ['부서 API 확인'],
            'decisions': ['ItemMaster 와 같은 구성'], 'constraints': [], 'modified_files': ['frontend/src/screens/DepartmentRegistration.tsx'],
            'active_errors': [], 'failed_attempts': [], 'test_status': [], 'next_actions': ['검사 다시 실행'], 'unknowns': []}
    return {**base, **over}


class FakeLLM:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def chat(self, messages, tools=None):
        self.calls.append(messages)
        item = self.replies.pop(0) if self.replies else reply(good())
        if isinstance(item, Exception):
            raise item
        return item


def conversation(rounds, chars=3000, path=lambda i: f'frontend/src/screens/S{i}.tsx', marker=''):
    msgs = [{'role': 'system', 'content': 'SYSTEM RULES'}, {'role': 'user', 'content': '할 일: ' + TASK}]
    for i in range(rounds):
        cid = f'call{i}'
        msgs.append({'role': 'assistant', 'content': '', 'tool_calls': [{'id': cid, 'type': 'function',
                     'function': {'name': 'read_file', 'arguments': json.dumps({'path': path(i)})}}]})
        body = (marker if i == 0 else '') + f'{i}:' + ('가나다라마 code line;\n' * (chars // 18))
        msgs.append({'role': 'tool', 'tool_call_id': cid, 'content': json.dumps({'content': body}, ensure_ascii=False)})
    return msgs


def runner(messages, llm, task=TASK):
    h = SimpleNamespace(llm=llm, events=[])
    h.log_event = lambda kind, data: h.events.append((kind, data))
    gate = SimpleNamespace(frozen_contract=json.dumps({'criteria': [{'id': 'C1', 'description': '부서코드 칸이 보인다'}]}))
    return SimpleNamespace(h=h, args=SimpleNamespace(task=task), messages=messages, read={'frontend/src/screens/S0.tsx'},
                           feedback='', last_check_results={}, requirement_gate=gate)


def kinds(r):
    return [k for k, _ in r.h.events]


def integrity(messages):
    calls = {c['id'] for m in messages for c in m.get('tool_calls') or []}
    results = [m['tool_call_id'] for m in messages if m.get('role') == 'tool']
    return set(results) <= calls and calls <= set(results)


class ContextManagerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.env = {k: os.environ.get(k) for k in ('HARNESS_JOB_DIR', 'HARNESS_CONTEXT_MANAGEMENT', 'LOCAL_LLM_CONTEXT', 'HARNESS_CONTEXT_CONFIG')}
        os.environ['HARNESS_JOB_DIR'] = self.tmp.name
        os.environ.pop('HARNESS_CONTEXT_MANAGEMENT', None)
        os.environ.pop('HARNESS_CONTEXT_CONFIG', None)
        os.environ['LOCAL_LLM_CONTEXT'] = '40960'
        self.addCleanup(self.restore_env)

    def restore_env(self):
        import context_budget
        context_budget.CALIBRATED_CHARS_PER_TOKEN = None
        for k, v in self.env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def usage(self, r, messages):
        return cm.manager(r).budget.usage(messages)

    # 1. soft threshold (~28K incl. output reserve) -> model compaction, below threshold afterwards
    def test_soft_threshold_compacts_with_the_local_model(self):
        llm = FakeLLM([reply(good())])
        msgs = conversation(42, chars=1100)
        r = runner(msgs, llm)
        before = self.usage(r, msgs)
        self.assertGreaterEqual(before['ratio'], 0.68)
        self.assertLess(before['ratio'], 0.78)
        out = cm.manager(r).prepare(msgs, None)
        self.assertIn('context.compacted', kinds(r))
        self.assertEqual(len(llm.calls), 1)
        self.assertLess(self.usage(r, out)['ratio'], 0.68)
        self.assertTrue(out[2]['content'].startswith(cm.CHECKPOINT_MARK))
        self.assertIs(r.messages, out)
        self.assertEqual(cm.manager(r).store.latest()['version'], 1)

    # 2. hard threshold (~32K) with a failing model -> deterministic checkpoint, run continues
    def test_hard_threshold_falls_back_to_a_deterministic_checkpoint(self):
        llm = FakeLLM([RuntimeError('server down'), RuntimeError('server down')])
        msgs = conversation(52, chars=1100)
        r = runner(msgs, llm)
        self.assertGreaterEqual(self.usage(r, msgs)['ratio'], 0.78)
        out = cm.manager(r).prepare(msgs, None)
        data = dict(r.h.events)['context.compacted']
        self.assertEqual(data['source'], 'deterministic_fallback')
        self.assertLess(self.usage(r, out)['ratio'], 0.68)
        self.assertIn('부서코드 칸이 보인다', cm.manager(r).checkpoint['constraints'][0])

    # 3. after compaction the run continues; the next calls do not rewrite the prefix
    def test_work_resumes_and_prefix_stays_stable(self):
        r = runner(conversation(42, chars=1100), FakeLLM([reply(good())]))
        out = cm.manager(r).prepare(r.messages, None)
        self.assertEqual(out[3]['role'], 'assistant')
        out.append({'role': 'assistant', 'content': '', 'tool_calls': [{'id': 'n1', 'type': 'function', 'function': {'name': 'edit_file', 'arguments': '{}'}}]})
        out.append({'role': 'tool', 'tool_call_id': 'n1', 'content': '{"status": "ok"}'})
        again = cm.manager(r).prepare(out, None)
        self.assertIs(again, out)
        self.assertEqual(kinds(r).count('context.compacted'), 1)

    # 4. confirmed constraints survive even if the model drops them
    def test_constraints_are_kept_by_code(self):
        llm = FakeLLM([reply(good(constraints=[]))])
        r = runner(conversation(42, chars=1100), llm)
        m = cm.manager(r)
        m.checkpoint = {**cm.empty_checkpoint(TASK), 'version': 0, 'constraints': ['부서코드는 필수 입력']}
        m.prepare(r.messages, None)
        cons = m.checkpoint['constraints']
        self.assertIn('부서코드는 필수 입력', cons)
        self.assertTrue(any('C1' in c for c in cons))
        self.assertTrue(any('constraints restored' in x for x in m.last['repaired']))

    # 5. recent original messages and call/result pairs stay intact
    def test_recent_messages_and_tool_pairs_are_intact(self):
        msgs = conversation(42, chars=1100)
        r = runner(msgs, FakeLLM([reply(good())]))
        out = cm.manager(r).prepare(msgs, None)
        self.assertTrue(integrity(out))
        self.assertEqual(out[-1], msgs[-1])
        self.assertEqual(out[-2], msgs[-2])

    # 6. repeated large tool results are pruned by rule (no model call when that is enough)
    def test_repeated_large_results_are_pruned_without_the_model(self):
        llm = FakeLLM([])
        msgs = conversation(18, chars=3600, path=lambda i: 'frontend/src/screens/Same.tsx')
        r = runner(msgs, llm)
        out = cm.manager(r).prepare(msgs, None)
        self.assertIn('context.pruned', kinds(r))
        self.assertEqual(llm.calls, [])
        stubs = [m for m in out if m.get('role') == 'tool' and '"pruned": true' in m['content']]
        self.assertTrue(stubs)
        self.assertTrue(integrity(out))
        self.assertLess(self.usage(r, out)['ratio'], 0.55)

    # 7. invalid JSON is retried and recovered
    def test_invalid_json_is_retried(self):
        llm = FakeLLM([reply('설명: 여기 요약입니다 {broken'), reply('```json\n' + json.dumps(good(), ensure_ascii=False) + '\n```')])
        r = runner(conversation(42, chars=1100), llm)
        m = cm.manager(r)
        m.prepare(r.messages, None)
        self.assertEqual(len(llm.calls), 2)
        self.assertIn('rejected', llm.calls[1][1]['content'].lower())
        self.assertEqual(m.last['source'], 'llm')
        self.assertEqual(m.stats['recoveries'], 1)

    # 8. model failure at the soft threshold keeps the previous state untouched
    def test_model_failure_keeps_state(self):
        llm = FakeLLM([RuntimeError('timeout'), RuntimeError('timeout')])
        msgs = conversation(42, chars=1100)
        snapshot = json.dumps(msgs)
        r = runner(msgs, llm)
        m = cm.manager(r)
        out = m.prepare(msgs, None)
        self.assertIs(out, msgs)
        self.assertEqual(json.dumps(msgs), snapshot)
        self.assertIsNone(m.store.latest())
        self.assertIn('context.compact_failed', kinds(r))
        calls = len(llm.calls)
        m.prepare(msgs, None)  # no immediate retry loop on the same context
        self.assertEqual(len(llm.calls), calls)

    # 9. a restarted runner restores the last checkpoint
    def test_restart_restores_the_checkpoint(self):
        r = runner(conversation(42, chars=1100), FakeLLM([reply(good())]))
        cm.manager(r).prepare(r.messages, None)
        fresh = runner(conversation(1, chars=200), FakeLLM([]))
        out = cm.manager(fresh).prepare(fresh.messages, None)
        self.assertTrue(out[2]['content'].startswith(cm.CHECKPOINT_MARK))
        self.assertIn('context.restored', kinds(fresh))
        other = runner(conversation(1, chars=200), FakeLLM([]), task='다른 요청')
        self.assertFalse(cm.manager(other).prepare(other.messages, None)[2]['content'].startswith(cm.CHECKPOINT_MARK))

    # 10. repeated compaction does not lose earlier decisions/failures
    def test_repeated_compaction_keeps_earlier_information(self):
        first = good(failed_attempts=['edit_file 400 오류: deptCode 누락'], decisions=['상위부서는 추가정보 탭'])
        llm = FakeLLM([reply(first), reply(good()), reply(good())])
        msgs = conversation(42, chars=1100)
        r = runner(msgs, llm)
        m = cm.manager(r)
        for cycle in range(3):
            out = m.prepare(r.messages, None)
            out.extend(conversation(30, chars=1100)[2:] if cycle < 2 else [])
            for n, msg in enumerate(out):
                for c in msg.get('tool_calls') or []:
                    c['id'] = f"{c['id']}-{cycle}-{n}"
                if msg.get('role') == 'tool':
                    msg['tool_call_id'] = f"{msg['tool_call_id']}-{cycle}-{n - 1}"
            r.messages = out
        self.assertGreaterEqual(m.checkpoint['version'], 3)
        self.assertIn('edit_file 400 오류: deptCode 누락', m.checkpoint['failed_attempts'])
        self.assertIn('상위부서는 추가정보 탭', m.checkpoint['decisions'])

    # 11. raw history is archived and searchable
    def test_raw_history_is_archived_and_searchable(self):
        msgs = conversation(42, chars=1100, marker='UNIQUE_MARKER_42 ')
        r = runner(msgs, FakeLLM([reply(good())]))
        m = cm.manager(r)
        m.prepare(msgs, None)
        hits = m.store.search('unique_marker_42')
        self.assertTrue(hits)
        self.assertTrue(any(h['archive'].endswith('.jsonl') for h in hits))
        self.assertTrue(Path(self.tmp.name, 'context', 'checkpoints', '0001.json').is_file())

    # 12. concurrent compaction attempts do not create duplicate checkpoints
    def test_concurrent_compaction_is_serialized(self):
        a = runner(conversation(42, chars=1100), FakeLLM([reply(good())]))
        b = runner(conversation(42, chars=1100), FakeLLM([reply(good())]))
        ma, mb = cm.manager(a), cm.manager(b)
        with mb.store.lock() as held:
            self.assertTrue(held)
            out = ma.prepare(a.messages, None)
        self.assertIs(out, a.messages)
        self.assertIn('context.compact_skipped', kinds(a))
        mb.prepare(b.messages, None)
        self.assertEqual(mb.store.versions(), [1])
        with self.assertRaises(FileExistsError):
            mb.store.commit({**mb.checkpoint})

    # extra: a span larger than one prompt is folded chunk by chunk
    def test_oversized_span_is_compacted_in_chunks(self):
        cfg = Path(self.tmp.name) / 'cfg.json'
        cfg.write_text(json.dumps({'context_management': {'max_context_tokens': 16000, 'min_output_reserve_tokens': 2000,
                                                          'summary_output_tokens': 1500, 'recent_messages_target_tokens': 1500}}))
        os.environ['HARNESS_CONTEXT_CONFIG'] = str(cfg)
        llm = FakeLLM([reply(good()) for _ in range(6)])
        r = runner(conversation(80, chars=900, path=lambda i: f'f{i}.ts'), llm)
        m = cm.manager(r)
        out = m.prepare(r.messages, None)
        self.assertGreater(len(llm.calls), 1)
        self.assertTrue(integrity(out))

    # extra: real prompt token counts calibrate the estimate
    def test_usage_calibrates_the_token_estimate(self):
        llm = FakeLLM([reply('x', prompt_tokens=10000)])
        r = runner(conversation(2), llm)
        m = cm.manager(r)
        before = m.meter.count(r.messages)
        r.h.llm.chat([{'role': 'user', 'content': 'a' * 40000}])
        self.assertIsNotNone(m.meter.ratio)
        self.assertNotEqual(m.meter.count(r.messages), before)

    def test_unshrinkable_overflow_never_reaches_the_model(self):
        import context_budget

        class Base:
            def ask(self, messages, tools):
                return 'sent'
        Runner = context_budget.extend_context(Base)
        r = Runner()
        msgs = conversation(1)
        msgs[-1]['content'] = 'x' * 200000  # the newest result is never shortened
        base = runner(msgs, FakeLLM([]))
        r.__dict__.update(base.__dict__)
        with self.assertRaises(RuntimeError):
            r.ask(r.messages, None)

    def test_prompt_rebuild_by_the_harness_keeps_the_checkpoint(self):
        r = runner(conversation(42, chars=1100), FakeLLM([reply(good())]))
        m = cm.manager(r)
        m.prepare(r.messages, None)
        r.messages = r.messages[:2]  # what fresh() does after a failed patch
        out = m.prepare(r.messages, None)
        self.assertTrue(out[2]['content'].startswith(cm.CHECKPOINT_MARK))
        self.assertIn('context.checkpoint_reinserted', kinds(r))

    def test_disabled_by_setting(self):
        os.environ['HARNESS_CONTEXT_MANAGEMENT'] = '0'
        self.assertIsNone(cm.manager(runner(conversation(2), FakeLLM([]))))


if __name__ == '__main__':
    unittest.main()
