#!/bin/sh
set -eu
platform_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
project_dir=$(dirname "$platform_dir")/local-only
mkdir -p "$platform_dir/state"
preview_pid=''
cleanup() {
  if [ -n "$preview_pid" ]; then kill "$preview_pid" 2>/dev/null || true; fi
}
trap cleanup EXIT
trap 'exit 130' INT TERM
if ! curl -fsS --max-time 2 http://127.0.0.1:5293/api/state >/dev/null 2>&1; then
  if [ ! -d "$platform_dir/web/node_modules" ]; then npm --prefix "$platform_dir/web" ci; fi
  npm --prefix "$platform_dir/web" run build
  if ! curl -fsS --max-time 2 http://127.0.0.1:5292/ >/dev/null 2>&1; then
    if [ ! -d "$project_dir/frontend/node_modules" ]; then npm --prefix "$project_dir/frontend" ci; fi
    (cd "$project_dir/frontend" && exec node node_modules/vite/bin/vite.js --host 127.0.0.1 --port 5292 --strictPort) >"$platform_dir/state/preview.log" 2>&1 &
    preview_pid=$!
  fi
  python3 "$platform_dir/server.py"
else
  echo '플랫폼 실행 중: http://127.0.0.1:5293'
fi
