from candidate_field_protocol import normalize_field_fences
import re
from snippet_patch_parser import parse_patches

def parse_reply(text: str):
    """
    Normalizes patch formatting to ensure compatibility with the canonical parser.
    Converts bare NODEid headers into standard PATCH NODEid format.
    """
    text = normalize_field_fences(text)
    lines = text.splitlines(keepends=True)
    normalized = []
    in_fence = False
    wrapped = False
    first_nonblank = next((idx for (idx, line) in enumerate(lines) if line.strip()), None)
    fence_type = None
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if stripped == '```old':
            in_fence = True
            fence_type = 'old'
            normalized.append(line)
            i += 1
            continue
        elif stripped == '```new':
            in_fence = True
            fence_type = 'new'
            normalized.append(line)
            i += 1
            continue
        elif stripped == '```' and in_fence:
            in_fence = False
            fence_type = None
            normalized.append(line)
            i += 1
            continue
        if not in_fence:
            if stripped and (not stripped.startswith('```')):
                next_idx = i + 1
                while next_idx < len(lines) and (not lines[next_idx].strip()):
                    next_idx += 1
                while next_idx < len(lines) and lines[next_idx].strip() == 'PATCH:':
                    next_idx += 1
                    while next_idx < len(lines) and (not lines[next_idx].strip()):
                        next_idx += 1
                if next_idx < len(lines) and lines[next_idx].strip() == '```old':
                    tokens = re.findall('(?<![A-Za-z0-9_-])([ns][0-9]+)(?![A-Za-z0-9_-])', stripped)
                    distinct_tokens = set(tokens)
                    if len(distinct_tokens) == 1:
                        node_id = tokens[0]
                    else:
                        node_id = stripped.removeprefix('NODE ').strip()
                    if re.fullmatch('[A-Za-z0-9_-]+', node_id):
                        normalized.append(f'PATCH {node_id}\n')
                        i = next_idx
                        continue
            if stripped == '```patch':
                if i == first_nonblank:
                    wrapped = True
                    i += 1
                    continue
        normalized.append(line)
        i += 1
    fulltext = ''.join(normalized)
    try:
        return parse_patches(fulltext)
    except ValueError:
        last_non_blank_idx = -1
        for idx in range(len(normalized) - 1, -1, -1):
            if normalized[idx].strip():
                last_non_blank_idx = idx
                break
        if wrapped and last_non_blank_idx != -1 and (normalized[last_non_blank_idx].strip() == '```'):
            try:
                truncated_text = ''.join(normalized[:last_non_blank_idx])
                return parse_patches(truncated_text)
            except ValueError:
                raise ValueError('Failed to parse patches after normalization and fallback.')
        raise ValueError('Failed to parse patches after normalization.')
