from cycle_context import cycle_context
from deterministic_plan import plan


def explicit_edit_paths(runner):
    """Focused context must not turn read-only references into AST targets."""
    from task_sources import resolve_task_sources
    paths = resolve_task_sources(runner.h.workspace.root, runner.args.task)
    for message in reversed(runner.messages):
        for call in reversed(message.get('tool_calls', [])):
            function = call.get('function', {})
            try:
                import json
                args = json.loads(function.get('arguments', '{}'))
                name = function.get('name')
                if name in ('apply_ast_edits', 'write_file', 'edit_file', 'apply_edits', 'apply_insertions', 'insert_text') or (name == 'inspect_code' and args.get('action') == 'edit_ranges'):
                    paths.append(args.get('path'))
            except (ValueError, TypeError, AttributeError):
                pass
    from workflow_progress import approach_files
    paths.extend(approach_files(runner))  # supply the planner-named files up front
    paths.extend(reversed(getattr(runner, '_selected_check_progress', {})))
    return list(dict.fromkeys(path for path in paths if isinstance(path, str)))

def extend_runner(base):
    class Extended(base):
        plan = plan

        def verify_step(self):
            return super().verify_step()

        def current_context(self):
            from ast_editing import editor
            import json
            if not any(m in ('frontend','framework') for m in self.modes) or cycle_context.is_grid_task(self.args.task):
                return cycle_context.snapshot(self)
            text, paths = cycle_context.snapshot(self)
            paths = set(paths)
            if any(m in ['frontend', 'framework'] for m in self.modes) and not cycle_context.is_grid_task(self.args.task):
                from recipe_context import prefer_recipe
                from focused_context import enabled
                recipe_focus = prefer_recipe(self)
                candidates = sorted(p for p in paths if p.startswith('frontend/src/') and p.endswith(('.ts', '.tsx', '.js', '.jsx')))
                if recipe_focus:
                    candidates = [p for p in candidates if p != 'frontend/src/App.tsx']
                if enabled(self):
                    candidates = []
                    from source_progress import current_bytes
                    for path in explicit_edit_paths(self):
                        if not path.startswith('frontend/src/') or not path.endswith(('.ts', '.tsx', '.js', '.jsx')):
                            continue
                        try:
                            if current_bytes(self, path) is not None:
                                candidates.append(path)
                        except (OSError, ValueError):
                            pass
                if not enabled(self) and not candidates and not recipe_focus and (self.h.workspace.root / 'frontend/src/App.tsx').is_file():
                    candidates = ['frontend/src/App.tsx']
                if candidates:
                    path = candidates[0]
                    try:
                        snap = editor(self.h).snapshot(path)
                        from ast_context import already_retained
                        if not enabled(self) or not already_retained(self, snap):
                            text += '\nCURRENT AST EDIT SCOPES (use these IDs; snapshot_id may be omitted):\n' + json.dumps(snap, ensure_ascii=False)
                        paths.add(path)
                    except Exception as e:
                        text += f"\nError loading AST for {path}: {e}. Use inspect_code action edit_ranges"
            from focused_context import enabled
            service = cycle_context.service(self.h)
            service_context = (service.context(read_paths=paths | set(getattr(self, '_context_supplied_paths', ())))
                               if enabled(self) else service.context())
            return (text + service_context, paths)

        def tools(self):
            res = super().tools()
            from frontend_tools import filter_tools
            from focused_context import enabled
            res = filter_tools(self, res, stable_schema=enabled(self))
            if getattr(self, '_plain_edits_only', False):
                # Standard screen change: plain text edits only; the AST tools cannot express the needed edit and the
                # model reaches for them first when they are offered.
                res = [t for t in res if t['function']['name'] not in ('apply_ast_edits', 'inspect_code', 'repair_ast_candidate', 'discard_ast_candidate', 'apply_snippet_patch')]
            svc = getattr(getattr(self.h, '_code_intelligence', None), 'allow_reads', lambda: True)()
            if not svc and not enabled(self):
                return [t for t in res if t['function']['name'] != 'read_file']
            return res

        def fresh(self, reason=''):
            super().fresh(reason)
            target = 'Reread current files; rejected changes were restored.'
            replacement = 'Provided current sources are already read; reread only changed content versions.'
            for msg in self.messages:
                if isinstance(msg.get('content'), str):
                    msg['content'] = msg['content'].replace(target, replacement)
            
            if any(m in ('frontend','framework') for m in self.modes):
                report = self.feedback + '\n' + self.memory.context()
                if 'error TS' in report and 'Installed API declarations:' not in report:
                    import re
                    from installed_type_records import declarations
                    joinedlines = '\n'.join(l for l in report.splitlines() if 'error TS' in l)
                    raw_ids = re.findall('[A-Z][A-Za-z0-9_]*', joinedlines)
                    exclude = {'Type', 'Types', 'Property', 'Cannot', 'The', 'No', 'Argument', 'Expression', 'Did'}
                    unique_ids = []
                    for i in raw_ids:
                        if i not in exclude and i not in unique_ids:
                            unique_ids.append(i)
                            if len(unique_ids) >= 6: break
                    
                    records = declarations(self.h.workspace.root, unique_ids)
                    if records:
                        fact_text = '\nInstalled API facts for RECORDED failures (current source already restored):\n' + '\n'.join(records)[:3500] + '\nUse these declared values; do not guess unsupported alternatives.'
                        for msg in reversed(self.messages):
                            if msg.get('role') == 'user':
                                msg['content'] += fact_text
                                break

        def apply(self, name, inputs, before):
            from workflow_progress import read_suspended, outside_scope, repeated_read
            from framework_docs import internal_read
            refused = (outside_scope(self, name, inputs) or read_suspended(self, name, inputs)
                       or internal_read(self, name, inputs) or repeated_read(self, name, inputs))
            if refused:
                return refused
            res = super().apply(name, inputs, before)
            if name == 'inspect_code':
                if inputs.get('action') == 'symbol':
                    sym = res.get('symbol', {})
                    if sym.get('source') and not sym.get('truncated'):
                        self.read.add(inputs['path'])
                elif inputs.get('action') == 'edit_ranges' and res.get('snapshot_id'):
                    self.read.add(inputs['path'])
            return res

        def batch(self, message):
            paths, error, finished = super().batch(message)
            if finished:
                coverage = cycle_context.coverage(self)
                if coverage:
                    self._coverage_refresh = coverage
                    finished = False
            return paths, error, finished

        def ask(self, messages, tools):
            if getattr(self, '_coverage_refresh', None):
                self._coverage_refresh = None
                self.feedback += f"\n{cycle_context.coverage(self)}"
                self.fresh('continue remaining requested screens after checks')
                messages, tools = self.messages, self.tools()
            if cycle_context.is_grid_task(getattr(self.args,"task","")) and messages is self.messages:
                from patch_proposal import propose_patch
                return propose_patch(self, lambda m,t:super(Extended,self).ask(m,t))
            return super().ask(messages, tools)

    return Extended
