/**
 * How a value reads, the same on every screen, in print and in exported files.
 *   number     1,234,567 / -1,234.5   thousands separators, right-aligned; decimals as stored (computed values: two places)
 *   percentage 45.0%                  always one decimal place
 *   date       2026/11/14             centred (stored as 2026-11-14); a month reads 2026/11
 *   date-time  2026/11/14 09:05:07    centred, in the viewer's local time
 *   time       09:05:07               centred (typed as 0905, 9:05 or 09:05:07)
 *   yes/no     예 / 아니오             centred
 *   common code, status               centred (values of a fixed form)
 *   text, auto number, "code name" of another screen's record: left
 *   nothing    an empty cell (never '-', 'null' or 0)
 * Screens call these instead of toLocaleString and the like, so nothing depends on the browser's language.
 */
const text = (value: unknown) => (value === null || value === undefined ? '' : String(value));
const pad = (number: number) => String(number).padStart(2, '0');
const NUMBER = /^-?\d+(\.\d+)?$/;

/** What was typed as a number, as it is stored: '1,500 ' -> '1500' (anything else is left for validation to refuse). */
export function readNumber(typed: string): string { return typed.replace(/[,\s]/g, ''); }
/** A number as it reads: 1,234,567.5. Something that is not a number is shown as it is; nothing is an empty string. */
export function showNumber(value: unknown, digits = 6, /** Always that many places (1,500.00), for a field with set decimal places. */ fixed = false): string {
  if (value === null || value === undefined || value === '') return '';
  const number = typeof value === 'number' ? value : NUMBER.test(readNumber(String(value))) ? Number(readNumber(String(value))) : NaN;
  if (!Number.isFinite(number)) return text(value);
  const shown = number.toLocaleString('en-US', { minimumFractionDigits: fixed ? digits : 0, maximumFractionDigits: digits });
  return /^-0(\.0*)?$/.test(shown) ? shown.slice(1) : shown;
}
/** A computed number (a sum, an average, a formula): at most two decimal places. */
export function showAmount(value: unknown): string { return showNumber(value, 2); }
/** A rate or a share: 45.0% */
export function showPercent(value: unknown): string {
  return typeof value === 'number' && Number.isFinite(value) ? `${value.toLocaleString('en-US', { minimumFractionDigits: 1, maximumFractionDigits: 1 })}%` : '';
}

/** How a date reads everywhere: 2026/11/14 (stored as 2026-11-14). Month groups read 2026/11. */
export function showDate(value: unknown): string { return text(value).replace(/^(\d{4})-(\d{2})(?:-(\d{2}))?$/, (_, year, month, day) => (day ? `${year}/${month}/${day}` : `${year}/${month}`)); }
/** What a person typed as a date, as it is stored: 2026/11/14, 2026.11.14, 20261114 or 2026-11-14 -> 2026-11-14 (anything else is left for the server to refuse). */
export function storeDate(value: string): string {
  const raw = value.trim().replace(/[./]/g, '-');
  const packed = /^(\d{4})(\d{2})(\d{2})$/.exec(raw);
  if (packed) return `${packed[1]}-${packed[2]}-${packed[3]}`;
  const parts = /^(\d{4})-(\d{1,2})-(\d{1,2})$/.exec(raw);
  return parts ? `${parts[1]}-${parts[2].padStart(2, '0')}-${parts[3].padStart(2, '0')}` : value.trim();
}
/** Is this something storeDate understands, and a day that exists? */
export function isDate(value: string): boolean {
  const stored = /^(\d{4})-(\d{2})-(\d{2})$/.exec(storeDate(value));
  if (!stored) return false;
  const date = new Date(Number(stored[1]), Number(stored[2]) - 1, Number(stored[3]));
  return date.getMonth() === Number(stored[2]) - 1 && date.getDate() === Number(stored[3]);
}

/** A moment from the server (UTC, with or without a Z) or a Date, as a local Date. */
function moment(value: unknown): Date | null {
  if (value instanceof Date) return value;
  const raw = text(value);
  if (!raw) return null;
  const date = new Date(/[zZ]|[+-]\d{2}:?\d{2}$/.test(raw) ? raw : raw.replace(' ', 'T') + 'Z');
  return Number.isNaN(date.getTime()) ? null : date;
}
/** A moment as it reads everywhere, in the viewer's local time: 2026/11/14 09:05:07. */
export function formatDateTime(value: unknown): string {
  const date = moment(value);
  return date ? `${date.getFullYear()}/${pad(date.getMonth() + 1)}/${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}` : text(value);
}
/** The time of a moment: 09:05:07. */
export function showTime(value: unknown): string {
  const date = moment(value);
  return date ? `${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}` : text(value);
}
/** What a person typed as a time, as it is stored: 0930, 9:30, 093015 or 09:30:15 -> 09:30:00 (anything else is left for the server to refuse). */
export function storeTime(value: string): string {
  const raw = value.trim(), found = /^(\d{1,2}):(\d{1,2})(?::(\d{1,2}))?$/.exec(raw) ?? /^(\d{2})(\d{2})(\d{2})?$/.exec(raw);
  if (!found) return raw;
  const [hour, minute, second] = [Number(found[1]), Number(found[2]), Number(found[3] ?? 0)];
  return hour > 23 || minute > 59 || second > 59 ? raw : `${pad(hour)}:${pad(minute)}:${pad(second)}`;
}
/** Is this something storeTime understands? */
export function isTime(value: string): boolean { return /^\d{2}:\d{2}:\d{2}$/.test(storeTime(value)); }
/** A yes/no as it reads: 예 or 아니오 (nothing is a no). */
export function showYesNo(value: unknown): string { return value === true || value === 'true' ? '예' : '아니오'; }
/** Today as it is stored (2026-11-14), in the viewer's local time. */
export function today(date = new Date()): string { return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`; }

export type Align = 'right' | 'center' | undefined;
/** Where a value of this kind sits in a table: numbers right; dates, times, common codes and statuses centre; the rest left. */
export function alignOf(type: string | null | undefined): Align {
  return type === 'number' ? 'right' : type === 'date' || type === 'datetime' || type === 'time' || type === 'yesno' || type === 'code' || type === 'status' ? 'center' : undefined;
}
/** A stored value of this kind as it reads (numbers and dates; the rest as it is). */
export function showValue(type: string | null | undefined, value: unknown): string {
  return type === 'number' ? showNumber(value) : type === 'date' ? showDate(value) : type === 'datetime' ? formatDateTime(value) : type === 'yesno' ? showYesNo(value) : text(value);
}
