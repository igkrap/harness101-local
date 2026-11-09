"""Context telemetry from indexed events; never read prompts or infer missing budgets."""
def context_report(history, job):
    key=job['id']
    request=history.last_event(key,'model.request')
    response=history.last_event(key,'model.response')
    error=history.last_event(key,'model.error')
    compact=history.last_event(key,'autonomy.compact')
    analysis=history.last_event(key,'autonomy.analysis')
    counts=history.counts(key)
    current=None
    if request:
        data=request.get('data') or {}
        current={'seq':request['seq'],'time':request.get('time'),'model':data.get('model'),
                 'estimated_input_tokens':data.get('estimated_input_tokens'),
                 'context':data.get('context') if isinstance(data.get('context'),dict) else None}
    last_response=None
    if response:
        data=response.get('data')or{}
        last_response={'seq':response['seq'],'time':response.get('time'),'usage':data.get('usage'),
                       'duration_ms':data.get('duration_ms'),'finish_reason':data.get('finish_reason')}
    finished_seq=max((response or {}).get('seq',0),(error or {}).get('seq',0))
    return {'job':{'id':key,'status':job.get('status')},'current':current,'confirmed':last_response,
            'waiting':job.get('status')=='running' and bool(request) and request['seq']>finished_seq,
            'compaction':{'seq':compact['seq'],'time':compact.get('time'),**(compact.get('data')or{})} if compact else None,
            'files':(analysis.get('data')or{}).get('paths',[]) if analysis else [],
            'counts':{'requests':counts.get('model.request',0),'compactions':counts.get('autonomy.compact',0)}}
