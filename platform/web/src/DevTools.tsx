import { useEffect, useState } from "react";
import { apiFetch } from "./api";

type Screen = { key: string; title: string; type: string | null; program: string; fields: string[]; lines: string[]; records: number; last: { when: string; subject: string } | null };
type Field = { name: string; label: string; notes: string[] };
type Detail = { key: string; rev: string | null; exists_now: boolean; title?: string; parts?: string[]; fields?: Field[]; lines?: Field[]; differences?: string[];
  history: { sha: string; when: string; who: string; subject: string }[]; definition: unknown };
type Records = { key: string; total: number; rows: { id: number; status: string | null; data: Record<string, unknown>; updated_by: string | null; updated_at: string | null }[] };
type Log = { container: string; state: string; url: string; database: string; lines: string[] };
const kinds: Record<string, string> = { master: "기준 정보", document: "줄 표 화면", summary: "집계", dashboard: "현황판", over: "업무 화면" };
const read = async <T,>(path: string): Promise<T> => { const r = await apiFetch(path); const d = await r.json(); if (!r.ok) throw Error(d.error || "읽지 못했습니다."); return d as T; };
const cell = (value: unknown) => (value === null || value === undefined ? "" : typeof value === "object" ? JSON.stringify(value) : String(value));

/** Looking inside the project: its screens as definitions and how they changed, the records it holds, its server's log. Read only. */
export default function DevTools() {
  const [tab, setTab] = useState<"screens" | "log">("screens");
  const [screens, setScreens] = useState<Screen[] | null>(null), [error, setError] = useState("");
  const [chosen, setChosen] = useState(""), [rev, setRev] = useState(""), [detail, setDetail] = useState<Detail | null>(null);
  const [view, setView] = useState<"fields" | "records" | "json">("fields"), [records, setRecords] = useState<Records | null>(null);
  const [log, setLog] = useState<Log | null>(null), [find, setFind] = useState("");
  useEffect(() => { read<{ screens: Screen[] }>("/api/tools/screens").then(d => { setScreens(d.screens); setError(""); }).catch(e => setError(String(e.message || e))); }, []);
  useEffect(() => { if (!chosen) { setDetail(null); return; }
    read<Detail>(`/api/tools/screen?key=${encodeURIComponent(chosen)}${rev ? `&rev=${rev}` : ""}`).then(d => { setDetail(d); setError(""); }).catch(e => setError(String(e.message || e))); }, [chosen, rev]);
  useEffect(() => { if (chosen && view === "records") read<Records>(`/api/tools/records?key=${encodeURIComponent(chosen)}`).then(setRecords).catch(e => setError(String(e.message || e))); }, [chosen, view]);
  const loadLog = () => read<Log>("/api/tools/log?lines=500").then(d => { setLog(d); setError(""); }).catch(e => setError(String(e.message || e)));
  useEffect(() => { if (tab === "log" && !log) void loadLog(); }, [tab]);   // eslint-disable-line react-hooks/exhaustive-deps
  const shown = (screens || []).filter(s => !find.trim() || (s.title + s.key).toLowerCase().includes(find.trim().toLowerCase()));
  const columns = records?.rows.length ? [...new Set(records.rows.flatMap(row => Object.keys(row.data).filter(name => name !== "lines")))].slice(0, 10) : [];
  const fieldTable = (title: string, fields: Field[]) => fields.length > 0 && <>
    <h4>{title}</h4>
    <table className="biz-table"><thead><tr><th style={{ width: "24%" }}>이름</th><th style={{ width: "20%" }}>영문 이름</th><th>종류와 조건</th></tr></thead>
      <tbody>{fields.map(f => <tr key={f.name}><td>{f.label}</td><td className="dim">{f.name}</td><td>{f.notes.join(" · ")}</td></tr>)}</tbody></table>
  </>;
  return <div className="devtools" data-ui="devtools">
    <div className="devtools-tabs" role="tablist">
      <button type="button" role="tab" aria-selected={tab === "screens"} onClick={() => setTab("screens")}>화면 정의와 자료</button>
      <button type="button" role="tab" aria-selected={tab === "log"} onClick={() => setTab("log")}>서버 기록</button>
    </div>
    {error && <p role="alert" className="devtools-error">{error}</p>}
    {tab === "screens" && <div className="devtools-split">
      <div className="devtools-list">
        <input type="search" aria-label="화면 찾기" placeholder="화면 찾기" value={find} onChange={e => setFind(e.target.value)} />
        <table className="biz-table"><thead><tr><th>화면</th><th style={{ width: 84 }}>종류</th><th className="num" style={{ width: 56 }}>자료</th></tr></thead>
          <tbody>{shown.map(s => <tr key={s.key} className={chosen === s.key ? "is-chosen" : undefined} onClick={() => { setChosen(s.key); setRev(""); setView("fields"); setRecords(null); }}>
            <td title={s.last ? `마지막 변경 ${s.last.when}: ${s.last.subject}` : s.key}>{s.title}<span className="dim"> {s.key}</span></td><td className="dim">{kinds[s.type || ""] || s.type || ""}</td><td className="num">{s.records || ""}</td></tr>)}
          {screens && shown.length === 0 && <tr><td colSpan={3} className="dim">{screens.length ? "맞는 화면이 없습니다." : "아직 화면이 없습니다."}</td></tr>}</tbody></table>
      </div>
      <div className="devtools-detail">
        {!detail ? <p className="dim">왼쪽에서 화면을 고르면 그 화면의 정의, 바뀐 이력, 들어 있는 자료를 봅니다.</p> : <>
          <h3>{detail.title || detail.key} <span className="dim">{detail.key}{detail.exists_now ? "" : " · 지금은 없는 화면"}</span></h3>
          {detail.parts && detail.parts.length > 0 && <p className="dim">{detail.parts.join(" · ")}</p>}
          <div className="devtools-bar">
            <span className="devtools-seg" role="group" aria-label="볼 것">
              {(["fields", "records", "json"] as const).map(v => <button key={v} type="button" aria-pressed={view === v} onClick={() => setView(v)}>{{ fields: "항목", records: "자료", json: "정의 원문" }[v]}</button>)}</span>
            <label>버전 <select aria-label="볼 버전" value={rev} onChange={e => setRev(e.target.value)}>
              <option value="">지금 (개발 사이트)</option>
              {detail.history.map(h => <option key={h.sha} value={h.sha}>{h.when} · {h.subject.slice(0, 40)}</option>)}</select></label>
          </div>
          {rev && detail.differences && <div className="devtools-diff" data-ui="devtools-diff"><b>이 버전에서 지금까지 바뀐 것</b><ul>{detail.differences.map((line, i) => <li key={i}>{line}</li>)}</ul></div>}
          {view === "fields" && <>{fieldTable("항목", detail.fields || [])}{fieldTable("줄 표 항목", detail.lines || [])}</>}
          {view === "json" && <pre className="devtools-json">{JSON.stringify(detail.definition, null, 1)}</pre>}
          {view === "records" && (records ? <>
            <p className="dim">{records.total.toLocaleString("en-US")}건 중 최신 {records.rows.length}건 (개발 사이트의 자료, 읽기 전용)</p>
            <div className="devtools-scroll"><table className="biz-table"><thead><tr><th style={{ width: 64 }}>id</th>{columns.map(name => <th key={name}>{name}</th>)}<th style={{ width: 80 }}>상태</th><th style={{ width: 90 }}>수정자</th></tr></thead>
              <tbody>{records.rows.map(row => <tr key={row.id}><td className="num">{row.id}</td>{columns.map(name => <td key={name} title={cell(row.data[name])}>{cell(row.data[name])}</td>)}<td>{row.status || ""}</td><td className="dim">{row.updated_by || ""}</td></tr>)}
              {records.rows.length === 0 && <tr><td colSpan={columns.length + 3} className="dim">자료가 없습니다.</td></tr>}</tbody></table></div></> : <p className="dim">불러오는 중…</p>)}
        </>}
      </div>
    </div>}
    {tab === "log" && <div className="devtools-log">
      <div className="devtools-bar"><span className="dim">{log ? `${log.container} · ${log.state} · ${log.url} · DB ${log.database}` : "불러오는 중…"}</span><span style={{ flex: 1 }} />
        <button type="button" className="home-btn" onClick={() => void loadLog()}>새로 고침</button></div>
      <pre className="devtools-json" data-ui="devtools-log">{log?.lines.join("\n")}</pre>
    </div>}
  </div>;
}
