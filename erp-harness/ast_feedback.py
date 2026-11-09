import json
import subprocess
import pathlib

def validate_fragments(editor, path, snapshot_id, snap, ops):
    normalized = []
    for start, end, nid, code in ops:
        node = snap.nodes[nid]
        cmd = [editor.service.node, str(pathlib.Path(__file__).with_name('ast_validate_fragments.cjs'))]
        payload = json.dumps({'edits': [{'kind': node.kind, 'label': node.label, 'code': code,
            **({'handler_statement_scope': True} if node.handler_statement_scope else {}),
            **({'original_code': node.source, 'nested_handler_scope': True}
               if node.handler_scope and editor.allow_nested_handlers else {})}]})
        data = {'ok': False, 'error': '', 'diagnostics': []}
        try:
            res = subprocess.run(cmd, input=payload, text=True, capture_output=True, timeout=10)
            try:
                out = json.loads(res.stdout)
                data.update(out)
                if res.returncode == 0 and data.get('ok') is True:
                    normalized.append((start, end, nid, data['edits'][0]['code']))
                    continue
            except json.JSONDecodeError:
                data['error']='Validator returned malformed JSON: '+res.stdout[:400]
            if res.returncode != 0:
                data['error'] = data.get('error') or res.stderr or 'Validator failed'
        except Exception as e:
            data['error'] = str(e)

        details = {
            'stage': 'fragment_validation', 'path': str(path), 'snapshot_id': snapshot_id,
            'node_id': nid, 'expected_kind': node.kind, 'scope': node.label,
            'error': (data.get('error') or 'Validator rejected fragment without a diagnostic')[:600], 'diagnostics': data['diagnostics'][:5],
            'layout_targets': [{"node_id": n.id, "kind": n.kind, "label": n.label, "source_preview": n.source[:180]} for n in snap.nodes.values() if n.kind in ('JsxElement', 'JsxFragment', 'JsxSelfClosingElement', 'JsxOpeningElement') and 'return' in n.label.lower()][:4],
            'scope_rule': 'Replace only the selected node kind. For screen layout use a return JSX node or its opening tag; never put whole-file or exported screen code in metadata or function-body slots.',
            'source_changed': False, 'applied': False,
            'retry_instruction': 'Original source unchanged; snapshot remains valid. Correct the reported fragment and resend the complete edit batch; no edits were applied. Do not repeat inspections unless stale snapshot is reported.',
            'original_code_truncated': len(node.source) > 1000, 'proposed_code_truncated': len(code) > 1400,
            'original_length': len(node.source), 'proposed_length': len(code),
            'all_edit_node_ids': [op[2] for op in ops]
        }
        if node.handler_scope:
            details['fix_hint'] = 'Replace this complete nested handler function only; preserve its name, parameters and type signature. Only its async modifier and body may change; no exports/defaults or JSX.'
        elif node.handler_statement_scope:
            details['scope_rule'] = 'Replace only this local handler statement range with complete local statements; statement kinds may change. Surrounding handler, imports and component stay outside this edit.'
            details['fix_hint'] = 'One or more complete local statements are allowed here, without JSX or module syntax; the 3000-character bound still applies.'
        elif node.kind == 'ImportDeclaration':
            details['fix_hint'] = 'multiple complete import declarations allowed, preserve still-used imports, avoid duplicates already elsewhere; use after-imports slot for new imports.'
        elif node.kind == 'JsxOpeningElement':
            details['fix_hint'] = 'Opening tag attributes ONLY: code must contain just <Component props...>, never children or </Component>. To add/move panels choose a complete JsxElement node from the PRIMARY stage file catalog; opening tag cannot add children.'
        elif node.kind.startswith('Jsx'):
            details['fix_hint'] = 'code must begin with \'<\' and end with its JSX closing tag; omit \'return (\' and trailing \');\' and enclosing function delimiters.'
        elif node.kind=='insert' and 'JSX' in node.label:
            details['fix_hint'] = 'Insert only child JSX INSIDE the indicated parent before its closing tag; never repeat the parent/form or close enclosing functions.'
        else:
            details['fix_hint'] = 'complete same-kind statements or insertion slot.'
        details['original_code'] = node.source[:1000]
        details['proposed_code'] = code[:1400]
        
        if data['diagnostics']:
            diag = data['diagnostics'][0]
            if 'line' in diag and diag['line'] is not None:
                lines = code.splitlines()
                idx = diag['line'] - 1
                start_idx, end_idx = max(0, idx - 2), min(len(lines), idx + 3)
                details['error_context'] = "\n".join(lines[start_idx:end_idx])[:800]
        
        raise ValueError('AST_EDIT_FEEDBACK ' + json.dumps(details, ensure_ascii=False))
    return normalized
