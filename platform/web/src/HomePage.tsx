import { useEffect, useRef, useState } from "react";
import { apiFetch, apiUrl, projectId } from "./api";
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
  const d = new Date(iso), two = (n: number) => String(n).padStart(2, "0");
  return `${two(d.getMonth() + 1)}-${two(d.getDate())} ${two(d.getHours())}:${two(d.getMinutes())}`;
}
function examplesFor(screens: string[]) {
  const [a, b] = screens.filter(s => s !== "홈");
  if (!a) return ["거래처 등록 화면 만들어줘", "품목 등록 화면에 비고 칸 추가해줘"];
  return [`${a} 화면에 비고 칸 추가해줘`, `${b || a} 화면 결과 목록에 등록일 열 추가해줘`, "거래처 등록 화면 만들어줘"];
}

type PackFile = { name: string; size: number };
type Pack = { stamp: string; started_at: string; screens: number; files: { install: PackFile; update: PackFile } };
type ReleaseStatus = { project: string; packs: Pack[]; current: boolean; unrecorded?: { site: string[]; files: string[] }; git?: { branch: string; remote: string; ahead: number | null } | null; pending: { new: string[]; changed: string[]; removed: number; program: boolean } | null; error?: string };
const mb = (bytes: number) => `${Math.round(bytes / 1024 / 1024)}MB`;
function PackLinks({ pack }: { pack: Pack }) {
  return <>
    <a href={apiUrl(`/api/release/packs/${pack.files.install.name}`)} title="빈 윈도우 서버에: 자바, PostgreSQL, DB, 서비스 등록까지. install.bat 을 관리자 권한으로 실행">최초 셋업 팩 ({mb(pack.files.install.size)})</a>
    <a href={apiUrl(`/api/release/packs/${pack.files.update.name}`)} title="이미 설치된 서버에: update.bat 을 관리자 권한으로 실행. 더 새 버전이 설치된 서버에는 update.bat -Force">업데이트 팩 ({mb(pack.files.update.size)})</a>
  </>;
}
/**
 * Deployment in one line. "현재 버전 배포 다운로드" hands over the setup packs of what the project holds right now (making them
 * first when the pack is behind). Only the current version's packs are kept.
 */
function Operation({ refreshKey, busy, onOrder }: { refreshKey: string; busy: boolean; onOrder: (goal: string) => void }) {
  const [status, setStatus] = useState<ReleaseStatus | null>(null);
  const [open, setOpen] = useState(false), [wanted, setWanted] = useState(false);
  useEffect(() => {
    const c = new AbortController();
    apiFetch("/api/release", { signal: c.signal }).then(r => r.json()).then(d => setStatus(d.status)).catch(() => {});
    return () => c.abort();
  }, [refreshKey]);
  // Asked for while the newest pack was behind: the downloads open by themselves once the new pack is there.
  useEffect(() => { if (wanted && status?.current) { setWanted(false); setOpen(true); } }, [wanted, status?.current]);
  if (!status) return null;
  const pending = status.pending, newest = status.packs[0];
  const waiting = pending ? pending.new.length + pending.changed.length + pending.removed : 0;
  const names = pending ? [...pending.new, ...pending.changed] : [];
  const behind = !status.current;
  const loose = [...(status.unrecorded?.site ?? []), ...(status.unrecorded?.files ?? [])];
  const download = () => { if (behind) { setOpen(false); setWanted(true); onOrder("운영 셋업 팩 만들어줘"); } else setOpen(value => !value); };
  return <section className="home-ops-box" aria-label="배포">
    <div className="home-ops">
      <strong>배포</strong>
      {!newest ? <span className="dim">아직 만든 버전이 없습니다</span>
        : status.current ? <span className="dim">현재 버전 {when(newest.started_at)} · 화면 {newest.screens}개</span>
        : <span className="home-ops-wait" title={names.join(", ")}>마지막 버전({when(newest.started_at)}) 뒤로 바뀜{waiting ? `: 화면 ${waiting}개` : ""}{pending?.program ? `${waiting ? ", " : ": "}프로그램` : ""}</span>}
      {wanted && <span className="dim">현재 버전을 만드는 중… 끝나면 받기가 열립니다</span>}
      {status.error && <span className="dim" title={status.error}>상태를 읽지 못함</span>}
      <span style={{ flex: 1 }} />
      {status.git && <span className="dim" title={status.git.remote ? `원격: ${status.git.remote}` : "원격 저장소 없음"}>작업 공간 {status.git.branch}{status.git.ahead ? ` · 올리지 않은 기록 ${status.git.ahead}` : ""}</span>}
      <button type="button" className={`home-btn${loose.length ? " is-waiting" : ""}`} disabled={busy} title={loose.length ? `아직 기록하지 않은 변경: ${loose.join(", ")}` : "요청이 성공하면 자동으로 기록됩니다. 그 밖에 바뀐 것이 있으면 여기서 기록합니다."} onClick={() => onOrder("지금까지 만든 것을 커밋해줘")}>커밋{loose.length ? ` (${loose.length})` : ""}</button>
      <button type="button" className="home-btn primary" disabled={busy || wanted} aria-expanded={open} title={behind ? "지금 상태로 셋업 팩을 만든 뒤 받습니다" : "현재 버전의 셋업 팩을 받습니다"} onClick={download}>현재 버전 배포 다운로드</button>
    </div>
    {open && newest && status.current && <div className="home-ops-files" data-ui="pack-current"><span>현재 버전 {when(newest.started_at)}</span><PackLinks pack={newest} /></div>}
  </section>;
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

function Step({ item, index, phase, onDetail, events }: { item: QueueItem & { started_at?: string; finished_at?: string; deploy?: string; deploy_note?: string; note?: string }; index: number; phase: string; onDetail: (id: string) => void; events: RunEvent[] }) {
  const state = item.status === "succeeded" ? "ok" : item.status === "failed" ? "bad" : item.status === "running" ? "live" : "wait";
  const what = item.domain === "backend" ? "데이터·API" : item.domain === "release" ? "운영" : "화면";
  return <li className={`home-step s-${state}`}>
    <span className="home-step-dot" aria-hidden>{state === "ok" ? "✓" : state === "bad" ? "!" : index + 1}</span>
    <div className="home-step-body">
      <div className="home-step-title"><span className="home-step-kind">{what}</span>{item.title}</div>
      <div className="home-step-sub">
        {state === "live" && <span>{item.domain === "release" ? item.note || "진행 중" : doing[phase] || "진행 중"}{item.started_at ? ` · ${since(item.started_at)}` : ""}</span>}
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
  /** Take back what a request applied; resolves when done. */ onUndo: (id: string) => Promise<void>;
  /** Carry out an order at once (record, make a setup pack, install it here) - the same as typing it into the box and pressing 만들기. */ onOrder: (goal: string) => Promise<void>;
  events: RunEvent[]; eventsJob?: string;
}) {
  const { goal, setGoal, queue } = props;
  const area = useRef<HTMLTextAreaElement>(null);
  const [recent, setRecent] = useState<TaskQueue[]>([]), [settings, setSettings] = useState(false);
  // The project every request here goes to, said out loud beside the request box.
  const [project, setProject] = useState<{ title: string; name: string; kind: string } | null>(null);
  useEffect(() => { const c = new AbortController();
    apiFetch("/api/projects", { signal: c.signal }).then(r => r.json()).then(d => { type P = { id: string; name: string; site?: { title?: string; kind?: string } };
      const list: P[] = d.projects || [], mine = list.find(p => p.id === projectId) || (projectId === "default" ? list[0] : undefined);
      const kind = (d.kinds || []).find((k: { id: string; label: string }) => k.id === (mine?.site?.kind || "business"))?.label || "";
      if (mine) setProject({ title: mine.site?.title || mine.name, name: mine.name, kind }); }).catch(() => {});
    return () => c.abort(); }, []);
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
  const [undoing, setUndoing] = useState("");
  const canUndo = (q: TaskQueue) => q.route === "definition" && !q.undone && !!q.definition_result && (q.definition_result.status === "applied" || q.definition_result.status === "partial");
  const undo = (q: TaskQueue) => { if (undoing || !window.confirm(`"${q.goal.slice(0, 60)}" 요청으로 바뀐 것을 되돌릴까요?`)) return;
    setUndoing(q.id); void props.onUndo(q.id).catch(e => window.alert(String(e instanceof Error ? e.message : e))).finally(() => { setUndoing("");
      apiFetch("/api/queues").then(r => r.json()).then(d => setRecent(d.queues || [])).catch(() => {}); }); };
  const others = recent.filter(q => q.id !== queue?.id).slice(0, 40);

  return <div className="home">
    <section className="home-ask" aria-label="요청">
      <h1>{project && <span className="home-project" title={`요청은 이 프로젝트에서 진행됩니다 (${project.name})`}>{project.title}{project.kind && <em>{project.kind}</em>}</span>}무엇을 만들까요?</h1>
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

    <Operation refreshKey={`${queue?.id}:${queue?.status}`} busy={props.busy || live} onOrder={text => { void props.onOrder(text); }} />

    {queue && <section className={`home-card tone-${tone}`} aria-label="진행 상황">
      <header className="home-card-head">
        <span className={`home-pill tone-${tone}`}>{label}</span>
        <h2 title={queue.goal}>{queue.goal}</h2>
        <span className="home-time">{since(queue.created_at, live ? null : queue.finished_at)}</span>
      </header>
      {queue.status === "planning" && <p className="home-note">요청을 작업 단위로 나누는 중입니다…</p>}
      <ol className="home-steps">{queue.items.map((item, i) => <Step key={i} item={item} index={i} phase={props.phase} onDetail={props.onDetail} events={eventsFor(item.job_id)} />)}</ol>
      {queue.status === "failed" && <p className="home-fail-detail">{queue.detail}</p>}
      {queue.status === "succeeded" && queue.detail && <p className="home-note home-result">{queue.detail}</p>}
      <div className="home-actions">
        {live && <button type="button" className="home-btn" disabled={props.busy || queue.status === "stopping"} onClick={() => props.onStopQueue(queue.id)}>중지</button>}
        {["failed", "stopped", "interrupted"].includes(queue.status) && <button type="button" className="home-btn primary" disabled={props.busy} onClick={() => props.onResumeQueue(queue.id)}>이어서 실행</button>}
        {queue.status === "succeeded" && <button type="button" className="home-btn primary" onClick={props.onOpenApp}>앱에서 보기</button>}
        {queue.status === "succeeded" && <button type="button" className="home-btn" onClick={props.onOpenHistory}>변경 이력</button>}
        {canUndo(queue) && <button type="button" className="home-btn" disabled={!!undoing || live} onClick={() => undo(queue)}>{undoing === queue.id ? "되돌리는 중…" : "되돌리기"}</button>}
        {queue.undone && <span className="home-time">되돌린 요청</span>}
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
      <table className="biz-table">
        <colgroup><col style={{ width: 62 }} /><col /><col style={{ width: "22%" }} /><col style={{ width: 58 }} /><col style={{ width: 56 }} /><col style={{ width: 84 }} /><col style={{ width: 104 }} /><col style={{ width: 104 }} /></colgroup>
        <thead><tr><th>상태</th><th>요청</th><th>결과</th><th>구분</th><th className="num">검사</th><th className="num">걸린 시간</th><th>일시</th><th /></tr></thead>
        <tbody>{others.map(q => { const [l, t] = queueStatus[q.status] || [q.status, "muted"]; const job = [...q.items].reverse().find(i => i.job_id)?.job_id; const r = q.definition_result;
          const failed = r?.failed?.length || 0;
          const outcome = r ? (r.status === "applied" ? `${r.title || ""}${r.key ? ` (${r.key})` : ""}` : (q.detail || "").split("\n").filter(Boolean).pop() || "") : (q.detail || "").split("\n")[0] || "";
          return <tr key={q.id}>
            <td><span className={`biz-tag tone-${t}`}>{l}</span></td>
            <td title={q.goal}>{q.goal}</td>
            <td className="dim" title={q.detail || outcome}>{outcome}</td>
            <td className="dim">{r ? (r.action === "change" ? "수정" : r.action === "create" ? "신규" : "") : q.items.length ? `작업 ${q.items.filter(i => i.status === "succeeded").length}/${q.items.length}` : ""}</td>
            <td className="num">{r?.checks ? (failed ? `${r.checks - failed}/${r.checks}` : r.checks) : ""}</td>
            <td className="num">{r?.seconds ? `${Math.round(r.seconds)}초` : since(q.created_at, q.finished_at)}</td>
            <td className="dim">{when(q.created_at)}</td>
            <td>{job && <button type="button" className="biz-link" onClick={() => props.onDetail(job)}>기록</button>}
              {canUndo(q) && <button type="button" className="biz-link" style={{ marginLeft: 8 }} disabled={!!undoing} onClick={() => undo(q)}>{undoing === q.id ? "…" : "되돌리기"}</button>}
              {q.undone && <span className="dim" style={{ marginLeft: 8 }}>되돌림</span>}</td>
          </tr>; })}</tbody>
      </table>
    </section>}
  </div>;
}
