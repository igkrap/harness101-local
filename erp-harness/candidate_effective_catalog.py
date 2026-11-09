def effective_catalog(catalog, proposal, ranges):
    """
    Returns a new catalog list based on proposal edits and byte ranges.
    Implements exact conflict logic to prevent stale overlapping nodes.
    """
    retained_edits = {e['node_id']: e['code'] for e in proposal.get('edits', [])}
    retained_ids = set(retained_edits.keys())
    edit_ranges = []
    for eid in retained_ids:
        if eid in ranges:
            edit_ranges.append(ranges[eid])

    def is_conflicting(start, end):
        for (s_start, s_end) in edit_ranges:
            if start == s_start or (start < s_end and s_start < end) or (start == end and s_start <= start <= s_end) or (s_start == s_end and start <= s_start <= end):
                return True
        return False
    new_catalog = []
    for item in catalog:
        node_id = item['id']
        if node_id in retained_ids:
            new_item = dict(item)
            new_item['source'] = retained_edits[node_id]
            new_catalog.append(new_item)
        elif node_id in ranges:
            (r_start, r_end) = ranges[node_id]
            if not is_conflicting(r_start, r_end):
                new_catalog.append(dict(item))
        else:
            new_catalog.append(dict(item))
    return new_catalog
