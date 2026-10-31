#!/usr/bin/env python3
"""할 일 보드 인수 검사 — 에이전트와 독립된 판정.

에이전트가 만든 app.py를 별도 프로세스로 띄우고 HTTP로만 확인한다(코드를 import하지 않는다).
네트워크 없는 컨테이너 안에서 실행한다:
  docker run --rm --network none -v <app폴더>:/app:ro -v <이 파일>:/check.py:ro python:3.12-slim python /check.py
"""
import json
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

PORT = 8123
BASE = f"http://127.0.0.1:{PORT}"
results = []


def req(method, path, body=None, raw=None):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    r = urllib.request.Request(BASE + path, data=data, method=method,
                               headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(r, timeout=5) as resp:
            text = resp.read().decode()
            return resp.status, resp.headers.get("Content-Type", ""), text
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Content-Type", ""), e.read().decode()


def js(text):
    try:
        return json.loads(text) if text else None
    except json.JSONDecodeError:
        return None


def check(name, fn):
    try:
        fn()
        results.append((name, True, ""))
    except Exception as e:  # noqa: BLE001 - 어떤 실패든 기록한다
        results.append((name, False, f"{type(e).__name__}: {e}"[:160]))


def main():
    work = tempfile.mkdtemp()
    shutil.copytree("/app", work, dirs_exist_ok=True)
    proc = subprocess.Popen([sys.executable, "app.py", "--port", str(PORT), "--db", f"{work}/check.sqlite3"],
                            cwd=work, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    for _ in range(50):
        try:
            urllib.request.urlopen(BASE + "/api/todos", timeout=1)
            break
        except Exception:
            time.sleep(0.2)
    else:
        proc.kill()
        print("FAIL startup:", (proc.stdout.read() or "")[-500:])
        print("결과: 0/1")
        return 1

    def page():
        s, ct, t = req("GET", "/")
        assert s == 200 and "text/html" in ct, (s, ct)
        for word in ("할 일 보드", "추가", "전체", "진행 중", "완료", "/api/todos"):
            assert word in t, f"missing {word!r} in page"
        assert "cdn" not in t.lower() and "https://" not in t, "external resource"

    def empty():
        s, _, t = req("GET", "/api/todos")
        assert s == 200 and js(t) == {"items": []}, (s, t)

    created = {}

    def create():
        s, _, t = req("POST", "/api/todos", {"title": "  장보기  "})
        item = js(t)["item"]
        assert s == 201 and item["title"] == "장보기" and item["done"] is False, (s, t)
        created["a"] = item["id"]
        s, _, t = req("POST", "/api/todos", {"title": "운동"})
        assert s == 201
        created["b"] = js(t)["item"]["id"]

    def order():
        s, _, t = req("GET", "/api/todos")
        ids = [i["id"] for i in js(t)["items"]]
        assert ids == sorted(ids) and len(ids) == 2, ids

    def bad_titles():
        for body in ({"title": "   "}, {"title": "x" * 101}, {"title": 3}, {}):
            s, _, t = req("POST", "/api/todos", body)
            assert s == 422 and "error" in (js(t) or {}), (body, s, t)
        s, _, _ = req("POST", "/api/todos", {"title": "가" * 100})
        assert s == 201, "100 chars must be accepted"

    def toggle():
        s, _, t = req("PATCH", f"/api/todos/{created['a']}", {"done": True})
        assert s == 200 and js(t)["item"]["done"] is True, (s, t)
        s, _, t = req("PATCH", f"/api/todos/{created['a']}", {"done": "yes"})
        assert s == 422, (s, t)

    def delete():
        s, _, _ = req("DELETE", f"/api/todos/{created['b']}")
        assert s == 204, s
        s, _, t = req("GET", "/api/todos")
        assert created["b"] not in [i["id"] for i in js(t)["items"]]

    def missing():
        for m, body in (("PATCH", {"done": True}), ("DELETE", None)):
            s, _, t = req(m, "/api/todos/99999", body)
            assert s == 404 and "error" in (js(t) or {}), (m, s, t)

    def persist():
        proc.terminate()
        proc.wait(timeout=5)
        p2 = subprocess.Popen([sys.executable, "app.py", "--port", str(PORT), "--db", f"{work}/check.sqlite3"],
                              cwd=work, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        try:
            t = None
            for _ in range(50):
                try:
                    s, _, t = req("GET", "/api/todos")
                    break
                except Exception:
                    time.sleep(0.2)
            if t is None:
                p2.kill()
                tail = (p2.stdout.read() or "").strip().splitlines()[-1:] or ["(no output)"]
                raise AssertionError(f"restarted server did not respond: {tail[0][:120]}")
            items = js(t)["items"]
            assert any(i["title"] == "장보기" and i["done"] is True for i in items), items
        finally:
            p2.kill()

    for name, fn in [("화면 GET /", page), ("빈 목록", empty), ("추가 POST", create), ("id 오름차순", order),
                     ("잘못된 제목 422 / 100자 허용", bad_titles), ("완료 토글 PATCH", toggle),
                     ("삭제 DELETE", delete), ("없는 id 404", missing), ("재시작 후 데이터 유지", persist)]:
        check(name, fn)
    proc.kill()
    for name, ok, why in results:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  — {why}" if why else ""))
    passed = sum(ok for _, ok, _ in results)
    print(f"결과: {passed}/{len(results)}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
