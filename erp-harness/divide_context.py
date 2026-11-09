import json
from pathlib import Path
from typing import Any, Dict, Set, Tuple

def snapshot(child, stage):
    root = child.h.workspace.root
    recent = list(getattr(child, '_division_ast_paths', []))[:2]
    targets = stage['paths'] + recent
    if stage.get('domain') == 'frontend':
        targets = targets + ['frontend/src/workspace.json']
    targets = targets + stage.get('references', [])
    targets = list(dict.fromkeys(targets))
    lines = []
    read = set()
    total = 0
    raw_total = 0
    ast_count = 0

    def emit(value):
        nonlocal total
        if total + len(value) + 1 <= 36000:
            lines.append(value)
            total += len(value) + 1
            return True
        return False
    for rel in targets:
        if len(read) >= 4:
            break
        parts = rel.split('/')
        valid_prefix = rel.startswith('frontend/src/') or rel.startswith('backend/src/')
        valid_parts = all((p and p not in ('.', '..') and ('\\' not in p) for p in parts))
        if not valid_prefix or not valid_parts:
            emit('SKIP invalid path: ' + rel)
            continue
        try:
            is_symlink = False
            for i in range(1, len(parts) + 1):
                if root.joinpath(*parts[:i]).is_symlink():
                    is_symlink = True
                    break
            if is_symlink:
                emit('SKIP symlink: ' + rel)
                continue
            target = root.joinpath(*parts)
            target.resolve().relative_to(root.resolve())
            if not target.is_file():
                emit('MISSING planned file: ' + rel)
                continue
            raw = target.read_text(encoding='utf-8')
            content = raw
            is_catalog = False
            if ast_count < 2 and rel.startswith('frontend/src/') and rel.endswith(('.tsx', '.ts')) and rel in (recent + stage['paths']):
                try:
                    from ast_editing import editor
                    data = json.dumps(editor(child.h).snapshot(rel), ensure_ascii=False)
                    if len(data) <= 32000:
                        content = data
                        is_catalog = True
                    else:
                        emit('AST too large: ' + rel)
                except Exception as e:
                    emit('AST error: ' + str(e)[:30])
            if not is_catalog and (len(raw) > 9000 or raw_total + len(raw) > 18000):
                emit('SIZE limit: ' + rel)
                continue
            if emit('--- ' + rel + ' ---\n' + content):
                read.add(rel)
                if is_catalog:
                    ast_count += 1
                else:
                    raw_total += len(raw)
        except Exception as e:
            emit('ERROR ' + rel + ': ' + str(e)[:180])
    return ('\n'.join(lines), read)

def packet(parent_gate: Any, accepted_paths: list[str], report: Dict[str, Any]) -> Dict[str, Any]:
    """
    Constructs the verified-evidence transport packet.
    """
    root = parent_gate.runner.h.workspace.root
    hashes = parent_gate._source_hashes(root)
    verified_results = []
    for res in report.get('results', []):
        item = {'id': res.get('id'), 'status': res.get('status'), 'reason': str(res.get('reason', ''))[:2000]}
        evidence = res.get('evidence')
        if isinstance(evidence, (dict, list)):
            ev_str = json.dumps(evidence)
            if len(ev_str) > 2000:
                item['evidence'] = {'truncated': True, 'preview': ev_str[:2000]}
            else:
                item['evidence'] = evidence
        else:
            item['evidence'] = evidence
        verified_results.append(item)
    return {'contract_hash': parent_gate.contract_hash, 'changed_paths': sorted(set(accepted_paths)), 'source_hashes': {rel: hashes[rel].hex() for rel in accepted_paths if rel in hashes}, 'verified_results': verified_results, 'transport': 'verified-evidence'}
