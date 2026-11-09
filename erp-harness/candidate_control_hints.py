def retained_control_hint(retained):
    if not retained:
        return "none"
    ids = [r['node_id'] for r in retained]
    return f"{','.join(ids)}. DROP_EDIT only cancels a retained operation not current AST source; only listed IDs may be dropped; for current source modifications use EDIT node or parent."

def unknown_removal_error(node_id, valid_ids):
    sorted_ids = sorted(list(valid_ids))
    return f"Cannot remove unknown node: {node_id}. {','.join(sorted_ids)}. DROP_EDIT only cancels a retained operation not current AST source; only listed IDs may be dropped; for current source modifications use EDIT node or parent."
