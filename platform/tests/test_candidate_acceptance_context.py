import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'local-only/harness'))
import candidate_blocks


class CandidateAcceptanceContextTests(unittest.TestCase):
    def test_latest_framework_error_does_not_replace_acceptance_constraints(self):
        runner = SimpleNamespace(args=SimpleNamespace(task='Move editor'), feedback='Exactly one form required: actual 2', requirement_gate=SimpleNamespace(context=Mock(return_value='C5: right-side form required')))
        proposal = dict(path='frontend/src/App.tsx', snapshot_id='snapshot', source_hash='hash', edits=[])
        with patch.object(candidate_blocks, 'faulty_candidate_nodes', return_value=[]), patch.object(candidate_blocks, 'unused_binding_targets', return_value=([], '')), patch.object(candidate_blocks, 'order_candidate_nodes', return_value=([], '')):
            text = candidate_blocks.format_candidate_context(runner, proposal, [])
        self.assertIn('Exactly one form required: actual 2', text)
        self.assertIn('C5: right-side form required', text)
        runner.requirement_gate.context.assert_called_once()

    def test_optional_gate_context_does_not_break_basic_runner(self):
        runner = SimpleNamespace(args=SimpleNamespace(task='Repair'), feedback='compiler error')
        proposal = dict(path='frontend/src/App.tsx', snapshot_id='snapshot', source_hash='hash', edits=[])
        with patch.object(candidate_blocks, 'faulty_candidate_nodes', return_value=[]), patch.object(candidate_blocks, 'unused_binding_targets', return_value=([], '')), patch.object(candidate_blocks, 'order_candidate_nodes', return_value=([], '')):
            self.assertIn('compiler error', candidate_blocks.format_candidate_context(runner, proposal, []))
