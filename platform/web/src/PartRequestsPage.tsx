import { Fragment, useEffect, useState } from "react";
import { Button } from "@astryxdesign/core/Button";
import { apiFetch } from "./api";

type Ask = { when: string; project: string; request: string; why: string };
type Item = { id: string; part: string; state: string; count: number; first: string; last: string; asks: Ask[]; decided?: string };

/** Parts the framework does not have yet, asked for by requests the model could not answer with the parts there are (the same list
 *  for every project: the framework is one). A person decides: made, or not made. */
export default function PartRequestsPage({ token }: { token: string }) {
  const [items, setItems] = useState<Item[] | null>(null), [open, setOpen] = useState(""), [error, setError] = useState(""), [busy, setBusy] = useState("");
  const load = () => apiFetch("/api/part-requests").then(r => r.json()).then(d => { setItems(d.items || []); setError(""); }).catch(e => setError(String(e.message || e)));
  useEffect(() => { void load(); }, []);
  const decide = async (id: string, state: string) => {
    setBusy(id);
    try {
      const r = await apiFetch("/api/part-requests/decide", { method: "POST", headers: { "Content-Type": "application/json", "X-Platform-Token": token }, body: JSON.stringify({ id, state }) });
      const d = await r.json(); if (!r.ok || d.error) throw Error(d.error || "바꾸지 못했습니다.");
      await load();
    } catch (e) { setError(String((e as Error).message || e)); } finally { setBusy(""); }
  };
  const day = (when: string) => when.slice(0, 10);
  return <div className="devtools" data-ui="part-requests">
    {error && <p className="dim" role="alert">{error}</p>}
    <table className="biz-table">
      <thead><tr><th style={{ width: 96, textAlign: "center" }}>마지막 요청</th><th>필요한 부품</th><th className="num" style={{ width: 72 }}>요청 횟수</th>
        <th style={{ width: 72, textAlign: "center" }}>상태</th><th style={{ width: 168 }}></th></tr></thead>
      <tbody>
        {(items || []).map(item => <Fragment key={item.id}>
          <tr onClick={() => setOpen(open === item.id ? "" : item.id)} style={{ cursor: "pointer" }} aria-expanded={open === item.id}>
            <td style={{ textAlign: "center" }}>{day(item.last)}</td>
            <td title={item.part}>{item.part}</td>
            <td className="num">{item.count}</td>
            <td style={{ textAlign: "center" }}>{item.state}</td>
            <td onClick={e => e.stopPropagation()}>
              {item.state === "대기"
                ? <span style={{ display: "inline-flex", gap: 6 }}>
                    <Button label="만듦" size="sm" variant="secondary" isDisabled={!!busy || !token} onClick={() => void decide(item.id, "만듦")} />
                    <Button label="안 함" size="sm" variant="secondary" isDisabled={!!busy || !token} onClick={() => void decide(item.id, "안 함")} /></span>
                : <Button label="다시 대기로" size="sm" variant="secondary" isDisabled={!!busy || !token} onClick={() => void decide(item.id, "대기")} />}
            </td>
          </tr>
          {open === item.id && item.asks.map((ask, index) => <tr key={index} className="is-selected">
            <td style={{ textAlign: "center" }}>{day(ask.when)}</td>
            <td colSpan={4} style={{ whiteSpace: "normal" }}>
              <div>{ask.request}</div>
              <div className="dim">{[ask.project, ask.why].filter(Boolean).join(" · ")}</div>
            </td>
          </tr>)}
        </Fragment>)}
        {items && items.length === 0 && <tr><td colSpan={5} className="dim">아직 부품 요청이 없습니다.</td></tr>}
        {!items && !error && <tr><td colSpan={5} className="dim">불러오는 중…</td></tr>}
      </tbody>
    </table>
  </div>;
}
