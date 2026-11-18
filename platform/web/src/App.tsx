import { StatusBadge } from "./StatusBadge";
import { LogRow } from "./LogRow";
import { ContextPanel } from "./ContextPanel";
import { VerificationPanel } from "./VerificationPanel";
import { readActivity } from "./logDetails";
import { RunRecordRow } from "./RunRecordRow";
import { LatestResult } from "./LatestResult";
import "./actions.css";
import Preview from "./Preview";
import HistoryPage from "./HistoryPage";
import GuidePage from "./GuidePage";
import HomePage from "./HomePage";
import DevTools from "./DevTools";
import { Selector } from "@astryxdesign/core/Selector";
import ProjectManager, { ProjectPicker, EnvironmentCheck } from "./ProjectManager";
import ModelManager, {type ModelConfig} from "./ModelManager";
import ChatPanel from "./ChatPanel";
import { QueuePanel, type TaskQueue } from "./QueuePanel";
import { RunComposer } from "./RunComposer";
import { OverviewStats } from "./OverviewStats";
import { ChangesPanel } from "./ChangesPanel";
import { apiFetch, projectId } from "./api";
import { useEffect, useRef, useState, lazy, Suspense, type ReactNode } from "react";
import { VStack, HStack } from "@astryxdesign/core/Layout";
import { Text, Heading } from "@astryxdesign/core/Text";
import { Card } from "@astryxdesign/core/Card";
import { Button } from "@astryxdesign/core/Button";
import { TextArea } from "@astryxdesign/core/TextArea";
import { Collapsible } from "@astryxdesign/core/Collapsible";
import {
  SideNav,
  SideNavSection,
  SideNavItem,
  SideNavHeading,
} from "@astryxdesign/core/SideNav";
import { TabList, Tab } from "@astryxdesign/core/TabList";
import { Flow } from "./Flow";
import { StrategyPanel } from "./StrategyPanel";
import { JobHistory, PagedEvents } from "./HistoryViews";
import { FailurePanel } from "./FailurePanel";
const SourceBrowser = lazy(() => import("./SourceBrowser"));
import * as echarts from "echarts/core";
import { BarChart, LineChart } from "echarts/charts";
import {
  GridComponent,
  TooltipComponent,
  LegendComponent,
} from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
echarts.use([
  BarChart,
  LineChart,
  GridComponent,
  TooltipComponent,
  LegendComponent,
  CanvasRenderer,
]);
type Event = {
  seq: number;
  time: string;
  type: string;
  data: Record<string, unknown>;
};
type Job = {
  id: string;
  kind: string;
  model?:string;
  goal: string;
  checks: string[];
  rounds: number;
  status: string;
  started_at: string;
  finished_at: string | null;
  exit_code: number | null;
};
type Evidence = {
  success: boolean;
  time: string;
  stdout?: string;
  stderr?: string;
  error?: string;
  duration_ms?: number;
  source: string;
};
type Gate = {
  mode: string;
  label: string;
  state: string;
  evidence: Evidence | null;
};
type Snapshot = {
  time: string;
  maintenance?: boolean;
  token: string;
  project: { id?:string; name: string; root: string; preview_url: string; checks?:string[] };
  workspace_busy?:boolean;
  chat_active?:boolean;
  queue?:TaskQueue|null;
  screens?:string[];
  latest_agent?:Job|null;
  agent_jobs?:Job[];
  agent_jobs_next?:string|null;
  agent_jobs_total?:number;
  agent_events?:Event[];
  model: { online: boolean; name: string; url: string; runtime: string; available?:string[]; unavailable?:Record<string,string>; configs?:ModelConfig[]; default_config?:string };
  active: Job | null;
  phase: string;
  external: { pid: number; elapsed: string }[];
  jobs: Job[];
  jobs_next?: string | null;
  jobs_total?: number;
  gates: Gate[];
  reports: { tests: number; failures: number; errors: number; skipped: number };
  events: Event[];
  counts: Record<string, number>;
};
const labels: Record<string, string> = {
  passed: "통과",
  failed: "실패",
  stale: "재검사 필요",
  unknown: "미검사",
  running: "실행 중",
  stopping: "중지 중",
  stopped: "중지됨",
  succeeded: "완료",
  interrupted: "종료 확인 필요",
  idle: "대기 중",
  model: "모델 응답 대기",
  check: "검사 중",
  tool: "도구 실행 중",
  frontend: "프론트 빌드",
  framework: "화면 동작",
  backend: "백엔드 통합",
  harness: "하네스 자체 검사",
};
const eventNames: Record<string, string> = {
  "requirement.contract_rejected": "완료 조건 수정 필요",
  "requirement.review": "완료 조건 검토",
  "requirement.contract": "완료 조건 고정",
  "verification.finished": "요청 달성 여부 검사",
  "run.started": "실행 시작",
  "run.finished": "실행 종료",
  "run.error": "실행 오류",
  "attempt.started": "새 컨텍스트 시작",
  "attempt.finished": "컨텍스트 종료",
  "model.request": "모델에 요청",
  "model.response": "모델 응답",
  "model.error": "모델 오류",
  "tool.started": "도구 시작",
  "tool.finished": "도구 완료",
  "check.started": "검사 시작",
  "check.finished": "검사 결과",
  "workspace.restored": "실행 전 파일 복원",
  "autonomy.plan": "작업 단계 생성",
  "autonomy.retry": "다시 시도",
  "autonomy.rollback": "실패한 수정 복원",
  "autonomy.accepted": "수정 반영",
  "autonomy.step_finished": "단계 완료",
  "autonomy.conflict": "다른 수정과 충돌",
  "autonomy.stopped": "작업 중지",
  "autonomy.error": "실행 오류",
  "autonomy.blocked": "수정 차단",
  "autonomy.exhausted": "실행 한도 도달",
  "autonomy.strategy": "반복 실패로 도구 전환",
};
const clock = (v: string) =>
  new Date(v).toLocaleTimeString("ko-KR", { hour12: false });
const stamp = (v: string) =>
  new Date(v).toLocaleString("ko-KR", {
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
const stateColor = (s: string) =>
  s === "passed" || s === "succeeded"
    ? "var(--color-text-success)"
    : s === "failed"
      ? "var(--color-text-error)"
      : s === "stale" || s === "stopping"
        ? "var(--color-text-warning)"
        : "var(--color-text-secondary)";
function Mark({ kind }: { kind: string }) {
  const paths: Record<string, string> = {
    overview: "M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z",
    run: "m8 5 11 7-11 7z",
    checks: "m4 12 5 5L20 6",
    source: "m8 5-6 7 6 7 M16 5l6 7-6 7",
    preview: "M3 4h18v15H3z M3 8h18",
    models: "M4 6h16 M4 12h16 M4 18h16 M8 3v6 M16 9v6 M10 15v6",
    environment: "M3 5h18v11H3z M8 20h8 M12 16v4 M7 9l2 2-2 2 M11 13h5",
    chat: "M3 4h18v13H8l-5 4V4z M7 9h10 M7 13h7",
    history: "M3 12a9 9 0 1 0 3-6.7 M3 4v5h5 M12 7v5l3 2",
    guide: "M4 4h7a3 3 0 0 1 3 3v13a2 2 0 0 0-2-2H4z M20 4h-7a3 3 0 0 0-3 3v13a2 2 0 0 1 2-2h8z",
    home: "M12 3l1.8 4.7L18.5 9.5l-4.7 1.8L12 16l-1.8-4.7L5.5 9.5l4.7-1.8z M18 15l.8 2.2L21 18l-2.2.8L18 21l-.8-2.2L15 18l2.2-.8z",
    projects: "M3 6h7l2 2h9v11H3z",
    brand: "m12 2 10 6-10 6L2 8z M2 12l10 6 10-6 M2 16l10 6 10-6",
  };
  return (
    <svg
      width="20"
      height="20"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d={paths[kind] || paths.brand} />
    </svg>
  );
}
function Panel({
  title,
  extra,
  children,
}: {
  title: string;
  extra?: ReactNode;
  children: ReactNode;
}) {
  return (
    <Card padding={5} style={{overflow:"visible",textAlign:"left"}}>
      <VStack gap={4}>
        <HStack hAlign="between" vAlign="center" gap={3}>
          <Heading level={3}>{title}</Heading>
          {extra}
        </HStack>
        {children}
      </VStack>
    </Card>
  );
}
function Status({value}:{value:string}){return <StatusBadge value={value}/>;}
function Code({ children }: { children: string }) {
  return (
    <pre
      style={{
        margin: 0,
        whiteSpace: "pre-wrap",
        overflowWrap: "anywhere",
        fontFamily: "var(--font-family-mono, monospace)",
        fontSize: "var(--text-small-size)",
        lineHeight: 1.7,
        maxHeight: "34rem",
        overflow: "auto",
        background: "var(--color-background-muted)",
        padding: "var(--spacing-4)",
        borderRadius: "var(--radius-container)",
      }}
    >
      {children}
    </pre>
  );
}
function EventList({events,jobId,running=false}:{events:Event[];jobId?:string;running?:boolean}) {
  const activity=readActivity(events);
  return jobId ? <VStack gap={3}>{activity.reads>=6&&activity.repeated.length>0&&<Card variant="muted" padding={3}><VStack gap={1}><Text weight="bold">같은 파일을 반복해서 읽고 있습니다.</Text><Text color="secondary">최근 불러온 기록에서 마지막 반영 이후 파일 읽기 {activity.reads}회. 이 구간에는 변경 반영이 없습니다.</Text>{activity.repeated.map(([path,count])=><Text key={path} style={{overflowWrap:'anywhere'}}>{path} · {count}회</Text>)}</VStack></Card>}<Text color="secondary">각 행을 펼치면 호출 인자·반환 결과·모델 메시지를 확인할 수 있습니다.</Text><PagedEvents key={jobId} jobId={jobId} recent={events} renderRow={e=><LogRow key={e.seq} event={e} jobId={jobId} running={running}/>} /></VStack> : <Text color="secondary">이벤트 없음</Text>;
}
function Steps({events,active}:{events:Event[];active:boolean}) {
  const plan=[...events].reverse().find(e=>e.type==='autonomy.plan');
  if(plan?.data.source==='divide-and-conquer') return null;
  const raw=plan?.data.steps;
  if(!Array.isArray(raw)) return null;
  const done=new Set(events.filter(e=>e.type==='autonomy.step_finished').map(e=>Number(e.data.step)));
  const current=raw.findIndex((_,i)=>!done.has(i+1));
  return <Panel title="작업 단계"><VStack gap={3}>{raw.map((step,i)=><HStack key={i} hAlign="between" gap={3}><Text>{i+1}. {typeof step==='string'?step:String(step?.title||'')}</Text>{done.has(i+1)?<Status value="passed"/>:<StatusBadge value={active&&i===current?"pending":"waiting"}/>}</HStack>)}</VStack></Panel>
}
function Chart({ events, gates }: { events: Event[]; gates: Gate[] }) {
  const ref = useRef<HTMLElement>(null);
  const instance = useRef<echarts.ECharts | null>(null);
  useEffect(() => {
    if (!ref.current) return;
    const chart = echarts.init(ref.current);
    instance.current = chart;
    const observer = new ResizeObserver(() => chart.resize());
    observer.observe(ref.current);
    return () => {
      observer.disconnect();
      chart.dispose();
      instance.current = null;
    };
  }, []);
  useEffect(() => {
    if (!ref.current || !instance.current) return;
    const css = getComputedStyle(ref.current);
    const token = (v: string) => css.getPropertyValue(v).trim();
    const checks = events.filter(
      (e) =>
        e.type === "check.finished" && typeof e.data.duration_ms === "number",
    );
    instance.current.setOption(
      {
        animation: false,
        textStyle: {
          fontFamily: css.fontFamily,
          color: token("--color-text-secondary"),
        },
        tooltip: { trigger: "axis" },
        grid: { left: 48, right: 20, top: 25, bottom: 40 },
        xAxis: {
          type: "category",
          data: checks.map(
            (e) =>
              `${labels[String(e.data.mode)] || e.data.mode}\n${clock(e.time)}`,
          ),
          axisLabel: { interval: 0, hideOverlap: true },
          axisLine: { lineStyle: { color: token("--color-border") } },
        },
        yAxis: {
          type: "value",
          name: "초",
          splitLine: { lineStyle: { color: token("--color-border") } },
        },
        series: [
          {
            type: "bar",
            barMaxWidth: 44,
            data: checks.map((e) => ({
              value: Number(e.data.duration_ms) / 1000,
              itemStyle: {
                color: token(
                  e.data.success
                    ? "--color-text-success"
                    : "--color-text-error",
                ),
                borderRadius: [3, 3, 0, 0],
              },
            })),
          },
        ],
      },
      true,
    );
  }, [events, gates]);
  return (
    <VStack gap={2}>
      <VStack
        ref={ref}
        height={245}
        role="img"
        aria-label="검사별 소요 시간"
      />
      {!events.some((e) => e.type === "check.finished") && (
        <Text color="secondary">
          아직 검사 기록이 없습니다.
        </Text>
      )}
      <Text color="secondary">
        선택한 실행 기준
      </Text>
    </VStack>
  );
}
async function read<T>(url: string, signal?: AbortSignal): Promise<T> {
  const r = await apiFetch(url, { signal, cache: "no-store" });
  const body = await r.json();
  if (!r.ok) throw Error(body.error || `HTTP ${r.status}`);
  return body;
}
export default function App() {
  const [data, setData] = useState<Snapshot | null>(null),
    [offline, setOffline] = useState(""),
    [page, setPage] = useState("home"),
    [focusKey, setFocusKey] = useState(0),
    [collapsed, setCollapsed] = useState(()=>window.matchMedia('(max-width: 1000px)').matches),
    [tabs, setTabs] = useState(["overview"]);
  const [composerOpen,setComposerOpen]=useState(true),[runTab,setRunTab]=useState("logs");
  const composerRef=useRef<HTMLDivElement>(null);
  useEffect(()=>{
    if(!composerOpen||page!=="run")return;
    const frame=requestAnimationFrame(()=>{composerRef.current?.scrollIntoView({block:"start"});composerRef.current?.querySelector<HTMLTextAreaElement>('textarea')?.focus({preventScroll:true});});
    return()=>cancelAnimationFrame(frame);
  },[composerOpen,page]);
  const [goal, setGoal] = useState(""),
    [rounds, setRounds] = useState(0),
    [checks, setChecks] = useState(["frontend", "framework", "backend"]),
    [thinking, setThinking] = useState(false),
    [useQueue, setUseQueue] = useState(()=>localStorage.getItem('use-queue')!=='0'),
    [dismissedQueue, setDismissedQueue] = useState(()=>localStorage.getItem('queue-dismissed')||''),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const [model,setModel]=useState(()=>localStorage.getItem("model:"+projectId)||"");
  const configs=data?.model.configs||[];
  const modelChoices=[...configs.map(m=>({value:'config:'+m.id,label:m.name,description:m.model})),...(data?.model.available||[]).filter(id=>!configs.some(m=>m.model===id&&m.url===data?.model.url)).map(id=>({value:id,label:id}))];
  const modelOptions=modelChoices.map(m=>m.value);
  const preferred=data?.model.default_config?'config:'+data.model.default_config:configs.find(m=>m.model===data?.model.name&&m.url===data?.model.url)?'config:'+configs.find(m=>m.model===data?.model.name&&m.url===data?.model.url)!.id:data?.model.name||'';
  const effectiveModel=modelOptions.includes(model)?model:modelOptions.includes(preferred)?preferred:modelOptions[0]||"";
  useEffect(()=>{if(data?.model.default_config){const choice='config:'+data.model.default_config;setModel(choice);localStorage.setItem('model:'+projectId,choice);}},[data?.model.default_config]);
  useEffect(()=>{if(data?.project.checks)setChecks(data.project.checks);},[data?.project.id]);
  const [selected, setSelected] = useState(""),
    [selectedRecord,setSelectedRecord]=useState<Job|null>(null),
    [history, setHistory] = useState<{ id: string; events: Event[] }>({ id: "", events: [] }),
    [output, setOutput] = useState(""),
    [sourceOpened,setSourceOpened]=useState(false),
    [chatOpened,setChatOpened]=useState(false);
  useEffect(() => {
    let timer: ReturnType<typeof setTimeout>;
    const controller = new AbortController();
    async function poll() {
      try {
        const next = await read<Snapshot>("/api/state", controller.signal);
        setData(next);
        setOffline("");
      } catch (e) {
        if (!controller.signal.aborted) setOffline(String(e));
      }
      if (!controller.signal.aborted) timer = setTimeout(poll, 1500);
    }
    poll();
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, []);
  const latest = data?.jobs[0];
  const selectedJob = data?.jobs.find((j) => j.id === selected) || (selectedRecord?.id === selected ? selectedRecord : null) || data?.latest_agent || latest;
  const selectedId = selectedJob?.id;
  useEffect(() => {
    if (!selectedId || page !== "run") return;
    const c = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    let last = 0;
    const poll = async () => {
      try {
        const [events, log] = await Promise.all([
          read<{ events: Event[] }>(`/api/jobs/${selectedId}/events?limit=200${last ? `&after=${last}` : ""}`, c.signal),
          read<{ text: string }>(`/api/jobs/${selectedId}/log`, c.signal),
        ]);
        if(events.events.length)last=events.events[events.events.length-1].seq;
        setHistory(previous => ({ id: selectedId, events: [...new Map([...(previous.id === selectedId ? previous.events : []),...events.events].map(e=>[e.seq,e])).values()].sort((a,b)=>a.seq-b.seq).slice(-600) }));
        setOutput(log.text);
      } catch (e) {
        if (!c.signal.aborted) setError(e instanceof Error ? e.message : String(e));
      }
      if (!c.signal.aborted && ["running","stopping"].includes(selectedJob?.status || "")) timer = setTimeout(poll, 2000);
    };
    setHistory({ id: selectedId, events: [] });
    setOutput("");
    poll();
    return () => {
      c.abort();
      clearTimeout(timer);
    };
  }, [selectedId, page, selectedJob?.status]);
  useEffect(()=>{if(page==='chat')setChatOpened(true);},[page]);
  useEffect(()=>{
    // Collapse the navigation on narrow windows so the work area keeps its width.
    const query=window.matchMedia('(max-width: 1000px)');
    const sync=()=>setCollapsed(query.matches);
    query.addEventListener('change',sync);
    return()=>query.removeEventListener('change',sync);
  },[]);
  const navigate = (key: string) => {
    setPage(key);
    if(key === "source") setSourceOpened(true);
  };
  const close = (key: string) => {
    const next = tabs.filter((t) => t !== key);
    setTabs(next);
    if(key === "source") setSourceOpened(false);
    if (page === key) setPage(next[next.length - 1] || "");
  };
  const post = async (path: string, body: object) => {
    setBusy(true);
    setError("");
    try {
      const r = await apiFetch(path, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Platform-Token": data?.token || "",
        },
        body: JSON.stringify(body),
      });
      const result = await r.json();
      if (!r.ok) throw Error(result.error);
      const next = await read<Snapshot>("/api/state");
      setData(next);
      return result;
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      return null;
    } finally {
      setBusy(false);
    }
  };
  const start = async () => {
    if (useQueue) {
      const queue = await post("/api/queues", { goal, rounds, thinking, model: effectiveModel });
      if (queue) setGoal("");
      return;
    }
    const job = await post("/api/jobs", {
      kind: "agent",
      goal,
      checks,
      rounds,
      thinking,
      model: effectiveModel,
    });
    if (job) {
      setSelected(job.id);
      setSelectedRecord(job);
      setGoal("");
    }
  };
  const stop = () =>
    data?.active && post(`/api/jobs/${data.active.id}/stop`, {});
  const navGroups: [string, string[][]][] = [
    ["업무", [["home", "만들기"], ["preview", "앱 보기"], ["guide", "업무 안내서"], ["history", "변경 이력"]]],
    ["설정", [["projects", "프로젝트"], ["environment", "개발 환경"], ["models", "AI 모델"]]],
    ["개발자 도구", [["tools", "화면 정의·자료·서버"], ["run", "실행 기록"], ["overview", "통계"], ["source", "프로젝트 소스"], ["chat", "채팅"]]],
  ];
  const navigation = navGroups.flatMap(([, items]) => items);
  const disabled =
    busy || !!offline || !data || !!data.maintenance || !!data.active || !!data.workspace_busy || !!data.external.length || ["planning","running","stopping"].includes(data.queue?.status||"");
  const queueLive = ["planning","running","stopping"].includes(data?.queue?.status||"");
  const runningNow = !!data?.active || queueLive;
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(()=>{ if(runningNow) setComposerOpen(false); },[runningNow]);
  const blockedReason = !data ? "플랫폼에 연결하는 중입니다." : offline ? "플랫폼 서버에 연결할 수 없습니다." : data.maintenance ? "하네스 업데이트 중입니다."
    : !data.model.online ? "모델 서버가 꺼져 있습니다. 모델 설정에서 확인하세요." : queueLive ? "작업 큐가 진행 중입니다. 끝나거나 중지한 뒤 새 작업을 시작할 수 있습니다."
    : data.active ? "실행 중인 작업이 있습니다." : data.chat_active ? "채팅이 모델을 사용 중입니다. 답변이 끝나면 시작할 수 있습니다."
    : data.workspace_busy || data.external.length ? "다른 프로젝트나 외부 프로세스가 모델을 사용 중입니다." : "";
  const events =
    page === "overview" || selectedId === latest?.id
      ? data?.events || []
      : history.id === selectedId ? history.events : [];
  const phase = data?.external.length
    ? "외부 작업 실행 중"
    : labels[data?.phase || "idle"];
  const recent = events[events.length - 1];
  return (
    <HStack
      height="100dvh"
      gap={0}
      style={{ overflow: "hidden", background: "var(--color-background-body)" }}
    >
      <SideNav
        header={
          <SideNavHeading
            heading="Local Workshop"
            subheading="말로 만드는 업무 앱"
            icon={<Mark kind="brand" />}
          />
        }
        topContent={<ProjectPicker/>}
        footer={<Text size="sm" style={{color: data?.model.online ? "var(--color-text-success)" : "var(--color-text-warning)"}}>● AI {data?.model.online ? "준비됨" : "연결 확인 중"}</Text>}
        collapsible={{
          isCollapsed: collapsed,
          onCollapsedChange: setCollapsed,
          hasButton: true,
        }}
      >
        {navGroups.map(([title, items]) => (
          <SideNavSection key={title || "main"} title={title || "업무"}>
            {items.map(([key, label]) => (
              <SideNavItem key={key} label={label} icon={<Mark kind={key} />} isSelected={page === key} onClick={() => navigate(key)} />
            ))}
          </SideNavSection>
        ))}
      </SideNav>
      <VStack gap={0} style={{ flex: 1, minWidth: 0, overflow: "hidden" }}>
        <VStack
          className="workspace-content"
          padding={4}
          gap={3}
          style={{ overflow: "auto", flex: 1, minWidth: 0, minHeight:0, textAlign:"left" }}
        >
          {data?.maintenance && <Card variant="muted"><Text>하네스 업데이트 중입니다. 검증 후 실행할 수 있습니다.</Text></Card>}
          {offline && (
            <Card variant="orange">
              <Text role="alert">
                플랫폼 연결 끊김 · 마지막 기록을 표시합니다. {offline}
              </Text>
            </Card>
          )}
          {error && (
            <Card variant="red">
              <HStack hAlign="between" gap={3}>
                <Text role="alert">{error}</Text>
                <Button
                  label="오류 닫기"
                  variant="ghost"
                  size="sm"
                  onClick={() => setError("")}
                />
              </HStack>
            </Card>
          )}
          {page === "home" && <HomePage token={data?.token||""} goal={goal} setGoal={setGoal} busy={busy}
            onUndo={async id => { const r = await apiFetch(`/api/queues/${id}/undo`, { method: "POST", headers: { "Content-Type": "application/json", "X-Platform-Token": data?.token || "" }, body: "{}" });
              const d = await r.json(); if (!r.ok) throw Error(d.error || `HTTP ${r.status}`); if (d.undone === false) throw Error(String(d.undo_note || "되돌리지 못했습니다.")); }}
            canStart={!disabled&&!!goal.trim()&&(useQueue||!!checks.length)&&!!data?.model.online&&!!effectiveModel} blockedReason={blockedReason} onStart={start}
            onOrder={async order => { await post("/api/queues", { goal: order, rounds, thinking, model: effectiveModel }); }}
            screens={data?.screens||[]} models={modelChoices} model={effectiveModel} setModel={value=>{setModel(value);localStorage.setItem("model:"+projectId,value);}}
            useQueue={useQueue} setUseQueue={next=>{setUseQueue(next);localStorage.setItem('use-queue',next?'1':'0');}} thinking={thinking} setThinking={setThinking}
            queue={data?.queue} active={data?.active||null} phase={data?.phase||"idle"} events={data?.events||[]} eventsJob={data?.jobs[0]?.id}
            onStopQueue={id=>void post(`/api/queues/${id}/stop`, {})} onResumeQueue={id=>void post(`/api/queues/${id}/resume`, {})} onStopJob={()=>void stop()}
            onOpenApp={()=>navigate("preview")} onOpenHistory={()=>navigate("history")} focusKey={focusKey}
            onDetail={id=>{setSelected(id);setSelectedRecord(null);setRunTab("logs");navigate("run");}}/>}
          {page === "overview" && (
            <>
              <OverviewStats jobs={data?.agent_jobs||[]} total={data?.agent_jobs_total} queue={data?.queue} online={!!data?.model.online}
                modelName={modelChoices.find(m=>m.value===effectiveModel)?.label||effectiveModel} active={data?.active||null}/>
              {data?.queue && ["planning","running","stopping"].includes(data.queue.status) && <QueuePanel queue={data.queue} busy={busy}
                onStop={() => void post(`/api/queues/${data.queue!.id}/stop`, {})} onResume={() => void post(`/api/queues/${data.queue!.id}/resume`, {})}
                onOpenJob={id => { setSelected(id); setSelectedRecord(null); setComposerOpen(false); setRunTab("logs"); navigate("run"); }} />}
              <LatestResult job={data?.latest_agent} refreshKey={data?.agent_events?.at(-1)?.seq} onSelect={j=>{setSelected(j.id);setSelectedRecord(j);setComposerOpen(false);setRunTab(j.status==='succeeded'?'changes':'logs');navigate("run");}}/>
              <Panel
                title="실행 로그"
                extra={
                  <Text color="secondary">
                    {data ? `갱신 ${clock(data.time)}` : "연결 중"}
                  </Text>
                }
              >
                <EventList events={events} jobId={latest?.id} running={!!data?.active}/>
              </Panel>
            </>
          )}
          {page === "run" && <>
            {data?.workspace_busy&&!data.active&&!queueLive&&<Text color="secondary">{data.chat_active?"채팅이 모델을 사용 중입니다.":"다른 프로젝트에서 실행 중입니다."}</Text>}
                  <RunComposer formRef={composerRef} open={composerOpen} setOpen={setComposerOpen} goal={goal} setGoal={setGoal}
                    models={[...modelChoices,...Object.entries(data?.model.unavailable||{}).map(([id,reason])=>({value:id,label:id+" · 미지원",description:reason,disabled:true}))]}
                    model={effectiveModel} setModel={value=>{setModel(value);localStorage.setItem("model:"+projectId,value);}}
                    available={data?.project.checks||["frontend","framework","backend"]} checks={checks}
                    toggleCheck={mode=>setChecks(prev=>prev.includes(mode)?prev.filter(x=>x!==mode):[...prev,mode])}
                    rounds={rounds} setRounds={setRounds} thinking={thinking} setThinking={setThinking}
                    useQueue={useQueue} setUseQueue={next=>{setUseQueue(next);localStorage.setItem('use-queue',next?'1':'0');}}
                    blockedReason={blockedReason} canStart={!disabled&&!!goal.trim()&&(useQueue||!!checks.length)&&!!data?.model.online&&!!effectiveModel}
                    onStart={start} screens={data?.screens||[]} running={!!data?.active} stopping={data?.active?.status==="stopping"} onStop={stop} busy={busy}/>

            {data?.queue && (queueLive || data.queue.id !== dismissedQueue) && <QueuePanel queue={data.queue} busy={busy}
              onDismiss={() => { setDismissedQueue(data.queue!.id); localStorage.setItem('queue-dismissed', data.queue!.id); }}
              onStop={() => void post(`/api/queues/${data.queue!.id}/stop`, {})}
              onResume={() => void post(`/api/queues/${data.queue!.id}/resume`, {})}
              onOpenJob={id => { setSelected(id); setSelectedRecord(null); setRunTab("logs"); }} />}
            <div className="actions-grid">
              <aside className="actions-history" aria-label="실행 탐색">
                <Heading level={3}>실행 기록</Heading>
                <JobHistory recent={data?.agent_jobs||data?.jobs.filter(j=>j.kind==='agent')||[]} cursor={data?.agent_jobs_next} total={data?.agent_jobs_total} kind="agent" selected={selectedId} onSelect={j=>{setSelected(j.id);setSelectedRecord(j);setRunTab("logs");}} renderJob={(j,choose,isSelected)=><RunRecordRow job={j} selected={isSelected} onClick={choose}/>}/>

              </aside>
              <section className="actions-detail" aria-label="실행 상세">
                {selectedJob?<>
                  <VStack gap={3}><HStack hAlign="between" gap={3}><Heading level={2}>{selectedJob.goal||"이전 검사 기록"}</Heading><Status value={selectedJob.status}/></HStack>
                  <HStack gap={4} style={{flexWrap:"wrap"}}><Text color="secondary">{selectedJob.id.slice(0,8)} · {stamp(selectedJob.started_at)}</Text><Text color="secondary">{Math.max(0,Math.floor((new Date(selectedJob.finished_at||data?.time||selectedJob.started_at).getTime()-new Date(selectedJob.started_at).getTime())/1000))}초</Text>{selectedJob.model&&selectedJob.kind==='agent'&&<Text color="secondary">{selectedJob.model}</Text>}</HStack></VStack>
                  <TabList role="tablist" aria-label="실행 보기" value={runTab} onChange={setRunTab}><Tab value="logs" label="로그" panelId="run-logs"/><Tab value="changes" label="변경 파일" panelId="run-changes"/><Tab value="context" label="컨텍스트" panelId="run-context"/><Tab value="verification" label="완료 조건" panelId="run-verification"/>{selectedJob.kind==='agent'&&<Tab value="flow" label="실행 흐름" panelId="run-flow"/>}</TabList>
                  <section id="run-verification" role="tabpanel" hidden={runTab!=='verification'}>{runTab==='verification'&&<VerificationPanel key={selectedJob.id} jobId={selectedJob.id} status={selectedJob.status}/>}</section>
                  <section id="run-context" role="tabpanel" hidden={runTab!=='context'}>{runTab==='context'&&<ContextPanel key={selectedJob.id} jobId={selectedJob.id} status={selectedJob.status}/>}</section>
                  <section id="run-changes" role="tabpanel" hidden={runTab!=='changes'}>{runTab==='changes'&&(selectedJob.kind==='agent'?<ChangesPanel key={selectedJob.id} jobId={selectedJob.id} refreshKey={events.at(-1)?.seq} autoOpen/>:<Text color="secondary">코드 변경이 없는 이전 검사 기록입니다.</Text>)}</section>
                  {selectedJob.kind==='agent'&&<section id="run-flow" role="tabpanel" hidden={runTab!=='flow'}>{runTab==='flow'&&<VStack gap={4}><StrategyPanel key={selectedJob.id} jobId={selectedJob.id} status={selectedJob.status}/><Flow events={events} job={selectedJob}/></VStack>}</section>}
                  <section id="run-logs" role="tabpanel" hidden={runTab!=='logs'}>{runTab==='logs'&&<VStack gap={4}>
                    {['failed','interrupted'].includes(selectedJob.status)&&<FailurePanel key={'failure-'+selectedJob.id} jobId={selectedJob.id} refreshKey={selectedJob.status}/>}
                    <ContextPanel key={'context-'+selectedJob.id} jobId={selectedJob.id} status={selectedJob.status} compact onOpen={()=>setRunTab("context")}/><Steps events={events} active={selectedJob.status==='running'}/>
                    <EventList events={events} jobId={selectedId} running={["running","stopping"].includes(selectedJob.status)}/>
                    <Collapsible trigger="프로세스 출력" defaultIsOpen={false}><Code>{output||"아직 출력이 없습니다."}</Code></Collapsible>
                    <Collapsible trigger="검사 소요 시간" defaultIsOpen={false}><Chart events={events} gates={data?.gates||[]}/></Collapsible>
                  </VStack>}</section>
                </>:<Text color="secondary">실행 기록이 없습니다. 새 작업을 시작하세요.</Text>}
              </section>
            </div>
          </>}
          {page === "tools" && <DevTools/>}
          {page === "projects" && <ProjectManager token={data?.token||""}/>}
          {page === "models" && <ModelManager token={data?.token||""}/>}
          {page === "environment" && <EnvironmentCheck token={data?.token||""}/>}
          {chatOpened && <div style={{display:page === "chat" ? "block" : "none",minWidth:0}}><ChatPanel token={data?.token||""} model={effectiveModel} online={!!data?.model.online} modelBusy={(!!data?.workspace_busy&&!data?.chat_active)||!!data?.active}/></div>}
          {sourceOpened && <VStack style={{display:page === "source" ? "flex" : "none",minWidth:0}}><Suspense fallback={<Text color="secondary">소스 화면 불러오는 중</Text>}><SourceBrowser/></Suspense></VStack>}
          {page === "preview" && <Preview token={data?.token||""}/>}
          {page === "guide" && <GuidePage/>}
          {page === "history" && <HistoryPage token={data?.token||""} busy={runningNow} onOpenJob={id => { setSelected(id); setSelectedRecord(null); setRunTab("logs"); navigate("run"); }}/>}
        </VStack>
      </VStack>
    </HStack>
  );
}
