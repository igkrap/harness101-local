import json
from pathlib import Path
import shutil
import subprocess
import uuid

from gemma_tool_output import recover_call, recover_calls


def _schemas(tools):
    result = {}
    for tool in tools:
        function = tool.get('function', {}) if isinstance(tool, dict) else {}
        name, schema = function.get('name'), function.get('parameters')
        if not isinstance(name, str) or not name or name in result or not isinstance(schema, dict):
            raise ValueError('Invalid offered tool definition')
        result[name] = schema
    if not result:
        raise ValueError('No offered tools for provider recovery')
    return result


def _validate_call(call, schema):
    validator = Path(__file__).resolve().parent.parent / 'local-only/harness/tool_schema_validator.cjs'
    node = shutil.which('node')
    if not node or not validator.is_file():
        raise ValueError('Tool argument validator is unavailable')
    checked = subprocess.run([node, str(validator)], input=json.dumps({'schema': schema, 'arguments': call['arguments']}),
                             text=True, capture_output=True, timeout=10)
    result = json.loads(checked.stdout)
    if checked.returncode != 0 or result.get('valid') is not True or result.get('internal_error'):
        raise ValueError('Recovered ' + call['name'] + ' arguments failed schema validation: '
                         + json.dumps(result.get('errors', result.get('internal_error')), ensure_ascii=False)[:1800])


def recover_empty(reply, model, tools=None):
    choices = reply.get('choices') or []
    if not choices:
        return reply
    choice = choices[0]
    message = choice.get('message') or {}
    if any(message.get(key) for key in ('content', 'tool_calls', 'reasoning', 'reasoning_content', 'refusal')):
        return reply
    ids = []
    try:
        ids = [item.get('id') for item in (choice.get('logprobs') or {}).get('content', [])]
        if not ids:
            raise ValueError('Server omitted generated token IDs')
        if len(ids) > 12288 or any(type(i) is not int or i < 0 for i in ids):
            raise ValueError('Invalid generated token IDs')
        cache = Path.home() / '.cache/huggingface/hub' / ('models--' + model.replace('/', '--'))
        reference = cache / 'refs/main'
        if reference.is_file():
            tokenizer = cache / 'snapshots' / reference.read_text().strip() / 'tokenizer.json'
        else:
            candidates = list((cache / 'snapshots').glob('*/tokenizer.json'))
            if len(candidates) != 1:
                raise ValueError('Cannot identify the exact local tokenizer')
            tokenizer = candidates[0]
        python = Path.home() / '.local/share/mlx-server/venv/bin/python'
        process = subprocess.run([str(python), str(Path(__file__).with_name('mlx_token_decode.py'))],
                                 input=json.dumps({'tokenizer': str(tokenizer), 'ids': ids}),
                                 text=True, capture_output=True, timeout=30, check=True)
        raw = json.loads(process.stdout)['text']
        schemas = _schemas(tools) if tools is not None else None
        if schemas is None or set(schemas) == {'replace_ast_fragments'}:
            call, repaired = recover_call(raw)
            calls = [call]
        else:
            calls, repaired = recover_calls(raw, set(schemas)), False
        if schemas is not None:
            for call in calls:
                _validate_call(call, schemas[call['name']])
        choice['message'] = {'role': 'assistant', 'tool_calls': [{'type': 'function', 'id': 'recovered-' + uuid.uuid4().hex,
            'function': {'name': call['name'], 'arguments': json.dumps(call['arguments'], ensure_ascii=False)}} for call in calls]}
        choice['finish_reason'] = 'tool_calls'
        reply['provider_recovery'] = {'recovered': True, 'generated_tokens': len(ids), 'outer_brace_completed': repaired,
                                      'tool_names': [call['name'] for call in calls]}
    except (ValueError, TypeError, KeyError, OSError, subprocess.SubprocessError) as exc:
        reason = 'Provider tool output could not be decoded: ' + str(exc)
        choice['message'] = {'role': 'assistant', 'content': reason, '_provider_error': reason}
        reply['provider_recovery'] = {'recovered': False, 'generated_tokens': len(ids), 'error': str(exc)}
    return reply
