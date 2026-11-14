import { Button } from "@astryxdesign/core/Button";
import "./queue.css";

export type QueueItem = { domain: string; title: string; checks: string[]; status: string; job_id: string | null; attempts?: number; deploy?: string; deploy_note?: string };
export type TaskQueue = { id: string; goal: string; status: string; items: QueueItem[]; detail?: string; plan_seconds?: number; plan_fallback?: boolean; created_at: string; finished_at?: string | null; route?: string; undone?: boolean;
  /** The outcome of a definition-route request (harness2). */ definition_result?: { status?: string; action?: string; key?: string; title?: string; checks?: number; seconds?: number; failed?: unknown[] } };

const statusLabel: Record<string, string> = {
  planning: "작업 분리 중", running: "진행 중", stopping: "중지 중", succeeded: "완료", failed: "실패", stopped: "중지됨",
  interrupted: "중단됨", pending: "대기",
};

const deployLabel: Record<string, string> = { running: "서버 배포 중", succeeded: "서버 반영됨", skipped: "서버 최신", failed: "배포 실패" };

export function QueuePanel({ queue, busy, onStop, onResume, onOpenJob, onDismiss }: {
  queue: TaskQueue; busy: boolean; onStop: () => void; onResume: () => void; onOpenJob: (id: string) => void; onDismiss?: () => void;
}) {
  const done = queue.items.filter(i => i.status === "succeeded").length;
  const live = ["planning", "running", "stopping"].includes(queue.status);
  return <section className={`queue queue-${queue.status}`} aria-label="작업 큐">
    <header className="queue-head">
      <div className="queue-title">
        <span className={`queue-pill s-${queue.status}`}>{statusLabel[queue.status] || queue.status}</span>
        <strong title={queue.goal}>{queue.goal}</strong>
      </div>
      <div className="queue-meta">
        {queue.items.length > 0 && <span>{done}/{queue.items.length} 완료</span>}
        {queue.plan_seconds !== undefined && <span>분리 {Math.round(queue.plan_seconds)}초{queue.plan_fallback ? " · 분리 실패로 원문 1개로 실행" : ""}</span>}
        {live && <Button label="큐 중지" size="sm" variant="secondary" isDisabled={busy || queue.status === "stopping"} onClick={onStop} />}
        {["failed", "stopped", "interrupted"].includes(queue.status) && <Button label="이어서 실행" size="sm" isDisabled={busy} onClick={onResume} />}
        {!live && onDismiss && <button type="button" className="queue-close" aria-label="큐 패널 닫기" title="닫기" onClick={onDismiss}>×</button>}
      </div>
    </header>
    {queue.items.length > 0 && <div className="queue-progress" aria-hidden><span style={{ width: `${(done / queue.items.length) * 100}%` }} /></div>}
    {queue.status === "planning" && <p className="queue-note">모델이 요청을 작은 작업으로 나누고 있습니다…</p>}
    <ol className="queue-items">
      {queue.items.map((item, index) => <li key={index} className={`queue-item s-${item.status}`}>
        <span className="queue-dot" aria-hidden>{item.status === "succeeded" ? "✓" : item.status === "failed" ? "!" : index + 1}</span>
        <span className="queue-item-text">
          <span className="queue-domain">{item.domain === "backend" ? "백엔드" : "화면"}</span>{item.title}
        </span>
        <span className="queue-item-state">{statusLabel[item.status] || item.status}{(item.attempts || 0) > 1 ? ` · ${item.attempts}회째` : ""}</span>
        {item.deploy && <span className={`queue-deploy d-${item.deploy}`} title={item.deploy_note}>{deployLabel[item.deploy] || item.deploy}{item.deploy === "running" && item.deploy_note ? ` · ${item.deploy_note}` : ""}</span>}
        {item.job_id && <button type="button" className="queue-link" onClick={() => onOpenJob(item.job_id!)}>실행 보기</button>}
      </li>)}
    </ol>
    {queue.detail && <p className="queue-note">{queue.detail}</p>}
  </section>;
}
