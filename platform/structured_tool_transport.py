"""Preserve Gemma tool tokens and require a sole focused repair action."""
import json
from urllib.parse import urlparse


def _gemma4(payload):
    return 'gemma4' in str(payload.get('model', '')).lower().replace('-', '').replace('_', '')


def require_fragment_tool(request):
    if urlparse(request.full_url).hostname not in ('127.0.0.1', 'localhost') or not request.data:
        return False
    payload = json.loads(request.data)
    tools = payload.get('tools') or []
    if len(tools) != 1:
        return False
    name = tools[0].get('function', {}).get('name')
    if name not in ('replace_ast_fragments', 'repair_new_file'):
        return False
    payload['tool_choice'] = {'type': 'function', 'function': {'name': name}}
    if _gemma4(payload):
        payload['logprobs'] = True
    request.data = json.dumps(payload, ensure_ascii=False).encode('utf-8')
    return True


def capture_gemma_tools(request):
    if urlparse(request.full_url).hostname not in ('127.0.0.1', 'localhost') or not request.data:
        return None
    payload = json.loads(request.data)
    if not payload.get('tools') or not _gemma4(payload):
        return None
    payload['logprobs'] = True
    # MLX emits the chosen token's ID in this mode, rather than the top candidate.
    payload['top_logprobs'] = 0
    request.data = json.dumps(payload, ensure_ascii=False).encode('utf-8')
    return payload


def install():
    import model_transport
    original = model_transport.complete
    if getattr(original, '_requires_fragment_tool', False):
        return

    def complete(request, timeout):
        require_fragment_tool(request)
        payload = capture_gemma_tools(request)
        reply = original(request, timeout)
        if payload is not None:
            from provider_output_recovery import recover_empty
            return recover_empty(reply, payload['model'], payload['tools'])
        return reply

    complete._requires_fragment_tool = True
    model_transport.complete = complete
