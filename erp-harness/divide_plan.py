import collections
import project_context
import json
import re
from pathlib import Path
from collections import deque, defaultdict

def duplicate_hook(pairs):
    d = {}
    for (k, v) in pairs:
        if k in d:
            raise ValueError(f'Duplicate key: {k}')
        d[k] = v
    return d

def validate(contract_dict: dict, raw_dict: dict, checks: list) -> list:
    if not isinstance(contract_dict, dict):
        raise ValueError('contract_dict must be dict')
    if not isinstance(raw_dict, dict):
        raise ValueError('raw_dict must be dict')
    'Validates the division plan against the contract and business rules.'
    stages = raw_dict.get('stages')
    if not isinstance(stages, list) or not 2 <= len(stages) <= 12:
        raise ValueError('stages must be a list of 2..12')
    contract_criteria = {c['id']: c for c in contract_dict.get('criteria', [])}
    all_assigned_ids = []
    stage_ids = []
    id_pattern = re.compile('^[a-z][a-z0-9_-]{0,31}$')
    for stage in stages:
        if not isinstance(stage, dict):
            raise ValueError('Stage must be an object')
        required = {'id', 'title', 'instructions', 'domain', 'criterion_ids', 'paths', 'depends_on'}
        if not required.issubset(stage.keys()):
            raise ValueError(f"Missing required fields in stage: {stage.get('id', 'unknown')}")
        s_id = stage['id']
        if not isinstance(s_id, str) or not id_pattern.match(s_id) or s_id == 'integration':
            raise ValueError(f'Invalid or reserved stage ID: {s_id}')
        if s_id in stage_ids:
            raise ValueError(f'Duplicate stage ID: {s_id}')
        stage_ids.append(s_id)
        if not isinstance(stage['title'], str) or not 0 < len(stage['title'].strip()) <= 200:
            raise ValueError(f'Invalid title in stage {s_id}')
        if not isinstance(stage['instructions'], str) or not 0 < len(stage['instructions'].strip()) <= 3000:
            raise ValueError(f'Invalid instructions in stage {s_id}')
        domain = stage['domain']
        if domain not in ('frontend', 'backend'):
            raise ValueError(f'Invalid domain: {domain}')
        if domain == 'backend' and 'backend' not in checks:
            raise ValueError('backend domain requested but not enabled in checks')
        if domain == 'frontend':
            if not ('frontend' in checks or 'framework' in checks):
                raise ValueError('frontend domain requested but not enabled in checks')
        c_ids = stage['criterion_ids']
        if not isinstance(c_ids, list) or not c_ids:
            raise ValueError(f'Stage {s_id} has empty criterion_ids; remove this stage entirely or assign existing required criteria of the correct domain; do not invent DB/API work for a layout-only request.')
        for cid in c_ids:
            if not isinstance(cid, str) or cid not in contract_criteria:
                raise ValueError(f'Unknown or invalid criterion ID: {cid}')
            if cid in all_assigned_ids:
                raise ValueError(f'Criterion {cid} assigned more than once')
            all_assigned_ids.append(cid)
        paths = stage['paths']
        if not isinstance(paths, list) or not 1 <= len(paths) <= 12:
            raise ValueError(f'paths must be list of 1..12 in {s_id}')
        for p in paths:
            if not isinstance(p, str) or not p:
                raise ValueError(f'Invalid path string in {s_id}')
            parts = p.split('/')
            if not all(parts) or '..' in parts or '.' in parts or ('\\' in p):
                raise ValueError(f"Path must be relative and not contain '..' or '.' or '\\' or absolute: {p}")
            if not (p.startswith('frontend/src/') or p.startswith('backend/src/')):
                raise ValueError(f'Path must start with frontend/src/ or backend/src/: {p}')
            if domain == 'backend' and (not p.startswith('backend/src/')):
                raise ValueError(f'Backend stage contains non-backend path: {p}')
            if domain == 'frontend' and (not p.startswith('frontend/src/')):
                raise ValueError(f'Frontend stage contains non-frontend path: {p}')
        refs = stage.get('references', [])
        if not isinstance(refs, list) or len(refs) > 12:
            raise ValueError(f'references must be list of 0..12 in {s_id}')
        for r in refs:
            if not isinstance(r, str) or not r:
                raise ValueError(f'Invalid path string in {s_id}')
            parts = r.split('/')
            if not all(parts) or '..' in parts or '.' in parts or ('\\' in r):
                raise ValueError(f"Path must be relative and not contain '..' or '.' or '\\' or absolute: {r}")
            if not (r.startswith('frontend/src/') or r.startswith('backend/src/')):
                raise ValueError(f'Path must start with frontend/src/ or backend/src/: {r}')
        deps = stage['depends_on']
        if not isinstance(deps, list):
            raise ValueError(f'depends_on must be list in {s_id}')
        if any((not isinstance(d, str) or not d for d in deps)) or len(deps) != len(set(deps)):
            raise ValueError(f'Duplicate dependencies in {s_id}')
        for d in deps:
            if d == s_id:
                raise ValueError(f'Self-dependency in {s_id}')
            if d not in stage_ids and d not in [s['id'] for s in stages]:
                pass
        for cid in c_ids:
            op = contract_criteria[cid]['check']['op']
            if op in ('api', 'junit_added') and domain != 'backend':
                raise ValueError(f'Criterion {cid} (api) requires backend domain')
            if op in ('layout', 'visible', 'text', 'scenario') and domain != 'frontend':
                raise ValueError(f'Criterion {cid} ({op}) requires frontend domain')
            if op == 'manual' and domain not in ('frontend', 'backend'):
                raise ValueError(f'Criterion {cid} (manual) invalid domain')
    if len(all_assigned_ids) != len(contract_criteria):
        raise ValueError('Not all criteria from contract are assigned exactly once')
    for d in [s['depends_on'] for s in stages]:
        for dep in d:
            if dep not in stage_ids:
                raise ValueError(f'Dependency {dep} not found in stages')
    in_degree = {s['id']: 0 for s in stages}
    graph = collections.defaultdict(list)
    for s in stages:
        for dep in s['depends_on']:
            graph[dep].append(s['id'])
            in_degree[s['id']] += 1
    idx_map = {s['id']: i for (i, s) in enumerate(stages)}
    sorted_list = []
    ready = [s['id'] for s in stages if in_degree[s['id']] == 0]
    while ready:
        ready.sort(key=lambda x: idx_map[x])
        u = ready.pop(0)
        sorted_list.append(u)
        for v in graph[u]:
            in_degree[v] -= 1
            if in_degree[v] == 0:
                ready.append(v)
    if len(sorted_list) != len(stages):
        raise ValueError('Cycle detected in dependencies')
    stage_map = {s['id']: s for s in stages}
    return [{**stage_map[sid], 'criterion_ids': list(stage_map[sid]['criterion_ids']), 'paths': list(stage_map[sid]['paths']), 'depends_on': list(stage_map[sid]['depends_on']), 'references': list(stage_map[sid].get('references', []))} for sid in sorted_list]

def create(runner):
    contract = json.loads(runner.requirement_gate.frozen_contract)
    files = project_context.project_files(runner.h.workspace.root)
    filtered_files = [f for f in files if f.startswith('frontend/src/') or f.startswith('backend/src/')][:200]
    allowed_domains = sorted(list(set(['backend' if c['check']['op'] in ('api', 'junit_added') else 'frontend' for c in contract.get('criteria', [])])))
    criterion_domains = {c['id']: 'backend' if c['check']['op'] in ('api', 'junit_added') else 'frontend' for c in contract.get('criteria', [])}
    planner_checks = [m for m in runner.modes if m in allowed_domains or (m == 'framework' and 'frontend' in allowed_domains)]
    messages = [{'role': 'system', 'content': f"JSON only. Divide into 2..12 independently verifiable feature slices. Assign each criterion exactly once. Stage keys id,title,instructions,domain(frontend/backend),criterion_ids(list),paths(list source paths),references(list),depends_on(list stage IDs). Use ONLY {allowed_domains}. Every stage needs at least one criterion. Remove unnecessary setup/database/API stages completely; never keep one with empty criterion_ids. Respect enabled checks: {planner_checks}. IDs must be lowercase letters/digits/underscores. Titles and instructions must use the user's language. When a request describes one composed screen, choose one primary existing screen file and evolve that same screen across the layout, query/grid, and editor stages. Do not scatter parts of one screen into unrelated tabs. Include previously modified shared layout files in references. Include dependencies. Final integration is added by harness, do not include it."}, {'role': 'user', 'content': json.dumps({'contract': contract, 'files': filtered_files, 'checks': planner_checks, 'allowed_domains': allowed_domains, 'criterion_domains': criterion_domains}, ensure_ascii=False)}]
    last_error = ''
    from component_catalog import context_for_task
    messages[-1]['content'] += context_for_task(runner)
    for _ in range(4):
        response = runner.ask(messages, tools=[])
        try:
            content = response['content'].strip()
            if content.startswith('```'):
                content = '\n'.join(content.splitlines()[1:-1])
            raw = json.loads(content, object_pairs_hook=duplicate_hook)
            if isinstance(raw, list): raw = {'stages': raw}
            stages = validate(contract, raw, runner.modes)
            folder = runner.requirement_gate.artifact_dir
            folder.mkdir(parents=True, exist_ok=True)
            (folder / 'division-plan.json').write_text(json.dumps({'source': 'divide-and-conquer', 'stages': stages, 'contract_hash': runner.requirement_gate.contract_hash}, ensure_ascii=False))
            runner.h.log_event('autonomy.plan', {'source': 'divide-and-conquer', 'steps': [dict(s, kind='change') for s in stages] + [{'id': 'integration', 'title': '전체 결과 검증', 'kind': 'verify'}]})
            return stages
        except (ValueError, TypeError, KeyError) as e:
            last_error = str(e)
            messages.append({'role': 'user', 'content': last_error})
            continue
    raise RuntimeError(f'Failed to generate plan after 4 attempts: {last_error}')
