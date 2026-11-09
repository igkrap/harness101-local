import pathlib
import re
from installed_type_records import declarations
from installed_module_evidence import missing_module_evidence

def enrich(root: str, output: str) -> str:
    root_path = pathlib.Path(root).resolve()
    lines = output.splitlines()
    parsed_errors = []
    
    # 1. Parse errors with continuation lines
    i = 0
    while i < len(lines):
        line = lines[i]
        if ': error TS' in line:
            try:
                prefix, tail = line.split(': error TS', 1)
                filename_part, coords = prefix.rsplit('(', 1)
                row_str, col_str = coords.rstrip(')').split(',', 1)
                row, col = int(row_str), int(col_str)
                err_code, msg = tail.split(':', 1)
                
                full_msg = msg.strip()
                # Capture up to 6 following indented diagnostic continuation lines
                continuation_idx = 1
                while continuation_idx < 7 and (i + continuation_idx) < len(lines):
                    next_line = lines[i + continuation_idx]
                    # Check if next line is indented and not a new error header
                    if next_line.startswith((' ', '\t')) and ': error TS' not in next_line:
                        full_msg += f"\n{next_line.strip()}"
                        continuation_idx += 1
                    else:
                        break
                
                parsed_errors.append({
                    'orig': line, 
                    'file': filename_part, 
                    'row': row, 
                    'code': err_code.strip(), 
                    'msg': full_msg
                })
                i += continuation_idx
            except (ValueError, IndexError):
                i += 1
        else:
            i += 1

    if not parsed_errors:
        return ''

    # 2. Extract identifiers with strict word boundaries and priority
    found_ids_raw = []
    exclude = {'Type', 'Types', 'Property', 'Cannot', 'The', 'No', 'Argument', 'Expression', 'Did', 'Is', 'Not'}
    
    # Regex: Word boundary on both sides to avoid partial matches like 'Key' from 'idKey'
    id_pattern = re.compile(r'\b[A-Z][A-Za-z0-9_]*\b')

    for e in parsed_errors[:3]:
        ids = id_pattern.findall(e['msg'])
        for identifier in ids:
            if identifier not in exclude:
                found_ids_raw.append(identifier)

    def get_priority(name: str) -> int:
        if name.endswith(('Type', 'Name')): return 0
        if name.endswith('Props'): return 1
        return 2

    # Deduplicate while preserving order, then sort by priority
    unique_ids = []
    for idx in found_ids_raw:
        if idx not in unique_ids:
            unique_ids.append(idx)
    
    sorted_ids = sorted(unique_ids, key=get_priority)
    ids_list = sorted_ids[:6]

    # 3. Build Output
    error_strs = []
    context_parts = []
    
    # Limit to first 3 distinct error headers for budget
    seen_orig = set()
    for e in parsed_errors:
        if e['orig'] in seen_orig:
            continue
        if len(error_strs) >= 3:
            break
        seen_orig.add(e['orig'])
        error_strs.append(f"{e['orig']}\n{e['msg']}")

        # Context retrieval
        p = pathlib.Path(e['file'])
        candidates = []
        if p.is_absolute():
            candidates.append(p)
        elif str(p).startswith('frontend/'):
            candidates.append(root_path / p)
        else:
            candidates.append(root_path / 'frontend' / p)
            
        valid_file = None
        for c in candidates:
            try:
                res = c.resolve()
                if res.is_relative_to(root_path) and res.is_file():
                    valid_file = res
                    break
            except (ValueError, OSError):
                continue
        
        if valid_file:
            try:
                src_lines = valid_file.read_text().splitlines()
                idx = e['row'] - 1
                start, end = max(0, idx - 2), min(len(src_lines), idx + 3)
                snippet = "\n".join(f"{i+1}: {src_lines[i]}" for i in range(start, end))
                context_parts.append(f"--- {valid_file} ---\n{snippet}")
            except OSError:
                continue

    inst_decls = declarations(root_path, ids_list)
    decl_strs = [f"{d}" for d in inst_decls]

    # Ordering: error diagnostics+instruction, then INSTALLED API, then context
    res = "\n".join(error_strs)
    res += missing_module_evidence(root_path, output)
    res += "\nUse the actual installed declarations below; do not replace one guessed value with another. Preserve unrelated code and use current AST scopes after rollback."
    
    res += "\n\nInstalled API declarations:\n"
    res += "\n".join(decl_strs) if decl_strs else "No matching declarations found."
    
    if context_parts:
        res += "\n\nCANDIDATE SOURCE CONTEXT:\n" + "\n".join(context_parts)
    
    return res[:4900]
