import { useEffect, useRef, useState } from "react";
import { apiFetch } from "./api";
import "./monitor.css";

type Step = { title: string; detail: string; state: "running" | "done" | "refused"; started: number; ended: number | null };
type Check = { description: string; passed: boolean; detail: string; at: number; step: string };
type Live = {
  goal: string; started: number; ended: number | null; ok: boolean | null; said: string; calls: number; tokens: number; now: number;
  steps: Step[]; checks: { total: number; passed: number; recent: Check[]; failed: Check[] };
  model?: { name: string; model: string; title: string; started: number; ended: number | null; first?: number | null; text: string; thinking: string; tokens: number; chunks: number; chars: number };
};

const clock = (seconds: number) => { const s = Math.max(0, Math.round(seconds)); return s >= 3600 ? `${Math.floor(s / 3600)}:${String(Math.floor(s / 60) % 60).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}` : `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`; };
const hms = (epoch: number) => { const d = new Date(epoch * 1000); return [d.getHours(), d.getMinutes(), d.getSeconds()].map(n => String(n).padStart(2, "0")).join(":"); };

/**
 * 실시간 보기: what the request being made is doing right now - the steps so far, what the local model is writing as it
 * writes it, and each check as it passes or fails. Read from the harness while it runs (GET /api/tools/live); nothing kept.
 */
export default function MonitorPage() {
  const [live, setLive] = useState<Live | null>(null), [error, setError] = useState(""), [thinking, setThinking] = useState(false);
  const [offset, setOffset] = useState(0);          // server clock minus this browser's, so elapsed times tick between reads
  const [tick, setTick] = useState(0);
  const out = useRef<HTMLPreElement>(null), follow = useRef(true);
  const first = useRef<{ call: number; at: number } | null>(null);      // when the model's first word was seen (before it: reading its input)
  useEffect(() => {
    let timer: ReturnType<typeof setTimeout>, stop = false;
    const read = async () => {
      try {
        const r = await apiFetch("/api/tools/live", { cache: "no-store" }); const d = await r.json();
        if (!r.ok) throw Error(d.error || "읽지 못했습니다.");
        if (!stop) { setLive(d.goal ? d : null); setError(""); if (d.now) setOffset(d.now - Date.now() / 1000); }
        timer = setTimeout(read, d.goal && !d.ended ? 600 : 3000);
      } catch (e) { if (!stop) { setError(String(e instanceof Error ? e.message : e)); timer = setTimeout(read, 3000); } }
    };
    void read();
    const ticking = setInterval(() => setTick(n => n + 1), 1000);
    return () => { stop = true; clearTimeout(timer); clearInterval(ticking); };
  }, []);
  useEffect(() => { if (out.current && follow.current) out.current.scrollTop = out.current.scrollHeight; }, [live?.model?.text, live?.model?.thinking, thinking]);
  void tick;
  const now = Date.now() / 1000 + offset;

  if (error && !live) return <div className="mon"><div className="mon-empty">{error}</div></div>;
  if (!live) return <div className="mon"><header className="mon-head"><div><div className="mon-kicker">실시간 보기</div><h2>지금 진행 중인 요청이 없습니다</h2>
    <p className="mon-muted">만들기에서 요청을 보내면 여기서 단계, 모델이 쓰는 글, 점검이 실시간으로 보입니다.</p></div></header></div>;

  const running = !live.ended, model = live.model, writing = !!model && !model.ended && running;
  const state = running ? "run" : live.ok ? "ok" : "fail";
  const elapsed = (live.ended ?? now) - live.started;
  const modelSeconds = model ? (model.ended ?? now) - model.started : 0;
  if (model && model.chunks === 0) first.current = { call: model.started, at: 0 };                 // seen reading: the first word's time is known here
  else if (model && first.current?.call === model.started && !first.current.at) first.current.at = now;
  const firstAt = model?.first ?? (model && first.current?.call === model.started && first.current.at ? first.current.at : null);
  const reading = !!model && !model.ended && model.chunks === 0;
  const writingSeconds = model && firstAt ? (model.ended ?? now) - firstAt : 0;
  const rate = model && writingSeconds > 1 ? model.chunks / writingSeconds : 0;
  const pct = live.checks.total ? Math.round(live.checks.passed / live.checks.total * 100) : 0;
  const shown = thinking && model?.thinking ? model.thinking : model?.text ?? "";

  return <div className="mon">
    <header className="mon-head">
      <div className="mon-head-main">
        <div className="mon-kicker"><span className={`mon-pill is-${state}`}>{running ? "진행 중" : live.ok ? "완료" : "실패"}</span> 시작 {hms(live.started)}{live.ended ? ` · 끝 ${hms(live.ended)}` : ""}</div>
        <h2 title={live.goal}>{live.goal}</h2>
        {!running && live.said && <p className="mon-said">{live.said.split("\n")[0]}</p>}
      </div>
    </header>

    <section className="mon-stats">
      <div className="mon-stat"><span>경과</span><b>{clock(elapsed)}</b></div>
      <div className="mon-stat"><span>모델 호출</span><b>{live.calls}<small>회</small></b></div>
      <div className="mon-stat"><span>생성 토큰</span><b>{(live.tokens + (writing ? model!.chunks : 0)).toLocaleString()}</b></div>
      <div className="mon-stat"><span>{reading ? "모델이 입력을 읽는 중" : "쓰는 속도"}</span><b>{reading ? clock(modelSeconds) : rate ? rate.toFixed(1) : "-"}<small>{reading ? "" : "토큰/초"}</small></b></div>
      <div className="mon-stat"><span>점검</span><b className={live.checks.failed.length ? "is-bad" : ""}>{live.checks.passed}<small>/{live.checks.total}</small></b>
        <div className="mon-bar"><i style={{ width: `${pct}%` }} className={live.checks.failed.length ? "is-bad" : ""} /></div></div>
    </section>

    <div className="mon-grid">
      <section className="mon-card mon-steps">
        <h3>단계</h3>
        <ol>{live.steps.map((step, i) => <li key={i} className={`is-${step.state}`}>
          <span className="mon-dot" />
          <div><div className="mon-step-title">{step.title}<em>{clock((step.ended ?? (running ? now : live.ended!)) - step.started)}</em></div>
            {step.detail && <div className="mon-step-detail">{step.detail}</div>}</div></li>)}
          {!live.steps.length && <li className="is-running"><span className="mon-dot" /><div className="mon-step-title">준비 중</div></li>}
        </ol>
      </section>

      <section className="mon-card mon-model">
        <div className="mon-model-head">
          <h3>{model ? model.title : "모델"}</h3>
          <div className="mon-model-meta">{model && <>{model.model.split("/").pop()} · {model.chars.toLocaleString()}자 · {clock(modelSeconds)}</>}
            {!!model?.thinking && <button type="button" className={thinking ? "on" : ""} onClick={() => setThinking(v => !v)}>생각 보기</button>}</div>
        </div>
        <pre ref={out} className="mon-terminal" onScroll={e => { const el = e.currentTarget; follow.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40; }}>
          {shown || (reading ? `요청과 업무 안내서, 부품 설명을 읽는 중… (${clock(modelSeconds)})` : model ? "" : "모델 호출을 기다리는 중…")}{writing && <span className="mon-caret" />}
        </pre>
      </section>
    </div>

    <section className="mon-card mon-checks">
      <h3>점검 <span className="mon-muted">{live.checks.total ? `${live.checks.total}개 중 ${live.checks.passed}개 통과` : "아직 없음"}</span></h3>
      {!!live.checks.failed.length && <ul className="mon-failed">{live.checks.failed.map((item, i) => <li key={i}><b>✗ {item.description}</b>{item.detail && <span>{item.detail}</span>}<small>{item.step}</small></li>)}</ul>}
      <ul className="mon-feed">{[...live.checks.recent].reverse().map((item, i) => <li key={i} className={item.passed ? "is-ok" : "is-bad"}>
        <i>{item.passed ? "✓" : "✗"}</i><span>{item.description}</span><small>{hms(item.at)}</small></li>)}</ul>
    </section>
  </div>;
}
