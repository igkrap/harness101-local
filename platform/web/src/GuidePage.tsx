import { useEffect, useState } from "react";
import { VStack, HStack } from "@astryxdesign/core/Layout";
import { Heading, Text } from "@astryxdesign/core/Text";
import { Button } from "@astryxdesign/core/Button";
import { apiFetch } from "./api";
import "./guide.css";

type Field = { label: string; words: string };
type Screen = { key: string; title: string; kind: string; layer?: number; flows: string[]; fields: Field[]; lines: { label: string; fields: Field[] }[]; sentences: string[]; usedBy: string[] };
type Flow = { name: string; title?: string; stages: string[]; screens?: string[]; steps: { from: string; to: string; how: string[] }[] };
type Guide = { flows: Flow[]; screens: Screen[]; common: string[] };

/**
 * 업무 안내서 of the project being made: its flows, its master data by layer, every screen in sentences and the rules every
 * screen has - read off the project's screen definitions by its framework (the same text the model reads). Lives on the
 * platform, beside the project, not inside the system people use.
 */
export default function GuidePage() {
  const [guide, setGuide] = useState<Guide | null>(null), [error, setError] = useState(""), [attempt, setAttempt] = useState(0);
  useEffect(() => {
    apiFetch("/api/tools/process").then(async r => { const d = await r.json(); if (!r.ok) throw Error(d.error || "안내서를 읽지 못했습니다."); setGuide(d as Guide); setError(""); })
      .catch(e => setError(String(e.message || e)));
  }, [attempt]);
  const byKey = new Map((guide?.screens ?? []).map(screen => [screen.key, screen]));
  const name = (key: string) => byKey.get(key)?.title ?? key;
  const go = (id: string) => document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });
  // screens by category: master data by layer, then the work - instructions (first stage of a flow) and results (later stages) -, then the screens over them
  const firstStages = new Set((guide?.flows ?? []).map(flow => flow.stages[0]));
  const laterStages = new Set((guide?.flows ?? []).flatMap(flow => flow.stages.slice(1)));
  const category = (screen: Screen) => screen.layer !== undefined ? `기준 정보 · Layer ${screen.layer}`
    : screen.kind === "업무" ? (firstStages.has(screen.key) && !laterStages.has(screen.key) ? "업무 · 지시" : laterStages.has(screen.key) ? "업무 · 실적" : "업무")
    : ["이어받기", "업무 처리"].includes(screen.kind) ? "이어받기·처리 화면" : "조회 화면";
  const order = (name: string) => name.startsWith("기준 정보") ? `0${name}` : name === "업무 · 지시" ? "1" : name === "업무 · 실적" ? "2" : name === "업무" ? "3" : name === "이어받기·처리 화면" ? "4" : "5";
  const flowTitle = (flow: Flow) => flow.title ?? `${name(flow.stages[0]).replace(/\s*(등록|관리|입력)$/, "")} - ${name(flow.stages[flow.stages.length - 1]).replace(/\s*(등록|관리|입력)$/, "")}`;
  const flowScreens = (flow: Flow) => (flow.screens ?? flow.stages).filter(key => byKey.has(key));
  const inFlows = new Set((guide?.flows ?? []).flatMap(flowScreens));
  const groups = [...new Set((guide?.screens ?? []).filter(screen => !inFlows.has(screen.key)).map(category))].sort((a, b) => order(a).localeCompare(order(b)))
    .map(name => ({ name, screens: (guide?.screens ?? []).filter(screen => !inFlows.has(screen.key) && category(screen) === name) }));
  const card = (screen: Screen) => <section key={screen.key} id={`guide-screen-${screen.key}`} className="guide-screen">
    <h5>{screen.title} <span className="guide-kind">{screen.kind}{screen.layer ? ` · Layer ${screen.layer}` : ""}</span></h5>
    {screen.fields.length > 0 && table(screen.fields)}
    {screen.lines.map(lines => <div key={lines.label}><p><strong>줄 표: {lines.label}</strong></p>{table(lines.fields)}</div>)}
    {screen.sentences.length > 0 && <ul>{screen.sentences.map(sentence => <li key={sentence}>{sentence}</li>)}</ul>}
    {screen.usedBy.length > 0 && <p className="muted">이 자료를 쓰는 화면: {screen.usedBy.join(", ")}</p>}
  </section>;
  const masterGroups = groups.filter(group => group.name.startsWith("기준 정보")), otherGroups = groups.filter(group => !group.name.startsWith("기준 정보"));
  const table = (fields: Field[]) => <table className="guide-fields"><thead><tr><th>항목</th><th>넣는 것</th></tr></thead>
    <tbody>{fields.map(field => <tr key={field.label}><td>{field.label}</td><td>{field.words}</td></tr>)}</tbody></table>;
  return <VStack gap={4}>
    <HStack hAlign="between" vAlign="center"><Heading level={2}>업무 안내서</Heading>
      <HStack gap={2}><Button label="새로 읽기" size="sm" variant="secondary" onClick={() => setAttempt(n => n + 1)} /><Button label="인쇄" size="sm" variant="secondary" onClick={() => window.print()} /></HStack></HStack>
    <Text color="secondary">이 프로젝트의 화면 정의에서 저절로 만들어집니다. 화면이 바뀌면 안내서도 함께 바뀌고, 로컬 모델도 화면을 만들기 전에 같은 내용을 읽습니다.</Text>
    {error && <Text role="alert">{error}</Text>}
    {guide && <div className="guide-body">
      <nav className="guide-toc" aria-label="안내서 목차">
        <button type="button" onClick={() => go("guide-masters")}>1. 기준 정보</button>
        {masterGroups.map((group, index) => <div key={group.name} className="guide-toc-group"><button type="button" className="sub" onClick={() => go(`guide-group-${group.name}`)}>1-{index + 1}. {group.name.replace("기준 정보 · ", "")}</button>
          {group.screens.map(screen => <button type="button" key={screen.key} className="sub2" onClick={() => go(`guide-screen-${screen.key}`)}>{screen.title}</button>)}</div>)}
        <button type="button" onClick={() => go("guide-flows")}>2. 업무 프로세스</button>
        {guide.flows.map((flow, index) => <div key={flow.name} className="guide-toc-group"><button type="button" className="sub" onClick={() => go(`guide-flow-${index}`)}>2-{index + 1}. {flowTitle(flow)}</button>
          {flowScreens(flow).map(key => <button type="button" key={key} className="sub2" onClick={() => go(`guide-screen-${key}`)}>{name(key)}</button>)}</div>)}
        {otherGroups.length > 0 && <button type="button" onClick={() => go("guide-others")}>3. 그 밖의 화면</button>}
        {otherGroups.map((group, index) => <div key={group.name} className="guide-toc-group"><button type="button" className="sub" onClick={() => go(`guide-group-${group.name}`)}>3-{index + 1}. {group.name}</button>
          {group.screens.map(screen => <button type="button" key={screen.key} className="sub2" onClick={() => go(`guide-screen-${screen.key}`)}>{screen.title}</button>)}</div>)}
        <button type="button" onClick={() => go("guide-common")}>{otherGroups.length > 0 ? 4 : 3}. 모든 화면의 규칙</button>
      </nav>
      <article className="guide-book">
        <h3 id="guide-masters">1. 기준 정보</h3>
        <p className="muted">업무 화면이 가져다 쓰는 자료입니다. Layer 1 은 혼자 서는 자료, Layer 2 부터는 아래 Layer 의 자료를 묶어 만든 자료입니다.</p>
        {masterGroups.map((group, index) => <section key={group.name} className="guide-group"><h4 id={`guide-group-${group.name}`} className="guide-group-title">1-{index + 1}. {group.name.replace("기준 정보 · ", "")}</h4>
          {group.screens.map(card)}</section>)}
        <h3 id="guide-flows">2. 업무 프로세스</h3>
        {guide.flows.length === 0 && <p className="muted">화면끼리 이어진 프로세스가 아직 없습니다.</p>}
        {guide.flows.map((flow, index) => <section key={flow.name} id={`guide-flow-${index}`} className="guide-group">
          <h4 className="guide-group-title">2-{index + 1}. {flowTitle(flow)}</h4>
          <p className="muted">{flowScreens(flow).map(name).join(" → ")}</p>
          {flow.steps.map(step => <div key={`${step.from}-${step.to}`} className="guide-step"><strong>{name(step.from)} → {name(step.to)}</strong>
            <ul>{step.how.map(how => <li key={how}>{how}</li>)}</ul></div>)}
          {flowScreens(flow).map(key => card(byKey.get(key)!))}
        </section>)}
        {otherGroups.length > 0 && <h3 id="guide-others">3. 그 밖의 화면</h3>}
        {otherGroups.map((group, index) => <section key={group.name} className="guide-group"><h4 id={`guide-group-${group.name}`} className="guide-group-title">3-{index + 1}. {group.name}</h4>
          {group.screens.map(card)}</section>)}
        <h3 id="guide-common">{otherGroups.length > 0 ? 4 : 3}. 모든 화면의 규칙</h3>
        <ul>{guide.common.map(rule => <li key={rule}>{rule}</li>)}</ul>
      </article>
    </div>}
  </VStack>;
}
