/**
 * Choosing one of many (a common code, a record of another screen), three ways:
 *   dropdown  the plain list - for a handful of choices
 *   search    type and the matching choices appear under the box - no window
 *   popup     the same box plus a search window (magnifier or F2) with several columns; typing and pressing
 *             Enter fills the box at once when one choice matches, and opens the window on the matches otherwise
 * Part of the design-system boundary: the only other file that imports Blueprint.
 */
import { useEffect, useId, useMemo, useRef, useState, type JSX, type KeyboardEvent } from 'react';
import { Button, Dialog, DialogBody, DialogFooter, FormGroup, HTMLSelect, InputGroup, Menu, MenuItem, Popover } from '@blueprintjs/core';

export type PickMode = 'dropdown' | 'search' | 'popup';
export type PickOption = { value: string; label: string; /** Its code, shown before the name ('V-001 한빛상사'). */ code?: string;
  /** The whole record, for the columns of the search window. */ row?: Record<string, unknown> };
export type PickColumn = { key: string; label: string; /** Shown text for a stored value (numbers, dates, codes, other records). */ text?: (value: unknown) => string;
  /** Numbers right, values of a fixed form centre. */ align?: 'right' | 'center' };
export type PickerProps = { label: string; hideLabel?: boolean; isRequired?: boolean; isDisabled?: boolean; mode?: PickMode;
  value: string; onChange: (value: string) => void; options: readonly PickOption[];
  /** Columns of the search window (popup); without them only the name is listed. */ columns?: readonly PickColumn[];
  /** Title of the search window, e.g. '거래처 찾기'. */ title?: string;
  /** When the options are only a part of what can be chosen: asks for the choices matching what was typed (they are then searched there, not in `options`). */
  search?: (typed: string) => Promise<readonly PickOption[]>;
  /** The business-program layout: a box for the code (typed into) and, beside it, the name (read only). In a table cell (hideLabel) one box shows both. */ split?: boolean };

const shown = (value: unknown) => (value === null || value === undefined ? '' : String(value));
const LIMIT = 30;

export function Picker({ label, hideLabel, isRequired, isDisabled, mode = 'dropdown', value, onChange, options, columns, title, split, search }: PickerProps) {
  const id = useId();
  const current = options.find(option => option.value === value);
  // A stored value whose choice is gone still shows, so old records stay readable.
  const both = (option: PickOption) => [option.code, option.label].filter(Boolean).join(' ');
  const twoBoxes = Boolean(split) && !hideLabel;
  const currentLabel = current ? (twoBoxes ? current.code ?? '' : both(current)) : value;
  const [text, setText] = useState<string | null>(null);   // null: not typing, the box shows the chosen name
  const [open, setOpen] = useState(false);
  const [at, setAt] = useState(0);
  const [windowOpen, setWindowOpen] = useState(false);
  const [filter, setFilter] = useState('');
  const [marked, setMarked] = useState(0);
  const filterInput = useRef<HTMLInputElement>(null);
  const moved = useRef(false);   // the arrow keys picked a candidate (so Enter means that one, even with nothing typed)

  const wordsOf = (option: PickOption) => [option.code ?? '', option.label, ...(columns ?? []).map(column => (column.text ?? shown)(option.row?.[column.key]))].join(' ').toLowerCase();
  const match = (query: string) => { const needle = query.trim().toLowerCase(); return needle ? options.filter(option => wordsOf(option).includes(needle)) : [...options]; };
  // Asked of the server (search) when something is typed; what the screen holds otherwise.
  const [found, setFound] = useState<{ typed: string; list: readonly PickOption[] } | null>(null);
  const [foundList, setFoundList] = useState<{ typed: string; list: readonly PickOption[] } | null>(null);
  const asked = useRef(0);
  useEffect(() => {
    const typed = (text ?? '').trim();
    if (!search || !typed) { setFound(null); return; }
    const turn = ++asked.current, timer = setTimeout(() => { void search(typed).then(list => { if (turn === asked.current) setFound({ typed, list }); }).catch(() => {}); }, 180);
    return () => clearTimeout(timer);
  }, [text, Boolean(search)]);   // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    const typed = filter.trim();
    if (!search || !typed || !windowOpen) { setFoundList(null); return; }
    let alive = true;
    const timer = setTimeout(() => { void search(typed).then(list => { if (alive) setFoundList({ typed, list }); }).catch(() => {}); }, 180);
    return () => { alive = false; clearTimeout(timer); };
  }, [filter, windowOpen, Boolean(search)]);   // eslint-disable-line react-hooks/exhaustive-deps
  const candidates = useMemo(() => (search && (text ?? '').trim() ? (found?.typed === (text ?? '').trim() ? [...found.list] : []) : match(text ?? '')), [text, options, found]);   // eslint-disable-line react-hooks/exhaustive-deps
  const listed = useMemo(() => (search && filter.trim() ? (foundList?.typed === filter.trim() ? [...foundList.list] : []) : match(filter)), [filter, options, windowOpen, foundList]);   // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { setAt(0); moved.current = false; }, [text]);
  useEffect(() => { setMarked(0); }, [filter]);
  useEffect(() => { if (windowOpen) requestAnimationFrame(() => filterInput.current?.focus()); }, [windowOpen]);

  const wrap = (control: JSX.Element) => hideLabel ? control
    : <FormGroup label={label} labelFor={id} labelInfo={isRequired ? '*' : undefined} disabled={isDisabled} className="fw-field">{control}</FormGroup>;

  if (mode === 'dropdown') {
    const list = [{ value: '', label: '선택' }, ...options.map(option => ({ value: option.value, label: both(option) })),
      ...(value && !current ? [{ value, label: value }] : [])];
    return wrap(<HTMLSelect id={id} fill value={value} disabled={isDisabled} aria-label={hideLabel ? label : undefined}
      onChange={event => onChange(event.currentTarget.value)} options={list} />);
  }

  const choose = (option: PickOption | null) => { onChange(option?.value ?? ''); setText(null); setOpen(false); setWindowOpen(false); };
  const openWindow = (query: string) => { setFilter(query); setOpen(false); setText(null); setWindowOpen(true); };
  function keys(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === 'F2' && mode === 'popup') { event.preventDefault(); openWindow(text ?? ''); return; }
    if (event.key === 'ArrowDown') { event.preventDefault(); if (!open) { setText(text ?? ''); setOpen(true); } else setAt(index => Math.min(index + 1, Math.min(candidates.length, LIMIT) - 1)); requestAnimationFrame(() => { moved.current = true; }); return; }
    if (event.key === 'ArrowUp') { event.preventDefault(); setAt(index => Math.max(index - 1, 0)); moved.current = true; return; }
    if (event.key === 'Escape' && (open || text !== null)) { event.preventDefault(); event.stopPropagation(); setText(null); setOpen(false); return; }
    if (event.key !== 'Enter') return;
    if (text === null && !open) return;                 // nothing typed: Enter keeps its usual meaning
    event.preventDefault();
    if ((text ?? '').trim() === '' && !moved.current) { choose(null); return; }
    const typed = (text ?? '').trim();
    if (search && typed && found?.typed !== typed) {     // the answer for what was typed has not come yet: ask now and decide on it
      asked.current++;
      void search(typed).then(list => { if (list.length === 1 || mode !== 'popup') { if (list[0]) choose(list[0]); } else openWindow(typed); }).catch(() => {});
      return;
    }
    // The window's habit: one match fills at once; several open the window on them.
    if (mode === 'popup' && candidates.length !== 1 && !moved.current) { openWindow(text ?? ''); return; }
    if (candidates[at]) choose(candidates[at]);
  }
  function leave() {
    // Leaving the box with half-typed text: an emptied box clears the value, anything else is put back.
    if (text !== null && text.trim() === '' && value) onChange('');
    setText(null); setOpen(false);
  }

  const menu = <Menu className="fw-pick-menu" role="listbox">
    {candidates.slice(0, LIMIT).map((option, index) => <MenuItem key={option.value} role="option" text={option.label} active={index === at} selected={option.value === value}
      label={option.code || undefined}
      onMouseDown={event => event.preventDefault()} onClick={() => choose(option)} />)}
    {candidates.length === 0 && <MenuItem disabled text="맞는 것이 없습니다" />}
    {candidates.length > LIMIT && <MenuItem disabled text={`… ${candidates.length - LIMIT}건 더 있습니다. 더 입력해 좁히세요.`} />}
  </Menu>;
  const box = <Popover isOpen={open && !isDisabled} content={menu} placement="bottom-start" minimal autoFocus={false} enforceFocus={false} matchTargetWidth
    onInteraction={next => { if (!next) setOpen(false); }} fill>
    <InputGroup id={id} fill size="small" role="combobox" aria-expanded={open} aria-label={hideLabel ? label : undefined} disabled={isDisabled} autoComplete="off"
      placeholder={twoBoxes ? '코드·이름' : mode === 'popup' ? '입력 후 Enter, 또는 F2' : '입력하여 찾기'} value={text ?? currentLabel}
      onValueChange={next => { setText(next); setOpen(true); }} onFocus={event => event.currentTarget.select()} onBlur={leave} onKeyDown={keys}
      rightElement={mode === 'popup'
        ? <Button variant="minimal" size="small" icon="search" aria-label={`${label} 찾기`} title={`${label} 찾기 (F2)`} disabled={isDisabled} onMouseDown={event => event.preventDefault()} onClick={() => openWindow(text ?? '')} />
        : undefined} />
  </Popover>;

  const windowColumns: readonly PickColumn[] = columns?.length ? columns : [{ key: '__label', label }];
  const cell = (option: PickOption, column: PickColumn) => column.key === '__label' ? option.label : (column.text ?? shown)(option.row?.[column.key]);
  function windowKeys(event: KeyboardEvent<HTMLElement>) {
    if (event.key === 'ArrowDown') { event.preventDefault(); setMarked(index => Math.min(index + 1, listed.length - 1)); }
    else if (event.key === 'ArrowUp') { event.preventDefault(); setMarked(index => Math.max(index - 1, 0)); }
    else if (event.key === 'Enter') { event.preventDefault(); if (listed[marked]) choose(listed[marked]); }
  }
  return <>
    {wrap(twoBoxes ? <div className="fw-pick-split">{box}<InputGroup fill size="small" readOnly tabIndex={-1} aria-label={`${label} 이름`} disabled={isDisabled} value={current?.label ?? ''} className="fw-pick-name" /></div> : box)}
    {mode === 'popup' && <Dialog isOpen={windowOpen} onClose={() => setWindowOpen(false)} title={title ?? `${label} 찾기`} className="fw-dialog fw-pick-window" style={{ width: Math.min(960, 260 + windowColumns.length * 140) }}>
      <DialogBody>
        <div onKeyDown={windowKeys}>
          <InputGroup inputRef={filterInput} fill size="small" leftIcon="search" aria-label="검색어" placeholder="검색어" value={filter} onValueChange={setFilter} />
          <div className="fw-pick-list" role="grid" aria-label={`${label} 목록`}>
            <table className="bp6-html-table bp6-compact bp6-interactive bp6-html-table-striped">
              <thead><tr>{windowColumns.map(column => <th key={column.key}>{column.label}</th>)}</tr></thead>
              <tbody>{listed.slice(0, 300).map((option, index) => <tr key={option.value} role="row" aria-selected={index === marked} className={index === marked ? 'is-marked' : undefined}
                onClick={() => setMarked(index)} onDoubleClick={() => choose(option)}>{windowColumns.map(column => <td key={column.key} className={column.align ? `is-${column.align}` : undefined}>{cell(option, column)}</td>)}</tr>)}
              {listed.length === 0 && <tr><td colSpan={windowColumns.length} className="fw-pick-empty">맞는 것이 없습니다.</td></tr>}</tbody>
            </table>
          </div>
          <div className="fw-pick-count">{listed.length > 300 ? `${listed.length}건 중 300건 표시 - 검색어로 좁히세요` : search && !filter.trim() ? `처음 ${listed.length}건 - 검색어를 넣으면 전체에서 찾습니다` : `${listed.length}건`} · 더블클릭 또는 Enter 로 선택</div>
        </div>
      </DialogBody>
      <DialogFooter actions={<>
        {value && <Button size="small" variant="minimal" text="선택 지우기" onClick={() => choose(null)} />}
        <Button size="small" text="닫기" onClick={() => setWindowOpen(false)} />
        <Button size="small" intent="primary" text="선택" disabled={!listed[marked]} onClick={() => listed[marked] && choose(listed[marked])} />
      </>} />
    </Dialog>}
  </>;
}
