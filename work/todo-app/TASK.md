현재 폴더(비어 있음)에 '할 일 보드' 웹앱을 만들어 줘.

[실행]
- `python app.py --port 8000 --db todo.sqlite3` 로 실행한다. Python 3.12 표준 라이브러리만 쓴다(설치 불가).
- 데이터는 SQLite 파일에 저장한다.

[화면] GET / 는 HTML 한 페이지를 돌려준다.
- 제목 "할 일 보드"
- 할 일 입력칸과 "추가" 버튼
- 목록: 항목마다 완료 체크박스, 제목, "삭제" 버튼. 완료된 항목은 취소선
- "남은 일 N개" 표시, 필터 버튼 3개: 전체 / 진행 중 / 완료
- 화면은 아래 API를 fetch로 호출한다. 외부 CDN·라이브러리 금지. 깔끔한 CSS를 직접 작성한다.

[API] JSON으로 주고받는다.
- GET /api/todos → 200 {"items": [{"id", "title", "done"}]}  (id 오름차순)
- POST /api/todos {"title"} → 201 {"item": {...}}. title은 앞뒤 공백 제거 후 1~100자, 아니면 422 {"error": "..."}
- PATCH /api/todos/<id> {"done": true|false} → 200 {"item": {...}}. done이 불리언이 아니면 422
- DELETE /api/todos/<id> → 204
- 없는 id → 404 {"error": "..."}

[검증] run_command로 서버를 백그라운드로 띄우고 urllib로 위 API를 직접 호출해 확인한 뒤 끝내.
(run_command는 네트워크가 막힌 컨테이너에서 실행된다. 같은 명령 안에서 localhost 호출은 된다.)
