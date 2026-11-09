import { useEffect, useRef, useState } from "react";
import { apiFetch } from "./api";
import type { TaskQueue, QueueItem } from "./QueuePanel";
import "./home.css";
import { activities, type RunEvent } from "./activity";

type Option = { value: string; label: string; disabled?: boolean };
type ActiveJob = { id: string; goal?: string; status: string; started_at: string } | null;

const queueStatus: Record<string, [string, string]> = {
  planning: ["진행 중", "live"], running: ["진행 중", "live"], stopping: ["중지 중", "live"],
  succeeded: ["완료", "ok"], failed: ["실패", "bad"], stopped: ["중지됨", "muted"], interrupted: ["중단됨", "muted"],
};
const doing: Record<string, string> = { model: "AI가 코드를 작성하는 중", tool: "파일을 고치는 중", check: "만든 결과를 검사하는 중", running: "진행 중" };
const deployText: Record<string, string> = { running: "실행 중인 앱에 반영하는 중", succeeded: "실행 중인 앱에 반영됨", skipped: "앱에 이미 반영됨", failed: "앱 반영 실패" };

function since(start?: string | null, end?: string | null) {
  if (!start) return "";
  const s = Math.max(0, Math.round(((end ? new Date(end) : new Date()).getTime() - new Date(start).getTime()) / 1000));
  return s < 60 ? `${s}초` : `${Math.floor(s / 60)}분 ${s % 60}초`;
}
function when(iso: string) {
  return new Date(iso).toLocaleString("ko-KR", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" });
}
function examplesFor(screens: string[]) {
  const [a, b] = screens.filter(s => s !== "홈");
  if (!a) return ["거래처 등록 화면 만들어줘", "품목 등록 화면에 비고 칸 추가해줘"];
  return [`${a} 화면에 비고 칸 추가해줘`, `${b || a} 화면 결과 목록에 등록일 열 추가해줘`, "거래처 등록 화면 만들어줘"];
}

function Feed({ events }: { events: RunEvent[] }) {
  const items = activities(events);
  if (!items.length) return null;
  return <ul className="home-feed" aria-label="지금 하는 일" aria-live="polite">{items.map(a =>
    <li key={a.key} className={`f-${a.state}`}>
      <span className="home-feed-icon" aria-hidden>{a.state === "live" ? <span className="home-spin" /> : a.state === "ok" ? "✓" : "✕"}</span>
      <span className="home-feed-text">{a.text}</span>{a.detail && <span className="home-feed-detail">{a.detail}</span>}
    </li>)}</ul>;
}

function Step({ item, index, phase, onDetail, events }: { item: QueueItem & { started_at?: string; finished_at?: string; deploy?: string; deploy_note?: string }; index: number; phase: string; onDetail: (id: string) => void; events: RunEvent[] }) {
  const state = item.status === "succeeded" ? "ok" : item.status === "failed" ? "bad" : item.status === "running" ? "live" : "wait";
  const what = item.domain === "backend" ? "데이터·API" : "화면";
  return <li className={`home-step s-${state}`}>
    <span className="home-step-dot" aria-hidden>{state === "ok" ? "✓" : state === "bad" ? "!" : index + 1}</span>
    <div className="home-step-body">
      <div className="home-step-title"><span className="home-step-kind">{what}</span>{item.title}</div>
      <div className="home-step-sub">
        {state === "live" && <span>{doing[phase] || "진행 중"} · {since(item.started_at)}</span>}
        {state === "ok" && <span>완료{item.started_at ? ` · ${since(item.started_at, item.finished_at)}` : ""}</span>}
        {state === "bad" && <span className="home-fail">실패</span>}
        {state === "wait" && <span>대기</span>}
        {item.deploy && <span className={`home-deploy d-${item.deploy}`}>{deployText[item.deploy] || item.deploy}</span>}
        {item.job_id && <button type="button" className="home-link" onClick={() => onDetail(item.job_id!)}>실행 기록</button>}
      </div>
      {state === "live" && <Feed events={events} />}
    </div>
  </li>;
}

export default function HomePage(props: {
  token: string; goal: string; setGoal: (v: string) => void; canStart: boolean; blockedReason: string; onStart: () => void; busy: boolean;
  screens: string[]; models: Option[]; model: string; setModel: (v: string) => void; useQueue: boolean; setUseQueue: (v: boolean) => void;
  thinking: boolean; setThinking: (v: boolean) => void;
  queue: TaskQueue | null | undefined; active: ActiveJob; phase: string;
  onStopQueue: (id: string) => void; onResumeQueue: (id: string) => void; onStopJob: () => void;
  onOpenApp: () => void; onOpenHistory: () => void; onDetail: (jobId: string) => void; focusKey: number;
  events: RunEvent[]; eventsJob?: string;
}) {
  const { goal, setGoal, queue } = props;
  const area = useRef<HTMLTextAreaElement>(null);
  const [recent, setRecent] = useState<TaskQueue[]>([]), [settings, setSettings] = useState(false);
  useEffect(() => { area.current?.focus(); }, [props.focusKey]);
  const [, tick] = useState(0);
  useEffect(() => { const t = setInterval(() => tick(n => n + 1), 1000); return () => clearInterval(t); }, []);
  const eventsFor = (jobId?: string | null) => (jobId && jobId === props.eventsJob ? props.events : []);
  useEffect(() => {
    const el = area.current; if (!el) return;
    el.style.height = "auto"; el.style.height = Math.min(Math.max(el.scrollHeight, 88), 280) + "px";
  }, [goal]);
  useEffect(() => {
    const c = new AbortController();
    apiFetch("/api/queues", { signal: c.signal }).then(r => r.json()).then(d => setRecent(d.queues || [])).catch(() => {});
    return () => c.abort();
  }, [queue?.status, queue?.id]);
  const live = !!queue && ["planning", "running", "stopping"].includes(queue.status);
  const start = () => { if (props.canStart) props.onStart(); };
  const [label, tone] = queue ? queueStatus[queue.status] || [queue.status, "muted"] : ["", ""];
  const failedJob = queue?.items.find(i => i.status === "failed")?.job_id;
  const lastJob = [...(queue?.items || [])].reverse().find(i => i.job_id)?.job_id;
  const others = recent.filter(q => q.id !== queue?.id).slice(0, 8);

  return <div className="home">
    <section className="home-ask" aria-label="요청">
      <h1>무엇을 만들까요?</h1>
      <p className="home-lead">만들 화면이나 바꿀 내용을 평소 말투로 적으세요. AI가 화면과 데이터를 만들고, 검사를 통과하면 앱에 반영합니다.</p>
      <div className="home-box">
        <textarea ref={area} aria-label="요청 내용" value={goal} maxLength={16000} placeholder="예: 거래처 등록 화면 만들어줘"
          onChange={e => setGoal(e.target.value)} onKeyDown={e => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) { e.preventDefault(); start(); } }} />
        <div className="home-bar">
          <button type="button" className="home-ghost" aria-expanded={settings} onClick={() => setSettings(!settings)}>세부 설정</button>
          <span className="home-hint">⌘ Enter</span>
          <button type="button" className="home-run" disabled={!props.canStart} onClick={start}>만들기</button>
        </div>
        {settings && <div className="home-settings">
          <label>AI 모델
            <select value={props.model} disabled={props.busy || live} onChange={e => props.setModel(e.target.value)}>
              {props.models.map(m => <option key={m.value} value={m.value} disabled={m.disabled}>{m.label}</option>)}
            </select>
          </label>
          <label className="home-check"><input type="checkbox" checked={props.useQueue} onChange={e => props.setUseQueue(e.target.checked)} />요청을 작은 작업으로 나눠서 진행 (권장)</label>
          <label className="home-check"><input type="checkbox" checked={props.thinking} onChange={e => props.setThinking(e.target.checked)} />더 신중하게 생각하기 (느려짐)</label>
        </div>}
      </div>
      {props.blockedReason ? <p className="home-blocked">{props.blockedReason}</p>
        : !goal.trim() && <div className="home-examples">{examplesFor(props.screens).map(t =>
          <button key={t} type="button" onClick={() => { setGoal(t); area.current?.focus(); }}>{t}</button>)}</div>}
    </section>

    {queue && <section className={`home-card tone-${tone}`} aria-label="진행 상황">
      <header className="home-card-head">
        <span className={`home-pill tone-${tone}`}>{label}</span>
        <h2 title={queue.goal}>{queue.goal}</h2>
        <span className="home-time">{since(queue.created_at, live ? null : queue.finished_at)}</span>
      </header>
      {queue.status === "planning" && <p className="home-note">요청을 작업 단위로 나누는 중입니다…</p>}
      <ol className="home-steps">{queue.items.map((item, i) => <Step key={i} item={item} index={i} phase={props.phase} onDetail={props.onDetail} events={eventsFor(item.job_id)} />)}</ol>
      {queue.status === "failed" && <p className="home-fail-detail">{queue.detail}</p>}
      <div className="home-actions">
        {live && <button type="button" className="home-btn" disabled={props.busy || queue.status === "stopping"} onClick={() => props.onStopQueue(queue.id)}>중지</button>}
        {["failed", "stopped", "interrupted"].includes(queue.status) && <button type="button" className="home-btn primary" disabled={props.busy} onClick={() => props.onResumeQueue(queue.id)}>이어서 실행</button>}
        {queue.status === "succeeded" && <button type="button" className="home-btn primary" onClick={props.onOpenApp}>앱에서 보기</button>}
        {queue.status === "succeeded" && <button type="button" className="home-btn" onClick={props.onOpenHistory}>변경 이력</button>}
        {(failedJob || lastJob) && <button type="button" className="home-link" onClick={() => props.onDetail((failedJob || lastJob)!)}>실행 기록 자세히</button>}
      </div>
    </section>}

    {!queue && props.active && <section className="home-card tone-live" aria-label="진행 상황">
      <header className="home-card-head"><span className="home-pill tone-live">진행 중</span><h2>{props.active.goal}</h2><span className="home-time">{since(props.active.started_at)}</span></header>
      <Feed events={eventsFor(props.active.id)} />
      <div className="home-actions"><button type="button" className="home-btn" onClick={props.onStopJob}>중지</button>
        <button type="button" className="home-link" onClick={() => props.onDetail(props.active!.id)}>실행 기록 자세히</button></div>
    </section>}

    {others.length > 0 && <section className="home-recent" aria-label="최근 요청">
      <h3>최근 요청</h3>
      <ul>{others.map(q => { const [l, t] = queueStatus[q.status] || [q.status, "muted"]; const job = [...q.items].reverse().find(i => i.job_id)?.job_id;
        return <li key={q.id}>
          <span className={`home-pill tone-${t}`}>{l}</span>
          <span className="home-recent-goal" title={q.goal}>{q.goal}</span>
          <span className="home-recent-meta">{q.items.length ? `작업 ${q.items.filter(i => i.status === "succeeded").length}/${q.items.length}` : ""} · {when(q.created_at)}</span>
          {job && <button type="button" className="home-link" onClick={() => props.onDetail(job)}>기록</button>}
        </li>; })}</ul>
    </section>}
  </div>;
}
