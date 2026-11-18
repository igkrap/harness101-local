import { useRef, useState } from 'react';
import { apiFetch } from '../auth/sessionClient';
import { Button, Dialog, TextArea } from '../ui';
import { downloadSheet, readSheet } from '../xlsx';

/** Rows of a sheet: comma- or tab-separated text with quoted cells ("a ""quoted"" value", cells holding line breaks). */
export function parseSheet(text: string): string[][] {
  const delimiter = text.split('\n', 1)[0].includes('\t') ? '\t' : ',';
  const rows: string[][] = [];
  let row: string[] = [], cell = '', quoted = false;
  for (let index = 0; index < text.length; index++) {
    const char = text[index];
    if (quoted) {
      if (char === '"' && text[index + 1] === '"') { cell += '"'; index++; }
      else if (char === '"') quoted = false;
      else cell += char;
    } else if (char === '"' && cell === '') quoted = true;
    else if (char === delimiter) { row.push(cell); cell = ''; }
    else if (char === '\n' || char === '\r') {
      if (char === '\r' && text[index + 1] === '\n') index++;
      row.push(cell); cell = '';
      if (row.some(value => value.trim() !== '')) rows.push(row);
      row = [];
    } else cell += char;
  }
  row.push(cell);
  if (row.some(value => value.trim() !== '')) rows.push(row);
  return rows;
}
/** A file saved by Excel in Korea is often not UTF-8: read it as UTF-8 when it is, as the Korean code page otherwise. */
async function readText(file: File): Promise<string> {
  const bytes = await file.arrayBuffer();
  try { return new TextDecoder('utf-8', { fatal: true }).decode(bytes).replace(/^﻿/, ''); }
  catch { return new TextDecoder('euc-kr').decode(bytes); }
}

type Problem = { row: number; message: string };
/**
 * Many records at once: paste cells copied from a spreadsheet, or choose a CSV file. The first row names the columns
 * with the labels on screen; every other row becomes a record, checked by the same rules as typing it in. All or nothing.
 */
export function ImportDialog({ title, api, labels, isOpen, onClose, onDone, note: extra }: { title: string; api: string; labels: readonly string[]; isOpen: boolean; onClose: () => void; onDone: (stored: number) => void;
  /** One more line under the buttons, e.g. how lines are grouped into records. */ note?: string }) {
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const [problems, setProblems] = useState<Problem[]>([]);
  const [note, setNote] = useState('');
  const picker = useRef<HTMLInputElement>(null);
  const rows = text.trim() ? parseSheet(text) : [];
  const heads = rows[0]?.map(value => value.trim()) ?? [];
  const unknown = heads.filter(head => head && !labels.includes(head));

  function template() { downloadSheet(`${title}_올리기 양식`, [[...labels]]); }
  /** A chosen file as the text the box holds: an Excel file's first sheet (tab separated, so cells may hold commas), or a CSV as it is. */
  async function take(file: File) {
    if (/\.xlsx$/i.test(file.name)) {
      try {
        const quote = (cell: string) => (/["\t\r\n]/.test(cell) ? `"${cell.replace(/"/g, '""')}"` : cell);
        setText(readSheet(new Uint8Array(await file.arrayBuffer())).map(row => row.map(quote).join('\t')).join('\n'));
      } catch (problem) { setNote(problem instanceof Error ? problem.message : '엑셀 파일을 읽지 못했습니다.'); }
    } else if (/\.xls$/i.test(file.name)) setNote('예전 형식(.xls)은 읽지 못합니다. 엑셀에서 .xlsx 로 저장해 올려 주세요.');
    else setText(await readText(file));
  }
  async function send() {
    setBusy(true); setProblems([]); setNote('');
    try {
      const body = { rows: rows.slice(1).map(row => Object.fromEntries(heads.map((head, index) => [head, (row[index] ?? '').trim()]).filter(([head]) => head))) };
      const response = await apiFetch(`${api}/import`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      const result = await response.json().catch(() => ({})) as { stored?: number; rows?: number; problems?: Problem[]; detail?: string };
      if (!response.ok) { setNote(result.detail || '올리지 못했습니다.'); return; }
      if (result.problems?.length) { setProblems(result.problems); setNote(`${result.rows}줄 중 ${result.problems.length}줄에 문제가 있어 하나도 저장하지 않았습니다. 고친 뒤 다시 올리세요.`); return; }
      setText(''); onDone(result.stored ?? 0); onClose();
    } finally { setBusy(false); }
  }
  return <Dialog isOpen={isOpen} onClose={onClose} title={`${title} 한꺼번에 올리기`} width={720}
    footer={<>
      <Button label="닫기" onClick={onClose} />
      <Button label={rows.length > 1 ? `${rows.length - 1}줄 올리기` : '올리기'} variant="primary" isDisabled={busy || rows.length < 2 || unknown.length > 0} isLoading={busy} onClick={() => void send()} />
    </>}>
    <div data-ui="import-dialog" className="fw-import">
      <div className="fw-import-bar">
        <Button label="엑셀 파일 고르기" icon="document-open" onClick={() => picker.current?.click()} />
        <Button label="양식 받기" icon="download" onClick={template} />
        <input ref={picker} type="file" accept=".xlsx,.csv,.txt,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" hidden onChange={event => { const file = event.target.files?.[0]; event.target.value = ''; if (file) { setProblems([]); setNote(''); void take(file); } }} />
        <span className="fw-import-hint">첫 줄: {labels.join(', ')}</span>
      </div>
      {extra && <div className="fw-import-hint">{extra}</div>}
      <TextArea label="엑셀에서 복사한 칸을 여기에 붙여넣기 (첫 줄은 항목 이름)" value={text} onChange={value => { setText(value); setProblems([]); setNote(''); }} rows={9} />
      {unknown.length > 0 && <div role="alert" className="fw-import-note is-bad">이 화면에 없는 항목 이름입니다: {unknown.join(', ')}</div>}
      {note && <div role={problems.length ? 'alert' : 'status'} className={problems.length ? 'fw-import-note is-bad' : 'fw-import-note'}>{note}</div>}
      {problems.length > 0 && <ul className="fw-import-problems fw-selectable">{problems.slice(0, 100).map(problem => <li key={problem.row}><b>{problem.row + 1}번째 줄</b> {problem.message}</li>)}</ul>}
    </div>
  </Dialog>;
}
