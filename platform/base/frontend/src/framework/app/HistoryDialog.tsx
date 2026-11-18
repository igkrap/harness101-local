import { useEffect, useState } from 'react';
import { apiFetch } from '../auth/sessionClient';
import { Button, Dialog } from '../ui';
import { formatDateTime } from '../format';

type Entry = { at: string; by: string | null; action: string; what: string; automatic: boolean; changes: { label: string; before: string; after: string }[] };

/** Who changed one record, when and what - newest first, in the words the screen itself uses. */
export function HistoryDialog({ api, id, title, isOpen, onClose }: { /** The record's API, e.g. /api/data/sales_order */ api: string; id: string | null; title: string; isOpen: boolean; onClose: () => void }) {
  const [entries, setEntries] = useState<Entry[] | null>(null);
  const [problem, setProblem] = useState('');
  useEffect(() => {
    if (!isOpen || !id) return;
    let alive = true;
    setEntries(null); setProblem('');
    void apiFetch(`${api}/${id}/history`).then(async response => {
      if (!alive) return;
      if (response.ok) setEntries(await response.json() as Entry[]); else setProblem('이력을 읽지 못했습니다.');
    }).catch(() => { if (alive) setProblem('이력을 읽지 못했습니다.'); });
    return () => { alive = false; };
  }, [api, id, isOpen]);
  return <Dialog isOpen={isOpen} onClose={onClose} title={`${title} 변경 이력`} width={760} footer={<Button label="닫기" onClick={onClose} />}>
    <div data-ui="record-history" className="fw-history fw-selectable">
      {problem && <div role="alert">{problem}</div>}
      {!problem && entries === null && <div className="fw-history-empty">불러오는 중…</div>}
      {entries?.length === 0 && <div className="fw-history-empty">남은 이력이 없습니다. (이력 기능이 생기기 전에 만든 자료입니다.)</div>}
      {entries && entries.length > 0 && <table className="fw-history-table bp6-html-table bp6-compact bp6-html-table-striped">
        <thead><tr><th style={{ width: 150 }}>일시</th><th style={{ width: 100 }}>누가</th><th style={{ width: 90 }}>무엇을</th><th>바뀐 내용</th></tr></thead>
        <tbody>{entries.map((entry, index) => <tr key={index}>
          <td className="is-center">{formatDateTime(entry.at)}</td>
          <td>{entry.by ?? ''}</td>
          <td className="is-center">{entry.what}{entry.automatic && <span className="fw-history-auto" title="다른 자료의 처리에 따라 자동으로 일어난 일">자동</span>}</td>
          <td>{entry.changes.length === 0 ? <span className="fw-history-none">{entry.action === 'UPDATE' ? '값은 그대로 저장' : ''}</span>
            : <ul>{entry.changes.map((change, at) => <li key={at}><b>{change.label}</b> {change.before === '' ? <span className="fw-history-none">(없음)</span> : <del>{change.before}</del>} → {change.after === '' ? <span className="fw-history-none">(없음)</span> : <ins>{change.after}</ins>}</li>)}</ul>}</td>
        </tr>)}</tbody>
      </table>}
    </div>
  </Dialog>;
}
