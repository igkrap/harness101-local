import { useEffect, useMemo, useState } from 'react';
import { BusinessWorkspace } from '../BusinessWorkspace';
import { QueryPanel } from '../QueryPanel';
import { RecordGrid, type GridColumn } from '../RecordGrid';
import type { FieldDefinition, FieldValues } from '../fields';
import { apiFetch } from '../auth/sessionClient';
import { exportRows, printRows } from '../gridExport';
import { alignOf, showDate, storeDate, type Align } from '../format';
import { Button, Select, StatTiles, type ChartKind } from '../ui';
import { cell, summaryView, type Result, type Row } from './summaryView';
import { definitionOf, entityOf, type EntityDefinition } from './definitions';
import { intentOf } from './links';
import { useWorkspaceNav } from '../workspace/navContext';
import { failure, toField } from './EntityScreen';

/**
 * A summary screen, drawn from its definition: conditions, a table of groups and computed values with a total line,
 * and (when the definition has one) a chart. It stores nothing; the numbers come from the entity it gathers.
 */
export function SummaryScreen({ entity }: { entity: EntityDefinition }) {
  const { key, title } = entity.definition;
  const summary = entity.definition.summary!;
  const source = definitionOf(summary.entity);
  const queryForm = `summary-${key}-query`;
  const [result, setResult] = useState<Result | null>(null);
  const nav = useWorkspaceNav();
  const [asked, setAsked] = useState<Record<string, string>>({});       // the conditions of the answer on screen, in stored form
  const [picked, setPicked] = useState<string | null>(null);

  // Conditions come from the gathered entity's own fields: a date is asked as a period, the rest as on its own screen.
  const queryFields = useMemo<FieldDefinition[]>(() => summary.filters.flatMap((name): FieldDefinition[] => {
    if (name === 'status') return source?.status ? [{ name: 'status', label: '상태', render: control =>
      <Select label="상태" value={control.value} onChange={control.onChange} options={[{ value: '', label: '전체' }, ...source.status!.values.map(value => ({ value: value.code, label: value.label }))]} /> }] : [];
    const field = source?.fields.find(item => item.name === name);
    if (!field) return [];
    if (field.type === 'date') return [{ ...toField(field, true), name: `${name}_from`, label: `${field.label} 부터` }, { ...toField(field, true), name: `${name}_to`, label: `${field.label} 까지` }];
    return [toField({ ...field, type: field.type === 'serial' ? 'text' : field.type }, true)];
  }), [entity.revision, source]);  // eslint-disable-line react-hooks/exhaustive-deps

  async function handleQuery(values: FieldValues) {
    const parameters = new URLSearchParams();
    for (const [name, value] of Object.entries(values)) if (value?.trim()) parameters.set(name, /_(from|to)$/.test(name) ? storeDate(value) : value.trim());
    const response = await apiFetch(`/api/summary/${key}?${parameters}`);
    if (!response.ok) throw await failure(response, `${title}을(를) 조회하지 못했습니다.`);
    setResult(await response.json() as Result);
    setAsked(Object.fromEntries(parameters)); setPicked(null);
  }
  useEffect(() => { void handleQuery({}).catch(() => {}); }, [key, entity.revision]);  // eslint-disable-line react-hooks/exhaustive-deps

  // What is grouped by sits as that kind of value does: a date or a month, a common code and a status in the centre; names on the left.
  const groupAligns: Align[] = summary.groupBy.map(group => {
    if (group.by) return 'center';
    if (group.field === 'status') return 'center';
    const field = source?.fields.find(item => item.name === group.field) ?? source?.lines?.fields.find(item => item.name === group.field);
    return alignOf(field?.type);
  });
  const groupAlign = (key: string) => groupAligns[(result?.columns ?? []).filter(column => column.kind === 'group').findIndex(column => column.key === key)];
  const columns: GridColumn<Row>[] = (result?.columns ?? []).map(column => ({ key: column.key, label: column.label, align: column.kind === 'group' ? groupAlign(column.key) : 'right' as const, width: column.kind === 'group' ? undefined : column.kind === 'value' || column.role === 'base' ? 130 : 110 }));
  const rows: Row[] = useMemo(() => {
    if (!result) return [];
    const shown = (row: Record<string, unknown>) => Object.fromEntries(result.columns.map(column => [column.key, cell(column, row[column.key])]));
    const list = result.rows.map((row, index) => ({ ...shown(row), id: String(index) }) as Row);
    // The total line: every computed column over all the rows asked for.
    if (result.rows.length) list.push({ ...Object.fromEntries(result.columns.map((column, index) => [column.key, column.kind === 'group' ? (index === 0 ? '합계' : '') : cell(column, result.totals[column.key])])), id: 'total' } as Row);
    return list;
  }, [result]);

  // The chart: which figure it draws and how can be switched on the spot; the definition says where it starts.
  const [measure, setMeasure] = useState(summary.chart?.value ?? '');
  const [kind, setKind] = useState<ChartKind>(summary.chart?.type ?? 'bar');
  const { values, chartColumn, tiles, chart } = summaryView(summary, result, measure, kind);
  const kinds: { id: ChartKind; label: string }[] = [{ id: 'bar', label: '막대' }, { id: 'line', label: '선' }, { id: 'pie', label: '원' }];
  // Three separate things above the table: the headline figures, then a panel that holds the chart and nothing else
  // (what it draws and in which form are chosen in the panel's own heading).
  const panel = <>
    {tiles.length > 0 && <StatTiles items={tiles} />}
    {chartColumn && <section data-ui="summary-chart" className="fw-chart-panel" aria-label="차트">
      <header className="fw-chart-panel-head">
        <strong>{chartColumn.label}</strong>
        <span style={{ flex: 1 }} />
        {values.length > 1 && <span className="fw-seg" role="group" aria-label="차트로 볼 값">{values.map(column =>
          <Button key={column.key} label={column.label} isActive={column.key === chartColumn.key} outlined onClick={() => setMeasure(column.label)} />)}</span>}
        <span className="fw-seg" role="group" aria-label="차트 모양">{kinds.map(item => <Button key={item.id} label={item.label} isActive={kind === item.id} outlined onClick={() => setKind(item.id)} />)}</span>
      </header>
      <div className="fw-chart-panel-body">
        {chart}
      </div>
    </section>}
  </>;

  // Two groupings can also be read as a cross table: the first down the side, the second across the top, one figure in each cell.
  const groupColumns = (result?.columns ?? []).filter(column => column.kind === 'group');
  const [cross, setCross] = useState(false);
  const crossed = useMemo(() => {
    if (!result || groupColumns.length !== 2 || !chartColumn) return null;
    const [down, across] = groupColumns, number = (value: unknown) => (typeof value === 'number' ? value : 0);
    const tops = [...new Set(result.rows.map(row => String(row[across.key] ?? '')))];
    const sides = [...new Set(result.rows.map(row => String(row[down.key] ?? '')))];
    const adds = chartColumn.op === 'sum' || chartColumn.op === 'count';        // only these may be added up along a row or column
    const at = (side: string, top: string) => result.rows.find(row => String(row[down.key] ?? '') === side && String(row[across.key] ?? '') === top);
    const list: Row[] = sides.map((side, index) => ({ id: String(index), side: showDate(side), ...Object.fromEntries(tops.map((top, column) => [`t${column}`, cell(chartColumn, at(side, top)?.[chartColumn.key])])),
      total: adds ? cell(chartColumn, tops.reduce((sum, top) => sum + number(at(side, top)?.[chartColumn.key]), 0)) : '' }) as Row);
    if (adds && sides.length) list.push({ id: 'total', side: '합계', ...Object.fromEntries(tops.map((top, column) => [`t${column}`, cell(chartColumn, sides.reduce((sum, side) => sum + number(at(side, top)?.[chartColumn.key]), 0))])),
      total: cell(chartColumn, result.totals[chartColumn.key]) } as Row);
    const heads: GridColumn<Row>[] = [{ key: 'side', label: `${down.label} \\ ${across.label}`, width: 200, align: groupAlign(down.key) }, ...tops.map((top, column) => ({ key: `t${column}`, label: showDate(top) || '(없음)', width: 120, align: 'right' as const })),
      ...(adds ? [{ key: 'total', label: '합계', width: 120, align: 'right' as const }] : [])];
    return { rows: list, columns: heads };
  }, [result, chartColumn?.key, groupColumns.length]);  // eslint-disable-line react-hooks/exhaustive-deps
  // From one line of the summary to the records behind it: the source screen, listed by this line's groups and the summary's own conditions.
  const sourceScreen = entityOf(summary.entity);
  function openDetail() {
    const row = result && picked !== null && picked !== 'total' ? result.rows[Number(picked)] : undefined;
    if (!row || !sourceScreen || !nav) return;
    const params: Record<string, string> = { ...asked }, words: string[] = [];
    let select: string | undefined;
    summary.groupBy.forEach((group, index) => {
      const raw = row[`g${index}Key`], shown = cell(result!.columns.filter(column => column.kind === 'group')[index], row[`g${index}`]);
      if (raw === null || raw === undefined || raw === '') return;
      const value = String(raw);
      words.push(`${group.label} ${shown}`);
      if (group.field === 'status') params.status = value;
      else if (group.field === 'id') select = value;
      else if (group.by === 'month') { const [year, month] = value.split('-').map(Number); params[`${group.field}_from`] = `${value}-01`; params[`${group.field}_to`] = `${value}-${String(new Date(year, month, 0).getDate()).padStart(2, '0')}`; }
      else if (group.by === 'year') { params[`${group.field}_from`] = `${value}-01-01`; params[`${group.field}_to`] = `${value}-12-31`; }
      else if (source?.fields.find(field => field.name === group.field)?.type === 'date') { params[`${group.field}_from`] = value; params[`${group.field}_to`] = value; }
      else if (summary.lines && source?.lines?.fields.some(field => field.name === group.field) && !source.fields.some(field => field.name === group.field)) params[`lines.${group.field}`] = value;
      else params[group.field] = value;
    });
    nav.open(sourceScreen.programCode, intentOf({ params, note: `${title}: ${words.join(', ')}`, select }));
  }
  const shownRows = cross && crossed ? crossed.rows : rows, shownColumns = cross && crossed ? crossed.columns : columns;
  const switcher = crossed && <div className="fw-table-switch" data-ui="summary-table-switch">
    <span className="fw-seg" role="group" aria-label="표 모양"><Button label="목록" isActive={!cross} outlined onClick={() => setCross(false)} /><Button label="교차표" isActive={cross} outlined onClick={() => setCross(true)} /></span>
    {cross && chartColumn && <span className="fw-table-switch-note">{chartColumn.label}</span>}
  </div>;

  return <BusinessWorkspace title={title}
    actions={{ query: { form: queryForm }, detail: { onClick: openDetail, disabled: cross || picked === null || picked === 'total' || !sourceScreen },
      export: { onClick: () => exportRows(title, shownColumns, shownRows), disabled: !shownRows.length }, print: { onClick: () => printRows(title, shownColumns, shownRows), disabled: !shownRows.length } }}
    query={<div style={{ display: queryFields.length ? undefined : 'none' }}><QueryPanel formId={queryForm} fields={queryFields} onQuery={handleQuery} /></div>}
    results={<div data-ui="summary" style={{ display: 'contents' }}>{panel}{switcher}<RecordGrid label={title} rows={shownRows} columns={shownColumns} keyField="id" onSelect={row => setPicked(cross ? null : row.id)} /></div>} />;
}
