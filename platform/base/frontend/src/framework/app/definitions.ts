import { apiFetch } from '../auth/sessionClient';
import { alignOf, readNumber, showDate, showNumber, showValue, showYesNo, storeDate, storeTime, type Align } from '../format';

/** One field of a defined entity, as the server's definition says. */
export type DefinedField = { name: string; label: string; type: 'text' | 'number' | 'date' | 'time' | 'yesno' | 'memo' | 'code' | 'ref' | 'serial'; required: boolean; search: boolean;
  codeGroup: string | null; ref: { entity: string; label: string; columns: string[] | null; code: string | null; line?: boolean; within?: string | null; withinTarget?: string | null } | null;
  /** serial prefix / computed from the row's numbers / header total of a line field / target field <- field of the chosen record */
  prefix: string | null; formula: string | null; sum: string | null; fill: Record<string, string> | null;
  /** allowed range of a number / no two records with the same value / how a code or ref is chosen */
  min: number | null; max: number | null; decimals: number | null; unique: boolean; pick: 'dropdown' | 'search' | 'popup' | null;
  /** there only when / required when / locked when another field has one of the values */
  showWhen?: { field: string; is: string[]; not?: boolean } | null; requiredWhen?: { field: string; is: string[]; not?: boolean } | null; lockWhen?: { field: string; is: string[]; not?: boolean } | null };
export type DefinedStatus = { initial: string; values: { code: string; label: string }[];
  actions: { name: string; label: string; from: string[]; to: string; separate: boolean }[]; locked: string[]; closed?: string[] };
/** A definition-driven screen: its fields are data kept on the server, not code. */
export type EntityDefinition = { key: string; programCode: string; status: 'DRAFT' | 'PUBLISHED'; revision: number;
  definition: { key: string; type: 'master' | 'document' | 'summary' | 'dashboard' | 'over' | 'calendar' | 'tree' | 'take'; title: string; keywords: string[]; fields: DefinedField[];
    lines: { label: string; fields: DefinedField[]; min: number; max: number | null } | null; status: DefinedStatus | null;
    /** Further tables of lines, each kept in the record under its name. */
    moreLines?: { name: string; label: string; fields: DefinedField[]; min: number; max: number | null }[] | null;
    /** A screen that gathers another entity's rows instead of storing its own. */
    summary: { entity: string; lines: boolean; groupBy: { field: string; by: string | null; label: string }[]; values: { label: string; op: string; field: string | null }[];
      filters: string[]; chart: { type: 'bar' | 'line' | 'pie'; value: string } | null;
      compare: { type: 'plan' | 'previous' | 'minus'; value: string; label: string } | null; share: boolean; top: number | null; cumulative: boolean } | null;
    /** A work screen over another entity's records (approve, hand over, look up). */
    over: { entity: string; statuses: string[]; actions: string[]; edit: boolean; create?: boolean; mine?: boolean; ask?: Record<string, string[]> } | null;
    /** A board of chart panels, each drawing one summary screen. */
    dashboard: { panels: { summary: string; chart: 'bar' | 'line' | 'pie' | 'figures'; value: string; title: string; width: number }[] } | null;
    /** How one record is printed as a paper form. */
    print: { title: string | null; signers: string[]; note: string | null; logo?: boolean; company?: boolean; receiver?: string | null; fields?: string[]; columns?: string[]; vat?: number | null } | null;
    /** What the list asks for when the screen opens (all | today | week | month | year); the date a month's closing goes by (or "none"). */
    period?: string | null; closing?: string | null;
    /** A month calendar of another entity's records. */ calendar?: { entity: string; date: string; end: string | null; label: string | null } | null;
    /** The records move quantities in the ledger: a thing at a place (in: lots at the line's cost; out: from the oldest lots, or from the lot named in `lot`; move: to toPlace; count). */ ledger?: { direction: 'in' | 'out' | 'move' | 'count'; thing: string; quantity: string; place: string; unitCost: string | null; date: string | null; lot: string | null; toPlace?: string | null; thingEntity?: string; placeEntity?: string } | null;
    /** Master data that combines other master data: field combinations no two records share; a parent its lines may not lead back to. */
    /** A screen that shows the ledger and stores nothing. */ ledgerView?: { show: 'all' | 'balance' | 'lots' | 'moves'; thing?: string | null } | null;
    uniqueBy?: string[][] | null; noCycle?: { parent: string; child: string } | null;
    /** A later stage: its records come only from the stage before (this field points at it); a 기타 screen registers ones without it. */ follows?: string | null;
    /** Data only: no screen of its own; made and moved on elsewhere. */ dataOnly?: boolean;
    /** Values found in master data (a customer's price for an item on the order date): from, match {theirs: mine}, at, set {mine: theirs}. */ lookups?: { from: string; match: Record<string, string>; at: string | null; set: Record<string, string> }[];
    /** Made from an earlier entity's records, one each: the pointer, what is carried over by name, what each row asks. */ from?: { entity: string; pointer: string | null; statuses: string[]; carry: string[]; ask: string[] } | null;
    /** Registering the next stage from a list of what an earlier stage leaves open (no form). */ take?: { entity: string; from: string; statuses: string[]; set: Record<string, string>; lineSet: Record<string, string>; columns: string[]; group?: 'source' | 'same' | null; ask?: string[] | null } | null;
    /** A hierarchy of another entity's records (own parent, or pairs of parent and child). */ tree?: { entity: string; parent: string; child: string | null; label: string | null; columns: string[] } | null } };

/** Published definitions; drafts too when asked (administrators; used to look at a screen before it is published). */
export async function loadDefinitions(drafts = false): Promise<EntityDefinition[]> {
  const response = await apiFetch(`/api/meta/definitions${drafts ? '?drafts=true' : ''}`);
  if (response.status === 404) return [];
  if (!response.ok) throw new Error('화면을 읽지 못했습니다.');
  const list = await response.json() as EntityDefinition[];
  // who registered a record (type user) is filled by the server and never typed: on the screens it reads like an automatic number
  for (const item of list) for (const field of item.definition.fields ?? []) if ((field.type as string) === 'user') { field.type = 'serial'; field.prefix = null; }
  for (const item of list) known.set(item.key, item);
  return list;
}

const known = new Map<string, EntityDefinition>();
/** The words for the quantity ledger, taken from the screens that move it (the thing, the place, the numbered lot): no business is assumed. */
/** of: the thing entity a view is about (its screens' words are used); none: the first screen that moves the ledger. */
export function ledgerWords(of?: string | null): { thing: string; place: string; lot: string } {
  const noun = (key: string | undefined) => (key ? known.get(key)?.definition.title.replace(/\s*(등록|관리|입력)$/, '') : undefined);
  const mover = [...known.values()].find(item => item.definition.ledger && (!of || item.definition.ledger.thingEntity === of));
  const ledger = mover?.definition.ledger;
  const lotField = ledger?.lot ? mover!.definition.fields.find(field => field.name === ledger.lot) : undefined;
  return { thing: noun(ledger?.thingEntity) ?? '대상', place: noun(ledger?.placeEntity) ?? '위치', lot: lotField?.label.replace(/\s*번호$/, '') ?? '묶음' };
}
/** The screens people register this entity on from the stage before (its take-over screens), by name. */
export function takingScreens(key: string): string[] {
  return [...known.values()].filter(item => item.definition.take?.entity === key).map(item => item.definition.title);
}
/** A stored value of a field as it reads in a list, on paper and in a file (a code or another screen's record is named by the screen, which knows the names). */
export function shownField(field: DefinedField, value: unknown): string {
  if (field.type === 'number') return field.decimals === null || field.decimals === undefined ? showNumber(value) : showNumber(value, field.decimals, true);
  if (field.type === 'yesno') return showYesNo(value);
  return showValue(field.type, value);
}
/** A stored value as the text a form box holds (dates with slashes, a yes as 'true', nothing as ''). */
export function typedField(field: DefinedField, value: unknown): string {
  if (value === null || value === undefined) return '';
  if (field.type === 'yesno') return value === true || value === 'true' ? 'true' : '';
  return field.type === 'date' ? showDate(value) : String(value);
}
/** What a form box holds, as it is sent to be stored. */
export function storedField(field: DefinedField, typed: string): unknown {
  const value = (typed ?? '').trim();
  if (field.type === 'yesno') return value === 'true';
  if (value === '') return null;
  return field.type === 'number' || field.type === 'ref' ? Number(readNumber(value)) : field.type === 'date' ? storeDate(value) : field.type === 'time' ? storeTime(value) : value;
}
/** Another screen's definition (as loaded with the list), e.g. the entity a summary gathers. */
export function definitionOf(key: string) { return known.get(key)?.definition; }
/** What a status is in the life of a record, for its colour: the start, on the way, done (a locked or last status), or called off. */
export function statusTone(status: DefinedStatus, code: string): 'start' | 'going' | 'done' | 'off' {
  const label = status.values.find(value => value.code === code)?.label ?? '';
  if (/취소|거절|반려|중단|폐기|보류/.test(label) || /CANCEL|REJECT|VOID/i.test(code)) return 'off';
  if (code === status.initial) return 'start';
  return status.locked.includes(code) || status.values[status.values.length - 1]?.code === code ? 'done' : 'going';
}
/** Another screen as loaded (its program code opens it). */
export function entityOf(key: string) { return known.get(key); }
/** How a ref field is chosen and what its search window lists: the definition's words, or the target's first plain fields. */
/** The target's field shown before the name ("V-001 한빛상사"): the definition's choice, or the target's first field when that is a code or a number of its own. */
export function codeOf(field: DefinedField): string | undefined {
  if (!field.ref) return undefined;
  if (field.ref.code) return field.ref.code;
  const first = known.get(field.ref.entity)?.definition.fields[0];
  return first && first.name !== field.ref.label && (first.type === 'text' || first.type === 'serial') ? first.name : undefined;
}
/** A referenced record as it reads everywhere: code and name. */
export function refText(field: DefinedField, row: Record<string, unknown> | undefined): string {
  if (!row || !field.ref) return '';
  const code = codeOf(field), show = (value: unknown) => (value === null || value === undefined ? '' : String(value));
  return [code ? show(row[code]) : '', show(row[field.ref.label])].filter(Boolean).join(' ');
}
/** The heading, approval boxes and note of the paper form: the definition's, or the usual ones. */
export function printOf(definition: EntityDefinition['definition']) {
  return { title: definition.print?.title || definition.title.replace(/\s*(등록|관리|입력)$/, ''), signers: definition.print?.signers?.length ? definition.print.signers : ['담당', '검토', '승인'],
    note: definition.print?.note ?? undefined };
}
export function pickOf(field: DefinedField): { pick: 'dropdown' | 'search' | 'popup'; columns: { key: string; label: string; align?: Align; text?: (value: unknown) => string }[]; title: string; code?: string } {
  const target = field.ref ? known.get(field.ref.entity)?.definition : undefined;
  const names = field.ref?.columns ?? target?.fields.filter(item => item.type === 'text' || item.type === 'serial' || item.type === 'number' || item.type === 'date' || item.type === 'time' || item.type === 'yesno').slice(0, 5).map(item => item.name) ?? [];
  const columns = names.flatMap(name => { const found = target?.fields.find(item => item.name === name); return found ? [{ key: found.name, label: found.label, align: alignOf(found.type), text: found.type === 'code' || found.type === 'ref' ? undefined : (value: unknown) => shownField(found, value) }] : []; });
  // Two ways only: a plain list, or the search box. For a record of another screen the search box always comes with its
  // search window (magnifier, F2, Enter on several matches); a common code has no window, only the candidates.
  const pick = field.type === 'code' ? (field.pick === 'search' || field.pick === 'popup' ? 'search' : 'dropdown') : field.pick === 'dropdown' ? 'dropdown' : 'popup';
  return { pick, columns, title: `${field.label} 찾기`, code: codeOf(field) };
}
