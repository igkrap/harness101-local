import { Fragment, useEffect, useState } from "react";
import { Button } from "@astryxdesign/core/Button";
import { TextInput } from "@astryxdesign/core/TextInput";
import { apiFetch } from "./api";

type Set = { id: string; name: string; requests: string[]; created: string };
type Summary = { id: string; set: string; name: string; started: string; ended?: string; state: string; total: number; done: number;
  counts: Record<string, number>; passed: number; first_try: number; invented: number; average: number | null; versions: Record<string, string> };
type Item = { request: string; outcome: string; seconds: number; calls?: number; checks?: number; invented: number; said: string };
type Run = { id: string; name: string; requests: string[]; items: Item[]; state: string; error?: string; cleanup?: string; summary: Summary };
type Listing = { sets: Set[]; runs: Summary[]; running: string | null; outcomes: string[] };

const good = (outcome: string) => outcome === "첫 시도 통과" || outcome === "재시도 후 완료";
const center = { textAlign: "center" as const };

/** Measurement: sets of plain requests run on a throwaway project, each run kept with what it ran on, two runs side by side. */
export default function BenchmarksPage({ token }: { token: string }) {
  const [data, setData] = useState<Listing | null>(null), [error, setError] = useState(""), [busy, setBusy] = useState("");
  const [editing, setEditing] = useState<{ id?: string; name: string; text: string } | null>(null);
  const [open, setOpen] = useState<Run | null>(null), [picked, setPicked] = useState<string[]>([]), [pair, setPair] = useState<[Run, Run] | null>(null);
  const load = () => apiFetch("/api/benchmarks").then(r => r.json()).then(d => { setData(d); setError(""); }).catch(e => setError(String(e.message || e)));
  useEffect(() => { void load(); }, []);
  useEffect(() => { if (!data?.running) return; const timer = setInterval(() => void load(), 5000); return () => clearInterval(timer); }, [data?.running]);
  const post = async (path: string, body: object) => {
    const r = await apiFetch(path, { method: "POST", headers: { "Content-Type": "application/json", "X-Platform-Token": token }, body: JSON.stringify(body) });
    const d = await r.json(); if (!r.ok || d.error) throw Error(d.error || "하지 못했습니다."); return d;
  };
  const act = async (key: string, path: string, body: object, after?: () => void) => {
    setBusy(key);
    try { await post(path, body); after?.(); await load(); } catch (e) { setError(String((e as Error).message || e)); } finally { setBusy(""); }
  };
  const detail = (id: string) => apiFetch(`/api/benchmarks/run?id=${encodeURIComponent(id)}`).then(r => r.json()) as Promise<Run>;
  const show = async (id: string) => { if (open?.id === id) { setOpen(null); return; } setOpen(await detail(id)); };
  const compare = async () => { if (picked.length !== 2) return; const [a, b] = await Promise.all(picked.map(detail)); setPair([a, b]); };
  const last = (set: Set) => data?.runs.find(run => run.set === set.id && run.ended);
  const running = data?.runs.find(run => run.id === data?.running);

  return <div className="devtools" data-ui="benchmarks" style={{ display: "flex", flexDirection: "column", gap: 16 }}>
    {error && <p className="dim" role="alert">{error}</p>}
    {running && <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
      <b>측정 중: {running.name}</b><span className="dim">{running.state} · {running.done}/{running.total}</span>
      <Button label={busy === "stop" ? "멈추는 중…" : "멈추기"} size="sm" variant="secondary" isDisabled={!!busy || !token} onClick={() => void act("stop", "/api/benchmarks/stop", {})} />
    </div>}

    <section>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 6 }}>
        <h3 style={{ margin: 0 }}>측정 묶음</h3>
        <Button label="새 묶음" size="sm" variant="secondary" isDisabled={!token} onClick={() => setEditing({ name: "", text: "" })} />
      </div>
      {editing && <div style={{ display: "flex", flexDirection: "column", gap: 8, padding: 12, border: "1px solid var(--color-border)", borderRadius: 8, marginBottom: 8 }}>
        <TextInput label="이름" value={editing.name} onChange={value => setEditing({ ...editing, name: value })} />
        <label style={{ display: "flex", flexDirection: "column", gap: 4, fontSize: 12, color: "var(--color-text-secondary)" }}>요청 문장 (한 줄에 하나, 요청할 순서대로)
          <textarea value={editing.text} rows={8} onChange={e => setEditing({ ...editing, text: e.target.value })}
            style={{ font: "inherit", fontSize: 13, padding: 8, borderRadius: 6, border: "1px solid var(--color-border-emphasized, var(--color-border))", background: "var(--color-background-surface)", color: "var(--color-text-primary)" }} /></label>
        <div style={{ display: "flex", gap: 8 }}>
          <Button label="저장" size="sm" variant="primary" isDisabled={!!busy || !token} onClick={() => void act("save", "/api/benchmarks/sets", { id: editing.id, name: editing.name, requests: editing.text }, () => setEditing(null))} />
          <Button label="그만두기" size="sm" variant="secondary" onClick={() => setEditing(null)} />
        </div>
      </div>}
      <table className="biz-table">
        <thead><tr><th>이름</th><th className="num" style={{ width: 64 }}>요청</th><th style={{ width: 140, ...center }}>마지막 측정</th><th className="num" style={{ width: 96 }}>첫 시도 통과</th><th style={{ width: 210 }}></th></tr></thead>
        <tbody>
          {(data?.sets || []).map(set => { const recent = last(set); return <tr key={set.id}>
            <td title={set.requests.join("\n")}>{set.name}</td>
            <td className="num">{set.requests.length}</td>
            <td style={center}>{recent ? recent.started : ""}</td>
            <td className="num">{recent ? `${recent.first_try}/${recent.total}` : ""}</td>
            <td><span style={{ display: "inline-flex", gap: 6 }}>
              <Button label="돌리기" size="sm" variant="secondary" isDisabled={!!busy || !token || !!data?.running} onClick={() => void act("start" + set.id, "/api/benchmarks/start", { set: set.id })} />
              <Button label="고치기" size="sm" variant="secondary" isDisabled={!token} onClick={() => setEditing({ id: set.id, name: set.name, text: set.requests.join("\n") })} />
              <Button label="지우기" size="sm" variant="secondary" isDisabled={!!busy || !token} onClick={() => void act("del" + set.id, "/api/benchmarks/sets/delete", { id: set.id })} />
            </span></td>
          </tr>; })}
          {data && data.sets.length === 0 && <tr><td colSpan={5} className="dim">아직 측정 묶음이 없습니다.</td></tr>}
        </tbody>
      </table>
    </section>

    <section>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 6 }}>
        <h3 style={{ margin: 0 }}>측정 기록</h3>
        <Button label="둘 나란히 보기" size="sm" variant="secondary" isDisabled={picked.length !== 2} onClick={() => void compare()} />
      </div>
      <table className="biz-table">
        <thead><tr><th style={{ width: 32 }}></th><th style={{ width: 140, ...center }}>시작</th><th>묶음</th><th style={{ width: 96, ...center }}>상태</th>
          <th className="num" style={{ width: 96 }}>첫 시도 통과</th><th className="num" style={{ width: 96 }}>재시도 포함</th><th className="num" style={{ width: 84 }}>지어낸 내용</th>
          <th className="num" style={{ width: 84 }}>평균(초)</th><th style={{ width: 180 }}>모델 · 프레임워크 · 지시문</th></tr></thead>
        <tbody>
          {(data?.runs || []).map(run => <Fragment key={run.id}>
            <tr onClick={() => void show(run.id)} style={{ cursor: "pointer" }} className={open?.id === run.id ? "is-selected" : undefined}>
              <td onClick={e => e.stopPropagation()}><input type="checkbox" aria-label="비교할 기록" checked={picked.includes(run.id)}
                onChange={e => setPicked(e.target.checked ? [...picked, run.id].slice(-2) : picked.filter(id => id !== run.id))} /></td>
              <td style={center}>{run.started}</td>
              <td>{run.name}</td>
              <td style={center}>{run.ended ? run.state : `${run.done}/${run.total}`}</td>
              <td className="num">{run.first_try}/{run.total}</td>
              <td className="num">{run.passed}/{run.total}</td>
              <td className="num">{run.invented}</td>
              <td className="num">{run.average ?? ""}</td>
              <td className="dim" title={JSON.stringify(run.versions)}>{[run.versions.model, run.versions.framework, run.versions.instructions].filter(Boolean).join(" · ")}</td>
            </tr>
            {open?.id === run.id && <tr><td colSpan={9} style={{ whiteSpace: "normal", padding: 8 }}>
              {open.error && <p className="dim">{open.error}</p>}{open.cleanup && <p className="dim">{open.cleanup}</p>}
              <table className="biz-table">
                <thead><tr><th className="num" style={{ width: 36 }}>#</th><th>요청</th><th style={{ width: 110, ...center }}>결과</th><th className="num" style={{ width: 70 }}>초</th>
                  <th className="num" style={{ width: 80 }}>모델 호출</th><th className="num" style={{ width: 60 }}>점검</th><th className="num" style={{ width: 84 }}>지어낸 내용</th></tr></thead>
                <tbody>{open.requests.map((request, index) => { const item = open.items[index]; return <tr key={index}>
                  <td className="num">{index + 1}</td><td title={item?.said || request}>{request}</td>
                  <td style={{ ...center, color: item ? (good(item.outcome) ? "var(--color-text-success, #2f9e44)" : "var(--color-text-danger, #e03131)") : undefined }}>{item?.outcome ?? "하지 않음"}</td>
                  <td className="num">{item?.seconds ?? ""}</td><td className="num">{item?.calls ?? ""}</td><td className="num">{item?.checks ?? ""}</td><td className="num">{item?.invented ?? ""}</td>
                </tr>; })}</tbody>
              </table></td></tr>}
          </Fragment>)}
          {data && data.runs.length === 0 && <tr><td colSpan={9} className="dim">아직 측정 기록이 없습니다.</td></tr>}
        </tbody>
      </table>
    </section>

    {pair && <section>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 6 }}>
        <h3 style={{ margin: 0 }}>나란히 보기: {pair[0].summary.started} ↔ {pair[1].summary.started}</h3>
        <Button label="닫기" size="sm" variant="secondary" onClick={() => setPair(null)} />
      </div>
      <table className="biz-table">
        <thead><tr><th>요청</th><th style={{ width: 110, ...center }}>A 결과</th><th style={{ width: 110, ...center }}>B 결과</th><th className="num" style={{ width: 70 }}>A 초</th><th className="num" style={{ width: 70 }}>B 초</th></tr></thead>
        <tbody>
          {[...new Set([...pair[0].requests, ...pair[1].requests])].map(request => {
            const a = pair[0].items[pair[0].requests.indexOf(request)], b = pair[1].items[pair[1].requests.indexOf(request)];
            const differs = (a?.outcome ?? "") !== (b?.outcome ?? "");
            return <tr key={request} className={differs ? "is-selected" : undefined}>
              <td title={request}>{request}</td><td style={center}>{a?.outcome ?? "-"}</td><td style={center}>{b?.outcome ?? "-"}</td>
              <td className="num">{a?.seconds ?? ""}</td><td className="num">{b?.seconds ?? ""}</td></tr>;
          })}
          <tr><td><b>합계</b></td><td style={center}>첫 시도 {pair[0].summary.first_try}/{pair[0].summary.total}</td><td style={center}>첫 시도 {pair[1].summary.first_try}/{pair[1].summary.total}</td>
            <td className="num">{pair[0].summary.average ?? ""}</td><td className="num">{pair[1].summary.average ?? ""}</td></tr>
        </tbody>
      </table>
    </section>}
  </div>;
}
