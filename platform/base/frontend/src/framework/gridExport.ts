/** Rows of a grid as a file for Excel, or on paper. Used by RecordGrid's right-click menu and by toolbar actions. */
import { formatDateTime } from './format';
import { downloadSheet } from './xlsx';

export type ExportColumn = { key: string; label: string; /** Where its values sit on paper (numbers right, values of a fixed form centre). */ align?: 'right' | 'center' };
type Row = Record<string, unknown>;
const text = (value: unknown) => value === null || value === undefined ? '' : String(value);

/** Download the rows as an Excel file (.xlsx): what the cells read, numbers as numbers so the sheet can add them up. */
export function exportRows(title: string, columns: readonly ExportColumn[], rows: readonly Row[]) {
  const stamp = formatDateTime(new Date()).slice(0, 10).replace(/\//g, '');
  downloadSheet(`${title || '목록'}_${stamp}`, [columns.map(column => column.label), ...rows.map(row => columns.map(column => text(row[column.key])))], columns.map(column => column.align === 'right'));
}

/** Print the rows as a plain table (all rows, not just the ones on screen). */
export function printRows(title: string, columns: readonly ExportColumn[], rows: readonly Row[]) {
  const escape = (value: unknown) => text(value).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  const frame = document.createElement('iframe');
  frame.setAttribute('aria-hidden', 'true');
  frame.style.cssText = 'position:fixed;right:0;bottom:0;width:0;height:0;border:0';
  document.body.appendChild(frame);
  const page = frame.contentDocument;
  if (!page) { frame.remove(); return; }
  page.open();
  page.write(`<!doctype html><html><head><meta charset="utf-8"><title>${escape(title)}</title><style>
    body{font:12px/1.4 -apple-system,"Malgun Gothic",sans-serif;margin:16px;color:#111}
    h1{font-size:16px;margin:0 0 4px} p{margin:0 0 10px;color:#555;font-size:11px}
    table{width:100%;border-collapse:collapse} th,td{border:1px solid #999;padding:4px 6px;text-align:left}
    th{background:#eee;text-align:center} thead{display:table-header-group} tr{page-break-inside:avoid}
    .r{text-align:right;font-variant-numeric:tabular-nums} .c{text-align:center;font-variant-numeric:tabular-nums}
  </style></head><body><h1>${escape(title)}</h1><p>${formatDateTime(new Date())} 출력 · ${rows.length.toLocaleString('en-US')}건</p>
  <table><thead><tr>${columns.map(column => `<th>${escape(column.label)}</th>`).join('')}</tr></thead>
  <tbody>${rows.map(row => `<tr>${columns.map(column => `<td${column.align === 'right' ? ' class="r"' : column.align === 'center' ? ' class="c"' : ''}>${escape(row[column.key])}</td>`).join('')}</tr>`).join('')}</tbody></table></body></html>`);
  page.close();
  const done = () => setTimeout(() => frame.remove(), 500);
  frame.contentWindow?.addEventListener('afterprint', done);
  setTimeout(() => { frame.contentWindow?.focus(); frame.contentWindow?.print(); }, 50);
}

export { formatDateTime, showDate, storeDate, isDate } from './format';
