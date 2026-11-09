from ast_editing import editor
from jsx_style_edits import build_styles

def normalize_response(data, files, runner):
    """
    Normalizes response data into edits or style updates.
    Returns tuple(data, target_file, validation_nodes).
    """
    if not isinstance(data, dict) or set(data) not in ({'path','edits'},{'path','style_updates'}):
        raise ValueError()
    target_file = next((f for f in files if f['path'] == data['path']), None)
    if not target_file:
        raise ValueError("No matching file found in files list for provided data path.")

    path = target_file['path']
    snap_id = target_file['snap_id']
    catalog = target_file['catalog']

    if 'edits' in data:
        # Raw edits mode
        validation_nodes = catalog
        return data, target_file, validation_nodes

    if 'style_updates' in data:
        # Style updates mode
        updates = data['style_updates']
        if not isinstance(updates, list) or not (1 <= len(updates) <= 8):
            raise ValueError("style_updates must contain between 1 and 8 entries.")

        catalog_ids = {node['id'] for node in catalog}
        for entry in updates:
            if not isinstance(entry, dict) or set(entry.keys()) != {'node_id', 'styles'}:
                raise ValueError("Each style update must have exact keys: 'node_id', 'styles'.")
            if not isinstance(entry['node_id'], str) or entry['node_id'] not in catalog_ids:
                raise ValueError(f"node_id '{entry['node_id']}' not found in catalog.")

        # Build operations
        operations = build_styles(runner, path, snap_id, updates)
        
        # Create new data dict to avoid mutating input
        new_data = data.copy()
        new_data['edits'] = operations

        # Validate against fresh snapshot
        snap = editor(runner.h).snapshot(path)
        if snap['snapshot_id'] != snap_id:
            raise ValueError("Snapshot ID mismatch during validation.")
        
        validation_nodes = snap['nodes']
        return new_data, target_file, validation_nodes

    raise ValueError("Data must contain either 'edits' or 'style_updates' keys.")
