# 로컬 MoE 모델로 「Harness Engineering 101」 따라 해 보기 — 체험 후기

> 책: [Harness Engineering 101](https://isuruwijesiri.com/harness-engineering-101/) (Isuru Wijesiri, v1.1, 2026-10) · 코드: [GitHub](https://github.com/IsuruMaduranga/harness-engineering-101) (MIT)
> 환경: Mac mini M4 · 32GB · **gemma-4-26B-A4B** (MoE, 4bit, `mlx_lm.server`) · 컨텍스트 **32k 토큰 제한** · 명령 실행은 Docker(네트워크 차단)
> 실습일: 2026-10-31

![최종 결과물 — 에이전트가 빈 폴더에서 만든 할 일 보드](images/09-final-app.png)

**한 줄 요약**: 책의 300줄짜리 토이 하네스를 로컬 MoE 모델에 연결하고, 빈 폴더에서 웹앱을 만들게 했습니다. 위 화면이 그 결과입니다. 최종 결과는 독립 인수 검사 9/9이지만 처음부터 그렇지는 않았습니다. 모델은 세 번 "완료"를 선언했고, 그때마다 검사가 버그를 찾아냈습니다. 그 사이에 하네스 쪽 버그 세 개를 직접 고쳐야 했습니다.

---

## 1. 이 책이 말하는 것

책의 주장은 한 문단으로 요약됩니다.

> An LLM API is stateless. Every turn, you send the entire conversation as a JSON array and get text back. A **harness** is the program that builds, maintains, and protects that array using a simple loop. Everything the field calls "agents" is a set of patches to that one loop, and each patch exists because something concrete broke.

모든 장이 **고장 → 최소 패치 → 그 패치의 비용** 순서로 쓰여 있고, 장이 진행될수록 토이 하네스가 v1(채팅) → v2(Tool) → v3(에이전트 루프) → v4(서브에이전트) → 완성본(`harness.py`, 약 300줄)으로 자랍니다. 이번 체험에서는 이 다섯 단계를 **클라우드 API 대신 내 Mac의 MoE 모델**로 그대로 돌려 봤습니다.

## 2. 준비: 두뇌만 바꾸기

책의 코드는 Anthropic Messages API 전용입니다. 하네스 본체는 그대로 두고 **통신부(wire)만** 바꿨습니다.

| 파일 | 역할 |
|---|---|
| `harness/local_llm.py` (135줄) | 책의 요청 body(Anthropic 형식)를 그대로 받아 OpenAI 호환 형식으로 바꿔 로컬 MLX 서버에 보내고, 응답을 다시 Anthropic 형식(`content` 블록, `stop_reason`, `usage`)으로 돌려줌. 32k 예산 검사, 토큰·캐시·속도 기록 |
| `harness/sandbox.py` (42줄) | 파일 Tool은 작업 폴더 안 상대 경로만 허용. `run_command`는 **네트워크 없는 Docker 컨테이너**에서 실행 |

책 코드에서 바뀐 줄은 다섯 파일을 합쳐 +82/−76줄입니다. `harness.py` 변경의 대부분은 아래 4장에서 설명할 패치 3개입니다.

![책 코드에서 바꾼 부분](images/10-port-diff.png)

> **느낀 점.** 책 부록 A의 제목 "One Harness, Many Brains"가 말 그대로였습니다. 배열을 만드는 쪽(하네스)과 배열을 읽는 쪽(모델)이 분리돼 있으니, 두뇌를 클라우드 프런티어 모델에서 로컬 MoE로 바꿔도 몸은 거의 그대로였습니다.

> **격리는 책보다 한 단계 더 했습니다.** 책의 토이는 `run_command`를 내 컴퓨터 셸에서 그대로 실행합니다(책도 스스로 "deliberate toy"라고 밝힙니다). 로컬 모델이 내 Mac의 셸을 직접 쥐는 건 받아들이기 어려워서, 13장(Reflexes)과 부록 B(Isolation)의 논리대로 손을 컨테이너 안에만 두었습니다.

## 3. 단계별로 따라 하기

### v1 — 배열이 곧 대화 (1장)

![v1](images/01-v1-chat.png)

모델은 "하네스"라는 이름을 기억하는 것처럼 보이지만, 실제로는 매번 대화 전체를 다시 보내고 있을 뿐입니다. `/clear`는 코드상 `messages = []` 한 줄이고, 그 순간 모델은 이름을 모릅니다. 마지막 줄의 `cached=64`는 로컬 MLX 서버도 **앞부분이 같은 배열을 캐시한다**는 증거입니다(5장).

### v2 — Tool은 JSON을 함수 호출로 바꾸는 것 (3장)

![v2](images/02-v2-tools.png)

"파일 목록을 보고, 메모를 읽고, 요약해 줘"라고 했는데 **답이 없습니다.** 모델은 `ls`를 요청했고 v2는 그것을 실행했습니다. 그다음 모델이 메모를 읽으려고 두 번째 Tool을 요청하자, v2는 그 요청을 **조용히 버립니다**(책 코드의 주석: *"If reply2 asks for ANOTHER tool, v2 drops it. Chapter 4."*). 책이 4장의 동기로 든 실패를 로컬 모델에서 그대로 재현했습니다.

### v3 — 에이전트는 while 루프 (4장)

![v3](images/03-v3-agent.png)

같은 요청을 v3에 주면 `ls` → `read_file` → `write_file` → `run_command`를 스스로 이어 가고 요약 파일까지 만듭니다. 바뀐 것은 "Tool을 요청하는 동안 계속 돈다"는 루프 하나입니다. 책의 표현 그대로 **"An agent is a while loop around a chat completion."** 이 장에서 가장 크게 와닿았습니다.

### v4 — 서브에이전트는 새 배열로 도는 같은 루프 (7장)

![v4](images/04-v4-subagents.png)

메인 에이전트는 `agent` Tool로 조사를 위임하고, 서브에이전트(`[sub]`)는 **빈 배열**에서 시작해 `find`, `grep`, 직접 작성한 파싱 스크립트로 조사한 뒤 보고서만 돌려줍니다. 표는 실제 파일과 대조해 보니 정확했습니다. 다만 서브에이전트가 만든 `extract_functions.py`가 작업 폴더에 **남아 있었습니다.** 컨텍스트는 분기되지만 파일 시스템은 분기되지 않는다는 점, 즉 부록 B(worktree 격리)가 왜 필요한지를 바로 보여 준 장면입니다.

## 4. 완성본으로 웹앱 만들기

### 과제와 판정 기준

빈 폴더에 `TASK.md`(할 일 보드: 화면 + JSON API + SQLite, Python 표준 라이브러리만 사용)와 `AGENT.md`(프로젝트 메모, 6장의 메모리 파일)를 두고, 완성본 `harness.py`에게 "TASK.md대로 구현하고 직접 테스트해"라고 한 줄만 줬습니다.

완료 판정은 모델이 아니라 **독립 인수 검사**(`tasks/todo-app/acceptance.py`, 9개 항목)가 합니다. 앱을 별도 프로세스로 띄우고 HTTP로만 확인하며, 네트워크 없는 컨테이너에서 실행합니다. 이 검사 자체도 미리 검증했습니다. 제가 직접 짠 정답 구현에서는 9/9, 빈 폴더에서는 0/1이 나왔습니다.

### 1차 실행 — "fully functional"

![1차 실행](images/05-harness-todo.png)

11번의 모델 호출, 4분 50초 만에 `app.py`, `index.html`, `test.py`를 만들고 자기 테스트를 통과한 뒤 *"The application is fully functional and meets all requirements"*라고 선언했습니다. `todo_write`로 계획을 세우고(8장), 서버를 띄워 자기 API를 직접 호출해 보는 모습은 정말 에이전트다웠습니다.

### 독립 검사 — 7/9

![독립 검사 1차](images/06-acceptance.png)

1. `{"title": 3}`처럼 문자열이 아닌 제목을 보내면 422 대신 **연결이 끊깁니다**(핸들러 예외).
2. 서버를 끄고 같은 포트로 바로 다시 띄우면 `Address already in use`로 **재시작에 실패합니다.**

모델이 만든 자체 테스트는 둘 다 다루지 않았습니다. *(고백: 처음에는 2번이 `UnboundLocalError`로 나왔습니다. 재시작한 서버가 응답하지 않을 때 원인을 보고하지 못하는 **제 검사 코드의 버그**였습니다. 검사를 고친 뒤에야 진짜 원인이 보였습니다. 검증기도 검증이 필요합니다.)*

### 하네스가 먼저 고장 났다 ①: 컨텍스트 초과 (6장)

실패 내용을 같은 세션에 이어서 넘겼습니다(1장: "resume is a file read"). 그러자 몇 라운드 만에 하네스가 죽었습니다.

![컨텍스트 초과](images/07a-context-overflow.png)

책 6장의 문장 그대로입니다. *"the array hits the model's input limit, the next API call is rejected, and the task dies mid-flight."* 책의 토이에는 Tool 결과를 자르는 기능만 있고 compaction은 없습니다. 클라우드의 200k 창에서는 한참 뒤에야 만날 문제지만, **32k에서는 웹앱 하나 만드는 사이에 바로 터집니다.** 파일 전체가 `write_file`/`edit_file` 호출의 인자로 배열에 계속 쌓이기 때문입니다.

게다가 세션 파일은 턴이 **정상적으로 끝나야** 저장되는 구조라, 이 턴의 대화가 통째로 사라졌습니다(파일 수정은 디스크에 남음).

**패치(직접 작성, 약 30줄)**
- 배열이 예산의 70%를 넘으면 최근 6개 메시지를 제외한 **오래된 Tool 결과와 Tool 호출 안의 긴 문자열(파일 본문)**을 400자로 줄입니다. 호출/결과 짝은 하나도 지우지 않습니다.
- 턴이 예외로 끝나도 세션을 저장합니다(`try/finally`).

**비용(5장)**: 압축하면 배열 앞부분이 바뀌므로 캐시가 한 번 깨집니다. 실제로 압축 직후 요청은 `cache_read`가 1만여 개에서 654개로 떨어졌습니다.

### 하네스가 먼저 고장 났다 ②: 사라진 Tool 호출 (부록 D)

![호출 유실](images/07b-dropped-tool-call.png)

압축은 동작했지만(`[compact] ~23,260 -> ~14,984`), 다음 응답에서 턴이 **아무 말 없이** 끝났습니다. 모델은 1,467토큰을 생성했는데도요. 같은 배열을 서버에 다시 보내 원본 응답을 확인해 보니, `finish_reason`은 `tool_calls`인데 `tool_calls` 필드가 없었습니다. 모델이 만든 긴 `edit_file` 호출을 **서버가 해석하지 못하고 버린 것**입니다. 제 어댑터는 이를 빈 "끝" 응답으로 바꿨고, 루프는 정상 종료로 받아들였습니다.

**패치**: 이런 경우를 `unparsed_tool_call`로 표시하고, Tool 결과 자리에 *"이전 호출은 해석되지 않아 실행되지 않았다. 더 작은 인자로 다시 시도하라"*를 돌려줍니다. 책 4장의 "errors are fuel"(오류는 예외로 끊지 말고 문자열로 돌려줘 모델의 연료로 쓴다)을 전선(wire) 층에 적용한 것입니다.

### 수정 → 8/9 → 9/9

![수정 턴](images/07-harness-fix.png)

다시 실행하자 두 버그를 고치고, 자기 테스트에 두 경우를 추가해 통과시켰습니다. 독립 검사는 **8/9**였습니다. 이번에는 목록 API의 `done`이 `true`가 아니라 SQLite 정수 `1`로 나왔습니다. 추가·수정 응답은 불리언이었기 때문에 모델의 테스트로는 보이지 않았습니다. 한 번 더 넘기자 고쳤습니다.

![수정 2회차](images/07c-harness-fix2.png)

![최종 검사](images/08-acceptance-final.png)

**9/9.** 그리고 맨 위의 화면이 이 앱을 컨테이너에서 띄워 API로 할 일 다섯 개를 넣고(세 개는 완료) Safari로 연 모습입니다. 제목, 입력칸, 세 가지 필터, 취소선, 삭제 버튼, "남은 일 2개"까지 명세대로 나옵니다. 외부 라이브러리 없이 모델이 직접 쓴 CSS입니다.

## 5. 숫자로 본 체험

| 단계 | 모델 호출 | 최대 입력 토큰 | 캐시 적중 | 생성 속도 |
|---|---:|---:|---:|---:|
| v1 채팅 | 3 | 84 | 39% | 14 tok/s |
| v2 Tool | 2 | 182 | 47% | 12 tok/s |
| v3 루프 | 5 | 442 | 74% | 18 tok/s |
| v4 서브에이전트 | 7 | 996 | 44% | 18 tok/s |
| 웹앱 1차 | 11 | 8,517 | **84%** | 20 tok/s |
| 웹앱 수정 (호출 유실) | 5 | 14,428 | 60% | 17 tok/s |
| 웹앱 수정 | 5 | 13,063 | 77% | 16 tok/s |
| 웹앱 수정 2회차 | 10 | 13,510 | 70% | 17 tok/s |

- **MoE의 체감**: 전체 26B 파라미터 중 토큰마다 약 4B만 활성화되는 구조라, 26B급 모델이 이 Mac에서 초당 12~20토큰을 생성했습니다. 서버 메모리는 16.6GB, 모델 파일은 16GB입니다. API 비용은 0원이고, 웹앱 완성까지 걸린 시간은 시간이 기록된 네 번의 실행만 합쳐도 약 22분입니다(컨텍스트 초과로 중단된 실행은 기록이 없어 제외).
- **캐시(5장)**: 로컬에서도 prefix 캐시가 체감됩니다. 배열을 덧붙이기만 하는(append-only) 1차 실행은 입력의 84%가 캐시였습니다. 압축 직후에는 캐시가 깨졌습니다.
- **32k 예산**: 최대 실제 입력은 14,428토큰이었습니다. 제 추정식(문자 수 ÷ 3)은 실제보다 크게 잡힙니다. 서버가 마지막으로 보고한 실제 입력이 22.5k였던 시점에, 다음 요청을 32.8k로 추정해 막았습니다. 안전하긴 하지만 예산을 낭비합니다. 책 6장의 말대로 **서버가 보고한 실제 사용량으로 회계**하는 게 맞습니다.

## 6. 후기

**① "에이전트는 while 루프"라는 말은 과장이 아니었습니다.** v2와 v3의 차이는 루프 하나인데, 결과는 "답이 없음"과 "스스로 끝까지 함"으로 갈립니다. 이 차이를 로컬 모델로 직접 보니 에이전트 프레임워크에 대한 막연함이 많이 걷혔습니다(10장 "Every Framework Is a Wrapper").

**② 실제로 고친 버그는 모델보다 몸(하네스)에 더 많았습니다.** 모델의 실수는 피드백 두 번으로 고쳐졌습니다. 반면 저는 하네스를 세 번 고쳐야 했습니다(compaction, 크래시 시 세션 저장, 사라진 Tool 호출). 책이 왜 "모델은 두뇌, 하네스는 몸"이라는 구도로 시작하는지, 그리고 왜 부록 D처럼 지루한 배관까지 다루는지 이해가 됐습니다. 특히 ②번 호출 유실은 **오류 없이 정상 종료처럼 보였다는 점**이 무서웠습니다.

**③ 작은 컨텍스트에서는 6장이 '고급'이 아니라 '첫 번째' 패치입니다.** 클라우드 모델로 책을 읽었다면 compaction은 나중 이야기였을 겁니다. 32k 로컬 모델에서는 웹앱 하나 만드는 중에 바로 필요했습니다. 로컬·작은 모델로 하네스를 공부하면 고장이 **빨리, 자주** 나서 오히려 배우기 좋다는 것이 이번 체험의 의외의 수확입니다.

**④ "완료"는 몸이 판정해야 합니다.** 모델은 세 번 모두 자신 있게 완료를 선언했고, 매번 자기 테스트도 통과했습니다. 그런데 독립 검사는 매번 다른 버그를 찾았습니다. 구현한 쪽이 테스트까지 쓰면 같은 맹점을 공유하게 됩니다. 책 14장의 "the world pushes back, cheaply and honestly"는 **누가 그 세계를 만들었는지**까지 따져야 성립한다고 느꼈습니다. 덧붙이면 제 검사 코드에도 버그가 있었으니, 검증기 역시 정답 구현과 빈 구현으로 미리 검증해 둬야 합니다.

**⑤ 아쉬운 점.** 시스템 프롬프트가 영어라서 모델이 한국어 요청에도 영어로 답했습니다. 하네스의 언어 정책도 프롬프트 설계의 일부입니다. 그리고 이번에는 Tool 승인 게이트(13장)가 거의 시험되지 않았습니다. 무인 실행이라 위험 명령은 자동 거부로 두었고, 모델도 위험한 명령을 시도하지 않았습니다.

## 7. 직접 해 보기

```bash
# 로컬 MoE 서버 (OpenAI 호환, 예: mlx_lm.server)가 127.0.0.1:8099/v1 에 떠 있다고 가정
git clone <이 저장소> harness101-local && cd harness101-local
docker pull python:3.12-slim

# 단계별 (대화형으로 입력)
cd work && mkdir v3 && cd v3 && HARNESS_WORKDIR=. python3 ../../harness/v3_agent.py

# 웹앱 과제
mkdir -p work/todo-app && cp tasks/todo-app/{TASK,AGENT}.md work/todo-app/
cd work/todo-app && HARNESS_WORKDIR=. python3 ../../harness/harness.py ../todo.session.json
#   you> TASK.md를 읽고 요구사항대로 구현해 줘. 끝나기 전에 직접 테스트해서 확인해.
cd ../.. && tasks/todo-app/check.sh work/todo-app      # 독립 인수 검사
```

환경 변수: `LOCAL_LLM_URL`, `LOCAL_LLM_MODEL`, `CONTEXT_TOKENS`(기본 32768), `HARNESS_WORKDIR`, `SANDBOX_IMAGE`

## 8. 파일 구성

```
harness/            책의 v1~v4, harness.py (MIT) + 로컬 어댑터 local_llm.py, sandbox.py
                    첫 커밋이 책 원본 그대로라서 `git diff 0754f0e -- harness/` 로 바꾼 부분만 볼 수 있음
tasks/todo-app/     TASK.md(과제), AGENT.md(프로젝트 메모), acceptance.py + check.sh(독립 인수 검사)
tasks/turns/        캡처에 쓴 사용자 입력
work/todo-app/      에이전트가 만든 결과물 (app.py, index.html, test.py)
review/             이 후기 (README.md, review.html, images/, logs/ = 각 캡처의 원본 출력)
```

## 출처와 라이선스

- 책 본문: © 2026 Isuru Wijesiri, [CC BY-NC-ND 4.0](https://creativecommons.org/licenses/by-nc-nd/4.0/). 이 후기에는 짧은 인용만 원문 그대로 실었습니다.
- 하네스 코드: [MIT](../harness/LICENSE-CODE.book). 원본 커밋 `745c433`.
