import re

def parse_patches(text: str) -> list[dict[str, str]]:
    if not text.strip():
        raise ValueError("Empty input")
    
    lines = text.splitlines(keepends=True)
    cursor = 0
    patches = []

    def consume_fence(tag: str) -> str:
        nonlocal cursor
        expected = f"```{tag}"
        # Skip whitespace/blanklines before fence
        while cursor < len(lines) and lines[cursor].strip() == "":
            cursor += 1
        
        if cursor >= len(lines) or lines[cursor].strip() != expected:
            raise ValueError(f"Expected fence {expected}")
        
        cursor += 1
        content_lines = []
        found_closing = False
        while cursor < len(lines):
            line = lines[cursor]
            if line.strip() == "```":
                found_closing = True
                cursor += 1
                break
            content_lines.append(line)
            cursor += 1
        
        if not found_closing:
            raise ValueError(f"Unclosed fence {tag}")
        
        content = "".join(content_lines)
        # Remove ONLY the final separator newline if it exists
        if content.endswith('\n'):
            content = content[:-1]
            if content.endswith('\r'):
                content = content[:-1]
        return content

    while cursor < len(lines):
        # Skip blank lines before header
        if lines[cursor].strip() == "":
            cursor += 1
            continue
            
        header = lines[cursor].strip()
        match = re.fullmatch(r"PATCH\s+([A-Za-z0-9_-]+)(?:\s+line\s+\d+)?", header)
        if not match:
            raise ValueError(f"Invalid header: {header}")
        
        node_id = match.group(1)
        cursor += 1
        
        old_text = consume_fence("old")
        new_text = consume_fence("new")
        
        if old_text == new_text:
            continue
        if len(old_text) > 3000 or len(new_text) > 3000:
            raise ValueError("Patch content exceeds 3000 chars")
            
        patches.append({
            'node_id': node_id,
            'old_text': old_text,
            'new_text': new_text
        })
        
        if len(patches) > 8:
            raise ValueError("Too many patches")

    # Validate total text length and unconsumed prose
    full_content = "".join(p['old_text'] + p['new_text'] for p in patches)
    # The prompt implies total text constraint on the input or the sum? 
    # "totaltext<=24000" usually refers to the input string length.
    if len(text) > 24000:
        raise ValueError("Total text exceeds 24000 chars")

    # Check if we consumed everything (ignoring trailing whitespace)
    remaining = "".join(lines[cursor:]).strip()
    if remaining:
        raise ValueError(f"Unconsumed prose: {remaining}")

    if not patches:
        raise ValueError('No actual patch changes')
    return patches
