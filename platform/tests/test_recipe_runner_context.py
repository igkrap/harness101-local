import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'local-only/harness'))
from runner_extensions import extend_runner


class RecipeRunnerContextTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / 'frontend/src').mkdir(parents=True)
        (self.root / 'frontend/src/App.tsx').write_text('export default function App() { return null; }')
        self.runner = extend_runner(object)()
        self.runner.args = SimpleNamespace(task='Create frontend/src/screens/New.tsx from components')
        self.runner.modes = ['frontend']
        self.runner.h = SimpleNamespace(workspace=SimpleNamespace(root=self.root))
        self.runner._component_recipe = {'files': [{'path': 'frontend/src/screens/Recipe.tsx'}]}

    def context(self):
        ed = Mock()
        ed.snapshot.return_value = {'path': 'frontend/src/App.tsx', 'nodes': []}
        with patch('runner_extensions.cycle_context.snapshot', return_value=('', set())), \
             patch('runner_extensions.cycle_context.service', return_value=SimpleNamespace(context=lambda: '')), \
             patch('ast_editing.editor', return_value=ed):
            result = self.runner.current_context()
        return result, ed

    def test_new_screen_recipe_does_not_offer_app_as_automatic_edit_target(self):
        (text, paths), ed = self.context()
        ed.snapshot.assert_not_called()
        self.assertNotIn('App.tsx', text)
        self.assertNotIn('frontend/src/App.tsx', paths)

    def test_explicit_app_task_keeps_app_edit_target(self):
        self.runner.args.task += ' and update frontend/src/App.tsx'
        (_, paths), ed = self.context()
        ed.snapshot.assert_called_once_with('frontend/src/App.tsx')
        self.assertIn('frontend/src/App.tsx', paths)

    def test_missing_recipe_keeps_existing_default_context(self):
        self.runner._component_recipe = None
        (_, paths), ed = self.context()
        ed.snapshot.assert_called_once_with('frontend/src/App.tsx')
        self.assertIn('frontend/src/App.tsx', paths)
