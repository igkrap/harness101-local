from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'local-only/harness'))
from test_feedback import feedback


class CombinedFrontendFeedbackTests(unittest.TestCase):
    def setUp(self):
        self.compiler = [f"src/Screen.tsx({n},1): error TS2322: Type 'bad{n}' is not assignable to 'FieldDefinition'." for n in range(1, 5)]
        self.lint = [f"frontend/src/Screen.tsx:{n}:1 error @typescript-eslint/no-unused-vars 'unused{n}' is defined but never used." for n in range(1, 5)]
        self.warning = 'frontend/src/App.tsx:1:1 warning react-hooks/exhaustive-deps OLD_WARNING'
        self.marker = '\nUse the actual installed declarations below; preserve unrelated code.'
        self.declaration = "Project declaration frontend/src/fields.ts:1\nexport type FieldDefinition = { type: 'text' | 'integer' };"

    def report(self, detailed):
        result = {'success': False, 'stdout': '\n'.join(self.lint + [self.warning] + self.compiler), 'stderr': ''}
        with patch('frontend_type_feedback.enrich', return_value=detailed):
            return feedback(Path('/unused'), 'frontend', result, 0)

    def test_both_error_groups_reach_focused_diagnostic_before_type_marker(self):
        detailed = '\n'.join(self.compiler[:3]) + self.marker + '\n\nInstalled API declarations:\n' + self.declaration
        report = self.report(detailed)
        diagnostic = report.split('Use the actual installed declarations', 1)[0]
        self.assertLess(len(diagnostic), 1200)
        for line in self.compiler[:3] + self.lint[:3]:
            self.assertIn(line, diagnostic)
        self.assertNotIn(self.compiler[3], report)
        self.assertNotIn(self.lint[3], report)
        self.assertNotIn('OLD_WARNING', report)
        self.assertIn(self.declaration, report)

    def test_large_declaration_records_are_omitted_whole_not_sliced(self):
        first = 'Project declaration frontend/src/First.ts:1\nexport type First = {' + ('x' * 2800) + '};'
        second = 'Project declaration frontend/src/Second.ts:1\nexport type Second = {' + ('y' * 1600) + '};'
        detailed = '\n'.join(self.compiler[:3]) + self.marker + '\n\nInstalled API declarations:\n' + first + '\n' + second
        report = self.report(detailed)
        self.assertIn(first, report)
        self.assertNotIn('export type Second', report)
        self.assertIn('declaration record(s) omitted', report)
        self.assertLess(len(report), 5000)

    def test_long_error_lines_retain_both_groups_and_diagnostic_tail(self):
        self.compiler[0] += ' ' + ('long detail ' * 150) + 'TYPE_CONCLUSION'
        self.lint[0] += ' ' + ('long detail ' * 150) + 'LINT_CONCLUSION'
        detailed = '\n'.join(self.compiler[:3]) + self.marker + '\n\nInstalled API declarations:\n' + self.declaration
        report = self.report(detailed)
        diagnostic = report.split('Use the actual installed declarations', 1)[0]
        self.assertLess(len(diagnostic), 1200)
        self.assertIn('TYPE_CONCLUSION', diagnostic)
        self.assertIn('LINT_CONCLUSION', diagnostic)
        self.assertIn(self.declaration, report)

    def test_lint_only_failure_excludes_warnings_and_keeps_compiler_infrastructure_error(self):
        self.compiler = []
        result = {'success': False, 'stdout': '\n'.join(self.lint + [self.warning]), 'stderr': 'Error: compiler executable unavailable'}
        with patch('frontend_type_feedback.enrich', return_value=''):
            report = feedback(Path('/unused'), 'frontend', result, 0)
        for line in self.lint[:3]:
            self.assertIn(line, report)
        self.assertNotIn(self.lint[3], report)
        self.assertNotIn('OLD_WARNING', report)
        self.assertIn('compiler executable unavailable', report)
