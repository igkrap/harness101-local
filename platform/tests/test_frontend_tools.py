import copy
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'local-only/harness'))
from frontend_tools import filter_tools


class FrontendToolTests(unittest.TestCase):
    def setUp(self):
        self.tools=[{'type':'function','function':{'name':name,'description':'tool',
            'parameters':{'type':'object','properties':{'path':{'type':'string'}},'required':['path']}}}
            for name in ('read_file','inspect_code','edit_file','apply_edits','apply_insertions','insert_text',
                         'apply_ast_edits','write_file','delete_file','add_java_annotations','isolate_spring_test','update_seed_rows')]
        self.runner=SimpleNamespace(args=SimpleNamespace(edit_format='auto'),modes=['frontend','framework'],
            initial_frontend_files={'frontend/src/App.tsx','frontend/src/screens/Inventory.tsx'})

    def test_frontend_model_cannot_select_blocked_raw_or_backend_edit_tools(self):
        result=filter_tools(self.runner,self.tools)
        names=[t['function']['name'] for t in result]
        self.assertEqual(names,['read_file','inspect_code','apply_ast_edits','write_file','delete_file'])
        write=next(t['function'] for t in result if t['function']['name']=='write_file')
        self.assertEqual(write['parameters']['properties']['path']['not']['enum'],sorted(self.runner.initial_frontend_files))
        self.assertIn('workspace',write['description'].lower())

    def test_tool_schemas_and_runner_modes_are_not_modified(self):
        original=copy.deepcopy(self.tools)
        filter_tools(self.runner,self.tools)
        self.assertEqual(self.tools,original)
        self.assertEqual(self.runner.modes,['frontend','framework'])

    def test_large_projects_keep_tool_metadata_bounded_and_prioritize_read_targets(self):
        self.runner.initial_frontend_files={f'frontend/src/screens/Screen{i:04}.tsx' for i in range(3000)}
        self.runner.read={'frontend/src/screens/Screen2999.tsx'}
        result=filter_tools(self.runner,self.tools)
        write=next(t['function'] for t in result if t['function']['name']=='write_file')
        excluded=write['parameters']['properties']['path']['not']['enum']
        self.assertLessEqual(len(excluded),64)
        self.assertIn('frontend/src/screens/Screen2999.tsx',excluded)
        self.assertLess(len(json.dumps(result)),15000)
        self.assertEqual(len(self.runner.initial_frontend_files),3000)

    def test_stable_schema_keeps_identical_bytes_after_reads_and_context_reset(self):
        paths=[f'frontend/src/screens/Screen{i:02}.tsx' for i in range(33)]
        self.runner.initial_frontend_files=set(paths)
        original=copy.deepcopy(self.tools)
        before=json.dumps(filter_tools(self.runner,self.tools,stable_schema=True))
        for reads in ({paths[20],paths[31]},set(paths),{paths[3]},set()):
            with self.subTest(reads=sorted(reads)):
                self.runner.read=reads
                after=filter_tools(self.runner,self.tools,stable_schema=True)
                self.assertEqual(json.dumps(after),before)
                write=next(t['function'] for t in after if t['function']['name']=='write_file')
                self.assertEqual(set(write['parameters']['properties']['path']['not']['enum']),set(paths))
                self.assertEqual(self.runner.read,reads)
        self.assertEqual(self.tools,original)

    def test_stable_large_project_selection_ignores_read_order_and_history(self):
        paths=[f'frontend/src/screens/Screen{i:04}.tsx' for i in range(3000)]
        self.runner.initial_frontend_files=set(reversed(paths))
        before=filter_tools(self.runner,self.tools,stable_schema=True)
        excluded=next(t['function'] for t in before if t['function']['name']=='write_file')['parameters']['properties']['path']['not']['enum']
        self.assertEqual(len(excluded),64)
        self.assertEqual(set(excluded),set(paths[:64]))
        for reads in ([paths[-1],paths[8]],[paths[8],paths[-1]],paths[1500:],[]):
            with self.subTest(read_count=len(reads)):
                self.runner.read=reads
                self.assertEqual(json.dumps(filter_tools(self.runner,self.tools,stable_schema=True)),json.dumps(before))
        self.assertLess(len(json.dumps(before)),15000)
        self.assertEqual(self.runner.initial_frontend_files,set(paths))

    def test_existing_file_omitted_from_bounded_schema_still_rejects_raw_writes(self):
        import tempfile
        from test_autonomy import native
        from autonomy_runtime import Runner
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            paths=[f'frontend/src/screens/Screen{i:03}.tsx' for i in range(65)]
            source='export default function Screen(){return <main/>;}'
            for rel in paths:
                p=root/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(source)
            args=SimpleNamespace(task='Update screen',workspace=folder,check='frontend',max_rounds=0,
                context_profile='focused',ponytail='off',llm_url='http://127.0.0.1:8099/v1',model='fixture')
            runner=Runner(args,native.Harness);runner.h.evidence_path=root/'events.jsonl'
            try:
                target=paths[-1]
                runner.read.add(target)
                schemas=filter_tools(runner,self.tools,stable_schema=True)
                write=next(t['function'] for t in schemas if t['function']['name']=='write_file')
                self.assertNotIn(target,write['parameters']['properties']['path']['not']['enum'])
                for name,extra in (('write_file',{'content':'replacement'}),('apply_edits',{'edits':[]})):
                    with self.subTest(tool=name),self.assertRaisesRegex(ValueError,'requires inspect_code'):
                        runner.apply(name,{'path':'./'+target,**extra},{})
                self.assertEqual((root/target).read_text(),source)
                self.assertFalse(runner.cp.pending)
            finally:
                if getattr(runner.h,'_code_intelligence',None):runner.h._code_intelligence.close()

    def test_explicit_formats_and_nonfrontend_work_retain_raw_tools(self):
        for modes,fmt in ((['backend'],'auto'),(['python'],'auto'),(['frontend'],'diff'),(['frontend'],'whole')):
            with self.subTest(modes=modes,fmt=fmt):
                self.runner.modes=modes;self.runner.args.edit_format=fmt
                self.assertEqual(filter_tools(self.runner,self.tools),self.tools)

    def test_mixed_check_selection_uses_frozen_criteria_without_dropping_checks(self):
        self.runner.modes=['frontend','framework','backend']
        self.runner.requirement_gate=SimpleNamespace(frozen_contract=json.dumps({'criteria':[{'check':{'op':'layout'}}]}))
        names=[t['function']['name'] for t in filter_tools(self.runner,self.tools)]
        self.assertNotIn('apply_edits',names)
        self.assertEqual(self.runner.modes,['frontend','framework','backend'])
        self.runner.requirement_gate.frozen_contract=json.dumps({'criteria':[{'check':{'op':'layout'}},{'check':{'op':'api'}}]})
        self.assertEqual(filter_tools(self.runner,self.tools),self.tools)

    def test_actual_runner_advertises_ast_without_raw_edits(self):
        import tempfile
        from test_autonomy import native
        from autonomy_runtime import Runner
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);p=root/'frontend/src/App.tsx';p.parent.mkdir(parents=True);p.write_text('export default function App(){return <main/>;}')
            args=SimpleNamespace(task='레이아웃 변경',workspace=folder,check='frontend',max_rounds=0,
                ponytail='off',llm_url='http://127.0.0.1:8099/v1',model='fixture')
            runner=Runner(args,native.Harness);runner.h.evidence_path=root/'events.jsonl'
            try:
                names=[t['function']['name'] for t in runner.tools()]
                self.assertIn('apply_ast_edits',names)
                self.assertNotIn('apply_edits',names)
                runner.read.add('frontend/src/App.tsx')
                with self.assertRaisesRegex(ValueError,'requires inspect_code'):
                    runner.apply('apply_edits',{'path':'./frontend/src/App.tsx','edits':[]},{})
            finally:
                if getattr(runner.h,'_code_intelligence',None):runner.h._code_intelligence.close()

    def test_focused_backend_only_tools_exclude_frontend_apis_and_remain_stable(self):
        extras=[{'type':'function','function':{'name':name,'parameters':{'type':'object','properties':{}}}}
                for name in ('search_components','astryx_docs','search_code','finish')]
        tools=self.tools+extras
        original=copy.deepcopy(tools)
        self.runner.modes=['backend']
        self.runner.args.context_profile='focused'
        first=filter_tools(self.runner,tools,stable_schema=True)
        names={tool['function']['name'] for tool in first}
        self.assertFalse(names & {'inspect_code','apply_ast_edits','search_components','astryx_docs'})
        self.assertTrue({'read_file','write_file','apply_edits','add_java_annotations','isolate_spring_test','search_code','finish'} <= names)
        for reads in (set(),{'backend/src/main/java/Query.java'},{'frontend/src/Reference.tsx'}):
            self.runner.read=reads
            self.runner.blocked_tools={'read_file'}
            self.assertEqual(json.dumps(filter_tools(self.runner,tools,stable_schema=True)),json.dumps(first))
        self.assertEqual(tools,original)

    def test_backend_tool_filter_does_not_change_legacy_mixed_or_frontend_modes(self):
        for modes,profile,stable in ((['backend'],'legacy',True),(['backend'],'focused',False),
                                     (['backend','frontend'],'focused',True),(['backend','python'],'focused',True)):
            with self.subTest(modes=modes,profile=profile,stable=stable):
                self.runner.modes=modes;self.runner.args.context_profile=profile
                self.assertEqual(filter_tools(self.runner,self.tools,stable_schema=stable),self.tools)
        self.runner.modes=['frontend'];self.runner.args.context_profile='focused'
        names={tool['function']['name'] for tool in filter_tools(self.runner,self.tools,stable_schema=True)}
        self.assertTrue({'inspect_code','apply_ast_edits'} <= names)

    def test_actual_focused_backend_runner_advertises_only_applicable_stable_tools(self):
        import tempfile
        from test_autonomy import native
        from autonomy_runtime import Runner
        with tempfile.TemporaryDirectory() as folder:
            args=SimpleNamespace(task='Add a query API',workspace=folder,check='backend',max_rounds=0,
                context_profile='focused',ponytail='off',llm_url='http://127.0.0.1:1/v1',model='fixture')
            runner=Runner(args,native.Harness)
            before=runner.tools()
            names={tool['function']['name'] for tool in before}
            self.assertFalse(names & {'inspect_code','apply_ast_edits','search_components','astryx_docs'})
            self.assertTrue({'read_file','write_file','add_java_annotations','isolate_spring_test','search_code'} <= names)
            runner.read={'backend/src/main/java/Query.java'}
            runner.blocked_tools={'read_file','list_files'}
            runner.focused=True
            self.assertEqual(json.dumps(runner.tools()),json.dumps(before))
            args.context_profile='legacy'
            legacy_names={tool['function']['name'] for tool in runner.tools()}
            # astryx_docs is offered only when the project depends on that design system
            self.assertTrue({'inspect_code','apply_ast_edits','search_components'} <= legacy_names)


if __name__=='__main__':unittest.main()
