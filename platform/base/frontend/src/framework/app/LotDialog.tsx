import { useEffect, useState } from 'react';
import { ledgerWords } from './definitions';
import { apiFetch } from '../auth/sessionClient';
import { Button, Dialog } from '../ui';
import { showAmount, showDate, showNumber } from '../format';

type Lot = { lot: string; receivedOn: string; unitCost: number; remaining: number; source: string };

/**
 * The lots of a thing that are held at a place, oldest first - to choose the one something is taken from.
 * Lots with the same number (the same maker's lot received twice) are shown as one line with what they hold together.
 */
export function LotDialog({ thing, place, isOpen, onClose, onPick }: { thing: string; place: string; isOpen: boolean; onClose: () => void; onPick: (lot: string) => void }) {
  const [lots, setLots] = useState<Lot[] | null>(null);
  const [problem, setProblem] = useState('');
  useEffect(() => {
    if (!isOpen) return;
    setLots(null); setProblem('');
    if (!thing || !place) { setProblem(!thing ? `먼저 ${ledgerWords().thing}을(를) 고르세요.` : `먼저 ${ledgerWords().place}을(를) 고르세요.`); return; }
    let alive = true;
    void apiFetch(`/api/auth/ledger/lots?thing=${encodeURIComponent(thing)}&place=${encodeURIComponent(place)}`).then(async response => {
      if (!alive) return;
      if (!response.ok) { setProblem(`${ledgerWords().lot}을(를) 읽지 못했습니다.`); return; }
      const merged = new Map<string, Lot>();
      for (const lot of await response.json() as Lot[]) {
        const held = merged.get(lot.lot);
        if (held) held.remaining = Number(held.remaining) + Number(lot.remaining); else merged.set(lot.lot, { ...lot, remaining: Number(lot.remaining) });
      }
      setLots([...merged.values()]);
    }).catch(() => { if (alive) setProblem(`${ledgerWords().lot}을(를) 읽지 못했습니다.`); });
    return () => { alive = false; };
  }, [isOpen, thing, place]);
  return <Dialog isOpen={isOpen} onClose={onClose} title="LOT 고르기" width={640} footer={<Button label="닫기" onClick={onClose} />}>
    <div data-ui="lot-picker" className="fw-history">
      {problem && <div role="alert">{problem}</div>}
      {!problem && lots === null && <div className="fw-history-empty">불러오는 중…</div>}
      {lots?.length === 0 && <div className="fw-history-empty">이 창고에 이 품목의 재고가 없습니다.</div>}
      {lots && lots.length > 0 && <table className="fw-history-table bp6-html-table bp6-compact bp6-html-table-striped">
        <thead><tr><th>LOT</th><th style={{ width: 100 }}>입고일</th><th style={{ width: 100 }}>단가</th><th style={{ width: 100 }}>남은 수량</th><th style={{ width: 150 }}>들어온 화면</th><th style={{ width: 60 }} /></tr></thead>
        <tbody>{lots.map(lot => <tr key={lot.lot}>
          <td className="is-center">{lot.lot}</td><td className="is-center">{showDate(lot.receivedOn)}</td>
          <td style={{ textAlign: 'right' }}>{showAmount(Number(lot.unitCost))}</td><td style={{ textAlign: 'right' }}>{showNumber(lot.remaining)}</td><td>{lot.source}</td>
          <td className="is-center"><Button label={`${lot.lot} 선택`} outlined onClick={() => { onPick(lot.lot); onClose(); }} /></td>
        </tr>)}</tbody>
      </table>}
    </div>
  </Dialog>;
}
