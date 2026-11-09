"""Offline recorded-read replay. No model calls, builds, or application writes."""
import argparse
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import patch

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'platform/tests'))
from test_autonomy import native, reply_text
from test_focused_source_once import text_content
from autonomy_runtime import Runner
from context_budget import measure


def replay(job_id):
    if not job_id.isalnum():
        raise ValueError('Expected a job ID')
    rows = [json.loads(line) for line in (ROOT / 'platform/state' / job_id / 'events.jsonl').read_text().splitlines()]
    responses = [event['data'] for event in rows if event['type'] == 'model.response'][:3]
    if len(responses) != 3 or any(call['function']['name'] != 'read_file' for response in responses for call in response['tool_calls']):
        raise ValueError('Replay accepts exactly three recorded read-only model responses')
    task = next(event['data']['goal'] for event in rows if event['type'] == 'run.started')
    paths = [json.loads(call['function']['arguments'])['path'] for response in responses for call in response['tool_calls']]
    raw = {path: (ROOT / 'local-only' / path).read_bytes() for path in paths}
    rag_chars = next(event['data']['context_chars'] for event in rows if event['type'] == 'autonomy.component_retrieval')
    args = SimpleNamespace(task=task, workspace=str(ROOT / 'local-only'), check='frontend|framework',
        context_profile='focused', max_rounds=4, ponytail='off', llm_url='http://127.0.0.1:1/v1', model='offline-replay')
    gate = SimpleNamespace(enabled=False, prepare=lambda: None, context=lambda: 'Frozen layout acceptance remains required')
    with patch('completion_runner.Gate', return_value=gate):
        runner = Runner(args, native.Harness)
    events, sent, schemas = [], [], []
    runner.h.log_event = lambda kind, data: events.append((kind, data))
    runner.h.checker.run_check = lambda mode: {'success': True, 'stdout': '', 'stderr': ''}
    scripted = [{'choices': [{'message': {'role': 'assistant', 'content': response.get('text'),
                                         'tool_calls': response['tool_calls']}}]} for response in responses]
    scripted.append(reply_text('offline replay done'))

    def chat(messages, tools=None):
        sent.append(json.loads(json.dumps(messages)))
        schemas.append(json.dumps(tools, sort_keys=True))
        return scripted.pop(0)

    def rag(current):
        # Preserve the original new-screen recipe routing without querying RAG.
        current._component_recipe = {'files': [{'path': 'frontend/src/framework/BusinessWorkspace.tsx'}]}
        label = 'RECORDED RAG SIZE FIXTURE\n'
        return label + 'r' * (rag_chars - len(label))

    runner.h.llm.chat = chat
    with patch('component_catalog.context_for_task', side_effect=rag), \
            patch.dict(os.environ, {'LOCAL_LLM_MAX_TOKENS': '8192'}), \
            patch('ast_editing.editor', side_effect=AssertionError('Reference source selected for AST edit')):
        assert runner.run() is False
    assert len(sent) == 4
    context = text_content(sent[3])
    counts = {path: context.count(source.decode()) for path, source in raw.items()}
    assert max(counts.values()) <= 1
    assert all(counts[path] == 1 for path in paths[len(responses[0]['tool_calls']):])
    assert context.count(task) == 1
    assert 'CURRENT AST EDIT SCOPES' not in context
    assert len(set(schemas)) == 1
    assert all((ROOT / 'local-only' / path).read_bytes() == source for path, source in raw.items())
    assert all(path in runner.read or path not in runner.h._code_intelligence.read_hashes for path in paths)
    compacts = [data for kind, data in events if kind == 'autonomy.compact']
    return {'job': job_id, 'method': 'Actual recorded read replies and real app read-only; mocked model/checks, fixed-size RAG fixture',
        'rag_fixture_chars': rag_chars, 'input_metric': 'character-based estimate, not tokenizer usage',
        'request_estimates': [measure(messages, json.loads(schemas[index]), reserved=8192)['estimated_input_tokens'] for index, messages in enumerate(sent)],
        'compacts': [{'before': data['before']['estimated_input_tokens'], 'after': data['after']['estimated_input_tokens'],
                      'removed_messages': data['removed_messages']} for data in compacts],
        'fourth_source_counts': counts, 'retained_read_paths': sorted(runner.read), 'task_occurrences': context.count(task),
        'ast_reference_present': False, 'tool_schema_variants': len(set(schemas)), 'app_source_unchanged': True,
        'real_model_calls': 0, 'real_checks': 0}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('job_id')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    report = json.dumps(replay(args.job_id), ensure_ascii=False, indent=2)
    if args.output:
        if args.output.resolve().is_relative_to(ROOT / 'local-only'):
            raise ValueError('Replay evidence must remain outside the application workspace')
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(report + '\n')
    print(report)
