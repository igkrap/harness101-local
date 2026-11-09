import json
import re
import subprocess
from pathlib import Path
from ast_editing import editor

def build_styles(runner, path, snapshot_id, updates):
    """Builds atomic JSX style edit operations using a CJS converter."""
    if not isinstance(updates, list) or not (1 <= len(updates) <= 8):
        raise ValueError("updates must be list length 1..8")
    
    ed = editor(runner.h)
    info = ed.snapshot(path)
    if info['snapshot_id'] != snapshot_id:
        raise ValueError(f"Stale snapshot: expected {snapshot_id}, got {info['snapshot_id']}")
    
    snap = ed._snapshots[snapshot_id]
    results = []
    seen_ids = set()
    any_changed = False

    for update in updates:
        if not isinstance(update, dict) or set(update.keys()) != {'node_id', 'styles'}:
            raise ValueError("update must have keys node_id, styles")
        node_id = update['node_id']
        styles = update['styles']
        if not isinstance(node_id, str) or not node_id:
            raise ValueError("node_id must be nonempty str")
        if node_id in seen_ids:
            raise ValueError(f"duplicate node_id: {node_id}")
        seen_ids.add(node_id)
        if not isinstance(styles, dict) or not (1 <= len(styles) <= 16):
            raise ValueError("styles must be dict length 1..16")

        node = snap.nodes.get(node_id)
        if not node or node.kind not in ('JsxElement', 'JsxSelfClosingElement', 'JsxOpeningElement'):
            raise ValueError(f"missing or unsupported node: {node_id}")

        converter_kind = node.kind
        converter_source = node.source
        target_id = node_id
        synthesized_tail = ""

        if node.kind == 'JsxElement':
            opening = next((n for n in snap.nodes.values() 
                           if n.kind == 'JsxOpeningElement' and snap.ranges[node_id][0] == snap.ranges[n.id][0]), None)
            if opening:
                if not node.source.startswith(opening.source):
                    raise ValueError(f"Source mismatch for JsxElement {node_id}")
                converter_kind = 'JsxElement'
                converter_source = node.source
                target_id = opening.id
                child_tail = node.source[len(opening.source):]
            else:
                converter_kind = 'JsxElement'
                converter_source = node.source
        elif node.kind == 'JsxOpeningElement':
            match = re.match(r'<([A-Za-z_$][A-Za-z0-9_$.:]*)', node.source)
            if not match:
                raise ValueError(f"missing tag regex match: {node_id}")
            tagname = match.group(1)
            synthesized_tail = f'</{tagname}>'
            converter_source = node.source + synthesized_tail
            converter_kind = 'JsxElement'
            target_id = node_id
        else:
            synthesized_tail = ""

        if len(converter_source) > 12000:
            raise ValueError(f"oversized converter source: {node_id}")

        proc = subprocess.run(
            [ed.service.node, str(Path(__file__).with_name('jsx_style_patch.cjs'))],
            input=json.dumps({'kind': converter_kind, 'source': converter_source, 'styles': styles}, ensure_ascii=False),
            capture_output=True, text=True, timeout=10
        )

        try:
            out = json.loads(proc.stdout)
        except json.JSONDecodeError:
            out = {'ok': False, 'error': proc.stderr or 'JSON decode error'}

        if proc.returncode != 0 or not out.get('ok'):
            raise ValueError(f"Converter failed for {node_id}: {out.get('error', proc.stderr)}")
        
        new_code = out['code']
        if not isinstance(new_code, str):
            raise ValueError(f"non-string code for {node_id}")

        if node.kind == 'JsxOpeningElement':
            if not new_code.endswith(synthesized_tail):
                raise ValueError(f"Synthesized tail missing for {node_id}")
            new_code = new_code[:-len(synthesized_tail)]
        elif node.kind == 'JsxElement' and target_id != node_id:
            child_tail = node.source[len(snap.nodes[target_id].source):]
            if not new_code.endswith(child_tail):
                raise ValueError(f"Child tail mismatch for {target_id}")
            new_code = new_code[:-len(child_tail)]

        if new_code == snap.nodes[target_id].source:
            continue
        if not new_code:
            raise ValueError(f"empty code for {target_id}")
        if len(new_code) > 12000:
            raise ValueError(f"oversized new code: {target_id}")
        if target_id in [r['node_id'] for r in results]:
            raise ValueError(f"duplicate output id: {target_id}")

        results.append({'node_id': target_id, 'code': new_code})
        any_changed = True

    if not any_changed:
        raise ValueError('No style source changes; change the failed geometry, not existing values.')
    return results
