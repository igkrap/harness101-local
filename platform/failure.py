"""Describe recorded termination and diagnostics without generating an explanation."""
import re


def diagnostic(event):
    if not event: return None
    data=event.get('data') or {}
    message=str(data.get('error') or data.get('reason') or '')
    if event.get('type') in ('verification.finished','autonomy.stage_verified'):
        message='\n'.join(f"{item.get('id')}: {item.get('reason') or item.get('status')}" for item in data.get('results',[]) if item.get('status') != 'passed')
    if not message: message='\n'.join(str(data.get(k) or '') for k in ('stdout','stderr'))
    message=re.sub(r'\x1b\[[0-9;]*m','',message)
    lines=[line.strip() for line in message.splitlines() if line.strip() and 'Error message = null' not in line and ' WARN ' not in line]
    errors=[line for line in lines if re.search(r'error TS\d+:|\[ERROR\]|AssertionError|Exception:|expected[:<]|^ERROR\b|^Error:',line)]
    selected=errors or lines
    unique=list(dict.fromkeys(selected))
    mode=data.get('mode')
    if not mode:
        match=re.search(r'\[(frontend|framework|backend|harness)\]',message)
        if match: mode=match.group(1)
    paths=data.get('paths') if isinstance(data.get('paths'),list) else []
    return {'seq':event.get('seq'),'time':event.get('time'),'type':event.get('type'),'mode':mode,
            'tool':data.get('name'),'path':data.get('path') or (paths[0] if paths else None),
            'message':'\n'.join(unique[:8])[:2200] or '오류 메시지가 기록되지 않았습니다.'}


def describe_failure(job, event, counts, plan=None, accepted=None, strategy=None):
    failure=diagnostic(event)
    later_verified=bool(event and accepted and accepted.get('seq',0)>event.get('seq',0))
    used=counts.get('model.request',0)
    limit=job.get('rounds')
    status=job.get('status')
    fatal=event and event.get('type') in ('run.error','autonomy.error','autonomy.conflict','model.error') and not later_verified
    if status=='stopped': reason,code='사용자가 중지했습니다.','stopped'
    elif status=='interrupted': reason,code=job.get('detail') or '프로세스 종료 상태를 확인하지 못했습니다.','interrupted'
    elif fatal: reason,code='실행 중 오류가 발생했습니다.','error'
    elif status=='failed' and job.get('kind')=='agent' and isinstance(limit,int) and limit>0 and used>=limit:
        reason,code=f'모델 호출 한도 {limit}회에 도달했습니다.','round_limit'
    elif status=='failed' and failure and not later_verified: reason,code='검사 또는 도구 실행이 실패했습니다.','error'
    elif status=='failed': reason,code='완료 조건을 충족하지 못하고 종료됐습니다.','incomplete'
    else: reason,code='','none'
    steps=(plan or {}).get('data',{}).get('steps')
    strategy_data=(strategy or {}).get('data') or {}
    completed=counts.get('autonomy.step_finished',0)
    if isinstance(strategy_data.get('completed_stage_ids'),list):
        completed=len(set(strategy_data['completed_stage_ids']))+int(strategy_data.get('phase')=='success')
    return {'job':job,'reason':reason,'code':code,'used':used,'limit':limit,
            'completed_steps':completed,'total_steps':len(steps) if isinstance(steps,list) else None,
            'failure':failure,'later_verified':later_verified,'exit_code':job.get('exit_code')}
