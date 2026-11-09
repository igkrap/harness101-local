import json
import pathlib
from divide_stage import run_stage

def repair_target(parent, stages, failed_ids):
    """Route suite failures by domain even when no goal criterion owns that suite."""
    failed_modes = [m for m, result in getattr(parent, 'last_check_results', {}).items()
                    if result.get('success') is not True]
    if failed_modes:
        domain = 'backend' if failed_modes[0] == 'backend' else 'frontend'
        for i, stage in enumerate(stages):
            if stage['domain'] == domain:
                return i
        root = parent.h.workspace.root
        prefix = domain + '/src/'
        files = sorted(str(p.relative_to(root)) for p in (root / prefix).rglob('*')
                       if p.is_file() and not p.is_symlink())
        paths = [p for p in files if '/test/' not in p][:12]
        if not paths:
            raise RuntimeError(f'Cannot route failed {domain} checks: no source files')
        stages.append({'id': 'repair_' + domain + '_checks',
            'title': f'{domain} 검사 실패 복구', 'domain': domain,
            'instructions': '원래 요청의 전체 완료를 막는 기존 검사 실패를 수정합니다. '
                            '실제 진단과 기존 테스트를 읽고 구현을 수정하세요. 테스트를 약화하거나 삭제하지 마세요.',
            'criterion_ids': [], 'paths': paths,
            'references': [p for p in files if '/test/' in p][:12],
            'depends_on': [s['id'] for s in stages], 'source': 'failed-selected-checks'})
        parent.steps = stages + [{'id': 'integration', 'title': '전체 결과 검증', 'kind': 'verify'}]
        parent.h.log_event('autonomy.repair_stage_added', stages[-1])
        return len(stages) - 1
    for i, stage in enumerate(stages):
        if set(stage.get('criterion_ids', [])) & set(failed_ids):
            return i
    return len(stages) - 1

def execute(parent, base, harness_class, stages) -> bool:
    """
    Executes a sequence of stages and an integration verification step.
    Supports repair loops based on requirement gate reports.
    """
    packets = {}
    index = 0
    repair_feedback = ''
    parent.division_accepted = False
    original_modes = list(parent.modes)

    def publish(phase: str):
        state = {
            'completed_stage_ids': list(packets.keys()),
            'active_stage_id': stages[index]['id'] if index < len(stages) else 'integration',
            'phase': phase
        }
        parent.h.log_event('autonomy.strategy_state', state)
        parent.requirement_gate.artifact_dir.mkdir(parents=True, exist_ok=True)
        with open(parent.requirement_gate.artifact_dir / 'division-state.json', 'w', encoding='utf-8') as f:
            json.dump({**state, 'stages': stages, 'completed_packets': packets, 'active_index': index}, 
                      f, ensure_ascii=False, indent=2)

    while True:
        if index < len(stages):
            stage = stages[index]
            parent.step = index
            publish('running')
            parent.h.log_event('autonomy.stage_started', {**stage, 'stage_id': stage['id'], 'index': index + 1, 'scope': 'stage'})
            
            ok, proof = run_stage(parent, base, harness_class, stage, index, packets, repair_feedback)
            
            if not ok:
                publish('failed')
                parent.h.log_event('autonomy.stage_failed', {'stage_id': stage['id'], 'success': False, 'reason': parent.feedback})
                return False
            
            packets[stage['id']] = proof
            parent.h.log_event('autonomy.handoff', proof)
            parent.h.log_event('autonomy.step_finished', {'step': index + 1, 'title': stage['title'], 'stage_id': stage['id'], 'scope': 'stage'})
            index += 1
            repair_feedback = ''
            continue
        else:
            # Integration Phase
            parent.step = len(stages)
            parent.modes = original_modes
            publish('integration')
            parent.h.log_event('autonomy.stage_started', {'stage_id': 'integration', 'index': len(stages) + 1, 'title': '전체 결과 검증', 'scope': 'goal'})
            
            checks_ok, diag = parent.verify()
            parent.accepted = parent.division_accepted
            
            if checks_ok:
                report = parent.requirement_gate.verify()
            else:
                report = {'success': False, 'results': [], 'error': diag}

            if report.get('success') is True:
                publish('success')
                parent.h.log_event('autonomy.step_finished', {'step': len(stages) + 1, 'title': '전체 결과 검증', 'stage_id': 'integration', 'scope': 'goal'})
                return True

            # Check if blocked by system mutation failure
            if any(r.get('id') == 'system:mutation' and r.get('status') != 'passed' for r in report.get('results', [])) and (not parent.division_accepted or not report.get('changed_paths')):
                publish('failed')
                parent.h.log_event('autonomy.blocked', {'reason': 'No verified changes; cannot claim change completion'})
                return False

            # Determine repair target
            failed_ids = [r['id'] for r in report.get('results', []) if r.get('status') != 'passed' and not r['id'].startswith('system:')]
            
            # Find first stage that covers any failed criterion
            target = repair_target(parent, stages, failed_ids)
            
            repair_feedback = json.dumps({k: v for k, v in report.items() if k not in ('layout', 'screenshot')}, ensure_ascii=False)
            parent.feedback = repair_feedback
            
            parent.h.log_event('autonomy.integration_failed', {
                'success': False, 
                'failed_criterion_ids': failed_ids, 
                'repair_stage_id': stages[target]['id'], 
                'reason': repair_feedback
            })

            # Reset from target onwards
            
            
            # Precise removal: remove packets for EVERY stage in stages[target:]
            stages_to_remove = [s['id'] for s in stages[target:]]
            for sid in stages_to_remove:
                packets.pop(sid, None)
            
            index = target
            publish('running')
