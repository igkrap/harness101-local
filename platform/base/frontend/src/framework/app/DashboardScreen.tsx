import { useEffect, useState } from 'react';
import { apiFetch } from '../auth/sessionClient';
import { ScreenTitle } from '../ScreenTitle';
import { Button, DateRangeInput, StatTiles } from '../ui';
import { isDate, showDate, showTime, storeDate, today } from '../format';
import { useWorkspaceNav } from '../workspace/navContext';
import { entityOf, type EntityDefinition } from './definitions';
import { summaryView, type Result } from './summaryView';

/**
 * A dashboard, drawn from its definition: chart panels and nothing else. Each panel shows one summary screen's
 * chart (or its headline figures); the table behind a chart is one click away, on that summary's own screen.
 */
export function DashboardScreen({ entity }: { entity: EntityDefinition }) {
  const { title } = entity.definition;
  const panels = entity.definition.dashboard!.panels;
  const nav = useWorkspaceNav();
  const [results, setResults] = useState<Record<string, Result | 'failed'>>({});
  const [loadedAt, setLoadedAt] = useState('');
  // One period for the whole board: every panel is asked for the same dates (each by the date its own summary is conditioned on).
  const [period, setPeriod] = useState<{ from: string; to: string }>({ from: '', to: '' });
  const day = (date: Date) => today(date);
  // The two date boxes as typed; a period takes effect when a box is left (or Enter) holding a date or nothing.
  const [typed, setTyped] = useState<{ from: string; to: string }>({ from: '', to: '' });
  useEffect(() => { setTyped({ from: showDate(period.from), to: showDate(period.to) }); }, [period.from, period.to]);
  const settle = (side: 'from' | 'to', value: string) => { if (value === '' || isDate(value)) setPeriod(current => ({ ...current, [side]: value ? storeDate(value) : '' })); };
  const presets: { label: string; range: () => { from: string; to: string } }[] = [
    { label: '전체', range: () => ({ from: '', to: '' }) },
    { label: '이번 달', range: () => { const now = new Date(); return { from: day(new Date(now.getFullYear(), now.getMonth(), 1)), to: day(new Date(now.getFullYear(), now.getMonth() + 1, 0)) }; } },
    { label: '최근 3개월', range: () => { const now = new Date(); return { from: day(new Date(now.getFullYear(), now.getMonth() - 2, 1)), to: day(new Date(now.getFullYear(), now.getMonth() + 1, 0)) }; } },
    { label: '올해', range: () => { const now = new Date(); return { from: `${now.getFullYear()}-01-01`, to: `${now.getFullYear()}-12-31` }; } },
  ];
  const dateOf = (key: string) => { const summary = entityOf(key)?.definition.summary, source = summary ? entityOf(summary.entity)?.definition : undefined;
    return summary?.filters.find(name => source?.fields.find(field => field.name === name)?.type === 'date'); };
  const keys = [...new Set(panels.map(panel => panel.summary))].join(',');
  async function load() {
    const next: Record<string, Result | 'failed'> = {};
    await Promise.all(keys.split(',').filter(Boolean).map(async key => {
      const date = dateOf(key), parameters = new URLSearchParams();
      if (date && period.from) parameters.set(`${date}_from`, period.from);
      if (date && period.to) parameters.set(`${date}_to`, period.to);
      const response = await apiFetch(`/api/summary/${key}?${parameters}`).catch(() => null);
      next[key] = response?.ok ? await response.json() as Result : 'failed';
    }));
    setResults(next);
    setLoadedAt(showTime(new Date()));
  }
  useEffect(() => { void load(); }, [keys, entity.revision, period.from, period.to]);  // eslint-disable-line react-hooks/exhaustive-deps

  return <div data-ui="dashboard" className="fw-dashboard">
    <header className="fw-dashboard-head">
      <ScreenTitle>{title}</ScreenTitle>
      <span className="fw-dashboard-period" role="group" aria-label="기간" data-ui="dashboard-period">
        {presets.map(preset => { const range = preset.range(); return <Button key={preset.label} label={preset.label} outlined isActive={range.from === period.from && range.to === period.to} onClick={() => setPeriod(range)} />; })}
        <DateRangeInput label="기간" hideLabel from={typed.from} to={typed.to} onChange={(from, to) => { setTyped({ from, to }); settle('from', from); settle('to', to); }} />
      </span>
      <span style={{ flex: 1 }} />
      {loadedAt && <span className="fw-dashboard-time">{loadedAt} 기준</span>}
      <Button label="새로 고침" icon="refresh" outlined onClick={() => void load()} />
    </header>
    <div className="fw-dashboard-grid">
      {panels.map((panel, index) => {
        const source = entityOf(panel.summary), result = results[panel.summary];
        const summary = source?.definition.summary;
        const view = summary && result && result !== 'failed' ? summaryView(summary, result, panel.value, panel.chart === 'figures' ? 'bar' : panel.chart, 240) : null;
        return <section key={index} data-ui="dashboard-panel" data-kind={panel.chart} className="fw-chart-panel" style={{ gridColumn: `span ${panel.width}` }} aria-label={panel.title}>
          <header className="fw-chart-panel-head">
            <strong>{panel.title}</strong>
            {panel.chart !== 'figures' && view?.chartColumn && <span className="fw-dashboard-of">{view.chartColumn.label}</span>}
            <span style={{ flex: 1 }} />
            {source && nav && <Button label="자세히" variant="ghost" icon="arrow-top-right" onClick={() => nav.open(source.programCode)} />}
          </header>
          <div className="fw-chart-panel-body">
            {result === 'failed' || !summary ? <div className="fw-chart-empty">이 패널의 집계를 읽지 못했습니다.</div>
              : !view ? <div className="fw-chart-empty">불러오는 중…</div>
              : panel.chart === 'figures' ? <StatTiles items={view.tiles} /> : view.chart}
          </div>
        </section>;
      })}
    </div>
  </div>;
}
