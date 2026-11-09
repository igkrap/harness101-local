import os
import glob
import xml.etree.ElementTree as ET

def root_failure(root, output, started):
    patterns = os.path.join(root, "backend/target/surefire-reports/TEST-*.xml")
    files = []
    for f in glob.glob(patterns):
        try:
            mtime = os.path.getmtime(f)
            if mtime >= started - 2:
                files.append(f)
        except OSError:
            continue

    collected = []
    skip_patterns = ["ApplicationContext", "contextCustomizers"]
    target_keys = [
        "Caused by", "SQL State", "Error Code", "Message :", 
        "Location :", "Statement :", "ERROR: relation", 
        "syntax error", "duplicate key", "expected: or but was:"
    ]

    for f in files:
        try:
            tree = ET.parse(f)
            root_el = tree.getroot()
            elements = root_el.findall('.//failure') + root_el.findall('.//error')
            for el in elements:
                lines = []
                # Collect attributes and text
                for k, v in el.attrib.items():
                    lines.append(f"{k}: {v}")
                if el.text:
                    lines.extend(el.text.splitlines())
                
                # Filter and extract
                file_lines = []
                for line in lines:
                    line = line.strip()
                    if not line or any(s in line for s in skip_patterns):
                        continue
                    if any(tk in line for tk in target_keys):
                        file_lines.append(line)
                
                if file_lines:
                    collected.append(file_lines)
        except Exception:
            continue

    if not collected:
        return None

    # Deduplicate and sort logic
    # We need to find the "deepest" Caused by (last occurrence)
    # and sort it last, others by appearance.
    all_unique_lines = []
    seen = set()
    
    # Flatten and deduplicate while preserving order
    for group in collected:
        for line in group:
            if line not in seen:
                all_unique_lines.append(line)
                seen.add(line)

    # Find the last 'Caused by' index
    last_cb_idx = -1
    for i in range(len(all_unique_lines) - 1, -1, -1):
        if "Caused by" in all_unique_lines[i]:
            last_cb_idx = i
            break

    if last_cb_idx != -1:
        # Move last Caused by to the start
        target = all_unique_lines.pop(last_cb_idx)
        all_unique_lines.insert(0, target)

    res = "\n".join(all_unique_lines)[:3500]
    return res if res else None
