"""로컬 MoE 모델용 '전선(wire)' 어댑터.

책의 하네스는 Anthropic Messages API 형식으로 배열을 만들고 응답을 읽는다.
이 모듈은 그 형식을 그대로 받아 OpenAI 호환 서버(여기서는 mlx_lm.server +
gemma-4-26B-A4B)로 번역해 보내고, 응답을 다시 Anthropic 형식으로 돌려준다.
하네스 본체는 바뀌지 않는다. (책 부록 A: One Harness, Many Brains)

컨텍스트 예산: 서버는 긴 입력도 받아 주지만 이 실습은 32k 토큰을 상한으로 둔다.
보내기 전에 크기를 추정해 넘으면 예외를 낸다. 실제 사용량은 서버가 보고한
prompt_tokens로 기록한다.
"""
import json
import os
import time
import urllib.request

BASE_URL = os.environ.get("LOCAL_LLM_URL", "http://127.0.0.1:8099/v1")
MODEL = os.environ.get("LOCAL_LLM_MODEL", "mlx-community/gemma-4-26B-A4B-it-OptiQ-4bit")
CONTEXT_TOKENS = int(os.environ.get("CONTEXT_TOKENS", "32768"))
CHARS_PER_TOKEN = 3                      # 코드·JSON 기준 보수적 추정 (실제 측정은 서버 usage)
STATS = {"calls": 0, "max_prompt_tokens": 0, "prompt_tokens": 0,
         "cached_tokens": 0, "output_tokens": 0, "seconds": 0.0}


class ContextBudgetExceeded(RuntimeError):
    pass


def _text_of(content):
    if isinstance(content, str):
        return content
    return "".join(b.get("text", "") for b in content if b.get("type") == "text")


def to_openai(body):
    """Anthropic 요청 body → OpenAI chat.completions body."""
    system = body.get("system", "")
    if isinstance(system, list):                      # cache_control이 붙은 블록 형식
        system = "".join(b.get("text", "") for b in system)
    msgs = [{"role": "system", "content": system}] if system else []
    for m in body["messages"]:
        content = m["content"]
        if m["role"] == "assistant":
            blocks = content if isinstance(content, list) else [{"type": "text", "text": content}]
            calls = [{"id": b["id"], "type": "function",
                      "function": {"name": b["name"], "arguments": json.dumps(b["input"], ensure_ascii=False)}}
                     for b in blocks if b.get("type") == "tool_use"]
            out = {"role": "assistant", "content": _text_of(blocks)}
            if calls:
                out["tool_calls"] = calls
            msgs.append(out)
            continue
        if isinstance(content, str):
            msgs.append({"role": "user", "content": content})
            continue
        texts = []
        for b in content:                              # tool_result는 tool 메시지, 나머지 텍스트는 user
            if b.get("type") == "tool_result":
                c = b["content"] if isinstance(b["content"], str) else _text_of(b["content"])
                msgs.append({"role": "tool", "tool_call_id": b["tool_use_id"], "content": c})
            elif b.get("type") == "text":
                texts.append(b["text"])
        if texts:
            msgs.append({"role": "user", "content": "\n".join(texts)})
    out = {"model": MODEL, "messages": msgs, "temperature": 0,
           "max_tokens": min(body.get("max_tokens", 4096), 4096)}
    if body.get("tools"):
        out["tools"] = [{"type": "function", "function": {
            "name": t["name"], "description": t.get("description", ""),
            "parameters": t["input_schema"]}} for t in body["tools"]]
    return out


def from_openai(data):
    """OpenAI 응답 → Anthropic 형식 reply (content 블록 + stop_reason + usage)."""
    choice = data["choices"][0]
    msg = choice["message"]
    blocks = []
    if (msg.get("content") or "").strip():
        blocks.append({"type": "text", "text": msg["content"]})
    for c in msg.get("tool_calls") or []:
        raw = c["function"].get("arguments") or "{}"
        try:
            args = json.loads(raw) if isinstance(raw, str) else raw
        except json.JSONDecodeError:
            args = {"_unparsed_arguments": raw}
        blocks.append({"type": "tool_use", "id": c.get("id") or f"call_{time.time_ns()}",
                       "name": c["function"]["name"], "input": args})
    if choice.get("finish_reason") == "tool_calls" and not msg.get("tool_calls"):
        # 서버가 모델이 만든 Tool 호출을 해석하지 못하고 버린 경우. 조용히 '끝'으로 보이지 않게 표시한다.
        blocks.append({"type": "tool_use", "id": f"call_{time.time_ns()}", "name": "unparsed_tool_call", "input": {}})
    if choice.get("finish_reason") == "length":
        stop = "max_tokens"
    else:
        stop = "tool_use" if any(b["type"] == "tool_use" for b in blocks) else "end_turn"
    u = data.get("usage", {})
    usage = {"input_tokens": u.get("prompt_tokens"), "output_tokens": u.get("completion_tokens"),
             "cache_read_input_tokens": (u.get("prompt_tokens_details") or {}).get("cached_tokens")}
    return {"content": blocks or [{"type": "text", "text": ""}], "stop_reason": stop, "usage": usage}


def estimate(messages, system, tools, max_tokens=4096):
    """보낼 요청의 토큰 수를 대략 추정한다(문자 수 / 3 + 출력 몫). 보수적으로 크게 잡힌다."""
    wire = to_openai({"messages": messages, "system": system, "tools": tools, "max_tokens": max_tokens})
    return len(json.dumps(wire, ensure_ascii=False)) // CHARS_PER_TOKEN + wire["max_tokens"]


def create(body):
    """책의 call_llm이 urllib로 Anthropic에 보내던 자리. 같은 body를 받아 같은 모양을 돌려준다."""
    wire = to_openai(body)
    est = len(json.dumps(wire, ensure_ascii=False)) // CHARS_PER_TOKEN + wire["max_tokens"]   # == estimate()
    if est > CONTEXT_TOKENS:
        raise ContextBudgetExceeded(f"request ~{est} tokens exceeds {CONTEXT_TOKENS}-token budget")
    req = urllib.request.Request(f"{BASE_URL}/chat/completions", json.dumps(wire).encode(),
                                 {"Content-Type": "application/json"})
    t = time.time()
    with urllib.request.urlopen(req, timeout=900) as resp:
        data = json.loads(resp.read())
    reply = from_openai(data)
    u = reply["usage"]
    STATS["calls"] += 1
    STATS["seconds"] += time.time() - t
    STATS["prompt_tokens"] += u["input_tokens"] or 0
    STATS["cached_tokens"] += u["cache_read_input_tokens"] or 0
    STATS["output_tokens"] += u["output_tokens"] or 0
    STATS["max_prompt_tokens"] = max(STATS["max_prompt_tokens"], u["input_tokens"] or 0)
    return reply


def report():
    s = STATS
    if s["calls"]:
        print(f"[local_llm] calls={s['calls']} max_prompt={s['max_prompt_tokens']:,}/{CONTEXT_TOKENS:,} "
              f"prompt={s['prompt_tokens']:,} cached={s['cached_tokens']:,} out={s['output_tokens']:,} "
              f"time={s['seconds']:.0f}s ({s['output_tokens'] / max(s['seconds'], 1e-9):.1f} out-tok/s)")
