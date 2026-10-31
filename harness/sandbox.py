"""로컬 실행용 '몸'의 경계.

책의 토이 하네스는 run_command를 내 컴퓨터의 셸에서 그대로 실행한다.
로컬 모델에게 내 Mac의 셸을 그대로 줄 수는 없으므로 두 가지 경계를 둔다.
  - 파일 Tool은 작업 폴더(WORKDIR) 안의 상대 경로만 허용한다.
  - run_command는 네트워크 없는 Docker 컨테이너에서, 작업 폴더만 /work로 마운트해 실행한다.
(책 13장 Reflexes and Guardrails, 부록 B Worktrees and Isolation)
"""
import os
import subprocess
from pathlib import Path

WORKDIR = Path(os.environ.get("HARNESS_WORKDIR", ".")).resolve()
IMAGE = os.environ.get("SANDBOX_IMAGE", "python:3.12-slim")
DOCKER_BIN = "/Applications/Docker.app/Contents/Resources/bin"


def path(p):
    """작업 폴더 밖을 가리키는 경로는 거부한다."""
    target = (WORKDIR / p).resolve()
    if target != WORKDIR and WORKDIR not in target.parents:
        raise PermissionError(f"path outside workspace: {p}")
    return target


def run(command, timeout=120):
    """네트워크 차단 컨테이너 안에서 셸 명령을 실행하고 stdout+stderr를 돌려준다."""
    env = {**os.environ, "PATH": f"{DOCKER_BIN}:{os.environ.get('PATH', '')}"}
    proc = subprocess.run(
        ["docker", "run", "--rm", "--network", "none", "--memory", "1g", "--pids-limit", "256",
         "-v", f"{WORKDIR}:/work", "-w", "/work", IMAGE, "sh", "-c", command],
        capture_output=True, text=True, timeout=timeout + 30, env=env)
    return proc.stdout + proc.stderr


def popen(command):
    """백그라운드 작업용(책 9장). 같은 컨테이너 경계로 실행한다."""
    env = {**os.environ, "PATH": f"{DOCKER_BIN}:{os.environ.get('PATH', '')}"}
    return subprocess.Popen(
        ["docker", "run", "--rm", "--network", "none", "--memory", "1g", "--pids-limit", "256",
         "-v", f"{WORKDIR}:/work", "-w", "/work", IMAGE, "sh", "-c", command],
        text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env)
