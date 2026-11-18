import { useEffect, useRef, useState } from 'react';
import { apiFetch } from '../auth/sessionClient';
import { Button, Dialog } from '../ui';
import { formatDateTime, showNumber } from '../format';

type Held = { id: number; name: string; size: number; by: string | null; at: string };
const sizeOf = (bytes: number) => (bytes >= 1024 * 1024 ? `${showNumber(bytes / 1024 / 1024, 1)} MB` : `${showNumber(Math.max(1, Math.round(bytes / 1024)))} KB`);
const LIMIT = 20 * 1024 * 1024;

/** The files attached to one record: add (several at once), download, remove. readOnly: only look and download. */
export function FilesDialog({ api, id, title, isOpen, onClose, readOnly, onCount }: { /** The record's API, e.g. /api/data/sales_order */ api: string; id: string | null; title: string;
  isOpen: boolean; onClose: () => void; readOnly?: boolean; /** Told the number of files whenever it changes. */ onCount?: (count: number) => void }) {
  const [files, setFiles] = useState<Held[] | null>(null);
  const [note, setNote] = useState<{ text: string; bad?: boolean } | null>(null);
  const [busy, setBusy] = useState(false);
  const picker = useRef<HTMLInputElement>(null);
  async function load() {
    const response = await apiFetch(`${api}/${id}/files`);
    if (!response.ok) { setNote({ text: '첨부 파일을 읽지 못했습니다.', bad: true }); return; }
    const list = await response.json() as Held[];
    setFiles(list); onCount?.(list.length);
  }
  useEffect(() => { if (isOpen && id) { setFiles(null); setNote(null); void load().catch(() => {}); } }, [api, id, isOpen]);   // eslint-disable-line react-hooks/exhaustive-deps
  async function add(chosen: FileList | null) {
    if (!chosen?.length) return;
    setBusy(true); setNote(null);
    const refused: string[] = [];
    for (const file of Array.from(chosen)) {
      if (file.size > LIMIT) { refused.push(`${file.name}: 20MB 를 넘습니다`); continue; }
      const response = await apiFetch(`${api}/${id}/files?name=${encodeURIComponent(file.name)}`, { method: 'POST', headers: { 'Content-Type': file.type || 'application/octet-stream' }, body: file });
      if (!response.ok) { const body = await response.json().catch(() => null) as { detail?: string } | null; refused.push(`${file.name}: ${body?.detail ?? `붙이지 못했습니다 (${response.status})`}`); }
    }
    await load().catch(() => {});
    setNote(refused.length ? { text: refused.join('\n'), bad: true } : { text: `${chosen.length}개를 붙였습니다.` });
    setBusy(false);
  }
  async function remove(file: Held) {
    setBusy(true); setNote(null);
    const response = await apiFetch(`${api}/${id}/files/${file.id}`, { method: 'DELETE' });
    if (!response.ok) { const body = await response.json().catch(() => null) as { detail?: string } | null; setNote({ text: body?.detail ?? '지우지 못했습니다.', bad: true }); }
    await load().catch(() => {});
    setBusy(false);
  }
  return <Dialog isOpen={isOpen} onClose={onClose} title={`${title} 첨부 파일`} width={680} footer={<Button label="닫기" onClick={onClose} />}>
    <div data-ui="record-files" className="fw-files">
      {!readOnly && <div className="fw-files-bar">
        <Button label="파일 붙이기" icon="paperclip" variant="primary" outlined isDisabled={busy} isLoading={busy} onClick={() => picker.current?.click()} />
        <input ref={picker} type="file" multiple hidden aria-label="붙일 파일" onChange={event => { const chosen = event.target.files; void add(chosen).finally(() => { if (picker.current) picker.current.value = ''; }); }} />
        <span className="fw-files-hint">파일 하나에 20MB 까지, 한 건에 30개까지</span>
      </div>}
      {note && <div role={note.bad ? 'alert' : 'status'} className={note.bad ? 'fw-files-note is-bad' : 'fw-files-note'}>{note.text}</div>}
      {files === null ? <div className="fw-history-empty">불러오는 중…</div> : files.length === 0 ? <div className="fw-history-empty">붙은 파일이 없습니다.</div>
        : <table className="fw-history-table bp6-html-table bp6-compact bp6-html-table-striped">
          <thead><tr><th>파일 이름</th><th style={{ width: 90 }}>크기</th><th style={{ width: 100 }}>올린 사람</th><th style={{ width: 150 }}>올린 일시</th>{!readOnly && <th style={{ width: 50 }} />}</tr></thead>
          <tbody>{files.map(file => <tr key={file.id}>
            <td><a href={`${api}/${id}/files/${file.id}`} download={file.name}>{file.name}</a></td>
            <td style={{ textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>{sizeOf(file.size)}</td>
            <td>{file.by ?? ''}</td>
            <td className="is-center">{formatDateTime(file.at)}</td>
            {!readOnly && <td className="is-center"><Button label={`${file.name} 지우기`} isIconOnly variant="ghost" icon="trash" isDisabled={busy} onClick={() => void remove(file)} /></td>}
          </tr>)}</tbody>
        </table>}
    </div>
  </Dialog>;
}
