# 프로젝트 메모 (하네스가 세션 시작 시 주입)
- Python 3.12, 표준 라이브러리만 사용. pip 설치 불가, 네트워크 없음.
- 파일을 고칠 때는 먼저 read_file로 읽고 edit_file로 고친다.
- 서버를 띄워 테스트할 때는 한 run_command 안에서 `python app.py ... & sleep 1; python test.py; kill %1` 처럼 실행하고 정리한다.
