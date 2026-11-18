import { useEffect, useMemo, useState } from 'react';
import { apiFetch } from '../auth/sessionClient';
import { ScreenTitle } from '../ScreenTitle';
import { Button, ContentButton } from '../ui';
import { useWorkspaceNav } from '../workspace/navContext';
import { statusTone, definitionOf, type EntityDefinition } from './definitions';
import { intentOf } from './links';
import './views.css';

type Item = { id: number; date: string; end: string | null; label: string; status?: string; statusLabel?: string };
type Answer = { month: string; entity: string; programCode: string; sourceTitle: string; items: Item[] };
const pad = (value: number) => String(value).padStart(2, '0');
const key = (date: Date) => `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;

/**
 * A calendar screen, drawn from its definition: one month, each record of the source entity on its day (on every day of
 * its period when it has an end date). It stores nothing; choosing a record opens it on its own screen.
 */
export function CalendarScreen({ entity }: { entity: EntityDefinition }) {
  const { title } = entity.definition;
  const nav = useWorkspaceNav();
  const [month, setMonth] = useState(() => { const now = new Date(); return `${now.getFullYear()}-${pad(now.getMonth() + 1)}`; });
  const [answer, setAnswer] = useState<Answer | null>(null);
  const [problem, setProblem] = useState('');
  useEffect(() => {
    let alive = true;
    void apiFetch(`/api/calendar/${entity.key}?month=${month}`).then(async response => {
      if (!alive) return;
      if (response.ok) { setAnswer(await response.json() as Answer); setProblem(''); } else setProblem('일정을 읽지 못했습니다.');
    }).catch(() => { if (alive) setProblem('일정을 읽지 못했습니다.'); });
    return () => { alive = false; };
  }, [entity.key, entity.revision, month]);
  const [year, monthNumber] = month.split('-').map(Number);
  const move = (by: number) => { const next = new Date(year, monthNumber - 1 + by, 1); setMonth(`${next.getFullYear()}-${pad(next.getMonth() + 1)}`); };
  // Six weeks from the Sunday on or before the first of the month.
  const days = useMemo(() => { const first = new Date(year, monthNumber - 1, 1); const start = new Date(first); start.setDate(1 - first.getDay());
    return Array.from({ length: 42 }, (_, index) => { const day = new Date(start); day.setDate(start.getDate() + index); return day; }); }, [year, monthNumber]);
  const on = (day: string) => (answer?.items ?? []).filter(item => item.date <= day && (item.end ?? item.date) >= day);
  const status = answer ? definitionOf(answer.entity)?.status : null;
  const today = key(new Date());
  const weeks = days.slice(35).some(day => day.getMonth() === monthNumber - 1) ? 6 : 5;
  return <div data-ui="calendar" className="fw-calendar">
    <header className="fw-view-head">
      <ScreenTitle>{title}</ScreenTitle>
      <span className="fw-view-move"><Button label="이전 달" isIconOnly icon="chevron-left" onClick={() => move(-1)} /><strong aria-live="polite">{year}/{pad(monthNumber)}</strong><Button label="다음 달" isIconOnly icon="chevron-right" onClick={() => move(1)} />
        <Button label="이번 달" outlined onClick={() => { const now = new Date(); setMonth(`${now.getFullYear()}-${pad(now.getMonth() + 1)}`); }} /></span>
      <span style={{ flex: 1 }} />
      {answer && <span className="fw-view-note">{answer.sourceTitle} {answer.items.length.toLocaleString('en-US')}건</span>}
    </header>
    {problem && <div role="alert">{problem}</div>}
    <div className="fw-calendar-grid" role="grid" aria-label={`${year}년 ${monthNumber}월`} style={{ gridTemplateRows: `auto repeat(${weeks}, minmax(0, 1fr))` }}>
      {['일', '월', '화', '수', '목', '금', '토'].map((name, index) => <div key={name} role="columnheader" className={`fw-calendar-week${index === 0 ? ' is-sun' : index === 6 ? ' is-sat' : ''}`}>{name}</div>)}
      {days.slice(0, weeks * 7).map(day => { const id = key(day), items = on(id);
        return <div key={id} role="gridcell" data-day={id} className={`fw-calendar-day${day.getMonth() !== monthNumber - 1 ? ' is-other' : ''}${id === today ? ' is-today' : ''}`}>
          <span className={`fw-calendar-date${day.getDay() === 0 ? ' is-sun' : day.getDay() === 6 ? ' is-sat' : ''}`}>{day.getDate()}</span>
          {items.slice(0, 4).map(item => <ContentButton key={item.id} className={`fw-calendar-item${status && item.status ? ` is-${statusTone(status, item.status)}` : ''}`} title={`${item.label}${item.statusLabel ? ` · ${item.statusLabel}` : ''}`}
            onClick={() => nav?.open(answer!.programCode, intentOf({ params: {}, note: '', select: String(item.id) }))}>{item.label || '(이름 없음)'}</ContentButton>)}
          {items.length > 4 && <span className="fw-calendar-more">외 {items.length - 4}건</span>}
        </div>; })}
    </div>
  </div>;
}
