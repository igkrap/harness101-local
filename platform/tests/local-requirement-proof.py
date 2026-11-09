"""Opt-in check of contract extraction by the configured local Gemma 26B model."""
import importlib.util
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'local-only/harness'))
from autonomy_runtime import Runner


def main():
    spec=importlib.util.spec_from_file_location('contract_proof_native',ROOT/'local-only/harness/harness.py')
    native=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(native)
    task='좌측 넓게, 우측 좁게\n좌측 상단에 조회 조건과 조회 버튼\n좌측 하단에 조회 결과 그리드\n우측에 신규 등록 및 수정 패널'
    args=SimpleNamespace(task=task,workspace=str(ROOT/'local-only'),check='frontend',max_rounds=8,
                         ponytail='off',llm_url='http://127.0.0.1:8099/v1',model='mlx-community/gemma-4-26B-A4B-it-OptiQ-4bit')
    output=ROOT/'platform/state/evidence/local-requirement-proof'
    output.mkdir(parents=True,exist_ok=True)
    runner=Runner(args,native.Harness)
    runner.h.evidence_path=output/'events.jsonl'
    original_ask=runner.ask
    replies=[]
    def ask(messages,tools):
        result=original_ask(messages,tools)
        replies.append({'messages':messages,'reply':result})
        (output/'model-replies.json').write_text(json.dumps(replies,ensure_ascii=False,indent=2))
        return result
    runner.ask=ask
    os.environ['HARNESS_PREVIEW_URL']='http://127.0.0.1:5292'
    os.environ['HARNESS_API_URL']='http://127.0.0.1:5292'
    try:
        runner.requirement_gate.prepare()
        contract=json.loads(runner.requirement_gate.frozen_contract)
        assert contract['task']==task
        assert len(contract['requirements'])==4
        report=runner.requirement_gate.verify()
        assert report['success'] is False, 'An unchanged application must not be marked as completed work'
        (output/'result.json').write_text(json.dumps({'model':args.model,'contract':contract,'report':report,'source_changes':False},ensure_ascii=False,indent=2))
        print(f"PASS: local 26B generated {len(contract['criteria'])} criteria for all four request clauses; unchanged work rejected")
    except Exception as error:
        (output/'result.json').write_text(json.dumps({'model':args.model,'success':False,'stage':'contract_or_verification','error':str(error),'source_changes':False},ensure_ascii=False,indent=2))
        raise
    finally:
        service=getattr(runner.h,'_code_intelligence',None)
        if service:service.close()


if __name__=='__main__':main()
