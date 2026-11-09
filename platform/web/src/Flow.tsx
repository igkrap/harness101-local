import { useId, useState } from "react";
import { VStack, HStack } from "@astryxdesign/core/Layout";
import { Text, Heading } from "@astryxdesign/core/Text";
import { Card } from "@astryxdesign/core/Card";
import { Button } from "@astryxdesign/core/Button";
import { StatusBadge } from "./StatusBadge";
import { deriveFlow, nodeNames, type FlowEvent, type FlowJob, type NodeId } from "./flowState";

const positions: Record<NodeId, [number, number]> = {
  request: [190, 44], baseline: [190, 116], plan: [190, 188], model: [190, 260],
  tool: [190, 332], check: [190, 404], accept: [190, 476], finish: [190, 548],
  rollback: [520, 404], retry: [520, 476],
};
const mainSequence: NodeId[] = ["request", "baseline", "plan", "model", "tool", "check", "accept", "finish"];
const modes: Record<string, string> = { frontend: "프론트 빌드", framework: "화면 동작", backend: "백엔드 통합", harness: "하네스 자체 검사" };
const endings: Record<string, string> = { succeeded: "완료", failed: "실패", stopped: "중지", interrupted: "확인 필요", stopping: "중지 중", idle: "대기" };

export function Flow({ events, job }: { events: FlowEvent[]; job?: FlowJob }) {
  const state = deriveFlow(events, job);
  const [selection, setSelection] = useState<{ job: string; node: NodeId } | null>(null);
  const inspecting = selection && selection.job === (job?.id || "");
  const selected = selection && selection.job === (job?.id || "") ? selection.node : state.current || "request";
  const marker = useId().replace(/:/g, "");
  const visible = state.checksOnly ? ["request", "baseline", "finish"] as NodeId[] : Object.keys(positions) as NodeId[];
  const latest = state.records[selected].at(-1);
  const detail = [...state.records[selected]].reverse().find(e => e.data.error || e.data.path || e.data.paths) || latest;
  const name = (id: NodeId) => state.checksOnly && id === "baseline" ? "선택한 검사" : nodeNames[id];
  const active = (id: NodeId) => state.current === id && !!job;
  const failed = (id: NodeId) => {
    const last = state.records[id].at(-1);
    return (id === "finish" && state.ended && state.status !== "succeeded") || last?.data.success === false || !!last?.data.error;
  };
  const blue="var(--color-text-link, #1d4ed8)";
  const color = (id: NodeId) => failed(id) ? "var(--color-text-error, #b91c1c)" : active(id) ? state.ended&&state.status==="succeeded" ? "var(--color-text-success, #15803d)" : blue : state.records[id].length ? "var(--color-text-primary)" : "var(--color-text-secondary)";
  const fill = (id:NodeId) => failed(id) ? "#fef2f2" : active(id) ? state.ended&&state.status==="succeeded" ? "#f0fdf4" : "#eff6ff" : "var(--color-background-card)";
  const status = (id: NodeId) => id === "finish" && state.ended ? endings[state.status] || state.status
    : active(id) && !state.ended ? (job?.status === "stopping" ? "중지 중" : "진행 중")
    : state.records[id].length ? "기록 있음" : state.incomplete ? "기록 없음" : "미실행";
  const path = (from: NodeId, to: NodeId, d: string, text?: string, at?: [number, number]) => {
    const seen = state.edges.has(`${from}:${to}`);
    const current=!state.ended&&state.lastEdge===`${from}:${to}`;
    return <g key={`${from}:${to}`} data-edge={`${from}:${to}`} data-visited={seen} style={{color:current?blue:seen?"#475569":"#cbd5e1"}}>
      <path d={d} fill="none" stroke="currentColor" strokeWidth={current?3.2:seen?2.5:1.5} strokeDasharray={seen ? undefined : "5 5"} markerEnd={`url(#${marker})`} />
      {text && at && <text x={at[0]} y={at[1]} textAnchor="middle" fill="currentColor" fontSize="12">{text}</text>}
    </g>;
  };
  return <Card padding={5} role="region" aria-label="실행 흐름"><VStack gap={4}>
    <HStack hAlign="between" vAlign="center" gap={3} style={{ flexWrap: "wrap" }}>
      <Heading level={3}>실행 흐름</Heading>
      <HStack gap={2} vAlign="center">
        {job && !state.ended && <Text>{name(state.current || "request")}</Text>}
        <span role="status"><StatusBadge value={job ? state.ended ? state.status : job.status === "stopping" ? "stopping" : "pending" : "waiting"} label={job ? state.ended ? endings[state.status] : undefined : "실행 대기"}/></span>
        {inspecting && <Button label="선택 해제" size="sm" variant="ghost" onClick={() => setSelection(null)} />}
      </HStack>
    </HStack>
    {job && <Text color="secondary" style={{overflowWrap:"anywhere"}}>{state.checksOnly ? "검사 실행" : job.goal}</Text>}
    <VStack style={{ overflowX: "auto", minWidth: 0 }}>
      <svg viewBox={state.checksOnly ? "0 0 720 110" : "0 0 720 590"} style={{ width: "100%", maxHeight: state.checksOnly ? undefined : "42rem", minWidth: "36rem", color: "var(--color-text-secondary)", fontFamily: "inherit" }} role="group" aria-label="작업 실행 흐름도">
        <defs><marker id={marker} viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0 10 5 0 10Z" fill="context-stroke" /></marker></defs>
        {state.checksOnly ? <>
          {path("request", "baseline", "M205 55H260")}
          {path("baseline", "finish", "M450 55H505")}
        </> : <>
          {mainSequence.slice(0, -1).map((id, i) => path(id, mainSequence[i+1], `M190 ${positions[id][1]+27}V${positions[mainSequence[i+1]][1]-27}`))}
          {path("check", "rollback", "M285 404H425", "실패", [355, 391])}
          {path("rollback", "retry", "M520 431V449")}
          {path("retry", "model", "M615 476H680V260H285")}
        </>}
        {visible.map(id => {
          const [x, y] = state.checksOnly ? [id === "request" ? 110 : id === "baseline" ? 355 : 600, 55] : positions[id];
          const number=state.checksOnly?visible.indexOf(id)+1:mainSequence.indexOf(id)+1;
          return <g key={id} role="button" tabIndex={0} aria-label={`${name(id)}: ${status(id)}`} aria-pressed={selected === id} data-node={id} data-current={active(id)} data-state={status(id)} onClick={() => setSelection({ job: job?.id || "", node: id })} onKeyDown={e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setSelection({ job: job?.id || "", node: id }); } }} style={{ cursor: "pointer", color: color(id) }}>
            <rect x={x-95} y={y-27} width="190" height="54" rx="6" fill={fill(id)} stroke={active(id)||selected===id?"currentColor":state.records[id].length?"#94a3b8":"#cbd5e1"} strokeWidth={active(id)?3:selected===id?2:1.4}/>
            <circle cx={x-72} cy={y} r="12" fill={active(id)?color(id):"#f1f5f9"}/>
            <text x={x-72} y={y+4} textAnchor="middle" fontSize="12" fontWeight="600" fill={active(id)?"white":"#475569"}>{number>0?number:id==="rollback"?"↶":"↻"}</text>
            <text x={x+2} y={y+6} textAnchor="middle" fill="currentColor" fontSize="17" fontWeight={active(id)||state.records[id].length?"600":"400"}>{name(id)}</text>
            {active(id)&&!state.ended&&<g><rect x={x+56} y={y-10} width="33" height="20" rx="3" fill={color(id)}/><text x={x+72} y={y+4} textAnchor="middle" fill="white" fontSize="10" fontWeight="600">진행</text></g>}
          </g>;
        })}
      </svg>
    </VStack>
    {state.incomplete && <Text color="secondary">최근 기록만 표시 중</Text>}
    {inspecting && <VStack gap={2} role="region" aria-label="단계 상세" style={{ borderTop: "1px solid var(--color-border)", paddingTop: "var(--spacing-3)" }}>
      <HStack gap={2} vAlign="center"><Text weight="bold">{name(selected)}</Text><StatusBadge value={failed(selected)?"failed":active(selected)&&!state.ended?"pending":"waiting"} label={status(selected)}/></HStack>
      {latest ? <>
        <Text>{new Date(latest.time).toLocaleTimeString("ko-KR", { hour12: false })} · {latest.type}{latest.data.name ? ` · ${latest.data.name}` : ""}{latest.data.mode ? ` · ${modes[String(latest.data.mode)] || latest.data.mode}` : ""}{typeof latest.data.success === "boolean" ? ` · ${latest.data.success ? "통과" : "실패"}` : ""}</Text>
        {typeof latest.data.estimated_input_tokens === "number" && <Text color="secondary">입력 추정 {latest.data.estimated_input_tokens.toLocaleString()} 토큰</Text>}
        {detail && !!(detail.data.path || detail.data.paths || detail.data.error || detail.data.reason || detail.data.title) && <Text style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{[detail.data.path, Array.isArray(detail.data.paths) ? detail.data.paths.join(", ") : "", detail.data.title, detail.data.error, detail.data.reason].filter(Boolean).join("\n").slice(0, 1800)}</Text>}
      </> : <Text color="secondary">이벤트 없음</Text>}
    </VStack>}
  </VStack></Card>;
}
