#!/bin/sh
# 플랫폼을 앱 창으로 연다. 처음이면 필요한 것을 먼저 받는다.
cd "$(dirname "$0")"
[ -d node_modules/electron ] || npm install --no-audit --no-fund
exec node_modules/.bin/electron .
