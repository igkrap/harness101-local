"""Manual, real local-model proof against a disposable frontend fixture."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
HARNESS = ROOT / 'local-only/harness'
sys.path.insert(0, str(HARNESS))
spec = importlib.util.spec_from_file_location('ast_live_native', HARNESS / 'harness.py')
native = importlib.util.module_from_spec(spec)
spec.loader.exec_module(native)
from autonomy_runtime import Runner
from ast_proposal import prepare, normalize, tool_call

os.environ['LOCAL_LLM_MAX_TOKENS'] = '700'
model = 'mlx-community/gemma-4-26B-A4B-it-OptiQ-4bit'
with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    relative = 'frontend/src/screens/Demo.tsx'
    file = root / relative
    file.parent.mkdir(parents=True)
    source = (
        '// 😀 unrelated bytes must survive\r\n'
        'export const Table = ({data}: {data:string[]}) => <table><tbody>{data.map(x=><tr key={x}><td>{x}</td></tr>)}</tbody></table>;\r\n'
        'export const meta = {title:"등록"};\r\n'
        'export default function Demo(){return <form><h1>원래 제목</h1><button type="submit">등록</button></form>;}\r\n'
        'export function Unrelated(){return <aside>keep exactly</aside>;}\r\n'
    )
    file.write_bytes(source.encode())
    args = SimpleNamespace(task="Demo 제목을 '조회 결과'로 바꾸고 기존 form 마지막 자식에 <Table data={['row']}/> 추가. 다른 코드는 그대로 유지.", workspace=str(root), check='frontend', max_rounds=0, ponytail='off', llm_url='http://127.0.0.1:8099/v1', model=model)
    runner = Runner(args, native.Harness)
    runner.h.evidence_path = root / 'test-events.jsonl'
    real_evidence = ROOT / 'platform/state/evidence/ast-local-model-proof.json'
    replay = os.environ.get('AST_PROOF_REPLAY') == '1'
    evidence = real_evidence.with_name('ast-local-model-replay.json') if replay else real_evidence
    report = {'model': model, 'source_before': source}
    prior_file = ROOT / 'platform/state/evidence/ast-local-initial-rejection.json'
    if prior_file.exists():
        prior = json.loads(prior_file.read_text())
        if prior.get('source_before') == source and not prior.get('success'):
            content = prior['response']['choices'][0]['message'].get('content') or ''
            rejected, _ = json.JSONDecoder().raw_decode(content[content.index('{'):])
            runner.feedback = prior['error'] + '\nRejected AST fragments (NOT current source):\n' + json.dumps(rejected['edits'], ensure_ascii=False)
            report['previous_rejection'] = str(prior_file)
    try:
        system, user, mode = prepare(runner, 'Project: Preserve all unrelated code.', '', source, relative, '', 'Table already exists. Add no imports.', '')
        if replay:
            saved = json.loads(real_evidence.read_text())
            assert saved['success'] and saved['source_before'] == source
            response = saved['response']
        else:
            response = runner.h.llm.chat([{'role': 'system', 'content': system}, {'role': 'user', 'content': user}], tools=[])
        text = response['choices'][0]['message'].get('content') or ''
        report.update(request={'system': system, 'user': user}, response=response)
        normalize(text, source, mode)
        tool = tool_call(mode, relative, [], 1)
        operations = json.loads(tool['arguments'])
        assert all(set(edit) == {'node_id', 'code'} for edit in operations['edits'])
        result = runner.apply(tool['name'], operations, {})
        assert not result.get('error'), result
        actual = file.read_bytes().decode()
        assert '<h1>조회 결과</h1>' in actual
        assert actual.count('<Table ') == 1
        assert '<button type="submit">등록</button>' in actual
        assert source.splitlines(keepends=True)[0] == actual.splitlines(keepends=True)[0]
        assert source.splitlines(keepends=True)[-1] == actual.splitlines(keepends=True)[-1]
        assert source.splitlines(keepends=True)[1] == actual.splitlines(keepends=True)[1]
        report.update(success=True, source_after=actual, model_calls=0 if replay else 1, replay_of=str(real_evidence) if replay else None, edits=operations['edits'])
        runner.cp.commit()
        print('AST_REPLAY_OK' if replay else 'AST_LOCAL_OK', ': node fragments only, existing form and unrelated bytes preserved')
    except Exception as error:
        report.update(success=False, error=str(error))
        raise
    finally:
        runner.cp.rollback()
        if getattr(runner.h, '_ast_editor', None):
            runner.h._ast_editor.service.close()
        evidence.write_text(json.dumps(report, ensure_ascii=False, indent=2))
