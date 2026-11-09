import re

def leaf_scope(catalog, snapshot, keep_ids=()):
    """
    Prunes a catalog of AST nodes to keep only the most specific JSX elements 
    containing specific test-id assignments, while preserving requested IDs.
    """
    nodes = getattr(snapshot, "nodes", {})
    ranges = getattr(snapshot, "ranges", {})
    
    # Regex to find data-testid assignments in source
    testid_re = re.compile(r'data-testid\s*=\s*["\']([^"\']+)["\']')
    
    # 1. Identify "Named Full Elements": JsxElements that contain a test-id in their source
    named_full_nodes = []
    for entry in catalog:
        eid = entry["id"]
        if eid not in nodes or nodes[eid].kind != "JsxElement":
            continue
        
        rng = ranges.get(eid)
        if not rng:
            continue
            
        start, end = rng
        actual = nodes[eid]
        # Find opening element that contains this node's start
        found_opener = None
        for oid, info_node in nodes.items():
            if info_node.kind in ('JsxOpeningElement', 'JsxSelfClosingElement'):
                o_start, o_end = ranges[oid]
                if o_start <= start < o_end:
                    # Check if actual.source is a descendant (prefix check)
                    if actual.source.startswith(info_node.source):
                        # Verify the opener itself has the testid
                        if testid_re.search(info_node.source):
                            found_opener = oid
                            break
        if found_opener:
            named_full_nodes.append(entry)

    if not named_full_nodes and not keep_ids:
        return list(catalog)

    # 2. Determine which nodes to prune
    # A node is pruned if it is a JsxElement, NOT in keep_ids, 
    # and strictly encloses a different named FULL element.
    keep_set = set(keep_ids)
    pruned_ids = set()
    
    # Map named full nodes for easy range comparison
    full_node_ranges = []
    for fn in named_full_nodes:
        r = ranges.get(fn["id"])
        if r:
            full_node_ranges.append((fn["id"], r[0], r[1]))

    for entry in catalog:
        eid = entry["id"]
        if eid in keep_set:
            continue
            
        rng = ranges.get(eid)
        if not rng or getattr(nodes.get(eid), "kind", None) != "JsxElement":
            continue
            
        e_start, e_end = rng
        
        # Check if this node strictly encloses any different named full element
        for fn_id, f_start, f_end in full_node_ranges:
            if fn_id == eid:
                continue
            # Strict enclosure: start <= child_start AND child_end <= end
            # AND the ranges are not identical (different ranges)
            if e_start <= f_start and f_end <= e_end:
                if (e_start, e_end) != (f_start, f_end):
                    pruned_ids.add(eid)
                    break

    # 3. Build result
    result = []
    for entry in catalog:
        if entry["id"] not in pruned_ids:
            result.append(entry)
            
    return result
