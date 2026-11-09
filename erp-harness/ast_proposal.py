import json
import ast

def prepare(runner, system, user_content, current_source, target, context_text, docs, ponytail):
    """
    Prepares an AST-based editing session.
    """
    import ast_editing
    
    editor = ast_editing.editor(runner.h)
    snapshot = editor.snapshot(target)
    
    mode = {
        'kind': 'ast',
        'editor': editor,
        'snapshot': snapshot
    }
    
    # Instruction set for the model to enforce AST-only JSON edits
    ast_instructions = (
        "Return ONLY JSON: {\"edits\":[{\"node_id\":\"id\",\"code\":\"fragment\"}]}. "
        "Do not use old_text or offsets. Use provided node_ids and insertion slots only. "
        "Use 'imports' slot for new imports/types, 'prologue' for state/effects, "
        "'before_return' for cleanup/returns, and append JSX children for tables. "
        "Do not copy existing form or output whole component/file; preserve existing handlers/API/meta. "
        "Never repeat previous rejected JSON. Stop immediately after JSON. No explanations or alternative drafts."
    )
    
    new_system = ast_instructions + '\nProject/policy: ' + system.partition('Project:')[2]
    new_user = f"Goal: {runner.args.task}\nTarget: {target}\nAST catalog:\n{json.dumps(snapshot,ensure_ascii=False)}\nReference: {context_text}\nDocs: {docs}\nFeedback: {runner.feedback[:2200]}\n{ponytail}"
    
    # Emit autonomy strategy
    # Note: The prompt implies this is part of the returned state or a side effect 
    # but since we return (new_system, new_user, mode), we attach it to the mode or 
    # assume the runner handles the metadata. We'll attach it to mode for visibility.
    mode['autonomy'] = {
        'reason': 'ast_scoped_edits',
        'format': 'ast',
        'path': target,
        'target': target,
        'snapshot_id': snapshot['snapshot_id'],
        'node_count': len(snapshot['nodes']),
        'model_calls': 0
    }
    
    # Add target to runner.read to ensure permissions for the full snippet catalog
    runner.h.log_event('autonomy.strategy',mode['autonomy'])
    runner.read.add(target)
    
    return new_system, new_user, mode

def normalize(content, current_source, mode):
    """
    Validates and applies AST-based JSON edits.
    """
    if mode.get('kind') != 'ast':
        raise ValueError("Invalid mode: expected 'ast'")

    # Find the first '{' to isolate the JSON object from prose/markdown
    start_idx = content.find('{')
    if start_idx == -1:
        raise ValueError("No JSON object found in content")
    
    json_str = content[start_idx:]
    
    try:
        # Use object_pairs_hook to reject duplicate keys during parsing
        def reject_duplicates(ordered_pairs):
            d = {}
            for k, v in ordered_pairs:
                if k in d:
                    raise ValueError(f"Duplicate key: {k}")
                d[k] = v
            return d

        data, _ = json.JSONDecoder(object_pairs_hook=reject_duplicates).raw_decode(json_str)
    except json.JSONDecodeError as e:
        raise ValueError('Incomplete/truncated JSON proposal; retry scoped edits') from e

    # Validate root keys and structure
    if not isinstance(data, dict) or set(data) != {'edits'}:
        raise ValueError("Missing 'edits' key in JSON")
    
    edits = data['edits']
    if not isinstance(edits, list):
        raise ValueError("'edits' must be a list")
    
    # Validate edits 1..16 (max 16 edits per instruction)
    if len(edits) > 16:
        raise ValueError("Too many edits; maximum 16 allowed")

    valid_edits = []
    for edit in edits:
        if not isinstance(edit, dict):
            raise ValueError("Each edit must be a dictionary")
        
        # Check keys: only node_id and code allowed
        if not set(edit.keys()).issubset({'node_id', 'code'}):
            raise ValueError("Edit dict must only contain 'node_id' and 'code'")
        
        if not isinstance(edit.get('node_id'), str) or not isinstance(edit.get('code'), str):
            raise ValueError("node_id and code must be strings")
            
        valid_edits.append(edit)

    mode['edits'] = valid_edits
    
    # Apply edits via the editor
    editor = mode['editor']
    snapshot = mode['snapshot']
    
    # editor.apply is expected to handle strict IDs/hash/ranges/AST
    result = editor.apply(snapshot['path'], snapshot['snapshot_id'], valid_edits)
    
    # Return legacy bridge format for existing candidate validation
    return json.dumps({'edits': [{'old_text': current_source, 'new_text': result['new_text']}]}, ensure_ascii=False)

def tool_call(mode, target, edits, used=None):
    """
    Generates the tool call dictionary.
    """
    if isinstance(mode, dict) and mode.get('kind') == 'ast':
        return {
            'name': 'apply_ast_edits',
            'arguments': json.dumps({
                'path': target,
                'snapshot_id': mode['snapshot']['snapshot_id'],
                'edits': mode['edits']
            }, ensure_ascii=False)
        }
    else:
        return {
            'name': 'apply_edits',
            'arguments': json.dumps({
                'path': target,
                'edits': edits
            }, ensure_ascii=False)
        }
