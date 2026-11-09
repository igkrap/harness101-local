from final_edit_group import select_final_edit_blocks
import json
import re
from candidate_patch import revise
from candidate_delta import compact_candidate_changes
from ast_editing import editor
from divide_plan import duplicate_hook
from candidate_blocks import parse_blocks, format_candidate_context
from candidate_guidance import repair_mode_instructions, scope_mode_instructions

def decode_candidate(runner, fail, catalog, resp):
    content = resp['content']
    if re.search('^(EDIT|REMOVE|DROP_EDIT)\\s', content, re.MULTILINE):
        data = parse_blocks(select_final_edit_blocks(content))
    else:
        start_idx = content.find('{')
        if start_idx == -1:
            raise ValueError('No JSON object found')
        data = json.JSONDecoder(object_pairs_hook=duplicate_hook).raw_decode(content[start_idx:])[0]
        if not isinstance(data, dict) or set(data) != {'changes', 'remove'}:
            raise ValueError()
    if not all((k in data for k in ('changes', 'remove'))):
        raise KeyError('Missing changes/remove keys')
    if not data['changes'] and (not data['remove']):
        raise ValueError('No repair changes; fix the reported failure instead of replaying the failed proposal')
    revise(fail, data['changes'], data['remove'])
    data = compact_candidate_changes(data, catalog, fail)
    catalog_map = {n['id']: n for n in catalog}
    retained_map = {e['node_id']: e['code'] for e in fail['edits']}
    for change in data['changes']:
        cid = change['node_id']
        if cid not in catalog_map:
            raise ValueError(f'Unknown node_id: {cid}')
        if change['code'] == catalog_map[cid]['source'] or (cid in retained_map and change['code'] == retained_map[cid]):
            raise ValueError(f'No-op change for {cid}')
    runner._candidate_focus_error = None
    return {'content': json.dumps(data), 'tool_calls': [{'function': {'name': 'repair_ast_candidate', 'arguments': json.dumps(data)}, 'id': f'candidate-focus-{runner.used}'}]}
