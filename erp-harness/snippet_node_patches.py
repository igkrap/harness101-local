def patch_nodes(proposal, catalog, patches):
    """
    Applies patches to a catalog of nodes, incorporating retained edits from a proposal.
    """
    base = {c['id']: c['source'] for c in catalog}
    retained = {e['node_id']: e['code'] for e in proposal['edits']}
    
    # Merge original + retained baseline
    working = {**base, **retained}
    touched = []

    for p in patches:
        node_id = p['node_id']
        old = p['old_text']
        new = p['new_text']

        if node_id not in working:
            raise ValueError(f"Unknown node_id: {node_id}")
        
        # Ensure anchor exists exactly once to prevent ambiguity
        if not old:
            if not (working[node_id] == '' and next((c.get('kind') for c in catalog if c['id']==node_id), None) == 'insert'):
                raise ValueError('Empty anchor requires an empty AST insertion slot')
        elif working[node_id].count(old) != 1:
            raise ValueError(f"Ambiguous or missing anchor in node {node_id}")

        working[node_id] = working[node_id].replace(old, new, 1)
        if node_id not in touched:
            touched.append(node_id)

    changes = []
    remove = []

    for nid in touched:
        res = working[nid]
        
        if res.strip() == "":
            if nid in retained and base.get(nid) == '':
                remove.append(nid)
            else:
                changes.append({'node_id': nid, 'code': ''})
        else:
            if len(res) > 12000:
                raise ValueError(f"Resulting code exceeds length limit for node {nid}")
            
            # Compare against the merged baseline (original or retained)
            # If the patch resulted in no actual change to the baseline, skip it
            baseline_val = retained.get(nid, base.get(nid, ""))
            if res != baseline_val:
                changes.append({'node_id': nid, 'code': res})

    if not changes and not remove:
        raise ValueError('No actual repair changes')
    return {'changes': changes, 'remove': remove}
