import { useEffect, useState } from "react";
import { apiFetch } from "./api";

type Status = { branch: string; remote: string; ahead: number | null; dirty: unknown[]; unrecorded?: { site: string[]; files: string[] } };

/** Under the project picker, always: where this project's work stands - its work space, what is not recorded yet, the remote. */
export default function ProjectStatus({ onOpen }: { onOpen: () => void }) {
  const [status, setStatus] = useState<Status | null>(null);
  useEffect(() => {
    let stop = false, timer: ReturnType<typeof setTimeout>;
    const read = () => apiFetch("/api/history?limit=1").then(r => r.json()).then(d => { if (!stop && d.status) setStatus(d.status); })
      .catch(() => {}).finally(() => { if (!stop) timer = setTimeout(read, 10000); });
    read();
    return () => { stop = true; clearTimeout(timer); };
  }, []);
  if (!status) return null;
  const loose = (status.unrecorded?.site.length || 0) + status.dirty.length;
  return <button type="button" className="ps" onClick={onOpen} title="형상 관리 보기">
    <span className="ps-chip">작업 공간 {status.branch || "-"}</span>
    <span className={`ps-chip${loose ? " warn" : " ok"}`}>{loose ? `기록 안 됨 ${loose}` : "모두 기록됨"}</span>
    <span className="ps-chip">{status.remote ? (status.ahead ? `원격에 안 올림 ${status.ahead}` : "원격과 같음") : "원격 없음"}</span>
  </button>;
}
