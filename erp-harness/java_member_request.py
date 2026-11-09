import json
import hashlib
import re
from pathlib import Path

def focused(runner, messages, ask):
    if not (messages is runner.messages and 'backend' in runner.modes and not getattr(runner.cp, 'pending', False)):
        return None

    gate = runner.requirement_gate
    contract = None
    criteria = []

    selected_func = getattr(gate, 'selected', None)
    if callable(selected_func):
        criteria = selected_func()
        own_ids = gate.stage['criterion_ids']
        criteria = [c for c in criteria if c.get('id') in own_ids]
        contract = gate.contract
    else:
        frozen = getattr(gate, 'frozen_contract', None)
        if isinstance(frozen, str):
            contract = json.loads(frozen)
            criteria = contract['criteria']
        else:
            return None

    criteria = [c for c in criteria if c.get('check', {}).get('op') == 'junit_added']
    if not criteria:
        return None
    suites = {c['check']['suite'] for c in criteria}
    if len(suites) > 1:
        return None
    criterion = max(criteria, key=lambda c: c['check']['count'])
    check = criterion['check']
    op = check['op']

    suite = check['suite']
    count = check['count']
    rel = f"backend/src/test/java/{suite.replace('.', '/')}.java"
    path = runner.h.workspace.safe_path(rel)

    if not path.is_file() or path.stat().st_size > 32000:
        return None

    source = path.read_text(encoding='utf-8')
    runner.read.add(rel)

    basegate = getattr(gate, 'parent_gate', gate)
    baseline = getattr(basegate, '_junit_baseline', {})
    original_executed = baseline.get('suites', {}).get(suite, {}).get('executed')
    target_total = (original_executed + count) if isinstance(original_executed, int) else None

    source_bytes = source.encode('utf-8')
    current_hash = hashlib.sha256(source_bytes).hexdigest()
    
    prev_code = ""
    if getattr(runner, '_java_member_hash', None) == current_hash:
        prev_code = getattr(runner, '_java_member_code', '')

    system_msg = f"{contract['task']}\nInstruction: ONLY NEW Java METHODDECLARATIONS inside ONE java fence, no imports/classwrapper/oldmethods/toolJSON; JDK AST chooses correct class position and native Maven/old assertion guards remain."
    user_msg = (f"Criterion: {json.dumps(criterion)}\nBaseline: {json.dumps(baseline.get('suites', {}).get(suite, {}))}\n"
                f"Target Total: {target_total}\nSource:\n{source}\nFeedback: {runner.feedback}\n"
                f"Error: {getattr(runner, '_java_member_error', '')}\nPrior Failed Code: {prev_code}")

    reply = ask([{'role': 'system', 'content': system_msg}, {'role': 'user', 'content': user_msg}], [])
    content = reply.get('content', '').strip()

    if not content:
        setattr(runner, '_java_member_error', 'Empty reply')
        return {'content': 'Java member response invalid: empty', 'tool_calls': []}
    if len(content) > 12000:
        setattr(runner, '_java_member_error', 'Reply too long')
        return {'content': 'Java member response invalid: length error', 'tool_calls': []}

    match = re.fullmatch('```java\\s*(.*?)\\s*```', content, re.DOTALL) or re.fullmatch('```\\s*(.*?)\\s*```', content, re.DOTALL)
    if match:
        code = match.group(1)
    elif content.startswith('```'):
        runner._java_member_error = 'Invalid format: multiple or non-java fences detected.'
        return {'content': f'Java member response invalid: {runner._java_member_error}', 'tool_calls': []}
    else:
        code = content

    # Validate code is not just prose after the fence
    if not code.strip() and content.strip() != "":
         setattr(runner, '_java_member_error', 'Empty code block')
         return {'content': 'Java member response invalid: empty code', 'tool_calls': []}

    setattr(runner, '_java_member_hash', current_hash)
    setattr(runner, '_java_member_code', code)
    setattr(runner, '_java_member_error', None)

    return {
        'content': '',
        'tool_calls': [{
            'id': f'java-members-{runner.used}',
            'type': 'function',
            'function': {
                'name': 'add_java_methods',
                'arguments': json.dumps({'path': rel, 'class_name': path.stem, 'code': code}, ensure_ascii=False)
            }
        }]
    }
