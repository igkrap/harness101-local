"""A bounded tool protocol for exact edits to a rejected new-file candidate."""
import json


TOOL = {
    'type': 'function',
    'function': {
        'name': 'repair_new_file',
        'description': (
            'Repair the supplied rejected NEW file with exact substring replacements. '
            'Every old_text must appear exactly once in the supplied candidate. '
            'Return only changed fragments; preserve all other source. '
            'Empty new_text deletes an unused fragment. No paths or whole-file content.'
        ),
        'parameters': {
            'type': 'object', 'required': ['edits'], 'additionalProperties': False,
            'properties': {
                'edits': {
                    'type': 'array', 'minItems': 1, 'maxItems': 8,
                    'items': {
                        'type': 'object', 'required': ['old_text', 'new_text'],
                        'additionalProperties': False,
                        'properties': {
                            'old_text': {'type': 'string', 'minLength': 1, 'maxLength': 3000},
                            'new_text': {'type': 'string', 'maxLength': 3000},
                        },
                    },
                },
            },
        },
    },
}


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate repair argument key: ' + key)
        result[key] = value
    return result


def _invalid_constant(value):
    raise ValueError('Invalid JSON constant in repair arguments: ' + value)


def validate_edits(data):
    if not isinstance(data, dict) or set(data) != {'edits'}:
        raise ValueError('Repair arguments must contain only edits')
    edits = data['edits']
    if not isinstance(edits, list) or not 1 <= len(edits) <= 8:
        raise ValueError('Repair edits count must be 1..8')
    for edit in edits:
        if not isinstance(edit, dict) or set(edit) != {'old_text', 'new_text'}:
            raise ValueError('Each repair edit must contain only old_text and new_text')
        old, new = edit['old_text'], edit['new_text']
        if not isinstance(old, str) or not 1 <= len(old) <= 3000:
            raise ValueError('Repair old_text must be a nonempty string of at most 3000 characters')
        if not isinstance(new, str) or len(new) > 3000:
            raise ValueError('Repair new_text must be a string of at most 3000 characters')
        if old == new:
            raise ValueError('Repair edit must change content')
    return data


def parse_response(response, legacy_parser=None):
    """Never combine tool arguments with prose or fall back from a malformed call.

    Returns (arguments, fenced_draft_count, response_format). Exact matching and
    applying the replacements remain the caller's responsibility.
    """
    if not isinstance(response, dict):
        raise ValueError('Repair response must be an object')
    if response.get('_provider_error'):
        raise ValueError(str(response['_provider_error']))
    calls = response.get('tool_calls')
    if calls is None:
        calls = []
    if not isinstance(calls, list):
        raise ValueError('Repair tool_calls must be a list')
    content = response.get('content')
    if content is not None and not isinstance(content, str):
        raise ValueError('Repair content must be text or null')
    if calls:
        if len(calls) != 1:
            raise ValueError('Return exactly one repair_new_file call')
        if content and content.strip():
            raise ValueError('Do not mix repair tool arguments with prose or another JSON draft')
        call = calls[0]
        if not isinstance(call, dict) or call.get('type', 'function') != 'function':
            raise ValueError('Repair must be a function tool call')
        function = call.get('function')
        if (not isinstance(function, dict) or set(function) != {'name', 'arguments'}
                or function['name'] != 'repair_new_file'):
            raise ValueError('Only the offered repair_new_file function is accepted')
        arguments = function['arguments']
        if not isinstance(arguments, str) or len(arguments) > 500000:
            raise ValueError('Repair arguments must be a bounded JSON string')
        data = json.loads(arguments, object_pairs_hook=_unique_pairs, parse_constant=_invalid_constant)
        return validate_edits(data), 0, 'tool'
    if legacy_parser is None:
        raise ValueError('Call repair_new_file with edits; a prose response is not a repair')
    data, drafts = legacy_parser(content)
    return validate_edits(data), drafts, 'legacy-json'
