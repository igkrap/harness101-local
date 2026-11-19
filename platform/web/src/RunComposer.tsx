import { useEffect, useRef, useState, type RefObject } from "react";
import "./composer.css";

type Option = { value: string; label: string; description?: string; disabled?: boolean };

function examplesFor(screens: string[]) {
  // Suggestions name the project's real screens; without any, fall back to generic phrasing.
  const [a, b] = screens;
  if (!a) return ["새 업무 화면을 만들고 조회·등록·수정·삭제 API까지 연결해줘", "공통 화면 레이아웃의 여백과 글꼴을 정리해줘"];
  return [`${a} 화면 조회 조건에 입력 항목을 하나 추가해줘`, `${a} 화면 편집 항목 하나를 필수 입력으로 바꿔줘`,
    `${b || a} 화면 결과 그리드에 열을 하나 추가해줘`];
}
const checkLabels: Record<string, string> = { frontend: "프론트 빌드", framework: "화면 동작", backend: "백엔드 통합" };

export function RunComposer(props: {
  formRef: RefObject<HTMLDivElement | null>;
  open: boolean; setOpen: (v: boolean) => void;
  goal: string; setGoal: (v: string) => void;
  models: Option[]; model: string; setModel: (v: string) => void;
  available: string[]; checks: string[]; toggleCheck: (mode: string) => void;
  rounds: number; setRounds: (n: number) => void;
  thinking: boolean; setThinking: (v: boolean) => void;
  useQueue: boolean; setUseQueue: (v: boolean) => void;
  blockedReason: string; canStart: boolean; onStart: () => void;
  running: boolean; stopping: boolean; onStop: () => void; busy: boolean; screens?: string[];
}) {
  const examples = examplesFor(props.screens || []);
  const { open, setOpen, goal, setGoal, useQueue } = props;
  const [advanced, setAdvanced] = useState(false);
  const area = useRef<HTMLTextAreaElement>(null);
  useEffect(() => {
    const el = area.current; if (!el) return;
    el.style.height = "auto"; el.style.height = Math.min(Math.max(el.scrollHeight, 96), 320) + "px";
  }, [goal, open]);
  const start = () => { if (props.canStart) props.onStart(); };

  return <div id="new-work-form" ref={props.formRef} className="composer">
    <button type="button" className="composer-toggle" aria-expanded={open} onClick={() => setOpen(!open)}>
      <span>새 작업 작성</span><span aria-hidden className={`composer-chev ${open ? "open" : ""}`}>⌄</span>
    </button>
    {open && <div className="composer-body">
      <div className="composer-box">
        <textarea ref={area} aria-label="만들거나 고칠 내용" value={goal} maxLength={16000}
          placeholder="무엇을 만들거나 고칠까요? 화면·기능·데이터를 구체적으로 적을수록 정확해집니다."
          onChange={e => setGoal(e.target.value)}
          onKeyDown={e => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) { e.preventDefault(); start(); } }} />
        <div className="composer-bar">
          <div className="composer-left">
            <select className="composer-model" aria-label="모델" value={props.model} disabled={props.busy || props.running}
              onChange={e => props.setModel(e.target.value)}>
              {props.models.map(m => <option key={m.value} value={m.value} disabled={m.disabled}>{m.label}</option>)}
            </select>
            <button type="button" className={`composer-ghost ${advanced ? "on" : ""}`} aria-expanded={advanced} onClick={() => setAdvanced(!advanced)}>고급 설정</button>
          </div>
          <div className="composer-right">
            <span className="composer-hint">⌘ Enter</span>
            {props.running
              ? <button type="button" className="composer-stop" disabled={props.busy || props.stopping} onClick={props.onStop}>{props.stopping ? "중지 중…" : "실행 중지"}</button>
              : <button type="button" className="composer-run" disabled={!props.canStart} onClick={start}>모델 실행</button>}
          </div>
        </div>
      </div>
      {advanced && <div className="composer-advanced">
        <div className="composer-field">
          <span className="composer-label">{useQueue ? "작업당 모델 호출 한도" : "모델 호출 한도"}</span>
          <div className="composer-chips">{[0, 16, 32, 64].map(n => <button key={n} type="button" aria-pressed={props.rounds === n}
            className={props.rounds === n ? "on" : ""} onClick={() => props.setRounds(n)}>{n === 0 ? "제한 없음" : `${n}회`}</button>)}</div>
        </div>
        <label className="composer-switch"><input type="checkbox" checked={props.thinking} onChange={e => props.setThinking(e.target.checked)} />
          <span className="composer-track" aria-hidden /><span>생각 모드 (Thinking) — 더 신중하지만 느립니다</span></label>
      </div>}
      <div className="composer-foot">
        {props.blockedReason
          ? <span className="composer-blocked">{props.blockedReason}</span>
          : <span>{useQueue ? "모델이 요청을 작은 작업으로 나눈 뒤, 작업마다 완료 조건을 정하고 검사를 통과해야 다음으로 넘어갑니다." : "요청 전체를 한 번의 실행으로 처리합니다. 선택한 완료 조건을 모두 통과해야 성공입니다."}</span>}
      </div>
      {!goal.trim() && <div className="composer-examples">{examples.map(text =>
        <button key={text} type="button" onClick={() => { setGoal(text); area.current?.focus(); }}>{text}</button>)}</div>}
    </div>}
  </div>;
}
