#!/bin/sh
# 두 번 눌러 플랫폼을 앱 창으로 연다 (플랫폼 서버·앱 화면·도커·모델 서버가 꺼져 있으면 켠다).
cd "$(dirname "$0")/platform/desktop" && exec sh run.sh
