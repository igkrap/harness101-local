from candidate_blocks import parse_blocks
import re


def select_final_edit_blocks(text: str) -> str:
    """Returns the last contiguous group of valid edit blocks."""
    if len(text) > 100000:
        raise ValueError("Input exceeds max length")

    lines = text.splitlines(keepends=True)
    last_valid_group = ""
    
    # We look for contiguous groups separated by blank lines.
    # A group is valid if parse_blocks succeeds.
    # We scan the whole text to find the LAST such group.
    
    current_group_lines = []
    in_group = False
    
    i = 0
    while i < len(lines):
        line = lines[i]
        # Check if line is a header
        is_header = re.match(r'^(EDIT|REMOVE|DROP_EDIT)\s+[A-Za-z0-9_-]+(?:\s+line\s+\d+)?$', line.strip())
        if re.match(r'^(EDIT|REMOVE|DROP_EDIT)\s', line.strip()) and not is_header: raise ValueError('Invalid edit header')
        
        if is_header:
            # Start of a potential group
            group_buffer = []
            j = i
            # Collect contiguous non-blank lines (or lines belonging to an EDIT fence)
            while j < len(lines):
                curr = lines[j]
                h_match = re.match(r'^(EDIT|REMOVE|DROP_EDIT)\s+[A-Za-z0-9_-]+(?:\s+line\s+\d+)?$', curr.strip())
                if h_match:
                    group_buffer.append(curr)
                    kind = h_match.group(1)
                    j += 1
                    if kind == 'EDIT':
                        while j < len(lines) and not lines[j].strip():
                            group_buffer.append(lines[j])
                            j += 1
                        if j < len(lines) and re.match(r'^```(tsx|ts|jsx|js|javascript|empty)\s*$', lines[j].strip()):
                            group_buffer.append(lines[j])
                            j += 1
                            found_end = False
                            while j < len(lines):
                                group_buffer.append(lines[j])
                                if lines[j].strip().startswith('```'):
                                    found_end = True
                                    j += 1
                                    break
                                j += 1
                            if not found_end: raise ValueError()
                        else: raise ValueError()
                    else:
                        pass
                elif not lines[j].strip():
                    group_buffer.append(lines[j])
                    j += 1
                else:
                    break
            
            if group_buffer:
                group_str = "".join(group_buffer)
                parse_blocks(group_str)
                last_valid_group = group_str
                i = j
                continue
        elif line.strip().startswith('```'):
            i += 1
            while i < len(lines) and lines[i].strip() != '```': i += 1
        i += 1

    if not last_valid_group:
        raise ValueError("No valid edit group found")
        
    # Check for trailing prose in the last group context
    # The requirement says "Return LAST contiguous group... Trailing prose allowed"
    # This implies we find the group, then if there's prose immediately after, 
    # we might need to include it? No, "Return LAST contiguous group... Trailing prose allowed, still last complete group selected."
    # This means the group itself is the target.
    
    return last_valid_group
