"""Framework components reach the model as usage (API.txt + props), not as their internals."""
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'local-only/harness'))
import framework_docs
import import_graph

API = '''COMPOSABLE ERP FRAMEWORK
 overview text

COMPOSITION GUIDE
 compose screens

GRID THINGS (rows)
 <Grid rows={rows} onSelect={pick}/> row click selects.

PANEL STUFF
 <Panel title="x"/> frames content.
'''


class FrameworkDocsTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        fw = self.root / 'frontend/src/framework'
        (self.root / 'frontend/src/screens').mkdir(parents=True)
        fw.mkdir(parents=True)
        (fw / 'API.txt').write_text(API)
        (fw / 'Grid.tsx').write_text('export function Grid(){ return SECRET_INTERNALS; }')
        (fw / 'Panel.tsx').write_text('export function Panel(){ return null; }')
        (fw / 'index.ts').write_text("export { Grid } from './Grid';\nexport { Panel } from './Panel';\n")
        (self.root / 'frontend/src/screens/Items.tsx').write_text(
            "import { Grid } from '../framework';\nexport const meta={title:'품목'};\nexport default function Items(){ return (<Grid rows={[]}/>); }")

    def test_sections_and_usage_match_by_export_name(self):
        titles = [t for t, _ in framework_docs.sections(self.root)]
        self.assertEqual(titles[2], 'GRID THINGS (rows)')
        text = framework_docs.usage(self.root, ['Grid'])
        self.assertIn('row click selects', text)
        self.assertNotIn('frames content', text)
        self.assertNotIn('compose screens', text)
        self.assertIn('compose screens', framework_docs.usage(self.root, ['Grid'], general=True))

    def test_planner_context_gives_usage_not_framework_source(self):
        text = import_graph.planner_context(self.root, 'Items 화면 수정')
        self.assertIn('row click selects', text)
        self.assertNotIn('SECRET_INTERNALS', text)
        self.assertNotIn('frames content', text)

    def test_first_framework_read_returns_usage_second_returns_source(self):
        runner = SimpleNamespace(h=SimpleNamespace(workspace=SimpleNamespace(root=self.root), log_event=Mock()), read=set())
        with patch.dict(os.environ, {'HARNESS_TASK_APPROACH': ''}):
            first = framework_docs.internal_read(runner, 'read_file', {'path': 'frontend/src/framework/Grid.tsx'})
            self.assertIn('row click selects', first['framework_usage'])
            self.assertNotIn('SECRET_INTERNALS', str(first))
            self.assertIsNone(framework_docs.internal_read(runner, 'read_file', {'path': 'frontend/src/framework/Grid.tsx'}))
            self.assertIsNone(framework_docs.internal_read(runner, 'read_file', {'path': 'frontend/src/framework/index.ts'}))
            self.assertIsNone(framework_docs.internal_read(runner, 'read_file', {'path': 'frontend/src/screens/Items.tsx'}))
            self.assertIsNone(framework_docs.internal_read(runner, 'inspect_code', {'path': 'frontend/src/framework/Panel.tsx', 'action': 'edit_ranges'}))
        with patch.dict(os.environ, {'HARNESS_TASK_APPROACH': 'Panel.tsx에 옵션 prop 추가'}):
            self.assertIsNone(framework_docs.internal_read(runner, 'read_file', {'path': 'frontend/src/framework/Panel.tsx'}))


if __name__ == '__main__':
    unittest.main()


class ReadLoopGuardTests(unittest.TestCase):
    def test_third_read_of_unchanged_file_is_refused_and_change_resets(self):
        import workflow_progress as wp
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        root = Path(tmp.name); (root / 'A.java').write_text('class A {}')
        runner = SimpleNamespace(h=SimpleNamespace(workspace=SimpleNamespace(root=root)))
        read = lambda: wp.repeated_read(runner, 'read_file', {'path': 'A.java'})
        self.assertIsNone(read()); self.assertIsNone(read())
        self.assertIn('already read', read()['error'])
        (root / 'A.java').write_text('class A { int x; }')
        self.assertIsNone(read())

    def test_read_only_streak_stops_and_any_edit_resets(self):
        import workflow_progress as wp
        runner = SimpleNamespace(h=SimpleNamespace(log_event=Mock()), used=1)
        read = {'tool_calls': [{'function': {'name': 'read_file'}}]}
        edit = {'tool_calls': [{'function': {'name': 'write_file'}}]}
        for _ in range(wp.READ_STREAK_LIMIT - 1):
            self.assertFalse(wp.note_read_streak(runner, read, False))
        self.assertFalse(wp.note_read_streak(runner, edit, False))
        for _ in range(wp.READ_STREAK_LIMIT - 1):
            self.assertFalse(wp.note_read_streak(runner, read, False))
        self.assertTrue(wp.note_read_streak(runner, read, False))


class NewApiReferenceTests(unittest.TestCase):
    def test_new_api_task_gets_short_brief_and_reference_files(self):
        import autonomy_runtime
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        for rel in autonomy_runtime.Runner.REFERENCE_API:
            (root / rel).parent.mkdir(parents=True, exist_ok=True); (root / rel).write_text('// ' + rel)
        (root / 'backend/src/main/resources/db/migration/V7__x.sql').write_text('')
        runner = SimpleNamespace(args=SimpleNamespace(task='회사 등록 API(테이블·엔티티·API 함께)'), h=SimpleNamespace(workspace=SimpleNamespace(root=root)), read=set(),
                                 REFERENCE_API=autonomy_runtime.Runner.REFERENCE_API)
        text = autonomy_runtime.Runner._new_api_reference(runner)
        self.assertIn('V8__', text)
        self.assertIn('ItemController.java', text)
        self.assertEqual(len(runner.read), 4)
        runner.args.task = 'InventoryIntegrationTest 픽스처 격리'
        self.assertEqual(autonomy_runtime.Runner._new_api_reference(runner), '')
