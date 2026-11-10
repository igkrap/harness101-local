import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'local-only/harness'))


class FrontendTypeFeedbackTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / 'frontend/src/App.tsx'
        self.source.parent.mkdir(parents=True)
        self.source.write_text('const a=1;\nconst b=2;\nconst c=3;\nexport function App(){return <Icon icon="box"/>;}\n')
        package = self.root / 'frontend/node_modules/@astryxdesign/core'
        folder = package / 'dist/Icon'
        folder.mkdir(parents=True)
        (package / 'package.json').write_text(json.dumps({'name': '@astryxdesign/core', 'version': 'fixture'}))
        (folder / 'globalIconRegistry.d.ts').write_text(
            "/** Built-in semantic names. */\nexport type IconName = 'close' | 'wrench';\n"
            '/** Extension keys must be registered before use. */\nexport type NamespacedIconName = `${string}:${string}`;\n'
        )
        (folder / 'Icon.d.ts').write_text('export type IconType = (props: Record<string, unknown>) => unknown;\n')
        self.error = "src/App.tsx(4,35): error TS2322: Type '\"box\"' is not assignable to type '`${string}:${string}` | IconName | IconType'."

    def tearDown(self):
        self.temp.cleanup()

    def test_actual_type_definitions_and_candidate_lines_reach_feedback(self):
        from frontend_type_feedback import enrich
        report = enrich(self.root, self.error)
        self.assertIn(self.error, report)
        self.assertIn("'close' | 'wrench'", report)
        self.assertIn('must be registered', report)
        self.assertIn('globalIconRegistry.d.ts', report)
        self.assertIn('4:', report)
        self.assertIn('icon="box"', report)
        self.assertIn('do not replace one guessed value', report.lower())
        self.assertLessEqual(len(report), 4900)

    def test_feedback_does_not_rerun_compiler_or_request_model(self):
        from frontend_type_feedback import enrich
        real_run = subprocess.run
        with patch('subprocess.run', wraps=real_run) as calls:
            report = enrich(self.root, self.error)
        self.assertIn('IconName', report)
        self.assertTrue(calls.call_args_list)
        for call in calls.call_args_list:
            command = call.args[0]
            self.assertNotIn('npx', command)
            self.assertNotIn('tsc', command)
            self.assertTrue(str(command[1]).endswith('ast_outline.cjs'))
            payload = json.loads(call.kwargs['input'])
            self.assertTrue(all(key in payload for key in ('path', 'source', 'symbol')))

    def test_non_typescript_error_keeps_existing_feedback_path(self):
        from frontend_type_feedback import enrich
        self.assertEqual(enrich(self.root, 'src/App.tsx:4:1 error no-unused-vars'), '')

    def test_missing_module_reports_actual_installed_exports(self):
        from frontend_type_feedback import enrich
        package = self.root / 'frontend/node_modules/@astryxdesign/core/package.json'
        package.write_text(json.dumps({'version': 'fixture', 'exports': {'./Card': './dist/Card.js', './VStack': './dist/VStack.js'}}))
        report = enrich(self.root, "src/App.tsx(1,1): error TS2307: Cannot find module '@astryxdesign/core/Ghost' or its corresponding type declarations.")
        self.assertIn('absent from the installed exports map', report)
        self.assertIn('./Card, ./VStack', report)
        self.assertIn('Repeating its import does not resolve it', report)
        self.assertLessEqual(len(report), 4900)

    def test_export_wildcard_is_not_falsely_reported_as_missing(self):
        from installed_module_evidence import missing_module_evidence
        package = self.root / 'frontend/node_modules/@astryxdesign/core/package.json'
        package.write_text(json.dumps({'exports': {'./widgets/*': './dist/*.js'}}))
        report = missing_module_evidence(self.root, "Cannot find module '@astryxdesign/core/widgets/Panel'")
        self.assertIn('has an export entry', report)
        self.assertNotIn('absent from', report)
        self.assertEqual(missing_module_evidence(self.root, "Cannot find module '../../private'"), '')

    def test_feedback_does_not_read_candidate_outside_workspace(self):
        from frontend_type_feedback import enrich
        with tempfile.TemporaryDirectory() as other:
            file = Path(other) / 'Outside.tsx'
            file.write_text('PRIVATE_TEST_MARKER')
            report = enrich(self.root, f'{file}(1,1): error TS2322: Type invalid for IconName.')
            self.assertNotIn('PRIVATE_TEST_MARKER', report)

    def test_frontend_check_feedback_includes_installed_values(self):
        from test_feedback import feedback
        report = feedback(self.root, 'frontend', {'success': False, 'stdout': self.error, 'stderr': ''}, 0)
        self.assertIn('[frontend]', report)
        self.assertIn("'close' | 'wrench'", report)

    @unittest.skipUnless((ROOT / 'local-only/frontend/node_modules/@astryxdesign/core').is_dir(), 'project no longer installs the astryx design system')
    def test_actual_installed_icon_type_is_resolved(self):
        from installed_type_records import declarations
        report = '\n'.join(declarations(ROOT / 'local-only', ('IconName', 'IconType')))
        self.assertIn("'viewColumns'", report)
        self.assertIn("'wrench'", report)
        self.assertIn('NamespacedIconName', report)
        self.assertIn('registerIcons', report)

    def test_recorded_type_failure_is_enriched_before_next_model_call(self):
        from autonomy_runtime import Runner
        from test_autonomy import native
        from types import SimpleNamespace
        from unittest.mock import Mock
        args = SimpleNamespace(task='사이드 패널 로고 추가', workspace=str(self.root), check='frontend', max_rounds=0, ponytail='off', llm_url='http://127.0.0.1:8099/v1', model='fixture')
        runner = Runner(args, native.Harness)
        runner.h.evidence_path = self.root / 'events.jsonl'
        runner.h.llm.chat = Mock(side_effect=AssertionError('feedback must not request a model'))
        runner.steps = [{'title': args.task, 'kind': 'change'}]
        runner.memory.context = Mock(return_value=self.error)
        try:
            runner.fresh()
            prompt = '\n'.join(message['content'] for message in runner.messages)
            self.assertIn("'close' | 'wrench'", prompt)
            self.assertIn('RECORDED failures', prompt)
            runner.h.llm.chat.assert_not_called()
        finally:
            if getattr(runner.h, '_code_intelligence', None):
                runner.h._code_intelligence.close()

    def test_full_compiler_explanation_and_actual_expected_type_names_are_prioritized(self):
        from frontend_type_feedback import enrich
        output="src/App.tsx(4,35): error TS2322: Type '{ idKey: string; onRowClick: (item: InventoryItem) => void; }' is not assignable to type 'IntrinsicAttributes & TableProps<InventoryItem> & { ref?: Ref<HTMLTableElement> }'.\n  Property 'onRowClick' does not exist on type 'TableProps<InventoryItem>'. Did you mean 'onClick'?\nsrc/App.tsx(4,60): error TS2322: Type '\"number\"' is not assignable to type 'TextInputType | undefined'."
        with patch('frontend_type_feedback.declarations',return_value=['ACTUAL_EXPECTED_TYPE_API'])as called:
            report=enrich(self.root,output)
        ids=called.call_args.args[1]
        self.assertIn('TableProps',ids)
        self.assertIn('TextInputType',ids)
        self.assertNotIn('RowClick',ids)
        self.assertNotIn('Key',ids)
        self.assertLess(ids.index('TextInputType'),ids.index('TableProps'))
        self.assertIn("Property 'onRowClick' does not exist",report)
        self.assertIn("Did you mean 'onClick'?",report)
        self.assertLess(report.index('ACTUAL_EXPECTED_TYPE_API'),report.index('--- '+str(self.source.resolve())))

    @unittest.skipUnless((ROOT / 'local-only/frontend/node_modules/@astryxdesign/core').is_dir(), 'project no longer installs the astryx design system')
    def test_actual_compact_declarations_include_useful_members_instead_of_only_comments(self):
        from installed_type_records import declarations
        records=declarations(ROOT/'local-only',('TextInputType','TableProps','TableColumn'))
        report='\n'.join(records)
        self.assertIn('TextInputType',report)
        self.assertIn("'text'",report)
        self.assertIn('TableProps',report)
        self.assertIn('renderCell',report)


if __name__ == '__main__':
    unittest.main()
