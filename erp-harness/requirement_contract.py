import re
import json
import hashlib
import math

HTML_TAGS = set("""a abbr address area article aside audio b bdi bdo blockquote body br button canvas caption cite code col colgroup
data datalist dd del details dfn dialog div dl dt em embed fieldset figcaption figure footer form h1 h2 h3 h4 h5 h6 head header
hgroup hr html i iframe img input ins kbd label legend li link main map mark menu meta meter nav noscript object ol optgroup option
output p param picture pre progress q rp rt ruby s samp script search section select slot small source span strong style sub summary
sup table tbody td template textarea tfoot th thead time title tr track u ul var video wbr svg path g circle rect line polyline polygon""".split())


def requirements(task: str) -> list[dict]:
    if not task or not task.strip():
        raise ValueError('Empty task')
    clauses = [c.strip() for c in task.split('\n') if c.strip()]
    if not clauses:
        raise ValueError('No non-empty clauses')
    if len(clauses) > 32:
        raise ValueError('Too many clauses')
    return [{'id': f'R{i + 1}', 'description': c} for (i, c) in enumerate(clauses)]

def prompt(task: str) -> str:
    reqs = requirements(task)
    req_str = '\n'.join([f"- {r['id']}: {r['description']}" for r in reqs])
    dsl = """
DSL (JSON only):
- manual: {op: 'manual', reason: string} (blocks completion)
- visible: {op: 'visible', selector: CSS/Playwright}
- absent: {op: 'absent', selector: CSS/Playwright} (a control/region the request removes, e.g. a split resize handle; the selector must match the CURRENT screen before the change, otherwise the contract is rejected)
- text: {op: 'text', selector: CSS/Playwright, contains: string}
- layout: {op: 'layout', subject: CSS/Playwright, relation: 'left_of'|'right_of'|'above'|'below'|'wider_than'|'narrower_than', reference: CSS/Playwright, ratio?: number}
- scenario: {op: 'scenario', steps: [{action: 'click'|'fill'|'select'|'expect_visible'|'expect_hidden'|'expect_text'|'expect_value'|'remember_style'|'expect_same_style'|'expect_animated', selector: string, value?: string}]}
  expect_animated placed right after a click proves the element changes gradually (height or opacity passes through intermediate values for ~0.7 s) instead of jumping; the element must stay in the DOM while it animates.
  remember_style stores the computed look (colors, border, radius, font, padding, height) of one element under the name in value; expect_same_style checks another element looks the same as the remembered one (value = that name). Use them for 'same look as' requests, e.g. remember_style the existing button, act, then expect_same_style the new button.
  expect_hidden proves an element is NOT shown (collapsed, closed, toggled off). The same selector must also be proven visible by an expect_visible step in that scenario, e.g. click toggle -> expect_hidden panel -> click toggle -> expect_visible panel. Never use visible/expect_visible to mean hidden. Form inputs have no name attribute; address an input by its label inside its form exactly as listed in CURRENT SCREEN ELEMENTS, e.g. #form-id >> internal:label="규격"i. Never use :nth-of-type for inputs. Every scenario starts on the untouched screen in its default state: include the steps that reach the state you test first (e.g. collapse before checking an expand animation; open before testing a close). Verify behavior rather than guessed visual markers: e.g. a required field is proven by leaving it empty, saving, and expecting the validation message, not by an asterisk element. A toggle control usually changes its label or icon after a click (e.g. '접기' becomes '펼치기') and may move; for the second click select it by a state-independent attribute (data-ui, aria-controls, data-testid) or by the label it has after the first click, never by the first-state label alone.
- api: {op: 'api', method: 'GET'|'POST'|'PUT'|'PATCH'|'DELETE', path: '/path', status: 100-599, body?: JSON, json_path?: [str|int], equals?: JSON}

Read layout literally: SUBJECT is RELATION REFERENCE. Use below and right_of directly; no mental operand swapping is needed.
Example: footer below header => {"op":"layout","subject":"footer","relation":"below","reference":"header"}.
Example: sidebar right of article => {"op":"layout","subject":"aside","relation":"right_of","reference":"article"}.
For wider_than, subject.width > reference.width * ratio. For narrower_than, reference.width > subject.width * ratio. Ratio defaults to 1 and must be >= 1; it is NOT a percentage of total width.
Use actual CSS selectors: an element with data-testid="area" is [data-testid="area"], not the custom tag area. Selectors for requested new regions may be introduced by the implementation, but use one consistent selector per region across criteria.
Multiple criteria can express the same geometric fact for different requirement clauses. Do not introduce contradictory or unrelated ordering. Split compound requirements into measurable checks. Functional requests need controls and outcomes, not an empty container or body visible alone. Descriptions must be concise and in the user's language.
Successful API mutations require both json_path and equals. Expected 4xx responses may omit both. Every requirement must remain covered.
"""
    from junit_added_gate import DSL_GUIDE
    dsl += '\n' + DSL_GUIDE
    return f"Task: {task}\nRequirements:\n{req_str}\nProduce JSON {{'criteria': [...]}} only. Every requirement must map to >=1 criterion. Criteria: {{'id': 'C1', 'requirement_id': 'R1', 'description': '...', 'check': {{...}}}}. {dsl}"

def normalize_layout(check: dict) -> dict:
    """Compile literal spatial expressions to the existing executor, without inference."""
    check = dict(check)
    if 'subject' in check or 'reference' in check:
        if 'left' in check or 'right' in check:
            raise ValueError('Use subject/reference OR legacy left/right, never both')
        if 'subject' not in check or 'reference' not in check:
            raise ValueError('Layout requires both subject and reference')
        check['left'] = check.pop('subject')
        check['right'] = check.pop('reference')
    inverse = {'below': 'above', 'right_of': 'left_of', 'narrower_than': 'wider_than'}
    if check.get('relation') in inverse:
        check['relation'] = inverse[check['relation']]
        check['left'], check['right'] = check.get('right'), check.get('left')
    return check

def validate(task: str, raw: dict) -> dict:
    if not isinstance(raw, dict):
        raise ValueError('Raw must be dict')
    criteria = raw.get('criteria')
    if not isinstance(criteria, list) or not 1 <= len(criteria) <= 64:
        raise ValueError('Criteria must be list 1..64')
    reqs = requirements(task)
    req_ids = {r['id'] for r in reqs}
    covered_reqs = set()

    def check_type(val, t, name):
        if not isinstance(val, t):
            raise ValueError(f'{name} must be {t}')
        if t is str and (not val or len(val) > 2000):
            raise ValueError(f'{name} invalid')

    def check_sel(s):
        if not isinstance(s, str) or not s or len(s) > 500:
            raise ValueError('Invalid selector')
        # Type selectors must be real HTML elements (custom elements contain '-'); words like
        # 'required' or 'error' used as tags can never match and make the criterion unsatisfiable.
        for segment in re.split(r'>>', s):
            segment = segment.strip()
            if segment.startswith('internal:'):
                # internal:label="X"i resolves to the field itself; CSS written after it without ' >> '
                # becomes part of the label text and can never match.
                m = re.match(r'internal:[\w-]+=(?:"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\')[is]?', segment)
                if m and segment[m.end():].strip():
                    raise ValueError(f"Selector {s!r}: text after {m.group(0)} must be separated by ' >> ' (it targets the labeled field itself; "
                                     "e.g. check required with a scenario: leave it empty, save, expect the error).")
                continue
            if segment.startswith(('text=', 'xpath=', 'role=')):
                continue
            for tag in re.findall(r'(?:^|[\s>+~,(])([a-zA-Z][a-zA-Z0-9-]*)(?=[\s.#\[:>+~,)]|$)', re.sub(r'\[[^\]]*\]|\([^)]*\)|"[^"]*"|\'[^\']*\'', '', segment)):
                if '-' not in tag and tag.lower() not in HTML_TAGS:
                    raise ValueError(f"Unknown element <{tag}> in selector {s!r}; use real HTML tags or attributes (e.g. [aria-required='true']) instead.")
        return s
    valid_criteria = []
    hidden_claims = []
    for c in criteria:
        if not isinstance(c, dict):
            raise ValueError('Criterion must be dict')
        cid = c.get('id')
        rid = c.get('requirement_id')
        desc = c.get('description')
        check = c.get('check')
        if not isinstance(cid, str) or not cid or cid.startswith('system:') or (len(cid) > 2000):
            raise ValueError('Invalid ID')
        if cid in {x['id'] for x in valid_criteria}:
            raise ValueError('Duplicate ID')
        if not isinstance(rid, str) or rid not in req_ids:
            raise ValueError('Invalid requirement_id')
        if not isinstance(desc, str) or not desc or len(desc) > 2000:
            raise ValueError('Invalid description')
        if not isinstance(check, dict):
            raise ValueError('Check must be dict')
        if check.get('op') == 'layout':
            check = normalize_layout(check)
        op = check.get('op')
        if not isinstance(op, str):
            raise ValueError('Op must be string')
        allowed = {'manual': {'reason'}, 'visible': {'selector'}, 'absent': {'selector'}, 'text': {'selector', 'contains'}, 'layout': {'left', 'right', 'relation', 'ratio'}, 'scenario': {'steps'}, 'api': {'method', 'path', 'status', 'body', 'json_path', 'equals'}, 'junit_added': {'suite', 'count', 'preserve_main'}}
        if op not in allowed:
            raise ValueError(f'Unknown op: {op}')
        if 'page' in check and (op not in ('visible', 'absent', 'text', 'scenario') or check['page'] != 'login'):
            raise ValueError(f"check.page for cid {cid} may only be \"login\" (checks the sign-in page before logging in) on visible/absent/text/scenario")
        if set(check.keys()) - allowed[op] - {'op', 'page'}:
            raise ValueError(f"Extra keys in check for cid {cid}: {sorted(list(set(check.keys()) - allowed[op] - {'op'}))}; allowed keys: {sorted(list(allowed[op]))}")
        if op == 'manual':
            check_type(check.get('reason'), str, 'reason')
        elif op in ('visible', 'absent'):
            check_sel(check.get('selector'))
        elif op == 'text':
            check_sel(check.get('selector'))
            check_type(check.get('contains'), str, 'contains')
        elif op == 'layout':
            rel = check.get('relation')
            if rel not in ('left_of', 'above', 'wider_than'):
                raise ValueError('Invalid relation')
            check_sel(check.get('left'))
            check_sel(check.get('right'))
            if rel == 'wider_than':
                ratio = check.get('ratio', 1.0)
                if isinstance(ratio, bool) or not isinstance(ratio, (int, float)) or (not math.isfinite(ratio)) or (ratio < 1.0):
                    raise ValueError('wider_than ratio must be finite numeric >= 1.0 (LEFTWIDTH/RIGHTWIDTH)')
            elif 'ratio' in check:
                raise ValueError('Ratio only for wider_than')
        elif op == 'scenario':
            steps = check.get('steps')
            if not isinstance(steps, list) or not 1 <= len(steps) <= 20:
                raise ValueError('Steps 1..20')
            has_expect = False
            for s in steps:
                if not isinstance(s, dict):
                    raise ValueError('Step must be dict')
                for alias in ('contains', 'text', 'expected'):
                    # The text op names its expectation 'contains'; the same word in a step means 'value'.
                    if alias in s and 'value' not in s and s.get('action') in ('expect_text', 'expect_value'):
                        s['value'] = s.pop(alias)
                if set(s.keys()) - {'action', 'selector', 'value'}:
                    raise ValueError(f"Extra keys in scenario step for cid {cid}: {sorted(list(set(s.keys()) - {'action', 'selector', 'value'}))}; allowed keys: ['action', 'selector', 'value']; scenario is ONLY browser actions click/fill/select/expect_visible/expect_hidden/expect_text/expect_value/remember_style/expect_same_style/expect_animated and API requests must be separate criteria check.op=api with method,path,status,body,json_path,equals; multiple API criteria execute sequentially.")
                act = s.get('action')
                if act not in ('click', 'fill', 'select', 'expect_visible', 'expect_hidden', 'expect_text', 'expect_value', 'remember_style', 'expect_same_style', 'expect_animated'):
                    raise ValueError(f"Invalid action {act} for cid {cid}; scenario is ONLY browser actions click/fill/select/expect_visible/expect_hidden/expect_text/expect_value/remember_style/expect_same_style/expect_animated and API requests must be separate criteria check.op=api with method,path,status,body,json_path,equals; multiple API criteria execute sequentially.")
                if act in ('expect_visible', 'expect_hidden', 'expect_text', 'expect_value', 'expect_same_style', 'expect_animated'):
                    has_expect = True
                if act not in ('click', 'expect_visible', 'expect_hidden', 'expect_animated'):
                    if 'value' not in s:
                        raise ValueError(f'{act} requires value')
                check_sel(s.get('selector'))
                if 'value' in s:
                    if not isinstance(s['value'], str):
                        raise ValueError('step value must be string')
            if not has_expect:
                raise ValueError('Scenario must have expect action')
            for i, st in enumerate(steps):
                if st.get('action') == 'expect_animated' and (i == 0 or steps[i - 1].get('action') != 'click'):
                    raise ValueError(f"expect_animated in cid {cid} must come directly after the click that starts the animation")
            remembered = set()
            for st in steps:
                if st.get('action') == 'remember_style':
                    remembered.add(st.get('value'))
                elif st.get('action') == 'expect_same_style' and st.get('value') not in remembered:
                    raise ValueError(f"expect_same_style in cid {cid} compares with {st.get('value')!r}, which no earlier remember_style step stored")
            # Checked after all criteria: another criterion showing the same selector also proves it.
            hidden_claims += [(cid, s.get('selector')) for s in steps if s.get('action') == 'expect_hidden']
        elif op == 'junit_added':
            from junit_added_gate import validate_spec
            validate_spec(check)
        elif op == 'api':
            m = check.get('method')
            if m not in ('GET', 'POST', 'PUT', 'PATCH', 'DELETE'):
                raise ValueError('Invalid method')
            p = check.get('path')
            if not isinstance(p, str) or not p.startswith('/') or p.startswith('//') or any((c in p for c in '#@\\')):
                raise ValueError('Invalid path')
            st = check.get('status')
            if not isinstance(st, int) or not 100 <= st <= 599:
                raise ValueError('Invalid status')
            jp = check.get('json_path')
            eq = check.get('equals')
            if ('json_path' in check) != ('equals' in check):
                raise ValueError('json_path and equals must coexist')
            if 'json_path' in check:
                if not isinstance(jp, list):
                    raise ValueError('json_path must be list')
                for (i, comp) in enumerate(jp):
                    if isinstance(comp, bool) or not isinstance(comp, (str, int)) or (isinstance(comp, int) and comp < 0):
                        raise ValueError('Invalid json_path component')
            if isinstance(eq, str) and eq.strip().lower() in ('string', 'number', 'integer', 'int', 'any', 'uuid', 'boolean'):
                raise ValueError(f"equals {eq!r} is a type name, but equals compares the literal value. Check a field you sent in body instead (e.g. json_path ['name'] equals the posted name).")
            if m != 'GET' and not (400 <= st < 500):
                if 'json_path' not in check or 'equals' not in check:
                    raise ValueError('Mutation requires json_path and equals')
            if 'body' in check:
                b = check['body']
                if len(json.dumps(b, allow_nan=False)) > 20000:
                    raise ValueError('Body too large')
        covered_reqs.add(rid)
        hidden_words = ('숨김', '숨겨', '숨기', '숨긴', '닫힘', '닫혀', '닫힌', '접힘', '접혀', '접힌', '안 보', '보이지 않', 'hidden', 'hide', 'collapsed', 'closed')
        if isinstance(desc, str) and check.get('op') != 'absent' and any(w in desc.casefold() for w in hidden_words) and not any(
                st.get('action') == 'expect_hidden' for st in (check.get('steps') or [])):
            raise ValueError(f"Criterion {cid} describes a hidden/collapsed state but its check never asserts it. Use a scenario with expect_hidden (plus expect_visible of the same selector), or change the description; visible/expect_visible prove the opposite.")
        valid_criteria.append({'id': cid, 'requirement_id': rid, 'description': desc, 'check': check})
    shown = {st.get('selector') for c in valid_criteria for st in (c['check'].get('steps') or []) if st.get('action') == 'expect_visible'}
    shown |= {c['check'].get('selector') for c in valid_criteria if c['check'].get('op') == 'visible'}
    for cid, sel in hidden_claims:
        if sel not in shown:
            raise ValueError(f"expect_hidden selector {sel!r} in cid {cid} must also be proven visible (expect_visible step or visible check with the same selector) in this or another criterion; a hidden check alone also passes for a wrong selector.")
    from api_error_payloads import validate_error_payloads
    validate_error_payloads(valid_criteria)
    if len(covered_reqs) != len(req_ids):
        raise ValueError(f"Not all requirements covered. Missing: {sorted(list(req_ids - covered_reqs))}. You must create at least one executable criterion for EACH missing id.")
    res = {'version': 1, 'task': task, 'requirements': reqs, 'criteria': valid_criteria}
    return json.loads(json.dumps(res, allow_nan=False))

def parse(task: str, text: str) -> dict:
    import re
    match = re.search('^```json\n(.*)\n```$', text, re.DOTALL | re.MULTILINE)
    if match:
        text = match.group(1)
    else:
        text = text.strip()

    def duplicate_hook(pairs):
        d = {}
        for (k, v) in pairs:
            if k in d:
                raise ValueError(f'Duplicate key: {k}')
            d[k] = v
        return d
    try:
        data = json.loads(text, object_pairs_hook=duplicate_hook)
    except Exception as e:
        raise ValueError(f'JSON error: {e}')
    return validate(task, data)

def digest(contract: dict) -> str:

    def canonical(obj):
        if isinstance(obj, dict):
            return {k: canonical(obj[k]) for k in sorted(obj.keys())}
        if isinstance(obj, list):
            return [canonical(x) for x in obj]
        return obj
    s = json.dumps(canonical(contract), sort_keys=True, ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(s.encode('utf-8')).hexdigest()
