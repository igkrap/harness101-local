import { useEffect, useMemo, useRef, useState, type KeyboardEvent, type MouseEvent, type ReactNode } from 'react';
import { Cell, Column, ColumnHeaderCell, Grid, Regions, RenderMode, SelectionModes, Table2 } from '@blueprintjs/table';
import '@blueprintjs/table/lib/css/table.css';
import './RecordGrid.css';
import { useGridDock } from './toolbarContext';
import { Button, Checkbox, Menu, MenuDivider, MenuItem } from './ui';
import { exportRows, printRows } from './gridExport';
import { showNumber } from './format';
import { apiFetch } from './auth/sessionClient';
import { useProgramCode } from './system/programAccess';

export type GridColumn<T> = { key: keyof T & string; label: string; width?: number; render?: (row: T) => ReactNode; editable?: boolean;
  /** The framework's standard: numbers right; dates, times, common codes and statuses (values of a fixed form) centre; text of any length left (the default). */ align?: 'right' | 'center' };
export type RecordGridProps<T extends Record<string, unknown>> = {
  rows: readonly T[];
  columns: readonly GridColumn<T>[];
  keyField: keyof T & string;
  selection?: 'single' | 'multiple' | 'checkbox-single' | 'checkbox-multiple';
  onSelectionChange?: (rows: T[]) => void;
  onSelect?: (row: T) => void;
  editable?: boolean;
  onRowsChange?: (rows: T[]) => void;
  label?: string;
  /** How many records the conditions match in all. With it the grid shows a count line under itself ("500 / 50,008건"). */
  total?: number;
  /** Bring the next part of the list (shown as "더 보기" while rows are fewer than total). */
  onMore?: () => void | Promise<void>;
  /** The list is only a part: putting it in order is the server's work. Called with the column and direction (null = no order); the grid then shows the rows as given. */
  onSort?: (sort: { key: string; descending: boolean } | null) => void;
  /** What this person's arrangement of the table (hidden columns, order, widths) is kept under. By default the screen's program code and the table's label,
   *  so nothing has to be given; a name when one screen has two tables with the same label; false to keep nothing. */
  settings?: string | false;
};
export type GridSelection = NonNullable<RecordGridProps<Record<string, unknown>>['selection']>;

const CHECK = '__check';
const CHECK_WIDTH = 44;
const ROW_HEIGHT = 24, HEADER_HEIGHT = 26, GUTTER = 0;
// Blueprint never lets a column header be shorter than this (30 by default); the compact grid uses 26.
(Grid as unknown as { MIN_COLUMN_HEADER_HEIGHT: number }).MIN_COLUMN_HEADER_HEIGHT = HEADER_HEIGHT;
const FOCUS_RING = 'inset 0 0 0 2px var(--fw-accent, #2d72d2)';

// Selection is by clicking the row itself (no per-row buttons). editable switches to cell focus with
// checkbox multi-row selection, the usual layout for multi-row editing grids.
export function RecordGrid<T extends Record<string, unknown>>({ rows: source, columns: declared, keyField, selection = 'single', onSelectionChange, onSelect, editable = false, onRowsChange, label = '결과 목록', total, onMore, onSort, settings }: RecordGridProps<T>) {
  const mode: GridSelection = editable ? 'checkbox-multiple' : selection;
  const docked = useGridDock();
  const multi = mode === 'multiple' || mode === 'checkbox-multiple';
  const checkbox = mode === 'checkbox-single' || mode === 'checkbox-multiple';
  const keyOf = (row: T) => String(row[keyField]);
  // View state owned by the grid: the user's column order (drag the header handle) and sort (header menu).
  const [order, setOrder] = useState<string[]>([]);
  const [sort, setSortState] = useState<{ key: string; descending: boolean } | null>(null);
  const [bringing, setBringing] = useState(false);
  const setSort = (next: { key: string; descending: boolean } | null) => { setSortState(next); onSort?.(next); };
  // ... and which columns the person hid and how wide they made them. All three are kept per person and screen, so the table opens the same way next time.
  const [hidden, setHidden] = useState<string[]>([]);
  const [sized, setSized] = useState<Record<string, number>>({});
  const program = useProgramCode();
  const settingsKey = settings === false ? '' : settings ? (program ? `${program}:${settings}` : settings) : program ? `${program}:${label}` : '';
  const loaded = useRef('');
  useEffect(() => {
    if (!settingsKey) return;
    let alive = true;
    void apiFetch(`/api/auth/grids?key=${encodeURIComponent(settingsKey)}`).then(async response => {
      if (!alive) return;
      if (response.ok) { const kept = await response.json() as { order?: string[]; hidden?: string[]; widths?: Record<string, number> }; if (!alive) return; setOrder(kept.order ?? []); setHidden(kept.hidden ?? []); setSized(kept.widths ?? {}); }
      loaded.current = settingsKey;
    }).catch(() => { loaded.current = settingsKey; });
    return () => { alive = false; };
  }, [settingsKey]);
  const arranged = order.length > 0 || hidden.length > 0 || Object.keys(sized).length > 0;
  /** Keep the arrangement (a moment after the last change); with nothing arranged the kept one is removed. */
  const keeping = useRef<ReturnType<typeof setTimeout> | null>(null);
  function keep(next: { order?: string[]; hidden?: string[]; widths?: Record<string, number> }) {
    const all = { order: next.order ?? order, hidden: next.hidden ?? hidden, widths: next.widths ?? sized };
    if (next.order) setOrder(next.order);
    if (next.hidden) setHidden(next.hidden);
    if (next.widths) setSized(next.widths);
    if (!settingsKey || loaded.current !== settingsKey) return;
    if (keeping.current) clearTimeout(keeping.current);
    const empty = !all.order.length && !all.hidden.length && !Object.keys(all.widths).length;
    keeping.current = setTimeout(() => { void (empty ? apiFetch(`/api/auth/grids?key=${encodeURIComponent(settingsKey)}`, { method: 'DELETE' })
      : apiFetch('/api/auth/grids', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ key: settingsKey, settings: all }) })).catch(() => {}); }, 400);
  }
  const known = order.filter(key => declared.some(column => column.key === key));
  const placed = [...known.map(key => declared.find(column => column.key === key)!), ...declared.filter(column => !known.includes(column.key))];
  // A hidden column is out of the table, and so out of what is copied, exported and printed. The last column cannot be hidden.
  const shown = placed.filter(column => !hidden.includes(column.key));
  const columns = (shown.length ? shown : placed.slice(0, 1)).map(column => (sized[column.key] ? { ...column, width: sized[column.key] } : column));
  const rows = useMemo(() => {
    if (!sort || onSort) return source;
    const text = (value: unknown) => value === null || value === undefined ? '' : String(value);
    return [...source].sort((a, b) => {
      const x = a[sort.key], y = b[sort.key];
      const result = typeof x === 'number' && typeof y === 'number' ? x - y : text(x).localeCompare(text(y), 'ko', { numeric: true });
      return sort.descending ? -result : result;
    });
  }, [source, sort, Boolean(onSort)]);   // eslint-disable-line react-hooks/exhaustive-deps
  const [internal, setInternal] = useState<string[]>([]);
  const selected = useMemo(() => new Set(internal), [internal]);
  const [anchor, setAnchor] = useState<number | null>(null);
  const [focus, setFocus] = useState<{ row: number; col: number }>({ row: 0, col: 0 });
  const [editing, setEditing] = useState<{ row: number; col: number; seed?: string } | null>(null);
  const host = useRef<HTMLDivElement>(null);
  // Blueprint makes its table box a tab stop for its own focused cell, which is off here (the cells take focus): inside a grid it is a stray stop.
  useEffect(() => { host.current?.querySelector('.bp6-table-container[tabindex]')?.removeAttribute('tabindex'); });
  const editingRef = useRef(false); // the blur of a committed editor must not commit (and refocus) again

  const dataColumns = columns.map(column => column.key as string);
  const cellColumns = checkbox ? [CHECK, ...dataColumns] : dataColumns;

  function commitSelection(keys: string[], current?: T) {
    setInternal(keys);
    onSelectionChange?.(rows.filter(row => keys.includes(keyOf(row))));
    if (current) onSelect?.(current);
  }
  // Rows replaced by a new query drop selections that no longer exist.
  const rowKeys = rows.map(keyOf).join('\u0000');
  useEffect(() => {
    const present = [...selected].filter(key => rows.some(row => keyOf(row) === key));
    if (present.length !== selected.size) commitSelection(present);
    setFocus(previous => ({ row: Math.min(previous.row, Math.max(rows.length - 1, 0)), col: previous.col }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rowKeys]);

  function toggle(index: number, additive: boolean) {
    const row = rows[index];
    if (!row) return;
    const key = keyOf(row);
    if (!multi) return commitSelection(selected.has(key) && checkbox ? [] : [key], row);
    const next = new Set(additive ? selected : []);
    if (additive && selected.has(key)) next.delete(key); else next.add(key);
    commitSelection([...next], row);
  }
  function selectRange(index: number) {
    const start = anchor ?? index;
    const [from, to] = start < index ? [start, index] : [index, start];
    commitSelection(rows.slice(from, to + 1).map(keyOf), rows[index]);
  }
  function rowClick(event: MouseEvent, index: number) {
    if ((event.target as HTMLElement).closest('input,button,select,textarea')) return;
    setFocus(previous => ({ row: index, col: editable ? previous.col : 0 }));
    if (editable) return; // cells take focus; the checkbox column selects rows
    if (mode === 'multiple' && event.shiftKey) selectRange(index);
    else toggle(index, mode === 'checkbox-multiple' || (mode === 'multiple' && (event.ctrlKey || event.metaKey)));
    if (!event.shiftKey) setAnchor(index);
  }
  // What a cell reads as text (copying, exporting, printing): the rendered words when they are plain, the stored value otherwise.
  const shownText = (column: GridColumn<T>, row: T) => { const drawn = column.render?.(row); return typeof drawn === 'string' || typeof drawn === 'number' ? String(drawn) : String(row[column.key] ?? ''); };
  const shownRows = () => rows.map(row => Object.fromEntries(columns.map(column => [column.key, shownText(column, row)])));
  const rowText = (row: T) => columns.map(column => shownText(column, row)).join('\t');
  function copy(text: string) { void navigator.clipboard?.writeText(text); }
  function copySelection(fallback: number) {
    const picked = rows.filter(row => selected.has(keyOf(row)));
    copy((picked.length ? picked : rows[fallback] ? [rows[fallback]] : []).map(rowText).join('\n'));
  }
  function focusAt(row: number, col: number) {
    const r = Math.max(0, Math.min(rows.length - 1, row)), c = Math.max(0, Math.min(cellColumns.length - 1, col));
    setFocus({ row: r, col: c });
    // Focus right away so a key typed immediately lands on the new cell; retry after render if needed.
    const find = () => host.current?.querySelector<HTMLElement>(editable ? `[data-cell="${r}:${c}"]` : `[data-row-index="${r}"]`);
    const target = find();
    if (target) target.focus(); else requestAnimationFrame(() => find()?.focus());
  }
  function rowKey(event: KeyboardEvent, index: number) {
    if (editable) return;
    const moves: Record<string, number> = { ArrowDown: index + 1, ArrowUp: index - 1, Home: 0, End: rows.length - 1 };
    if (event.key in moves) {
      event.preventDefault();
      const target = Math.max(0, Math.min(rows.length - 1, moves[event.key]));
      focusAt(target, 0);
      if (mode === 'multiple' && event.shiftKey) selectRange(target);
      else if (!checkbox && !(mode === 'multiple' && (event.ctrlKey || event.metaKey))) { toggle(target, false); setAnchor(target); }
    } else if (event.key === ' ' || event.key === 'Enter') {
      event.preventDefault();
      toggle(index, multi);
    } else if (multi && event.key.toLowerCase() === 'a' && (event.ctrlKey || event.metaKey)) {
      event.preventDefault();
      commitSelection(rows.map(keyOf));
    } else if (event.key.toLowerCase() === 'c' && (event.ctrlKey || event.metaKey)) {
      event.preventDefault();
      copySelection(index);
    }
  }
  function cellKey(event: KeyboardEvent, row: number, col: number) {
    if (!editable || editing) return;
    const column = columns.find(item => item.key === cellColumns[col]);
    const moves: Record<string, [number, number]> = { ArrowDown: [row + 1, col], ArrowUp: [row - 1, col], ArrowRight: [row, col + 1], ArrowLeft: [row, col - 1], Home: [row, 0], End: [row, cellColumns.length - 1] };
    if (event.key === 'Tab') { event.preventDefault(); return focusAt(row, col + (event.shiftKey ? -1 : 1)); }
    if (event.key in moves) { event.preventDefault(); return focusAt(...moves[event.key]); }
    if (event.key.toLowerCase() === 'c' && (event.ctrlKey || event.metaKey)) { event.preventDefault(); return column && rows[row] ? copy(shownText(column, rows[row])) : copySelection(row); }
    if (cellColumns[col] === CHECK && (event.key === ' ' || event.key === 'Enter')) { event.preventDefault(); return toggle(row, true); }
    if (!column?.editable) return;
    if (event.key === 'Enter' || event.key === 'F2') { event.preventDefault(); startEdit({ row, col }); }
    else if (event.key.length === 1 && !event.ctrlKey && !event.metaKey) { event.preventDefault(); startEdit({ row, col, seed: event.key }); }
  }
  function startEdit(value: { row: number; col: number; seed?: string }) { editingRef.current = true; setEditing(value); }
  function commitEdit(row: number, col: number, value: string, next?: [number, number]) {
    if (!editingRef.current) return;
    editingRef.current = false;
    const field = cellColumns[col];
    if (rows[row] && String(rows[row][field] ?? '') !== value) onRowsChange?.(source.map(item => keyOf(item) === keyOf(rows[row]) ? { ...item, [field]: value } : item));
    setEditing(null);
    focusAt(...(next ?? [row, col]));
  }

  const allSelected = rows.length > 0 && rows.every(row => selected.has(keyOf(row)));

  function cellContent(column: GridColumn<T>, row: T, r: number, c: number): ReactNode {
    if (editing && editing.row === r && editing.col === c) {
      return <input aria-label={column.label} autoFocus defaultValue={editing.seed ?? String(row[column.key] ?? '')}
        className="fw-grid-input bp6-input bp6-small"
        onBlur={event => commitEdit(r, c, event.currentTarget.value)}
        onKeyDown={event => {
          if (event.key === 'Enter') { event.preventDefault(); commitEdit(r, c, event.currentTarget.value, [r + 1, c]); }
          else if (event.key === 'Tab') { event.preventDefault(); commitEdit(r, c, event.currentTarget.value, [r, c + (event.shiftKey ? -1 : 1)]); }
          else if (event.key === 'Escape') { event.preventDefault(); editingRef.current = false; setEditing(null); focusAt(r, c); }
        }} />;
    }
    const placed = column.align === 'right' ? 'fw-grid-number' : column.align === 'center' ? 'fw-grid-center' : '';
    if (column.render) return placed ? <span className={placed}>{column.render(row)}</span> : column.render(row);
    if (placed) return <span className={placed}>{String(row[column.key] ?? '')}</span>;
    // Numbers line up on the right, as in a ledger.
    return typeof row[column.key] === 'number' ? <span className="fw-grid-number">{showNumber(row[column.key])}</span> : String(row[column.key] ?? '');
  }
  // Fixed widths as given; the other columns share the remaining width (the table needs pixel widths).
  const [hostWidth, setHostWidth] = useState(0);
  const gutter = GUTTER;
  const [headerHeight, setHeaderHeight] = useState(HEADER_HEIGHT);
  useEffect(() => {
    const element = host.current;
    if (!element) return;
    const measure = () => {
      setHostWidth(element.clientWidth);
      const header = element.querySelector<HTMLElement>('.bp6-table-quadrant-top .bp6-table-column-headers');
      if (header?.offsetHeight) setHeaderHeight(header.offsetHeight);
    };
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    measure();
    const frame = requestAnimationFrame(measure);
    return () => { observer.disconnect(); cancelAnimationFrame(frame); };
  }, [rows.length]);
  const fixed = (checkbox ? CHECK_WIDTH : 0) + columns.reduce((sum, column) => sum + (column.width ?? 0), 0);
  const flexible = columns.filter(column => column.width === undefined).length;
  const share = flexible ? Math.max(90, Math.floor((hostWidth - gutter - fixed - 2) / flexible)) : 0;
  const widths = [...(checkbox ? [CHECK_WIDTH] : []), ...columns.map(column => column.width ?? share)];

  // One grid cell. Blueprint's table has no row elements, so every cell carries its row's key and
  // selection state; a row is all cells with the same data-row-key.
  function gridCell(r: number, c: number, content: ReactNode, canEdit: boolean) {
    const row = rows[r];
    if (!row) return <Cell />;
    const isSelected = selected.has(keyOf(row));
    const tabStop = editable ? focus.row === r && focus.col === c : focus.row === r && c === 0;
    const focusedCell = editable && focus.row === r && focus.col === c;
    // (the table draws cells, not rows: each cell stands in a row of its own, so the grid holds rows and the rows hold cells)
    return <Cell className={isSelected ? 'fw-grid-td is-selected' : 'fw-grid-td'}><div role="row" aria-rowindex={r + 2} className="fw-grid-rowbox">
      <div role="gridcell" className="fw-grid-cell" data-row-key={keyOf(row)} data-row-index={r} data-col={c}
        data-cell={editable ? `${r}:${c}` : undefined} aria-selected={isSelected} data-selected={isSelected || undefined}
        tabIndex={tabStop ? 0 : -1} style={{ boxShadow: focusedCell ? FOCUS_RING : undefined }}
        onClick={event => { if (editable) setFocus({ row: r, col: c }); else rowClick(event, r); }}
        onDoubleClick={() => { if (editable && canEdit) startEdit({ row: r, col: c }); }}
        onKeyDown={event => { if (editable) cellKey(event, r, c); else rowKey(event, r); }}>
        {content}
      </div>
    </div></Cell>;
  }

  // Selected rows are drawn as the table's own regions (blue outline over the rows).
  const regions = rows.reduce<[number, number][]>((list, row, index) => {
    if (!selected.has(keyOf(row))) return list;
    const last = list[list.length - 1];
    if (last && last[1] === index - 1) last[1] = index; else list.push([index, index]);
    return list;
  }, []).map(([from, to]) => Regions.row(from, to));
  // Columns move by dragging a header name onto another header (the header row itself, no extra strip).
  const [dragging, setDragging] = useState<string | null>(null);
  const [over, setOver] = useState<string | null>(null);
  function moveColumn(from: string, to: string) {
    const keys = columns.map(column => column.key as string);
    if (from === to || !keys.includes(from) || !keys.includes(to)) return;
    const target = keys.indexOf(to);
    keys.splice(keys.indexOf(from), 1);
    keys.splice(target, 0, from);
    keep({ order: [...keys, ...placed.map(column => column.key as string).filter(key => !keys.includes(key))] });
  }
  const sortClass = (key: string) => sort?.key === key ? (sort.descending ? ' is-sorted-desc' : ' is-sorted-asc') : '';
  const part = total !== undefined && rows.length < total;
  return <><div ref={host} data-ui="record-grid" role="grid" aria-label={label} aria-multiselectable={multi || undefined} aria-rowcount={rows.length}
    data-selection={mode} data-editable={editable || undefined} data-docked={docked || undefined} className={docked ? 'fw-grid is-docked' : 'fw-grid'}
    style={docked ? { minWidth: 0 } : { minWidth: 0, height: headerHeight + Math.max(rows.length, 1) * ROW_HEIGHT + 4 }}>
    {rows.length === 0 && <div role="row" className="fw-grid-empty-row"><div role="gridcell">표시할 자료가 없습니다</div></div>}
    <Table2 numRows={rows.length} columnWidths={widths} defaultRowHeight={ROW_HEIGHT} enableRowHeader={false} enableGhostCells={docked}
      selectionModes={SelectionModes.NONE} renderMode={RenderMode.NONE} enableFocusedCell={false}
      enableColumnResizing onColumnWidthChanged={(index, size) => { const column = columns[index - (checkbox ? 1 : 0)]; if (column) keep({ widths: { ...sized, [column.key]: Math.max(40, Math.round(size)) } }); }}
      selectedRegions={regions} onSelection={() => undefined}
      bodyContextMenuRenderer={context => {
        const target = context.getTarget(), r = target.rows?.[0], c = target.cols?.[0];
        const row = r === undefined || r === null ? undefined : rows[r];
        const column = c === undefined || c === null ? undefined : columns.find(item => item.key === cellColumns[c]);
        const whole = <><MenuItem text="엑셀로 내보내기" disabled={!rows.length} onClick={() => exportRows(label, columns, shownRows())} />
          <MenuItem text="인쇄" disabled={!rows.length} onClick={() => printRows(label, columns, shownRows())} /></>;
        if (!row) return <Menu>{whole}</Menu>;
        const picked = rows.filter(item => selected.has(keyOf(item)));
        return <Menu>
          {column && <MenuItem text="셀 복사" onClick={() => copy(shownText(column, row))} />}
          <MenuItem text="행 복사" onClick={() => copy(rowText(row))} />
          {picked.length > 1 && <MenuItem text={`선택한 ${picked.length}행 복사`} onClick={() => copy(picked.map(rowText).join('\n'))} />}
          <MenuDivider />{whole}
        </Menu>;
      }}
      cellRendererDependencies={[rows, internal, focus, editing, mode, editable, hostWidth, gutter, order, sort, dragging, over, hidden, sized]}>
      {[
        ...(checkbox ? [<Column key={CHECK} columnHeaderCellRenderer={() => <ColumnHeaderCell className="fw-grid-th" enableColumnReordering={false}>
          <div role="row" className="fw-grid-check"><div role="columnheader">{mode === 'checkbox-multiple'
            ? <Checkbox label="전체 선택" hideLabel checked={allSelected} indeterminate={!allSelected && rows.some(row => selected.has(keyOf(row)))}
                onChange={() => commitSelection(allSelected ? [] : rows.map(keyOf))} />
            : <span aria-hidden />}</div></div>
        </ColumnHeaderCell>}
          cellRenderer={r => gridCell(r, 0, rows[r] && <Checkbox label={`${keyOf(rows[r])} 선택`} hideLabel checked={selected.has(keyOf(rows[r]))}
            onChange={() => toggle(r, mode === 'checkbox-multiple')} />, false)} />] : []),
        ...columns.map(column => <Column key={column.key} name={column.label}
          columnHeaderCellRenderer={() => <ColumnHeaderCell name={column.label} selectCellsOnMenuClick={false}
            className={(editable && column.editable ? 'fw-grid-th is-editable' : 'fw-grid-th') + sortClass(column.key) + (over === column.key && dragging && dragging !== column.key ? ' is-drop' : '')}
            nameRenderer={name => <div className="bp6-table-truncated-text fw-grid-name" draggable data-column-key={column.key} title="끌어서 열 순서 바꾸기"
              onDragStart={event => { event.dataTransfer.effectAllowed = 'move'; event.dataTransfer.setData('text/plain', column.key); setDragging(column.key); }}
              onDragOver={event => { if (dragging) { event.preventDefault(); setOver(column.key); } }}
              onDrop={event => { event.preventDefault(); if (dragging) moveColumn(dragging, column.key); setDragging(null); setOver(null); }}
              onDragEnd={() => { setDragging(null); setOver(null); }}>{name}</div>}
            menuRenderer={() => <Menu>
              <MenuItem text="오름차순 정렬" active={sort?.key === column.key && !sort.descending} onClick={() => setSort({ key: column.key, descending: false })} />
              <MenuItem text="내림차순 정렬" active={sort?.key === column.key && sort.descending} onClick={() => setSort({ key: column.key, descending: true })} />
              <MenuItem text="정렬 해제" disabled={sort?.key !== column.key} onClick={() => setSort(null)} />
              <MenuDivider />
              <MenuItem text="이 열 숨기기" disabled={columns.length <= 1} onClick={() => keep({ hidden: [...hidden, column.key] })} />
              <MenuItem text="열 고르기">
                {placed.map(item => <MenuItem key={item.key} text={`${hidden.includes(item.key) ? '\u2003' : '✓'} ${item.label}`} disabled={!hidden.includes(item.key) && columns.length <= 1}
                  onClick={() => keep({ hidden: hidden.includes(item.key) ? hidden.filter(key => key !== item.key) : [...hidden, item.key] })} />)}
              </MenuItem>
              <MenuItem text="열 설정 처음으로" disabled={!arranged} onClick={() => keep({ order: [], hidden: [], widths: {} })} />
            </Menu>} />}
          cellRenderer={r => { const c = cellColumns.indexOf(column.key); return gridCell(r, c, rows[r] ? cellContent(column, rows[r], r, c) : null, Boolean(column.editable)); }} />),
      ]}
    </Table2>
  </div>
  {total !== undefined && <div className="fw-grid-foot" data-ui="grid-count" aria-live="polite">
    <span>{part ? `${showNumber(rows.length)} / ${showNumber(total)}건` : `${showNumber(total)}건`}</span>
    {part && onMore && <Button label={bringing ? '불러오는 중…' : '더 보기'} outlined isDisabled={bringing} isLoading={bringing} onClick={() => { setBringing(true); void Promise.resolve(onMore()).finally(() => setBringing(false)); }} />}
    {part && <span className="fw-grid-foot-note">정렬·엑셀은 전체 자료 기준입니다</span>}
  </div>}</>;
}

/** Tracks edits of an editable grid against the last loaded rows: pass `rows`/`onRowsChange` to RecordGrid, save `changed`. */
export function useEditableRows<T extends Record<string, unknown>>(keyField: keyof T & string) {
  const [baseline, setBaseline] = useState<readonly T[]>([]);
  const [rows, setRows] = useState<readonly T[]>([]);
  const changed = rows.filter(row => {
    const before = baseline.find(item => String(item[keyField]) === String(row[keyField]));
    return !before || Object.keys(row).some(key => String(row[key] ?? '') !== String(before[key] ?? ''));
  });
  return {
    rows, changed, isDirty: changed.length > 0,
    onRowsChange: (next: T[]) => setRows(next),
    load: (next: readonly T[]) => { setBaseline(next); setRows(next); },
  };
}
