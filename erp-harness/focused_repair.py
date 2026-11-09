import json
import re
import hashlib
from new_file_repair_tool import TOOL, parse_response

def final_json(content):
    """Use the model's final complete JSON block, never join separate drafts."""
    from divide_plan import duplicate_hook
    if not isinstance(content, str) or not content.strip():
        raise ValueError('Empty repair response')
    fences = list(re.finditer(r'^[ \t]*```([^\r\n`]*)\r?\n?', content, re.MULTILINE))
    drafts = 0
    if fences:
        if len(fences) % 2:
            raise ValueError('Unclosed final JSON fence; return a complete JSON object')
        opening, closing = fences[-2:]
        if opening.group(1).strip().lower() not in ('', 'json') or closing.group(1).strip():
            raise ValueError('Final fenced block must contain JSON')
        if content[closing.end():].strip():
            raise ValueError('Text follows final JSON block; return JSON only')
        payload = content[opening.end():closing.start()]
        drafts = len(fences) // 2
    else:
        payload = content.strip()
    return json.loads(payload, object_pairs_hook=duplicate_hook), drafts

def repair_diagnostic(runner, record):
    error = record['error']
    root = getattr(runner.h.workspace, 'root', None)
    if root is None or not record['path'].endswith(('.ts', '.tsx')):
        return error[:2500]
    # Fetch whole declarations separately: slicing enriched compiler text can
    # otherwise cut precisely the union member/property needed for repair.
    diagnostic = error.split('Use the actual installed declarations', 1)[0]
    excluded = {'Type', 'Types', 'Property', 'Cannot', 'The', 'No', 'Argument', 'Expression', 'Did', 'Is', 'Not', 'TypeScript', 'ESLint'}
    names = list(dict.fromkeys(name for name in re.findall(r'\b[A-Z][A-Za-z0-9_]*\b', diagnostic)
                              if name not in excluded and not re.fullmatch(r'TS\d+', name)))[:6]
    from installed_type_records import declarations
    records = declarations(root, names, source=record['path'], source_text=record['source'])
    selected, size = [], 0
    for item in records:
        if size + len(item) + 1 <= 4000:
            selected.append(item)
            size += len(item) + 1
    if not any(item.startswith(('Project declaration ', 'Installed declaration ')) for item in selected):
        return error[:2500]
    return diagnostic[:1200] + '\nActual source declarations:\n' + '\n'.join(selected)

def candidate_error_context(record):
    """Point to actual rejected source lines for both ESLint and tsc errors."""
    path = record['path']
    spellings = [path]
    if path.startswith('frontend/'):
        spellings.append(path[len('frontend/'):])
    pattern = '(?:' + '|'.join(re.escape(value) for value in spellings) + r')[:(](\d+)[,:]\d+'
    lines = record['source'].splitlines()
    locations = list(dict.fromkeys(int(match.group(1)) for match in re.finditer(pattern, record['error'])))[:3]
    indices = sorted({index for line in locations for index in range(max(0, line - 3), min(len(lines), line + 2))})
    output, size = [], 0
    for index in indices:
        line = f'{index + 1}: {lines[index]}'
        if size + len(line) + 1 > 1800:
            break
        output.append(line)
        size += len(line) + 1
    return '\n'.join(output)

def repair_new(runner, record):
    path, source, error = record["path"], record["source"], record["error"]
    if runner.h.workspace.safe_path(path).exists():
        raise ValueError(f"Target path {path} already exists")

    sys_msg = ('Fix the reported compiler, runtime, or screen-module contract error in the supplied rejected NEW file. Preserve functionality/API/meta and unrelated source. Screen modules must export their own const meta with a title and a default component; importing meta is insufficient. Call repair_new_file exactly once with exact old_text/new_text fragments. Each edit is a separate object in the edits array. Copy old_text exactly from the supplied source without line numbers. Preserve surrounding JSX braces and syntax. No prose or JSON draft outside the tool call.')
    if len(source) > 12000:
        raise ValueError("Source exceeds 12000")
    prompt = f"File: {path}\nError: {repair_diagnostic(runner, record)}"
    excerpt = candidate_error_context(record)
    if excerpt:
        prompt += '\nActual rejected source around reported errors (line numbers are not source text):\n' + excerpt
    prompt += f"\nSource:\n{source}"
    if record.get('repair_error'):
        prompt += (f"\nPrevious repair response was rejected: {record['repair_error'][:1200]}"
                   f"\nNo edits were applied. Repair the ORIGINAL source above using one repair_new_file call."
                   f"\nPrevious response (tail):\n{record.get('repair_reply', '')[-4000:]}")
    
    resp = runner.ask([{"role": "system", "content": sys_msg}, {"role": "user", "content": prompt}], tools=[TOOL])
    content = json.dumps(resp, ensure_ascii=False) if resp.get('tool_calls') else (resp.get('content') or '')
    record['repair_reply'] = content[-6000:]
    data, drafts, response_format = parse_response(resp, legacy_parser=final_json)
    
    if not isinstance(data, dict) or set(data) != {'edits'}:
        raise ValueError("Invalid JSON shape")
    
    edits = data["edits"]
    if not isinstance(edits, list):
        raise ValueError("Edits must be a list")
    if not (1 <= len(edits) <= 8):
        raise ValueError("Edits count must be 1..8")

    corrected = source
    for edit in edits:
        if not isinstance(edit, dict) or set(edit) != {'old_text', 'new_text'}:
            raise ValueError("Edit must contain only old_text and new_text")
        old, new = edit.get("old_text"), edit.get("new_text")
        if not isinstance(old, str) or not old or not isinstance(new, str):
            raise ValueError("Invalid edit strings")
        if len(old) > 3000 or len(new) > 3000:
            raise ValueError("Edit size exceeds limit")
        
        count = corrected.count(old)
        if count != 1:
            raise ValueError(f"Old text must occur exactly once: {old[:20]}")
        if old == new:
            raise ValueError("Edit must change content")
            
        corrected = corrected.replace(old, new, 1)

    if len(corrected) > 14000:
        raise ValueError("Resulting source exceeds max length")

    if hasattr(runner.h, 'log_event'):
        runner.h.log_event('autonomy.focused_repair', {
            'path': path, 'fenced_drafts': drafts, 'edits': len(edits),
            'response_format': response_format,
            'response_sha256': hashlib.sha256(content.encode()).hexdigest(),
            'source_sha256': hashlib.sha256(source.encode()).hexdigest(),
            'candidate_sha256': hashlib.sha256(corrected.encode()).hexdigest(),
        })

    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [{
            "id": f"repair-{runner.used}",
            "type": "function",
            "function": {
                "name": "write_file",
                "arguments": json.dumps({"path": path, "content": corrected}, ensure_ascii=False)
            }
        }]
    }
