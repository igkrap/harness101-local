"""Mock model replies and temporary sources; no model, database, or build calls."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from types import MethodType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'local-only/harness'))
from call_budget import ask_with_recovery, snapshot
from workflow_policy import WorkflowPolicy, PolicyAuthority
import workflow_progress as progress


POLICY = WorkflowPolicy(True, True, 'checker', 8, 'fresh-owned',
                        PolicyAuthority('unit-workflow', 'a' * 64, '/trusted/policy.json', 'b' * 64))


def reply(*names):
    return {'role': 'assistant', 'content': None, 'tool_calls': [
        {'id': 'call-' + str(index), 'type': 'function', 'function': {'name': name, 'arguments': '{}'}}
        for index, name in enumerate(names)]}


class FakeRunner:
    def __init__(self, root):
        self.path = 'backend/src/main/java/example/RouteController.java'
        target = root / self.path; target.parent.mkdir(parents=True); target.write_text('class RouteController {}\n')
        self.args = SimpleNamespace(task='Change RouteController.java', context_profile='focused', max_rounds=32, ponytail='off')
        self.modes = ['backend']; self.used = 0; self.step = 0
        self.steps = [{'title': self.args.task, 'kind': 'change'}]
        self.events = []; self.sent = []; self.script = []; self.fresh_count = 0
        workspace = SimpleNamespace(root=root)
        def safe_path(path):
            target = (root / path).resolve(); target.relative_to(root); return target
        workspace.safe_path = safe_path
        self.h = SimpleNamespace(workspace=workspace, log_event=lambda kind, data: self.events.append((kind, data)))
        self.cp = SimpleNamespace(pending=False); self.memory = SimpleNamespace(entries=[], context=lambda: '')
        self.accepted = False; self.rejected_candidate = None
        self.rejected_new_files = SimpleNamespace(files={}); self._selected_check_progress = {}
        self.read = {self.path}; self.listed = {}; self.feedback = ''; self.baseline_feedback = ''
        self.messages = [{'role': 'system', 'content': 'same immutable task'}, {'role': 'user', 'content': self.block()}]
        self.tool_schema = [{'type': 'function', 'function': {'name': 'read_file', 'parameters': {'type': 'object'}}}]

    def block(self):
        return 'CURRENT FILE ' + self.path + '\n' + self.h.workspace.safe_path(self.path).read_text() + '\n'

    def tools(self):
        return self.tool_schema

    def ask(self, messages, tools=None):
        self.used += 1; self.sent.append((copy.deepcopy(messages), copy.deepcopy(tools)))
        result = self.script.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result

    def fresh(self, reason=''):
        self.fresh_count += 1
        text, paths = snapshot(self)
        self.messages = [{'role': 'system', 'content': 'same immutable task'}, {'role': 'user', 'content': text}]
        self.read = paths

    def current_context(self):
        return snapshot(self)

    def complete_read(self, *names):
        self.script.append(reply(*(names or ('read_file',))))
        return ask_with_recovery(self)


class WorkflowProgressTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve(); self.runner = FakeRunner(self.root)
        self.policy = patch('workflow_policy.get_policy', return_value=POLICY)
        self.policy.start(); self.addCleanup(self.policy.stop)

    def test_eight_completed_read_only_responses_transition_once_and_keep_all_tools(self):
        runner = self.runner
        for _ in range(8): runner.complete_read('read_file', 'search_code', 'list_files')
        self.assertEqual(runner._workflow_progress['read_only_rounds'], 8)
        self.assertEqual(runner._workflow_progress['phase'], 'discovery')
        original = copy.deepcopy(runner.messages)
        runner.complete_read()
        self.assertEqual(runner._workflow_progress['phase'], 'act')
        self.assertEqual(runner.messages[:len(original)], original, 'Prior prompt prefix must stay unchanged')
        self.assertIn('remaining model calls before the next request=24', runner.sent[8][0][-1]['content'])
        runner.complete_read()
        self.assertEqual(sum(kind == 'autonomy.workflow_progress' for kind, _ in runner.events), 1)
        self.assertEqual(sum(progress.ANCHOR in message.get('content', '') for message in runner.messages), 1)
        self.assertTrue(all(schema == runner.tool_schema for _, schema in runner.sent))
        self.assertEqual(runner.read, {runner.path})

    def test_fixed_frontend_screen_receives_act_reminder_after_five_reads(self):
        runner = FakeRunner(self.root / 'frontend-case')
        runner.path = 'frontend/src/screens/ItemMaster.tsx'
        target = runner.h.workspace.root / runner.path
        target.parent.mkdir(parents=True)
        target.write_text('export function ItemMaster() { return null; }\n')
        runner.read = {runner.path}
        runner.messages = [{'role': 'system', 'content': 'same immutable task'},
                           {'role': 'user', 'content': runner.block()}]
        runner.modes = ['frontend', 'framework']
        runner.args.fixed_acceptance = {'script_sha256': 'a' * 64}
        with patch('fixed_acceptance.validate', return_value=runner.args.fixed_acceptance):
            for _ in range(5):
                runner.complete_read()
            self.assertEqual(runner._workflow_progress['read_only_rounds'], 5)
            runner.complete_read()
        self.assertEqual(runner._workflow_progress['phase'], 'act')
        self.assertIn(progress.ANCHOR, runner.sent[5][0][-1]['content'])
        self.assertEqual(runner.read, {runner.path})
        self.assertTrue(all(schema == runner.tool_schema for _, schema in runner.sent))

    def test_natural_mixed_check_screen_task_gets_act_reminder_and_stall_guard(self):
        runner = FakeRunner(self.root / 'natural-screen')
        runner.path = 'frontend/src/screens/ItemMaster.tsx'
        target = runner.h.workspace.root / runner.path
        target.parent.mkdir(parents=True)
        target.write_text("export const meta = { title: '품목 등록' };\nexport function ItemMaster() { return null; }\n")
        runner.args.task = '품목 등록 화면 편집 패널을 버튼으로 접게 해줘'
        runner.args.context_profile = 'legacy'
        runner.modes = ['frontend', 'framework', 'backend']
        runner.read = {runner.path}
        runner.messages = [{'role': 'system', 'content': 'task'}, {'role': 'user', 'content': runner.block()}]
        for _ in range(progress.SCREEN_DISCOVERY_LIMIT):
            runner.complete_read()
        runner.complete_read()
        self.assertEqual(runner._workflow_progress['phase'], 'act')
        self.assertIn(progress.ANCHOR, runner.sent[-1][0][-1]['content'])
        for _ in range(progress.SCREEN_STALL_EXTRA_RESPONSES):
            runner.complete_read()
        start = runner._workflow_progress['first_read_at']
        with patch('workflow_progress.time.monotonic', return_value=start + progress.SCREEN_STALL_SECONDS + 1):
            self.assertTrue(progress.stop_if_stalled(runner))
        self.assertEqual(runner.events[-1][0], 'autonomy.stalled')
        runner.cp.pending = True
        self.assertFalse(progress.stop_if_stalled(runner))

    def test_backend_intent_does_not_enter_screen_only_discovery_policy(self):
        runner = FakeRunner(self.root / 'mixed-backend')
        runner.path = 'frontend/src/screens/ItemMaster.tsx'
        target = runner.h.workspace.root / runner.path
        target.parent.mkdir(parents=True)
        target.write_text("export const meta = { title: '품목 등록' };\n")
        runner.args.task = '품목 등록 화면 저장 API와 DB 테이블을 만들어줘'
        runner.args.context_profile = 'legacy'
        runner.modes = ['frontend', 'framework', 'backend']
        runner.read = {runner.path}
        runner.messages = [{'role': 'system', 'content': 'task'}, {'role': 'user', 'content': runner.block()}]
        for _ in range(10):
            runner.complete_read()
        self.assertIsNone(getattr(runner, '_workflow_progress', None))

    def test_fresh_new_reads_lists_and_compaction_do_not_reset_accumulated_rounds(self):
        runner = self.runner
        for _ in range(4): runner.complete_read()
        runner.fresh('tool error')
        for _ in range(4): runner.complete_read('list_files')
        progress.before_request(runner)
        self.assertEqual(runner._workflow_progress['read_only_rounds'], 8)
        runner.fresh('context budget threshold')
        self.assertIn(progress.ANCHOR, runner.messages[1]['content'])
        progress.before_request(runner)
        self.assertEqual(sum(kind == 'autonomy.workflow_progress' for kind, _ in runner.events), 1)
        self.assertEqual(runner._workflow_progress['read_only_rounds'], 8)

    def test_only_complete_current_primary_source_starts_the_discovery_counter(self):
        runner = self.runner
        runner.messages[1]['content'] = 'Only a path and partial source: ' + runner.path
        for _ in range(8): runner.complete_read()
        self.assertEqual(runner._workflow_progress['read_only_rounds'], 0)
        runner.messages[1]['content'] = runner.block(); runner.read.clear()
        runner.complete_read()
        self.assertEqual(runner._workflow_progress['read_only_rounds'], 0)
        runner.read.add(runner.path); runner.complete_read()
        self.assertEqual(runner._workflow_progress['read_only_rounds'], 1)

    def test_retained_whole_read_can_preserve_an_already_supplied_primary_after_compaction(self):
        runner = self.runner
        for _ in range(7): runner.complete_read()
        runner.messages = [{'role': 'system', 'content': 'same immutable task'},
            {'role': 'user', 'content': 'compacted context'},
            {'role': 'assistant', 'tool_calls': [{'id': 'retained', 'function': {'name': 'read_file', 'arguments': json.dumps({'path': runner.path})}}]},
            {'role': 'tool', 'tool_call_id': 'retained', 'content': json.dumps({'content': runner.h.workspace.safe_path(runner.path).read_text()})}]
        runner.complete_read(); progress.before_request(runner)
        self.assertEqual(runner._workflow_progress['phase'], 'act')

    def test_actual_compaction_json_anchor_preserves_primary_and_eighth_response_transition(self):
        from recent_context import compact
        runner = self.runner
        for _ in range(7): runner.complete_read()
        runner.messages.append({'role': 'user', 'content': 'Expired discovery details ' * 500})
        for index in range(4):
            path = 'backend/src/main/java/example/Reference' + str(index) + '.java'
            target = self.root / path; target.write_text('class Reference' + str(index) + ' {}\n')
            identifier = 'recorded-read-' + str(index)
            runner.messages.extend([
                {'role': 'assistant', 'tool_calls': [{'id': identifier, 'function': {'name': 'read_file', 'arguments': json.dumps({'path': path})}}]},
                {'role': 'tool', 'tool_call_id': identifier, 'content': json.dumps({'content': target.read_text()})}])
        self.assertTrue(compact(runner, runner.tools(), 8192, 32768, 'context budget threshold'))
        anchor = json.loads(runner.messages[1]['content'])
        self.assertIn(runner.block(), anchor['current_source'])
        self.assertNotIn(runner.block(), runner.messages[1]['content'], 'Primary must only occur in the encoded source anchor')
        self.assertIn(runner.path, runner.read)
        runner.complete_read(); progress.before_request(runner)
        self.assertEqual(runner._workflow_progress['read_only_rounds'], 8)
        self.assertEqual(runner._workflow_progress['phase'], 'act')
        self.assertEqual(sum(kind == 'autonomy.workflow_progress' for kind, _ in runner.events), 1)

    def test_json_anchor_requires_current_complete_body_read_membership_and_size_bounds(self):
        for reason in ('partial', 'stale', 'unrelated-key', 'non-string', 'oversized-anchor', 'oversized-source', 'not-read'):
            with self.subTest(reason=reason):
                runner = FakeRunner(self.root / reason)
                for _ in range(7): runner.complete_read()
                source = runner.block()
                anchor = {'current_source': source}
                if reason == 'partial': anchor['current_source'] = source[:30]
                elif reason == 'stale': anchor['current_source'] = source.replace('class RouteController', 'class OldController')
                elif reason == 'unrelated-key': anchor = {'other': source}
                elif reason == 'non-string': anchor['current_source'] = {'text': source}
                elif reason == 'oversized-anchor': anchor['padding'] = 'x' * progress.MAX_COMPACT_ANCHOR_CHARS
                elif reason == 'oversized-source': anchor['current_source'] = source + 'x' * progress.MAX_CURRENT_SOURCE_CHARS
                elif reason == 'not-read': runner.read.clear()
                runner.messages = [{'role': 'system', 'content': 'immutable task'}, {'role': 'user', 'content': json.dumps(anchor)}]
                runner.complete_read(); progress.before_request(runner)
                self.assertEqual(runner._workflow_progress['phase'], 'discovery')
                self.assertFalse(any(kind == 'autonomy.workflow_progress' for kind, _ in runner.events))

    def test_partial_or_stale_retained_content_cannot_supply_current_primary(self):
        runner = self.runner
        for _ in range(8): runner.complete_read()
        runner.messages = [{'role': 'user', 'content': 'no current source'},
            {'role': 'assistant', 'tool_calls': [{'id': 'partial', 'function': {'name': 'read_file', 'arguments': json.dumps({'path': runner.path})}}]},
            {'role': 'tool', 'tool_call_id': 'partial', 'content': json.dumps({'content': 'partial'})}]
        progress.before_request(runner)
        self.assertEqual(runner._workflow_progress['phase'], 'discovery')

    def test_planning_plain_text_finish_and_duplicate_observation_are_not_discovery_rounds(self):
        runner = self.runner
        for message in ({'content': 'Implementation plan'}, reply('finish'), reply('write_file')):
            runner.used += 1; progress.note_completed_response(runner, message)
        self.assertEqual(runner._workflow_progress['read_only_rounds'], 0)
        runner.used += 1; message = reply('read_file', 'search_code')
        progress.note_completed_response(runner, message); progress.note_completed_response(runner, message)
        self.assertEqual(runner._workflow_progress['read_only_rounds'], 1)

    def test_read_only_loop_after_a_failed_edit_stops_the_run(self):
        runner = self.runner
        runner.used += 1; progress.note_completed_response(runner, reply('edit_file'))
        runner.accepted = True
        for i in range(progress.POST_EDIT_READ_LIMIT - 1):
            runner.used += 1; progress.note_completed_response(runner, reply('read_file'))
            self.assertFalse(progress.stop_if_stalled(runner))
        runner.used += 1; progress.note_completed_response(runner, reply('edit_file'))
        for i in range(progress.POST_EDIT_READ_LIMIT):
            runner.used += 1; progress.note_completed_response(runner, reply('read_file'))
        self.assertTrue(progress.stop_if_stalled(runner))

    def test_timed_out_request_is_not_counted_and_remaining_calls_use_actual_budget(self):
        runner = self.runner
        runner.script = [TimeoutError('timed out'), reply('read_file')]
        ask_with_recovery(runner)
        self.assertEqual(runner.used, 2)
        self.assertEqual(runner._workflow_progress['read_only_rounds'], 1)
        self.assertEqual(runner.fresh_count, 1)

    def test_actual_candidate_or_accepted_progress_keeps_repair_and_verification_first(self):
        for candidate in ('pending', 'accepted', 'failed-memory', 'rejected-new'):
            with self.subTest(candidate=candidate):
                runner = FakeRunner(self.root / candidate)
                for _ in range(8): runner.complete_read()
                progress.before_request(runner)
                runner.cp.pending = candidate == 'pending'; runner.accepted = candidate == 'accepted'
                runner.memory.entries = [{'path': runner.path, 'candidate_sha': 'changed'}] if candidate == 'failed-memory' else []
                runner.rejected_new_files.files = {'new.java': {}} if candidate == 'rejected-new' else {}
                text = progress.context(runner)
                self.assertNotIn(progress.ANCHOR, text)
                self.assertIn('repair and verification feedback take precedence', text)
                self.assertIn('remaining model calls', text)
                progress.before_request(runner)
                self.assertIn('repair and verification feedback take precedence', runner.messages[-1]['content'])
                self.assertEqual(runner._workflow_progress['read_only_rounds'], 8)

    def test_disabled_absent_authority_legacy_frontend_and_mixed_profiles_are_unchanged(self):
        for profile, modes, policy in [('legacy', ['backend'], POLICY), ('focused', ['frontend'], POLICY),
                ('focused', ['backend', 'framework'], POLICY), ('focused', ['backend'], WorkflowPolicy()),
                ('focused', ['backend'], WorkflowPolicy(True, True, 'checker', 8, 'fresh-owned', None))]:
            with self.subTest(profile=profile, modes=modes), patch('workflow_policy.get_policy', return_value=policy):
                runner = FakeRunner(self.root / (profile + '-' + '-'.join(modes) + '-' + str(id(policy))))
                runner.args.context_profile = profile; runner.modes = modes
                runner.complete_read(); self.assertFalse(hasattr(runner, '_workflow_progress'))
                self.assertEqual(progress.context(runner), '')

    def test_zero_discovery_limit_does_not_enable_progress_messages(self):
        with patch('workflow_policy.get_policy', return_value=WorkflowPolicy(True, True, 'checker', 0, 'fresh-owned', POLICY.authority)):
            self.runner.complete_read()
            self.assertFalse(hasattr(self.runner, '_workflow_progress'))


class FixtureContextTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve(); self.runner = FakeRunner(self.root)
        folder = self.root / 'backend/src/main/resources/db/migration'; folder.mkdir(parents=True)
        (folder / 'V1__schema.sql').write_text("CREATE TABLE legacy(id BIGINT); INSERT INTO legacy VALUES (7654321); -- BASELINE-SEED-SENTINEL")
        from autonomy_runtime import Runner
        self.base = next(cls for cls in Runner.__mro__ if 'backend_context' in cls.__dict__)
        self.runner.backend_context = MethodType(self.base.backend_context, self.runner)
        self.runner.frontend_context = lambda: ''
        self.runner.current_context = lambda: snapshot(self.runner)
        self.runner.rejected_new_context = lambda: ''

    def test_checker_owned_context_omits_legacy_values_and_preserves_baseline_contract(self):
        with patch('workflow_policy.get_policy', return_value=POLICY):
            text = self.runner.backend_context()
            self.assertIn('fresh owned test databases', text)
            self.assertIn('Baseline schema', text)
            self.assertIn('V1__schema.sql', text)
            self.assertNotIn('BASELINE-SEED-SENTINEL', text)
            self.assertNotIn('7654321', text)
            self.assertNotIn('UPDATE by existing IDs', text)
            self.assertNotIn('isolate_spring_test', text)
            self.base.fresh(self.runner)
            prompt = self.runner.messages[0]['content']
            self.assertIn('Create application sample rows only when the task explicitly requests them', prompt)
            self.assertNotIn('preserve seed row IDs and count', prompt)

    def test_legacy_policy_and_explicit_seed_request_keep_previous_guidance(self):
        for policy, explicit in [(WorkflowPolicy(), False), (POLICY, True)]:
            with self.subTest(explicit=explicit), patch('workflow_policy.get_policy', return_value=policy), \
                    patch('seed_updates.is_seed_request', return_value=explicit):
                if hasattr(self.runner, '_backend_context_cache'): del self.runner._backend_context_cache
                text = self.runner.backend_context()
                self.assertIn('BASELINE-SEED-SENTINEL', text)
                self.assertIn('UPDATE by existing IDs', text)
                self.base.fresh(self.runner)
                prompt = self.runner.messages[0]['content']
                self.assertIn('preserve seed row IDs and count', prompt)
                if explicit: self.assertIn('Seed Update Guide', prompt)


class MigrationReadReceiptTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve(); self.runner = FakeRunner(self.root)
        self.path = 'backend/src/main/resources/db/migration/V2__change.sql'
        target = self.root / self.path; target.parent.mkdir(parents=True)
        self.raw = b'ALTER TABLE catalog ADD COLUMN note TEXT;\r\n'; target.write_bytes(self.raw)
        self.runner.args.task = 'Change ' + self.path
        self.runner.steps = [{'title': self.runner.args.task, 'kind': 'change'}]
        self.runner.read = {self.path}
        self.runner._job_migrations = SimpleNamespace(enabled=True)
        self.policy = patch('workflow_policy.get_policy', return_value=WorkflowPolicy())
        self.policy.start(); self.addCleanup(self.policy.stop)

    def test_only_fully_supplied_current_sql_records_its_exact_byte_sha(self):
        text, paths = snapshot(self.runner)
        self.assertEqual(paths, {self.path})
        self.assertIn(self.raw.decode('utf-8'), text)
        self.assertEqual(self.runner._migration_full_reads, {self.path: hashlib.sha256(self.raw).hexdigest()})

    def test_oversized_budget_omitted_and_retained_sources_do_not_create_receipts(self):
        for reason in ('oversized', 'budget', 'retained'):
            with self.subTest(reason=reason):
                target = self.root / self.path
                target.write_bytes(b'x' * 9001 if reason == 'oversized' else self.raw)
                self.runner._context_supplied_paths = {self.path} if reason == 'retained' else set()
                with patch('source_progress.progress_context', return_value='P' * 10000 if reason == 'budget' else ''):
                    _, paths = snapshot(self.runner)
                self.assertNotIn(self.path, paths)
                self.assertFalse(hasattr(self.runner, '_migration_full_reads'))

    def test_missing_or_disabled_ledger_and_non_sql_sources_leave_metadata_unchanged(self):
        for ledger in (None, SimpleNamespace(enabled=False)):
            with self.subTest(ledger=ledger):
                self.runner._job_migrations = ledger
                snapshot(self.runner)
                self.assertFalse(hasattr(self.runner, '_migration_full_reads'))
        self.runner._job_migrations = SimpleNamespace(enabled=True)
        self.runner.args.task = 'Change RouteController.java'; self.runner.steps = [{'title': self.runner.args.task}]
        self.runner.read = {self.runner.path}
        snapshot(self.runner)
        self.assertFalse(hasattr(self.runner, '_migration_full_reads'))


if __name__ == '__main__':
    unittest.main()


class ReadSuspensionTests(unittest.TestCase):
    def runner(self, rounds, phase='act'):
        import workflow_progress
        r = SimpleNamespace(h=SimpleNamespace(log_event=Mock()), used=8, read={'frontend/src/screens/A.tsx'})
        r._workflow_progress = {'read_only_rounds': rounds, 'phase': phase, 'primary': 'frontend/src/screens/A.tsx',
                                'mutation_seen': False, 'memory_stamp': None, 'first_read_at': None, 'last_completed_call': 0}
        return workflow_progress, r

    def test_reads_refused_only_after_ignored_act_reminder(self):
        wp, r = self.runner(4)
        policy = SimpleNamespace(discovery_round_limit=3)
        with patch.object(wp, '_policy', return_value=policy), patch.object(wp, '_mutation_priority', return_value=False):
            self.assertIsNone(wp.read_suspended(r, 'read_file', {'path': 'frontend/src/screens/A.tsx'}))
            r._workflow_progress['read_only_rounds'] = 5
            refused = wp.read_suspended(r, 'read_file', {'path': 'frontend/src/screens/A.tsx'})
            self.assertIn('READ SUSPENDED', refused['error'])
            self.assertIsNone(wp.read_suspended(r, 'read_file', {'path': 'frontend/src/framework/New.tsx'}))
            self.assertIsNone(wp.read_suspended(r, 'apply_ast_edits'))
            self.assertIsNone(wp.read_suspended(r, 'inspect_code', {'action': 'edit_ranges', 'path': 'x.tsx'}))
            self.assertIsNotNone(wp.read_suspended(r, 'inspect_code', {'action': 'symbol', 'path': 'frontend/src/screens/A.tsx'}))
            self.assertIsNone(wp.read_suspended(r, 'search_code', {'query': 'x'}))
            wp.read_suspended(r, 'read_file', {'path': 'frontend/src/screens/A.tsx'})
            self.assertEqual(r.h.log_event.call_count, 1)
        with patch.object(wp, '_policy', return_value=policy), patch.object(wp, '_mutation_priority', return_value=True):
            self.assertIsNone(wp.read_suspended(r, 'read_file', {'path': 'frontend/src/screens/A.tsx'}))

    def test_discovery_phase_never_refuses(self):
        wp, r = self.runner(9, phase='discovery')
        with patch.object(wp, '_policy', return_value=SimpleNamespace(discovery_round_limit=3)):
            self.assertIsNone(wp.read_suspended(r, 'read_file', {'path': 'frontend/src/screens/A.tsx'}))


class EditAttemptResetsReadsTests(unittest.TestCase):
    def test_edit_attempt_restores_read_allowance(self):
        import workflow_progress as wp
        r = SimpleNamespace(h=SimpleNamespace(log_event=Mock()), used=9, read={'frontend/src/screens/A.tsx'})
        r._workflow_progress = {'read_only_rounds': 6, 'phase': 'act', 'primary': 'frontend/src/screens/A.tsx',
                                'mutation_seen': False, 'memory_stamp': None, 'first_read_at': None, 'last_completed_call': 8}
        message = {'tool_calls': [{'function': {'name': 'apply_ast_edits', 'arguments': '{}'}}]}
        with patch.object(wp, '_policy', return_value=SimpleNamespace(discovery_round_limit=3)), \
                patch.object(wp, '_mutation_priority', return_value=False), patch.object(wp, '_primary_ready', return_value=None):
            wp.note_completed_response(r, message)
            self.assertEqual(r._workflow_progress['read_only_rounds'], 0)
            self.assertIsNone(wp.read_suspended(r, 'read_file', {'path': 'frontend/src/screens/A.tsx'}))


class ReadScopeTests(unittest.TestCase):
    def test_reads_outside_the_screen_import_closure_are_refused(self):
        import workflow_progress as wp
        root = Path(__file__).resolve().parents[2] / 'local-only'
        r = SimpleNamespace(h=SimpleNamespace(log_event=Mock(), workspace=SimpleNamespace(root=root)), cp=SimpleNamespace(_records={}))
        policy = SimpleNamespace(authority='screen-source', discovery_round_limit=3)
        with patch.object(wp, '_policy', return_value=policy), \
                patch.object(wp, '_screen_target', return_value='frontend/src/screens/ItemMaster.tsx'):
            self.assertIsNone(wp.outside_scope(r, 'read_file', {'path': 'frontend/src/framework/BusinessWorkspace.tsx'}))
            self.assertIsNone(wp.outside_scope(r, 'read_file', {'path': 'frontend/src/framework/TabbedPanel.tsx'}))
            refused = wp.outside_scope(r, 'read_file', {'path': 'frontend/src/framework/workspace/registry.ts'})
            self.assertIn('OUT OF SCOPE', refused['error'])
            self.assertIsNone(wp.outside_scope(r, 'read_file', {'path': 'backend/pom.xml'}))
            r.cp._records = {'frontend/src/framework/workspace/registry.ts': {}}
            self.assertIsNone(wp.outside_scope(r, 'read_file', {'path': 'frontend/src/framework/workspace/registry.ts'}))
        with patch.object(wp, '_policy', return_value=None):
            self.assertIsNone(wp.outside_scope(r, 'read_file', {'path': 'frontend/src/framework/workspace/registry.ts'}))


class ApproachScopeTests(unittest.TestCase):
    def test_act_phase_narrows_reads_to_planner_named_files(self):
        import os
        import workflow_progress as wp
        root = Path(__file__).resolve().parents[2] / 'local-only'
        r = SimpleNamespace(h=SimpleNamespace(log_event=Mock(), workspace=SimpleNamespace(root=root)), cp=SimpleNamespace(_records={}),
                            _workflow_progress={'phase': 'discovery'})
        policy = SimpleNamespace(authority='screen-source', discovery_round_limit=3)
        with patch.dict(os.environ, {'HARNESS_TASK_APPROACH': 'BusinessWorkspace.tsx에 prop 추가, ItemMaster.tsx에서 전달'}), \
                patch.object(wp, '_policy', return_value=policy), \
                patch.object(wp, '_screen_target', return_value='frontend/src/screens/ItemMaster.tsx'):
            self.assertEqual(wp.approach_files(r), ['frontend/src/framework/BusinessWorkspace.tsx', 'frontend/src/screens/ItemMaster.tsx'])
            self.assertIsNone(wp.outside_scope(r, 'read_file', {'path': 'frontend/src/framework/Panel.tsx'}))
            r._workflow_progress['phase'] = 'act'
            self.assertIn('OUT OF SCOPE', wp.outside_scope(r, 'read_file', {'path': 'frontend/src/framework/Panel.tsx'})['error'])
            self.assertIsNone(wp.outside_scope(r, 'read_file', {'path': 'frontend/src/framework/BusinessWorkspace.tsx'}))
