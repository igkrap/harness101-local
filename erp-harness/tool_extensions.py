from pathlib import Path

def extend_harness(base):
    class ExtendedHarness(base):
        def _get_tool_schemas(self):
            from code_intelligence import TOOL
            from ast_editing import TOOL as AST_TOOL
            return [TOOL, AST_TOOL] + super()._get_tool_schemas()

        def _execute_tool(self, name, args):
            try:
                from cycle_context import cycle_context
                if name == 'inspect_code' and args.get('action') == 'edit_ranges':
                    from ast_editing import editor
                    return editor(self).snapshot(args['path'])
                if name == 'inspect_code':
                    return cycle_context.service(self).run(args)
                if name == 'read_file':
                    path_str = args.get('path', '')
                    if path_str.startswith('frontend/src/'):
                        suffix = Path(path_str).suffix
                        if suffix in ('.ts', '.tsx', '.js', '.jsx'):
                            return cycle_context.service(self).read(path_str)
                return super()._execute_tool(name, args)
            except Exception as e:
                return {'error': str(e)}
    return ExtendedHarness

def extend_checker(base):
    class ExtendedChecker(base):
        def _check_frontend(self):
            from frontend_checks import run_frontend
            return run_frontend(self)
    return ExtendedChecker
