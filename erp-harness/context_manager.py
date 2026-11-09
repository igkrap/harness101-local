"""Automatic context management for the local-model agent loop.

Pipeline before a model call (ContextBudgetMixin.ask -> prepare):

    budget check -> (below soft threshold: send as is)
                 -> deterministic pruning of old/duplicate tool output
                 -> still high? archive raw span -> local-model incremental compaction
                 -> validate + deterministic repair -> commit checkpoint (atomic)
                 -> rebuild [system][project/task][checkpoint][recent original messages]

Design notes
- Compaction runs only when a threshold is crossed and then frees a large block, so the
  prompt prefix stays stable between compactions (the MLX server reuses its prompt cache;
  rewriting the prefix on every call made each call a full multi-minute prefill).
- Facts the harness knows (goal, frozen constraints, modified files, test status, latest
  error) are merged by code; the model only summarizes what happened and what to do next.
- A failed or invalid compaction never replaces the last valid checkpoint; at the hard
  threshold a deterministic checkpoint is used so the run can continue.
- Raw history is archived per checkpoint (never deleted by default) and searchable.
"""
import copy
import fcntl
import hashlib
import json
import math
import os
import re
import time
from contextlib import contextmanager
from pathlib import Path

CONFIG_FILE = Path(__file__).with_name('context_config.json')
CHECKPOINT_MARK = '[CONTEXT CHECKPOINT]'
SCHEMA_VERSION = 1
LIST_FIELDS = ('completed_tasks', 'decisions', 'constraints', 'modified_files', 'active_errors',
               'failed_attempts', 'test_status', 'next_actions', 'unknowns')
TEXT_FIELDS = ('goal', 'current_task')


# ---------------------------------------------------------------- configuration

def load_config():
    data = {}
    for path in (CONFIG_FILE, os.environ.get('HARNESS_CONTEXT_CONFIG')):
        if path and Path(path).is_file():
            try:
                data.update(json.loads(Path(path).read_text(encoding='utf-8')).get('context_management', {}))
            except (OSError, ValueError):
                pass
    flag = os.environ.get('HARNESS_CONTEXT_MANAGEMENT')
    if flag is not None:
        data['enabled'] = flag not in ('0', 'false', 'off', '')
    env_cap = os.environ.get('LOCAL_LLM_CONTEXT')
    if env_cap and env_cap.isdigit():
        data['max_context_tokens'] = min(int(data.get('max_context_tokens', 40960)), int(env_cap))
    defaults = {'enabled': True, 'max_context_tokens': 40960, 'soft_compact_threshold': 0.68,
                'hard_compact_threshold': 0.78, 'prune_only_target': 0.55, 'min_output_reserve_tokens': 8192,
                'summary_target_tokens': 1500, 'summary_max_tokens': 2500, 'summary_output_tokens': 3072,
                'recent_messages_target_tokens': 5000, 'prune_keep_recent_rounds': 3, 'prune_min_result_chars': 1500,
                'archive_raw_history': True, 'validate_before_commit': True, 'restore_on_failure': True,
                'max_failed_compactions': 3, 'llm_attempts': 2, 'token_safety_margin': 1.08,
                'default_chars_per_token': 3.0, 'keep_checkpoint_versions': 0, 'archive_max_mb': 200,
                'archive_delete_enabled': False, 'incremental_compaction': True}
    return {**defaults, **data}


def enabled():
    return bool(load_config().get('enabled'))


# ---------------------------------------------------------------- token budget

def _clean(messages):
    return [{k: v for k, v in m.items() if k not in ('reasoning', 'reasoning_content')} for m in messages]


def _chars(messages, tools=None):
    return len(json.dumps(_clean(messages), ensure_ascii=False)) + (len(json.dumps(tools, ensure_ascii=False)) if tools else 0)


class TokenMeter:
    """Character-based estimate calibrated against the server's real prompt token counts.

    The tokenizer lives in the model server's environment, so the harness learns the
    chars-per-token ratio from usage.prompt_tokens and stays conservative (smallest
    observed ratio, plus a safety margin). Until calibrated it uses chars/3 (overcounts)."""

    def __init__(self, cfg):
        self.default = float(cfg.get('default_chars_per_token', 3.0))
        self.margin = float(cfg.get('token_safety_margin', 1.08))
        self.samples = []

    @property
    def ratio(self):
        return min(self.samples) if self.samples else None

    def observe(self, chars, prompt_tokens):
        if isinstance(prompt_tokens, int) and prompt_tokens >= 500 and chars > 0:
            self.samples = (self.samples + [chars / prompt_tokens])[-12:]

    def tokens_for_chars(self, chars):
        if self.ratio:
            return math.ceil(chars / self.ratio * self.margin)
        return math.ceil(chars / self.default)

    def count(self, messages, tools=None):
        return self.tokens_for_chars(_chars(messages, tools))

    def text(self, value):
        return self.tokens_for_chars(len(value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)))


class Budget:
    def __init__(self, cfg, meter):
        self.cfg, self.meter = cfg, meter

    def reserve(self):
        return max(int(self.cfg['min_output_reserve_tokens']), int(os.environ.get('LOCAL_LLM_MAX_TOKENS', '4096') or 4096))

    def usage(self, messages, tools=None):
        tokens = self.meter.count(messages, tools)
        cap = int(self.cfg['max_context_tokens'])
        reserve = self.reserve()
        return {'input_tokens': tokens, 'reserve_tokens': reserve, 'max_context_tokens': cap,
                'ratio': round((tokens + reserve) / cap, 4), 'tools_tokens': self.meter.count([], tools) if tools else 0,
                'calibrated': self.meter.ratio is not None}

    def level(self, usage):
        if usage['ratio'] >= self.cfg['hard_compact_threshold']:
            return 'hard'
        if usage['ratio'] >= self.cfg['soft_compact_threshold']:
            return 'soft'
        return 'ok'


# ---------------------------------------------------------------- archive / checkpoints

class Store:
    """Per-run context state under <job dir>/context, written atomically and serialized by a file lock."""

    def __init__(self, root):
        self.root = Path(root) if root else None
        if self.root:
            for sub in ('checkpoints', 'archive', 'pruned'):
                (self.root / sub).mkdir(parents=True, exist_ok=True)
            for tmp in self.root.rglob('*.tmp'):
                try:
                    tmp.unlink()  # leftovers of an interrupted write are never valid state
                except OSError:
                    pass

    @staticmethod
    def _atomic(path, text):
        tmp = path.with_name(path.name + '.tmp')
        with open(tmp, 'w', encoding='utf-8') as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)

    @contextmanager
    def lock(self, wait_seconds=0.0):
        if not self.root:
            yield True
            return
        handle = open(self.root / '.lock', 'a+')
        deadline = time.monotonic() + wait_seconds
        acquired = False
        try:
            while True:
                try:
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    acquired = True
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        break
                    time.sleep(0.2)
            yield acquired
        finally:
            if acquired:
                fcntl.flock(handle, fcntl.LOCK_UN)
            handle.close()

    def state(self):
        if not self.root:
            return {}
        try:
            return json.loads((self.root / 'state.json').read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return {}

    def save_state(self, state):
        if self.root:
            self._atomic(self.root / 'state.json', json.dumps(state, ensure_ascii=False, indent=1))

    def versions(self):
        if not self.root:
            return []
        return sorted(int(p.stem) for p in (self.root / 'checkpoints').glob('*.json') if p.stem.isdigit())

    def load(self, version):
        try:
            data = json.loads((self.root / 'checkpoints' / f'{version:04d}.json').read_text(encoding='utf-8'))
            return data if isinstance(data, dict) and data.get('version') == version else None
        except (OSError, ValueError, AttributeError):
            return None

    def latest(self):
        """Last checkpoint that still loads and passes structural validation."""
        for version in reversed(self.versions()):
            data = self.load(version)
            if data and not structural_errors(data):
                return data
        return None

    def archive(self, version, messages, pruned):
        if not self.root:
            return None
        path = self.root / 'archive' / f'{version:04d}.jsonl'
        lines = [json.dumps({'kind': 'message', 'index': i, 'message': m}, ensure_ascii=False) for i, m in messages]
        lines += [json.dumps({'kind': 'pruned', **p}, ensure_ascii=False) for p in pruned]
        self._atomic(path, '\n'.join(lines) + '\n')
        return str(path.relative_to(self.root))

    def keep_pruned(self, content):
        digest = hashlib.sha256(content.encode('utf-8', 'replace')).hexdigest()[:16]
        if self.root:
            target = self.root / 'pruned' / f'{digest}.txt'
            if not target.exists():
                self._atomic(target, content)
        return f'pruned/{digest}.txt'

    def commit(self, checkpoint):
        if not self.root:
            return
        path = self.root / 'checkpoints' / f"{checkpoint['version']:04d}.json"
        if path.exists():
            raise FileExistsError(f'checkpoint {checkpoint["version"]} already exists')
        self._atomic(path, json.dumps(checkpoint, ensure_ascii=False, indent=1))

    def search(self, query, limit=20):
        """Find archived original messages containing the query (case-insensitive)."""
        hits, needle = [], str(query).lower()
        if not self.root or not needle:
            return hits
        for path in sorted((self.root / 'archive').glob('*.jsonl')):
            for line in path.read_text(encoding='utf-8').splitlines():
                if needle in line.lower():
                    record = json.loads(line)
                    text = json.dumps(record.get('message') or record, ensure_ascii=False)
                    at = text.lower().find(needle)
                    hits.append({'archive': path.name, 'kind': record.get('kind'), 'index': record.get('index'),
                                 'excerpt': text[max(0, at - 160):at + 240]})
                    if len(hits) >= limit:
                        return hits
        for path in sorted((self.root / 'pruned').glob('*.txt')):
            text = path.read_text(encoding='utf-8', errors='replace')
            at = text.lower().find(needle)
            if at >= 0:
                hits.append({'archive': f'pruned/{path.name}', 'kind': 'pruned', 'index': None, 'excerpt': text[max(0, at - 160):at + 240]})
                if len(hits) >= limit:
                    break
        return hits

    def cleanup(self, cfg):
        """Version and size policy. Raw history is only deleted when explicitly enabled."""
        if not self.root:
            return {'deleted': []}
        deleted = []
        keep = int(cfg.get('keep_checkpoint_versions') or 0)
        if cfg.get('archive_delete_enabled'):
            versions = self.versions()
            if keep > 0:
                for version in versions[:-keep]:
                    for p in (self.root / 'checkpoints' / f'{version:04d}.json', self.root / 'archive' / f'{version:04d}.jsonl'):
                        if p.exists():
                            p.unlink()
                            deleted.append(str(p.relative_to(self.root)))
            limit = float(cfg.get('archive_max_mb') or 0) * 1024 * 1024
            archives = sorted((self.root / 'archive').glob('*.jsonl'))
            while limit and archives and sum(p.stat().st_size for p in archives) > limit and len(archives) > 1:
                victim = archives.pop(0)
                victim.unlink()
                deleted.append(str(victim.relative_to(self.root)))
        return {'deleted': deleted}


# ---------------------------------------------------------------- deterministic pruning

def _calls(messages):
    """tool_call_id -> (name, parsed arguments)."""
    out = {}
    for m in messages:
        for call in m.get('tool_calls') or []:
            fn = call.get('function') or {}
            try:
                args = json.loads(fn.get('arguments') or '{}')
            except (TypeError, ValueError):
                args = {}
            out[call.get('id')] = (fn.get('name') or '', args if isinstance(args, dict) else {})
    return out


def _round_starts(messages, start):
    return [i for i in range(start, len(messages)) if messages[i].get('role') == 'assistant']


def prune(messages, cfg, protected_until, keep_from, store=None):
    """Shrink old tool results by rule; returns (new messages, pruned records).

    Never touches messages before protected_until (system/task/checkpoint) or from keep_from
    on (recent rounds). Tool messages keep their role and tool_call_id, so call/result pairs
    stay intact; only the content becomes a short stub pointing at the archived original."""
    calls = _calls(messages)
    out = copy.deepcopy(messages)
    pruned = []
    later_reads, later_hashes = {}, {}
    for i in range(len(messages) - 1, -1, -1):
        m = messages[i]
        if m.get('role') != 'tool':
            continue
        name, args = calls.get(m.get('tool_call_id'), ('', {}))
        content = m.get('content') if isinstance(m.get('content'), str) else json.dumps(m.get('content'), ensure_ascii=False)
        digest = hashlib.sha256(content.encode('utf-8', 'replace')).hexdigest()
        reason = None
        if protected_until <= i < keep_from:
            path = args.get('path')
            if name == 'read_file' and path and path in later_reads:
                reason = 'superseded by a later read of the same file'
            elif digest in later_hashes:
                reason = 'identical to a later tool result'
            elif len(content) >= int(cfg['prune_min_result_chars']) and not _is_error(content):
                reason = 'large old tool output'
            elif len(content) >= int(cfg['prune_min_result_chars']) * 3:
                reason = 'very large old error output (head and tail kept)'
        if name == 'read_file' and args.get('path'):
            later_reads.setdefault(args['path'], i)
        later_hashes.setdefault(digest, i)
        if not reason:
            continue
        ref = store.keep_pruned(content) if store else None
        keep_text = content[:600] + ('\n...\n' + content[-400:] if 'error' in reason else '')
        stub = {'pruned': True, 'tool': name, 'path': args.get('path'), 'reason': reason, 'original_chars': len(content),
                'archive': ref, 'excerpt': keep_text[:1000],
                'note': 'Old output removed from context. Read the file again if you need its current content.'}
        out[i] = {**m, 'content': json.dumps(stub, ensure_ascii=False)}
        pruned.append({'index': i, 'tool_call_id': m.get('tool_call_id'), 'tool': name, 'path': args.get('path'),
                       'reason': reason, 'chars': len(content), 'archive': ref})
    return out, pruned


def _is_error(text):
    head = text[:400].lower()
    return '"success": false' in head or '"error":' in head or 'traceback' in head or 'exception' in head


# ---------------------------------------------------------------- checkpoint validation

class CheckpointError(ValueError):
    pass


def empty_checkpoint(goal=''):
    return {'schema_version': SCHEMA_VERSION, 'version': 0, 'goal': goal, 'current_task': '',
            **{f: [] for f in LIST_FIELDS}}


def structural_errors(data):
    errors = []
    if not isinstance(data, dict):
        return ['checkpoint is not an object']
    if data.get('schema_version') != SCHEMA_VERSION:
        errors.append('schema_version mismatch')
    for f in TEXT_FIELDS:
        if not isinstance(data.get(f), str):
            errors.append(f'{f} must be a string')
    for f in LIST_FIELDS:
        if not isinstance(data.get(f), list) or not all(isinstance(x, str) for x in data.get(f, [])):
            errors.append(f'{f} must be a list of strings')
    return errors


def extract_json(text):
    if not isinstance(text, str):
        raise CheckpointError('empty reply')
    text = re.sub(r'<think>.*?</think>', '', text, flags=re.S)
    fence = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.S)
    candidate = fence.group(1) if fence else text[text.find('{'):text.rfind('}') + 1] if '{' in text else ''
    try:
        data = json.loads(candidate)
    except ValueError as exc:
        raise CheckpointError(f'reply is not valid JSON: {exc}') from None
    if not isinstance(data, dict):
        raise CheckpointError('reply JSON is not an object')
    return data


def _strings(value):
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    out = []
    for item in value:
        if isinstance(item, (dict, list)):
            item = json.dumps(item, ensure_ascii=False)
        if item is not None and str(item).strip():
            out.append(str(item).strip()[:400])
    return out


def _dedupe(items):
    seen, out = set(), []
    for item in items:
        key = re.sub(r'\s+', ' ', item).strip().lower()
        if key and key not in seen:
            seen.add(key)
            out.append(item)
    return out


def finalize(candidate, prev, facts, cfg, meter, source):
    """Validate a model checkpoint and merge the harness facts into it by code.

    Returns (checkpoint, report). Raises CheckpointError when the result is unusable."""
    report = {'repaired': [], 'source': source}
    if not isinstance(candidate, dict):
        raise CheckpointError('checkpoint is not an object')
    cp = {'schema_version': SCHEMA_VERSION}
    for f in TEXT_FIELDS:
        cp[f] = str(candidate.get(f) or '').strip()[:600]
    for f in LIST_FIELDS:
        cp[f] = _strings(candidate.get(f))
    missing = [f for f in ('current_task', 'next_actions') if not cp[f]]
    if missing:
        raise CheckpointError(f'missing required content: {missing}')
    # Goal and constraints come from the harness, not from the summary.
    if cp['goal'] != facts['goal']:
        report['repaired'].append('goal')
    cp['goal'] = facts['goal']
    required = _dedupe(prev.get('constraints', []) + facts.get('constraints', []))
    lost = [c for c in required if c.lower() not in {x.lower() for x in cp['constraints']}]
    if lost:
        report['repaired'].append(f'constraints restored: {len(lost)}')
    cp['constraints'] = _dedupe(required + cp['constraints'])
    # Never forget history that later decisions depend on.
    for f in ('completed_tasks', 'decisions', 'failed_attempts'):
        prior = prev.get(f, [])
        dropped = [x for x in prior if x.lower() not in {y.lower() for y in cp[f]}]
        if dropped:
            report['repaired'].append(f'{f} carried over: {len(dropped)}')
        cp[f] = _dedupe(prior + cp[f])
    cp['modified_files'] = _dedupe(facts.get('modified_files', []) + prev.get('modified_files', []) + cp['modified_files'])
    if facts.get('test_status'):
        cp['test_status'] = facts['test_status']
    error = facts.get('latest_error')
    if error and not any(error[:80].lower() in e.lower() or e.lower() in error.lower() for e in cp['active_errors']):
        report['repaired'].append('unresolved error kept')
        cp['active_errors'] = [error] + cp['active_errors']
    cp['active_errors'] = _dedupe(cp['active_errors'])[:6]
    # Fit the size budget: oldest narrative items go first; goal/constraints/next actions stay.
    trimmed = 0
    while meter.text(cp) > int(cfg['summary_max_tokens']):
        for f in ('completed_tasks', 'failed_attempts', 'decisions', 'unknowns'):
            if len(cp[f]) > 3:
                cp[f] = cp[f][1:]
                trimmed += 1
                break
        else:
            raise CheckpointError(f'checkpoint exceeds {cfg["summary_max_tokens"]} tokens even after trimming')
    if trimmed:
        report['repaired'].append(f'trimmed oldest items: {trimmed}')
    errors = structural_errors(cp)
    if errors:
        raise CheckpointError('; '.join(errors))
    preserved = len(required) - len(lost)
    report['constraints_preserved_by_model'] = f'{preserved}/{len(required)}' if required else 'n/a'
    return cp, report


# ---------------------------------------------------------------- compaction

SYSTEM_PROMPT = """You maintain the working memory of a coding agent. Update the checkpoint with the NEW MESSAGES.
Rules:
1. Never invent facts. Only use the previous checkpoint, the harness facts and the new messages.
2. Keep every confirmed constraint and user requirement exactly; never change the user's request.
3. Copy file paths, function and component names exactly.
4. An error stays in active_errors until a later message shows it fixed (a passing check or a successful retry).
5. Record failed approaches in failed_attempts (what was tried and why it failed).
6. next_actions: concrete next steps (which file, what change, which check).
7. If old and new information conflict, the newer message wins; mention the conflict in unknowns.
8. Put anything uncertain in unknowns instead of stating it as fact.
9. Be brief: short items, no repetition. Target about {target} tokens.
Answer with JSON only, exactly these keys:
{{"goal": str, "current_task": str, "completed_tasks": [str], "decisions": [str], "constraints": [str],
"modified_files": [str], "active_errors": [str], "failed_attempts": [str], "test_status": [str],
"next_actions": [str], "unknowns": [str]}}"""


def _short(text, limit):
    text = text if isinstance(text, str) else json.dumps(text, ensure_ascii=False)
    return text if len(text) <= limit else text[:int(limit * 0.7)] + f' …[{len(text) - limit} chars]… ' + text[-int(limit * 0.3):]


def render(messages, offset=0):
    """Readable, bounded transcript of a message span for the compaction prompt."""
    calls = _calls(messages)
    items = []
    for i, m in enumerate(messages):
        role = m.get('role')
        if role == 'assistant':
            parts = []
            if m.get('content'):
                parts.append(_short(m['content'], 600))
            for call in m.get('tool_calls') or []:
                fn = call.get('function') or {}
                parts.append(f"CALL {fn.get('name')}({_short(fn.get('arguments') or '', 300)})")
            items.append(f'[{offset + i}] ASSISTANT: ' + ' | '.join(parts))
        elif role == 'tool':
            name, args = calls.get(m.get('tool_call_id'), ('tool', {}))
            label = f"{name}({args.get('path') or args.get('query') or ''})"
            items.append(f'[{offset + i}] RESULT {label}: ' + _short(m.get('content') or '', 900))
        else:
            items.append(f'[{offset + i}] {str(role).upper()}: ' + _short(m.get('content') or '', 1200))
    return items


class ContextManager:
    def __init__(self, runner, cfg=None):
        self.cfg = cfg or load_config()
        self.meter = TokenMeter(self.cfg)
        self.budget = Budget(self.cfg, self.meter)
        job = os.environ.get('HARNESS_JOB_DIR')
        self.store = Store(Path(job) / 'context' if job else None)
        self.runner = runner
        self.checkpoint = None
        self.failures = 0
        self.skip_below = 0
        state = self.store.state()
        self.stats = state.get('stats') or {'compactions': 0, 'prunes': 0, 'failures': 0, 'recoveries': 0,
                                            'fallbacks': 0, 'restores': 0}
        self.last = state.get('last_compaction')
        self._restore(runner)
        self._hook_calibration(runner)

    # --- integration helpers
    def _log(self, kind, data):
        try:
            self.runner.h.log_event(kind, data)
        except Exception:
            pass

    def _hook_calibration(self, runner):
        llm = getattr(getattr(runner, 'h', None), 'llm', None)
        import inspect
        if llm is None or getattr(llm, '_context_meter_hooked', False):
            return
        if not (inspect.ismethod(llm.chat) or inspect.isfunction(llm.chat)):
            return  # test doubles (Mock) keep their call records
        original = llm.chat
        meter = self.meter

        def chat(messages, tools=None, **kw):
            reply = original(messages, tools=tools, **kw)
            try:
                meter.observe(_chars(messages, tools), (reply.get('usage') or {}).get('prompt_tokens'))
                import context_budget
                if meter.ratio:
                    context_budget.CALIBRATED_CHARS_PER_TOKEN = meter.ratio / meter.margin
            except Exception:
                pass
            return reply
        llm.chat = chat
        llm._context_meter_hooked = True

    def _restore(self, runner):
        latest = self.store.latest()
        goal = str(getattr(getattr(runner, 'args', None), 'task', '') or '')
        if latest and latest.get('goal') == goal:
            self.checkpoint = latest
            self.stats['restores'] += 1
            self._pending_restore = True
            self._log('context.restored', {'version': latest['version'], 'created_at': latest.get('created_at')})
        else:
            self._pending_restore = False

    def facts(self):
        """What the harness knows for certain; merged into every checkpoint by code."""
        r = self.runner
        goal = str(getattr(getattr(r, 'args', None), 'task', '') or '')
        constraints = []
        approach = os.environ.get('HARNESS_TASK_APPROACH', '').strip()
        if approach:
            constraints.append('Planned direction: ' + approach[:300])
        gate = getattr(r, 'requirement_gate', None)
        frozen = getattr(gate, 'frozen_contract', None)
        if frozen:
            try:
                for c in json.loads(frozen).get('criteria', [])[:8]:
                    constraints.append(f"Completion check {c.get('id')}: {c.get('description', '')}"[:300])
            except (ValueError, AttributeError):
                pass
        modified = []
        try:
            modified = [p for p in json.loads(os.environ.get('HARNESS_CHANGED_PATHS', '[]')) if isinstance(p, str)]
        except ValueError:
            pass
        records = getattr(getattr(r, 'cp', None), '_records', None) or {}
        modified += [p for p in records if isinstance(p, str)]
        tests = []
        for mode, result in (getattr(r, 'last_check_results', None) or {}).items():
            ok = bool((result or {}).get('success'))
            tests.append(f"{mode}: {'passed' if ok else 'failed'}")
        feedback = getattr(r, 'feedback', '') or ''
        latest_error = ''
        if isinstance(feedback, str) and feedback.strip() and any(w in feedback.lower() for w in ('fail', 'error', 'mismatch', 'refused', '실패')):
            latest_error = feedback.strip()[:400]
        return {'goal': goal, 'constraints': _dedupe(constraints), 'modified_files': _dedupe(modified),
                'test_status': tests, 'latest_error': latest_error}

    # --- main entry
    def prepare(self, messages, tools):
        r = self.runner
        if self.checkpoint and len(messages) >= 2 and not self._has_checkpoint(messages):
            # A restarted runner, or the harness rebuilding its prompt (fresh()), must not lose the checkpoint.
            messages = messages[:2] + [self._checkpoint_message(self.checkpoint, messages[2:])] + messages[2:]
            r.messages = messages
            if self._pending_restore:
                self._pending_restore = False
            else:
                self._log('context.checkpoint_reinserted', {'version': self.checkpoint.get('version')})
        before = self.budget.usage(messages, tools)
        level = self.budget.level(before)
        self._status(before)
        if level == 'ok' or (level == 'soft' and before['input_tokens'] < self.skip_below):
            return messages
        if self.failures >= int(self.cfg['max_failed_compactions']) and level != 'hard':
            return messages
        with self.store.lock(wait_seconds=30 if level == 'hard' else 0) as acquired:
            if not acquired:
                self._log('context.compact_skipped', {'reason': 'another compaction holds the lock'})
                return messages
            started = time.monotonic()
            try:
                new = self._shrink(messages, tools, before, level)
            except Exception as exc:  # keep the valid state; never lose the run to a compaction bug
                self.failures += 1
                self.stats['failures'] += 1
                self.skip_below = before['input_tokens'] + 1500
                self._log('context.compact_failed', {'error': str(exc)[:400], 'level': level, 'usage': before})
                self._status(before, failure=str(exc)[:300])
                return messages
            after = self.budget.usage(new, tools)
            if new is not messages:
                r.messages = new
                self._log('autonomy.compact', {'before': self._legacy(before, messages), 'after': self._legacy(after, new),
                                               'reason': f'context management ({level})', 'removed_messages': max(0, len(messages) - len(new)),
                                               'retained_paths': sorted(getattr(r, 'read', set()) or []), 'model_calls': self._last_calls,
                                               'duration_ms': round((time.monotonic() - started) * 1000)})
            self._status(after)
            return new

    _last_calls = 0

    def _legacy(self, usage, messages):
        return {'estimated_input_tokens': usage['input_tokens'], 'reserved_output_tokens': usage['reserve_tokens'],
                'budget_tokens': usage['max_context_tokens'], 'pressure': usage['ratio'], 'message_count': len(messages),
                'remaining_tokens': max(0, usage['max_context_tokens'] - usage['input_tokens'] - usage['reserve_tokens'])}

    @staticmethod
    def _has_checkpoint(messages):
        return any(isinstance(m.get('content'), str) and m['content'].startswith(CHECKPOINT_MARK) for m in messages[:4])

    def _header_end(self, messages):
        end = min(2, len(messages))
        while end < len(messages) and isinstance(messages[end].get('content'), str) and messages[end]['content'].startswith(CHECKPOINT_MARK):
            end += 1
        return end

    def _tail_start(self, messages, header_end):
        """Earliest safe turn boundary whose suffix is about recent_messages_target_tokens.

        A boundary is an assistant or user message, so every tool result in the tail follows
        its own call; the latest assistant turn and its results are always kept whole."""
        target = int(self.cfg['recent_messages_target_tokens'])
        bounds = [i for i in range(header_end, len(messages)) if messages[i].get('role') in ('assistant', 'user')]
        if not bounds:
            return None
        for b in reversed(bounds):
            if self.meter.count(messages[b:]) >= target:
                return b
        return bounds[0]

    def _shrink(self, messages, tools, before, level):
        r = self.runner
        self._last_calls = 0
        started = time.monotonic()
        if messages and messages[-1].get('role') == 'assistant' and messages[-1].get('tool_calls'):
            raise RuntimeError('a tool call is still waiting for its result; not a safe point to compact')
        header_end = self._header_end(messages)
        tail = self._tail_start(messages, header_end)
        if tail is None:
            raise RuntimeError('no turn boundary to compact at')
        rounds = _round_starts(messages, header_end)
        keep_rounds = int(self.cfg['prune_keep_recent_rounds'])
        keep_from = rounds[-keep_rounds] if len(rounds) >= keep_rounds else header_end
        pruned_messages, pruned = prune(messages, self.cfg, header_end, keep_from, self.store)
        if pruned:
            self.stats['prunes'] += 1
            saved = before['input_tokens'] - self.budget.usage(pruned_messages, tools)['input_tokens']
            self._log('context.pruned', {'count': len(pruned), 'saved_tokens': saved,
                                         'items': [{k: p[k] for k in ('tool', 'path', 'reason', 'chars')} for p in pruned[:20]]})
            if self.budget.usage(pruned_messages, tools)['ratio'] < float(self.cfg['prune_only_target']):
                return pruned_messages
        if tail <= header_end:
            if pruned:
                return pruned_messages
            raise RuntimeError('recent messages alone fill the budget; nothing older to compact')
        span = list(range(header_end, tail))
        prev = self.checkpoint or empty_checkpoint(self.facts()['goal'])
        version = max([prev.get('version', 0)] + self.store.versions()) + 1
        archive = self.store.archive(version, [(i, messages[i]) for i in span], pruned) if self.cfg.get('archive_raw_history') else None
        facts = self.facts()
        checkpoint, report = self._compact(prev, facts, pruned_messages[header_end:tail], header_end, level)
        checkpoint.update(version=version, created_at=time.strftime('%Y-%m-%dT%H:%M:%S'), parent_version=prev.get('version', 0),
                          source_span={'from_index': header_end, 'to_index': tail - 1, 'messages': len(span), 'archive': archive})
        self.store.commit(checkpoint)
        self.checkpoint = checkpoint
        self.failures = 0
        self.skip_below = 0
        rebuilt = messages[:min(2, len(messages))] + [self._checkpoint_message(checkpoint, pruned_messages[tail:])] + pruned_messages[tail:]
        after = self.budget.usage(rebuilt, tools)
        if after['ratio'] >= float(self.cfg['hard_compact_threshold']):
            rebuilt = self._squeeze_tail(rebuilt, tools)
        self._sync_reads(rebuilt)
        self.stats['compactions'] += 1
        if report['source'] != 'llm':
            self.stats['fallbacks'] += 1
        self.last = {'time': checkpoint['created_at'], 'version': version, 'before_tokens': before['input_tokens'],
                     'after_tokens': self.budget.usage(rebuilt, tools)['input_tokens'], 'level': level,
                     'duration_ms': round((time.monotonic() - started) * 1000), **report}
        self._log('context.compacted', {**self.last, 'model_calls': self._last_calls, 'archive': archive,
                                        'checkpoint_tokens': self.meter.text(checkpoint)})
        self.store.cleanup(self.cfg)
        return rebuilt

    def _compact(self, prev, facts, span_messages, offset, level):
        """Fold the span into the checkpoint with the local model; fall back to code at the hard threshold."""
        errors = []
        if self.cfg.get('incremental_compaction', True):
            for chunk in self._chunks(prev, facts, span_messages, offset):
                checkpoint = None
                for attempt in range(int(self.cfg['llm_attempts'])):
                    try:
                        raw = self._ask_model(prev, facts, chunk, errors[-1] if errors else '')
                        checkpoint, report = finalize(extract_json(raw), prev, facts, self.cfg, self.meter, 'llm')
                        break
                    except Exception as exc:
                        errors.append(str(exc)[:300])
                        self.stats['failures'] += 1
                        self._log('context.compact_failed', {'error': errors[-1], 'attempt': attempt + 1, 'level': level})
                if checkpoint is None:
                    break
                prev = {**checkpoint, 'version': prev.get('version', 0)}
            else:
                if errors:
                    self.stats['recoveries'] += 1
                    report['recovered_after'] = len(errors)
                return prev, report
        if level != 'hard' and self.cfg.get('restore_on_failure', True):
            raise RuntimeError('model compaction failed; previous state kept: ' + ' | '.join(errors[-2:]))
        checkpoint, report = finalize(self._deterministic(prev, facts, span_messages), prev, facts, self.cfg, self.meter, 'deterministic_fallback')
        report['model_errors'] = errors[-2:]
        return checkpoint, report

    def _chunks(self, prev, facts, span_messages, offset):
        """Split a span the model cannot read in one prompt into sequential chunks."""
        items = render(span_messages, offset)
        overhead = self.meter.text(SYSTEM_PROMPT) + self.meter.text(prev) + self.meter.text(facts) + 400
        room = int(self.cfg['max_context_tokens']) - int(self.cfg['summary_output_tokens']) - overhead - 1024
        room = max(2000, room)
        chunk, used = [], 0
        for item in items:
            size = self.meter.text(item)
            if chunk and used + size > room:
                yield chunk
                chunk, used = [], 0
            chunk.append(item[: int(room * 3)])
            used += size
        if chunk:
            yield chunk

    def _ask_model(self, prev, facts, chunk, last_error):
        llm = self.runner.h.llm
        keep = {k: v for k, v in prev.items() if k in ('goal', 'current_task') + LIST_FIELDS}
        user = ('PREVIOUS CHECKPOINT:\n' + json.dumps(keep, ensure_ascii=False) +
                '\n\nHARNESS FACTS (authoritative):\n' + json.dumps(facts, ensure_ascii=False) +
                '\n\nNEW MESSAGES:\n' + '\n'.join(chunk) +
                ('\n\nYOUR PREVIOUS ANSWER WAS REJECTED: ' + last_error + '\nAnswer again with valid JSON only.' if last_error else '') +
                '\n\nReturn the updated checkpoint JSON.')
        messages = [{'role': 'system', 'content': SYSTEM_PROMPT.format(target=self.cfg['summary_target_tokens'])},
                    {'role': 'user', 'content': user}]
        saved = os.environ.get('LOCAL_LLM_MAX_TOKENS')
        os.environ['LOCAL_LLM_MAX_TOKENS'] = str(int(self.cfg['summary_output_tokens']))
        try:
            self._last_calls += 1
            reply = llm.chat(messages, tools=None)
        finally:
            if saved is None:
                os.environ.pop('LOCAL_LLM_MAX_TOKENS', None)
            else:
                os.environ['LOCAL_LLM_MAX_TOKENS'] = saved
        message = ((reply or {}).get('choices') or [{}])[0].get('message') or {}
        return message.get('content') or message.get('reasoning_content') or ''

    def _deterministic(self, prev, facts, span_messages):
        """Checkpoint built by code only (used when the model cannot produce a valid one)."""
        calls = _calls(span_messages)
        failed, done = [], []
        for m in span_messages:
            if m.get('role') != 'tool':
                continue
            name, args = calls.get(m.get('tool_call_id'), ('tool', {}))
            text = m.get('content') if isinstance(m.get('content'), str) else ''
            target = args.get('path') or args.get('query') or ''
            if _is_error(text):
                failed.append(f'{name} {target}: {text[:160]}')
            elif name in ('write_file', 'edit_file', 'apply_edits', 'apply_ast_edits'):
                done.append(f'{name} {target}')
        return {'goal': facts['goal'], 'current_task': prev.get('current_task') or facts['goal'],
                'completed_tasks': prev.get('completed_tasks', []) + done[-6:], 'decisions': prev.get('decisions', []),
                'constraints': prev.get('constraints', []), 'modified_files': facts.get('modified_files', []),
                'active_errors': ([facts['latest_error']] if facts.get('latest_error') else []) + prev.get('active_errors', []),
                'failed_attempts': prev.get('failed_attempts', []) + failed[-6:], 'test_status': facts.get('test_status', []),
                'next_actions': prev.get('next_actions') or ['Re-read the files you need from disk and continue the goal; check the latest results first.'],
                'unknowns': prev.get('unknowns', []) + ['This checkpoint was built without a model summary; details of older steps are only in the archive.']}

    def _checkpoint_message(self, checkpoint, tail):
        body = {k: checkpoint.get(k) for k in ('goal', 'current_task') + LIST_FIELDS if checkpoint.get(k)}
        read = sorted({a.get('path') for _, (n, a) in _calls(tail).items() if a.get('path')} if tail else set())
        earlier = sorted(set(getattr(self.runner, 'read', set()) or []) - set(read))
        refs = ('\nFiles read earlier (not in context now; read again from disk if needed): ' + ', '.join(earlier[:30])) if earlier else ''
        return {'role': 'user', 'content': (
            f"{CHECKPOINT_MARK} v{checkpoint.get('version')} — earlier steps of this run were compacted.\n"
            'The current files on disk and the latest check results are more reliable than this summary.\n'
            + json.dumps(body, ensure_ascii=False, indent=0) + refs +
            '\nContinue with next_actions.')}

    def _squeeze_tail(self, messages, tools):
        """Emergency: shorten large tool results inside the recent tail (never the newest one)."""
        out = copy.deepcopy(messages)
        tool_idx = [i for i, m in enumerate(out) if m.get('role') == 'tool']
        for i in tool_idx[:-1]:
            content = out[i].get('content') or ''
            if isinstance(content, str) and len(content) > 4000:
                out[i]['content'] = _short(content, 2500)
            if self.budget.usage(out, tools)['ratio'] < float(self.cfg['soft_compact_threshold']):
                break
        return out

    def _sync_reads(self, messages):
        """Files whose content left the prompt may be read again (reset read guards for them)."""
        r = self.runner
        present = {a.get('path') for _, (n, a) in _calls(messages).items() if n == 'read_file' and a.get('path')}
        counts = r.__dict__.get('_read_counts')
        if isinstance(counts, dict):
            for key in [k for k in counts if isinstance(k, tuple) and k[0] not in present]:
                counts.pop(key, None)
        if hasattr(r, 'read'):
            try:
                from source_progress import sync_read_context
                sync_read_context(r, set(getattr(r, 'read', set())) & present)
            except Exception:
                r.read = set(getattr(r, 'read', set())) & present

    def _status(self, usage, failure=None):
        state = {'updated_at': time.strftime('%Y-%m-%dT%H:%M:%S'), 'enabled': True, 'usage': usage,
                 'thresholds': {'soft': self.cfg['soft_compact_threshold'], 'hard': self.cfg['hard_compact_threshold'],
                                'prune_only_target': self.cfg['prune_only_target']},
                 'stats': self.stats, 'last_compaction': self.last,
                 'checkpoint_version': (self.checkpoint or {}).get('version', 0),
                 'last_failure': failure, 'chars_per_token': self.meter.ratio}
        try:
            self.store.save_state(state)
        except OSError:
            pass


def manager(runner):
    """The runner's context manager, or None when context management is disabled."""
    if not enabled():
        return None
    current = runner.__dict__.get('_context_manager')
    if current is None:
        current = runner.__dict__['_context_manager'] = ContextManager(runner)
    return current


if __name__ == '__main__':  # python3 context_manager.py <job dir> status|search <query>|cleanup
    import sys
    store = Store(Path(sys.argv[1]) / 'context')
    command = sys.argv[2] if len(sys.argv) > 2 else 'status'
    if command == 'search':
        print(json.dumps(store.search(' '.join(sys.argv[3:])), ensure_ascii=False, indent=1))
    elif command == 'cleanup':
        print(json.dumps(store.cleanup(load_config()), ensure_ascii=False))
    else:
        print(json.dumps({**store.state(), 'versions': store.versions()}, ensure_ascii=False, indent=1))
