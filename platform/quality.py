"""Validate that a successful backend command actually executed tests."""
import re


def checked_result(mode, result):
    if mode != 'backend' or not result.get('success'):
        return result
    output = result.get('stdout', '') + '\n' + result.get('stderr', '')
    summaries = re.findall(r'Tests run:\s*(\d+),\s*Failures:\s*(\d+),\s*Errors:\s*(\d+),\s*Skipped:\s*(\d+)', output)
    if summaries:
        tests, failures, errors, skipped = map(int, summaries[-1])
        if tests > skipped and failures == errors == 0:
            return {**result, 'test_summary': {'tests': tests, 'failures': failures, 'errors': errors, 'skipped': skipped}}
    return {**result, 'success': False, 'stderr': result.get('stderr', '') + '\n실행된 백엔드 테스트를 확인할 수 없습니다.'}
