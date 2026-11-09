"""Replay recorded read requests using real source; no model, build, or DB calls."""
import argparse
import hashlib
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
from task_sources import resolve_task_sources


def replay(job_id):
    if not job_id.isalnum():
        raise ValueError('Expected a job ID')
    folder = ROOT / 'platform/state' / job_id
    request = json.loads((folder / 'request.json').read_text())
    rows = [json.loads(line) for line in (folder / 'events.jsonl').read_text().splitlines()]
    responses = [event['data'] for event in rows if event['type'] == 'model.response'][:3]
    if len(responses) != 3 or any(call['function']['name'] != 'read_file'
                                for response in responses for call in response['tool_calls']):
        raise ValueError('Replay requires the first three responses to be read-only')
    task = request['goal']
    app = ROOT / 'local-only'
    sources = {str(path.relative_to(app)): path.read_bytes()
               for base in ('frontend/src', 'backend/src')
               for path in (app / base).rglob('*') if path.is_file() and not path.is_symlink()}
    rag_chars = next(event['data']['context_chars'] for event in rows
                     if event['type'] == 'autonomy.component_retrieval')
    args = SimpleNamespace(task=task, workspace=str(app), check='|'.join(request['checks']),
        context_profile='focused', max_rounds=4, ponytail='off', llm_url='http://127.0.0.1:1/v1', model='offline-replay')
    gate = SimpleNamespace(enabled=False, prepare=lambda: None,
                           context=lambda: 'Frozen query acceptance still required; replay is not a completion proof')
    with patch('completion_runner.Gate', return_value=gate):
        runner = Runner(args, native.Harness)
    events, sent, schemas = [], [], []
    runner.h.log_event = lambda kind, data: events.append((kind, data))
    runner.h.checker.run_check = lambda mode: {'success': True, 'stdout': '', 'stderr': ''}
    scripted = [{'choices': [{'message': {'role': 'assistant', 'content': response.get('text'),
                                         'tool_calls': response['tool_calls']}}]} for response in responses]
    scripted.append(reply_text('offline replay finished'))

    def chat(messages, tools=None):
        sent.append(json.loads(json.dumps(messages)))
        schemas.append(json.dumps(tools, sort_keys=True))
        return scripted.pop(0)

    def rag(current):
        current._component_recipe = None
        label = 'RECORDED RAG SIZE FIXTURE\n'
        return label + 'r' * (rag_chars - len(label))

    runner.h.llm.chat = chat
    with patch('component_catalog.context_for_task', side_effect=rag), \
            patch.dict(os.environ, {'LOCAL_LLM_MAX_TOKENS': '8192'}):
        assert runner.run() is False
    assert len(sent) == 4
    targets = resolve_task_sources(app, task)
    assert len(targets) == 1
    target = targets[0]
    target_source = sources[target].decode()
    for packet in sent:
        body = text_content(packet)
        assert target_source in body and target in body
        assert 'CURRENT AST EDIT SCOPES' in body
        assert body.count(task) == 1
    assert len(set(schemas)) == 1
    assert all(measure(packet, json.loads(schemas[index]), reserved=8192)['pressure'] <= 1
               for index, packet in enumerate(sent))
    assert all((app / path).read_bytes() == raw for path, raw in sources.items())
    compacts = [data for kind, data in events if kind == 'autonomy.compact']
    assert all(data['after']['estimated_input_tokens'] < data['before']['estimated_input_tokens'] for data in compacts)
    assert target in runner.read
    service = runner.h._code_intelligence
    assert all(path in runner.read for path in service.read_hashes)
    return {'job': job_id, 'method': 'Actual first three recorded read requests replayed against real sources; model/checks mocked; fixed-size RAG fixture',
            'rag_fixture_chars': rag_chars, 'input_metric': 'character-based estimate, not tokenizer usage',
            'request_estimates': [measure(packet, json.loads(schemas[index]), reserved=8192)['estimated_input_tokens']
                                  for index, packet in enumerate(sent)],
            'prefix_preserved': [packet[:len(previous)] == previous for previous, packet in zip(sent, sent[1:])],
            'compacts': [{'before': data['before']['estimated_input_tokens'], 'after': data['after']['estimated_input_tokens']}
                         for data in compacts],
            'resolved_targets': targets, 'target_sha256': hashlib.sha256(sources[target]).hexdigest(),
            'target_present_in_all_packets': True, 'target_whole_source_counts': [text_content(packet).count(target_source) for packet in sent],
            'tool_schema_variants': len(set(schemas)), 'retained_read_paths': sorted(runner.read),
            'app_source_unchanged': True, 'real_model_calls': 0, 'real_checks': 0}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('job_id')
    parser.add_argument('--output', type=Path)
    options = parser.parse_args()
    report = replay(options.job_id)
    if options.output:
        if options.output.resolve().is_relative_to(ROOT / 'local-only'):
            raise ValueError('Evidence must remain outside the application workspace')
        options.output.parent.mkdir(parents=True, exist_ok=True)
        options.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(report, ensure_ascii=False, indent=2))
