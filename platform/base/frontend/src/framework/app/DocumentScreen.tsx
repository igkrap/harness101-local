import { useEffect, useMemo, useRef, useState } from 'react';
import { BusinessWorkspace } from '../BusinessWorkspace';
import { QueryPanel } from '../QueryPanel';
import { RecordGrid, type GridColumn } from '../RecordGrid';
import { CodeField, Fields, LineField, LookupField, holds, type FieldDefinition, type FieldValues } from '../fields';
import { AsyncFeedback } from '../AsyncFeedback';
import { apiFetch } from '../auth/sessionClient';
import { alignOf, formatDateTime, readNumber, showAmount, showNumber } from '../format';
import { Button, DateInput, NumberInput, Picker, Select, TextInput, TimeInput, YesNoInput } from '../ui';
import { definitionOf, pickOf, printOf, refText, shownField, statusTone, storedField, takingScreens, typedField, type DefinedField, type EntityDefinition } from './definitions';
import { currentBranding } from '../system/branding';
import { printRecord } from './printRecord';
import { ImportDialog } from './ImportDialog';
import { usePagedList } from './pagedList';
import { openingQuery, periodFields, storedQuery } from './query';
import { HistoryDialog } from './HistoryDialog';
import { FilesDialog } from './FilesDialog';
import { LinkedNote, LinksDialog, useLinked } from './links';
import { LotDialog } from './LotDialog';
import { fetchLookup, mergeRows } from '../lookup';
import { failure, text, toField } from './EntityScreen';
import { evaluate } from './formula';
import './document.css';

type Row = Record<string, string> & { id: string };
type Source = Record<string, unknown>[];   // rows of a referenced entity

const numberOf = (value: string) => (readNumber(value) === '' || Number.isNaN(Number(readNumber(value))) ? null : Number(readNumber(value)));
// What the screen works out itself (a formula, a total of the lines) reads with the field's decimal places, or at most two.
const shownNumber = (value: number | null, field?: DefinedField) => (field && field.decimals !== null && field.decimals !== undefined ? showNumber(value, field.decimals, true) : showAmount(value));

/**
 * The screen of an entity that has more than plain fields - a number given on save, a status with actions, a table of
 * lines (e.g. an order) - drawn from its definition. Each of those parts is there only if the definition has it. The server computes and
 * checks everything again on save; what is shown while typing uses the same formulas.
 */
export type WorkScreen = { key: string; title: string; statuses: string[]; actions: string[]; edit: boolean; create?: boolean;
  /** Fields an action is taken with, row by row (a reason to reject): action name -> field names. */ ask?: Record<string, string[]> };
/** over: the same records under a work screen (approve, hand over, look up, or only register - create) - its own API path, only its statuses and actions, nothing deleted. */
export function DocumentScreen({ entity, over }: { entity: EntityDefinition; over?: WorkScreen }) {
  const { key, fields, lines, status } = entity.definition;
  const title = over?.title ?? entity.definition.title;
  const lineFields = lines?.fields ?? [];
  const api = over ? `/api/over/${over.key}` : `/api/data/${key}`;
  const queryForm = `document-${over?.key ?? key}-query`;
  // Choosing a lot for a line of a screen that takes quantities out: which line the lot window is open for.
  const ledger = entity.definition.ledger;
  const [lotFor, setLotFor] = useState<number | null>(null);
  const [selected, setSelected] = useState<{ id: string; status: string; seen: string } | null>(null);   // seen: when it was last changed as shown
  const [header, setHeader] = useState<FieldValues>({});
  const blank = (): FieldValues[] => (lines && lines.min > 0 ? [{}] : []);
  const [items, setItems] = useState<FieldValues[]>(blank);
  // Every table of lines: the first ("lines", held in items) and any further ones (held by name).
  type LineSet = { name: string; label: string; fields: DefinedField[]; min: number; max: number | null };
  const sets: LineSet[] = [...(lines ? [{ name: 'lines', ...lines }] : []), ...(entity.definition.moreLines ?? [])];
  const more = sets.slice(1);
  const blankMore = (): Record<string, FieldValues[]> => Object.fromEntries(more.map(set => [set.name, set.min > 0 ? [{}] : []]));
  const [extra, setExtra] = useState<Record<string, FieldValues[]>>(blankMore);
  const rowsOf = (name: string) => (name === 'lines' ? items : extra[name] ?? []);
  const changeRows = (name: string, change: (previous: FieldValues[]) => FieldValues[]) => (name === 'lines' ? setItems(change) : setExtra(previous => ({ ...previous, [name]: change(previous[name] ?? []) })));
  const allLineFields = sets.flatMap(set => set.fields);
  const [sources, setSources] = useState<Record<string, Source>>({});
  const [message, setMessage] = useState<{ text: string; bad?: boolean } | null>(null);
  const [importing, setImporting] = useState(false);
  const [history, setHistory] = useState(false);
  const [filing, setFiling] = useState(false);
  const [linking, setLinking] = useState(false);
  const [chosen, setChosen] = useState<Row[]>([]);
  const [bulk, setBulk] = useState<{ busy: boolean; note: string }>({ busy: false, note: '' });
  const sent = useLinked(over ? undefined : entity.programCode);
  const typed = useRef<FieldValues>({});
  const [fileCount, setFileCount] = useState(0);
  // Column names of a sheet to upload: the fields above, then the line fields (named with the table when a name is used twice).
  const sheetLabels = [...fields.filter(field => field.type !== 'serial' && !field.formula && !field.sum).map(field => field.label),
    ...lineFields.filter(field => !field.formula).map(field => (fields.some(head => head.label === field.label) ? `${lines?.label ?? ''} ${field.label}` : field.label))];

  // Rows of the entities the fields point to: choices for the pickers, names for print, values for "fill". An entity may hold
  // more records than one reading brings (partial): then typing searches on the server, and the records this one points at are fetched by id.
  const targets = [...new Set([...fields, ...allLineFields].filter(field => field.ref && !field.ref.line).map(field => field.ref!.entity))].join(',');
  const [partial, setPartial] = useState<Record<string, boolean>>({});
  const held = useRef<Record<string, Source>>({});
  const keep = (entity: string, found: Source) => { held.current = { ...held.current, [entity]: mergeRows(held.current[entity], found) }; setSources(held.current); };
  useEffect(() => {
    let alive = true;
    void (async () => {
      const more: Record<string, boolean> = {};
      for (const target of targets.split(',').filter(Boolean)) {
        const answer = await fetchLookup(`/api/lookup/${target}`);
        more[target] = answer.more;
        if (alive) keep(target, answer.rows);
      }
      if (alive) setPartial(more);
    })().catch(() => {});
    return () => { alive = false; };
  }, [targets]);   // eslint-disable-line react-hooks/exhaustive-deps
  /** The record of another screen with this id: from what is held, or fetched now. */
  async function rowOf(entity: string, id: string): Promise<Record<string, unknown> | undefined> {
    const known = held.current[entity]?.find(item => text(item.id) === id);
    if (known || !id) return known;
    const found = (await fetchLookup(`/api/lookup/${entity}`, { ids: [id] })).rows;
    keep(entity, found);
    return found[0];
  }
  /** Bring the records this one points at (above and in its lines) that are not held yet. */
  async function ensure(data: Record<string, unknown>) {
    const wanted: Record<string, Set<string>> = {};
    const note = (list: DefinedField[], unit: Record<string, unknown>) => { for (const field of list) if (field.ref && !field.ref.line && unit[field.name] != null && !held.current[field.ref.entity]?.some(item => text(item.id) === text(unit[field.name]))) (wanted[field.ref.entity] ??= new Set()).add(text(unit[field.name])); };
    note(fields, data);
    for (const set of sets) for (const line of Array.isArray(data[set.name]) ? data[set.name] as Record<string, unknown>[] : []) note(set.fields, line);
    for (const [entity, ids] of Object.entries(wanted)) keep(entity, (await fetchLookup(`/api/lookup/${entity}`, { ids: [...ids] })).rows);
  }
  const searchIn = (field: DefinedField) => (partial[field.ref!.entity] ? async (typed: string) => {
    const found = (await fetchLookup(`/api/lookup/${field.ref!.entity}`, { q: typed })).rows;
    keep(field.ref!.entity, found);
    return found.map(item => optionOf(field, item));
  } : undefined);
  const optionOf = (field: DefinedField, item: Record<string, unknown>) => ({ value: text(item.id), label: text(item[field.ref!.label]), code: pickOf(field).code ? text(item[pickOf(field).code!]) : undefined, row: item });

  // Names of the common codes the fields above use, so the list reads words instead of codes.
  const codeGroups = [...new Set(fields.filter(field => field.type === 'code' && field.codeGroup).map(field => field.codeGroup as string))].join(',');
  const [codeNames, setCodeNames] = useState<Record<string, Record<string, string>>>({});
  useEffect(() => {
    if (!codeGroups) return;
    let alive = true;
    void apiFetch(`/api/auth/codes?groups=${encodeURIComponent(codeGroups)}`).then(async response => {
      const codes = response.ok ? await response.json() as Record<string, { code: string; name: string }[]> : {};
      if (alive) setCodeNames(Object.fromEntries(Object.entries(codes).map(([group, list]) => [group, Object.fromEntries(list.map(item => [item.code, item.name]))])));
    }).catch(() => {});
    return () => { alive = false; };
  }, [codeGroups]);
  const nameOf = (field: DefinedField, value: string) => field.ref
    ? refText(field, sources[field.ref.entity]?.find(item => text(item.id) === value)) || value : value;

  const lineValue = (line: FieldValues, field: DefinedField, among: DefinedField[] = lineFields): number | null => field.formula
    ? evaluate(field.formula, Object.fromEntries(among.filter(other => other.type === 'number' && other !== field).map(other => [other.name, lineValue(line, other, among)])))
    : numberOf(line[field.name] ?? '');
  const headerValue = (field: DefinedField): string => {
    if (field.sum) {       // "amount" adds up the first table, "materials.amount" the table named materials
      const [table, name] = field.sum.includes('.') ? field.sum.split('.') : ['lines', field.sum];
      const set = sets.find(item => item.name === table), column = set?.fields.find(line => line.name === name);
      return set && column ? shownNumber(rowsOf(table).reduce((total, line) => total + (lineValue(line, column, set.fields) ?? 0), 0), field) : '';
    }
    if (field.formula) return shownNumber(evaluate(field.formula, Object.fromEntries(fields.filter(other => other.type === 'number' && other !== field).map(other => [other.name, numberOf(header[other.name] ?? '')]))), field);
    return header[field.name] ?? '';
  };

  // A work screen is a list of things to do: it is there when the screen opens.
  useEffect(() => { if (over) void handleQuery({}).catch(() => {}); }, [over?.key]);  // eslint-disable-line react-hooks/exhaustive-deps
  // A later stage (follows) registers nothing on its own screen; its 기타 screen (a work screen with create) registers ones without the stage before.
  const follows = entity.definition.follows ?? null;
  const ownOnly = Boolean(!over && follows), other = Boolean(over?.create && follows);
  const locked = Boolean(selected && status?.locked.includes(selected.status)) || Boolean(over && !over.edit && (selected || !over.create)) || Boolean(ownOnly && !selected);
  const headerFields: FieldDefinition[] = useMemo(() => fields.filter(field => !field.sum && !field.formula && field.type !== 'serial' && !(other && field.name === follows)).map(field => ({ ...toField(field, false), group: undefined,
    // the lot of a record that takes out or moves one thing: typed, or chosen from the lots held
    ...(ledger && ledger.direction !== 'in' && ledger.lot === field.name ? { render: (control: { value: string; onChange: (value: string) => void; disabled: boolean }) => <span className="doc-lot">
      <TextInput label={field.label} isDisabled={control.disabled} value={control.value} onChange={control.onChange} />
      <Button label="LOT 고르기" isIconOnly variant="ghost" icon="search" isDisabled={control.disabled} onClick={() => setLotFor(-1)} /></span> } : {}) })),
    [entity.revision]);  // eslint-disable-line react-hooks/exhaustive-deps
  const queryFields = useMemo(() => {
    const marked = fields.filter(field => field.search);
    const base = (marked.length ? marked : fields.filter(field => field.type === 'serial' || field.type === 'text').slice(0, 2)).flatMap(field => (field.type === 'date' ? periodFields(toField(field, true)) : [toField({ ...field, type: field.type === 'serial' ? 'text' : field.type }, true)]));
    return status ? [...base, { name: 'status', label: '상태', render: (control: { value: string; onChange: (value: string) => void }) =>
      <Select label="상태" value={control.value} onChange={control.onChange} options={[{ value: '', label: '전체' }, ...status.values.filter(value => !over?.statuses.length || over.statuses.includes(value.code)).map(value => ({ value: value.code, label: value.label }))]} /> } as FieldDefinition] : base;
  }, [entity.revision]);  // eslint-disable-line react-hooks/exhaustive-deps
  const columns: GridColumn<Row>[] = [
    ...fields.map(field => ({ key: field.name, label: field.label, width: field.type === 'text' || field.type === 'memo' ? undefined : field.type === 'yesno' || field.type === 'time' ? 90 : 130, align: alignOf(field.type),
      render: field.ref ? (row: Row) => row[`${field.name}__name`] ?? nameOf(field, row[field.name]) : field.type === 'code' ? (row: Row) => codeNames[field.codeGroup ?? '']?.[row[field.name]] ?? row[field.name] : field.type === 'text' || field.type === 'serial' ? undefined : (row: Row) => shownField(field, row[field.name]) })),
    ...(status ? [{ key: 'statusLabel', label: '상태', width: 90, align: 'center' as const, render: (row: Row) => <span className={`fw-status is-${statusTone(status, row.status)}`}>{row.statusLabel}</span> }] : []),
    { key: 'updatedBy', label: '수정자', width: 100 }, { key: 'updatedAt', label: '수정일시', width: 160, align: 'center' as const },
  ];
  const toRow = (data: Record<string, unknown>): Row => ({ ...Object.fromEntries(fields.map(field => [field.name, typedField(field, data[field.name])])),
    ...Object.fromEntries(Object.entries((data._names ?? {}) as Record<string, string>).map(([name, shown]) => [`${name}__name`, shown])),
    id: text(data.id), status: text(data.status), statusLabel: text(data.statusLabel), updatedBy: text(data.updatedBy), updatedAt: formatDateTime(data.updatedAt), seenAt: text(data.updatedAt) });
  // Newest first: on a screen of orders or requests the last ones entered are the ones looked for.
  const list = usePagedList<Row>(api, toRow, response => failure(response, `${title} 자료를 조회하지 못했습니다.`), { key: 'id', descending: true });
  const rows = list.rows;

  const stored = (values: FieldValues) => storedQuery(fields, values);
  // A work screen is a list of things waiting: it opens on all of them; the entity's own screen opens on its period.
  const opening = useMemo(() => (over ? {} : openingQuery(entity.definition, fields.filter(field => field.search && field.type === 'date').map(field => field.name))), [entity.revision]);  // eslint-disable-line react-hooks/exhaustive-deps
  async function handleQuery(values: FieldValues) {
    typed.current = values;
    await list.query({ ...stored(values), ...(sent.linked?.params ?? {}) });
  }
  // Another screen sent conditions or a record to show.
  useEffect(() => {
    if (!sent.linked) return;
    const { params, select } = sent.linked;
    void list.query({ ...params }).catch(() => {});       // what was sent decides the list, whatever was typed before
    if (select) void open(select);
  }, [sent.at]);   // eslint-disable-line react-hooks/exhaustive-deps
  const releaseLinked = () => { sent.release(); void list.query(stored(typed.current)).catch(() => {}); };
  function show(data: Record<string, unknown>) {
    void ensure(data).catch(() => {});
    setFileCount(Number(data._files ?? 0));
    setSelected({ id: text(data.id), status: text(data.status), seen: text(data.updatedAt) });
    setHeader(Object.fromEntries(fields.map(field => [field.name, typedField(field, data[field.name])])));
    const stored = Array.isArray(data.lines) ? data.lines as Record<string, unknown>[] : [];
    setItems(stored.length ? stored.map(line => ({ ...Object.fromEntries(lineFields.map(field => [field.name, typedField(field, line[field.name])])), ...(line._line != null ? { _line: String(line._line) } : {}) })) : blank());
    setExtra(Object.fromEntries(more.map(set => { const held = Array.isArray(data[set.name]) ? data[set.name] as Record<string, unknown>[] : [];
      return [set.name, held.length ? held.map(line => Object.fromEntries(set.fields.map(field => [field.name, typedField(field, line[field.name])]))) : set.min > 0 ? [{}] : []]; })));
  }
  async function open(id: string) {
    setMessage(null);
    const response = await apiFetch(`${api}/${id}`);
    if (response.ok) show(await response.json());
  }
  /** A new record that starts as a copy of the one on screen: its number, values that may not repeat and its status start afresh. */
  function handleCopy() {
    if (!selected) return;
    setHeader(previous => Object.fromEntries(Object.entries(previous).filter(([name]) => { const field = fields.find(item => item.name === name); return field && field.type !== 'serial' && !field.unique; })));
    setSelected(null); setFileCount(0); setMessage({ text: '복사했습니다. 고친 뒤 저장하면 새 건으로 등록됩니다.' });
  }
  function handleNew() { setFileCount(0); setSelected(null); setHeader({}); setItems(blank()); setExtra(blankMore()); setMessage(null); }
  async function handleSave() {
    const payloadOf = (list: DefinedField[], values: FieldValues) => Object.fromEntries(list.filter(field => !field.sum && !field.formula && field.type !== 'serial').map(field => [field.name, storedField(field, values[field.name] ?? '')]));
    const filled = items.filter(line => lineFields.some(field => (line[field.name] ?? '').trim() !== ''));
    const body = { ...payloadOf(fields, header), ...(lines ? { lines: filled.map(line => ({ ...payloadOf(lineFields, line), ...(line._line ? { _line: Number(line._line) } : {}) })) } : {}),
      ...Object.fromEntries(more.map(set => [set.name, rowsOf(set.name).filter(line => set.fields.some(field => (line[field.name] ?? '').trim() !== '')).map(line => payloadOf(set.fields, line))])) };
    const response = await apiFetch(selected ? `${api}/${selected.id}` : api, { method: selected ? 'PUT' : 'POST', headers: { 'Content-Type': 'application/json', ...(selected ? { 'X-Seen': selected.seen } : {}) }, body: JSON.stringify(body) });
    if (!response.ok) throw await failure(response, `${title} 자료를 저장하지 못했습니다.`);
    show(await response.json());
    setMessage({ text: '저장했습니다.' });
    await list.refresh();
  }
  async function handleDelete() {
    if (!selected) return;
    const response = await apiFetch(`${api}/${selected.id}`, { method: 'DELETE', headers: { 'X-Seen': selected.seen } });
    if (!response.ok) throw await failure(response, `${title} 자료를 삭제하지 못했습니다.`);
    handleNew();
    await list.refresh();
  }
  // An action of a work screen that asks fields (a reason to reject): the rows it is taken on get those fields in the list, then 확정.
  const askOf = (name: string) => (over?.ask?.[name] ?? []).map(asked => fields.find(field => field.name === asked)).filter((field): field is DefinedField => Boolean(field));
  const [asking, setAsking] = useState<{ name: string; label: string; rows: Row[]; typed: Record<string, Record<string, string>> } | null>(null);
  async function confirmAsked() {
    if (!asking) return;
    const asked = askOf(asking.name);
    const lacking = asking.rows.find(row => asked.some(field => field.type !== 'yesno' && !(asking.typed[row.id]?.[field.name] ?? '').trim()));
    if (lacking) { setBulk({ busy: false, note: `${asked.map(field => field.label).join(', ')}을(를) 줄마다 적어야 ${asking.label}할 수 있습니다.` }); return; }
    setBulk({ busy: true, note: '' });
    const failed: string[] = [];
    let done = 0;
    for (const row of asking.rows) {
      const values = Object.fromEntries(asked.map(field => [field.name, storedField(field, asking.typed[row.id]?.[field.name] ?? '')]));
      const response = await apiFetch(`${api}/${row.id}/actions/${asking.name}`, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Seen': text(row.seenAt) }, body: JSON.stringify({ values }) });
      if (response.ok) done++; else failed.push(`${row[fields[0]?.name ?? ''] || row.id}: ${(await failure(response, `${asking.label}하지 못했습니다.`)).message}`);
    }
    setBulk({ busy: false, note: `${done}건 ${asking.label}했습니다.` + (failed.length ? `\n${failed.length}건은 하지 못했습니다:\n` + failed.slice(0, 5).join('\n') : '') });
    setAsking(null); setChosen([]);
    if (selected) { setSelected(null); setHeader({}); setItems(blank()); setExtra(blankMore()); }
    await list.refresh();
  }
  async function act(name: string, label: string) {
    if (!selected) return;
    if (askOf(name).length) { const row = rows.find(one => one.id === selected.id); if (row) setAsking({ name, label, rows: [row], typed: {} }); return; }
    setMessage(null);
    const response = await apiFetch(`${api}/${selected.id}/actions/${name}`, { method: 'POST', headers: { 'X-Seen': selected.seen } });
    if (!response.ok) { setMessage({ text: (await failure(response, `${label}하지 못했습니다.`)).message, bad: true }); return; }
    const after = await response.json() as Record<string, unknown>;
    // On a work screen a record that has left its statuses is done with: it goes from the list, and the form is cleared for the next.
    if (over?.statuses.length && !over.statuses.includes(text(after.status))) { setSelected(null); setHeader({}); setItems(blank()); setExtra(blankMore()); } else show(after);
    setMessage({ text: `${label}했습니다.` });
    await list.refresh();
  }
  // "fill": choosing a record brings its values along (the item's price, the order's customer), still editable afterwards.
  // The chosen record is taken from what is held, or fetched when the screen holds only a part of that entity.
  // lookups: a value found in master data (this customer's and item's price on the order date) - filled as soon as what it is looked up by is chosen
  const lookups = entity.definition.lookups ?? [];
  const lookedBy = new Set(lookups.flatMap(lookup => [...Object.values(lookup.match), ...(lookup.at ? [lookup.at] : [])]));
  function lookUp(values: FieldValues) {
    const body = Object.fromEntries(fields.filter(field => field.type !== 'serial').map(field => [field.name, storedField(field, values[field.name] ?? '')]));
    void apiFetch(`${api}/_lookup`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }).then(async response => {
      if (!response.ok) return;
      const found = await response.json() as Record<string, unknown>;
      setHeader(previous => ({ ...previous, ...Object.fromEntries(Object.entries(found).filter(([, value]) => value !== null && value !== undefined)
        .map(([into, value]) => [into, typedField(fields.find(field => field.name === into)!, value)])) }));
    }).catch(() => {});
  }
  function setHead(name: string, value: string) {
    setHeader(previous => ({ ...previous, [name]: value }));
    if (lookups.length && lookedBy.has(name)) lookUp({ ...header, [name]: value });
    const field = fields.find(item => item.name === name);
    if (field?.ref && field.fill && value) void rowOf(field.ref.entity, value).then(chosen => {
      if (chosen) setHeader(previous => (previous[name] === value ? { ...previous, ...Object.fromEntries(Object.entries(field.fill!).map(([into, from]) => [into, text(chosen[from])])) } : previous));
    }).catch(() => {});
  }
  function setLine(index: number, field: DefinedField, value: string, table = 'lines') {
    changeRows(table, previous => previous.map((line, at) => (at === index ? { ...line, [field.name]: value } : line)));
    if (field.ref && field.fill && value) void rowOf(field.ref.entity, value).then(chosen => {
      if (chosen) changeRows(table, previous => previous.map((line, at) => (at === index && line[field.name] === value ? { ...line, ...Object.fromEntries(Object.entries(field.fill!).map(([into, from]) => [into, text(chosen[from])])) } : line)));
    }).catch(() => {});
  }

  // Several records chosen in the list (Ctrl or Shift): a status action all of them allow can be taken on all at once.
  const together = chosen.length > 1 && status ? status.actions.filter(action => (over ? over.actions.includes(action.name) : !action.separate) && chosen.every(row => action.from.includes(row.status))) : [];
  async function actOnAll(name: string, label: string) {
    if (askOf(name).length) { setAsking({ name, label, rows: chosen, typed: {} }); return; }
    setBulk({ busy: true, note: '' });
    const failed: string[] = [];
    let done = 0;
    for (const row of chosen) {
      const response = await apiFetch(`${api}/${row.id}/actions/${name}`, { method: 'POST', headers: { 'X-Seen': text(row.seenAt) } });
      if (response.ok) done++; else failed.push(`${row[fields[0]?.name ?? ''] || row.id}: ${(await failure(response, `${label}하지 못했습니다.`)).message}`);
    }
    setBulk({ busy: false, note: `${done}건 ${label}했습니다.` + (failed.length ? `\n${failed.length}건은 하지 못했습니다:\n` + failed.slice(0, 5).join('\n') : '') });
    setChosen([]);
    await list.refresh();
    if (selected) void open(selected.id);
  }

  function askedCell(field: DefinedField, row: Row) {
    const value = asking?.typed[row.id]?.[field.name] ?? '';
    const put = (next: string) => setAsking(previous => previous && ({ ...previous, typed: { ...previous.typed, [row.id]: { ...previous.typed[row.id], [field.name]: next } } }));
    const name = `${row[fields[0]?.name ?? ''] || row.id} ${field.label}`;
    if (field.type === 'date') return <DateInput label={name} hideLabel value={value} onChange={put} />;
    if (field.type === 'time') return <TimeInput label={name} hideLabel center value={value} onChange={put} />;
    if (field.type === 'number') return <NumberInput label={name} hideLabel decimals={field.decimals} value={value} onChange={put} />;
    if (field.type === 'yesno') return <YesNoInput label={name} hideLabel value={value} onChange={put} />;
    if (field.type === 'code') return <CodeField hideLabel field={{ label: name, required: true, codeGroup: field.codeGroup ?? undefined }} control={{ value, onChange: put, disabled: false }} />;
    if (field.ref) { const control = toField(field, false); return control.lookup ? <LookupField hideLabel field={{ ...control, label: name }} lookup={control.lookup} control={{ value, onChange: put, disabled: false }} /> : null; }
    return <TextInput label={name} hideLabel value={value} onChange={put} />;
  }

  /** The record on screen as a paper form (what is typed but not saved is printed as typed). */
  async function handlePrint() {
    const groups = [...new Set([...fields, ...lineFields].filter(field => field.type === 'code' && field.codeGroup).map(field => field.codeGroup as string))];
    const response = groups.length ? await apiFetch(`/api/auth/codes?groups=${encodeURIComponent(groups.join(','))}`) : null;
    const codes = response?.ok ? await response.json() as Record<string, { code: string; name: string }[]> : {};
    const read = (field: DefinedField, value: string) => field.ref ? nameOf(field, value)
      : field.type === 'code' ? codes[field.codeGroup ?? '']?.find(item => item.code === value)?.name ?? value
      : shownField(field, value);
    const serial = fields.find(field => field.type === 'serial');
    const form = printOf(entity.definition), layout = entity.definition.print;
    const brand = currentBranding();
    // The two sides of the paper: the company itself (from the system settings) and the record the form is addressed to.
    const parties: { title: string; rows: { label: string; value: string }[] }[] = [];
    const receiver = layout?.receiver ? fields.find(field => field.name === layout.receiver) : undefined;
    if (layout?.company) parties.push({ title: '공급자', rows: [{ label: '상호', value: brand.companyName || brand.systemName }, { label: '대표자', value: brand.companyCeo ?? '' },
      { label: '등록번호', value: brand.companyBizNo ?? '' }, { label: '주소', value: brand.companyAddress ?? '' }, { label: '전화', value: brand.companyPhone ?? '' }].filter((row, index) => index === 0 || row.value) });
    if (receiver?.ref) {
      const chosen = sources[receiver.ref.entity]?.find(item => text(item.id) === (header[receiver.name] ?? ''));
      const target = definitionOf(receiver.ref.entity);
      const more = (target?.fields ?? []).filter(field => field.name !== receiver.ref!.label && ['text', 'serial'].includes(field.type) && chosen?.[field.name]).slice(0, 4);
      parties.push({ title: '공급받는자', rows: [{ label: receiver.label, value: chosen ? text(chosen[receiver.ref.label]) : '' }, ...more.map(field => ({ label: field.label, value: text(chosen?.[field.name]) }))] });
    }
    const headFields = fields.filter(field => field.type !== 'serial' && !field.sum && field.name !== receiver?.name && (!layout?.fields?.length || layout.fields.includes(field.name)));
    const lineColumns = lineFields.filter(field => !layout?.columns?.length || layout.columns.includes(field.name));
    const totals = fields.filter(field => field.sum).map(field => ({ label: field.label, value: headerValue(field) }));
    if (layout?.vat != null && totals.length) {     // the lines add up to the supply price; tax and the grand total follow
      const supply = fields.find(field => field.sum), column = lineFields.find(line => line.name === supply?.sum);
      const amount = column ? items.reduce((total, line) => total + (lineValue(line, column) ?? 0), 0) : 0, tax = Math.round(amount * layout.vat) / 100;
      totals.splice(0, totals.length, { label: '공급가액', value: shownNumber(amount, supply) }, { label: `부가세 (${layout.vat}%)`, value: shownNumber(Math.round(tax), supply) }, { label: '합계', value: shownNumber(amount + Math.round(tax), supply) });
    }
    printRecord({ ...form, foot: title, logo: layout?.logo && brand.logo ? brand.logo : undefined, parties,
      number: serial ? { label: serial.label, value: header[serial.name] ?? '' } : undefined,
      status: selected && status ? status.values.find(value => value.code === selected.status)?.label : undefined,
      pairs: headFields.map(field => ({ label: field.label, value: field.formula ? headerValue(field) : read(field, header[field.name] ?? '') })),
      lines: lines ? { label: lines.label, columns: lineColumns.map(field => ({ label: field.label, align: alignOf(field.type) })),
        rows: items.filter(line => lineFields.some(field => (line[field.name] ?? '').trim() !== '')).map(line => lineColumns.map(field => field.formula ? shownNumber(lineValue(line, field), field) : read(field, line[field.name] ?? ''))) } : undefined,
      totals });
  }

  /** One table of lines with its "줄 추가". A cell follows its field's conditions, judged by the line and the record above it. */
  function linesTable(set: LineSet) {
    const list = rowsOf(set.name), first = set.name === 'lines';
    const put = (index: number, field: DefinedField, value: string) => setLine(index, field, value, set.name);
    return <div key={set.name} className="doc-set" data-ui={first ? undefined : 'document-more-lines'}>
      {sets.length > 1 && <strong className="doc-set-title">{set.label}</strong>}
      <table className="doc-lines bp6-html-table bp6-compact" data-ui={first ? 'document-lines' : `document-lines-${set.name}`} aria-label={set.label ?? '명세'}>
      <thead><tr><th className="doc-no">#</th>{set.fields.map(field => <th key={field.name}>{field.label}{field.required ? ' *' : ''}</th>)}<th className="doc-remove" /></tr></thead>
      <tbody>{list.map((line, index) => <tr key={index}>
        <td className="doc-no">{index + 1}</td>
        {set.fields.map(field => { const off = locked || holds(field.lockWhen, line, header), name = `${field.label} ${index + 1}`;
          return <td key={field.name} className={field.type === 'number' ? 'is-number' : alignOf(field.type) === 'center' ? 'is-center' : undefined}>
          {field.showWhen && !holds(field.showWhen, line, header) ? <span className="doc-off" aria-label={`${name} 해당 없음`} />
            : field.formula ? <span aria-label={name}>{shownNumber(lineValue(line, field, set.fields), field)}</span>
            : first && ledger && ledger.direction !== 'in' && ledger.lot === field.name ? <span className="doc-lot">
                <TextInput label={name} hideLabel isDisabled={off} value={line[field.name] ?? ''} onChange={value => put(index, field, value)} />
                <Button label={`${index + 1}번째 줄 LOT 고르기`} isIconOnly variant="ghost" icon="search" isDisabled={off} onClick={() => setLotFor(index)} /></span>
            : field.ref?.line ? <LineField hideLabel field={{ label: name, required: field.required }} lookup={{ entity: field.ref.entity, label: field.ref.label, within: field.ref.within, withinTarget: field.ref.withinTarget }}
                control={{ value: line[field.name] ?? '', onChange: value => put(index, field, value), disabled: off }} owner={field.ref.within ? (line[field.ref.within] ?? header[field.ref.within]) : undefined} />
            : field.ref ? <Picker label={name} hideLabel isDisabled={off} mode={partial[field.ref.entity] && pickOf(field).pick === 'dropdown' ? 'popup' : pickOf(field).pick} columns={pickOf(field).columns} title={pickOf(field).title}
                value={line[field.name] ?? ''} onChange={value => put(index, field, value)}
                options={(sources[field.ref.entity] ?? []).map(item => optionOf(field, item))} search={searchIn(field)} />
            : field.type === 'number' ? <NumberInput label={name} hideLabel isDisabled={off} decimals={field.decimals} value={line[field.name] ?? ''} onChange={value => put(index, field, value)} />
            : field.type === 'time' ? <TimeInput label={name} hideLabel center isDisabled={off} value={line[field.name] ?? ''} onChange={value => put(index, field, value)} />
            : field.type === 'yesno' ? <YesNoInput label={name} hideLabel isDisabled={off} value={line[field.name] ?? ''} onChange={value => put(index, field, value)} />
            : field.type === 'date' ? <DateInput label={name} hideLabel center isDisabled={off} value={line[field.name] ?? ''} onChange={value => put(index, field, value)} />
            : field.type === 'code' && field.codeGroup ? <CodeField hideLabel field={{ label: name, codeGroup: field.codeGroup, pick: pickOf(field).pick }} control={{ value: line[field.name] ?? '', onChange: value => put(index, field, value), disabled: off }} />
            : <TextInput label={name} hideLabel isDisabled={off} value={line[field.name] ?? ''} onChange={value => put(index, field, value)} />}
        </td>; })}
        <td className="doc-remove"><Button label={first ? `${index + 1}번째 줄 삭제` : `${set.label} ${index + 1}번째 줄 삭제`} isIconOnly variant="ghost" icon="small-cross" isDisabled={locked || list.length <= set.min}
          onClick={() => changeRows(set.name, previous => previous.filter((_, at) => at !== index))} /></td>
      </tr>)}</tbody>
      </table>
      <div className="doc-foot"><Button label={first ? '줄 추가' : `${set.label} 줄 추가`} icon="plus" isDisabled={locked || (set.max !== null && list.length >= set.max)} onClick={() => changeRows(set.name, previous => [...previous, {}])} />
        {set.max !== null && <span className="doc-limit">{`최대 ${set.max}줄`}</span>}</div>
    </div>;
  }

  // The entity's own screen offers every action that is not kept for a work screen; a work screen offers exactly its own.
  const actions = selected && status ? status.actions.filter(action => action.from.includes(selected.status) && (over ? over.actions.includes(action.name) : !action.separate)) : [];
  const form = <div className="doc" data-ui="document-editor">
    <div className="doc-head">
      <strong>{over ? (selected ? '내용' : over.create ? '신규' : '목록에서 고르세요') : selected ? '수정' : ownOnly ? `목록에서 고르세요${takingScreens(key).length ? ` (등록은 ${takingScreens(key).map(name => `「${name}」`).join(', ')}에서)` : ''}` : '신규'}</strong>
      {fields.filter(field => field.type === 'serial').map(field => <span key={field.name} className="doc-serial" aria-label={field.label}>{header[field.name] || `${field.label}: 저장하면 매겨집니다`}</span>)}
      {selected && status && <span className={`fw-status is-${statusTone(status, selected.status)}`} aria-label="상태">{status.values.find(value => value.code === selected.status)?.label ?? selected.status}</span>}
      <span style={{ flex: 1 }} />
      {actions.map(action => <Button key={action.name} label={action.label} outlined variant={action.to === status?.initial ? undefined : 'primary'} onClick={() => void act(action.name, action.label)} />)}
    </div>
    <fieldset disabled={locked} className="doc-fields">
      <Fields fields={headerFields} values={header} setValue={setHead} errors={{}} disabled={locked} />
      {fields.filter(field => field.sum || field.formula).map(field => <div key={field.name} className="doc-computed"><span>{field.label}</span><strong aria-label={field.label}>{headerValue(field) || '0'}</strong></div>)}
    </fieldset>
    {sets.map(set => linesTable(set))}
    <div className="doc-foot">{message && <span role={message.bad ? 'alert' : 'status'} className={message.bad ? 'doc-message is-bad' : 'doc-message'}>{message.text}</span>}</div>
    <AsyncFeedback error="" />
  </div>;

  return <>
  <BusinessWorkspace title={title}
    actions={over ? { query: { form: queryForm }, ...(over.create ? { create: { onClick: handleNew } } : {}), ...(over.edit || over.create ? { save: { onClick: handleSave, disabled: locked || (selected ? !over.edit : !over.create) } } : {}), print: { onClick: handlePrint, disabled: !selected }, links: { onClick: () => setLinking(true), disabled: !selected }, files: { onClick: () => setFiling(true), disabled: !selected, label: fileCount ? `첨부 ${fileCount}` : undefined }, history: { onClick: () => setHistory(true), disabled: !selected } }
      : { query: { form: queryForm }, ...(ownOnly ? {} : { create: { onClick: handleNew }, copy: { onClick: handleCopy, disabled: !selected } }), save: { onClick: handleSave, disabled: locked || (ownOnly && !selected) }, ...(ownOnly ? {} : { import: { onClick: () => setImporting(true) } }),
      remove: { onClick: handleDelete, disabled: !selected || locked, confirm: `선택한 ${title} 자료를 삭제할까요?` },
      print: { onClick: handlePrint, disabled: !selected }, links: { onClick: () => setLinking(true), disabled: !selected }, files: { onClick: () => setFiling(true), disabled: !selected, label: fileCount ? `첨부 ${fileCount}` : undefined }, history: { onClick: () => setHistory(true), disabled: !selected } }}
    query={<QueryPanel formId={queryForm} fields={queryFields} onQuery={handleQuery} initialValues={opening} />}
    results={<><LinkedNote linked={sent.linked} onRelease={releaseLinked} />
      {asking && <div className="fw-bulk" data-ui="asked-action" role="status">
        <b>{asking.label} {asking.rows.length}건</b><span className="fw-bulk-note">줄마다 {askOf(asking.name).map(field => field.label).join(', ')}을(를) 적고 확정하세요.</span>
        <Button label={`${asking.label} 확정`} variant="primary" isDisabled={bulk.busy} isLoading={bulk.busy} onClick={() => void confirmAsked()} />
        <Button label="취소" variant="ghost" isDisabled={bulk.busy} onClick={() => setAsking(null)} />
      </div>}
      {status && !asking && (chosen.length > 1 || bulk.note) && <div className="fw-bulk" data-ui="bulk-actions" role="status">
        {chosen.length > 1 && <b>{chosen.length}건 선택</b>}
        {together.map(action => <Button key={action.name} label={`모두 ${action.label}`} outlined variant="primary" isDisabled={bulk.busy} isLoading={bulk.busy} onClick={() => void actOnAll(action.name, action.label)} />)}
        {chosen.length > 1 && together.length === 0 && <span className="fw-bulk-note">고른 건들이 함께 할 수 있는 동작이 없습니다 (상태가 서로 다릅니다).</span>}
        {bulk.note && <span className="fw-bulk-note">{bulk.note}</span>}
      </div>}
      <RecordGrid label={title} rows={asking ? asking.rows : rows} keyField="id" selection={status ? 'multiple' : 'single'}
        columns={asking ? [...columns.filter(column => column.key !== 'updatedBy' && column.key !== 'updatedAt'), ...askOf(asking.name).map(field => ({ key: `ask_${field.name}`, label: `${field.label} *`, width: field.type === 'memo' || field.type === 'text' ? 220 : 150, render: (row: Row) => askedCell(field, row) }))] : columns} onSelectionChange={picked => { setChosen(picked); if (picked.length > 1) setBulk(previous => ({ ...previous, note: '' })); }} onSelect={row => void open(row.id)}
      total={list.total} onMore={list.more} onSort={sort => { void list.sortBy(sort && { ...sort, key: sort.key === 'statusLabel' ? 'status' : sort.key }).catch(() => {}); }} /></>}
    editorTabs={[{ id: 'document', label: ['기본 정보', ...sets.map(set => set.label)].join(' · '), content: form }]} />
    <LinksDialog api={`/api/data/${key}`} id={selected?.id ?? null} title={title} isOpen={linking} onClose={() => setLinking(false)}
      name={selected ? `${entity.definition.title.replace(/\s*(등록|관리|입력)$/, '')} ${header[fields.find(field => field.type === 'serial')?.name ?? fields[0]?.name ?? ''] ?? ''}`.trim() : ''} />
    <FilesDialog api={api} id={selected?.id ?? null} title={title} isOpen={filing} onClose={() => setFiling(false)} onCount={setFileCount} readOnly={locked} />
    <HistoryDialog api={api} id={selected?.id ?? null} title={title} isOpen={history} onClose={() => setHistory(false)} />
    {ledger?.lot && <LotDialog isOpen={lotFor !== null} onClose={() => setLotFor(null)}
      thing={lotFor === null ? '' : items[lotFor]?.[ledger.thing] ?? header[ledger.thing] ?? ''} place={lotFor === null ? '' : items[lotFor]?.[ledger.place] ?? header[ledger.place] ?? ''}
      onPick={lot => { const field = lineFields.find(item => item.name === ledger.lot); if (lotFor === -1) setHead(ledger.lot!, lot); else if (field && lotFor !== null) setLine(lotFor, field, lot); }} />}
    {!over && <ImportDialog title={title} api={api} labels={sheetLabels} isOpen={importing} onClose={() => setImporting(false)} onDone={() => { void list.refresh(); }}
      note={lines ? `${lines.label} 한 줄이 시트의 한 줄입니다. 위쪽 항목이 같은 줄이 이어지면 한 건으로 묶입니다.` : undefined} />}
  </>;
}
