def compact_candidate_changes(data, catalog, proposal):
    catalog_map = {node['id']: node['source'] for node in catalog}
    retained_map = {p['node_id']: p['code'] for p in proposal['edits']}
    
    new_changes = {}
    new_removals = []

    for change in data['changes']:
        cid, cval = change['node_id'], change['code']
        if cid not in catalog_map:
            raise ValueError(f"Unknown catalog id: {cid}")
        
        current_source = catalog_map[cid]
        retained_code = retained_map.get(cid)

        if retained_code is not None:
            if cval == retained_code:
                continue
            if cval == current_source:
                raise ValueError(f"Use REMOVE {cid} to restore a retained operation")
            new_changes[cid] = cval
        else:
            if cval == current_source:
                continue
            new_changes[cid] = cval

    for rid in data.get('remove', []):
        if rid not in catalog_map:
            raise ValueError(f"Unknown catalog id: {rid}")
        new_removals.append(rid)

    if not new_changes and not new_removals:
        raise ValueError("No actual repair changes")

    return {'changes': [{'node_id': cid, 'code': cval} for cid, cval in new_changes.items()], 'remove': new_removals}
