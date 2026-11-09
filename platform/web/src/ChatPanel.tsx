import { memo, useEffect, useMemo, useRef, useState } from "react";
import { apiFetch, projectId } from "./api";
import { renderMarkdown } from "./markdown";
import "./chat.css";

type Mode = "chat" | "project";
type Stats = { promptTokens?: number; cachedTokens?: number; completionTokens?: number; seconds?: number; firstTokenSeconds?: number; finish?: string };
type Turn = { id: string; role: "user" | "assistant"; content: string; reasoning?: string; sources?: string[]; stats?: Stats; error?: string; stopped?: boolean };
type Conversation = { id: string; title: string; mode: Mode; turns: Turn[] | null; updatedAt: number };
type Settings = { maxTokens: number; thinking: boolean; instructions: string };

const legacyKeys = [`local-workshop-chats:${projectId}`];
const legacySessionKey = `local-workshop-chat:${projectId}`;
const settingsKey = `local-workshop-chat-settings:${projectId}`;
const HISTORY_CHARS = 40000;
const uid = () => Math.random().toString(36).slice(2) + Date.now().toString(36);

/** Conversations saved only in this browser by earlier versions, uploaded once to the server store. */
function legacyConversations(): Conversation[] {
  const found: Conversation[] = [];
  try {
    for (const key of legacyKeys) {
      const value = JSON.parse(localStorage.getItem(key) || "[]");
      if (Array.isArray(value)) found.push(...value.filter(c => c && typeof c.id === "string" && Array.isArray(c.turns)));
    }
    const old = JSON.parse(sessionStorage.getItem(legacySessionKey) || "null");
    for (const mode of ["chat", "project"] as Mode[]) {
      const list = old?.[mode];
      if (Array.isArray(list) && list.length) found.push({ id: uid(), mode, updatedAt: Date.now(),
        title: titleFrom(list.find((t: Turn) => t.role === "user")?.content || "이전 대화"),
        turns: list.filter((t: Turn) => t && typeof t.content === "string").map((t: Turn) => ({ ...t, id: uid() })) });
    }
  } catch { /* storage unavailable */ }
  return found;
}
function clearLegacy() {
  try { legacyKeys.forEach(k => localStorage.removeItem(k)); sessionStorage.removeItem(legacySessionKey); } catch { /* ignore */ }
}
function postJson(path: string, token: string, body: unknown, keepalive = false) {
  return apiFetch(path, { method: "POST", keepalive, headers: { "Content-Type": "application/json", "X-Platform-Token": token }, body: JSON.stringify(body) });
}
function loadSettings(): Settings {
  try { return { maxTokens: 2048, thinking: false, instructions: "", ...JSON.parse(localStorage.getItem(settingsKey) || "{}") }; }
  catch { return { maxTokens: 2048, thinking: false, instructions: "" }; }
}
function titleFrom(text: string) {
  const line = text.replace(/\s+/g, " ").trim();
  return line.length > 40 ? line.slice(0, 40) + "…" : line || "새 대화";
}
function historyFor(turns: Turn[]) {
  const usable = turns.filter(t => t.content.trim() && !t.error);
  const kept: { role: Turn["role"]; content: string }[] = [];
  let used = 0;
  for (let i = usable.length - 1; i >= 0; i--) {
    const t = usable[i];
    if (kept.length && used + t.content.length > HISTORY_CHARS) break;
    kept.unshift({ role: t.role, content: t.content.slice(0, 32000) });
    used += t.content.length;
  }
  while (kept.length && kept[0].role !== "user") kept.shift();
  return kept;
}
function dayLabel(time: number) {
  const days = Math.floor((new Date().setHours(0, 0, 0, 0) - new Date(time).setHours(0, 0, 0, 0)) / 86400000);
  return days <= 0 ? "오늘" : days === 1 ? "어제" : days < 7 ? "지난 7일" : days < 30 ? "지난 30일" : "이전";
}

const Markdown = memo(function Markdown({ text }: { text: string }) {
  const html = useMemo(() => renderMarkdown(text), [text]);
  return <div className="md" dangerouslySetInnerHTML={{ __html: html }} />;
});

async function copyText(text: string) {
  try { await navigator.clipboard.writeText(text); } catch {
    const area = document.createElement("textarea"); area.value = text; document.body.appendChild(area); area.select();
    document.execCommand("copy"); area.remove();
  }
}

export default function ChatPanel({ token, model, online, modelBusy }: { token: string; model: string; online: boolean; modelBusy: boolean }) {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeId, setActiveId] = useState<string>("");
  const [loaded, setLoaded] = useState(false);
  const saved = useRef<Record<string, string>>({});
  const saveTimer = useRef(0);
  const latest = useRef<Conversation[]>([]);
  const [newMode, setNewMode] = useState<Mode>("chat");
  const [settings, setSettings] = useState<Settings>(loadSettings);
  const [showSettings, setShowSettings] = useState(false);
  const [draft, setDraft] = useState("");
  const [streamingId, setStreamingId] = useState("");
  const [phase, setPhase] = useState("");
  const [error, setError] = useState("");
  const [filter, setFilter] = useState("");
  const [editing, setEditing] = useState<{ id: string; text: string } | null>(null);
  const [renaming, setRenaming] = useState<{ id: string; text: string } | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const abort = useRef<AbortController | null>(null);
  const scroller = useRef<HTMLDivElement>(null);
  const stick = useRef(true);
  const input = useRef<HTMLTextAreaElement>(null);

  const active = conversations.find(c => c.id === activeId);
  const mode: Mode = active?.mode || newMode;
  const turns = active?.turns || [];
  const pending = !!streamingId;
  const canSend = loaded && online && !!model && !!token && !modelBusy && !pending;

  // Load the server-side conversation list once a token is available; upload old browser-only chats.
  useEffect(() => {
    if (!token || loaded) return;
    let cancelled = false;
    (async () => {
      try {
        const legacy = legacyConversations();
        for (const conv of legacy) {
          const response = await postJson(`/api/chats/${conv.id}`, token, conv);
          if (!response.ok) throw Error((await response.json().catch(() => ({}))).error || `HTTP ${response.status}`);
        }
        if (legacy.length) clearLegacy();
        const response = await apiFetch("/api/chats");
        const body = await response.json();
        if (!response.ok) throw Error(body.error || `HTTP ${response.status}`);
        if (cancelled) return;
        const list: Conversation[] = body.conversations.map((c: Conversation) => ({ ...c, turns: null }));
        setConversations(list); setLoaded(true);
        if (list[0]) void open(list[0].id);
      } catch (cause) { if (!cancelled) setError("대화 목록을 불러오지 못했습니다: " + (cause instanceof Error ? cause.message : String(cause))); }
    })();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, loaded]);

  // Persist changed conversations to the server (debounced; more often finished than while streaming).
  function flushSaves(keepalive = false) {
    window.clearTimeout(saveTimer.current); saveTimer.current = 0;
    for (const conv of latest.current) {
      if (!conv.turns) continue;
      const json = JSON.stringify(conv);
      if (saved.current[conv.id] === json) continue;
      saved.current[conv.id] = json;
      void postJson(`/api/chats/${conv.id}`, token, conv, keepalive).then(async r => {
        if (!r.ok) { delete saved.current[conv.id]; setError("대화 저장 실패: " + ((await r.json().catch(() => ({}))).error || r.status)); }
      }).catch(() => { delete saved.current[conv.id]; });
    }
  }
  useEffect(() => {
    latest.current = conversations;
    if (!loaded || !token) return;
    window.clearTimeout(saveTimer.current);
    saveTimer.current = window.setTimeout(() => flushSaves(), pending ? 1500 : 200);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [conversations, pending, loaded, token]);
  useEffect(() => {
    const leave = () => flushSaves(true);
    window.addEventListener("pagehide", leave);
    return () => { window.removeEventListener("pagehide", leave); leave(); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  async function open(id: string) {
    setActiveId(id); setEditing(null);
    const conv = latest.current.find(c => c.id === id);
    if (conv?.turns) return;
    try {
      const response = await apiFetch(`/api/chats/${id}`);
      const body = await response.json();
      if (!response.ok) throw Error(body.error || `HTTP ${response.status}`);
      saved.current[id] = JSON.stringify({ ...body, turns: body.turns });
      setConversations(list => list.map(c => c.id === id ? { ...body } : c));
    } catch (cause) { setError("대화를 불러오지 못했습니다: " + (cause instanceof Error ? cause.message : String(cause))); }
  }
  useEffect(() => { try { localStorage.setItem(settingsKey, JSON.stringify(settings)); } catch { /* ignore */ } }, [settings]);
  useEffect(() => {
    const el = scroller.current;
    if (el && stick.current) el.scrollTop = el.scrollHeight;
  });
  useEffect(() => { stick.current = true; input.current?.focus(); }, [activeId]);
  useEffect(() => {
    const el = input.current; if (!el) return;
    el.style.height = "auto"; el.style.height = Math.min(el.scrollHeight, 260) + "px";
  }, [draft]);

  function update(id: string, fn: (c: Conversation) => Conversation) {
    setError("");
    setConversations(list => list.map(c => c.id === id ? fn(c) : c));
  }
  function patchTurn(convId: string, turnId: string, fn: (t: Turn) => Turn) {
    update(convId, c => ({ ...c, turns: (c.turns || []).map(t => t.id === turnId ? fn(t) : t) }));
  }

  async function run(convId: string, history: Turn[]) {
    const conv = conversations.find(c => c.id === convId);
    const convMode = conv?.mode || newMode;
    const answer: Turn = { id: uid(), role: "assistant", content: "" };
    update(convId, c => ({ ...c, turns: [...history, answer], updatedAt: Date.now() }));
    setStreamingId(answer.id); setError(""); setPhase("입력 처리 중"); stick.current = true;
    const controller = new AbortController(); abort.current = controller;
    const started = performance.now(); let first = 0;
    let content = "", reasoning = "";
    let frame = 0;
    const flush = () => { frame = 0; patchTurn(convId, answer.id, t => ({ ...t, content, reasoning: reasoning || undefined })); };
    const schedule = () => { if (!frame) frame = requestAnimationFrame(flush); };
    try {
      const response = await apiFetch("/api/chat/stream", {
        method: "POST", signal: controller.signal,
        headers: { "Content-Type": "application/json", "X-Platform-Token": token },
        body: JSON.stringify({ mode: convMode, model, max_tokens: settings.maxTokens, thinking: settings.thinking,
          instructions: settings.instructions, messages: historyFor(history) }),
      });
      if (!response.ok || !response.body) {
        const body = await response.json().catch(() => ({}));
        throw Error(body.error || `HTTP ${response.status}`);
      }
      const reader = response.body.getReader(); const decoder = new TextDecoder(); let buffer = "";
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        let index;
        while ((index = buffer.indexOf("\n")) >= 0) {
          const line = buffer.slice(0, index).trim(); buffer = buffer.slice(index + 1);
          if (!line) continue;
          const event = JSON.parse(line);
          if (event.type === "meta") patchTurn(convId, answer.id, t => ({ ...t, sources: event.sources || [] }));
          else if (event.type === "reasoning" || event.type === "delta") {
            if (!first) { first = performance.now(); }
            if (event.type === "reasoning") { reasoning += event.content; setPhase("생각 중"); }
            else { content += event.content; setPhase("답변 작성 중"); }
            schedule();
          } else if (event.type === "error") throw Error(event.error);
          else if (event.type === "done") {
            const u = event.usage || {};
            const stats: Stats = { promptTokens: u.prompt_tokens, completionTokens: u.completion_tokens,
              cachedTokens: u.prompt_tokens_details?.cached_tokens, seconds: (performance.now() - started) / 1000,
              firstTokenSeconds: first ? (first - started) / 1000 : undefined, finish: event.finish_reason };
            if (frame) cancelAnimationFrame(frame);
            flush(); patchTurn(convId, answer.id, t => ({ ...t, stats }));
          }
        }
      }
    } catch (cause) {
      if (frame) cancelAnimationFrame(frame);
      flush();
      if (controller.signal.aborted) patchTurn(convId, answer.id, t => ({ ...t, stopped: true }));
      else {
        const message = cause instanceof Error ? cause.message : String(cause);
        patchTurn(convId, answer.id, t => ({ ...t, error: message }));
      }
    } finally {
      abort.current = null; setStreamingId(""); setPhase("");
      update(convId, c => ({ ...c, updatedAt: Date.now() }));
    }
  }

  function send(text = draft) {
    const content = text.trim();
    if (!content || !canSend) return;
    const user: Turn = { id: uid(), role: "user", content };
    let convId = activeId;
    let base = active?.turns || [];
    if (!active) {
      convId = uid(); base = [];
      setConversations(list => [{ id: convId, title: titleFrom(content), mode: newMode, turns: [], updatedAt: Date.now() }, ...list]);
      setActiveId(convId);
    }
    setDraft("");
    void run(convId, [...base, user]);
  }
  function regenerate(turnId: string) {
    if (!active || !canSend) return;
    const list = active.turns || [];
    void run(active.id, list.slice(0, list.findIndex(t => t.id === turnId)));
  }
  function saveEdit() {
    if (!active || !editing || !canSend || !editing.text.trim()) return;
    const list = active.turns || [];
    const index = list.findIndex(t => t.id === editing.id);
    const history = [...list.slice(0, index), { ...list[index], content: editing.text.trim() }];
    setEditing(null);
    void run(active.id, history);
  }
  function newChat() {
    if (pending) return;
    setActiveId(""); setDraft(""); setError(""); setEditing(null); input.current?.focus();
  }
  function remove(id: string) {
    if (pending && id === activeId) return;
    if (!confirm("이 대화를 삭제할까요?")) return;
    setConversations(list => list.filter(c => c.id !== id));
    delete saved.current[id];
    void postJson(`/api/chats/${id}/delete`, token, {});
    if (id === activeId) setActiveId("");
  }
  function onTranscriptClick(event: React.MouseEvent) {
    const target = event.target as HTMLElement;
    if (target.dataset.copyCode) {
      const code = target.closest(".md-code")?.querySelector("code")?.textContent || "";
      void copyText(code).then(() => { target.textContent = "복사됨"; setTimeout(() => { target.textContent = "복사"; }, 1200); });
    }
  }

  const grouped = useMemo(() => {
    const q = filter.trim().toLowerCase();
    const list = [...conversations].sort((a, b) => b.updatedAt - a.updatedAt)
      .filter(c => !q || c.title.toLowerCase().includes(q) || !!c.turns?.some(t => t.content.toLowerCase().includes(q)));
    const groups: [string, Conversation[]][] = [];
    for (const c of list) {
      const label = dayLabel(c.updatedAt);
      const last = groups[groups.length - 1];
      if (last && last[0] === label) last[1].push(c); else groups.push([label, [c]]);
    }
    return groups;
  }, [conversations, filter]);

  const status = !online ? "모델 연결 대기 중" : modelBusy && !pending ? "에이전트 작업이 모델 사용 중" : pending ? phase : "준비됨";
  const lastAssistant = [...turns].reverse().find(t => t.role === "assistant");
  const suggestions = mode === "project"
    ? ["이 프로젝트의 전체 구조를 설명해줘", "품목 등록 화면의 저장 흐름을 분석해줘", "로그인 인증은 어떻게 동작해?"]
    : ["React에서 상태 관리 방법들을 비교해줘", "이 SQL 쿼리를 최적화하는 방법은?", "Spring Boot 트랜잭션 전파를 설명해줘"];

  return <section className={`chatx ${sidebarOpen ? "" : "chatx-collapsed"}`} aria-label="로컬 모델 채팅">
    <aside className="chatx-side" aria-label="대화 목록">
      <div className="chatx-side-top">
        <button type="button" className="chatx-new" onClick={newChat} disabled={pending}>＋ 새 대화</button>
        <button type="button" className="chatx-icon" title="목록 접기" aria-label="목록 접기" onClick={() => setSidebarOpen(false)}>«</button>
      </div>
      <input className="chatx-search" placeholder="대화 검색" value={filter} onChange={e => setFilter(e.target.value)} />
      <nav className="chatx-list">
        {!grouped.length && <div className="chatx-muted chatx-pad">대화가 없습니다.</div>}
        {grouped.map(([label, items]) => <div key={label}>
          <div className="chatx-group">{label}</div>
          {items.map(c => <div key={c.id} className={`chatx-item ${c.id === activeId ? "active" : ""}`}>
            {renaming?.id === c.id
              ? <input autoFocus className="chatx-rename" value={renaming.text} onChange={e => setRenaming({ id: c.id, text: e.target.value })}
                  onBlur={() => { update(c.id, x => ({ ...x, title: renaming.text.trim() || x.title })); setRenaming(null); }}
                  onKeyDown={e => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); if (e.key === "Escape") setRenaming(null); }} />
              : <button type="button" className="chatx-item-title" onClick={() => !pending && void open(c.id)}
                  onDoubleClick={() => setRenaming({ id: c.id, text: c.title })} title={c.title}>
                  {c.mode === "project" && <span className="chatx-tag">프로젝트</span>}{c.title}
                </button>}
            <span className="chatx-item-actions">
              <button type="button" title="이름 바꾸기" aria-label="이름 바꾸기" onClick={() => setRenaming({ id: c.id, text: c.title })}>✎</button>
              <button type="button" title="삭제" aria-label="삭제" onClick={() => remove(c.id)}>🗑</button>
            </span>
          </div>)}
        </div>)}
      </nav>
    </aside>

    <div className="chatx-main">
      <header className="chatx-head">
        {!sidebarOpen && <button type="button" className="chatx-icon" title="목록 펼치기" aria-label="목록 펼치기" onClick={() => setSidebarOpen(true)}>»</button>}
        <div className="chatx-title">{active?.title || "새 대화"}</div>
        {!active && <div className="chatx-seg" role="group" aria-label="대화 모드">
          <button type="button" className={newMode === "chat" ? "on" : ""} onClick={() => setNewMode("chat")}>일반</button>
          <button type="button" className={newMode === "project" ? "on" : ""} onClick={() => setNewMode("project")}>프로젝트 분석</button>
        </div>}
        {active && <span className="chatx-tag">{mode === "project" ? "프로젝트 분석 (읽기 전용)" : "일반"}</span>}
        <span className={`chatx-status ${online && !(modelBusy && !pending) ? "ok" : ""}`}>{status}</span>
        <button type="button" className="chatx-icon" title="설정" aria-label="설정" aria-expanded={showSettings} onClick={() => setShowSettings(v => !v)}>⚙</button>
      </header>

      {showSettings && <div className="chatx-settings">
        <label>답변 최대 길이
          <select value={settings.maxTokens} onChange={e => setSettings(s => ({ ...s, maxTokens: Number(e.target.value) }))}>
            <option value={1024}>짧게 (1K 토큰)</option><option value={2048}>보통 (2K)</option><option value={4096}>길게 (4K)</option><option value={8192}>최대 (8K)</option>
          </select>
        </label>
        <label className="chatx-check"><input type="checkbox" checked={settings.thinking} onChange={e => setSettings(s => ({ ...s, thinking: e.target.checked }))} />
          생각 모드 (더 정확하지만 느림)</label>
        <label className="chatx-wide">사용자 지침 (모든 대화에 적용)
          <textarea rows={3} maxLength={4000} value={settings.instructions} placeholder="예: 답변은 항상 간결하게, 코드는 TypeScript로"
            onChange={e => setSettings(s => ({ ...s, instructions: e.target.value }))} />
        </label>
      </div>}

      <div className="chatx-transcript" ref={scroller} role="log" onClick={onTranscriptClick}
        onScroll={e => { const el = e.currentTarget; stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80; }}>
        <div className="chatx-column">
          {!turns.length && <div className="chatx-empty">
            <h2>{mode === "project" ? "프로젝트에 대해 물어보세요" : "무엇을 도와드릴까요?"}</h2>
            <p className="chatx-muted">{mode === "project" ? "관련 소스를 읽기 전용으로 찾아 근거와 함께 답합니다." : "로컬 모델과 대화합니다. 파일을 수정하거나 작업을 실행하지 않습니다."}</p>
            <div className="chatx-suggest">{suggestions.map(s => <button type="button" key={s} disabled={!canSend} onClick={() => send(s)}>{s}</button>)}</div>
          </div>}
          {turns.map(turn => <article key={turn.id} className={`chatx-msg chatx-${turn.role}`}>
            {turn.role === "user"
              ? editing?.id === turn.id
                ? <div className="chatx-edit">
                    <textarea autoFocus value={editing.text} onChange={e => setEditing({ id: turn.id, text: e.target.value })}
                      onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); saveEdit(); } if (e.key === "Escape") setEditing(null); }} />
                    <div><button type="button" onClick={() => setEditing(null)}>취소</button><button type="button" className="primary" disabled={!canSend} onClick={saveEdit}>보내기</button></div>
                  </div>
                : <div className="chatx-bubble">{turn.content}</div>
              : <div className="chatx-answer">
                  {turn.reasoning && <details className="chatx-reasoning" open={turn.id === streamingId && !turn.content}>
                    <summary>생각 과정</summary><div>{turn.reasoning}</div></details>}
                  {turn.content ? <Markdown text={turn.content} />
                    : turn.id === streamingId && <div className="chatx-typing"><span /><span /><span /> <em>{phase}</em></div>}
                  {turn.id === streamingId && turn.content && <span className="chatx-cursor" />}
                  {turn.stopped && <div className="chatx-note">사용자가 중단함</div>}
                  {turn.error && <div className="chatx-err" role="alert">{turn.error}</div>}
                  {!!turn.sources?.length && <details className="chatx-sources"><summary>참고한 소스 {turn.sources.length}개</summary>
                    <ul>{turn.sources.map(p => <li key={p}><code>{p}</code></li>)}</ul></details>}
                </div>}
            {turn.id !== streamingId && editing?.id !== turn.id && <div className="chatx-actions">
              <button type="button" onClick={() => void copyText(turn.content)} title="복사">복사</button>
              {turn.role === "user" && <button type="button" disabled={!canSend} onClick={() => setEditing({ id: turn.id, text: turn.content })}>편집</button>}
              {turn.role === "assistant" && turn.id === lastAssistant?.id && <button type="button" disabled={!canSend} onClick={() => regenerate(turn.id)}>다시 생성</button>}
              {turn.stats && <span className="chatx-stats">
                {turn.stats.completionTokens ?? "?"} 토큰 · {turn.stats.seconds?.toFixed(1)}초
                {turn.stats.completionTokens && turn.stats.seconds && turn.stats.firstTokenSeconds !== undefined
                  ? ` · ${(turn.stats.completionTokens / Math.max(0.1, turn.stats.seconds - turn.stats.firstTokenSeconds)).toFixed(1)} 토큰/초` : ""}
                {turn.stats.firstTokenSeconds !== undefined ? ` · 첫 응답 ${turn.stats.firstTokenSeconds.toFixed(1)}초` : ""}
                {turn.stats.promptTokens ? ` · 입력 ${turn.stats.promptTokens}${turn.stats.cachedTokens ? ` (캐시 ${turn.stats.cachedTokens})` : ""}` : ""}
                {turn.stats.finish === "length" ? " · 길이 제한으로 잘림" : ""}
              </span>}
            </div>}
          </article>)}
        </div>
      </div>

      <div className="chatx-composer-wrap">
        {error && <div className="chatx-err" role="alert">{error}</div>}
        <form className="chatx-composer" onSubmit={e => { e.preventDefault(); send(); }}>
          <textarea ref={input} value={draft} rows={1} maxLength={32000} aria-label="메시지"
            placeholder={!online ? "모델 연결 대기 중…" : modelBusy && !pending ? "에이전트 작업이 끝나면 보낼 수 있습니다" : mode === "project" ? "프로젝트 구조나 코드 동작을 물어보세요" : "메시지를 입력하세요 (Shift+Enter 줄바꿈)"}
            onChange={e => setDraft(e.target.value)}
            onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); send(); } }} />
          {pending
            ? <button type="button" className="chatx-send stop" onClick={() => abort.current?.abort()} title="중단" aria-label="중단">■</button>
            : <button type="submit" className="chatx-send" disabled={!canSend || !draft.trim()} title="보내기" aria-label="보내기">↑</button>}
        </form>
        <div className="chatx-foot chatx-muted">{model || "모델 없음"}{settings.thinking ? " · 생각 모드" : ""} · 로컬 모델은 틀릴 수 있습니다.</div>
      </div>
    </div>
  </section>;
}
