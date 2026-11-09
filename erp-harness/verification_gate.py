import re
import subprocess
import json
import os
import uuid
import hashlib
from pathlib import Path
import requirement_contract

def css_selector(e):
    """A ready-to-use CSS selector for an inventoried element (real attribute names), plus button text."""
    if e.get('field'):
        return e['field']
    attrs = (('role', 'role'), ('label', 'aria-label'), ('ui', 'data-ui'), ('testid', 'data-testid'), ('region', 'data-region'))
    sel = (e.get('tag') or '') + ''.join('[%s="%s"]' % (name, str(e[key]).replace('"', '\\"')) for key, name in attrs if e.get(key))
    if e.get('id'):
        sel += '#' + str(e['id'])
    if e.get('text'):
        sel += ':has-text("%s")' % str(e['text']).replace('"', '\\"')
    return sel


def selector_parts(selector):
    """Top-level compound selectors of a CSS/Playwright selector (descendant and child combinators)."""
    parts, buf, depth, quote = [], '', 0, ''
    for ch in selector.strip():
        if quote:
            buf += ch
            if ch == quote:
                quote = ''
            continue
        if ch in '\'"':
            quote = ch
        elif ch in '([':
            depth += 1
        elif ch in ')]':
            depth -= 1
        if depth == 0 and (ch.isspace() or ch == '>'):
            if buf.strip():
                parts.append(buf.strip())
            buf = ''
            continue
        buf += ch
    if buf.strip():
        parts.append(buf.strip())
    return parts


class Gate:

    def __init__(self, runner):
        self.runner = runner
        self.enabled = any((m in runner.modes for m in ['frontend', 'framework', 'backend']))
        self.frozen_contract = None
        self.contract_hash = None
        self.artifact_dir = Path.home() / '.local/state/local-workshop/verification' / uuid.uuid4().hex
        self._initial_hashes = self._source_hashes(runner.h.workspace.root)

    def _source_hashes(self, root: Path) -> dict[str, bytes]:
        hashes = {}
        for sub in ['frontend/src', 'backend/src']:
            target = root / sub
            if not target.exists():
                continue
            for path in target.rglob('*'):
                if path.is_file() and (not path.is_symlink()):
                    if path.stat().st_size <= 1048576:
                        rel = path.relative_to(root)
                        with path.open('rb') as f:
                            hashes[str(rel)] = hashlib.sha256(f.read()).digest()
        return hashes

    def prepare(self):
        if not self.enabled or self.frozen_contract:
            return
        if getattr(self.runner.args, 'fixed_acceptance', None) is not None:
            from fixed_acceptance import prepare
            return prepare(self, self.runner.args.fixed_acceptance)
        from junit_added_gate import capture_baseline
        self._junit_baseline = capture_baseline(self.runner.h.workspace.root)
        if getattr(self.runner.args, 'resume_contract', None) is not None:
            rc = self.runner.args.resume_contract
            if not isinstance(rc, dict) or not rc.get("source_job") or \
               not isinstance(rc.get("contract"), dict) or not rc.get("contract_hash"):
                raise ValueError("Invalid rc structure")

            task = self.runner.args.task
            contract = rc["contract"]
            
            if contract.get("task") != task or \
               contract.get("requirements") != requirement_contract.requirements(task):
                raise ValueError("Contract mismatch with task requirements")

            parsed = requirement_contract.validate(task, contract)

            if requirement_contract.digest(contract) != rc["contract_hash"] or \
               requirement_contract.digest(parsed) != rc["contract_hash"]:
                raise ValueError("Contract hash mismatch")

            if any(c.get("check", {}).get("op") == "manual" for c in parsed["criteria"]):
                raise ValueError("Manual check detected in parsed contract")

            contract_hash = rc["contract_hash"]
            self.frozen_contract = json.dumps(parsed, ensure_ascii=False, sort_keys=True, allow_nan=False)
            self.contract_hash = contract_hash

            self.artifact_dir.mkdir(parents=True, exist_ok=True)
            with open(self.artifact_dir / "contract.json", "w", encoding="utf-8") as f:
                json.dump(contract, f, ensure_ascii=False, indent=4)

            self.runner.h.log_event('requirement.contract', {
                'contract': parsed,
                'contract_hash': contract_hash,
                'artifact_dir': str(self.artifact_dir),
                'source_job': rc['source_job']
            })
            
            self.runner.h.log_event('requirement.contract_reused', {
                'source_job': rc['source_job'],
                'contract_hash': contract_hash,
                'model_calls': 0
            })
            return None
        get_task = self.runner.args.task
        (ctx_str, _) = self.runner.current_context()
        from active_preview_context import active_screen_context
        ctx_str = active_screen_context(self.runner) + ctx_str
        prompt = requirement_contract.prompt(get_task) + '\nThis autonomous run has no manual approval step. Use executable visible/text/layout/scenario/api checks for concrete requirements. Explanatory headings can map to an objective overall layout check. Manual checks cannot be completed by code edits. The browser tab title is checked with {"op":"text","selector":"title","contains":"..."}. Browser checks run with writes blocked (POST/PUT/PATCH/DELETE are aborted), so never require a successful save/delete; check validation, visibility and values instead. Be concise: at most 2 criteria per requirement and at most 6 criteria in total, descriptions under 80 characters, compact JSON without comments or extra keys.\n' + ctx_str[:14000]
        approach = os.environ.get('HARNESS_TASK_APPROACH', '').strip()
        if approach:
            # The planned direction names the fields/paths the author will build; checks must use the same ones.
            prompt += '\nPLANNED DIRECTION (the author builds this; use the same fields, names and paths in request bodies and selectors): ' + approach[:1200]
        if 'backend' in (getattr(self.runner, 'modes', ()) or ()):
            prompt += ('\nAPI JSON uses camelCase field names like the existing APIs (e.g. {"itemCode": "A1", "name": "볼트"}); '
                       'snake_case names such as dept_code are database columns and never appear in request bodies or json_path.')
        from component_catalog import context_for_task
        prompt += context_for_task(self.runner)
        from task_sources import task_screen_title
        screen = task_screen_title(self.runner.h.workspace.root, get_task)
        from task_sources import new_screen_reference
        reference = '' if screen else new_screen_reference(self.runner.h.workspace.root, get_task)
        self._probe_screen = reference
        if reference:
            prompt += (f"\nThis task adds a NEW screen; it does not exist yet. It is built from the same framework components as the "
                       f"'{reference}' screen, and browser checks open it from the menu by its own title. Check its parts with the same "
                       "tags and attributes the reference screen has, and its own fields and columns by their labels "
                       "(e.g. internal:label=\"회사명\"). Do not invent elements (h1, main, ...) the reference screen lacks.")
            elements = self._screen_inventory()
            self.runner._screen_layout_facts = (f"New screen, not built yet; it uses the same components as '{reference}'. "
                                                "Its editor puts required fields in tab 기본정보 and the rest in 추가정보.")
            if elements:
                prompt += f"\nREFERENCE SCREEN ELEMENTS ('{reference}', same components as the new screen): " + elements
        elif screen:
            prompt += f"\nBrowser checks start after login with the '{screen}' screen already opened from the menu; do not add steps to open it. Selectors must match elements of that screen."
            elements = self._screen_inventory()
            if elements:
                prompt += "\nCURRENT SCREEN ELEMENTS (before the change; use these exact attributes for selectors of existing elements): " + elements
        messages = [{'role': 'system', 'content': 'JSON only'}, {'role': 'user', 'content': prompt}]
        last_error = ''
        attempts = int(os.environ.get('REQUIREMENT_CONTRACT_ATTEMPTS', '3'))
        for attempt in range(attempts):
            response = self.runner.ask(messages=list(messages), tools=[])
            try:
                parsed = requirement_contract.parse(get_task, response['content'])
                manual_ids = [c['id'] for c in parsed['criteria'] if c.get('check', {}).get('op') == 'manual']
                if manual_ids and len(manual_ids) < len(parsed['criteria']):
                    # Wording like "프레임워크에서 살펴야함" says where to change, not something a check can observe.
                    # Keep the executable criteria; the reviewer below still judges whether the request is covered.
                    kept = dict(parsed, criteria=[c for c in parsed['criteria'] if c['id'] not in manual_ids])
                    parsed = requirement_contract.validate(get_task, kept)
                    self.runner.h.log_event('requirement.manual_dropped', {'removed': manual_ids})
                    manual_ids = []
                if manual_ids:
                    raise ValueError(f'Manual criteria cannot be executed automatically. Replace these with measurable DSL checks; do not drop request clauses or invent human approval. IDs: {manual_ids}')

                if not {'frontend', 'framework'} & set(getattr(self.runner, 'modes', ()) or ()):
                    ui = [c['id'] for c in parsed['criteria'] if c['check'].get('op') not in ('api', 'junit_added')]
                    if ui:
                        raise ValueError(f'This task is backend only (no screen is part of it): check it through its API with op=api. Remove or replace {ui}.')
                self._require_absent_baseline(parsed)
                self._require_unique_selectors(parsed)
                self._dry_run_scenarios(parsed)
                from requirement_review import review
                review_result = review(self.runner, parsed)
                if review_result['approved'] is not True:
                    pruned = self._prune_rejected(get_task, parsed, review_result)
                    if pruned is not None:
                        parsed, review_result = pruned
                if review_result['approved'] is not True:
                    raise ValueError('Requirement review rejected: ' + json.dumps(review_result['issues'], ensure_ascii=False))
                frozen = json.dumps(parsed, ensure_ascii=False, sort_keys=True, allow_nan=False)
                h = requirement_contract.digest(parsed)
                self.frozen_contract = frozen
                self.contract_hash = h
                self.artifact_dir.mkdir(parents=True, exist_ok=True)
                (self.artifact_dir / 'contract.json').write_text(frozen, encoding='utf-8')
                self.runner.h.log_event('requirement.contract', {'contract': parsed, 'contract_hash': h, 'artifact_dir': str(self.artifact_dir)})
                return
            except Exception as e:
                if isinstance(e, (SystemExit, KeyboardInterrupt)):
                    raise
                last_error = str(e)
                self.runner.h.log_event('requirement.contract_rejected', {'success': False, 'error': last_error, 'attempt': attempt + 1})
                # Keep the actual rejected draft adjacent to its feedback; do not
                # accumulate stale corrections without the draft they refer to.
                messages = messages[:2] + [
                    {'role': 'assistant', 'content': response['content']},
                    {'role': 'user', 'content': f'Revise this draft using the feedback: {last_error}. Return the complete corrected JSON. Preserve all request clauses and consistent selectors. Use literal subject/relation/reference layout expressions.'},
                ]
                if attempt == attempts - 1:
                    if os.environ.get('REQUIREMENT_CONTRACT_FALLBACK') != '1':
                        raise RuntimeError(f'Requirement contract unavailable; completion blocked: {last_error}')
                    # Opt-in only: never treat an unverified run as success by default.
                    self.enabled = False
                    self.runner.h.log_event('requirement.contract_fallback', {
                        'success': False, 'error': last_error[:500], 'attempts': attempts,
                        'detail': 'Acceptance contract unavailable; completion uses selected checks only.'})
                    return

    def _prune_rejected(self, task, parsed, review_result):
        """Drop the criteria the reviewer rejected and ask it once more about the rest.

        Rejections are usually extra criteria the request never asked for (an API parameter, an exact
        position). Removing them keeps the contract faithful; the reviewer re-checks that what remains
        still covers the whole request, so coverage is never dropped silently."""
        ids = {c['id'] for c in parsed['criteria']}
        rejected = {str(i.get('criterion_id')) for i in review_result.get('issues', [])}
        if not rejected or not rejected <= ids or len(rejected) >= len(ids):
            return None
        raw = json.loads(json.dumps(parsed))
        raw['criteria'] = [c for c in raw['criteria'] if c['id'] not in rejected]
        try:
            pruned = requirement_contract.validate(task, raw)
            self._require_unique_selectors(pruned)
            from requirement_review import review
            again = review(self.runner, pruned)
        except Exception as error:
            self.runner.h.log_event('requirement.contract_pruned', {'removed': sorted(rejected), 'approved': False, 'error': str(error)[:300]})
            return None
        self.runner.h.log_event('requirement.contract_pruned', {'removed': sorted(rejected), 'approved': again['approved'] is True,
                                                               'issues': again.get('issues', [])})
        return (pruned, again) if again['approved'] is True else None

    def _dry_run_scenarios(self, parsed):
        """Run each scenario on the untouched screen. Steps on new elements fail there as expected, but a
        step that cannot reach an element which exists on the default screen fails because of the steps
        before it (e.g. a tab switch hid it) — no code change can fix that, so the draft is rejected."""
        counts = getattr(self, '_baseline_counts', None) or {}
        scenarios = [c for c in parsed['criteria'] if c.get('check', {}).get('op') == 'scenario']
        if not scenarios or not counts:
            return
        try:
            report = self._probe(scenarios)
        except Exception:
            return
        by_id = {c['id']: c for c in scenarios}
        problems = []
        for r in report.get('results', []):
            m = re.match(r'step (\d+) \(', str(r.get('reason', '')))
            if r.get('status') != 'failed' or not m or r.get('id') not in by_id:
                continue
            steps = by_id[r['id']]['check']['steps']
            index = int(m.group(1)) - 1
            if not 0 < index < len(steps):
                continue
            step = steps[index]
            if (step.get('action') in ('fill', 'click', 'select', 'expect_value') and counts.get(step.get('selector'), 0) > 0
                    and 'does not exist in the DOM at this point' in r['reason']):
                problems.append(f"{r['id']} step {index + 1} ({step['action']} {step['selector']}): this element is on the default "
                                f"screen but is gone after the earlier steps (e.g. a tab switch hides the other tab's fields). "
                                f"Reorder the steps (fill a tab's fields while that tab is open) or open its tab again first.")
        self.runner.h.log_event('requirement.dry_run', {'problems': problems})
        if problems:
            raise ValueError('scenario steps cannot run as written: ' + ' '.join(problems))

    def _drop_write_criteria(self, contract, report):
        """A criterion that needs a real write can never pass here (browser writes are blocked) and no
        code edit can change that. Once every other criterion passes, drop it if the reviewer confirms
        the rest still covers the request; otherwise it stays and the run fails honestly."""
        results = report.get('results', [])
        blocked = {r['id'] for r in results if r.get('status') == 'unverified' and r.get('reason') == 'blocked_requests'}
        if not blocked or getattr(self, '_write_criteria_checked', False):
            return contract
        if any(r.get('status') != 'passed' for r in results if r['id'] not in blocked):
            return contract
        self._write_criteria_checked = True
        issues = [{'criterion_id': cid, 'reason': 'requires a real write; browser checks block writes'} for cid in sorted(blocked)]
        pruned = self._prune_rejected(self.runner.args.task, contract, {'approved': False, 'issues': issues})
        if pruned is None:
            return contract
        contract = pruned[0]
        self.frozen_contract = json.dumps(contract, ensure_ascii=False, sort_keys=True, allow_nan=False)
        self.contract_hash = requirement_contract.digest(contract)
        self.artifact_dir.mkdir(parents=True, exist_ok=True)
        (self.artifact_dir / 'contract.json').write_text(self.frozen_contract, encoding='utf-8')
        report['results'] = [r for r in results if r['id'] not in blocked]
        report['success'] = all(r.get('status') == 'passed' for r in report['results'])
        report['dropped_write_criteria'] = sorted(blocked)
        self.runner.h.log_event('requirement.contract', {'contract': contract, 'contract_hash': self.contract_hash,
                                                         'artifact_dir': str(self.artifact_dir), 'dropped_write_criteria': sorted(blocked)})
        return contract

    def _screen_inventory(self):
        """Selector-relevant attributes of the opened target screen, as one compact line."""
        try:
            report = self._probe([{'id': 'inventory', 'requirement_id': 'R1', 'description': 'screen inventory', 'check': {'op': 'inventory'}}])
        except Exception:
            return ''
        elements, tabs = [], []
        for r in report.get('results', []):
            elements = (r.get('evidence') or {}).get('elements') or elements
            tabs = (r.get('evidence') or {}).get('tabs') or tabs
        text = '; '.join(css_selector(e) for e in elements[:60])[:5000]
        if tabs:
            self.runner._screen_layout_facts = 'Existing editor tabs: ' + '; '.join(
                f"fields {', '.join(t['fields'][:12])} are in tab '{t['tab']}' (not visible until that tab is clicked)" for t in tabs[:6])
            text += ('\nFIELDS IN INACTIVE TABS (not visible on the default screen; a scenario must first click the tab, '
                     'e.g. {"action":"click","selector":"role=tab[name=\\"<tab>\\"]"}): '
                     + '; '.join(f"tab '{t['tab']}': " + ', '.join(t['fields'][:12]) for t in tabs[:6]))
        return text

    def _require_unique_selectors(self, parsed):
        """Validate contract selectors against the screen before the change.

        - visible/text/layout selectors that already match several elements are ambiguous;
        - the container part of a descendant selector (e.g. ``form[...]`` in ``form[...] input``) must exist now;
        - a selector matching nothing while its attributes match an element of another tag uses the wrong tag.
        """
        single, every = [], []
        for c in parsed['criteria']:
            check = c.get('check', {})
            if check.get('op') in ('visible', 'text'):
                single.append((c['id'], check.get('selector')))
            elif check.get('op') == 'layout':
                single += [(c['id'], check.get('left')), (c['id'], check.get('right'))]
            elif check.get('op') == 'scenario':
                every += [(c['id'], st.get('selector')) for st in check.get('steps', [])]
                single += [(c['id'], st.get('selector')) for st in check.get('steps', [])
                           if st.get('action') in ('fill', 'click', 'select', 'expect_value', 'expect_text', 'remember_style')]
        every += single
        every = [(cid, sel) for cid, sel in every if isinstance(sel, str)]
        if not every:
            return
        derived = {}
        for _, sel in every:
            parts = selector_parts(sel) if '>>' not in sel else [sel]
            if len(parts) > 1:
                derived[sel] = ('container', parts[0])
            elif '>>' in sel:
                derived[sel] = ('container', sel.split('>>')[0].strip())
            elif re.match(r'^[a-zA-Z][\w-]*\[', sel):
                derived[sel] = ('attrs', re.sub(r'^[a-zA-Z][\w-]*', '', sel, count=1))
        queries = sorted({sel for _, sel in every} | {v for _, v in derived.values()})
        try:
            report = self._probe([{'id': 'count', 'requirement_id': parsed['criteria'][0].get('requirement_id'),
                                   'description': 'selector counts', 'check': {'op': 'count', 'selectors': queries}}])
        except Exception:
            return
        counts, visible = {}, {}
        for r in report.get('results', []):
            counts = (r.get('evidence') or {}).get('counts') or counts
            visible = (r.get('evidence') or {}).get('visible') or visible
        problems = {}
        # The first action of each scenario runs on the untouched screen, so its target must be visible there.
        for c in parsed['criteria']:
            check = c.get('check', {})
            if check.get('op') != 'scenario':
                continue
            first = next((st for st in check.get('steps', []) if st.get('action') in ('click', 'fill', 'select')), None)
            if first and isinstance(first.get('selector'), str) and visible.get(first['selector']) == 0 and counts.get(first['selector'], 0) > 0:
                problems.setdefault(c['id'], []).append(f"first action targets {first['selector']}, which exists but is not visible on the starting screen; add the steps that reveal it first (e.g. the click that collapses or opens the area)")
        for cid, sel in every:
            if counts.get(sel) == -1:
                problems.setdefault(cid, []).append(f'{sel} is not a valid selector')
        for cid, sel in single:
            if counts.get(sel, 0) > 1:
                problems.setdefault(cid, []).append(f'{sel} already matches {counts[sel]} elements (needs exactly one)')
        for cid, sel in every:
            kind, other = derived.get(sel, (None, None))
            if kind == 'container' and counts.get(other, 0) == 0:
                problems.setdefault(cid, []).append(f'container {other} of {sel} matches nothing on the current screen')
            elif kind == 'attrs' and counts.get(sel, 0) == 0 and counts.get(other, 0) > 0:
                problems.setdefault(cid, []).append(f'{sel} matches nothing but {other} exists with another tag')
        reference = getattr(self, '_probe_screen', '')
        if reference:
            # A structural selector (no label/name/text) absent from a screen of the same components will be absent from the new one too.
            named = re.compile(r'internal:|has-text|text=|aria-label|\[name=|placeholder|title=')
            for cid, sel in every:
                if counts.get(sel, 0) == 0 and not named.search(sel):
                    problems.setdefault(cid, []).append(f"{sel} matches nothing on '{reference}', which is built from the same components, "
                                                        "so the new screen will not have it either")
        self._baseline_counts = counts
        self.runner.h.log_event('requirement.selector_counts', {'counts': counts, 'problems': problems})
        if problems:
            raise ValueError(f"criteria selectors do not fit the current screen: {problems}. Use the exact tags and attributes "
                             "from the CURRENT SCREEN ELEMENTS for existing elements; only the new element itself may be absent before the change.")

    def _require_absent_baseline(self, parsed):
        """An absence check only means something if the element exists before the change."""
        absent = [c for c in parsed['criteria'] if c.get('check', {}).get('op') == 'absent']
        if not absent:
            return
        probes = [{'id': c['id'], 'requirement_id': c.get('requirement_id'), 'description': 'baseline presence',
                   'check': {'op': 'visible', 'selector': c['check']['selector']}} for c in absent]
        report = self._probe(probes)
        passed = {r.get('id') for r in report.get('results', []) if r.get('status') == 'passed'}
        missing = [c['id'] for c in absent if c['id'] not in passed]
        self.runner.h.log_event('requirement.absent_baseline', {'checked': [c['id'] for c in absent], 'missing': missing})
        if missing:
            elements = []
            try:
                inventory = self._probe([{'id': 'inventory', 'requirement_id': absent[0].get('requirement_id'),
                                          'description': 'screen inventory', 'check': {'op': 'inventory'}}])
                for r in inventory.get('results', []):
                    elements = (r.get('evidence') or {}).get('elements') or elements
            except Exception:
                elements = []
            shown = '; '.join(css_selector(e) for e in elements[:60])
            used = {c['id']: c['check']['selector'] for c in absent if c['id'] in missing}
            raise ValueError(f"absent criteria {missing} use selectors {used} that match nothing on the current screen before the change, "
                             "so absence would pass trivially. Pick the element being removed from the CURRENT SCREEN ELEMENTS below "
                             "(e.g. [role='separator'][aria-label='...'] or [data-ui='...']). CURRENT SCREEN ELEMENTS: " + (shown or 'unavailable'))

    def context(self) -> str:
        if self.enabled and self.frozen_contract:
            if json.loads(self.frozen_contract).get('provenance') == 'trusted-fixed-browser-oracle':
                from fixed_acceptance import context
                return context(self)
            return self.frozen_contract + '\nEvery criterion must pass. Manual/unverified blocks completion.'
        return ''

    def _input(self, criteria: list[dict]) -> dict:
        p_url = os.environ.get('HARNESS_VERIFICATION_PREVIEW_URL') or os.environ.get('HARNESS_PREVIEW_URL') or ''
        a_url = os.environ.get('HARNESS_VERIFICATION_API_URL') or os.environ.get('HARNESS_API_URL') or ''

        def is_isolated(env_key, url_env, default_url):
            flag = os.environ.get(env_key) == '1'
            val = os.environ.get(url_env) or ''
            return flag and val != '' and (val != default_url)
        def_p = os.environ.get('HARNESS_PREVIEW_URL', '')
        def_a = os.environ.get('HARNESS_API_URL', '')
        from task_sources import task_screen_title
        try:
            screen = task_screen_title(self.runner.h.workspace.root, self.runner.args.task)
        except Exception:
            screen = ''
        if not screen and not self.frozen_contract:
            screen = getattr(self, '_probe_screen', '')  # a new screen's contract is probed on its reference screen
        return {'open_screen': screen, 'contract': {'criteria': criteria, 'requirements': json.loads(self.frozen_contract).get('requirements', []) if self.frozen_contract else []}, 'preview_url': p_url, 'api_url': a_url, 'output_dir': str(self.artifact_dir / uuid.uuid4().hex), 'allow_browser_writes': is_isolated('HARNESS_VERIFICATION_BROWSER_ISOLATED', 'HARNESS_VERIFICATION_PREVIEW_URL', def_p), 'allow_api_writes': is_isolated('HARNESS_VERIFICATION_API_ISOLATED', 'HARNESS_VERIFICATION_API_URL', def_a)}

    def _probe(self, criteria: list):
        if any(c.get('check', {}).get('op') == 'fixed_browser' for c in criteria):
            from fixed_acceptance import probe
            return probe(self, criteria)
        import json
        import os
        import subprocess
        from pathlib import Path
        actual_path = self.runner.h.workspace.root
        actual_checker = self.runner.h.checker
        results = []
        layout = []
        screenshot = None
        api_list = []
        junit_list = []
        node_list = []
        for c in criteria:
            check_type = c.get('check', {}).get('op')
            if check_type == 'junit_added':
                junit_list.append(c)
            elif check_type == 'api':
                api_list.append(c)
            else:
                node_list.append(c)
        junit_success = True
        if junit_list:
            try:
                import junit_added_gate
                junit_report = junit_added_gate.verify(actual_checker, junit_list, getattr(self, '_junit_baseline', None), self.artifact_dir / uuid.uuid4().hex)
                junit_success = junit_report.get('success') is True
                results.extend(junit_report.get('results', []))
            except Exception as e:
                junit_success = False
                results.extend({'id': c['id'], 'status': 'unverified', 'reason': str(e), 'evidence': {}} for c in junit_list)
        api_success = True
        api_results = []
        node_success = True
        if api_list:
            pom_path = Path(actual_path) / 'backend' / 'pom.xml'
            if pom_path.is_file() and (not os.environ.get('HARNESS_VERIFICATION_API_URL')):
                try:
                    import backend_contract_gate
                    input_data = self._input(api_list)
                    api_report = backend_contract_gate.verify(actual_checker, api_list, input_data['output_dir'])
                    api_results = api_report.get('results', [])
                    api_success = api_report.get('success', False)
                except Exception as e:
                    api_success = False
                    for c in api_list:
                        api_results.append({'id': c['id'], 'status': 'unverified', 'reason': str(e), 'evidence': ''})
            else:
                node_list.extend(api_list)
                api_list = []
                api_success = True
        results.extend(api_results)
        if node_list:
            node_success = True
            node_results = []
            node_layout = []
            node_screenshot = None
            script_path = Path(__file__).resolve().with_name('react_layout_inspector.cjs')
            try:
                input_data = self._input(node_list)
                proc = subprocess.run(['node', str(script_path)], input=json.dumps(input_data), text=True, capture_output=True, timeout=120)
                raw_out = json.loads(proc.stdout)
                node_success = raw_out.get('success', False)
                node_results = raw_out.get('results', [])
                node_layout = raw_out.get('layout', [])
                node_screenshot = raw_out.get('screenshot')
            except Exception as e:
                node_success = False
                reason = str(e) if str(e) else 'subprocess_error'
                for c in node_list:
                    node_results.append({'id': c['id'], 'status': 'unverified', 'reason': reason, 'evidence': ''})
            results.extend(node_results)
            layout.extend(node_layout)
            screenshot = node_screenshot
            if not node_success and any((r.get('status') != 'unverified' for r in node_results)):
                pass
            elif not node_success and (not node_results):
                pass
        expected_ids = [c['id'] for c in criteria]
        seen_ids = []
        valid_report = True
        for eid in expected_ids:
            if eid.startswith('system:'):
                continue
            count = 0
            for r in results:
                if r.get('id') == eid:
                    count += 1
            if count != 1:
                valid_report = False
                break
        for r in results:
            rid = r.get('id') if r.get('id') is not None else None
            if rid not in expected_ids and (not rid.startswith('system:')):
                valid_report = False
                break
        final_success = True
        if not valid_report:
            final_success = False
            results = []
            for c in criteria:
                results.append({'id': c['id'], 'status': 'unverified', 'reason': 'invalid_report', 'evidence': ''})
        else:
            all_passed = len(results) > 0
            for r in results:
                if r.get('status') not in ('passed', 'failed', 'unverified'):
                    all_passed = False
                if r.get('status') != 'passed':
                    all_passed = False
            if not (api_success if api_list else True) or not (node_success if node_list else True) or not junit_success:
                all_passed = False
            if not all_passed:
                final_success = False
                if not (api_success if api_list else True) and (not (node_success if node_list else True)):
                    pass
                if all((r.get('status') == 'passed' for r in results)) and (not api_success or not node_success or not junit_success):
                    results.append({'id': 'system:probe', 'status': 'failed', 'reason': 'executor_error', 'evidence': ''})
                    final_success = False
        return {'success': final_success, 'results': results, 'layout': layout, 'screenshot': screenshot}

    def verify(self) -> dict:
        import json
        import uuid
        from datetime import datetime, timezone
        if not self.enabled:
            return {'success': True, 'disabled': True}
        if not self.frozen_contract:
            raise RuntimeError('Requirement contract missing or changed; completion blocked')
        try:
            contract = json.loads(self.frozen_contract)
            if self.contract_hash != requirement_contract.digest(contract):
                raise ValueError()
        except Exception:
            raise RuntimeError('Requirement contract missing or changed; completion blocked')
        actual_report = self._probe(contract['criteria'])
        contract = self._drop_write_criteria(contract, actual_report)
        current_source_hashes = self._source_hashes(self.runner.h.workspace.root)
        changed_paths = set()
        all_keys = set(self._initial_hashes.keys()) | set(current_source_hashes.keys())
        for path in all_keys:
            old_h = self._initial_hashes.get(path)
            new_h = current_source_hashes.get(path)
            if old_h != new_h:
                changed_paths.add(path)
        mutation_passed = self.runner.accepted and len(changed_paths) > 0
        mutation_result = {'id': 'system:mutation', 'status': 'passed' if mutation_passed else 'failed', 'reason': 'verified source change' if mutation_passed else 'none'}
        actual_report['results'].append(mutation_result)
        all_statuses_passed = all((r.get('status') == 'passed' for r in actual_report['results']))
        actual_report['success'] = actual_report['success'] and mutation_passed and all_statuses_passed
        actual_report.update({'contract_hash': self.contract_hash, 'task': self.runner.args.task, 'timestamp_utc': datetime.now(timezone.utc).isoformat(), 'changed_paths': list(changed_paths)})
        self.artifact_dir.mkdir(parents=True, exist_ok=True)
        report_path = self.artifact_dir / f'{uuid.uuid4().hex}-report.json'
        actual_report['report_path'] = str(report_path)
        with open(report_path, 'w') as f:
            json.dump(actual_report, f)
        self.runner.h.log_event('verification.finished', actual_report)
        return actual_report

    def inspect(self) -> dict:
        import json
        import uuid
        from datetime import datetime, timezone
        try:
            report = self._probe([{'id': 'layout-inspection', 'check': {'op': 'visible', 'selector': 'body'}}])
            return {'measurement_only': True, 'layout': report.get('layout', []), 'screenshot': report.get('screenshot'), 'results': report.get('results', []), 'error': None}
        except Exception as e:
            return {'measurement_only': True, 'layout': [], 'screenshot': None, 'results': [], 'error': str(e)}
TOOLS = [{'type': 'function', 'function': {'name': 'inspect_layout', 'description': 'Measure actual rendered React DOM rectangles and styles.', 'parameters': {'type': 'object', 'properties': {}, 'additionalProperties': False}}}, {'type': 'function', 'function': {'name': 'verify_requirements', 'description': 'Execute immutable contract verification against current state.', 'parameters': {'type': 'object', 'properties': {}, 'additionalProperties': False}}}]
