# platform

사람이 쓰는 쪽입니다. 요청을 받고, 하네스를 부르고, 결과와 변경 이력을 보여 주고, 운영으로 내보내는 일을 여기서 합니다.
전체 소개는 [저장소 맨 위 README](../README.md)를 보세요.

## 켜기

```sh
cd web && npm ci && npm run build && cd ..
python3 server.py        # http://127.0.0.1:5293
```

로컬 모델 서버(8099)는 `scripts/qwen-serve-forever.sh`로 따로 띄웁니다. 처음 열면 프로젝트가 없으니 「설정 › 개발 환경」 점검부터 하면 됩니다.

## 어디에 뭐가 있나

- `server.py` — 플랫폼 서버. 화면과 API를 모두 내보냅니다.
- `web/` — 플랫폼 화면(React). 고친 뒤에는 `npm run build`를 다시 하면 열려 있는 페이지가 저절로 새로 고쳐집니다.
- `ctl.py` — 화면에서 하는 일을 명령줄로. `python3 ctl.py -h`
- `base/` — 프레임워크 원본. 모든 프로젝트가 함께 씁니다. 바꾸면 `framework_update.py`가 프로젝트마다 반영하고 점검합니다.
- `projects.py`, `sites.py` — 프로젝트 만들기·이름·포트, 프로젝트별 서버와 DB 위치.
- `release.py` — 프로젝트 깃(기록·원복·작업 공간·원격)과 운영 셋업 팩.
- `windows_pack.py` — 윈도우 설치용·업데이트용 팩.
- `platform_pack.py` — 플랫폼 자체를 다른 맥으로 옮기는 팩.
- `first_setup.py`, `environment.py` — 개발 환경 점검과 셋업.
- `desktop/` — 앱 창(Electron). 저장소 맨 위의 `Local Workshop.command`가 이걸 엽니다.
- `state/` — 실행 중에 생기는 것들(프로젝트 목록, 요청별 실행 기록, 로그인 정보). 저장소에는 안 들어갑니다.

## 고친 뒤에 돌려 볼 것

```sh
python3 tests/control_check.py   # 프로젝트 만들기부터 요청·원복·지우기까지 한 바퀴 (점검용 프로젝트를 만들었다 지움)
python3 tests/flow_check.py      # 업무 흐름 판정이 제대로 걸러 내는지
```

요청이 돌고 있을 때는 플랫폼 서버를 다시 켜지 마세요. 돌던 요청이 끊깁니다.
