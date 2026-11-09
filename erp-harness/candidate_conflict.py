import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple
from ast_editing import editor
from candidate_patch import revise
from candidate_guidance import scope_mode_instructions

@dataclass
class NodeInfo:
    id: str
    kind: str
    label: str
    source: str

def resolve_conflict(runner: Any, proposal: Dict[str, Any], ask: Any) -> Optional[Dict[str, Any]]:
    ed = editor(runner.h)
    path = proposal['path']
    info = ed.snapshot(path)
    
    if not info or info.get('snapshot_id') != proposal.get('snapshot_id'):
        return

    sid = info['snapshot_id']
    snap = ed._snapshots[sid]
    
    # proposal['edits'] is List[Dict] with node_id/code
    # We need to find conflicts in the proposed changes relative to the current AST state
    # or between the proposed changes themselves if they overlap.
    # The requirement specifies: duplicate start OR intervals overlap OR zero-length insertion within interval.
    
    proposed_ranges: Dict[str, Tuple[int, int]] = {}
    proposed_nodes: Dict[str, NodeInfo] = {}
    
    for edit in proposal['edits']:
        nid = edit['node_id']
        if nid in snap.nodes:
            node = snap.nodes[nid]
            proposed_nodes[nid] = NodeInfo(node.id, node.kind, node.label, edit['code'])
            # Assuming snap.ranges provides the byte offsets for the node
            proposed_ranges[nid] = snap.ranges[nid]

    conflict_pair: Optional[Tuple[str, str, Tuple[int, int], Tuple[int, int]]] = None

    edit_ids = list(proposed_ranges.keys())
    for i in range(len(edit_ids)):
        for j in range(i + 1, len(edit_ids)):
            id1, id2 = edit_ids[i], edit_ids[j]
            if id1 == id2: continue
            
            r1, r2 = proposed_ranges[id1], proposed_ranges[id2]
            
            # Check duplicate start
            dup_start = (r1[0] == r2[0])
            # Check overlap
            overlap = max(r1[0], r2[0]) < min(r1[1], r2[1])
            # Check zero-length insertion within interval (including boundaries)
            zero_in = (r1[0] == r1[1] and r2[0] <= r1[0] <= r2[1]) or \
                      (r2[0] == r2[1] and r1[0] <= r2[0] <= r1[1])
            
            if dup_start or overlap or zero_in:
                # Sort by span length DESC: larger is A, smaller is B
                span1 = r1[1] - r1[0]
                span2 = r2[1] - r2[0]
                if span1 >= span2:
                    conflict_pair = (id1, id2, r1, r2)
                else:
                    conflict_pair = (id2, id1, r2, r1)
                break
        if conflict_pair: break

    if not conflict_pair:
        return

    aid, bid, ar, br = conflict_pair
    node_a, node_b = proposed_nodes[aid], proposed_nodes[bid]
    
    # Prepare prompt
    choices_str = "\n".join([
        f"ID: {n.id}, Kind: {n.kind}, Scope: {n.label}, Code:\n```\n{n.source}\n```"
        for n in [node_a, node_b]
    ])

    prompt = scope_mode_instructions(runner) + "\n" + (
        f"Path: {path}\n"
        f"Feedback: {str(getattr(runner, 'feedback', ''))[:2500]}\n"
        f"Previous Error: {getattr(runner, '_candidate_conflict_error', '')}\n\n"
        f"Conflict detected between overlapping operations.\n"
        f"A (Larger): {aid} ({node_a.kind})\n"
        f"B (Smaller): {bid} ({node_b.kind})\n\n"
        f"Choices:\n{choices_str}\n\n"
        f"Instructions: Overlapping parent+child operations cannot apply atomically. "
        f"Choose operation preserving desired goal. Prefer A if parent includes child changes.\n"
        f"Respond ONLY with 'A' to keep A and remove B, or 'B' to keep B and remove A."
    )

    try:
        response = ask([{"role": "user", "content": prompt}], [])
        content = (response.get('content') or '').strip().upper()
    except Exception as e:
        raise e

    if content not in ('A', 'B'):
        runner._candidate_conflict_error = f"Invalid model response: {content}"
        return {"content": runner._candidate_conflict_error, "tool_calls": []}

    remove_id = bid if content == 'A' else aid
    keep_id = aid if content == 'A' else bid

    # Validate legality via revise
    try:
        # revise(proposal, edits_to_apply, ids_to_remove)
        revise(proposal, [], [remove_id])
    except Exception as e:
        runner._candidate_conflict_error = f"Conflict resolution invalid: {str(e)}"
        return {"content": runner._candidate_conflict_error, "tool_calls": []}

    # Success: update proposal and return synthetic tool call
    # We don't modify proposal in-place for the runner's actual state, 
    # but we prepare the metadata for the next step in the pipeline.
    
    # Construct tool call for the repair pipeline
    tool_call = {
        "id": f"conflict-{runner.used}",
        "type": "function",
        "function": {
            "name": "repair_ast_candidate",
            "arguments": json.dumps({'changes': [], 'remove': [remove_id]})
        }
    }
    
    runner._candidate_conflict_error = None
    return {"content": content, "tool_calls": [tool_call]}
