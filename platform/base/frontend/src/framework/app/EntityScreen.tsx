import { useEffect, useMemo, useRef, useState } from 'react';
import { BusinessWorkspace } from '../BusinessWorkspace';
import { QueryPanel } from '../QueryPanel';
import { RecordGrid, type GridColumn } from '../RecordGrid';
import type { FieldDefinition, FieldValues } from '../fields';
import type { EditableRecord } from '../RecordEditor';
import { apiFetch } from '../auth/sessionClient';
import { exportRows } from '../gridExport';
import { alignOf, formatDateTime } from '../format';
import { Select } from '../ui';
import { pickOf, printOf, shownField, storedField, typedField, type DefinedField, type EntityDefinition } from './definitions';
import { printRecord } from './printRecord';
import { ImportDialog } from './ImportDialog';
import { usePagedList } from './pagedList';
import { openingQuery, periodFields, storedQuery } from './query';
import { HistoryDialog } from './HistoryDialog';
import { FilesDialog } from './FilesDialog';
import { LinkedNote, LinksDialog, useLinked } from './links';

type Row = Record<string, string> & { id: string };
type Names = Record<string, Record<string, string>>;  // field name -> stored value -> shown name

export const text = (value: unknown) => (value === null || value === undefined ? '' : String(value));

export async function failure(response: Response, fallback: string): Promise<Error> {
  const body = await response.json().catch(() => null) as { detail?: string; message?: string } | null;
  return new Error(body?.detail || body?.message || `${fallback} (${response.status})`);
}

export function toField(field: DefinedField, forQuery: boolean): FieldDefinition {
  const base: FieldDefinition = { name: field.name, label: field.label, required: !forQuery && field.required, group: field.required ? 'basic' : 'extra',
    ...(forQuery ? {} : { showWhen: field.showWhen, requiredWhen: field.requiredWhen, lockWhen: field.lockWhen }) };
  if (field.type === 'number') return { ...base, type: 'decimal', min: field.min ?? undefined, max: field.max ?? undefined, decimals: field.decimals };
  if (field.type === 'time') return { ...base, type: 'time' };
  // Asked as a condition, a yes/no has three answers: all, yes, no.
  if (field.type === 'yesno') return forQuery ? { ...base, render: control => <Select label={field.label} value={control.value} onChange={control.onChange} options={[{ value: '', label: '전체' }, { value: 'true', label: '예' }, { value: 'false', label: '아니오' }]} /> }
    : { ...base, type: 'yesno' };
  if (field.type === 'memo') return forQuery ? base : { ...base, type: 'memo' };
  if (field.type === 'date') return { ...base, type: 'date' };
  if (field.type === 'code' && field.codeGroup) return { ...base, codeGroup: field.codeGroup, pick: forQuery ? 'dropdown' : pickOf(field).pick };
  if (field.type === 'ref' && field.ref?.line) return { ...base, lineLookup: { entity: field.ref.entity, label: field.ref.label, within: field.ref.within, withinTarget: field.ref.withinTarget } };
  if (field.type === 'ref' && field.ref) return { ...base, lookup: { api: `/api/lookup/${field.ref.entity}`, label: field.ref.label, ...pickOf(field) } };
  return base;
}

/**
 * The screen of a defined entity: query conditions, list, edit panel and the shared toolbar, drawn from the
 * definition. Adding or changing a field is a change of the definition; this component is never edited for it.
 */
export function EntityScreen({ entity }: { entity: EntityDefinition }) {
  const { key, title, fields } = entity.definition;
  const api = `/api/data/${key}`;
  const queryForm = `entity-${key}-query`, editorForm = `entity-${key}-editor`;
  const [selected, setSelected] = useState<EditableRecord | null>(null);
  const [resetKey, setResetKey] = useState(0);
  const [names, setNames] = useState<Names>({});
  const [importing, setImporting] = useState(false);
  const [history, setHistory] = useState(false);
  const [filing, setFiling] = useState(false);
  const [linking, setLinking] = useState(false);
  const sent = useLinked(entity.programCode);
  const typed = useRef<FieldValues>({});
  const [fileCount, setFileCount] = useState(0);
  // How many files the chosen record holds (shown on the button).
  useEffect(() => { setFileCount(0); if (!selected) return; let alive = true;
    void apiFetch(`${api}/${selected.id}`).then(async response => { if (alive && response.ok) setFileCount(Number((await response.json() as { _files?: number })._files ?? 0)); }).catch(() => {});
    return () => { alive = false; }; }, [selected?.id]);   // eslint-disable-line react-hooks/exhaustive-deps

  // Names for codes and for records of other entities, so the list shows words instead of stored values.
  const signature = fields.map(field => `${field.name}:${field.codeGroup ?? ''}:${field.ref?.entity ?? ''}:${field.ref?.label ?? ''}`).join('|');
  useEffect(() => {
    let alive = true;
    void (async () => {
      const next: Names = {};
      const groups = [...new Set(fields.filter(field => field.type === 'code' && field.codeGroup).map(field => field.codeGroup as string))];
      if (groups.length) {
        const response = await apiFetch(`/api/auth/codes?groups=${encodeURIComponent(groups.join(','))}`);
        const codes = response.ok ? await response.json() as Record<string, { code: string; name: string }[]> : {};
        for (const field of fields) if (field.type === 'code' && field.codeGroup)
          next[field.name] = Object.fromEntries((codes[field.codeGroup] ?? []).map(item => [item.code, item.name]));
      }
      if (alive) setNames(next);
    })().catch(() => {});
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [signature]);

  const editFields = useMemo(() => fields.map(field => toField(field, false)), [signature]);  // eslint-disable-line react-hooks/exhaustive-deps
  const queryFields = useMemo(() => {
    const marked = fields.filter(field => field.search);
    return (marked.length ? marked : fields.filter(field => field.type === 'text').slice(0, 2)).flatMap(field => (field.type === 'date' ? periodFields(toField(field, true)) : [toField(field, true)]));
  }, [signature]);  // eslint-disable-line react-hooks/exhaustive-deps
  const columns: GridColumn<Row>[] = [
    ...fields.map(field => ({ key: field.name, label: field.label, width: field.type === 'text' || field.type === 'memo' ? undefined : field.type === 'yesno' || field.type === 'time' ? 90 : 120, align: alignOf(field.type),
      render: field.type === 'ref' ? (row: Row) => row[`${field.name}__name`] ?? row[field.name] : field.type === 'code' ? (row: Row) => names[field.name]?.[row[field.name]] ?? row[field.name] : field.type === 'text' || field.type === 'serial' ? undefined : (row: Row) => shownField(field, row[field.name]) })),
    { key: 'updatedBy', label: '수정자', width: 100 }, { key: 'updatedAt', label: '수정일시', width: 160, align: 'center' as const },
  ];

  const toRow = (data: Record<string, unknown>): Row => ({ ...Object.fromEntries(fields.map(field => [field.name, typedField(field, data[field.name])])),
    // How the fields that point at other screens' records read, as the server named them for this row.
    ...Object.fromEntries(Object.entries((data._names ?? {}) as Record<string, string>).map(([name, shown]) => [`${name}__name`, shown])),
    id: text(data.id), updatedBy: text(data.updatedBy), updatedAt: formatDateTime(data.updatedAt), seenAt: text(data.updatedAt) });     // seenAt: as the server gave it (sent back as X-Seen)
  const list = usePagedList<Row>(api, toRow, response => failure(response, `${title} 자료를 조회하지 못했습니다.`));
  const rows = list.rows;

  // What is typed in the conditions, in stored form; what another screen sent comes on top of it.
  const stored = (values: FieldValues) => storedQuery(fields, values);
  const opening = useMemo(() => openingQuery(entity.definition, fields.filter(field => field.search && field.type === 'date').map(field => field.name)), [signature]);  // eslint-disable-line react-hooks/exhaustive-deps
  async function handleQuery(values: FieldValues) {
    typed.current = values;
    await list.query({ ...stored(values), ...(sent.linked?.params ?? {}) });
  }
  // Another screen sent conditions or a record to show: list by them (and open that record) as soon as they arrive.
  useEffect(() => {
    if (!sent.linked) return;
    const { params, select } = sent.linked;
    void (async () => {
      const rows = await list.query({ ...params }).catch(() => [] as Row[]);       // what was sent decides the list, whatever was typed before
      if (!select) return;
      const found = rows.find(row => row.id === select);
      if (found) { setSelected({ id: found.id, values: found }); return; }
      const response = await apiFetch(`${api}/${select}`);      // not in the first part of the list: fetched by itself
      if (response.ok) { const row = toRow(await response.json()); setSelected({ id: row.id, values: row }); }
    })();
  }, [sent.at]);   // eslint-disable-line react-hooks/exhaustive-deps
  const releaseLinked = () => { sent.release(); void list.query(stored(typed.current)).catch(() => {}); };
  async function handleSave(values: FieldValues, id: string | number | null) {
    const payload = Object.fromEntries(fields.map(field => [field.name, storedField(field, values[field.name] ?? '')]));
    const seen = id !== null && selected && String(selected.id) === String(id) ? String(selected.values.seenAt ?? '') : '';   // when it was last changed as shown
    const response = await apiFetch(id === null ? api : `${api}/${id}`, { method: id === null ? 'POST' : 'PUT',
      headers: { 'Content-Type': 'application/json', ...(seen ? { 'X-Seen': seen } : {}) }, body: JSON.stringify(payload) });
    if (!response.ok) throw await failure(response, `${title} 자료를 저장하지 못했습니다.`);
    const saved = toRow(await response.json());
    const shownNow = await list.refresh();
    const again = shownNow.find(row => row.id === saved.id) ?? saved;      // the listed row carries the names of what it points at
    setSelected({ id: again.id, values: again });
  }
  function handleNew() { setSelected(null); setCopied(undefined); setResetKey(value => value + 1); }
  // A new record that starts as a copy of the chosen one: what must differ per record (auto numbers, values that may not repeat) is left empty.
  const [copied, setCopied] = useState<FieldValues | undefined>(undefined);
  function handleCopy() {
    if (!selected) return;
    setCopied(Object.fromEntries(fields.filter(field => field.type !== 'serial' && !field.unique).map(field => [field.name, selected.values[field.name] ?? ''])));
    setSelected(null); setResetKey(value => value + 1);
  }
  async function handleDelete() {
    if (!selected) return;
    const response = await apiFetch(`${api}/${selected.id}`, { method: 'DELETE', headers: { 'X-Seen': String(selected.values.seenAt ?? '') } });
    if (!response.ok) throw await failure(response, `${title} 자료를 삭제하지 못했습니다.`);
    handleNew();
    await list.refresh();
  }
  const shown = (row: Row) => Object.fromEntries(columns.map(column => [column.key, column.render ? text(column.render(row)) : row[column.key]]));

  return <>
  <BusinessWorkspace title={title}
    actions={{ query: { form: queryForm }, create: { onClick: handleNew }, copy: { onClick: handleCopy, disabled: !selected }, save: { form: editorForm },
      remove: { onClick: handleDelete, disabled: !selected, confirm: `선택한 ${title} 자료를 삭제할까요?` },
      import: { onClick: () => setImporting(true) }, links: { onClick: () => setLinking(true), disabled: !selected }, files: { onClick: () => setFiling(true), disabled: !selected, label: fileCount ? `첨부 ${fileCount}` : undefined }, history: { onClick: () => setHistory(true), disabled: !selected },
      export: { onClick: async () => exportRows(title, columns, (await list.all()).map(shown)), disabled: !rows.length },
      print: { onClick: () => { if (selected) printRecord({ ...printOf(entity.definition), foot: title, totals: [],
        pairs: fields.map(field => ({ label: field.label, value: field.type === 'ref' ? selected.values[`${field.name}__name`] ?? selected.values[field.name] ?? '' : field.type === 'code' ? names[field.name]?.[selected.values[field.name]] ?? selected.values[field.name] ?? '' : shownField(field, selected.values[field.name] ?? '') })) }); }, disabled: !selected } }}
    query={<QueryPanel formId={queryForm} fields={queryFields} onQuery={handleQuery} initialValues={opening} />}
    results={<><LinkedNote linked={sent.linked} onRelease={releaseLinked} /><RecordGrid label={title} rows={rows} columns={columns} keyField="id" onSelect={row => setSelected({ id: row.id, values: row })}
      total={list.total} onMore={list.more} onSort={sort => { void list.sortBy(sort).catch(() => {}); }} /></>}
    editor={{ fields: editFields, record: selected, defaults: copied, onSave: handleSave, onNew: handleNew, resetKey, formId: editorForm }} />
    <LinksDialog api={api} id={selected ? String(selected.id) : null} title={title} isOpen={linking} onClose={() => setLinking(false)}
      name={selected ? `${title.replace(/\s*(등록|관리|입력)$/, '')} ${[selected.values[fields[0]?.name ?? ''], selected.values[fields[1]?.name ?? '']].filter(Boolean).slice(0, 2).join(' ')}` : ''} />
    <FilesDialog api={api} id={selected ? String(selected.id) : null} title={title} isOpen={filing} onClose={() => setFiling(false)} onCount={setFileCount} />
    <HistoryDialog api={api} id={selected ? String(selected.id) : null} title={title} isOpen={history} onClose={() => setHistory(false)} />
    <ImportDialog title={title} api={api} labels={fields.filter(field => field.type !== 'serial' && !field.formula && !field.sum).map(field => field.label)} isOpen={importing}
      onClose={() => setImporting(false)} onDone={() => { void list.refresh(); }} />
  </>;
}
