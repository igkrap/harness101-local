/**
 * Excel files (.xlsx) written and read in the browser: one sheet of rows, nothing more. A workbook is a zip of a few
 * XML parts; fflate does the zip. Numbers are written as numbers (so the sheet can add them up), everything else as text;
 * the first row is bold and the columns are wide enough to read. Reading takes the first sheet and gives back text cells -
 * a date cell as 2026-11-14, a number without its display format - which is what the import dialog checks row by row.
 */
import { strFromU8, strToU8, unzipSync, zipSync } from 'fflate';

const escape = (text: string) => text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f]/g, '');
const column = (index: number) => { let name = ''; for (let at = index + 1; at > 0; at = Math.floor((at - 1) / 26)) name = String.fromCharCode(65 + ((at - 1) % 26)) + name; return name; };
const NUMBER = /^-?\d+(\.\d+)?$/;

/** The bytes of a workbook holding these rows (the first row is the heading). `numeric` says which columns hold numbers. */
export function writeSheet(rows: readonly (readonly string[])[], numeric: readonly boolean[] = [], sheetName = 'Sheet1'): Uint8Array {
  const widths = (rows[0] ?? []).map((_, at) => Math.min(60, Math.max(8, ...rows.slice(0, 200).map(row => [...(row[at] ?? '')].reduce((sum, letter) => sum + (letter.charCodeAt(0) > 255 ? 2 : 1), 0) + 2))));
  const body = rows.map((row, r) => `<row r="${r + 1}">` + row.map((value, c) => {
    const at = `${column(c)}${r + 1}`, text = value ?? '';
    if (r > 0 && numeric[c] && NUMBER.test(text.replace(/,/g, ''))) return `<c r="${at}" s="2"><v>${text.replace(/,/g, '')}</v></c>`;
    return text === '' ? '' : `<c r="${at}" t="inlineStr"${r === 0 ? ' s="1"' : ''}><is><t xml:space="preserve">${escape(text)}</t></is></c>`;
  }).join('') + '</row>').join('');
  const sheet = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">`
    + `<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>`
    + `<cols>${widths.map((width, at) => `<col min="${at + 1}" max="${at + 1}" width="${width}" customWidth="1"/>`).join('')}</cols><sheetData>${body}</sheetData></worksheet>`;
  const styles = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">`
    + `<fonts count="2"><font><sz val="11"/><name val="맑은 고딕"/></font><font><b/><sz val="11"/><name val="맑은 고딕"/></font></fonts>`
    + `<fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill><fill><patternFill patternType="solid"><fgColor rgb="FFEEF0F2"/></patternFill></fill></fills>`
    + `<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders><cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>`
    + `<cellXfs count="3"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/><xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1"><alignment horizontal="center"/></xf>`
    + `<xf numFmtId="3" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/></cellXfs></styleSheet>`;
  const name = escape(sheetName.replace(/[\\/*?:[\]]/g, ' ').slice(0, 31) || 'Sheet1');
  return zipSync({
    '[Content_Types].xml': strToU8(`<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/></Types>`),
    '_rels/.rels': strToU8(`<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>`),
    'xl/workbook.xml': strToU8(`<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="${name}" sheetId="1" r:id="rId1"/></sheets></workbook>`),
    'xl/_rels/workbook.xml.rels': strToU8(`<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>`),
    'xl/worksheets/sheet1.xml': strToU8(sheet), 'xl/styles.xml': strToU8(styles),
  });
}

/** Offer the rows as a file: <name>.xlsx. */
export function downloadSheet(fileName: string, rows: readonly (readonly string[])[], numeric: readonly boolean[] = []) {
  const blob = new Blob([writeSheet(rows, numeric, fileName) as BlobPart], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' });
  const link = document.createElement('a');
  link.href = URL.createObjectURL(blob); link.download = `${fileName.replace(/[\\/:*?"<>|]/g, '_') || '목록'}.xlsx`;
  document.body.appendChild(link); link.click(); link.remove();
  setTimeout(() => URL.revokeObjectURL(link.href), 1000);
}

// Number formats that mean a date (built-in ids, and custom ones that speak of years, months or days).
const DATE_FORMATS = new Set([14, 15, 16, 17, 18, 19, 20, 21, 22, 27, 28, 29, 30, 31, 32, 33, 34, 35, 36, 45, 46, 47, 50, 51, 52, 53, 54, 55, 56, 57, 58]);
const pad = (value: number) => String(value).padStart(2, '0');
function serialDate(serial: number): string {
  const whole = Math.floor(serial), date = new Date(Date.UTC(1899, 11, 30) + whole * 86400000);
  const day = `${date.getUTCFullYear()}-${pad(date.getUTCMonth() + 1)}-${pad(date.getUTCDate())}`, rest = Math.round((serial - whole) * 86400);
  if (whole === 0) return `${pad(Math.floor(rest / 3600))}:${pad(Math.floor(rest / 60) % 60)}:${pad(rest % 60)}`;       // a time of day only
  return rest ? `${day} ${pad(Math.floor(rest / 3600))}:${pad(Math.floor(rest / 60) % 60)}:${pad(rest % 60)}` : day;
}

/** The first sheet of a workbook as rows of text. Empty rows are left out. */
export function readSheet(bytes: Uint8Array): string[][] {
  const parts = unzipSync(bytes), xml = (name: string) => (parts[name] ? new DOMParser().parseFromString(strFromU8(parts[name]), 'application/xml') : null);
  const workbook = xml('xl/workbook.xml'), links = xml('xl/_rels/workbook.xml.rels');
  let path = 'xl/worksheets/sheet1.xml';
  const first = workbook?.getElementsByTagName('sheet')[0]?.getAttribute('r:id');
  for (const link of Array.from(links?.getElementsByTagName('Relationship') ?? [])) if (link.getAttribute('Id') === first) { const target = link.getAttribute('Target') ?? ''; path = target.startsWith('/') ? target.slice(1) : `xl/${target}`; }
  const sheet = xml(path);
  if (!sheet) throw new Error('엑셀 파일에서 시트를 찾지 못했습니다.');
  const shared = Array.from(xml('xl/sharedStrings.xml')?.getElementsByTagName('si') ?? []).map(item => Array.from(item.getElementsByTagName('t')).map(text => text.textContent ?? '').join(''));
  const styles = xml('xl/styles.xml');
  const custom = new Map(Array.from(styles?.getElementsByTagName('numFmt') ?? []).map(format => [Number(format.getAttribute('numFmtId')), format.getAttribute('formatCode') ?? '']));
  const dated = Array.from(styles?.getElementsByTagName('cellXfs')[0]?.getElementsByTagName('xf') ?? []).map(style => { const id = Number(style.getAttribute('numFmtId') ?? 0);
    return DATE_FORMATS.has(id) || /[ymdh]/i.test((custom.get(id) ?? '').replace(/"[^"]*"|\[[^\]]*\]/g, '')); });
  const rows: string[][] = [];
  for (const row of Array.from(sheet.getElementsByTagName('row'))) {
    const cells: string[] = [];
    for (const cell of Array.from(row.getElementsByTagName('c'))) {
      const letters = (cell.getAttribute('r') ?? '').replace(/\d/g, ''), at = [...letters].reduce((sum, letter) => sum * 26 + letter.charCodeAt(0) - 64, 0) - 1;
      const kind = cell.getAttribute('t'), raw = cell.getElementsByTagName('v')[0]?.textContent ?? '';
      let value = kind === 's' ? shared[Number(raw)] ?? '' : kind === 'inlineStr' ? Array.from(cell.getElementsByTagName('t')).map(text => text.textContent ?? '').join('') : kind === 'b' ? (raw === '1' ? '예' : '아니오') : raw;
      if (!kind && raw !== '' && dated[Number(cell.getAttribute('s') ?? 0)] && NUMBER.test(raw)) value = serialDate(Number(raw));
      else if (!kind && /^-?\d+\.\d{7,}$/.test(raw)) value = String(Number(Number(raw).toFixed(6)));       // 0.1 + 0.2 as the sheet stores it
      cells[at >= 0 ? at : cells.length] = value;
    }
    const filled = Array.from(cells, value => value ?? '');
    if (filled.some(value => value.trim() !== '')) rows.push(filled);
  }
  return rows;
}
