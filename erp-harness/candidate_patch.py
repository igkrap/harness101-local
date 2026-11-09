import copy
from candidate_control_hints import unknown_removal_error
import json

def revise(proposal: dict, changes: list, remove: list) -> dict:
    """
    Revises a proposal dictionary based on changes and removals.
    
    Args:
        proposal: dict with {path, snapshot_id, source_hash, edits: [{node_id, code}, ...]}
        changes: list of dicts with {node_id, code} (max 16, len(code) <= 12000)
        remove: list of unique node_id strings to remove
        
    Returns:
        A deepcopied proposal with updated edits list.
    """
    if not isinstance(changes, list) or len(changes) > 16 or not isinstance(remove, list) or len(remove) > 16 or not all(isinstance(r, str) for r in remove) or len(set(remove)) != len(remove):
        raise ValueError("Invalid changes or remove list")
    for c in changes:
        if not isinstance(c, dict) or set(c.keys()) != {'node_id', 'code'} or not isinstance(c['node_id'], str) or not c['node_id'] or not isinstance(c['code'], str) or len(c['code']) > 12000:
            raise ValueError("Invalid change format")
    if set(proposal.keys()) != {'path', 'snapshot_id', 'source_hash', 'edits'}:
        raise ValueError("Unknown keys in proposal")
    new_proposal = copy.deepcopy(proposal)
    existing_edits = new_proposal.get('edits', [])
    
    change_map = {}
    for c in changes:
        nid = c['node_id']
        code = c['code']
        if nid in change_map:
            raise ValueError("Duplicate change IDs")
        change_map[nid] = code

    # 2. Validate removals and ambiguity
    remove_set = set(remove)
    for nid in remove_set:
        if nid in change_map:
            raise ValueError("Ambiguous: node in both remove and changes")

    # 3. Build the new edits list
    # We use an OrderedDict-like approach via dict to maintain order/uniqueness
    # but the requirement asks for an ordered dict of operations.
    # We'll build the final edits list by:
    # - Keeping existing edits if not in remove or change_map
    # - Adding/Replacing from change_map
    # - Removing if in remove_set
    
    existing_ids = set()
    for e in existing_edits:
        if not isinstance(e, dict) or set(e.keys()) != {'node_id', 'code'} or not isinstance(e['node_id'], str) or not e['node_id'] or not isinstance(e['code'], str) or len(e['code']) > 12000:
            raise ValueError("Invalid existing edit")
        existing_ids.add(e['node_id'])
    for rid in remove_set:
        if rid not in existing_ids:
            raise ValueError(unknown_removal_error(rid, existing_ids))

    # Construct new edits list
    # We must preserve the order of existing edits for unchanged nodes,
    # and append new nodes from changes.
    new_edits = []
    seen_ids = set()

    # Process existing edits (Preserve unchanged and apply replacements)
    for e in existing_edits:
        nid = e['node_id']
        if nid in remove_set:
            continue
        if nid in change_map:
            new_edits.append({'node_id': nid, 'code': change_map[nid]})
        else:
            new_edits.append(e)
        seen_ids.add(nid)

    # Process new changes (Add nodes that didn't exist)
    for nid, code in change_map.items():
        if nid not in seen_ids:
            new_edits.append({'node_id': nid, 'code': code})
            seen_ids.add(nid)

    if not new_edits:
        raise ValueError('Discard empty proposal instead')

    new_proposal['edits'] = new_edits
    if not (1 <= len(new_edits) <= 16) or len(json.dumps(new_proposal, ensure_ascii=False)) > 18000:
        raise ValueError('Proposal too large; reduce edits or discard')
    return new_proposal
