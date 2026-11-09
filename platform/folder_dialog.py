"""Native folder chooser; no user path is evaluated as script."""
from pathlib import Path
import subprocess
import sys
import threading

_dialog = threading.Lock()


def choose_folder():
    if sys.platform != 'darwin':
        raise ValueError('현재 폴더 선택 다이얼로그는 macOS에서 지원합니다.')
    if not _dialog.acquire(blocking=False):
        raise RuntimeError('폴더 선택 창이 이미 열려 있습니다.')
    try:
        result = subprocess.run(['osascript', '-e', 'activate\nPOSIX path of (choose folder with prompt "프로젝트 폴더를 선택하세요")'], capture_output=True, text=True, timeout=600)
        if result.returncode:
            if '-128' in result.stderr: return {'cancelled':True}
            raise ValueError('폴더 선택 창을 열지 못했습니다. '+result.stderr.strip()[:400])
        selected=result.stdout.rstrip('\r\n')
        if not selected:raise ValueError('선택한 폴더를 찾을 수 없습니다.')
        root = Path(selected).resolve()
        if not root.is_dir(): raise ValueError('선택한 폴더를 찾을 수 없습니다.')
        return {'cancelled':False, 'root':str(root), 'name':root.name}
    except subprocess.TimeoutExpired:
        raise ValueError('폴더 선택 시간이 지났습니다. 다시 선택하세요.')
    finally:
        _dialog.release()
