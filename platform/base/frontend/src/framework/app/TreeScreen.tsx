import { useEffect, useMemo, useState } from 'react';
import { apiFetch } from '../auth/sessionClient';
import { ScreenTitle } from '../ScreenTitle';
import { Button, SearchInput } from '../ui';
import { useWorkspaceNav } from '../workspace/navContext';
import { alignOf, showValue } from '../format';
import type { EntityDefinition } from './definitions';
import { intentOf } from './links';
import './views.css';

type Column = { name: string; label: string; type: string };
type Node = { id: number; parent: number | null; label: string; values: Record<string, unknown> };
type Edge = { id: number; parent: number; child: number; values: Record<string, unknown> };
type Answer = { entity: string; programCode: string; sourceTitle: string; columns: Column[]; nodes?: Node[]; edges?: Edge[]; names?: Record<string, string> };
/** One line of the drawn tree: where it sits, what it reads, which record of the source screen it is. */
type Line = { path: string; depth: number; label: string; values: Record<string, unknown>; record: number | null; children: number };

/**
 * A tree screen, drawn from its definition: the source entity's records as a hierarchy, folded and unfolded. Records with
 * their own parent make the tree directly; pairs of parent and child (a bill of materials) make a tree of the records
 * they join, a record appearing under every parent it has. Choosing a line opens that record on its own screen.
 */
export function TreeScreen({ entity }: { entity: EntityDefinition }) {
  const { title } = entity.definition;
  const nav = useWorkspaceNav();
  const [answer, setAnswer] = useState<Answer | null>(null);
  const [problem, setProblem] = useState('');
  const [closed, setClosed] = useState<Set<string>>(new Set());
  const [find, setFind] = useState('');
  const load = () => { void apiFetch(`/api/tree/${entity.key}`).then(async response => {
    if (response.ok) { setAnswer(await response.json() as Answer); setProblem(''); } else setProblem('자료를 읽지 못했습니다.'); }).catch(() => setProblem('자료를 읽지 못했습니다.')); };
  useEffect(load, [entity.key, entity.revision]);   // eslint-disable-line react-hooks/exhaustive-deps

  const lines = useMemo(() => {
    const out: Line[] = [];
    if (!answer) return out;
    if (answer.nodes) {
      const ids = new Set(answer.nodes.map(node => node.id));
      const under = new Map<number | null, Node[]>();
      for (const node of answer.nodes) { const up = node.parent !== null && ids.has(node.parent) && node.parent !== node.id ? node.parent : null; under.set(up, [...(under.get(up) ?? []), node]); }
      const walk = (parent: number | null, depth: number, path: string, seen: Set<number>) => {
        for (const node of under.get(parent) ?? []) {
          if (seen.has(node.id)) continue;        // a loop in the data: shown once
          const here = `${path}/${node.id}`, kids = (under.get(node.id) ?? []).length;
          out.push({ path: here, depth, label: node.label, values: node.values, record: node.id, children: kids });
          if (!closed.has(here)) walk(node.id, depth + 1, here, new Set([...seen, node.id]));
        }
      };
      walk(null, 0, '', new Set());
    } else if (answer.edges) {
      const under = new Map<number, Edge[]>(), children = new Set(answer.edges.map(edge => edge.child));
      for (const edge of answer.edges) under.set(edge.parent, [...(under.get(edge.parent) ?? []), edge]);
      const walk = (id: number, depth: number, path: string, seen: Set<number>, via: Edge | null) => {
        const here = `${path}/${id}`, kids = seen.has(id) ? [] : under.get(id) ?? [];
        out.push({ path: here, depth, label: answer.names?.[String(id)] ?? String(id), values: via?.values ?? {}, record: via?.id ?? null, children: kids.length });
        if (!closed.has(here)) for (const edge of kids) walk(edge.child, depth + 1, here, new Set([...seen, id]), edge);
      };
      for (const root of [...under.keys()].filter(id => !children.has(id))) walk(root, 0, '', new Set(), null);
    }
    return out;
  }, [answer, closed]);
  const needle = find.trim().toLowerCase();
  const shown = needle ? lines.filter(line => line.label.toLowerCase().includes(needle)) : lines;
  const toggle = (path: string) => setClosed(previous => { const next = new Set(previous); if (next.has(path)) next.delete(path); else next.add(path); return next; });
  const foldAll = () => setClosed(new Set(lines.filter(line => line.children > 0).map(line => line.path)));
  return <div data-ui="tree" className="fw-tree">
    <header className="fw-view-head">
      <ScreenTitle>{title}</ScreenTitle>
      <span style={{ width: 240 }}><SearchInput label="찾기" placeholder="이름으로 찾기" value={find} onChange={setFind} /></span>
      <Button label="모두 펼치기" outlined onClick={() => setClosed(new Set())} /><Button label="모두 접기" outlined onClick={foldAll} />
      <span style={{ flex: 1 }} />
      {answer && <span className="fw-view-note">{answer.sourceTitle} · {shown.length.toLocaleString('en-US')}줄</span>}
      <Button label="새로 고침" icon="refresh" outlined onClick={load} />
    </header>
    {problem && <div role="alert">{problem}</div>}
    <div className="fw-tree-body">
      <table className="fw-tree-table bp6-html-table bp6-compact" role="treegrid" aria-label={title}>
        <thead><tr><th>이름</th>{(answer?.columns ?? []).map(column => <th key={column.name} style={{ width: 150 }}>{column.label}</th>)}</tr></thead>
        <tbody>{shown.map(line => <tr key={line.path} role="row" aria-level={line.depth + 1} aria-expanded={line.children ? !closed.has(line.path) : undefined}>
          <td><span style={{ paddingLeft: needle ? 0 : line.depth * 18 }} className="fw-tree-name">
            {line.children > 0 && !needle ? <Button label={closed.has(line.path) ? '펼치기' : '접기'} isIconOnly variant="ghost" icon={closed.has(line.path) ? 'chevron-right' : 'chevron-down'} className="fw-tree-fold" onClick={() => toggle(line.path)} /> : <span className="fw-tree-fold" />}
            {line.record !== null && nav && answer ? <Button label={line.label || '(이름 없음)'} variant="ghost" className="fw-tree-open" onClick={() => nav.open(answer.programCode, intentOf({ params: {}, note: '', select: String(line.record) }))} /> : <span>{line.label}</span>}
            {line.children > 0 && <span className="fw-tree-count">{line.children}</span>}</span></td>
          {(answer?.columns ?? []).map(column => <td key={column.name} style={{ textAlign: alignOf(column.type) ?? 'left' }}>{showValue(column.type, line.values[column.name])}</td>)}
        </tr>)}
        {answer && shown.length === 0 && <tr><td colSpan={1 + (answer.columns?.length ?? 0)} className="fw-view-note">{needle ? '맞는 것이 없습니다.' : '자료가 없습니다.'}</td></tr>}</tbody>
      </table>
    </div>
  </div>;
}
