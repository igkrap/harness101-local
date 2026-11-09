import hashlib
from pathlib import Path
from typing import Any, Dict

def guard(child: Any, stage: Dict[str, Any], name: str, inputs: Dict[str, Any]) -> None:
    """
    Production guard for mutation tools to ensure filesystem safety and 
    prevent unauthorized scope escapes or redundant AST inspections.
    """
    if name == 'update_seed_rows' and stage.get('domain') != 'backend':
        raise ValueError('Seed changes belong to a backend stage')
    root: Path = child.h.workspace.root
    log_event = child.h.log_event
    if not hasattr(child, '_division_inspections'):
        child._division_inspections = {}
    mutation_tools = {'write_file', 'edit_file', 'delete_file', 'apply_ast_edits', 'apply_edits', 'apply_insertions', 'insert_text', 'add_java_annotations', 'isolate_spring_test'}
    action = inputs.get('action')
    input_path_raw = inputs.get('path') or inputs.get('input_path')
    if name in mutation_tools and input_path_raw:
        target_path = child.h.workspace.safe_path(input_path_raw)
        try:
            rel_path_obj = target_path.relative_to(root)
            rel_path_posix = rel_path_obj.as_posix()
        except ValueError:
            raise ValueError(f"Stage: {stage.get('id')} | Path: {input_path_raw} | Allowed Scope: Within workspace root.")
        domain = stage.get('domain', '')
        if domain == 'frontend':
            if not rel_path_posix.startswith('frontend/src/'):
                raise ValueError(f"Stage: {stage.get('id')} | Path: {rel_path_posix} | Allowed Scope: frontend/src/")
        elif domain == 'backend':
            if not rel_path_posix.startswith('backend/src/'):
                raise ValueError(f"Stage: {stage.get('id')} | Path: {rel_path_posix} | Allowed Scope: backend/src/")
        if rel_path_posix not in stage.get('paths', []):
            log_event('autonomy.stage_scope_extended', {'path': rel_path_posix, 'stage_id': stage.get('id')})
    if name == 'inspect_code' and action == 'edit_ranges' and input_path_raw:
        target_path = child.h.workspace.safe_path(input_path_raw)
        try:
            file_bytes = target_path.read_bytes()
            source_hash = hashlib.sha256(file_bytes).hexdigest()
        except Exception as e:
            return
        stage_id = stage.get('id', 'unknown')
        rel_path_str = str(target_path.relative_to(root))
        inspection_key = (rel_path_str, action, source_hash)
        if not hasattr(child, '_division_ast_paths'):
            child._division_ast_paths = []
        if not hasattr(child, '_division_ast_focus'):
            child._division_ast_focus = False
        if inspection_key not in child._division_inspections:
            child._division_inspections[inspection_key] = 0
        child._division_inspections[inspection_key] += 1
        count = child._division_inspections[inspection_key]
        if rel_path_str not in child._division_ast_paths:
            child._division_ast_paths.insert(0, rel_path_str)
            child._division_ast_paths = child._division_ast_paths[:2]
        if count > 2:
            if not child._division_ast_focus:
                child._division_ast_focus = True
                log_event('autonomy.strategy', {'stage_id': stage_id, 'path': rel_path_str, 'reason': 'Repeated unchanged AST reads; cached scopes retained; next turn uses edit tools'})
            return
    return None
