import re, json, copy
from candidate_tools import TOOLS
from candidate_original_references import reference_fragments
from patch_reply_adapter import parse_reply

from candidate_guidance import scope_mode_instructions
from candidate_decode import decode_candidate
from candidate_blocks import format_candidate_context
from candidate_effective_catalog import effective_catalog
from snippet_node_patches import patch_nodes
from candidate_patch import revise
from ast_editing import editor
from candidate_snippet_tools import tool_spec, parse_tool_patches
from divide_plan import duplicate_hook

def ask_snippets(runner, proposal, catalog, ask):
    ed = editor(runner.h)
    snap = ed._snapshots.get(proposal['snapshot_id'])
    ranges = getattr(snap, 'ranges', {}) if snap else {}
    if not isinstance(ranges, dict): ranges = {}
    view_catalog = effective_catalog(catalog, proposal, ranges or {})
    node_map = {n['id']: n for n in view_catalog}
    spec = copy.deepcopy(TOOLS[0])
    spec['function']['name'] = 'replace_ast_fragments'
    spec['function']['description'] = 'Replace ACTIVE scoped AST node fragments. Local handler statement scopes may change statement kinds; other nodes keep their advertised kind. Submit only changed nodes; unchanged companion edits are retained automatically. Never wholefile. No cancellation in this tool.'
    if getattr(runner, '_paired_jsx_tags', False):
        spec['function']['description'] += ' Renaming a JsxOpeningElement also renames its matching closing tag automatically and preserves every child; return only the opening tag. Repeated imports already present elsewhere are deduplicated.'
    del spec['function']['parameters']['properties']['remove']
    spec['function']['parameters']['required'] = ['changes']
    spec['function']['parameters']['additionalProperties'] = False
    compact = getattr(runner, '_compact_fragment_output', False)
    if compact:
        changes = spec['function']['parameters']['properties']['changes']
        changes['maxItems'] = 2
        changes['items']['properties']['code']['maxLength'] = 2400
        spec['function']['description'] += ' Previous output was truncated. Return at most TWO small fragments, each <=2400 characters. Edit individual declarations or controls; do not repeat entire panels. Completed candidate edits are retained across actions.'
        view_catalog = [node for node in view_catalog if len(node.get('source', '')) <= 2400]
        node_map = {n['id']: n for n in view_catalog}
    packet = reference_fragments(catalog, view_catalog, proposal) + '\nACTIVE EDIT TARGETS:\n' + format_candidate_context(runner, proposal, view_catalog)
    if len(packet) > 70000: return {'content': 'Error: Packet too large', 'tool_calls': []}
    sys_msg = scope_mode_instructions(runner) + f"\n{spec['function']['description']}\nSubmit changes only using replace_ast_fragments, no cancellation."
    messages = [{'role': 'system', 'content': sys_msg}, {'role': 'user', 'content': packet}]
    response = ask(messages, [spec])
    try:
        if len(response.get('tool_calls', [])) == 1 and response['tool_calls'][0]['function']['name'] == 'replace_ast_fragments':
            data = json.loads(response['tool_calls'][0]['function']['arguments'], object_pairs_hook=duplicate_hook)
            if not isinstance(data, dict) or set(data) != {'changes'}: raise ValueError('replace_ast_fragments accepts only changes; cancellation is not part of this tool')
            if compact:
                from types import SimpleNamespace
                from tool_input_validation import validate_arguments
                validate_arguments(SimpleNamespace(tools=lambda: [spec]), 'replace_ast_fragments', data)
            return decode_candidate(runner, proposal, catalog, {'content': json.dumps({'changes': data['changes'], 'remove': []})})
        if len(response.get('tool_calls', [])) == 1 and response['tool_calls'][0]['function']['name'] == 'repair_ast_candidate':
            return decode_candidate(runner, proposal, catalog, {'content': response['tool_calls'][0]['function']['arguments']})
        patches = parse_tool_patches(response, node_map)
        if patches is None:
            content = response.get('content') or ''
            if content.lstrip().startswith(('{', '```json')) or re.search('^(EDIT|REMOVE|DROP_EDIT)\\s', content, re.MULTILINE):
                return decode_candidate(runner, proposal, catalog, response)
            patches = parse_reply(content)
        delta = patch_nodes(proposal, catalog, patches)
        updated = revise(proposal, delta['changes'], delta['remove'])
        ed.apply(proposal['path'], proposal['snapshot_id'], updated['edits'])
        runner._candidate_focus_error = ''
        runner.h.log_event('autonomy.strategy', {'reason': 'native_repair', 'node_ids': [p['node_id'] for p in patches]})
        return {'content': 'repair', 'tool_calls': [{'id': f'snippet-{runner.used}', 'function': {'name': 'repair_ast_candidate', 'arguments': json.dumps(delta)}}]}
    except Exception as e:
        runner._candidate_focus_error = str(e)
        return {'content': f'Snippet repair rejected: {str(e)}', 'tool_calls': []}
