"""Read the latest decomposition through indexed offsets, independent of journal size."""
def strategy_report(history, job):
    plan = history.last_event(job['id'], 'autonomy.plan') or {}
    data = plan.get('data') or {}
    if data.get('source') != 'divide-and-conquer':
        return {'recorded': False, 'stages': [], 'state': None}
    state_event = history.last_event(job['id'], 'autonomy.strategy_state') or {}
    state = state_event.get('data') or {}
    if state_event.get('seq', 0) < plan.get('seq', 0):
        state = {}
    return {'recorded': True, 'stages': data.get('steps', []), 'state': state,
            'time': state_event.get('time'), 'job_status': job.get('status')}
