#!/bin/sh
# 사용법: tasks/todo-app/check.sh <앱 폴더>   (네트워크 없는 컨테이너에서 인수 검사)
export PATH="/Applications/Docker.app/Contents/Resources/bin:$PATH"
exec docker run --rm --network none -v "$(cd "$1" && pwd)":/app:ro -v "$(cd "$(dirname "$0")" && pwd)/acceptance.py":/check.py:ro python:3.12-slim python /check.py
