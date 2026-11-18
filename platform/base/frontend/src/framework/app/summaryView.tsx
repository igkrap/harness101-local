import type { ReactNode } from 'react';
import { Chart, type ChartKind } from '../ui';
import { showAmount, showDate, showPercent } from '../format';
import type { EntityDefinition } from './definitions';

export type Column = { key: string; label: string; kind: 'group' | 'value' | 'compare' | 'share' | 'running'; op?: string; role?: 'base' | 'difference' | 'balance' | 'rate'; of?: string; type?: 'plan' | 'previous' | 'minus' };
export type Result = { columns: Column[]; rows: Record<string, unknown>[]; totals: Record<string, number | null> };
export type Row = Record<string, string> & { id: string };
/** A cell as it reads: amounts with separators, a difference with its direction, rates and shares as percentages. */
export function cell(column: Column, value: unknown): string {
  if (column.kind === 'group') return showDate(value);        // a date or a month reads 2026/11/14, 2026/11; anything else as it is
  if (typeof value !== 'number') return '';
  if (column.kind === 'share' || column.role === 'rate') return showPercent(value);
  if (column.role === 'difference') return value === 0 ? '0' : `${value > 0 ? '▲' : '▼'} ${amount(Math.abs(value))}`;
  return amount(value);
}
export const amount = (value: unknown) => (typeof value === 'number' ? showAmount(value) : '');

type SummaryPart = NonNullable<EntityDefinition['definition']['summary']>;
export type Tile = { label: string; value: number | null; note?: string; text?: string; tone?: 'up' | 'down' };

/**
 * What a summary's answer shows besides its table: the headline figures and the chart of one of its values.
 * Shared by the summary screen and by dashboard panels, so both draw the same figures the same way.
 */
export function summaryView(summary: SummaryPart, result: Result | null, measure: string, kind: ChartKind, height?: number): { values: Column[]; chartColumn: Column | undefined; tiles: Tile[]; chart: ReactNode } {
  const values = (result?.columns ?? []).filter(column => column.kind === 'value');
  const groupKeys = (result?.columns ?? []).filter(column => column.kind === 'group').map(column => column.key);
  const chartColumn = values.find(column => column.label === measure) ?? values[0];
  const drawn = (() => {
    if (!result || !chartColumn) return { categories: [] as string[], series: [] as { name: string; values: (number | null)[] }[] };
    const number = (row: Record<string, unknown>) => (typeof row[chartColumn.key] === 'number' ? row[chartColumn.key] as number : null);
    const categories = [...new Set(result.rows.map(row => showDate(row[groupKeys[0]])))];
    if (groupKeys.length < 2) return { categories, series: [{ name: chartColumn.label, values: result.rows.map(number) }] };
    // Two groupings: the first runs along the axis, the second becomes the series (each with its own colour and a legend).
    const names = [...new Set(result.rows.map(row => String(row[groupKeys[1]] ?? '')))];
    return { categories, series: names.map(name => ({ name, values: categories.map(category => {
      const row = result.rows.find(item => showDate(item[groupKeys[0]]) === category && String(item[groupKeys[1]] ?? '') === name);
      return row ? number(row) : null; }) })) };
  })();
  // Set against a plan or an earlier period: the same figure twice, and how far apart.
  const base = result?.columns.find(column => column.role === 'base');
  const compared = Boolean(base && chartColumn && base.of === chartColumn.key && groupKeys.length === 1);
  const baseAt = (category: string) => { const row = result?.rows.find(item => showDate(item[groupKeys[0]]) === category); return row && typeof row.c0 === 'number' ? row.c0 as number : null; };
  // Against a plan the whole period is weighed; against an earlier period only the latest one says something.
  const latest = base?.type === 'previous' ? [...(result?.rows ?? [])].reverse().find(row => typeof row.c0 === 'number') : undefined;
  const figures = latest ?? result?.totals ?? {};
  const rate = typeof figures.c2 === 'number' ? figures.c2 as number : null, gap = typeof figures.c1 === 'number' ? figures.c1 as number : null;
  const tiles = [...(result ? values.map(column => ({ label: column.label, value: result.totals[column.key] ?? null,
    note: (word => (word && !column.label.includes(word) ? word : undefined))({ sum: '합계', count: '건수', avg: '평균', min: '최소', max: '최대' }[column.op ?? '']) })) : []),
    ...(result && base ? [{ label: latest ? `${showDate(latest[groupKeys[0]])} ${chartColumn?.label ?? ''}` : base.label, value: latest ? (typeof latest[base.of ?? ''] === 'number' ? latest[base.of ?? ''] as number : null) : result.totals.c0 ?? null, note: latest ? `${base.label} ${amount(latest.c0)}` : undefined },
      base.type === 'minus' ? { label: result.columns.find(column => column.role === 'balance')?.label ?? '잔량', value: gap, note: rate === null ? undefined : `진행률 ${showPercent(rate)}` }
      : base.type === 'plan' ? { label: '달성률', value: rate, text: rate === null ? '-' : showPercent(rate), note: gap === null ? undefined : `계획 대비 ${gap >= 0 ? '+' : '−'}${amount(Math.abs(gap))}` }
        : { label: `${base.label} 대비`, value: rate, text: rate === null ? '-' : showPercent(Math.abs(rate)), tone: rate === null || rate === 0 ? undefined : rate > 0 ? 'up' as const : 'down' as const,
            note: gap === null ? undefined : `${gap >= 0 ? '+' : '−'}${amount(Math.abs(gap))}` }] : [])];
  const chart = !chartColumn ? null : compared && base?.type === 'previous'
        ? <Chart height={height} kind={kind === 'pie' ? 'bar' : kind} name={chartColumn.label} categories={drawn.categories} muted={0}
            series={[{ name: base.label, values: drawn.categories.map(baseAt) }, ...drawn.series]} />
        : <Chart height={height} kind={kind} name={chartColumn.label} categories={drawn.categories} series={drawn.series}
            targets={compared && kind === 'bar' ? drawn.categories.map(baseAt) : undefined} targetName={base?.label} markIsPart={base?.type === 'minus'}
            ranked={!summary.groupBy[0]?.by} stacked={chartColumn.op === 'sum' || chartColumn.op === 'count'} />;
  return { values, chartColumn, tiles, chart };
}
