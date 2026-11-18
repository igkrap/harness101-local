/**
 * One record on paper: a heading, approval boxes, the record's values in a two-column table, its lines with the
 * totals under them, and a closing note. What goes where comes from the definition; this only lays it out.
 */
import { formatDateTime } from '../format';

export type PrintForm = {
  /** The form's heading, e.g. '견 적 서'. */ title: string;
  /** The record's number, shown under the heading. */ number?: { label: string; value: string };
  status?: string;
  /** Label and value of each field above the lines. */ pairs: { label: string; value: string }[];
  lines?: { label: string; columns: { label: string; /** Numbers right, dates and codes centre. */ align?: 'right' | 'center' }[]; rows: string[][] };
  /** Computed values under the lines (totals). */ totals: { label: string; value: string }[];
  /** Approval boxes, e.g. ['담당', '검토', '승인']. */ signers: string[];
  note?: string;
  /** Printed at the foot: who made it and when. */ foot?: string;
  /** The company's logo (an image address) above the heading. */ logo?: string;
  /** The two sides of the paper, each a small table of label and value: who supplies (the company itself) and who receives. */
  parties?: { title: string; rows: { label: string; value: string }[] }[];
};

const escape = (value: unknown) => String(value ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

/** The whole page as HTML (kept apart from printing so it can be shown or checked without a printer). */
export function recordFormHtml(form: PrintForm): string {
  const pairRows: string[] = [];
  for (let index = 0; index < form.pairs.length; index += 2) {
    const [first, second] = [form.pairs[index], form.pairs[index + 1]];
    pairRows.push(`<tr><th>${escape(first.label)}</th><td${second ? '' : ' colspan="3"'}>${escape(first.value)}</td>${second ? `<th>${escape(second.label)}</th><td>${escape(second.value)}</td>` : ''}</tr>`);
  }
  const lines = form.lines ? `<h2>${escape(form.lines.label)}</h2><table class="lines"><thead><tr><th class="no">No</th>${form.lines.columns.map(column => `<th>${escape(column.label)}</th>`).join('')}</tr></thead>
    <tbody>${form.lines.rows.map((row, index) => `<tr><td class="no">${index + 1}</td>${row.map((cell, at) => `<td${form.lines!.columns[at]?.align === 'right' ? ' class="num"' : form.lines!.columns[at]?.align === 'center' ? ' class="mid"' : ''}>${escape(cell)}</td>`).join('')}</tr>`).join('')}</tbody></table>` : '';
  const totals = form.totals.length ? `<table class="totals"><tbody>${form.totals.map(total => `<tr><th>${escape(total.label)}</th><td class="num">${escape(total.value)}</td></tr>`).join('')}</tbody></table>` : '';
  const signers = form.signers.length ? `<table class="sign"><tbody><tr>${form.signers.map(name => `<th>${escape(name)}</th>`).join('')}</tr><tr>${form.signers.map(() => '<td></td>').join('')}</tr></tbody></table>` : '';
  const parties = form.parties?.length ? `<div class="parties">${form.parties.map(party => `<table class="party"><tbody>${party.rows.map((row, index) =>
    `<tr>${index === 0 ? `<th class="side" rowspan="${party.rows.length}">${escape(party.title)}</th>` : ''}<th>${escape(row.label)}</th><td>${escape(row.value)}</td></tr>`).join('')}</tbody></table>`).join('')}</div>` : '';
  return `<!doctype html><html><head><meta charset="utf-8"><title>${escape(form.title)}</title><style>
    @page{size:A4;margin:14mm}
    body{font:12px/1.5 -apple-system,"Malgun Gothic","Apple SD Gothic Neo",sans-serif;margin:0;color:#111}
    .sheet{max-width:182mm;margin:0 auto;padding:4mm 0}
    .top{display:flex;align-items:flex-end;justify-content:space-between;gap:12px;margin-bottom:10px;min-height:22mm}
    h1{font-size:24px;letter-spacing:.35em;margin:0;font-weight:700;flex:1;text-align:center;padding-left:.35em}
    .meta{font-size:12px;color:#333;margin:0 0 8px;display:flex;justify-content:space-between}
    h2{font-size:12px;margin:12px 0 4px}
    table{border-collapse:collapse;width:100%}
    th,td{border:1px solid #555;padding:4px 7px;text-align:left;vertical-align:middle}
    th{background:#eef0f2;font-weight:600;white-space:nowrap}
    .head th{width:16%} .head td{width:34%;white-space:pre-wrap}
    .lines th{text-align:center} .lines thead{display:table-header-group} .lines tr{page-break-inside:avoid}
    .no{width:34px;text-align:center} .num{text-align:right;font-variant-numeric:tabular-nums} .mid{text-align:center;font-variant-numeric:tabular-nums}
    .totals{width:46%;margin:6px 0 0 auto} .totals th{width:40%} .totals td{font-weight:700}
    .sign{width:auto;flex:none} .sign th{text-align:center;padding:2px 0;width:19mm;font-size:11px} .sign td{height:15mm}
    .logo{max-height:14mm;max-width:40mm;display:block;margin:0 0 4px}
    .parties{display:flex;gap:8px;margin:0 0 8px} .party{flex:1} .party th{width:22%} .party .side{width:7mm;text-align:center;writing-mode:vertical-rl;letter-spacing:.3em;padding:2px}
    .note{margin:14px 0 0;white-space:pre-wrap} .foot{margin-top:18px;font-size:10px;color:#666;display:flex;justify-content:space-between}
  </style></head><body><div class="sheet">
    <div class="top"><div style="width:${form.signers.length * 19}mm">${form.logo ? `<img class="logo" src="${escape(form.logo)}" alt="">` : ''}</div><h1>${escape(form.title)}</h1>${signers}</div>
    <p class="meta"><span>${form.number ? `${escape(form.number.label)}: <b>${escape(form.number.value)}</b>` : ''}</span><span>${form.status ? `상태: ${escape(form.status)}` : ''}</span></p>
    ${parties}
    ${pairRows.length ? `<table class="head"><tbody>${pairRows.join('')}</tbody></table>` : ''}
    ${lines}${totals}
    ${form.note ? `<p class="note">${escape(form.note)}</p>` : ''}
    ${form.foot ? `<p class="foot"><span>${escape(form.foot)}</span><span>${formatDateTime(new Date())} 출력</span></p>` : ''}
  </div></body></html>`;
}

/** Send the form to the printer (the browser's print window; "PDF로 저장" there makes a file). */
export function printRecord(form: PrintForm) {
  const frame = document.createElement('iframe');
  frame.setAttribute('aria-hidden', 'true');
  frame.dataset.ui = 'print-form';
  frame.style.cssText = 'position:fixed;right:0;bottom:0;width:0;height:0;border:0';
  document.body.appendChild(frame);
  const page = frame.contentDocument;
  if (!page) { frame.remove(); return; }
  page.open();
  page.write(recordFormHtml(form));
  page.close();
  frame.contentWindow?.addEventListener('afterprint', () => setTimeout(() => frame.remove(), 500));
  setTimeout(() => { frame.contentWindow?.focus(); frame.contentWindow?.print(); }, 50);
}
