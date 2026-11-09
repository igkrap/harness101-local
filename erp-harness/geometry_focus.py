import json

def measured_height_failure(context):
    try:
        ctx = json.loads(context)
        if not isinstance(ctx, dict): return False
        checks = ctx.get('unresolved_checks', [])
        if not isinstance(checks, list): return False
        reqs = ["actual_height=", "allowed_height_min=", "allowed_height_max="]
        return any(isinstance(c, dict) and all(r in c.get('reason', '') for r in reqs) for c in checks)
    except (json.JSONDecodeError, TypeError, AttributeError):
        return False

def geometry_prompt(runner, files, context):
    try:
        from ast_editing import editor
        ctx = json.loads(context)
        if not isinstance(ctx, dict): raise ValueError
        checks = ctx.get('unresolved_checks', [])
        if not isinstance(checks, list): return None
        reason = next((c.get('reason', '') for c in checks if isinstance(c, dict) and all(x in c.get('reason', '') for x in ["actual_height=", "allowed_height_min=", "allowed_height_max="])), "")
        if not reason: return None
    except (ValueError, TypeError):
        return None

    entries = []
    candidates = files
    if getattr(runner, '_geometry_attempts', 0) >= 1:
        parents = [f for f in files if f['path'].endswith('/src/App.tsx')]
        if parents: candidates = parents
    for f in candidates:
        ed = editor(runner.h)
        info = ed.snapshot(f['path'])
        if info['snapshot_id'] != f['snap_id']:
            return None
        snap = ed._snapshots[f['snap_id']]
        
        for node_ref in f.get('catalog', []):
            try:
                actual = snap.nodes[node_ref['id']]
                ref_src = ""
                if actual.kind == 'JsxElement':
                    start = snap.ranges[actual.id][0]
                    counterpart = next((n for n in snap.nodes.values() 
                                      if n.kind == 'JsxOpeningElement' 
                                      and snap.ranges[n.id][0] == start), None)
                    if not counterpart or not actual.source.startswith(counterpart.source):
                        continue
                    ref_src = counterpart.source
                elif actual.kind in ('JsxSelfClosingElement', 'JsxOpeningElement'):
                    ref_src = actual.source
                else:
                    continue

                if len(ref_src) > 2000:
                    continue
                
                start, end = snap.ranges[actual.id]
                ancestors = [n for n in snap.nodes.values() if n.kind=='JsxElement' and n.id!=actual.id and snap.ranges[n.id][0]<start and snap.ranges[n.id][1]>=end]
                parent = min(ancestors, key=lambda n: snap.ranges[n.id][1]-snap.ranges[n.id][0], default=None)
                entries.append({
                    "path": f['path'],
                    "node_id": actual.id,
                    "label": actual.label,
                    "attributes_reference": ref_src,
                    "parent_node_id": parent.id if parent else None,
                    "depth": len(ancestors),
                    "source_order": start
                })
            except KeyError:
                continue

    entries.sort(key=lambda x: (x['path'], x.pop('source_order')))
    if not entries:
        return None

    sys_msg = ( 
        'Return a JSON object with exact keys path and style_updates. style_updates is 1..8 objects with node_id and styles (CSS property names -> strings/numbers/null). ' 
        'Use only catalog path and exact node_id; never testid. Read current attributes_reference. DO NOT propose existing same values or merely change numeric types. ' 
        'Every proposed property must differ and address native measured failure. The grid and outer screen percentage height do not work until ALL shared intermediate flex-column containers have bounded available height. ' 
        'Find content wrapper and active tab screen wrapper among App catalog nodes; adjust their flex/minHeight/height constraints while preserving display condition, padding and behavior. ' 
        'Root viewport height should remain bounded. Read last_error and change failed proposal. No JSX copies or code edits. Keep parent scope selection, actual failure criteria, all other code unchanged. ' 
        'Catalog is an actual JSX tree in source order. Follow parent_node_id from active screen wrapper through content wrapper to bounded viewport root. Fix the missing bounded intermediate container; reapplying leaf flex/height cannot repair an auto-height parent. Preserve sidebar branch and conditional display.'
    )
    
    user_payload = {
        "task": ctx.get('original_task', runner.args.task),
        "context": {'unresolved_checks': ctx.get('unresolved_checks', [])},
        "catalog": entries,
        "last_error": str(getattr(runner, '_ast_recovery_error', ''))[:3500],
        "attempt": getattr(runner, '_geometry_attempts', 0)
    }
    user_str = json.dumps(user_payload)
    
    if len(user_str) > 25000:
        return None
        
    return sys_msg, user_str
