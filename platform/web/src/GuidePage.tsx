import { useEffect, useState } from "react";
import { VStack, HStack } from "@astryxdesign/core/Layout";
import { Heading, Text } from "@astryxdesign/core/Text";
import { Button } from "@astryxdesign/core/Button";
import { apiFetch } from "./api";
import "./guide.css";

type Field = { label: string; words: string };
type Screen = { key: string; title: string; kind: string; layer?: number; flows: string[]; fields: Field[]; lines: { label: string; fields: Field[] }[]; sentences: string[]; usedBy: string[] };
type Flow = { name: string; stages: string[]; steps: { from: string; to: string; how: string[] }[] };
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
  const masters = (guide?.screens ?? []).filter(screen => screen.layer !== undefined).sort((a, b) => (a.layer ?? 0) - (b.layer ?? 0));
  const layers = [...new Set(masters.map(screen => screen.layer ?? 1))];
  const table = (fields: Field[]) => <table className="guide-fields"><thead><tr><th>항목</th><th>넣는 것</th></tr></thead>
    <tbody>{fields.map(field => <tr key={field.label}><td>{field.label}</td><td>{field.words}</td></tr>)}</tbody></table>;
  return <VStack gap={4}>
    <HStack hAlign="between" vAlign="center"><Heading level={2}>업무 안내서</Heading>
      <HStack gap={2}><Button label="새로 읽기" size="sm" variant="secondary" onClick={() => setAttempt(n => n + 1)} /><Button label="인쇄" size="sm" variant="secondary" onClick={() => window.print()} /></HStack></HStack>
    <Text color="secondary">이 프로젝트의 화면 정의에서 저절로 만들어집니다. 화면이 바뀌면 안내서도 함께 바뀌고, 로컬 모델도 화면을 만들기 전에 같은 내용을 읽습니다.</Text>
    {error && <Text role="alert">{error}</Text>}
    {guide && <div className="guide-body">
      <nav className="guide-toc" aria-label="안내서 목차">
        <button type="button" onClick={() => go("guide-flows")}>1. 업무 흐름</button>
        {guide.flows.map((flow, index) => <button type="button" key={flow.name} className="sub" onClick={() => go(`guide-flow-${index}`)}>{flow.name}</button>)}
        <button type="button" onClick={() => go("guide-masters")}>2. 기준 정보</button>
        <button type="button" onClick={() => go("guide-screens")}>3. 화면별 안내</button>
        {guide.screens.map(screen => <button type="button" key={screen.key} className="sub" onClick={() => go(`guide-screen-${screen.key}`)}>{screen.title}</button>)}
        <button type="button" onClick={() => go("guide-common")}>4. 모든 화면의 규칙</button>
      </nav>
      <article className="guide-book">
        <h3 id="guide-flows">1. 업무 흐름</h3>
        {guide.flows.length === 0 && <p className="muted">화면끼리 이어진 흐름이 아직 없습니다.</p>}
        {guide.flows.map((flow, index) => <section key={flow.name} id={`guide-flow-${index}`}>
          <h4>{flow.name}</h4>
          {flow.steps.map(step => <div key={`${step.from}-${step.to}`} className="guide-step"><strong>{name(step.from)} → {name(step.to)}</strong>
            <ul>{step.how.map(how => <li key={how}>{how}</li>)}</ul></div>)}
        </section>)}
        <h3 id="guide-masters">2. 기준 정보</h3>
        <p className="muted">업무 화면이 가져다 쓰는 자료입니다. Layer 1 은 혼자 서는 자료, Layer 2 부터는 아래 Layer 의 자료를 묶어 만든 자료입니다.</p>
        {layers.map(layer => <section key={layer}><h4>Layer {layer}</h4><ul>{masters.filter(screen => screen.layer === layer).map(screen => <li key={screen.key}>
          {screen.title}{screen.usedBy.length > 0 && <span className="muted"> - 쓰는 화면: {screen.usedBy.join(", ")}</span>}</li>)}</ul></section>)}
        <h3 id="guide-screens">3. 화면별 안내</h3>
        {guide.screens.map(screen => <section key={screen.key} id={`guide-screen-${screen.key}`} className="guide-screen">
          <h4>{screen.title} <span className="guide-kind">{screen.kind}{screen.layer ? ` · Layer ${screen.layer}` : ""}</span></h4>
          {screen.flows.length > 0 && <p className="muted">속한 흐름: {screen.flows.join(" / ")}</p>}
          {screen.fields.length > 0 && table(screen.fields)}
          {screen.lines.map(lines => <div key={lines.label}><p><strong>줄 표: {lines.label}</strong></p>{table(lines.fields)}</div>)}
          {screen.sentences.length > 0 && <ul>{screen.sentences.map(sentence => <li key={sentence}>{sentence}</li>)}</ul>}
          {screen.usedBy.length > 0 && <p className="muted">이 자료를 쓰는 화면: {screen.usedBy.join(", ")}</p>}
        </section>)}
        <h3 id="guide-common">4. 모든 화면의 규칙</h3>
        <ul>{guide.common.map(rule => <li key={rule}>{rule}</li>)}</ul>
      </article>
    </div>}
  </VStack>;
}
