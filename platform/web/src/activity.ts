// Plain-language lines for what the model is doing right now, built from run events.
export type RunEvent = { seq: number; time: string; type: string; data: Record<string, unknown> };
export type Activity = { key: number; text: string; detail: string; state: "live" | "ok" | "bad"; time: string };

const base = (path: unknown) => (typeof path === "string" ? path.split("/").pop() || path : "");
const tools: Record<string, string> = {
  read_file: "파일 읽기", inspect_code: "코드 구조 살펴보기", search_code: "코드 검색", search_components: "쓸 수 있는 부품 찾기",
  write_file: "새 파일 작성", edit_file: "파일 수정", delete_file: "파일 삭제", apply_ast_edits: "파일 수정", apply_edits: "파일 수정",
  apply_insertions: "파일 수정", insert_text: "파일 수정", list_files: "폴더 살펴보기", verify_requirements: "완료 조건 확인", finish: "마무리",
};
const checks: Record<string, string> = { frontend: "화면 빌드 검사", framework: "화면 동작 검사", backend: "서버 빌드·테스트" };

function line(e: RunEvent): Omit<Activity, "key" | "state" | "time"> | null {
  const d = e.data || {};
  switch (e.type) {
    case "run.started": return { text: "작업 시작", detail: String(d.goal || "") };
    case "definition.step": return { text: String(d.title || "단계"), detail: `${d.seconds != null ? `${d.seconds}초` : ""}${d.detail ? ` · ${String(d.detail).slice(0, 200)}` : ""}` };
    case "model.request": return { text: "AI가 생각하는 중", detail: "" };
    case "tool.started": {
      const name = String(d.name || "");
      const detail = name === "search_code" ? String(d.query || "") : base(d.path);
      return { text: tools[name] || name, detail };
    }
    case "check.started": return { text: checks[String(d.mode)] || "검사", detail: "" };
    case "requirement.contract": return { text: "완료 조건 정함", detail: `${((d.contract as { criteria?: unknown[] })?.criteria || []).length}개` };
    case "requirement.contract_rejected": return { text: "완료 조건 다시 정하는 중", detail: "" };
    case "autonomy.strategy": return d.reason === "automatic_requirement_verification" ? { text: "만든 결과를 실제 화면·API로 확인", detail: "" } : null;
    case "autonomy.rollback": return { text: "실패한 수정을 되돌림", detail: "" };
    case "autonomy.stalled": return { text: "진전이 없어 중단", detail: "" };
    case "run.restored": return { text: "실패해서 원래대로 되돌림", detail: "" };
    case "run.finished": return { text: d.success ? "작업 완료" : "작업 실패", detail: "" };
    default: return null;
  }
}

/** Most recent activities (newest last). A started step stays "live" until its finishing event arrives. */
export function activities(events: RunEvent[], limit = 6): Activity[] {
  const out: Activity[] = [];
  for (const e of events) {
    const d = e.data || {};
    if (e.type === "model.response" || e.type === "tool.finished" || e.type === "check.finished" || e.type === "verification.finished") {
      const open = [...out].reverse().find(a => a.state === "live");
      if (open) open.state = (e.type === "tool.finished" || e.type === "check.finished" || e.type === "verification.finished") && d.success === false ? "bad" : "ok";
      continue;
    }
    const item = line(e);
    if (!item) continue;
    const prev = out[out.length - 1];
    if (prev && prev.state === "live") prev.state = "ok";
    const terminal = e.type === "run.finished" || e.type === "requirement.contract" || e.type === "autonomy.rollback" || e.type === "run.restored" || e.type === "autonomy.stalled";
    out.push({ key: e.seq, ...item, time: e.time, state: terminal ? (e.type === "run.finished" && d.success || e.type === "requirement.contract" ? "ok" : "bad") : "live" });
  }
  return out.slice(-limit);
}
