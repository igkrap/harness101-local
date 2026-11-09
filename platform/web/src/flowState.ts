export type FlowEvent = {
  seq: number;
  time: string;
  type: string;
  data: Record<string, unknown>;
};
export type FlowJob = { id: string; kind: string; status: string; goal: string };
export type NodeId = "request" | "baseline" | "plan" | "model" | "tool" | "check" | "accept" | "finish" | "rollback" | "retry";
export const nodeNames: Record<NodeId, string> = {
  request: "요청", baseline: "사전 검사", plan: "계획",
  model: "모델 호출", tool: "도구 실행", check: "검사",
  accept: "반영", finish: "종료", rollback: "복원", retry: "재시도",
};

// Replay actual events: visited does not imply a successful check or a completed task.
export function deriveFlow(events: FlowEvent[], job?: FlowJob) {
  const records: Record<NodeId, FlowEvent[]> = {
    request: [], baseline: [], plan: [], model: [], tool: [], check: [], accept: [], finish: [], rollback: [], retry: [],
  };
  let current: NodeId | null = null;
  const incomplete = !!events.length && events[0].seq > 1;
  let hasPlan = incomplete, hasTool = false, hasAccepted = false;
  let checking: NodeId = incomplete && job?.kind === "agent" ? "check" : "baseline";
  let lastNode: NodeId | null = null;
  const edges = new Set<string>();
  let lastEdge: string | null = null;
  const checksOnly = !!job && job.kind !== "agent";
  for (const event of events) {
    let node: NodeId | null = null;
    switch (event.type) {
      case "run.started": node = "request"; break;
      case "requirement.contract": case "autonomy.plan": hasPlan = true; node = "plan"; break;
      case "autonomy.stage_verified": case "verification.finished": node = "check"; break;
      case "model.request": case "model.response": case "model.error":
        node = !hasPlan && !hasTool && !hasAccepted && !checksOnly ? "plan" : "model"; break;
      case "tool.started": case "tool.finished": hasTool = true; node = "tool"; break;
      case "check.started":
        checking = checksOnly || (!hasPlan && !hasTool && !hasAccepted) ? "baseline" : "check";
        node = checking; break;
      case "check.finished": node = checking; break;
      case "autonomy.accepted": hasAccepted = true; node = "accept"; break;
      case "autonomy.rollback": case "workspace.restored": node = "rollback"; break;
      case "autonomy.stage_stalled": case "autonomy.integration_failed": case "autonomy.retry": case "autonomy.strategy": case "autonomy.blocked": node = "retry"; break;
      case "autonomy.step_finished": node = "accept"; break;
      case "run.finished": case "run.error": case "autonomy.error": case "autonomy.conflict":
      case "autonomy.exhausted": case "autonomy.stopped": node = "finish"; break;
    }
    if (node) {
      records[node].push(event);
      if (lastNode && lastNode !== node) { lastEdge=`${lastNode}:${node}`; edges.add(lastEdge); }
      lastNode = current = node;
    }
  }
  const terminal = job && !["running", "stopping"].includes(job.status);
  if (terminal) current = "finish";
  const ended = terminal || records.finish.some(e => e.type === "run.finished" || e.type === "run.error");
  const status = terminal ? job.status : ended ? (records.finish.some(e => e.type === "run.finished" && e.data.success === true)
    ? "succeeded" : "failed") : job?.status || "idle";
  return { records, current, edges, lastEdge, ended, status, checksOnly, incomplete };
}
