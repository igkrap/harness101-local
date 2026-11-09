"""Read Gemma's literal tool format without changing any source string values."""
import json
import re


DELIMITER = '<|"|>'


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate tool argument key: ' + key)
        result[key] = value
    return result


def recover_call(raw):
    text = raw.strip()
    endings = ('<turn|>', '<eos>', '<|tool_response>', '<tool_call|>')
    while any(text.endswith(end) for end in endings):
        end = next(end for end in endings if text.endswith(end))
        text = text[:-len(end)].rstrip()
    if not text.startswith('<|tool_call>'):
        raise ValueError('No explicit Gemma tool call marker')
    text = text[len('<|tool_call>'):]
    match = re.match(r'call:([\w-]+)(\{)', text)
    if not match or match.group(1) != 'replace_ast_fragments':
        raise ValueError('Unexpected tool function')
    body = text[match.start(2):]
    if '\x00' in body:
        raise ValueError('Unexpected NUL in tool arguments')
    stack, gemma_string, json_string, escape, closed = [], False, False, False, False
    i = 0
    while i < len(body):
        if not json_string and body.startswith(DELIMITER, i):
            gemma_string = not gemma_string
            i += len(DELIMITER)
            continue
        char = body[i]
        if gemma_string:
            i += 1
            continue
        if json_string:
            if escape:
                escape = False
            elif char == '\\':
                escape = True
            elif char == '"':
                json_string = False
        elif closed and not char.isspace():
            raise ValueError('Trailing or multiple tool calls')
        elif char == '"':
            json_string = True
        elif char in '{[':
            stack.append(char)
        elif char in '}]':
            if not stack or stack.pop() != ('{' if char == '}' else '['):
                raise ValueError('Mismatched tool argument brackets')
            closed = not stack
        i += 1
    if gemma_string or json_string:
        raise ValueError('Truncated tool source string; source completion is prohibited')
    repaired = False
    if stack == ['{'] and body.rstrip().endswith(']'):
        body += '}'
        repaired = True
    elif stack:
        raise ValueError('Truncated inner tool arguments')

    strings = []
    def capture(value):
        strings.append(value)
        return '\x00' + str(len(strings) - 1) + '\x00'

    body = re.sub(re.escape(DELIMITER) + '(.*?)' + re.escape(DELIMITER), lambda m: capture(m.group(1)), body, flags=re.S)
    body = re.sub(r'"(?:\\.|[^"\\])*"', lambda m: capture(json.loads(m.group(0))), body)
    body = re.sub(r'(?<=[{,])(\s*)([A-Za-z_]\w*)\s*:', r'\1"\2":', body)
    for index, value in enumerate(strings):
        body = body.replace('\x00' + str(index) + '\x00', json.dumps(value, ensure_ascii=False))
    args = json.loads(body, object_pairs_hook=_pairs)
    if not isinstance(args, dict):
        raise ValueError('Tool arguments must be an object')
    return {'name': match.group(1), 'arguments': args}, repaired


def _argument_end(text, start):
    """Locate a complete object; quoted source is opaque to bracket scanning."""
    stack, index = [], start
    while index < len(text):
        if text.startswith(DELIMITER, index):
            end = text.find(DELIMITER, index + len(DELIMITER))
            if end == -1:
                raise ValueError('Truncated tool source string; source completion is prohibited')
            index = end + len(DELIMITER)
            continue
        char = text[index]
        if char == '"':
            try:
                _, length = json.JSONDecoder().raw_decode(text[index:])
            except ValueError as exc:
                raise ValueError('Invalid or truncated JSON tool string') from exc
            index += length
            continue
        if char in '{[':
            stack.append(char)
        elif char in '}]':
            if not stack or stack.pop() != ('{' if char == '}' else '['):
                raise ValueError('Mismatched tool argument brackets')
            if not stack:
                return index + 1
        index += 1
    raise ValueError('Truncated tool arguments; missing brackets are not completed')


def _literal_arguments(body):
    """Quote structural keys while copying every string value without rewriting it."""
    chunks, outside, index = [], [], 0

    def flush():
        chunks.append(re.sub(r'(?<=[{,])(\s*)([A-Za-z_]\w*)\s*:', r'\1"\2":', ''.join(outside)))
        outside.clear()

    while index < len(body):
        if body.startswith(DELIMITER, index):
            flush()
            end = body.find(DELIMITER, index + len(DELIMITER))
            if end == -1:
                raise ValueError('Truncated tool source string')
            chunks.append(json.dumps(body[index + len(DELIMITER):end], ensure_ascii=False))
            index = end + len(DELIMITER)
        elif body[index] == '"':
            flush()
            _, length = json.JSONDecoder().raw_decode(body[index:])
            chunks.append(body[index:index + length])
            index += length
        else:
            outside.append(body[index])
            index += 1
    flush()

    def reject_constant(value):
        raise ValueError('Non-JSON tool argument constant: ' + value)

    arguments = json.loads(''.join(chunks), object_pairs_hook=_pairs, parse_constant=reject_constant)
    if not isinstance(arguments, dict):
        raise ValueError('Tool arguments must be an object')
    return arguments


def recover_calls(raw, allowed_names):
    """Read complete, explicit calls to offered tools; never complete missing arguments."""
    if not isinstance(raw, str) or len(raw) > 500000 or '\x00' in raw:
        raise ValueError('Invalid literal tool output')
    text = raw.strip()
    endings = ('<turn|>', '<eos>', '<|tool_response>', '<tool_call|>')
    while any(text.endswith(end) for end in endings):
        end = next(end for end in endings if text.endswith(end))
        text = text[:-len(end)].rstrip()
    if not text.startswith('<|tool_call>'):
        raise ValueError('No explicit Gemma tool call marker')
    text = text[len('<|tool_call>'):].lstrip()
    calls = []
    while text:
        match = re.match(r'call:([A-Za-z_][\w-]*)\s*(\{)', text)
        if not match or match.group(1) not in allowed_names:
            raise ValueError('Unexpected or unoffered tool function')
        end = _argument_end(text, match.start(2))
        calls.append({'name': match.group(1), 'arguments': _literal_arguments(text[match.start(2):end])})
        if len(calls) > 16:
            raise ValueError('Too many recovered tool calls')
        text = text[end:].lstrip()
        if text.startswith('<tool_call|>'):
            text = text[len('<tool_call|>'):].lstrip()
        if text.startswith('<|tool_call>'):
            text = text[len('<|tool_call>'):].lstrip()
            if not text:
                raise ValueError('Empty trailing tool call')
        if text and not text.startswith('call:'):
            raise ValueError('Trailing non-tool text')
    if not calls:
        raise ValueError('No complete tool calls')
    return calls
