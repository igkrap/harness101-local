def reference_fragments(catalog, active_catalog, proposal, limit=7000) -> str:
    """
    Identifies original source snippets for nodes that were modified or removed,
    providing read-only context for VariableStatements or specific form sources.
    """
    active_map = {item['id']: item for item in active_catalog}
    fragments = []
    current_size = 0
    seen_sources = set()

    # Identify candidates: missing from active OR source mismatch
    candidates = []
    for orig in catalog:
        node_id = orig['id']
        active_node = active_map.get(node_id)
        
        # Condition: Missing from active OR source has changed
        is_replaced = (not active_node) or (active_node.get('source') != orig.get('source'))
        
        if is_replaced:
            # Filter by kind or specific source pattern
            is_target_kind = orig.get('kind') == 'VariableStatement'
            is_form_source = str(orig.get('source', '')).lstrip().startswith('<form')
            
            if is_target_kind or is_form_source:
                candidates.append(orig)

    for orig in candidates:
        src = orig.get('source', '')
        if not src or src in seen_sources:
            continue
            
        # Prepare fragment
        header = f"READ-ONLY ORIGINAL BEHAVIOR (NOT an active edit target)\n```tsx\n"
        footer = "\n```"
        fragment = f"{header}{src}{footer}"
        frag_len = len(fragment) + (2 if fragments else 0)

        if current_size + frag_len <= limit:
            fragments.append(fragment)
            current_size += frag_len
            seen_sources.add(src)
        else:
            # Stop adding if next fragment exceeds limit to maintain stability
            continue

    return "\n\n".join(fragments)
