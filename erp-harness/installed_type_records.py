import pathlib
import re
import json
import subprocess
import shutil

def declarations(root, aliases, source=None, source_text=None):
    from local_type_records import resolve, records
    root = pathlib.Path(root)
    local = resolve(root, aliases, source=source, source_text=source_text)
    local_records = records(local)
    package = root / 'frontend/node_modules/@astryxdesign/core/dist'
    helper = pathlib.Path(__file__).with_name('ast_outline.cjs')
    
    root = pathlib.Path(root)
    node = shutil.which('node')
    if not node:
        home = pathlib.Path.home()
        node = home / '.nvm/versions/node/v22.15.0/bin/node'
    
    if not package.exists() or not helper.exists() or not pathlib.Path(node).exists():
        return local_records

    target_names = []
    for a in aliases:
        if a in local.get('resolved', []) or a in local.get('ambiguous', []):
            continue
        if a not in target_names:
            target_names.append(a)
            if len(target_names) >= 6: break
            
    if 'IconName' in target_names and 'NamespacedIconName' not in target_names: target_names.append('NamespacedIconName')

    records = []
    matches_found = {}

    for name in target_names:
        pattern = re.compile(rf'^\s*(?:export\s+)?(?:type|interface|class)\s+{re.escape(name)}\b', re.MULTILINE)
        found_for_name = []
        
        for dts_file in package.rglob('*.d.ts'):
            try:
                text = dts_file.read_text(encoding='utf-8')
                if pattern.search(text):
                    try:
                        proc = subprocess.run(
                            [str(node), str(helper)],
                            input=json.dumps({'path': str(dts_file), 'source': text, 'symbol': name, 'compact': True}),
                            capture_output=True,
                            text=True,
                            timeout=10
                        )
                        if proc.returncode == 0:
                            data = json.loads(proc.stdout)
                            symbol = data.get('symbol', {})
                            if symbol.get('source') and not proc.stderr:
                                found_for_name.append((dts_file, symbol))
                    except (subprocess.TimeoutExpired, json.JSONDecodeError, KeyError):
                        continue
            except (OSError, UnicodeDecodeError):
                continue
        
        if len(found_for_name) == 1:
            matches_found[name] = found_for_name[0]
        elif len(found_for_name) > 1:
            first_src = found_for_name[0][1]['source']
            if all(f[1]['source'] == first_src for f in found_for_name):
                matches_found[name] = found_for_name[0]

    for name, (file_path, symbol) in matches_found.items():
        try:
            full_text = file_path.read_text(encoding='utf-8').splitlines()
            start_idx = symbol['start_line'] - 1
            
            jsdoc = ""
            search_idx = start_idx - 1
            while search_idx >= 0:
                line = full_text[search_idx].strip()
                if '*/' in line:
                    prefix = ""
                    for i in range(search_idx, -1, -1):
                        prefix = full_text[i] + "\n" + prefix
                        if '/**' in full_text[i]:
                            break
                    jsdoc = prefix.strip()
                    if jsdoc.endswith('*/'):
                        jsdoc = jsdoc[-700:]
                    break
                if line and not line.startswith(('*', '//')):
                    break
                search_idx -= 1

            source_lines = full_text[start_idx:]
            source_content = ""
            current_line = 0
            for line in source_lines:
                source_content += line + "\n"
                current_line += 1
                if current_line > 100: break 
            
            source_snippet = symbol['source'][:1800].strip()
            record = f"Installed declaration {file_path}:{symbol['start_line']}\n{jsdoc}\n{source_snippet}".strip()
            records.append(record)
            if len(records) >= 4:
                break
        except Exception:
            continue
        if len(records) >= 4:
            break

    if not local_records:
        return records[:4]
    combined = list(local_records)
    used = sum(len(record) + 1 for record in combined)
    for record in records[:4]:
        if used + len(record) + 1 <= 4000:
            combined.append(record)
            used += len(record) + 1
    return combined
