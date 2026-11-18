import { useEffect, useMemo, useState } from "react";
import { VStack, HStack } from "@astryxdesign/core/Layout";
import { Heading, Text } from "@astryxdesign/core/Text";
import { Button } from "@astryxdesign/core/Button";
import { apiFetch } from "./api";

type State = { code: string; label: string; initial: boolean; closed: boolean };
type Step = { action: string; label: string; screens: { key: string; title: string }[] };
type Dep = { key: string; field: string; label: string; lines?: string };
type GNode = { key: string; title: string; states: State[]; steps: Step[]; layer?: number; dependsOn?: Dep[]; usedBy?: Dep[] };
type GEdge = { from: string; to: string; how: string; pointer?: string; screen?: string; label?: string };
type Screen = { key: string; title: string; kind: string; layer?: number; sentences: string[]; fields: { label: string; words: string }[] };
type Box = { key: string; x: number; y: number; w: number; h: number; master: boolean };

const HOW: Record<string, string> = { from: "가져와 만듦", take: "골라서 넘김", limit: "가리킴 (수량 한도)", expand: "자동 생성 (펼침)", create: "자동 생성", choose: "가리킴" };
const W = 190, MW = 150, MGAP = 80, GAPX = 90, GAPY = 26, LEFT = 20, TOP = 34;

/**
 * 업무 흐름도: the project's screens drawn as one picture, read off its definitions by the framework (GET /api/meta/graph) - nothing
 * drawn or kept by hand. Master data on the left by layer; each connected piece of work as a row from left to right, its links
 * labelled with how a later record comes of an earlier one; screens on their own below. A box opens its screen's sentences.
 */
export default function FlowMapPage() {
  const [graph, setGraph] = useState<{ nodes: GNode[]; edges: GEdge[] } | null>(null), [screens, setScreens] = useState<Screen[]>([]);
  const [error, setError] = useState(""), [masters, setMasters] = useState(true), [open, setOpen] = useState<string | null>(null), [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const read = (path: string) => apiFetch(path).then(async r => { const d = await r.json(); if (!r.ok) throw Error(d.error || "흐름도를 읽지 못했습니다."); return d; });
    Promise.all([read("/api/tools/graph"), read("/api/tools/process")]).then(([g, p]) => { setGraph(g); setScreens(p.screens || []); setError(""); })
      .catch(e => setError(String(e.message || e)));
  }, [attempt]);
  const screenOf = useMemo(() => new Map(screens.map(s => [s.key, s])), [screens]);
  const layout = useMemo(() => {
    if (!graph) return null;
    const isMaster = (key: string) => screenOf.get(key)?.layer !== undefined;
    const work = graph.nodes.filter(n => !isMaster(n.key));
    // the flow of work: how a later record comes of an earlier one (pointing alone is a dependency, drawn apart from the flow)
    const links = graph.edges.filter(e => !isMaster(e.from) && !isMaster(e.to) && e.how !== "choose");
    // dependencies: every field pointing at another screen, from the graph's dependsOn (the one source the framework keeps)
    // one arrow per pair of screens, however many fields point the same way (출발 창고 · 도착 창고)
    const byPair = new Map<string, GEdge>();
    graph.nodes.forEach(n => (n.dependsOn || []).forEach(d => {
      const name = d.lines ? `${d.lines} · ${d.label}` : d.label, pair = `${d.key}>${n.key}`, seen = byPair.get(pair);
      if (seen) seen.label = `${seen.label} · ${name}`; else byPair.set(pair, { from: d.key, to: n.key, how: "choose", label: name });
    }));
    const deps = [...byPair.values()];
    // pieces of work: nodes joined by links; a node's column is the longest way to it from where the piece starts
    const touch = new Map<string, string[]>();
    links.forEach(e => { touch.set(e.from, [...(touch.get(e.from) || []), e.to]); touch.set(e.to, [...(touch.get(e.to) || []), e.from]); });
    const seen = new Set<string>(), pieces: string[][] = [];
    work.forEach(n => { if (seen.has(n.key) || !touch.has(n.key)) return; const piece: string[] = [], todo = [n.key];
      while (todo.length) { const k = todo.pop()!; if (seen.has(k)) continue; seen.add(k); piece.push(k); (touch.get(k) || []).forEach(o => todo.push(o)); }
      pieces.push(piece); });
    const column = new Map<string, number>();
    work.forEach(n => column.set(n.key, 0));
    for (let round = 0; round < work.length; round++) links.forEach(e => { if ((column.get(e.to) ?? 0) < (column.get(e.from) ?? 0) + 1) column.set(e.to, Math.min(12, (column.get(e.from) ?? 0) + 1)); });
    const height = (key: string) => { const n = graph.nodes.find(x => x.key === key)!; return 46 + (n.states.length ? 18 : 0) + (stepScreens(n, graph.edges).length ? 18 : 0); };
    const boxes = new Map<string, Box>();
    const masterNodes = graph.nodes.filter(n => isMaster(n.key)).sort((a, b) => (screenOf.get(a.key)!.layer! - screenOf.get(b.key)!.layer!) || a.title.localeCompare(b.title));
    // master data in a column per layer (Layer 1 → Layer 2 → …), so what a combination is made of points at it from the left
    const layers = [...new Set(masterNodes.map(n => screenOf.get(n.key)!.layer!))].sort((a, b) => a - b);
    const columnTop = new Map<number, number>();
    masterNodes.forEach(n => { const layer = screenOf.get(n.key)!.layer!, at = layers.indexOf(layer), y0 = columnTop.get(layer) ?? TOP;
      boxes.set(n.key, { key: n.key, x: LEFT + at * (MW + MGAP), y: y0, w: MW, h: 40, master: true }); columnTop.set(layer, y0 + 40 + 14); });
    const y = Math.max(TOP, ...columnTop.values());
    const left = masterNodes.length ? LEFT + layers.length * (MW + MGAP) + GAPX - MGAP : LEFT;
    let rowY = TOP;
    const rows: { title: string; y: number }[] = [];
    pieces.forEach(piece => {
      rows.push({ title: "", y: rowY - 20 });
      const byColumn = new Map<number, string[]>();
      piece.forEach(k => byColumn.set(column.get(k)!, [...(byColumn.get(column.get(k)!) || []), k]));
      let bottom = rowY;
      byColumn.forEach((keys, c) => { let cy = rowY; keys.forEach(k => { const h = height(k); boxes.set(k, { key: k, x: left + c * (W + GAPX), y: cy, w: W, h, master: false }); cy += h + GAPY; }); bottom = Math.max(bottom, cy); });
      rowY = bottom + 30;
    });
    const alone = work.filter(n => !touch.has(n.key));
    const aloneY = rowY + 10;
    alone.forEach((n, i) => boxes.set(n.key, { key: n.key, x: left + (i % 4) * (W + 30), y: aloneY + Math.floor(i / 4) * 70, w: W, h: 46, master: false }));
    const width = Math.max(...[...boxes.values()].map(b => b.x + b.w), 400) + 20;
    const total = Math.max(...[...boxes.values()].map(b => b.y + b.h), y) + 20;
    return { boxes, links, layers, masterLinks: deps.filter(e => !isMaster(e.to) && boxes.has(e.from) && boxes.has(e.to)),
      layerLinks: deps.filter(e => isMaster(e.from) && isMaster(e.to)), alone: alone.length ? aloneY : null, left, width, total, rows };
  }, [graph, screenOf]);

  if (error) return <VStack gap={2}><Heading level={2}>업무 흐름도</Heading><Text color="secondary">{error}</Text><Button label="다시 읽기" size="sm" onClick={() => setAttempt(n => n + 1)} /></VStack>;
  if (!graph || !layout) return <Text color="secondary">읽는 중…</Text>;
  const node = (key: string) => graph.nodes.find(n => n.key === key)!;
  // a dependency: from the one that uses (its left side) to the one it points at (its right side), the arrow at what is depended on
  const depends = (user: Box, used: Box) => { const x1 = user.x, y1 = user.y + user.h / 2, x2 = used.x + used.w + 2, y2 = used.y + used.h / 2, mx = (x1 + x2) / 2;
    return { d: `M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2},${y2}`, mx, my: (y1 + y2) / 2 }; };
  const curve = (a: Box, b: Box) => { const x1 = a.x + a.w, y1 = a.y + a.h / 2, x2 = b.x, y2 = b.y + b.h / 2, mx = (x1 + x2) / 2;
    return { d: `M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2 - 2},${y2}`, mx, my: (y1 + y2) / 2 }; };
  const chosen = open ? screenOf.get(open) : null, chosenNode = open ? node(open) : null;
  const related = chosenNode ? stepScreens(chosenNode, graph.edges).map(k => screenOf.get(k)).filter(Boolean) as Screen[] : [];
  return <VStack gap={3}>
    <HStack hAlign="between" vAlign="center"><VStack gap={1}><Heading level={2}>업무 흐름도</Heading>
      <Text color="secondary">화면 정의에서 저절로 그린 그림입니다. 상자를 누르면 그 화면의 항목과 규칙이 열립니다.</Text></VStack>
      <HStack gap={2}><Button label={masters ? "업무 자료의 의존 선 숨기기" : "업무 자료의 의존 선 보기"} size="sm" variant="secondary" onClick={() => setMasters(v => !v)} />
        <Button label="다시 읽기" size="sm" variant="secondary" onClick={() => setAttempt(n => n + 1)} /></HStack></HStack>
    {!graph.nodes.length && <Text color="secondary">아직 만든 화면이 없습니다.</Text>}
    <HStack gap={3} vAlign="start">
      <div style={{ flex: 1, minWidth: 0, overflow: "auto", border: "1px solid var(--color-border)", borderRadius: 8 }}>
        <svg width={layout.width} height={layout.total} role="img" aria-label="업무 흐름도" style={{ display: "block", fontSize: 12 }}>
          <defs><marker id="flow-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0L10,5L0,10z" fill="var(--color-text-success)" /></marker>
            <marker id="flow-arrow-dim" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M0,0L10,5L0,10z" fill="var(--color-text-secondary)" /></marker></defs>
          {layout.layers.map((layer, i) => <text key={layer} x={LEFT + i * (MW + MGAP)} y={20} fill="var(--color-text-secondary)">기준 정보 · Layer {layer}</text>)}
          {layout.layerLinks.map((e, i) => { const c = depends(layout.boxes.get(e.to)!, layout.boxes.get(e.from)!);
            return <g key={`y${i}`}><path d={c.d} fill="none" stroke="var(--color-text-secondary)" strokeWidth={1.2} markerEnd="url(#flow-arrow-dim)" />
              {e.label && <text x={c.mx} y={c.my - 5} textAnchor="middle" fill="var(--color-text-secondary)" style={{ fontSize: 10 }}>{e.label}</text>}</g>; })}
          <text x={layout.left} y={20} fill="var(--color-text-secondary)">업무 흐름</text>
          {layout.alone !== null && <text x={layout.left} y={layout.alone - 8} fill="var(--color-text-secondary)">따로 쓰는 화면</text>}
          {masters && layout.masterLinks.map((e, i) => { const c = depends(layout.boxes.get(e.to)!, layout.boxes.get(e.from)!);
            return <g key={`m${i}`}><path d={c.d} fill="none" stroke="var(--color-text-secondary)" strokeDasharray="3 3" opacity={0.6} markerEnd="url(#flow-arrow-dim)" />
              {e.label && <text x={c.mx} y={c.my - 4} textAnchor="middle" fill="var(--color-text-secondary)" opacity={0.85} style={{ fontSize: 10 }}>{e.label}</text>}</g>; })}
          {layout.links.map((e, i) => { const a = layout.boxes.get(e.from), b = layout.boxes.get(e.to); if (!a || !b) return null; const c = curve(a, b);
            return <g key={`l${i}`}><path d={c.d} fill="none" stroke="var(--color-text-success)" strokeWidth={1.5} markerEnd="url(#flow-arrow)" />
              <text x={c.mx} y={c.my - 6} textAnchor="middle" fill="var(--color-text-primary)" style={{ fontSize: 11 }}>{HOW[e.how] || e.how}{e.label ? ` · ${e.label}` : ""}</text></g>; })}
          {[...layout.boxes.values()].map(b => { const n = node(b.key), states = ordered(n.states), on = screenStepTitles(n, graph.edges, screenOf);
            return <g key={b.key} onClick={() => setOpen(b.key)} style={{ cursor: "pointer" }}>
              <rect x={b.x} y={b.y} width={b.w} height={b.h} rx={7} fill={open === b.key ? "var(--color-background-surface-raised, rgba(127,127,127,.12))" : "var(--color-background-surface)"}
                stroke={b.master ? "var(--color-text-secondary)" : "var(--color-text-success)"} strokeDasharray={b.master ? "4 3" : undefined} strokeWidth={b.master ? 1 : 1.5} />
              <text x={b.x + 10} y={b.y + 18} fill="var(--color-text-primary)" style={{ fontWeight: 600 }}>{clip((b.master ? `L${screenOf.get(b.key)?.layer} ` : "") + n.title, b.w)}</text>
              {!b.master && states && <text x={b.x + 10} y={b.y + 36} fill="var(--color-text-secondary)" style={{ fontSize: 11 }}>{clip(states, b.w)}</text>}
              {!b.master && on && <text x={b.x + 10} y={b.y + (states ? 54 : 36)} fill="var(--color-text-secondary)" style={{ fontSize: 11 }}>{clip("화면: " + on, b.w)}</text>}
            </g>; })}
        </svg>
      </div>
      {chosen && <VStack gap={2} style={{ width: 320, flexShrink: 0 }}>
        <HStack hAlign="between" vAlign="center"><Heading level={3}>{chosen.title}</Heading><Button label="닫기" size="sm" variant="ghost" onClick={() => setOpen(null)} /></HStack>
        <Text color="secondary">{chosen.kind}{chosen.layer !== undefined ? ` · Layer ${chosen.layer}` : ""}</Text>
        {!!chosen.fields?.length && <Text>항목: {chosen.fields.map(f => `${f.label}(${f.words})`).join("; ")}</Text>}
        {chosen.sentences.map((s, i) => <Text key={i}>· {s}</Text>)}
        {related.map(r => <VStack key={r.key} gap={1}><Text style={{ fontWeight: 600 }}>{r.title}</Text>{r.sentences.map((s, i) => <Text key={i}>· {s}</Text>)}</VStack>)}
      </VStack>}
    </HStack>
  </VStack>;
}

function stepScreens(n: GNode, edges: GEdge[]) {
  return [...new Set([...n.steps.flatMap(s => s.screens.map(x => x.key)), ...edges.filter(e => e.to === n.key && e.screen).map(e => e.screen!)])];
}
function screenStepTitles(n: GNode, edges: GEdge[], screenOf: Map<string, Screen>) {
  return stepScreens(n, edges).map(k => screenOf.get(k)?.title ?? k).join(", ");
}
function ordered(states: State[]) {
  if (!states.length) return "";
  const open = states.filter(s => !s.closed), closed = states.filter(s => s.closed);
  return [...open.sort((a, b) => Number(b.initial) - Number(a.initial)).map(s => s.label)].join(" → ") + (closed.length ? " / " + closed.map(s => s.label).join(" · ") : "");
}
function clip(text: string, width: number) {
  const room = Math.floor((width - 18) / 12);
  return text.length > room ? text.slice(0, room - 1) + "…" : text;
}
