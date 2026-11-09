import json, re
from pathlib import Path
from ast_editing import editor
from candidate_positions import utf16_column_bytes

def faulty_candidate_nodes(runner, proposal, feedback):
    try:
        ed = editor(runner.h)
        info = ed.snapshot(proposal['path'])
        sid = info['snapshot_id']
        if sid != proposal['snapshot_id']: return []
        snap = ed._snapshots[sid]
        edits = proposal.get('edits', [])
        if not edits: return []
        
        marker = "AST_EDIT_FEEDBACK"
        target_ids = []
        if marker in feedback:
            idx = feedback.find(marker) + len(marker)
            obj, _ = json.JSONDecoder().raw_decode(feedback[idx:].lstrip())
            nid = obj.get('node_id')
            if any(e['node_id'] == nid for e in edits): return [nid]
        else:
            target_ids = [e['node_id'] for e in edits]

        expected_res = ed.apply(proposal['path'], sid, edits)['new_text'].encode('utf8')
        
        ops = []
        for e in edits:
            nid = e['node_id']
            start, end = snap.ranges[nid]
            repl = e['code'].encode('utf8')
            if start == end: repl = b'\n' + repl + b'\n'
            ops.append((start, end, repl, nid))
        ops.sort()

        reconstructed = bytearray()
        last_pos = 0
        for start, end, repl, nid in ops:
            reconstructed.extend(snap.raw_bytes[last_pos:start])
            reconstructed.extend(repl)
            last_pos = end
        reconstructed.extend(snap.raw_bytes[last_pos:])
        
        if bytes(reconstructed) != expected_res: return []

        current_delta = 0
        new_spans = {}
        for start, end, repl, nid in ops:
            ns = start + current_delta
            ne = ns + len(repl)
            new_spans[nid] = (ns, ne)
            current_delta += (len(repl) - (end - start))

        results = []
        pattern = re.compile(r'(?:\[.*?\]\s*)?([^(\n]+)\((\d+),(\d+)\):\s*error\s+TS\d+')
        for match in pattern.finditer(feedback):
            fname, row, col = match.groups()
            row, col = int(row), int(col)
            try:
                p_raw = Path(fname)
                root = runner.h.workspace.root
                target = snap.path.resolve()
                p = None
                if p_raw.is_absolute():
                    p = p_raw.resolve()
                else:
                    opt1 = (root / fname).resolve()
                    if opt1 == target: p = opt1
                    else:
                        opt2 = (root / "frontend" / fname).resolve()
                        if opt2 == target: p = opt2
                
                if p != target: continue
                
                lines = expected_res.decode('utf8').splitlines(keepends=True)
                if not (1 <= row <= len(lines)): continue
                line = lines[row-1]
                if not (1 <= col <= len(line.encode('utf-8')) + 1): continue
                
                line_start_offset = sum(len(l.encode('utf-8')) for l in lines[:row-1])
                total_offset = line_start_offset + utf16_column_bytes(line, col)
                
                for nid in target_ids:
                    ns, ne = new_spans[nid]
                    if ns <= total_offset < ne:
                        results.append(nid)
                        break
            except Exception: continue
        return list(dict.fromkeys(results))
    except Exception:
        return []
