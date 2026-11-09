import json
from json import JSONDecoder
from cycle_context import cycle_context
from patch_edits import patch_arguments

def propose_patch(runner, call):
    if getattr(runner, "_identical_rejections", 0) >= 3:
        raise RuntimeError("No progress: identical patch rejected three times; " + getattr(runner, "_proposal_rejection", "")[:200])
    service = cycle_context.service(runner.h)
    structs = [i for i in cycle_context.structures(runner) if "error" not in i]
    biz_screens = sorted([i["path"] for i in structs if any(t in ["form", "TextInput"] for t in i["jsx_tags"])])
    missing = [p for p in biz_screens if not any(t.endswith(("Table", "Grid")) or t in ["DataGrid", "DataTable"] for t in next(x["jsx_tags"] for x in structs if x["path"] == p))]
    
    if not missing:
        if runner.accepted:
            return {'role': 'assistant', 'content': json.dumps({'status': 'complete'}), 'tool_calls': [{'id': 'finish-' + str(runner.used), 'type': 'function', 'function': {'name': 'finish', 'arguments': '{}'}}]}
        return {'role': 'assistant', 'content': 'Error: No missing grid screens found.', 'tool_calls': []}
    
    target = missing[0]
    context_text, paths_set = cycle_context.snapshot(runner)
    runner.read.update(paths_set)
    
    if getattr(runner.args,'edit_format','auto') in ('diff','whole') and target not in runner.read:
        return {'role': 'assistant', 'content': f'Target {target} not in read set.', 'tool_calls': []}
    
    current_source = service._validate(target).read_text(encoding='utf-8')
    
    if not hasattr(runner, '_grid_docs'):
        docs_res = runner.h._execute_tool('astryx_docs', {'topic': 'Table'})
        runner._grid_docs = json.dumps(docs_res)[:5000] if isinstance(docs_res, dict) else ""
    
    from project_context import project_context
    proj_ctx = project_context(runner.h.workspace.root)[:4500]
    from runtime_policy import frontend_contract
    policy = frontend_contract(runner.modes)
    
    ponytail = ""
    if runner.args.ponytail in ('full', 'ultra'):
        import os
        p_path = os.environ.get('PONYTAIL_SKILL_PATH', os.path.expanduser('~/.local/share/mlx-server/skills/ponytail/SKILL.md'))
        try:
            with open(p_path, 'r') as f:
                ponytail = f.read(12000)
        except Exception: pass

    user_content = (f"Goal: {runner.args.task}\nTarget: {target}\nContext: {context_text}\n"
                    f"Docs: {runner._grid_docs}\nFeedback: {runner.feedback[:2200]}\n"
                    f"Last Rejection: {getattr(runner, '_proposal_rejection', '')[:3500]}\n{ponytail}")
    
    system = ("Return ONLY JSON with an edits array of old_text and new_text. "
              f"Perform 1 to 8 precise text transformations, ensuring each replacement string does not exceed 32000 characters. Must include import, state, GETfetch, columns, renderedTable. "
              f"Preserve registrationform/API/meta. No toolcalls/thoughts. Project: {proj_ctx} Policy: {policy}")

    from proposal_format import prepare, normalize
    from ast_proposal import tool_call
    system,user_content,whole_file = prepare(runner,system,user_content,current_source,target,context_text,runner._grid_docs,ponytail)
    response = call([{'role': 'system', 'content': system}, {'role': 'user', 'content': user_content}], [])
    content = response.get('content') or ''
    
    try:
        content = normalize(content,current_source,whole_file)
        decoder = JSONDecoder()
        pos = 0
        last_valid_edits = None
        while pos < len(content):
            pos = content.find('{', pos)
            if pos == -1: break
            try:
                obj, end = decoder.raw_decode(content[pos:])
                if 'edits' in obj and isinstance(obj['edits'], list):
                    last_valid_edits = obj['edits']
                    pos += end
                else:
                    pos += 1
            except Exception:
                pos += 1
        
        if not last_valid_edits and getattr(getattr(runner.h,"llm",None),"last_finish_reason",None)=="length":
            raise ValueError("actionableoutput-truncatedmessage: use shortuniqueanchors, onlynewcode, no unchangedfunction/form copies.")
        elif not last_valid_edits:
            raise ValueError("No valid JSON edits found in response")

        edits = last_valid_edits[:8]
        # Validate edit sizes
        if isinstance(whole_file, dict) and whole_file.get('kind') == 'ast':
            for e in edits: pass
            patched_data = whole_file['editor'].apply(target,whole_file['snapshot']['snapshot_id'],whole_file['edits'])
        else:
            for e in edits:
                if len(e['old_text']) > 32000 or len(e['new_text']) > 32000:
                    raise ValueError("Edit size exceeds 32000 chars")
            patched_data = patch_arguments({'path': target, 'edits': edits}, current_source)
        # AST Validation
        candidate_text = patched_data['new_text']
        if service._ast(target, candidate_text).get('error') or service._ast(target, candidate_text).get('diagnostics', []):
            raise ValueError(f'{json.dumps(service._ast(target, candidate_text).get("diagnostics", []), ensure_ascii=False)[:1600]}')
        
        if 'form' in service._ast(target, current_source).get('jsx_tags', []) and 'form' not in service._ast(target, candidate_text).get('jsx_tags', []):
            raise ValueError('Existing registration form must be preserved')
        # Check if it actually contains a table-like structure in the new text
        if not any(t.endswith(('Table', 'Grid')) for t in service._ast(target, candidate_text).get('jsx_tags', [])):
             raise ValueError("No Table/Grid JSX in proposed code")

        runner._proposal_rejection = ""
        runner._identical_rejections = 0
        runner._proposal_failures = 0
        if isinstance(whole_file, dict) and whole_file.get('kind') == 'ast':
            return {'role': 'assistant', 'content': None, 'tool_calls': [{'id':f'proposal-{runner.used}','type':'function','function':tool_call(whole_file,target,edits,runner.used)}]}
        return {'role': 'assistant', 'content': None, 'tool_calls': [{
            'id': f'proposal-{runner.used}',
            'type': 'function',
            'function': {'name': 'apply_edits', 'arguments': json.dumps({'path': target, 'edits': edits}, ensure_ascii=False)}
        }]}

    except Exception as e:
        runner._proposal_failures = getattr(runner,'_proposal_failures',0)+1
        import hashlib
        fingerprint = hashlib.sha256((str(e) + content).encode()).hexdigest()
        if getattr(runner, '_rejection_fingerprint', None) == fingerprint:
            runner._identical_rejections = getattr(runner, '_identical_rejections', 0) + 1
        else:
            runner._rejection_fingerprint = fingerprint
            runner._identical_rejections = 1
        err_msg = f"{str(e)}\n{content[:3000]}"
        runner._proposal_rejection = err_msg
        runner.feedback = f"Patch rejected before write: {str(e)}"
        if isinstance(whole_file, dict) and whole_file.get('kind') == 'ast':
            runner.feedback += "\nRejected AST fragments (NOT current source):\n" + json.dumps(whole_file.get('edits', []), ensure_ascii=False)[:1600]
        runner.h.log_event("autonomy.proposal_rejected",{"reason":str(e),"path":target,"before_write":True})
        return {'role': 'assistant', 'content': runner.feedback, 'tool_calls': []}
