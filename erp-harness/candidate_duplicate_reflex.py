from __future__ import annotations
import json
import subprocess
import pathlib
from ast_editing import editor
from candidate_patch import revise

def resolve_duplicate(runner, proposal) -> dict | None:
    try:
        feedback = runner.feedback or ""
        if "error TS2451:" not in feedback:
            return None
        
        # Extract name from "Cannot redeclare block-scoped variable 'NAME'."
        parts = feedback.split("error TS2451:")
        if len(parts) < 2:
            return None
        msg = parts[1].strip()
        name = msg.split("'")[1] if "'" in msg else None
        if not name:
            return None

        ed = editor(runner.h)
        info = ed.snapshot(proposal['path'])
        if info['snapshot_id'] != proposal['snapshot_id'] or info['source_hash'] != proposal['source_hash']:
            return None
        
        snap = ed._snapshots[info['snapshot_id']]
        
        # Build operations map from proposal edits
        # We need to find which node_ids from the proposal correspond to the duplicate
        # The requirement says: "For each distinct reported name try once."
        # We use the node_ids from proposal['edits'] to identify the context.
        
        cjs_path = pathlib.Path(__file__).with_name('candidate_duplicate_functions.cjs')
        
        # Prepare input for the JS deduplicator
        # We pass the edits from the proposal as the operations to deduplicate
        ops = []
        for edit in proposal['edits']:
            node_id = edit['node_id']
            code = edit['code']
            start, end = snap.ranges[node_id]
            ops.append({
                "node_id": node_id,
                "start": start,
                "end": end,
                "code": code,
                "is_insert": start == end
            })

        payload = json.dumps({"operations": ops, "name": name})
        
        proc = subprocess.run(
            [ed.service.node, '-e', 
             f"const fs=require('fs'),ts=require(require('os').homedir()+'/.local/share/mlx-server/code-intelligence/node_modules/typescript'),{{deduplicate}}=require(process.argv[1]);const v=JSON.parse(fs.readFileSync(0,'utf8'));console.log(JSON.stringify(deduplicate(ts,v.operations,v.name)));",
             str(cjs_path)],
            input=payload,
            capture_output=True,
            text=True,
            timeout=10
        )

        if proc.returncode != 0:
            return None

        changes = json.loads(proc.stdout)
        if not changes:
            return None

        # Validation: max 1 changed, nonempty code, differs from prior, 
        # IDs from insertion ops only, exact keys/strs.
        if len(changes) > 1:
            return None
        
        change = changes[0]
        if not change.get('code') or change['code'] == "":
            return None
        
        # Check if change is valid via revise (pure validation)
        updated = revise(proposal, changes, [])
        if not updated:
            return None
        ed.apply(proposal['path'], proposal['snapshot_id'], updated['edits'])

        # Final verification of the logic: 
        # The tool call must reflect the removal of the duplicate.
        runner.h.log_event('autonomy.strategy', {
            'reason': 'identical_duplicate_function',
            'path': proposal['path'],
            'binding': name,
            'node_ids': [c['node_id'] for c in changes],
            'model_calls': 0
        })

        return {
            'content': 'Removed identical duplicate function from inserted statements',
            'tool_calls': [{
                'id': f'candidate-deduplicate-{runner.used}',
                'function': {
                    'name': 'repair_ast_candidate',
                    'arguments': json.dumps({'changes': changes, 'remove': []})
                }
            }]
        }

    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception:
        return None
