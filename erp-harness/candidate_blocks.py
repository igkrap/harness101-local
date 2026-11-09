import re
from candidate_control_hints import retained_control_hint

def parse_blocks(content: str) -> dict:
    if not isinstance(content, str):
        raise ValueError("Content must be str")
    if len(content) > 100000:
        raise ValueError("Input too long")

    pattern = re.compile(r'^(EDIT|REMOVE|DROP_EDIT)\s+([a-zA-Z0-9_-]+)(?:\s+line\s+\d+)?$', re.MULTILINE)
    lines = content.splitlines(keepends=True)
    
    edits, removes = [], []
    seen_ids = set()
    idx = 0
    
    while idx < len(lines):
        line = lines[idx]
        if not line.strip():
            idx += 1
            continue
            
        match = pattern.match(line.strip())
        if not match:
            raise ValueError(f"Invalid header or prose: {line.strip()}")
        
        action, node_id = match.groups()
        if node_id in seen_ids:
            raise ValueError(f"Duplicate ID: {node_id}")
        seen_ids.add(node_id)
        
        if action in ('REMOVE', 'DROP_EDIT'):
            removes.append(node_id)
            idx += 1
        else:
            idx += 1
            while idx < len(lines) and not lines[idx].strip():
                idx += 1
            if idx >= len(lines):
                raise ValueError("Missing code block after EDIT")
            
            fence_match = re.fullmatch(r'```(tsx|ts|jsx|javascript|js)?', lines[idx].strip())
            if not fence_match:
                raise ValueError("Invalid code fence")
            
            idx += 1
            code_lines = []
            found_end = False
            while idx < len(lines):
                if lines[idx].strip() == '```':
                    found_end = True
                    idx += 1
                    break
                code_lines.append(lines[idx])
                idx += 1
            
            if not found_end:
                raise ValueError("Unterminated code fence")
            
            full_code = "".join(code_lines)
            # Remove ONLY the final line terminator separating code from closing fence
            if full_code.endswith('\n'):
                # Check if it was CRLF
                if full_code.endswith('\r\n'):
                    full_code = full_code[:-2]
                else:
                    full_code = full_code[:-1]
            elif full_code.endswith('\r'):
                full_code = full_code[:-1]

            if not full_code.strip():
                raise ValueError("Empty code block")
            if len(full_code) > 12000:
                raise ValueError("Code block too large")
            
            edits.append({"node_id": node_id, "code": full_code})

    if len(edits) > 8 or len(removes) > 8:
        raise ValueError("Too many changes")
    if any(eid in removes for eid in [e['node_id'] for e in edits]):
        raise ValueError("ID in both edit and remove")
    if not edits and not removes:
        raise ValueError("No actions")

    return {"changes": edits, "remove": removes}

from candidate_diagnostics import faulty_candidate_nodes
from candidate_targets import order_candidate_nodes
from lint_binding_targets import unused_binding_targets

def format_candidate_context(runner, proposal, catalog) -> str:
    out = [f"current stage={runner.args.task}"]
    # The focused repair call has fresh messages; retain the already retrieved
    # component contracts instead of losing them when the agent enters repair.
    retrieved = getattr(runner, '_component_retrieval', None)
    if retrieved and len(retrieved) == 2 and isinstance(retrieved[1], str):
        out.append(retrieved[1])
    out.append(f"failure={str(runner.feedback)[:7000]}")
    gate=getattr(runner, 'requirement_gate', None)
    context=getattr(gate, 'context', None)
    if callable(context):
        out.append(f"ACCEPTANCE CRITERIA (must hold together with latest compiler/framework feedback): {str(context())[:10000]}")
    out.append(f"parse_error={getattr(runner, '_candidate_focus_error', '')}")
    out.append(f"proposal={proposal['path']}/{proposal['snapshot_id']}/{proposal['source_hash']}")
    
    faulty = faulty_candidate_nodes(runner, proposal, str(runner.feedback))
    binding_ids, binding_hint = unused_binding_targets(proposal['path'], str(runner.feedback), catalog)
    catalog, target_hint = order_candidate_nodes(runner, proposal, catalog, faulty + binding_ids)
    out.append(binding_hint)
    out.append(target_hint)
    if faulty:
        out.append(f"FAULTY OPERATIONS: {','.join(faulty)} (compiler/AST coordinates mapped to the retained edits; fix these operations first, unchanged companions retained automatically)")

    out.append("RETAINED IDS (DROP_EDIT allowed only for these): " + retained_control_hint(proposal.get('edits', [])))
    out.append("\nRETAINED")
    sorted_edits = sorted(proposal.get('edits', []), key=lambda e: e['node_id'] not in faulty)
    for e in sorted_edits:
        nid = e['node_id']
        out.append(f"RETAINED {nid}\n```tsx\n{e['code']}\n```")
        
    out.append("\nCURRENT NODES")
    for node in catalog:
        nid, kind, scope = node['id'], node['kind'], node['label']
        out.append(f"NODE {nid} KIND {kind} SCOPE {scope}")
        if node.get('source'):
            out.append(f"```tsx\n{node['source']}\n```")
        else:
            out.append(f"(empty insertion point; use scope {scope})")
            
    return "\n".join(out)
