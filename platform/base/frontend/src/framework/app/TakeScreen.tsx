import { useEffect, useMemo, useRef, useState } from 'react';
import { BusinessWorkspace } from '../BusinessWorkspace';
import { QueryPanel } from '../QueryPanel';
import { RecordGrid, type GridColumn } from '../RecordGrid';
import { Fields, LookupField, holds, type FieldDefinition, type FieldValues } from '../fields';
import { apiFetch } from '../auth/sessionClient';
import { alignOf, readNumber, showDate, showNumber, storeDate, today } from '../format';
import { Button, Select, YesNoInput } from '../ui';
import { useWorkspaceNav } from '../workspace/navContext';
import { definitionOf, entityOf, shownField, storedField, type DefinedField, type EntityDefinition } from './definitions';
import { failure, text, toField } from './EntityScreen';
import { periodFields, storedQuery } from './query';
import { intentOf } from './links';
import { LotDialog } from './LotDialog';
import './views.css';

type Shape = { entity: string; from: string; lines: boolean; ask: string[]; quantity: string | null; once?: boolean; quantityLabel: string; decimals: number | null; columns: string[]; combinable: boolean; group: 'source' | 'same'; fromTitle: string; askLines?: { name: string; label: string; type: string; required: boolean }[];
  /** The lot typed in a row can be chosen from the lots held: the row's thing (a field of the earlier line) and where the place comes from. */
  lotPick?: { field: string; thing: string | null; placeAsked: string | null; placeFrom: string | null } };
type Open = { key: string; sourceId: number; line: number; head: Record<string, unknown> & { _names?: Record<string, string> }; unit?: Record<string, unknown> & { _names?: Record<string, string> }; ordered: number; done: number; remaining: number };
type Row = Record<string, string> & { key: string };
type Made = { count: number; lines: number; title: string; created: { id: number; name: string }[] };

/**
 * A take-over screen, drawn from its definition: the next stage registered from a list of what the earlier stage still
 * leaves open (shipments from orders not shipped in full). Everything happens in the list - conditions, tick the rows,
 * set this time's quantity in the row, 저장. There is no form: many records are never handled through an edit panel.
 * The few values every new record needs and the earlier stage cannot give (the date, the place) are asked once above the list.
 */
export function TakeScreen({ entity }: { entity: EntityDefinition }) {
  const { title, take } = entity.definition;
  const api = `/api/take/${entity.key}`, queryForm = `take-${entity.key}-query`;
  const earlier = definitionOf(take!.from), target = definitionOf(take!.entity);
  const nav = useWorkspaceNav();
  const [shape, setShape] = useState<Shape | null>(null);
  const [rows, setRows] = useState<Row[]>([]);
  const [picked, setPicked] = useState<string[]>([]);
  const [values, setValues] = useState<FieldValues>({});
  const [message, setMessage] = useState<{ text: string; bad?: boolean; made?: Made } | null>(null);
  const [per, setPer] = useState<'source' | 'same'>('source');
  const [codeNames, setCodeNames] = useState<Record<string, Record<string, string>>>({});
  const typed = useRef<FieldValues>({});
  const opens = useRef<Record<string, Open>>({});          // the rows as the server gave them (ids, not names): what the lot window asks by
  const [lotFor, setLotFor] = useState<string | null>(null);
  const headFields = earlier?.fields ?? [], lineFields = earlier?.lines?.fields ?? [];

  useEffect(() => { let alive = true;
    void apiFetch(`${api}/shape`).then(async response => { if (alive && response.ok) { const read = await response.json() as Shape; setShape(read); setPer(read.group); } }).catch(() => {});
    return () => { alive = false; }; }, [api, entity.revision]);
  const groups = [...new Set([...headFields, ...lineFields].filter(field => field.type === 'code' && field.codeGroup).map(field => field.codeGroup as string))].join(',');
  useEffect(() => { if (!groups) return; let alive = true;
    void apiFetch(`/api/auth/codes?groups=${encodeURIComponent(groups)}`).then(async response => {
      const codes = response.ok ? await response.json() as Record<string, { code: string; name: string }[]> : {};
      if (alive) setCodeNames(Object.fromEntries(Object.entries(codes).map(([group, list]) => [group, Object.fromEntries(list.map(item => [item.code, item.name]))])));
    }).catch(() => {});
    return () => { alive = false; }; }, [groups]);

  // The values asked once: the new record's fields above its lines that the earlier stage does not give. A date starts as today.
  const askFields = useMemo(() => (shape && target ? shape.ask.flatMap(name => target.fields.filter(field => field.name === name)) : []), [shape, target]);
  useEffect(() => { setValues(previous => ({ ...Object.fromEntries(askFields.filter(field => field.type === 'date' && field.required).map(field => [field.name, showDate(today())])), ...previous })); }, [askFields]);
  const askForm: FieldDefinition[] = useMemo(() => askFields.map(field => ({ ...toField(field, false), group: undefined })), [askFields]);

  const queryFields = useMemo(() => {
    const marked = headFields.filter(field => field.search);
    const base = (marked.length ? marked : headFields.filter(field => field.type === 'serial' || field.type === 'text').slice(0, 2)).flatMap(field => (field.type === 'date' ? periodFields(toField(field, true)) : [toField({ ...field, type: field.type === 'serial' ? 'text' : field.type }, true)]));
    const statuses = earlier?.status?.values.filter(value => !take!.statuses.length || take!.statuses.includes(value.code)) ?? [];
    return statuses.length > 1 ? [...base, { name: 'status', label: '상태', render: (control: { value: string; onChange: (value: string) => void }) =>
      <Select label="상태" value={control.value} onChange={control.onChange} options={[{ value: '', label: '전체' }, ...statuses.map(value => ({ value: value.code, label: value.label }))]} /> } as FieldDefinition] : base;
  }, [entity.revision, earlier]);   // eslint-disable-line react-hooks/exhaustive-deps

  const read = (field: DefinedField, unit: Record<string, unknown> & { _names?: Record<string, string> }) => field.ref ? unit._names?.[field.name] ?? text(unit[field.name])
    : field.type === 'code' ? codeNames[field.codeGroup ?? '']?.[text(unit[field.name])] ?? text(unit[field.name]) : shownField(field, unit[field.name]);
  const amount = (value: number) => showNumber(value, shape?.decimals ?? undefined);
  const toRow = (item: Open): Row => ({ key: item.key, sourceId: String(item.sourceId), line: String(item.line),
    ...Object.fromEntries(headFields.map(field => [`h_${field.name}`, read(field, item.head)])), h_statusLabel: text(item.head.statusLabel),
    ...Object.fromEntries(lineFields.map(field => [`l_${field.name}`, item.unit ? read(field, item.unit) : ''])),
    ordered: amount(item.ordered), done: amount(item.done), remaining: amount(item.remaining), quantity: amount(item.remaining) });

  async function load(conditions: FieldValues) {
    typed.current = conditions;
    const response = await apiFetch(`${api}?${new URLSearchParams(storedQuery(headFields, conditions)).toString()}`);
    if (!response.ok) throw await failure(response, `${title} 목록을 조회하지 못했습니다.`);
    const found = await response.json() as Open[];
    opens.current = Object.fromEntries(found.map(item => [item.key, item]));
    const next = found.map(toRow);
    setRows(next);
    setPicked(previous => previous.filter(key => next.some(row => row.key === key)));      // a row still open stays ticked (the list keeps its ticks by row)
  }
  // A list of what is waiting: it is there when the screen opens.
  useEffect(() => { if (shape) void load({}).catch(() => {}); }, [shape, codeNames]);   // eslint-disable-line react-hooks/exhaustive-deps

  async function handleSave() {
    setMessage(null);
    const chosen = rows.filter(row => picked.includes(row.key));
    if (!chosen.length) { setMessage({ text: '목록에서 넘길 줄을 먼저 고르세요.', bad: true }); return; }
    const missing = askFields.find(field => (field.required || holds(field.requiredWhen, values)) && !(values[field.name] ?? '').trim() && (!field.showWhen || holds(field.showWhen, values)));
    if (missing) { setMessage({ text: `${missing.label}을(를) 입력하세요.`, bad: true }); return; }
    const body = { per, values: Object.fromEntries(askFields.map(field => [field.name, storedField(field, values[field.name] ?? '')])),
      rows: chosen.map(row => ({ sourceId: Number(row.sourceId), line: Number(row.line), quantity: shape?.once ? 1 : Number(readNumber(row.quantity)), seen: text(opens.current[row.key]?.head.updatedAt),
        values: Object.fromEntries((shape?.askLines ?? []).filter(field => (row[`a_${field.name}`] ?? '').trim() !== '').map(field => [field.name, field.type === 'number' ? Number(readNumber(row[`a_${field.name}`])) : field.type === 'date' ? storeDate(row[`a_${field.name}`]) : field.type === 'yesno' ? row[`a_${field.name}`] === 'true' : field.type === 'ref' ? Number(row[`a_${field.name}`]) : row[`a_${field.name}`].trim()])) })) };
    const lacking = (shape?.askLines ?? []).find(field => field.required && field.type !== 'yesno' && chosen.some(row => !(row[`a_${field.name}`] ?? '').trim()));
    if (lacking) { setMessage({ text: `고른 줄의 ${lacking.label}을(를) 입력하세요.`, bad: true }); return; }
    const response = await apiFetch(api, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    if (!response.ok) { setMessage({ text: (await failure(response, '저장하지 못했습니다.')).message, bad: true }); return; }
    const made = await response.json() as Made;
    setMessage({ text: `${made.title.replace(/\s*(등록|관리|입력)$/, '')} ${made.count}건을 만들었습니다 (${made.lines}줄)` + (made.created.some(item => item.name) ? `: ${made.created.map(item => item.name).filter(Boolean).slice(0, 5).join(', ')}${made.created.length > 5 ? ' …' : ''}` : '.'), made });
    await load(typed.current);
  }

  // Columns: the earlier record (its number, the fields that say whose and when), the line, then ordered / done / open and this time's quantity.
  const quantityField = (shape?.lines ? lineFields : headFields).find(field => field.name === shape?.quantity);
  const wanted = shape?.columns.length ? shape.columns : null;
  const headShown = headFields.filter(field => (wanted ? wanted.includes(field.name) : !field.sum && !field.formula && field.type !== 'memo' && field.type !== 'yesno' && (field.type === 'serial' || field.type === 'ref' || field.type === 'date' || field.required)) && !(field.name === shape?.quantity && !shape?.lines)).slice(0, wanted ? 20 : 3);      // by default just enough to tell the earlier record: its number, whose, when
  const lineShown = lineFields.filter(field => (wanted ? wanted.includes(field.name) : !field.formula) && field.name !== shape?.quantity);
  const sized = (field: DefinedField) => (field.type === 'text' || field.type === 'ref' ? 150 : field.type === 'yesno' || field.type === 'time' ? 80 : 110);
  const columns: GridColumn<Row>[] = [
    ...headShown.map(field => ({ key: `h_${field.name}`, label: field.label, width: sized(field), align: alignOf(field.type) })),
    ...(earlier?.status ? [{ key: 'h_statusLabel', label: '상태', width: 80, align: 'center' as const }] : []),
    ...lineShown.map(field => ({ key: `l_${field.name}`, label: field.label, width: field.type === 'ref' ? undefined : sized(field), align: alignOf(field.type) })),
    // followed once (no quantities): only what is still open is listed, so there is nothing to count
    ...(shape?.once ? [] : [
      { key: 'ordered', label: quantityField?.label ?? '수량', width: 100, align: 'right' as const }, { key: 'done', label: '처리한 수량', width: 100, align: 'right' as const },
      { key: 'remaining', label: '남은 수량', width: 100, align: 'right' as const },
      { key: 'quantity', label: `이번 ${shape?.quantityLabel ?? '수량'}`, width: 120, align: 'right' as const, editable: true }]),
    // what else is typed in the row (a lot number, the quantity that passed)
    ...(shape?.askLines ?? []).map(field => ({ key: `a_${field.name}`, label: field.label + (field.required ? ' *' : ''), width: field.type === 'ref' ? 200 : field.type === 'text' ? 170 : 110, align: field.type === 'number' ? 'right' as const : field.type === 'date' || field.type === 'time' || field.type === 'yesno' ? 'center' as const : undefined, editable: field.type !== 'yesno' && field.type !== 'ref',
      // a lot number: typed, or chosen from the lots held with the button in the cell; a yes/no: a tick box in the cell
      render: shape?.lotPick?.field === field.name ? (row: Row) => <span className="fw-take-lot"><span>{row[`a_${field.name}`] ?? ''}</span><Button label={`${row.key} LOT 고르기`} icon="search" isIconOnly variant="ghost" onClick={() => setLotFor(row.key)} /></span>
        : field.type === 'yesno' ? (row: Row) => <YesNoInput label={`${row.key} ${field.label}`} hideLabel value={row[`a_${field.name}`] ?? ''} onChange={value => setRows(previous => previous.map(one => (one.key === row.key ? { ...one, [`a_${field.name}`]: value } : one)))} />
        // another record chosen in the row (who took the mail): the same picker as in the edit panel, inside the cell
        : field.type === 'ref' ? (row: Row) => { const defined = target?.fields.find(item => item.name === field.name); const control = defined ? toField(defined, false) : null;
            return control?.lookup ? <LookupField hideLabel field={{ ...control, label: `${row.key} ${field.label}` }} lookup={control.lookup}
              control={{ value: row[`a_${field.name}`] ?? '', onChange: value => setRows(previous => previous.map(one => (one.key === row.key ? { ...one, [`a_${field.name}`]: value } : one))), disabled: false }} /> : null; }
        : undefined })),
  ];
  const targetProgram = entityOf(take!.entity)?.programCode;

  return <><BusinessWorkspace title={title}
    actions={{ query: { form: queryForm }, save: { onClick: handleSave, disabled: picked.length === 0 } }}
    query={<QueryPanel formId={queryForm} fields={queryFields} onQuery={load} />}
    results={<div data-ui="take" style={{ display: 'flex', flexDirection: 'column', flex: 1, minHeight: 0, gap: 6 }}>
      <div className="fw-take-ask" data-ui="take-values">
        {askForm.length > 0 && <div className="fw-take-fields"><Fields fields={askForm} values={values} setValue={(name, value) => setValues(previous => ({ ...previous, [name]: value }))} errors={{}} /></div>}
        <div className="fw-take-note">
          {shape?.combinable && <Select label="묶는 기준" value={per} onChange={value => setPer(value === 'same' ? 'same' : 'source')}
            options={[{ value: 'source', label: `${shape.fromTitle.replace(/\s*(등록|관리|입력)$/, '')} 한 건마다 한 건` }, { value: 'same', label: '위쪽 값이 같으면 한 건으로 묶기' }]} />}
          <span>{picked.length ? `${picked.length}줄 선택 · 이번 수량을 고친 뒤 저장` : '넘길 줄을 고르고(왼쪽 체크) 이번 수량을 고친 뒤 저장을 누르세요'}</span>
          {message && <span role={message.bad ? 'alert' : 'status'} className={message.bad ? 'fw-take-message is-bad' : 'fw-take-message'}>{message.text}</span>}
          {message?.made && targetProgram && <Button label={`${message.made.title} 화면에서 보기`} outlined onClick={() => nav?.open(targetProgram, intentOf({ params: {}, note: `${title}에서 방금 만든 자료`, select: String(message.made!.created[0]?.id ?? '') }))} />}
        </div>
      </div>
      <RecordGrid label={title} rows={rows} columns={columns} keyField="key" editable onRowsChange={next => setRows(next)} onSelectionChange={chosen => setPicked(chosen.map(row => row.key))} total={rows.length} />
    </div>} />
    {shape?.lotPick && <LotDialog isOpen={lotFor !== null} onClose={() => setLotFor(null)}
      thing={(() => { const open = lotFor ? opens.current[lotFor] : undefined, name = shape.lotPick!.thing; return open && name ? text(open.unit?.[name] ?? open.head[name]) : ''; })()}
      place={(() => { const open = lotFor ? opens.current[lotFor] : undefined, pick = shape.lotPick!; return pick.placeAsked ? values[pick.placeAsked] ?? '' : open && pick.placeFrom ? text(open.head[pick.placeFrom]) : ''; })()}
      onPick={lot => setRows(previous => previous.map(row => (row.key === lotFor ? { ...row, [`a_${shape.lotPick!.field}`]: lot } : row)))} />}
  </>;
}
