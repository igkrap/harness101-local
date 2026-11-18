import type { FieldDefinition, FieldValues } from '../fields';
import { showDate, storeDate, storeTime, today } from '../format';
import type { DefinedField, EntityDefinition } from './definitions';

/**
 * The conditions a list is asked by. A date is always asked as a period: two boxes, "<name>_from" and "<name>_to",
 * which the server reads as "from this day" and "to this day" (both included).
 */
export function periodFields(field: FieldDefinition): FieldDefinition[] {
  // one control (a date range: from ~ to); its two values are kept under <name>_from and <name>_to
  return [{ ...field, name: `${field.name}_from`, label: field.label, dateRange: { to: `${field.name}_to` } }];
}

/** What is typed into the conditions, in the form the server stores things in. */
export function storedQuery(fields: readonly DefinedField[], values: FieldValues): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [name, value] of Object.entries(values)) {
    if (!value?.trim()) continue;
    const base = name.replace(/_(from|to)$/, '');
    const kind = fields.find(field => field.name === (name === base ? name : base))?.type;
    out[name] = kind === 'date' ? storeDate(value) : kind === 'time' ? storeTime(value) : value.trim();
  }
  return out;
}

const pad = (value: number) => String(value).padStart(2, '0');
/** The first and last day of a period around today: today | week (Monday to Sunday) | month | year. */
export function periodOf(period: string, now = new Date()): { from: string; to: string } | null {
  const day = (date: Date) => today(date);
  if (period === 'today') return { from: day(now), to: day(now) };
  if (period === 'week') { const monday = new Date(now); monday.setDate(now.getDate() - ((now.getDay() + 6) % 7)); const sunday = new Date(monday); sunday.setDate(monday.getDate() + 6); return { from: day(monday), to: day(sunday) }; }
  if (period === 'month') return { from: `${now.getFullYear()}-${pad(now.getMonth() + 1)}-01`, to: day(new Date(now.getFullYear(), now.getMonth() + 1, 0)) };
  if (period === 'year') return { from: `${now.getFullYear()}-01-01`, to: `${now.getFullYear()}-12-31` };
  return null;
}

/**
 * What the conditions hold when the screen opens: the period the definition asks for, on its first date condition.
 * A screen of work (lines, a status or an auto number) opens on this month unless its definition says otherwise;
 * a screen of basic records opens without a period.
 */
export function openingQuery(definition: EntityDefinition['definition'], dateConditions: readonly string[]): FieldValues {
  const work = Boolean(definition.lines || definition.status || definition.fields.some(field => field.type === 'serial'));
  const period = definition.period ?? (work ? 'month' : 'all');
  const range = periodOf(period);
  if (!range || !dateConditions.length) return {};
  return { [`${dateConditions[0]}_from`]: showDate(range.from), [`${dateConditions[0]}_to`]: showDate(range.to) };
}
