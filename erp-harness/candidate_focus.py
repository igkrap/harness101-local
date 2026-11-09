from final_edit_group import select_final_edit_blocks
import json
import re
from candidate_patch import revise
from candidate_delta import compact_candidate_changes
from ast_editing import editor
from divide_plan import duplicate_hook
from candidate_blocks import parse_blocks, format_candidate_context
from candidate_guidance import repair_mode_instructions, scope_mode_instructions
from candidate_targets import order_candidate_nodes
from candidate_leaf_scope import leaf_scope

def ask_candidate(runner, ask):
    """Focuses the model on repairing a specific failed AST candidate."""
    request_in_progress = False
    try:
        fail = runner._failed_ast_candidate
        ed = editor(runner.h)
        info = ed.snapshot(fail['path'])
        runner.read.add(fail['path'])
        
        if info['snapshot_id'] != fail['snapshot_id']:
            return {"content": "stale", "tool_calls": [{"function": {"name": "discard_ast_candidate", "arguments": "{}"}, "id": f"candidate-stale-{runner.used}"}]}

        # Filter nodes: exclude JsxOpeningElement with complete JSX node, include others <= 12000
        catalog = []
        for node in info['nodes']:
            is_jsx_open = node.get('kind') == 'JsxOpeningElement' and "complete JSX node" in node.get('label', '')
            if (not is_jsx_open or node['id'] in {e['node_id'] for e in fail['edits']}) and len(node.get('source', '')) <= 12000:
                catalog.append(node)
        
        catalog = catalog[:100]
        catalog, target_hint = order_candidate_nodes(runner, fail, catalog, [])
        if target_hint:
            keep_ids = [e['node_id'] for e in fail['edits']] + re.findall(r'\b[ns]\d+\b', target_hint)
            catalog = leaf_scope(catalog, ed._snapshots.get(info['snapshot_id']), keep_ids)
        if fail is not None:
            runner._candidate_snippet_hash = fail['source_hash']
            from candidate_snippet_repair import ask_snippets
            request_in_progress = True
            return ask_snippets(runner, fail, catalog, ask)
        payload = format_candidate_context(runner, fail, catalog)
        if len(payload) > 70000:
            raise ValueError("Context packet too large")

        request_in_progress = True
        system = (
            "model output must use EDIT <exact_node_id> line followed by a ```tsx fenced COMPLETE scoped fragment (local handler statement kinds may change; other nodes preserve their kind), "
            "optional DROP_EDIT <retained_id> on separate line (cancel a retained operation, not current source). No JSON wrapping/quotes/escaped newline strings. "
            "Native changes may touch multiple nodes atomically, prefer 1..4 small existing named panel/form nodes, max 8. "
            "Reuse existing state and real API save handlers; if duplicate forms separate query from registration instead of cloning create forms; "
            "initially required form must be initially visible. Slots allow only their scope: function slots local statements, "
            "append child slots do not replace existing panels. Don't invent missing backend endpoints in frontend-only stage. "
            "Preserve companions, real behavior, never weaken checks. ONLY EDIT/DROP_EDIT blocks, no prose. "
            "Do not include literal code examples with fixed values."
        )

        system = scope_mode_instructions(runner) + "\n" + system
        system += "\n" + repair_mode_instructions(fail)

        resp = ask([{"role": "system", "content": system}, {"role": "user", "content": payload}], [])
        request_in_progress = False
        content = resp['content']
        
        if re.search(r'^(EDIT|REMOVE|DROP_EDIT)\s', content, re.MULTILINE):
            data = parse_blocks(select_final_edit_blocks(content))
        else:
            start_idx = content.find('{')
            if start_idx == -1:
                raise ValueError("No JSON object found")
            data = json.JSONDecoder(object_pairs_hook=duplicate_hook).raw_decode(content[start_idx:])[0]
            if not isinstance(data, dict) or set(data) != {'changes', 'remove'}: raise ValueError()

        if not all(k in data for k in ("changes", "remove")):
            raise KeyError("Missing changes/remove keys")

        # Pure shape and logic validation
        if not data['changes'] and not data['remove']: raise ValueError('No repair changes; fix the reported failure instead of replaying the failed proposal')
        revise(fail, data['changes'], data['remove'])
        data = compact_candidate_changes(data, catalog, fail)

        # Semantic validation: IDs must exist in catalog, code must differ from current/retained
        catalog_map = {n['id']: n for n in catalog}
        retained_map = {e['node_id']: e['code'] for e in fail['edits']}
        
        for change in data['changes']:
            cid = change['node_id']
            if cid not in catalog_map:
                raise ValueError(f"Unknown node_id: {cid}")
            if change['code'] == catalog_map[cid]['source'] or (cid in retained_map and change['code'] == retained_map[cid]):
                raise ValueError(f"No-op change for {cid}")

        runner._candidate_focus_error = None
        return {
            "content": json.dumps(data),
            "tool_calls": [{"function": {"name": "repair_ast_candidate", "arguments": json.dumps(data)}, "id": f"candidate-focus-{runner.used}"}]
        }

    except Exception as e:
        if request_in_progress: raise
        if isinstance(e, (KeyboardInterrupt, SystemExit)): raise
        err_msg = f"Failed proposal repair invalid: {str(e)}"
        runner._candidate_focus_error = str(e)
        return {"content": err_msg, "tool_calls": []}
