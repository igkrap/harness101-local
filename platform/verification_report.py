"""Read the contract and most recent gate result through indexed journal offsets."""
def completion_evidence(events, goal):
    contract_event = events.get('requirement.contract') or {}
    report_event = events.get('verification.finished') or {}
    accepted_event = events.get('autonomy.accepted') or {}
    contract_data = contract_event.get('data') or {}
    report = report_event.get('data') or {}
    contract = contract_data.get('contract') or {}
    if contract.get('task') != goal or not contract_data.get('contract_hash'):
        return False, '요청과 일치하는 완료 조건 계약이 없습니다.'
    if report.get('contract_hash') != contract_data['contract_hash'] or report.get('success') is not True:
        return False, '완료 조건을 모두 확인한 검사 결과가 없습니다.'
    criteria = contract.get('criteria')
    results = report.get('results')
    if not isinstance(criteria, list) or not criteria or not isinstance(results, list):
        return False, '완료 조건 또는 관측값이 비어 있습니다.'
    expected = [c.get('id') for c in criteria if isinstance(c, dict)]
    actual = [r.get('id') for r in results if isinstance(r, dict) and not str(r.get('id', '')).startswith('system:')]
    if any(not isinstance(key, str) or not key for key in expected + actual):
        return False, '검사 항목 식별자가 올바르지 않습니다.'
    if len(expected) != len(criteria) or len(expected) != len(set(expected)) or sorted(expected) != sorted(actual):
        return False, '완료 조건과 검사 항목이 일치하지 않습니다.'
    if any(not isinstance(r, dict) or r.get('status') != 'passed' for r in results):
        return False, '실패하거나 미확인인 완료 조건이 있습니다.'
    if not accepted_event or accepted_event.get('seq', 0) >= report_event.get('seq', 0):
        return False, '마지막 코드 변경 이후의 완료 검사가 없습니다.'
    return True, ''


def verification_report(history, job):
    contract_event = history.last_event(job['id'], 'requirement.contract')
    result_event = history.last_event(job['id'], 'verification.finished')
    contract = (contract_event or {}).get('data') or {}
    result = (result_event or {}).get('data') or {}
    expected_hash = contract.get('contract_hash')
    matching = bool(expected_hash and result.get('contract_hash') == expected_hash)
    return {
        'job': {'id': job['id'], 'status': job.get('status')},
        'contract': contract.get('contract'),
        'contract_hash': expected_hash,
        'result': result if matching else None,
        'result_time': result_event.get('time') if matching else None,
        'recorded': bool(contract_event),
        'warning': '계약과 검사 결과가 일치하지 않습니다.' if result_event and not matching else None,
    }
