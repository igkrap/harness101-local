import "./overview.css";

type JobLite = { id: string; status: string; started_at: string; finished_at: string | null; goal: string; origin?: string };
type QueueLite = { status: string; goal: string; items: { status: string }[] } | null | undefined;

function minutes(job: JobLite) {
  if (!job.finished_at) return null;
  const ms = new Date(job.finished_at).getTime() - new Date(job.started_at).getTime();
  return Number.isFinite(ms) && ms > 0 ? ms / 60000 : null;
}
function fmt(min: number | null) {
  if (min === null) return "—";
  return min < 1 ? `${Math.round(min * 60)}초` : min < 60 ? `${min.toFixed(min < 10 ? 1 : 0)}분` : `${(min / 60).toFixed(1)}시간`;
}

export function OverviewStats({ jobs, total, queue, online, modelName, active }: {
  jobs: JobLite[]; total?: number; queue: QueueLite; online: boolean; modelName: string; active: JobLite | null;
}) {
  // Measurement (benchmark) runs are excluded so the numbers describe real work.
  const real = jobs.filter(j => j.origin !== "bench");
  // Runs the user stopped are neither successes nor failures; they are reported separately.
  const finished = real.filter(j => ["succeeded", "failed", "interrupted"].includes(j.status)).slice(0, 20);
  const stopped = real.filter(j => j.status === "stopped").length;
  const succeeded = finished.filter(j => j.status === "succeeded");
  const rate = finished.length ? Math.round((succeeded.length / finished.length) * 100) : null;
  const durations = succeeded.map(minutes).filter((m): m is number => m !== null).sort((a, b) => a - b);
  const median = durations.length ? durations[Math.floor(durations.length / 2)] : null;
  const queueDone = queue ? queue.items.filter(i => i.status === "succeeded").length : 0;
  const tiles = [
    { label: "최근 성공률", value: rate === null ? "—" : `${rate}%`, sub: (finished.length ? `${finished.length}건 중 ${succeeded.length}건 성공` : "완료된 실행 없음") + (stopped ? ` · 중지 ${stopped}건 제외` : "") + (jobs.some(j => j.origin === "bench") ? " · 측정 제외" : ""),
      tone: rate === null ? "" : rate >= 60 ? "good" : rate >= 30 ? "warn" : "bad" },
    { label: "성공 시 소요 시간 (중앙값)", value: fmt(median), sub: durations.length ? `가장 빠름 ${fmt(durations[0])}` : "데이터 없음", tone: "" },
    { label: "지금 상태", value: active ? "실행 중" : queue && ["planning", "running", "stopping"].includes(queue.status) ? "큐 진행 중" : "대기",
      sub: queue && queue.items.length ? `큐 ${queueDone}/${queue.items.length} 완료` : active ? active.goal.slice(0, 40) : "새 작업을 시작할 수 있습니다", tone: active ? "live" : "" },
    { label: "모델", value: online ? "연결됨" : "꺼짐", sub: modelName || "선택된 모델 없음", tone: online ? "good" : "bad" },
  ];
  return <section className="ov-stats" aria-label="요약 지표">
    {tiles.map(t => <div key={t.label} className={`ov-tile ${t.tone}`}>
      <div className="ov-label">{t.label}</div>
      <div className="ov-value">{t.value}</div>
      <div className="ov-sub" title={t.sub}>{t.sub}</div>
    </div>)}
  </section>;
}
