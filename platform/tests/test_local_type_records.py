import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'local-only/harness'))
from local_type_records import declarations, records, resolve


class LocalTypeRecordsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.src = self.root / 'frontend/src'
        self.src.mkdir(parents=True)

    def write(self, rel, text):
        path = self.src / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def contract(self, rel, names, **limits):
        return resolve(self.root, names, source='frontend/src/' + rel, **limits)

    def test_relative_import_reexport_aliases_preserve_real_members_and_generics(self):
        self.write('types/shape.ts', "export type Action={form?:string;onClick?:()=>void}; export type Actions=Partial<Record<'query'|'create',Action>>;")
        self.write('types/barrel.ts', "export type {Actions as ActionsAlias} from './shape';")
        self.write('Entry.tsx', "import type {ActionsAlias as Commands} from './types/barrel'; export type Props<T extends Record<string,unknown>>={actions:Commands;row:T};")
        result = self.contract('Entry.tsx', ['Props'])
        text = '\n'.join(records(result))
        self.assertEqual([d['name'] for d in result['declarations']], ['Props', 'Actions', 'Action'])
        self.assertIn('referenced as Commands', text)
        self.assertIn("'query' | 'create'", text)
        self.assertIn('form?: string', text)
        self.assertIn('T extends Record<string, unknown>', text)

    def test_star_reexports_namespace_and_cycles_resolve_once(self):
        self.write('shape.ts', 'export type A={b:B}; export type B={a?:A};')
        self.write('barrel.ts', "export * from './shape';")
        self.write('Entry.tsx', "import type * as Shape from './barrel'; export interface Props {value:Shape.A}")
        result = self.contract('Entry.tsx', ['Props'])
        self.assertEqual([d['name'] for d in result['declarations']], ['Props', 'A', 'B'])
        self.assertFalse(result['omitted'])

    def test_ambiguous_global_name_is_not_guessed_but_import_owner_is_exact(self):
        self.write('one.ts', "export type Shared={owner:'one'}")
        self.write('two.ts', "export type Shared={owner:'two'}")
        result = resolve(self.root, ['Shared'])
        self.assertEqual(result['declarations'], [])
        self.assertEqual(result['ambiguous'], ['Shared'])
        self.write('Entry.tsx', "import type {Shared} from './one'; export type Props={value:Shared};")
        text = '\n'.join(records(self.contract('Entry.tsx', ['Props'])))
        self.assertIn("'one'", text)
        self.assertNotIn("'two'", text)

    def test_virtual_candidate_and_nested_imported_contract_work_after_rollback(self):
        self.write('api.ts', 'export type Action={form?:string}; export type Props={action:Action}; export function Component(){return null;}')
        self.write('barrel.ts', "export {Component} from './api'; export type {Action,Props} from './api';")
        source = "import {Component} from './barrel'; export default function Candidate(){return null;}"
        result = resolve(self.root, ['Action'], source='frontend/src/Candidate.tsx', source_text=source)
        self.assertFalse((self.src / 'Candidate.tsx').exists())
        self.assertIn('form?: string', '\n'.join(records(result)))

    def test_nested_contract_owner_is_followed_through_component_imports(self):
        self.write('actions.ts', 'export type Action={form?:string}; export type Actions={query?:Action};')
        self.write('workspace.ts', "import type {Actions} from './actions'; export type WorkspaceProps={actions:Actions}; export function Workspace(){return null;}")
        self.write('unrelated.ts', "export type Action={wrong:'unrelated'};")
        source = "import {Workspace} from './workspace'; export default function Candidate(){return null;}"
        result = resolve(self.root, ['Action'], source='frontend/src/Candidate.tsx', source_text=source)
        text = '\n'.join(records(result))
        self.assertIn('form?: string', text)
        self.assertNotIn('unrelated', text)
        actual = resolve(ROOT / 'local-only', ['ScreenAction'], source='frontend/src/screens/Missing.tsx',
                         source_text="import {BusinessWorkspace} from '../framework/BusinessWorkspace';")
        self.assertIn('form?: string', '\n'.join(records(actual)))

    def test_source_changes_are_reflected_without_stale_cached_contract(self):
        path = self.write('shape.ts', "export type Mode='before';")
        before = self.contract('shape.ts', ['Mode'])
        path.write_text("export type Mode='after';")
        after = self.contract('shape.ts', ['Mode'])
        self.assertIn("'before'", '\n'.join(records(before)))
        self.assertIn("'after'", '\n'.join(records(after)))

    def test_depth_count_and_character_bounds_report_omitted_complete_declarations(self):
        self.write('shape.ts', '\n'.join('export type T%d={next:T%d};' % (i, i + 1) for i in range(15)) + '\nexport type T15={done:true};')
        result = self.contract('shape.ts', ['T0'])
        self.assertEqual([d['name'] for d in result['declarations']], ['T0', 'T1', 'T2', 'T3'])
        self.assertIn({'name': 'T4', 'reason': 'depth limit'}, result['omitted'])
        self.write('many.ts', 'export type Many=[' + ','.join('P%d' % i for i in range(15)) + '];\n' + '\n'.join('export type P%d={value:%d};' % (i, i) for i in range(15)))
        count = self.contract('many.ts', ['Many'])
        self.assertEqual(len(count['declarations']), 12)
        self.assertTrue(any(o['reason'] == 'declaration limit' for o in count['omitted']))
        bounded = self.contract('many.ts', ['Many'], max_chars=450)
        self.assertLessEqual(len('\n'.join(records(bounded))), 450)
        self.assertTrue(any(o['reason'] == 'character limit' for o in bounded['omitted']))
        self.assertTrue(all(d['source'].endswith(';') for d in bounded['declarations']))

    def test_local_declarations_do_not_require_installed_astryx(self):
        from installed_type_records import declarations as diagnostics
        self.write('shape.ts', "export type Field={type:'integer'|'text'};")
        self.assertFalse((self.root / 'frontend/node_modules').exists())
        text = '\n'.join(diagnostics(self.root, ['Field']))
        self.assertIn("'integer' | 'text'", text)

    def test_outside_paths_symlinks_and_external_type_imports_are_not_followed(self):
        private = self.root / 'outside.ts'
        private.write_text("export type Secret={marker:'PRIVATE_MARKER'};")
        self.write('Entry.tsx', "import type {Secret} from '../../outside'; import type {Node} from 'external'; export type Props={value:Secret;node:Node};")
        result = self.contract('Entry.tsx', ['Props'])
        self.assertNotIn('PRIVATE_MARKER', '\n'.join(records(result)))
        link = self.src / 'link.ts'
        link.symlink_to(private)
        self.assertTrue(self.contract('link.ts', ['Secret']).get('error'))
        self.assertTrue(resolve(self.root, ['Secret'], source='../outside.ts', source_text=private.read_text()).get('error'))

    def test_actual_framework_dependencies_are_in_rag_props(self):
        from component_catalog import actual_props
        root = ROOT / 'local-only'
        workspace = actual_props(root, {'source': 'frontend/src/framework/BusinessWorkspace.tsx', 'props_type': 'BusinessWorkspaceProps'})
        fields = actual_props(root, {'source': 'frontend/src/framework/QueryPanel.tsx', 'props_type': 'QueryPanelProps'})
        grid = actual_props(root, {'source': 'frontend/src/framework/RecordGrid.tsx', 'props_type': 'RecordGridProps'})
        self.assertIn("'query' | 'create' | 'remove' | 'save' | 'export' | 'print'", workspace)
        self.assertIn('form?: string', workspace)
        self.assertIn("'integer' | 'decimal'", fields)
        self.assertIn('GridColumn<T>', grid)
        self.assertIn('T extends Record<string, unknown>', grid)
        self.assertLessEqual(len(workspace), 2600)
        self.assertLessEqual(len(fields), 2600)


if __name__ == '__main__':
    unittest.main()
