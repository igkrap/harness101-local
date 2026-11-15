import { lazy, Suspense, useCallback, useEffect, useState } from "react";
import { VStack, HStack } from "@astryxdesign/core/Layout";
import { Text, Heading } from "@astryxdesign/core/Text";
import { Button } from "@astryxdesign/core/Button";
import { TextInput } from "@astryxdesign/core/TextInput";
import { Collapsible } from "@astryxdesign/core/Collapsible";
import { AlertDialog } from "@astryxdesign/core/AlertDialog";
import { apiFetch } from "./api";
import "./history.css";

const DiffEditor = lazy(() => import("./DiffEditor"));

type Commit = { sha: string; short: string; author: string; kind: "model" | "person" | "platform"; date: string; subject: string; body: string; job_id: string | null; tags: string[] };
type Status = { branch: string; branches: string[]; head: string | null; dirty: { path: string; status: string }[]; remote: string; ahead: number | null; unrecorded?: { site: string[]; files: string[] } };
type FileChange = { path: string; status: string; added: number; removed: number };
type Contents = { path: string; before: string; after: string };

const who: Record<Commit["kind"], string> = { model: "AI", person: "사람", platform: "플랫폼" };
const fileStatus: Record<string, string> = { added: "새 파일", deleted: "삭제", modified: "수정" };

function when(iso: string) {
  const d = new Date(iso);
  return d.toLocaleString("ko-KR", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

function deployLabel(tag: string) {
  const m = tag.match(/^deploy-(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})/);
  return m ? `서버 반영 ${Number(m[2])}/${Number(m[3])} ${m[4]}:${m[5]}` : tag;
}

/** Changed files of one commit (or of the unrecorded edits) with a before/after view. */
function Changes({ base }: { base: string }) {
  const [files, setFiles] = useState<FileChange[]>([]), [open, setOpen] = useState(""), [body, setBody] = useState<Contents | null>(null), [error, setError] = useState("");
  useEffect(() => {
    const c = new AbortController(); setOpen(""); setBody(null);
    apiFetch(base, { signal: c.signal }).then(async r => { const d = await r.json(); if (!r.ok) throw Error(d.error); setFiles(d.files || []); }).catch(e => { if (!c.signal.aborted) setError(String(e)); });
    return () => c.abort();
  }, [base]);
  useEffect(() => {
    if (!open) return; const c = new AbortController(); setBody(null);
    apiFetch(`${base}?path=${encodeURIComponent(open)}`, { signal: c.signal }).then(async r => { const d = await r.json(); if (!r.ok) throw Error(d.error); setBody(d); }).catch(e => { if (!c.signal.aborted) setError(String(e)); });
    return () => c.abort();
  }, [base, open]);
  return <VStack gap={2}>
    {error && <Text role="alert">{error}</Text>}
    {files.map(f => <HStack key={f.path} hAlign="between" gap={2}>
      <Button label={f.path} size="sm" className="history-file" variant={open === f.path ? "secondary" : "ghost"} onClick={() => setOpen(open === f.path ? "" : f.path)} />
      <HStack gap={2}><Text color="secondary">{fileStatus[f.status] || f.status}</Text><Text style={{ color: "var(--color-text-success)" }}>+{f.added}</Text><Text style={{ color: "var(--color-text-error)" }}>−{f.removed}</Text></HStack>
    </HStack>)}
    {body && <Suspense fallback={<Text color="secondary">비교 불러오는 중</Text>}><DiffEditor {...body} sideBySide={false} /></Suspense>}
  </VStack>;
}

export default function HistoryPage({ token, busy, onOpenJob }: { token: string; busy: boolean; onOpenJob: (id: string) => void }) {
  const [status, setStatus] = useState<Status | null>(null), [commits, setCommits] = useState<Commit[]>([]), [error, setError] = useState(""), [notice, setNotice] = useState("");
  const [selected, setSelected] = useState(""), [message, setMessage] = useState(""), [pending, setPending] = useState(false), [undoing, setUndoing] = useState<Commit | null>(null), [branch, setBranch] = useState(""), [remote, setRemote] = useState("");
  const load = useCallback(async () => {
    try { const r = await apiFetch("/api/history"); const d = await r.json(); if (!r.ok) throw Error(d.error); setStatus(d.status); setCommits(d.commits); setError(""); }
    catch (e) { setError(e instanceof Error ? e.message : String(e)); }
  }, []);
  useEffect(() => { void load(); }, [load, busy]);
  const act = async (action: string, body: object, done: string) => {
    setPending(true); setNotice("");
    try {
      const r = await apiFetch(`/api/history/${action}`, { method: "POST", headers: { "Content-Type": "application/json", "X-Platform-Token": token }, body: JSON.stringify(body) });
      const d = await r.json(); if (!r.ok) throw Error(d.error); setNotice(Array.isArray(d.lines) && d.lines.length ? d.lines.join(" ") : done); setError(""); await load();
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setPending(false); }
  };
  const locked = busy || pending;
  const loose = [...(status?.unrecorded?.site ?? []), ...(status?.unrecorded?.files ?? [])];
  const current = commits.find(c => c.sha === selected);
  return <div className="history-page">
    <VStack gap={4}>
      <VStack gap={1}><Heading level={2}>변경 이력</Heading><Text color="secondary">프로젝트에 무엇이 언제 바뀌었는지 기록됩니다. AI 작업이 성공하면 자동으로 기록되고, 필요하면 특정 변경만 취소할 수 있습니다.</Text></VStack>
      {busy && <Text color="secondary">AI 작업이 진행 중이라 기록·취소는 작업이 끝난 뒤 할 수 있습니다.</Text>}
      {error && <Text role="alert">{error}</Text>}
      {notice && <Text role="status">{notice}</Text>}
      {status && loose.length > 0 && <div className="history-unrecorded" data-ui="history-unrecorded">
        <VStack gap={3}>
          <Text weight="bold">아직 기록되지 않은 변경 {loose.length}개</Text>
          <Text color="secondary">요청 밖에서 바뀐 것입니다 (관리자 화면에서 고친 화면·메뉴 편성·공통 코드, 직접 고친 파일): {loose.slice(0, 8).join(", ")}{loose.length > 8 ? " …" : ""}. 기록해 두면 나중에 이 시점과 비교하거나 되돌릴 수 있습니다.</Text>
          <HStack gap={2} vAlign="end"><div style={{ flex: 1 }}><TextInput label="무엇을 바꿨나요?" value={message} onChange={setMessage} placeholder="예: 영업 메뉴 편성" /></div>
            <Button label="기록하기" isDisabled={locked || !message.trim()} onClick={() => void act("record", { message }, "기록했습니다.").then(() => setMessage(""))} /></HStack>
          {status.dirty.length > 0 && <Collapsible trigger="바뀐 파일 보기" defaultIsOpen={false}><Changes base="/api/history/working" /></Collapsible>}
        </VStack>
      </div>}
      <ol className="history-list" aria-label="변경 이력 목록">
        {commits.map(c => <li key={c.sha} className={selected === c.sha ? "history-item selected" : "history-item"}>
          <button type="button" className="history-row" onClick={() => setSelected(selected === c.sha ? "" : c.sha)} aria-expanded={selected === c.sha}>
            <span className={`history-who who-${c.kind}`}>{who[c.kind]}</span>
            <span className="history-subject">{c.subject}</span>
            {c.tags.filter(t => t.startsWith("deploy-")).map(t => <span key={t} className="history-deploy">{deployLabel(t)}</span>)}
            <span className="history-when">{when(c.date)}</span>
          </button>
          {selected === c.sha && current && <div className="history-detail">
            <VStack gap={3}>
              <HStack gap={2} style={{ flexWrap: "wrap" }}>
                {c.job_id && <Button label="AI 작업 기록 보기" size="sm" variant="secondary" onClick={() => onOpenJob(c.job_id!)} />}
                {c.sha === commits[0]?.sha ? <Button label="이 변경 취소하기" size="sm" variant="secondary" isDisabled={locked} onClick={() => setUndoing(c)} />
                  : <Text color="secondary">가장 최근 기록만 취소할 수 있습니다.</Text>}
                {loose.length > 0 && <Text color="secondary">기록되지 않은 변경은 취소하기 전에 먼저 자동으로 기록됩니다.</Text>}
              </HStack>
              {c.body && <Collapsible trigger="요청 원문" defaultIsOpen={false}><pre className="history-body">{c.body}</pre></Collapsible>}
              <Collapsible trigger="바뀐 파일과 코드 보기" defaultIsOpen={false}><Changes base={`/api/history/${c.sha}`} /></Collapsible>
            </VStack>
          </div>}
        </li>)}
        {status && commits.length === 0 && <Text color="secondary">아직 기록이 없습니다.</Text>}
      </ol>
      {status && <Collapsible trigger="작업 공간(브랜치)과 원격 저장소" defaultIsOpen={false}>
        <VStack gap={3} padding={2}>
          <Text color="secondary">작업 공간을 나누면 시험 삼아 바꿔 본 것을 지금 화면과 섞지 않고 보관할 수 있습니다. 현재: <b>{status.branch}</b></Text>
          <HStack gap={2} style={{ flexWrap: "wrap" }}>{status.branches.filter(b => b !== status.branch).map(b => <Button key={b} label={`${b}(으)로 전환`} size="sm" variant="ghost" isDisabled={locked} onClick={() => void act("branch", { name: b }, `${b} 작업 공간으로 전환했습니다.`)} />)}</HStack>
          <HStack gap={2} vAlign="end"><div style={{ flex: 1 }}><TextInput label="새 작업 공간 이름" value={branch} onChange={setBranch} placeholder="예: 회사화면-시안" /></div>
            <Button label="만들고 전환" size="sm" isDisabled={locked || !branch.trim()} onClick={() => void act("branch", { name: branch.trim(), create: true }, "새 작업 공간을 만들었습니다.").then(() => setBranch(""))} /></HStack>
          {status.remote ? <HStack gap={2}><Text color="secondary">원격: {status.remote}{status.ahead ? ` · 올리지 않은 기록 ${status.ahead}개` : ""}</Text><Button label="원격에 올리기" size="sm" variant="secondary" isDisabled={locked} onClick={() => void act("push", {}, "원격 저장소에 올렸습니다.")} /></HStack>
            : <Text color="secondary">원격 저장소가 연결되어 있지 않습니다.</Text>}
          <HStack gap={2} vAlign="end"><div style={{ flex: 1 }}><TextInput label={status.remote ? "원격 저장소 주소 바꾸기" : "원격 저장소 주소 (깃허브 등의 비공개 저장소)"} value={remote} onChange={setRemote} placeholder="https://github.com/내계정/프로젝트.git" /></div>
            <Button label="연결" size="sm" isDisabled={locked || !remote.trim()} onClick={() => void act("remote", { url: remote.trim() }, "원격 저장소를 연결했습니다.").then(() => setRemote(""))} /></HStack>
        </VStack>
      </Collapsible>}
    </VStack>
    <AlertDialog isOpen={!!undoing} onOpenChange={open => { if (!open) setUndoing(null); }} title="이 변경 취소하기"
      description={undoing ? `"${undoing.subject}" 변경을 취소합니다. 개발 사이트의 화면·메뉴·공통 코드도 따라 되돌아갑니다. 이후의 다른 변경은 그대로 두고, 취소한 것도 새 기록으로 남습니다.` : ""}
      cancelLabel="닫기" actionLabel="취소하기" actionVariant="destructive"
      onAction={() => { const c = undoing; setUndoing(null); if (c) void act("undo", { sha: c.sha }, `"${c.subject}" 변경을 취소했습니다.`); }} />
  </div>;
}
