import json
from divide_plan import duplicate_hook
from ast_editing import editor
from pathlib import Path
from style_response import normalize_response
from geometry_focus import geometry_prompt, measured_height_failure

def extend_recovery(base):
    class Recovery(base):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._ast_recovery_count = 0
            self._ast_recovery_path = None
            self._ast_recovery_error = None
            self._geometry_recovery_active = False
            self._geometry_attempts = 0

        def reject_repeat(self, name, inputs, error):
            if name == "apply_ast_edits" and isinstance(inputs.get("path"), str):
                self._ast_recovery_path = inputs["path"]
                self._ast_recovery_error = str(error)[:3500]
                self._ast_recovery_count = getattr(self, "_ast_recovery_count", 0) + 1
            super().reject_repeat(name, inputs, error)

        def apply(self, name, inputs, before=None):
            result = super().apply(name, inputs, before=before)
            if name == "apply_ast_edits" and not result.get('error'):
                if not getattr(self, "_geometry_recovery_active", False):
                    self._ast_recovery_count = 0
            return result

        def ask(self, messages, tools=None):
            if messages is self.messages and (getattr(self, "_ast_recovery_count", 0) >= 2 or getattr(self, "_geometry_recovery_active", False) or measured_height_failure(self.requirement_gate.context())) and not self.cp.pending:
                if not self._ast_recovery_path:
                    paths = getattr(self.requirement_gate, 'stage', {}).get('paths', [])
                    self._ast_recovery_path = next((p for p in paths if p.startswith('frontend/src/') and p.endswith('.tsx')), 'frontend/src/App.tsx')
                return self._focused_ast_ask(messages, tools or [])
            return super().ask(messages, tools)

        def _focused_ast_ask(self, messages, tools):
            self.h.log_event("autonomy.strategy", {"reason": "focused_ast_recovery", "path": self._ast_recovery_path})
            
            def get_file_data(rel_path):
                try:
                    p = editor(self.h).service._validate(rel_path)
                    if not p.is_file() or p.is_symlink(): return None
                    rel_path = p.resolve().relative_to(self.h.workspace.root.resolve())
                    if any(self.h.workspace.root.joinpath(*rel_path.parts[:i]).is_symlink() for i in range(len(rel_path.parts))):
                        return None
                        return None
                    if len(str(p)) > 9000: return None
                    
                    snap = editor(self.h).snapshot(str(rel_path))
                    with open(p, 'r', encoding='utf-8') as f:
                        raw = f.read()
                    if len(raw) > 9000: return None
                    
                    catalog = []
                    for n in snap['nodes']:
                        if n['kind'] == 'JsxOpeningElement' and 'complete JSX node ' in n['label']:
                            continue
                        src = n['source']
                        item = {"id": n['id'], "kind": n['kind'], "label": n['label'], "source": src}
                        catalog.append(item)
                    
                    self.read.add(str(rel_path))
                    return {"path": str(rel_path), "raw": raw, "catalog": catalog, "snap_id": snap['snapshot_id']}
                except Exception: return None

            files = []
            if self._ast_recovery_path:
                f1 = get_file_data(self._ast_recovery_path)
                if f1: files.append(f1)
            
            f2 = get_file_data("frontend/src/App.tsx")
            if f2 and (not files or f2['path'] != files[0]['path']):
                files.append(f2)

            if not files: return super().ask(messages, tools)

            prompt_parts = [
                f"Task: {self.args.task}\nContext: {self.requirement_gate.context()}\nError: {self._ast_recovery_error}\n",
                'System: Correct the actual failed behavior using existing AST nodes. Earlier tool turns made no progress. Use measured browser feedback and bounded ancestor layout; inspect both screen and shared parent source supplied. Change actual values, never return unchanged code. Return ONLY JSON {"path":"file","edits":[{"node_id":"id","code":"code"}]} OR {"path":"file","style_updates":[{"node_id":"id","styles":{"flex":1}}]}. Use 1..8 small nodes. For geometry specify only changed style properties (number/string/null); do not copy JSX. Use edits format only for structural/handler changes, never both. No prose, offsets, whole-file writes or invented IDs. In recovery paired opening IDs are omitted. Each catalog source is a COMPLETE scoped edit fragment. Local handler statement scopes may change statement kinds; other nodes keep their advertised kind. Use its current ID and return complete code with all existing children preserved, changing only needed behavior. No partial snippets or old error IDs.'
            ]
            
            for f in files:
                prompt_parts.append(f"File: {f['path']}\nCatalog: {json.dumps(f['catalog'], ensure_ascii=False, separators=(',', ':'))}\nSource: {f['raw']}")

            full_prompt = "\n".join(prompt_parts)
            if len(full_prompt) > 65000: return super().ask(messages, tools)

            focused_messages = [{"role": "system", "content": prompt_parts[1]}, {"role": "user", "content": "\n".join([prompt_parts[0]] + prompt_parts[2:])}]
            geometry_packet = geometry_prompt(self, files, self.requirement_gate.context())
            self._geometry_recovery_active = (geometry_packet is not None)
            if self._geometry_recovery_active:
                self._geometry_attempts += 1
                self._ast_recovery_count = max(self._ast_recovery_count, 2)
            else:
                self._geometry_attempts = 0
            if geometry_packet is not None: focused_messages=[{'role':'system','content':geometry_packet[0]},{'role':'user','content':geometry_packet[1]}]
            import os
            from runtime_policy import generation_settings
            baseline = generation_settings()['temperature']
            temperature = max(baseline, round(min(0.8, 0.4 + 0.1 * max(0, self._ast_recovery_count - 2)), 2))
            old = os.environ.get('LOCAL_LLM_TEMPERATURE')
            try:
                os.environ['LOCAL_LLM_TEMPERATURE'] = str(temperature)
                self.h.log_event("autonomy.strategy", {"reason": "recovery_sampling", "baseline_temperature": baseline, "temperature": temperature, "rejection_count": self._ast_recovery_count})
                resp = super().ask(focused_messages, [])
            finally:
                if old is not None: os.environ['LOCAL_LLM_TEMPERATURE'] = old
                else: os.environ.pop('LOCAL_LLM_TEMPERATURE', None)

            try:
                content = resp['content'].strip()
                start = content.find('{')
                if start == -1: raise ValueError("No JSON")
                
                data = json.JSONDecoder(object_pairs_hook=duplicate_hook).raw_decode(content[start:])[0]
                if geometry_packet is not None: 
                    if not isinstance(data, dict) or set(data) != {'path', 'style_updates'}: raise ValueError('Measured geometry recovery requires style_updates, not JSX copies')
                else: pass
                data, target_file, validation_nodes = normalize_response(data, files, self)
                
                if not isinstance(data['edits'], list) or not (1 <= len(data['edits']) <= 8):
                    raise ValueError("Invalid edits count")
                valid_edits = []
                for e in data['edits']:
                    if not isinstance(e, dict) or set(e.keys()) != {'node_id', 'code'} or not isinstance(e['node_id'], str) or not isinstance(e['code'], str):
                        raise ValueError("Invalid edit format")
                    nid, code = e['node_id'], e['code']
                    if len(nid) == 0 or len(code) == 0 or len(code) > 12000:
                        raise ValueError("Edit field error")
                    
                    node = next((n for n in validation_nodes if n['id'] == nid), None)
                    if not node or code == node['source']:
                        raise ValueError("Invalid node or redundant code")
                    valid_edits.append({"node_id": nid, "code": code})

                return {
                    "role": "assistant",
                    "content": resp['content'],
                    "tool_calls": [{
                        "function": {"name": "apply_ast_edits", "arguments": json.dumps({
                            "snapshot_id": target_file['snap_id'],
                            "path": data['path'],
                            "edits": valid_edits
                        })},
                        "id": f"ast-recovery-{self.used}"
                    }]
                }
            except Exception as e:
                self._ast_recovery_count += 1
                self._ast_recovery_error = str(e)
                self._ast_recovery_error = str(e)
                return {"role": "assistant", "content": f"Focused AST proposal invalid: {e}", "tool_calls": []}

    return Recovery

extend_recovery = extend_recovery
