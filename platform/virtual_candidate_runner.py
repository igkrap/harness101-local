import os
"""Adapt the native transaction loop to edit the latest failed source, not stale nodes."""
import copy
import json
import re

from ast_candidate_buffer import CandidateBuffer, CandidateStore, digest

CANDIDATE_REJECTION_LIMIT = 6  # consecutive rejected repair proposals before the run stops


PUBLISH_TOOL = {'type': 'function', 'function': {
    'name': 'publish_candidate_buffer', 'description': 'Internal publication of validated AST buffer edits.',
    'parameters': {'type': 'object', 'properties': {'path': {'type': 'string'}, 'token': {'type': 'string'}},
                   'required': ['path', 'token'], 'additionalProperties': False}}}


def extend_virtual_candidate(base, store):
    class BufferedRunner(base):
        def __init__(self, *args, **kwargs):
            self._edit_buffer = None
            super().__init__(*args, **kwargs)

        def _buffer_allowed(self, path):
            # Standard screen changes rewrite a short file whole; the fragment-repair buffer only got in the way there
            # (its structural rules rejected six repairs of a one-line omission in a row).
            if getattr(self, '_no_candidate_buffer', False):
                return False
            if not isinstance(path, str) or path not in self.initial_frontend_files:
                return False
            stage = getattr(getattr(self, 'requirement_gate', None), 'stage', {})
            paths = stage.get('paths', []) if isinstance(stage, dict) else []
            return not paths or path in paths

        def _saved_buffer(self):
            from ast_editing import editor
            data = store.load()
            if not data or not self._buffer_allowed(data.get('path')):
                return False
            target = self.h.workspace.safe_path(data['path'])
            source = target.read_bytes().decode('utf-8')
            if source != data.get('base_source') or digest(source) != data.get('base_hash'):
                return False
            try:
                self._edit_buffer = CandidateBuffer(self.h.workspace, editor(self.h), data['path'], data['candidate_source'], data.get('origin'))
            except (ValueError, KeyError):
                return False
            self._failed_ast_candidate = None
            self._edit_buffer.prepare_publication()
            self.h.log_event('autonomy.strategy', {'reason': 'candidate_buffer_resumed', 'path': data['path'], 'model_calls': 0})
            return True

        def _publication(self):
            buffer = self._edit_buffer
            return {'content': 'Apply validated candidate AST edits through the native checkpoint.', 'tool_calls': [{
                'id': 'buffer-' + buffer.pending['token'], 'type': 'function', 'function': {
                    'name': 'publish_candidate_buffer', 'arguments': json.dumps({'path': buffer.path, 'token': buffer.pending['token']})}}]}

        def ask(self, messages, tools=None):
            from ast_editing import editor
            from candidate_focus import ask_candidate
            if messages is not self.messages or self.cp.pending:
                return super().ask(messages, tools)
            if self._edit_buffer and self.h.workspace.safe_path(self._edit_buffer.path).read_bytes().decode() == self._edit_buffer.source:
                self._edit_buffer.close()
                self._edit_buffer = None
            if self._edit_buffer is None and self._saved_buffer():
                return self._publication()
            proposal = getattr(self, '_failed_ast_candidate', None)
            if self._edit_buffer is None and proposal and proposal.get('edits') and self._buffer_allowed(proposal['path']):
                try:
                    ed = editor(self.h)
                    result = ed.apply(proposal['path'], proposal['snapshot_id'], proposal['edits'])
                    self._edit_buffer = CandidateBuffer(self.h.workspace, ed, proposal['path'], result['new_text'])
                    store.save(self._edit_buffer.record(self.feedback))
                    self._failed_ast_candidate = None
                    self.h.log_event('autonomy.strategy', {'reason': 'candidate_buffer_created', 'path': proposal['path'], 'model_calls': 0})
                except ValueError:
                    return super().ask(messages, tools)
            if self._edit_buffer is None:
                return super().ask(messages, tools)
            buffer = self._edit_buffer
            buffer.check_base()
            snapshot = buffer.snapshot()
            from candidate_binding_reflex import identical_bindings
            redundant = identical_bindings(buffer, snapshot)
            if redundant:
                buffer.prepare(snapshot['snapshot_id'], redundant)
                store.save(buffer.record(self.feedback))
                self.h.log_event('autonomy.strategy', {'reason': 'candidate_identical_declarations_removed', 'path': buffer.path,
                                 'node_ids': [edit['node_id'] for edit in redundant], 'model_calls': 0})
                return self._publication()
            proxy = copy.copy(self)
            proxy._paired_jsx_tags = True
            proxy.h = copy.copy(self.h)
            proxy.h._ast_editor = buffer.editor
            proxy._failed_ast_candidate = {'path': buffer.path, 'snapshot_id': snapshot['snapshot_id'],
                                          'source_hash': snapshot['source_hash'], 'edits': []}
            # Native DOM reports can describe the restored published source. Keep
            # the criteria and current check feedback, without presenting those
            # older measurements as observations of the private candidate.
            from candidate_targets import order_candidate_nodes
            from candidate_leaf_scope import leaf_scope
            _, hint = order_candidate_nodes(proxy, proxy._failed_ast_candidate, snapshot['nodes'], [])
            scoped = leaf_scope(snapshot['nodes'], buffer.editor._snapshots[snapshot['snapshot_id']], re.findall(r'\b[ns]\d+\b', hint))
            scoped = [{**node, 'label': node['label'].replace('complete JSX node', 'matching full element node')}
                      if node['kind'] == 'JsxOpeningElement' else node for node in scoped]

            class CatalogView:
                def __getattr__(self, name):
                    return getattr(buffer.editor, name)

                def snapshot(self, path):
                    return {**buffer.editor.snapshot(path), 'nodes': scoped}

            proxy.h._ast_editor = CatalogView()
            proxy.requirement_gate = copy.copy(self.requirement_gate)
            proxy.requirement_gate.last_report = {'results': []}
            contract = getattr(proxy.requirement_gate, 'contract', {})
            if not isinstance(contract, dict) or not contract.get('task'):
                proxy.requirement_gate.contract = {**(contract if isinstance(contract, dict) else {}), 'task': self.args.task}
            diagnostics = [line for line in self.feedback.splitlines() if re.search(r'error TS\d+|error @typescript-eslint/', line)]
            microtask = bool(diagnostics)
            if microtask:
                proxy.args = copy.copy(self.args)
                proxy.args.task = ('Repair ONLY this compiler/lint diagnostic in the CURRENT candidate: ' + diagnostics[0]
                                  + '. Return focused AST node edits for this issue; related nodes may change atomically. Keep current state, handlers and panels; do not reimplement the screen or duplicate declarations. '
                                    'An unused callback needs a real consumer reference when required by the task; reprinting its body does not fix it.')
            else:
                behavior = next((line.strip() for line in self.feedback.splitlines()
                                 if ('Error:' in line or 'AssertionError' in line or 'Native UI requirement:' in line)
                                 and 'Command failed:' not in line and not line.lstrip().startswith(('at ', 'stderr:', 'stdout:'))), '')
                if behavior:
                    proxy.args = copy.copy(self.args)
                    proxy.args.task = ('Repair ONLY this observed behavior in the CURRENT candidate: ' + behavior[:2200]
                                       + '. Trace the clicked control to its event handler, request, state update and rendered result. '
                                         'Keep the existing screen, editor and working handlers. Use focused related AST node edits; do not regenerate the feature.')
            proxy.feedback = 'CURRENT CANDIDATE SOURCE includes prior changes. Repair this source; published files remain restored.\n' + self.feedback
            if getattr(self, '_candidate_focus_error', ''):
                proxy.feedback = ('LAST REJECTED PROPOSAL: ' + self._candidate_focus_error
                                  + '\nChoose a different actual edit; repeating the current source cannot repair behavior.\n' + proxy.feedback)
            if '@astryxdesign/core/Table' in buffer.source:
                from installed_type_records import declarations
                if not hasattr(self, '_candidate_table_api'):
                    self._candidate_table_api = '\n'.join(declarations(self.h.workspace.root, ['TableProps', 'TableColumn', 'TablePlugin']))[:4500]
                proxy.feedback += '\nCURRENT INSTALLED STYLED TABLE API: TableProps owns the plugins property. Use its declared container shape and the TablePlugin members together.\n' + self._candidate_table_api
            protocol_errors = []
            def callback(messages, tools):
                # Report structural evidence, without synthesizing application code.
                # A cell plugin gated on an absent column is unreachable even if
                # its callback is otherwise correct.
                evidence = []
                for node in snapshot['nodes']:
                    if node['kind'] != 'JsxSelfClosingElement' or not re.match(r'<Table\b', node['source']):
                        continue
                    source = node['source']
                    binding = re.search(r'\bcolumns=\{(\w+)\}', source)
                    declaration = next((n for n in snapshot['nodes'] if binding and n['kind'] == 'VariableStatement'
                                        and re.match(r'(?:const|let)\s+' + re.escape(binding[1]) + r'\b', n['source'])), None)
                    if declaration:
                        keys = re.findall(r'\bkey:\s*[\'\"]([^\'\"]+)[\'\"]', declaration['source'])
                        gates = re.findall(r'\b\w+\.key\s*===\s*[\'\"]([^\'\"]+)[\'\"]', source)
                        absent = sorted(set(gates) - set(keys))
                        if absent:
                            evidence.append({'table_node': node['id'], 'columns_node': declaration['id'],
                                             'declared_column_keys': keys, 'unreachable_cell_branch_keys': absent})
                if evidence:
                    messages = copy.deepcopy(messages)
                    messages[-1]['content'] += ('\nSTRUCTURAL UI WIRING DIAGNOSTIC: ' + json.dumps(evidence)
                                               + '\nThe cell-plugin branch cannot run for any declared column. Trace the rendered control to the existing handler. '
                                                 'Repair the actual wiring; reprinting the unchanged handler body has no effect.')
                repeats = getattr(self, '_candidate_repeat', 0)
                old_temperature = os.environ.get('LOCAL_LLM_TEMPERATURE')
                if repeats:
                    # The same proposal was already rejected: an identical prompt at low temperature
                    # would only reproduce it, so say so explicitly and sample more broadly.
                    messages = copy.deepcopy(messages)
                    messages[-1]['content'] += ('\nREPEATED REJECTION: your last ' + str(repeats + 1) + ' proposals were identical and were rejected for the same reason. '
                                               'Do not send that edit again. Choose a different target node (e.g. the enclosing declaration or the exact parameter/statement node) or different code.')
                    from runtime_policy import generation_settings
                    os.environ['LOCAL_LLM_TEMPERATURE'] = str(round(min(1.0, max(generation_settings()['temperature'], 0.5) + 0.15 * repeats), 2))
                    self.h.log_event('autonomy.strategy', {'reason': 'candidate_repeat_escalation', 'path': buffer.path,
                                                           'identical_rejections': repeats + 1, 'temperature': os.environ['LOCAL_LLM_TEMPERATURE'], 'model_calls': 0})
                try:
                    reply = super(BufferedRunner, self).ask(messages, tools)
                finally:
                    if repeats:
                        if old_temperature is None:
                            os.environ.pop('LOCAL_LLM_TEMPERATURE', None)
                        else:
                            os.environ['LOCAL_LLM_TEMPERATURE'] = old_temperature
                problem = reply.pop('_provider_error', None)
                if problem:
                    protocol_errors.append(problem)
                return reply
            response = ask_candidate(proxy, callback)
            self._candidate_focus_error = '\n'.join(protocol_errors) or getattr(proxy, '_candidate_focus_error', '')
            calls = response.get('tool_calls') or []
            if not calls:
                self.h.log_event('autonomy.strategy', {'reason': 'candidate_buffer_rejected', 'path': buffer.path, 'error': self._candidate_focus_error})
                self._candidate_give_up(buffer)
                return response
            if len(calls) != 1 or calls[0]['function']['name'] != 'repair_ast_candidate':
                raise ValueError('Unexpected candidate buffer action')
            data = json.loads(calls[0]['function']['arguments'])
            if data.get('remove'):
                raise ValueError('Current source nodes must be changed with AST fragments')
            try:
                buffer.prepare(snapshot['snapshot_id'], data['changes'])
            except ValueError as exc:
                buffer.check_base()
                suggestions = []
                for edit in data['changes']:
                    code = edit['code'].strip()
                    tag = re.match(r'<([A-Za-z][\w.:-]*)\b', code)
                    if tag:
                        kind = ('JsxSelfClosingElement' if code.endswith('/>') else
                                'JsxOpeningElement' if '</' not in code and code.count('<') == 1 else 'JsxElement')
                        suggestions.extend({'node_id': node['id'], 'kind': node['kind'], 'source': node['source'][:350]}
                                           for node in scoped if node['kind'] == kind and re.match(r'<' + re.escape(tag.group(1)) + r'\b', node['source']))
                detail = str(exc) + ('\nMATCHING PRECISE JSX TARGETS: ' + json.dumps(suggestions[:8], ensure_ascii=False) if suggestions else '')
                key = json.dumps(data['changes'], sort_keys=True, ensure_ascii=False)
                self._candidate_repeat = getattr(self, '_candidate_repeat', 0) + 1 if key == getattr(self, '_candidate_last_rejected', None) else 0
                self._candidate_last_rejected = key
                self._candidate_focus_error = detail
                self.h.log_event('autonomy.strategy', {'reason': 'candidate_buffer_rejected', 'path': buffer.path, 'error': detail})
                self._candidate_give_up(buffer)
                return {'content': 'Candidate AST edit rejected: ' + detail, 'tool_calls': []}
            self._candidate_repeat, self._candidate_last_rejected = 0, None
            self._candidate_rejections = 0
            store.save(buffer.record(self.feedback))
            if buffer.pending['edits'] != data['changes']:
                self.h.log_event('autonomy.strategy', {'reason': 'candidate_fragment_edits_normalized',
                    'path': buffer.path, 'requested_node_ids': [c['node_id'] for c in data['changes']],
                    'applied_node_ids': [c['node_id'] for c in buffer.pending['edits']], 'model_calls': 0})
            self.h.log_event('autonomy.strategy', {'reason': 'candidate_buffer_reindexed', 'path': buffer.path,
                             'node_count': len(snapshot['nodes']), 'node_ids': [c['node_id'] for c in data['changes']]})
            return self._publication()

        def _candidate_give_up(self, buffer):
            # Repair proposals that keep getting rejected only burn model calls (one run looped 61 times).
            self._candidate_rejections = getattr(self, '_candidate_rejections', 0) + 1
            if self._candidate_rejections >= CANDIDATE_REJECTION_LIMIT:
                self.h.log_event('autonomy.stalled', {'reason': 'candidate_repair_no_progress', 'path': buffer.path,
                                                      'rejections': self._candidate_rejections, 'model_calls': getattr(self, 'used', 0)})
                raise RuntimeError(f'Candidate repair of {buffer.path} was rejected {self._candidate_rejections} times in a row; stopping instead of looping')

        def tools(self):
            result = super().tools()
            if self._edit_buffer:
                return result + [copy.deepcopy(PUBLISH_TOOL)]
            return result

        def apply(self, name, inputs, before=None):
            if name != 'publish_candidate_buffer':
                return super().apply(name, inputs, before)
            buffer = self._edit_buffer
            if not buffer or not buffer.pending or self.cp.pending or inputs != {'path': buffer.path, 'token': buffer.pending['token']}:
                raise ValueError('No matching validated candidate publication')
            buffer.check_base()
            original = self.h._ast_editor
            self.h._ast_editor = buffer.bridge()
            self.read.add(buffer.path)
            try:
                result = super().apply('apply_ast_edits', {'path': buffer.path, 'snapshot_id': buffer.pending['token'],
                                      'edits': buffer.pending['edits']}, before if before is not None else {})
            finally:
                self.h._ast_editor = original
                buffer.pending = None
            self._failed_ast_candidate = None
            return result

        def verify(self):
            ok, feedback = super().verify()
            if self._edit_buffer and self.cp.pending:
                self._failed_ast_candidate = None
                source = self.h.workspace.safe_path(self._edit_buffer.path).read_bytes().decode('utf-8')
                self._edit_buffer.set_source(source)
                store.save(self._edit_buffer.record(feedback))
            return ok, feedback

        def run(self):
            try:
                return super().run()
            finally:
                if self._edit_buffer:
                    self._edit_buffer.close()
    return BufferedRunner


def install(directory, project, goal):
    """Install before autonomy_runtime is imported; its stage factories capture this wrapper."""
    import candidate_repair
    store = CandidateStore(directory, project, goal)
    factory = candidate_repair.extend_candidate
    candidate_repair.extend_candidate = lambda base: extend_virtual_candidate(factory(base), store)
    return store
