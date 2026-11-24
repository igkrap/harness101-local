import { useEffect, useMemo, useRef, useState } from "react";
import { apiFetch } from "./api";
import type { TaskQueue } from "./QueuePanel";
import { ChangesPanel } from "./ChangesPanel";
import Preview from "./Preview";
import FlowMapPage from "./FlowMapPage";
import { Operation } from "./HomePage";
import "./chathome.css";

type Step = { title: string; detail: string; state: "running" | "done" | "refused" };
type Live = { goal: string; queue?: string | null; started: number; ended: number | null; ok: boolean | null; now: number; stopping?: boolean;
  steps: Step[]; checks: { total: number; passed: number }; model?: { title: string; reading?: { done: number; total: number }; chars: number; ended: number | null } };
type Dirty = { path: string; status: string; staged?: boolean; unstaged?: boolean };
type Commit = { sha: string; short: string; author: string; kind: string; date: string; subject: string; job_id: string | null };
type Git = { status: { branch: string; branches: string[]; remote: string; ahead: number | null; behind?: number | null; dirty: Dirty[]; unrecorded?: { site: string[]; files: string[] } }; commits: Commit[] };
type Panel = "preview" | "flow" | "changes" | "git" | "deploy";

const LIVE = ["planning", "running", "stopping"];
const two = (n: number) => String(n).padStart(2, "0");
const stamp = (iso: string) => { const d = new Date(iso); return `${d.getFullYear()}/${two(d.getMonth() + 1)}/${two(d.getDate())} ${two(d.getHours())}:${two(d.getMinutes())}`; };
const took = (start?: string | null, end?: string | null) => {
  if (!start) return "";
  const s = Math.max(0, Math.round(((end ? new Date(end) : new Date()).getTime() - new Date(start).getTime()) / 1000));
  return s < 60 ? `${s}초` : `${Math.floor(s / 60)}분 ${s % 60}초`;
};
/** The one line a person needs from a long result: why it did not go through, or what was made. */
function headline(q: TaskQueue): string {
  const lines = (q.detail || "").split("\n").map(line => line.trim()).filter(Boolean);
  if (q.status === "succeeded") {        // what was made: the screens and the flow, rather than how many steps it took
    const made = lines.filter(line => /^(새 화면|화면 수정|업무 흐름을 등록)/.test(line)).map(line => line.replace(/\s*\([a-z0-9_]+\)\s*$/, ""));
    if (made.length) return [...new Set(made)].join(" · ");
  }
  const reason = lines.find(line => /적용하지 않|못했|않았|멈췄|만들 수 없|되지 않/.test(line));
  return reason || lines[0] || "";
}
/** A step as a person reads it: the harness's own names for the model's calls said in words. */
const CALLS: Record<string, string> = { "plan-matches-request": "계획을 요청과 맞춰 봄", "matches-request": "결과를 요청과 맞춰 봄", "request-as-a-whole": "요청 전체를 맞춰 봄",
  "removed-on-purpose": "지워진 항목이 요청한 것인지 확인" };
function stepTitle(title: string): string {
  const call = title.match(/^모델:\s*(.+)$/);
  if (!call) return title;
  const name = call[1].trim();
  return CALLS[name] || (/^define-\d+$/.test(name) ? "모델이 정의를 씀" : `모델: ${name}`);
}
function outcome(q: TaskQueue): [string, string] {
  if (q.undone) return ["원복함", "muted"];
  if (LIVE.includes(q.status)) return [q.status === "stopping" ? "멈추는 중" : "만드는 중", "live"];
  if (q.status === "succeeded") return [q.definition_result?.first_try ? "재시도 후 완료" : "완료", "ok"];
  if (q.status === "stopped") return ["중지함", "muted"];
  return ["적용하지 않음", "bad"];
}

function LiveSteps({ live }: { live: Live }) {
  const reading = live.model?.reading, writing = live.model && !live.model.ended && !reading;
  return <div className="ch-steps">
    {live.steps.slice(-8).map((step, index) => <div key={index} className={`ch-step s-${step.state}`}>
      <span aria-hidden>{step.state === "done" ? "✓" : step.state === "refused" ? "✕" : "●"}</span>
      <span>{stepTitle(step.title)}{step.detail ? <em> · {step.detail.slice(0, 90)}</em> : null}</span></div>)}
    {reading && <div className="ch-step s-running"><span aria-hidden>●</span><span>모델이 입력을 읽는 중 · {Math.round(100 * reading.done / Math.max(1, reading.total))}%</span></div>}
    {writing && <div className="ch-step s-running"><span aria-hidden>●</span><span>모델이 정의를 쓰는 중 · {live.model!.chars.toLocaleString()}자</span></div>}
    {live.checks.total > 0 && <div className="ch-meta">점검 {live.checks.passed}/{live.checks.total} 통과</div>}
  </div>;
}

function GitPanel({ git, busy, onOrder, onOpenHistory }: { git: Git | null; busy: boolean; onOrder: (text: string) => void; onOpenHistory: () => void }) {
  if (!git) return <p className="ch-dim">형상 관리 상태를 읽는 중…</p>;
  const { status, commits } = git;
  const site = status.unrecorded?.site || [];
  const staged = status.dirty.filter(file => file.staged), unstaged = status.dirty.filter(file => file.staged === undefined || file.unstaged);
  const word = (file: Dirty) => file.status === "added" ? "새 파일" : file.status === "deleted" ? "지움" : "고침";
  const nothing = !site.length && !status.dirty.length;
  return <div className="ch-git">
    <div className="ch-git-head">
      <div><span className="ch-dim">작업 공간</span><b>{status.branch || "-"}</b></div>
      <div><span className="ch-dim">원격</span><b>{status.remote ? (status.ahead ? `올리지 않은 기록 ${status.ahead}` : "맞춰져 있음") : "연결 안 됨"}</b></div>
      <div><span className="ch-dim">마지막 기록</span><b>{commits[0] ? `${commits[0].subject.slice(0, 22)}` : "-"}</b></div>
    </div>
    <section><h4>1. 개발 사이트에만 있음 <span className="ch-count">{site.length}</span></h4>
      {site.length ? <ul>{site.map(name => <li key={name}>{name}</li>)}</ul> : <p className="ch-dim">없음</p>}</section>
    <section><h4>2. 파일 변경 · 기록 준비 전 <span className="ch-count">{unstaged.length}</span></h4>
      {unstaged.length ? <ul>{unstaged.map(file => <li key={file.path}><span className={`ch-file f-${file.status}`}>{word(file)}</span>{file.path}</li>)}</ul> : <p className="ch-dim">없음</p>}</section>
    {status.dirty.some(file => file.staged !== undefined) && <section><h4>3. 기록 준비됨 (스테이징) <span className="ch-count">{staged.length}</span></h4>
      {staged.length ? <ul>{staged.map(file => <li key={file.path}><span className={`ch-file f-${file.status}`}>{word(file)}</span>{file.path}</li>)}</ul> : <p className="ch-dim">없음</p>}</section>}
    <div className="ch-actions">
      <button type="button" className="ch-btn pri" disabled={busy || nothing} onClick={() => onOrder("지금까지 만든 것을 커밋해줘")}>기록하기</button>
      {status.remote && !!status.ahead && <button type="button" className="ch-btn" disabled={busy} onClick={() => onOrder("원격 저장소에 올려줘")}>원격에 올리기</button>}
      <button type="button" className="ch-btn" onClick={onOpenHistory}>변경 이력 전체</button>
    </div>
    <section><h4>최근 기록</h4>
      <ul className="ch-commits">{commits.slice(0, 12).map(commit => <li key={commit.sha}>
        <span className={`ch-who k-${commit.kind}`}>{commit.kind === "model" ? "모델" : commit.kind === "person" ? "사람" : "플랫폼"}</span>
        <span className="ch-subject" title={commit.subject}>{commit.subject}</span><span className="ch-date">{stamp(commit.date)}</span></li>)}</ul></section>
  </div>;
}

/**
 * The platform as a conversation: what was asked, what is being done, what came of it - one thread per project, newest at the
 * bottom - with what the work produced (the app, the flow map, the changes, the project's git) in a panel beside it.
 */
export default function ChatHome(props: {
  token: string; goal: string; setGoal: (v: string) => void; canStart: boolean; blockedReason: string; onStart: () => void; busy: boolean;
  queue: TaskQueue | null | undefined; onStopQueue: (id: string) => void; onResumeQueue: (id: string) => void;
  onUndo: (id: string) => Promise<void>; onOrder: (goal: string) => Promise<void>;
  onDetail: (jobId: string) => void; onOpenMonitor: () => void; onOpenHistory: () => void; onOpenParts: () => void;
}) {
  const { queue } = props;
  const [recent, setRecent] = useState<TaskQueue[]>([]), [live, setLive] = useState<Live | null>(null), [git, setGit] = useState<Git | null>(null);
  const [panel, setPanel] = useState<Panel | null>("git"), [panelJob, setPanelJob] = useState(""), [undoing, setUndoing] = useState("");
  const thread = useRef<HTMLDivElement>(null), area = useRef<HTMLTextAreaElement>(null);
  const running = !!queue && LIVE.includes(queue.status);
  const [, tick] = useState(0);
  useEffect(() => { const t = setInterval(() => tick(n => n + 1), 1000); return () => clearInterval(t); }, []);
  const refresh = () => {
    apiFetch("/api/queues").then(r => r.json()).then(d => setRecent(d.queues || [])).catch(() => {});
    apiFetch("/api/history?limit=20").then(r => r.json()).then(d => { if (d.status) setGit(d); }).catch(() => {});
  };
  useEffect(refresh, [queue?.id, queue?.status]);
  useEffect(() => {          // the request being made: its steps, read from the harness as it goes
    if (!running) { setLive(null); return; }
    let stop = false, timer: ReturnType<typeof setTimeout>;
    const read = () => apiFetch("/api/tools/live", { cache: "no-store" }).then(r => r.json()).then(d => { if (!stop) setLive(d && d.steps ? d : null); })
      .catch(() => {}).finally(() => { if (!stop) timer = setTimeout(read, 1500); });
    read();
    return () => { stop = true; clearTimeout(timer); };
  }, [running]);
  const items = useMemo(() => {
    const all = new Map<string, TaskQueue>();
    for (const q of recent) all.set(q.id, q);
    if (queue) all.set(queue.id, queue);
    return [...all.values()].sort((a, b) => String(a.created_at).localeCompare(String(b.created_at))).slice(-40);
  }, [recent, queue]);
  useEffect(() => { thread.current?.scrollTo({ top: thread.current.scrollHeight }); }, [items.length, live?.steps.length]);
  useEffect(() => {
    const el = area.current; if (!el) return;
    el.style.height = "auto"; el.style.height = Math.min(Math.max(el.scrollHeight, 52), 220) + "px";
  }, [props.goal]);
  const newest = items.filter(q => q.route === "definition" && q.definition_result?.status === "applied" && !q.undone).at(-1);
  const undo = (q: TaskQueue) => { if (undoing || !window.confirm(`"${q.goal.slice(0, 60)}" 요청으로 바뀐 것을 원복할까요?`)) return;
    setUndoing(q.id); void props.onUndo(q.id).catch(e => window.alert(String(e instanceof Error ? e.message : e))).finally(() => { setUndoing(""); refresh(); }); };
  const open = (which: Panel, job?: string | null) => { setPanel(which); if (job) setPanelJob(job); };
  const loose = git ? (git.status.unrecorded?.site.length || 0) + git.status.dirty.length : 0;
  const order = (text: string) => { void props.onOrder(text); };
  const suggestions: [string, () => void][] = [
    ["앱 보기", () => open("preview")], ["업무 흐름도", () => open("flow")], ["형상 관리", () => open("git")],
    ["기록해줘", () => order("지금까지 만든 것을 커밋해줘")], ["셋업 팩 만들어줘", () => order("운영 셋업 팩 만들어줘")],
  ];
  const send = () => { if (props.canStart) props.onStart(); };

  return <div className={`ch${panel ? " with-panel" : ""}`}>
    <div className="ch-main">
      <div className="ch-thread" ref={thread} aria-label="대화" aria-live="polite">
        {!items.length && <div className="ch-empty"><b>무엇을 만들까요?</b><span>평소 말투로 적으면 화면을 만들고, 점검을 통과한 것만 앱에 반영합니다.</span></div>}
        {items.map(q => {
          const [label, tone] = outcome(q), r = q.definition_result, job = [...q.items].reverse().find(i => i.job_id)?.job_id || null;
          const isLive = LIVE.includes(q.status), mine = live && (live.queue === q.id || isLive) ? live : null;
          const why = headline(q), part = /부품 요청/.test(q.detail || "");
          return <div key={q.id} className="ch-turn">
            <div className="ch-me"><p>{q.goal}</p><span>{stamp(q.created_at)}</span></div>
            <div className={`ch-card t-${tone}`}>
              <header><span className={`ch-pill t-${tone}`}>{label}</span>
                <span className="ch-dim">{took(q.created_at, isLive ? null : q.finished_at)}{r?.checks ? ` · 점검 ${r.checks}개` : ""}{r?.title && !isLive ? ` · ${r.title}` : ""}</span></header>
              {isLive && (mine ? <LiveSteps live={mine} /> : <p className="ch-dim">{q.status === "planning" ? "요청을 읽고 계획하는 중…" : "진행 중…"}</p>)}
              {!isLive && why && <p className={tone === "bad" ? "ch-why" : "ch-said"}>{why}</p>}
              {!isLive && r?.first_try && <p className="ch-dim">처음 시도가 떨어진 이유: {(r.first_try.flows || []).join(" / ").slice(0, 200)} - 이유를 들려주고 다시 만들어 통과했습니다.</p>}
              {!isLive && q.detail && q.detail.split("\n").filter(Boolean).length > 1 && <details className="ch-more"><summary>자세히</summary><pre>{q.detail}</pre></details>}
              <div className="ch-actions">
                {isLive && <button type="button" className="ch-btn" onClick={props.onOpenMonitor}>실시간으로 보기</button>}
                {isLive && <button type="button" className="ch-btn" disabled={props.busy || q.status === "stopping"} onClick={() => props.onStopQueue(q.id)}>멈추기</button>}
                {q.status === "succeeded" && !q.undone && <button type="button" className="ch-btn pri" onClick={() => open("preview")}>앱에서 보기</button>}
                {q.status === "succeeded" && !q.undone && <button type="button" className="ch-btn" onClick={() => open("flow")}>흐름도</button>}
                {job && !isLive && <button type="button" className="ch-btn" onClick={() => open("changes", job)}>바뀐 내용</button>}
                {newest?.id === q.id && !running && <button type="button" className="ch-btn" disabled={!!undoing} onClick={() => undo(q)}>{undoing === q.id ? "원복하는 중…" : "원복"}</button>}
                {["failed", "stopped", "interrupted"].includes(q.status) && <button type="button" className="ch-btn" onClick={() => { props.setGoal(q.goal); area.current?.focus(); }}>다시 요청</button>}
                {part && <button type="button" className="ch-btn" onClick={props.onOpenParts}>부품 요청 보기</button>}
                {job && <button type="button" className="ch-link" onClick={() => props.onDetail(job)}>실행 기록</button>}
              </div>
            </div>
          </div>;
        })}
        {loose > 0 && !running && <div className="ch-card t-wait ch-notice">
          <header><span className="ch-pill t-wait">기록 안 됨</span><span>아직 기록하지 않은 변경이 {loose}개 있습니다</span></header>
          <div className="ch-actions"><button type="button" className="ch-btn pri" disabled={props.busy} onClick={() => order("지금까지 만든 것을 커밋해줘")}>기록하기</button>
            <button type="button" className="ch-btn" onClick={() => open("git")}>무엇이 바뀌었나</button></div></div>}
      </div>
      <div className="ch-compose">
        {props.blockedReason ? <p className="ch-blocked">{props.blockedReason}</p>
          : <div className="ch-sug">{suggestions.map(([label, act]) => <button key={label} type="button" onClick={act}>{label}</button>)}</div>}
        <div className="ch-box">
          <textarea ref={area} aria-label="요청 내용" value={props.goal} maxLength={16000} placeholder="무엇을 만들까요?"
            onChange={e => props.setGoal(e.target.value)} onKeyDown={e => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) { e.preventDefault(); send(); } }} />
          <button type="button" className="ch-send" disabled={!props.canStart} onClick={send} aria-label="보내기">보내기 <kbd>⌘↵</kbd></button>
        </div>
      </div>
    </div>
    {panel && <aside className="ch-panel" aria-label="작업 패널">
      <div className="ch-tabs" role="tablist">
        {([["preview", "앱 미리보기"], ["flow", "흐름도"], ["changes", "바뀐 내용"], ["git", "형상 관리"], ["deploy", "배포"]] as [Panel, string][]).map(([key, label]) =>
          <button key={key} type="button" role="tab" aria-selected={panel === key} className={panel === key ? "on" : ""} onClick={() => setPanel(key)}>{label}</button>)}
        <span style={{ flex: 1 }} /><button type="button" className="ch-close" aria-label="패널 닫기" onClick={() => setPanel(null)}>×</button>
      </div>
      <div className="ch-panel-body">
        {panel === "preview" && <Preview token={props.token} />}
        {panel === "flow" && <FlowMapPage />}
        {panel === "changes" && (panelJob ? <ChangesPanel key={panelJob} jobId={panelJob} embedded autoOpen /> : <p className="ch-dim">대화의 결과 카드에서 「바뀐 내용」을 누르세요.</p>)}
        {panel === "git" && <GitPanel git={git} busy={props.busy || running} onOrder={order} onOpenHistory={props.onOpenHistory} />}
        {panel === "deploy" && <Operation refreshKey={`${queue?.id}:${queue?.status}`} busy={props.busy || running} onOrder={order} />}
      </div>
    </aside>}
    {!panel && <button type="button" className="ch-reopen" onClick={() => setPanel("git")}>작업 패널 열기</button>}
  </div>;
}
