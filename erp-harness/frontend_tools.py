import copy
import json

def filter_tools(runner, items: list, *, stable_schema: bool = False) -> list:
    """Filters OpenAI tool dicts based on runner context and frontend scope logic."""
    modes = getattr(runner, 'modes', [])
    if (stable_schema and set(modes) == {'backend'} and
            getattr(runner.args, 'context_profile', 'legacy') == 'focused'):
        # These tools operate on frontend source/component contracts only.
        # Keep this set static throughout a backend task so cache prefixes remain stable.
        unsupported = {'inspect_code', 'apply_ast_edits', 'search_components', 'astryx_docs'}
        return [item for item in items if item.get('function', {}).get('name') not in unsupported]
    is_frontend = any(m in ('frontend', 'framework') for m in modes)
    is_backend = 'backend' in modes
    
    frontend_scope = is_frontend and not is_backend
    
    if is_frontend and is_backend:
        contract_raw = getattr(getattr(runner,'requirement_gate',None),'frozen_contract',None)
        if isinstance(contract_raw, str):
            try:
                contract = json.loads(contract_raw)
                checks = contract.get('criteria', [])
                if checks:
                    valid_ops = {'layout', 'visible', 'text', 'scenario'}
                    frontend_scope = all(c.get('check',{}).get('op') in valid_ops for c in checks)
                else:
                    frontend_scope = False
            except (json.JSONDecodeError, AttributeError, TypeError):
                frontend_scope = False
        else:
            frontend_scope = False

    if not frontend_scope or getattr(runner.args,'edit_format','auto') in ('diff', 'whole'):
        return items

    forbidden_names = {
        'edit_file', 'apply_edits', 'apply_insertions', 'insert_text',
        'add_java_annotations', 'isolate_spring_test', 'update_seed_rows'
    }
    
    initial_files = set(getattr(runner, 'initial_frontend_files', set()))
    if stable_schema:
        # This bounded hint must not change the prompt prefix after reads or compaction.
        # Runner.apply enforces the existing-file restriction for the full set.
        sorted_files = sorted(initial_files)
    else:
        read_paths = set(getattr(runner, 'read', set()))
        sorted_files = sorted(list(read_paths.intersection(initial_files))) + sorted(list(initial_files.difference(read_paths)))
    sorted_files = sorted_files[:64]
    
    new_items = []
    for item in items:
        func = item.get('function', {})
        name = func.get('name')
        
        if name in forbidden_names:
            continue
            
        if name == 'write_file':
            new_item = copy.deepcopy(item)
            new_desc = (new_item['function'].get('description', '') + 
                        " (Use for NEW source files or workspace JSON only; "
                        "existing JS/TS/JSX/TSX must use provided AST IDs.)")
            new_item['function']['description'] = new_desc.strip()
            
            params = new_item['function'].get('parameters', {})
            props = params.get('properties', {})
            if isinstance(props.get('path'), dict) and initial_files:
                props['path']['not'] = {'enum': sorted_files}
            new_items.append(new_item)
        else:
            # Keep non-write tools as original objects per requirement
            new_items.append(item)
            
    if getattr(runner, '_division_ast_focus', False):
        return [i for i in new_items if i.get('function', {}).get('name') in ('apply_ast_edits', 'write_file')]
    return new_items
