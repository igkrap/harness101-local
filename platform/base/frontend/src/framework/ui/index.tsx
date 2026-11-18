/**
 * The framework's only contact with the design system (Blueprint). Framework components and
 * screens import these primitives; nothing else imports @blueprintjs directly, so the design
 * system can be replaced here without touching screens.
 */
import { Fragment, useId, useState, type ButtonHTMLAttributes, type KeyboardEvent as ReactKeyboardEvent, type CSSProperties, type HTMLAttributes, type JSX, type MouseEvent, type ReactNode, type Ref, type InputHTMLAttributes } from 'react';
import { DateInput as BlueprintDateInput, DateRangeInput as BlueprintDateRangeInput } from '@blueprintjs/datetime';
import '@blueprintjs/datetime/lib/css/blueprint-datetime.css';
import { formatISO, parseISO } from 'date-fns';
import { ko } from 'date-fns/locale';
import { Alert, Button as BlueprintButton, Card as BlueprintCard, Dialog as BlueprintDialog, DialogBody, DialogFooter, Checkbox as BlueprintCheckbox, FocusStyleManager, FormGroup, Icon as BlueprintIcon, type IconName, H1, H2, H3, HTMLSelect, InputGroup, Menu as BlueprintMenu, MenuDivider as BlueprintMenuDivider, MenuItem as BlueprintMenuItem, Popover as BlueprintPopover,  Tag as BlueprintTag, TextArea as BlueprintTextArea,
  Tooltip as BlueprintTooltip, Tree as BlueprintTree, type TreeNodeInfo } from '@blueprintjs/core';
import '@blueprintjs/core/lib/css/blueprint.css';
import './ui.css';
import { isDate, isTime, readNumber, showDate, showNumber, storeDate, storeTime } from '../format';

// Focus frames belong to text inputs; buttons, tabs and rows show them only for keyboard (Tab) users.
FocusStyleManager.onlyShowFocusOnTabs();

export function AppTheme({ children }: { children: ReactNode }) {
  return <div className="fw-app">{children}</div>;
}

type Variant = 'primary' | 'secondary' | 'ghost' | 'destructive' | 'success';
export type ButtonProps = Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'children'> & {
  label: string;
  variant?: Variant;
  /** Controls are compact (24px, the same height as inputs) by default; 'md' is the larger 30px. */
  size?: 'sm' | 'md';
  isDisabled?: boolean;
  isLoading?: boolean;
  /** A Blueprint icon name ('search', 'plus', 'trash', 'floppy-disk', 'print', …) or any element. */
  icon?: ReactNode;
  isIconOnly?: boolean;
  isActive?: boolean;
  /** Colour on the border and text only (white background): a quieter look for coloured actions. */
  outlined?: boolean;
};

export function Button({ label, variant = 'secondary', size, isDisabled, isLoading, icon, isIconOnly, isActive, outlined, className, onClick, ...rest }: ButtonProps) {
  // Blueprint types its handlers on HTMLElement; ours are the ordinary <button> ones.
  return <BlueprintButton {...(rest as object)} onClick={onClick as ((event: MouseEvent<HTMLElement>) => void) | undefined}
    intent={variant === 'primary' ? 'primary' : variant === 'destructive' ? 'danger' : variant === 'success' ? 'success' : 'none'}
    variant={variant === 'ghost' ? 'minimal' : outlined ? 'outlined' : 'solid'} size={size === 'md' ? 'medium' : 'small'}
    disabled={isDisabled} loading={isLoading} active={isActive} className={className}
    aria-label={isIconOnly ? label : rest['aria-label']} title={isIconOnly ? label : rest.title}
    icon={typeof icon === 'string' ? icon as IconName : icon ? <span className="fw-icon" aria-hidden="true">{icon}</span> : undefined} text={isIconOnly ? undefined : label} />;
}

/** A Blueprint button holding its own content (a chip with a dot and a count, a line of a list): minimal or outlined. */
export function ContentButton({ label, children, onClick, outlined, className, title }: { label?: string; children: ReactNode; onClick?: () => void; outlined?: boolean; className?: string; title?: string }) {
  return <BlueprintButton variant={outlined ? 'outlined' : 'minimal'} size="small" className={className} title={title} aria-label={label} onClick={onClick}>{children}</BlueprintButton>;
}
/** A large search box (Blueprint): leading magnifier; other input attributes (role, aria-*) pass through to the input. */
export function BigSearchInput({ inputRef, value, onChange, ...rest }: { inputRef?: Ref<HTMLInputElement>; value: string; onChange: (value: string) => void } & Omit<InputHTMLAttributes<HTMLInputElement>, 'value' | 'onChange' | 'size'>) {
  return <InputGroup {...(rest as object)} inputRef={inputRef} large fill type="search" leftIcon="search" value={value} onValueChange={onChange} />;
}

export function IconButton({ label, icon, ...rest }: Omit<ButtonProps, 'isIconOnly'> & { icon: ReactNode }) {
  return <Button {...rest} label={label} icon={icon} isIconOnly variant={rest.variant ?? 'ghost'} />;
}

type StackProps = HTMLAttributes<HTMLDivElement> & { gap?: number; children?: ReactNode; style?: CSSProperties };
// gap unit is 4px.
export function VStack({ gap = 0, style, ...rest }: StackProps) { return <div {...rest} style={{ display: 'flex', flexDirection: 'column', gap: gap * 4, ...style }} />; }
export function HStack({ gap = 0, style, ...rest }: StackProps) { return <div {...rest} style={{ display: 'flex', flexDirection: 'row', gap: gap * 4, ...style }} />; }

export function Text({ children, style, color }: { children?: ReactNode; style?: CSSProperties; color?: 'secondary' }) {
  return <div className={color === 'secondary' ? 'bp6-text-muted' : undefined} style={style}>{children}</div>;
}

export function Heading({ level = 2, style, children }: { level?: 1 | 2 | 3; style?: CSSProperties; children?: ReactNode }) {
  const Tag = level === 3 ? H3 : level === 1 ? H1 : H2;
  return <Tag style={style}>{children}</Tag>;
}

export type TextInputProps = {
  label: string; value: string; onChange: (value: string) => void; type?: 'text' | 'email' | 'password';
  isRequired?: boolean; isDisabled?: boolean; placeholder?: string; 'aria-invalid'?: boolean;
  /** No label above it (a table cell): `label` is its accessible name. */ hideLabel?: boolean;
};
export function TextInput({ label, value, onChange, type = 'text', isRequired, isDisabled, placeholder, 'aria-invalid': invalid, hideLabel }: TextInputProps) {
  const id = useId();
  if (hideLabel) return <InputGroup id={id} fill size="small" value={value} type={type} placeholder={placeholder} disabled={isDisabled} aria-label={label} onValueChange={onChange} />;
  return <FormGroup label={label} labelFor={id} labelInfo={isRequired ? '*' : undefined} disabled={isDisabled} intent={invalid ? 'danger' : 'none'} className="fw-field">
    <InputGroup id={id} fill size="small" value={value} type={type} placeholder={placeholder} disabled={isDisabled} required={isRequired}
      intent={invalid ? 'danger' : 'none'} aria-invalid={invalid || undefined} onValueChange={onChange} />
  </FormGroup>;
}

type ValueInputProps = { label: string; value: string; onChange: (value: string) => void; isRequired?: boolean; isDisabled?: boolean; placeholder?: string; 'aria-invalid'?: boolean;
  /** No label above it (a table cell, a toolbar): `label` is its accessible name. */ hideLabel?: boolean };
/**
 * A box for a number: right-aligned, read with thousands separators (1,234,567) and typed plainly - the separators
 * step aside while the box is being typed in. Its value is the plain number ('1234567'); typed commas are dropped.
 */
export function NumberInput({ label, value, onChange, isRequired, isDisabled, placeholder, 'aria-invalid': invalid, hideLabel, decimals }: ValueInputProps & {
  /** Read with exactly this many decimal places (1,500.00). */ decimals?: number | null }) {
  const id = useId();
  const [typing, setTyping] = useState(false);
  const box = <InputGroup id={id} fill size="small" className="fw-number" inputMode="decimal" autoComplete="off" value={typing ? value : decimals === null || decimals === undefined ? showNumber(value) : showNumber(value, decimals, true)} placeholder={placeholder} disabled={isDisabled}
    intent={invalid ? 'danger' : 'none'} aria-invalid={invalid || undefined} aria-label={hideLabel ? label : undefined} aria-required={isRequired || undefined}
    onValueChange={next => onChange(readNumber(next))} onFocus={event => { setTyping(true); const input = event.currentTarget; requestAnimationFrame(() => input.select()); }} onBlur={() => setTyping(false)} />;
  return hideLabel ? box : <FormGroup label={label} labelFor={id} labelInfo={isRequired ? '*' : undefined} disabled={isDisabled} intent={invalid ? 'danger' : 'none'} className="fw-field">{box}</FormGroup>;
}
/**
 * A box for a date, read as 2026/11/14. It may be typed as 2026/11/14, 2026.11.14, 2026-11-14 or 20261114; on leaving
 * the box (or Enter) it is rewritten the standard way. onDone gets the settled text ('' or a date as it reads).
 */
export function DateInput({ label, value, onChange, isRequired, isDisabled, placeholder = '2026/01/15', 'aria-invalid': invalid, hideLabel, center, onDone }: ValueInputProps & {
  /** Centred, as dates are in tables. */ center?: boolean; onDone?: (value: string) => void }) {
  // Blueprint's date input: typed as 2026/01/15 (or 20260115, 2026-01-15 ...) or picked from the calendar it opens. The value stays as the
  // screens hold it (2026/01/15); the calendar speaks Korean and starts the week on Sunday.
  const id = useId();
  const stored = isDate(value) ? storeDate(value) : null;
  const box = <BlueprintDateInput inputProps={{ id, size: 'small', className: center ? 'fw-date is-center' : 'fw-date', placeholder, 'aria-label': hideLabel ? label : undefined, 'aria-required': isRequired || undefined,
      'aria-invalid': invalid || undefined, autoComplete: 'off', inputMode: 'numeric' }}
    fill value={stored} disabled={isDisabled} locale={ko} dateFnsFormat="yyyy/MM/dd" parseDate={text => { const typed = text.trim(); return isDate(typed) ? parseISO(storeDate(typed)) : null; }}
    formatDate={date => showDate(formatISO(date, { representation: 'date' }))} canClearSelection highlightCurrentDay shortcuts={false} showActionsBar todayButtonText="오늘" clearButtonText="지우기"
    popoverProps={{ placement: 'bottom-start', minimal: true }} closeOnSelection
    onChange={next => { const shown = next ? showDate(next.slice(0, 10)) : ''; onChange(shown); onDone?.(shown); }} />;
  return hideLabel ? box : <FormGroup label={label} labelFor={id} labelInfo={isRequired ? '*' : undefined} disabled={isDisabled} intent={invalid ? 'danger' : 'none'} className="fw-field">{box}</FormGroup>;
}

/** The two boxes of a period sit in a plain group: the pop-up attributes Blueprint puts on it are not allowed on a div (the boxes themselves open the calendar). */
function RangeBox({ 'aria-expanded': _expanded, 'aria-haspopup': _popup, ...rest }: HTMLAttributes<HTMLDivElement> & { ref?: Ref<HTMLDivElement> }) {
  return <div {...rest} />;
}
/** A period as one control (Blueprint's date range input): from and to, typed or picked on two months side by side, with the usual periods offered. */
export function DateRangeInput({ label, from, to, onChange, isDisabled, hideLabel }: { label: string; from: string; to: string; onChange: (from: string, to: string) => void; isDisabled?: boolean; hideLabel?: boolean }) {
  const id = useId();
  const day = (text: string) => (isDate(text) ? parseISO(storeDate(text)) : null);
  const shown = (date: Date | null) => (date ? showDate(formatISO(date, { representation: 'date' })) : '');
  const now = new Date(), start = (y: number, m: number, d = 1) => new Date(y, m, d);
  const monday = new Date(now); monday.setDate(now.getDate() - ((now.getDay() + 6) % 7));
  const sunday = new Date(monday); sunday.setDate(monday.getDate() + 6);
  const shortcuts = [
    { label: '오늘', dateRange: [start(now.getFullYear(), now.getMonth(), now.getDate()), start(now.getFullYear(), now.getMonth(), now.getDate())] as [Date, Date] },
    { label: '이번 주', dateRange: [monday, sunday] as [Date, Date] },
    { label: '이번 달', dateRange: [start(now.getFullYear(), now.getMonth()), start(now.getFullYear(), now.getMonth() + 1, 0)] as [Date, Date] },
    { label: '지난달', dateRange: [start(now.getFullYear(), now.getMonth() - 1), start(now.getFullYear(), now.getMonth(), 0)] as [Date, Date] },
    { label: '올해', dateRange: [start(now.getFullYear(), 0), start(now.getFullYear(), 11, 31)] as [Date, Date] },
  ];
  const box = <span id={id} className="fw-date-range"><BlueprintDateRangeInput value={[day(from), day(to)]} disabled={isDisabled} locale={ko} allowSingleDayRange shortcuts={shortcuts} closeOnSelection
    formatDate={shown} parseDate={text => day(text.trim())} contiguousCalendarMonths popoverProps={{ placement: 'bottom-start', minimal: true, targetTagName: RangeBox as unknown as 'div' }}
    startInputProps={{ size: 'small', placeholder: '부터', 'aria-label': `${label} 부터`, className: 'fw-date', autoComplete: 'off' }}
    endInputProps={{ size: 'small', placeholder: '까지', 'aria-label': `${label} 까지`, className: 'fw-date', autoComplete: 'off' }}
    onChange={([start, end]) => onChange(shown(start), shown(end))} /></span>;
  return hideLabel ? box : <FormGroup label={label} labelFor={id} disabled={isDisabled} className="fw-field">{box}</FormGroup>;
}

/** A box for a time of day, read as 09:30:00. It may be typed as 0930, 9:30 or 09:30:15; on leaving the box it is rewritten the standard way. */
export function TimeInput({ label, value, onChange, isRequired, isDisabled, placeholder = '09:00', 'aria-invalid': invalid, hideLabel, center }: ValueInputProps & { /** Centred, as times are in tables. */ center?: boolean }) {
  const id = useId();
  const settle = () => { const next = isTime(value) ? storeTime(value) : value.trim(); if (next !== value) onChange(next); };
  const box = <InputGroup id={id} fill size="small" className={center ? 'fw-date is-center' : 'fw-date'} inputMode="numeric" autoComplete="off" value={value} placeholder={placeholder} disabled={isDisabled}
    intent={invalid ? 'danger' : 'none'} aria-invalid={invalid || undefined} aria-label={hideLabel ? label : undefined} aria-required={isRequired || undefined} onValueChange={onChange} onBlur={settle} />;
  return hideLabel ? box : <FormGroup label={label} labelFor={id} labelInfo={isRequired ? '*' : undefined} disabled={isDisabled} intent={invalid ? 'danger' : 'none'} className="fw-field">{box}</FormGroup>;
}
/** A yes/no as a tick box under its label (in a table cell: the box alone, centred). Its value is 'true' or ''. */
export function YesNoInput({ label, value, onChange, isDisabled, hideLabel }: { label: string; value: string; onChange: (value: string) => void; isDisabled?: boolean; hideLabel?: boolean }) {
  const id = useId();
  // Blueprint's tick box (in a table cell: the box alone, centred).
  const box = <span className="fw-yesno"><BlueprintCheckbox id={id} checked={value === 'true'} disabled={isDisabled} aria-label={hideLabel ? label : undefined} className="fw-checkbox"
    onChange={event => onChange(event.currentTarget.checked ? 'true' : '')} /></span>;
  return hideLabel ? box : <FormGroup label={label} labelFor={id} disabled={isDisabled} className="fw-field">{box}</FormGroup>;
}

export type AlertDialogProps = {
  isOpen: boolean; onOpenChange: (open: boolean) => void; title: string; description: string;
  cancelLabel: string; actionLabel: string; actionVariant?: 'destructive'; onAction: () => void;
};
/** A confirmation inside the app (never window.confirm). role="alertdialog". */
export function AlertDialog({ isOpen, onOpenChange, title, description, cancelLabel, actionLabel, actionVariant, onAction }: AlertDialogProps) {
  return <Alert isOpen={isOpen} cancelButtonText={cancelLabel} confirmButtonText={actionLabel} canEscapeKeyCancel canOutsideClickCancel
    intent={actionVariant === 'destructive' ? 'danger' : 'primary'} onConfirm={onAction} onCancel={() => onOpenChange(false)}>
    <h4 className="bp6-heading" style={{ marginTop: 0 }}>{title}</h4>
    <p style={{ margin: 0 }}>{description}</p>
  </Alert>;
}

/** An icon from Blueprint's set by name (https://blueprintjs.com/docs/#icons). */
export function Icon({ name, size = 16 }: { name: string; size?: number }) {
  return <BlueprintIcon icon={name as IconName} size={size} aria-hidden="true" />;
}

export function CloseIcon() { return <Icon name="small-cross" />; }

/** Compact search box (no label shown; `label` is its accessible name). */
export function SearchInput({ label, value, onChange, placeholder, onEnter, onEscape }: { label: string; value: string; onChange: (value: string) => void;
  placeholder?: string; onEnter?: () => void; onEscape?: () => void }) {
  return <InputGroup size="small" fill type="search" aria-label={label} placeholder={placeholder} value={value} onValueChange={onChange}
    leftIcon="search"
    onKeyDown={event => { if (event.key === 'Enter') onEnter?.(); else if (event.key === 'Escape') onEscape?.(); }} />;
}

export type SelectOption = { value: string; label: string };
/** A labelled drop-down. */
export function Select({ label, value, onChange, options, isDisabled, hideLabel }: { label: string; value: string; onChange: (value: string) => void;
  options: readonly SelectOption[]; isDisabled?: boolean; hideLabel?: boolean }) {
  const id = useId();
  const control = <HTMLSelect id={id} fill value={value} disabled={isDisabled} aria-label={hideLabel ? label : undefined}
    onChange={event => onChange(event.currentTarget.value)} options={options.map(option => ({ value: option.value, label: option.label }))} />;
  return hideLabel ? control : <FormGroup label={label} labelFor={id} disabled={isDisabled} className="fw-field">{control}</FormGroup>;
}

/** A check box with its label (pass hideLabel for grids where the column header names it). */
export function Checkbox({ label, checked, onChange, isDisabled, hideLabel, indeterminate }: { label: string; checked: boolean; onChange: (checked: boolean) => void;
  isDisabled?: boolean; hideLabel?: boolean; indeterminate?: boolean }) {
  return <BlueprintCheckbox checked={checked} disabled={isDisabled} indeterminate={indeterminate} aria-label={hideLabel ? label : undefined}
    label={hideLabel ? undefined : label} onChange={event => onChange(event.currentTarget.checked)} className="fw-checkbox" />;
}

/** A pop-up menu (column header menus, right-click menus). */
export function Menu({ children }: { children?: ReactNode }) { return <BlueprintMenu>{children}</BlueprintMenu>; }
export function MenuItem({ text, onClick, disabled, active, icon, children }: { text: string; onClick?: () => void; disabled?: boolean; active?: boolean;
  /** An element shown before the text. */ icon?: JSX.Element; /** Nested items make this a submenu. */ children?: ReactNode }) {
  return <BlueprintMenuItem text={text} onClick={onClick} disabled={disabled} active={active} icon={icon}>{children}</BlueprintMenuItem>;
}
/** A line (optionally titled) between groups of menu items. */
export function MenuDivider({ title }: { title?: string }) { return <BlueprintMenuDivider title={title} />; }
/** A menu that opens beside its trigger (click). `children` are MenuItems. */
export function PopoverMenu({ trigger, children, placement = 'right-start' }: { trigger: JSX.Element; children: ReactNode; placement?: 'right-start' | 'bottom-start' | 'bottom-end' | 'top-start' }) {
  return <BlueprintPopover content={<BlueprintMenu>{children}</BlueprintMenu>} placement={placement} minimal>{trigger}</BlueprintPopover>;
}

export type TabItem = { id: string; title: ReactNode; /** Rendered right after the tab (e.g. its close button). */ after?: ReactNode };
/** The id Blueprint gives a tab's title element (use it for aria-labelledby of your panel). */
export const tabTitleId = (listId: string, tabId: string) => `bp6-tab-title_${listId}_${tabId}`;
/** The id of the panel a tab controls: give it to your panel (role="tabpanel"). */
export const tabPanelId = (listId: string, tabId: string) => `bp6-tab-panel_${listId}_${tabId}`;
/**
 * A row of tabs (titles only; the caller renders the panels with tabPanelId / tabTitleId). Arrow/Home/End move the selection.
 * What follows a tab (its close button) and the row's end stand beside the tabs, not inside the tab list: the list owns only its
 * tabs (aria-owns), so the row may hold buttons and still read as a proper tab list.
 */
export function TabList({ id, tabs, selected, onSelect, end }: { id: string; tabs: readonly TabItem[]; selected: string; onSelect: (id: string) => void; end?: ReactNode }) {
  function keys(event: ReactKeyboardEvent<HTMLDivElement>) {
    if (!(event.target as HTMLElement).matches('[role="tab"]')) return;
    if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); onSelect((event.target as HTMLElement).dataset.tabId ?? selected); return; }
    const index = tabs.findIndex(tab => tab.id === selected);
    const next = event.key === 'ArrowRight' ? index + 1 : event.key === 'ArrowLeft' ? index - 1 : event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : null;
    if (next === null || !tabs.length) return;
    event.preventDefault(); event.stopPropagation();
    const tab = tabs[(next + tabs.length) % tabs.length];
    onSelect(tab.id);
    requestAnimationFrame(() => document.getElementById(tabTitleId(id, tab.id))?.focus());
  }
  return <div className="fw-tabs bp6-tabs" onKeyDownCapture={keys}>
    <div role="tablist" aria-owns={tabs.map(tab => tabTitleId(id, tab.id)).join(' ')} className="fw-tablist-owner" />
    <div className="bp6-tab-list fw-tab-row">
      {tabs.map(tab => <Fragment key={tab.id}>
        <div role="tab" id={tabTitleId(id, tab.id)} data-tab-id={tab.id} className="bp6-tab" aria-selected={tab.id === selected} aria-controls={tabPanelId(id, tab.id)}
          tabIndex={tab.id === selected ? 0 : -1} onClick={() => onSelect(tab.id)}>{tab.title}</div>
        {tab.after}
      </Fragment>)}
      {end ? <span style={{ flex: 1 }} /> : null}
      {end}
    </div>
  </div>;
}

export type TreeNode<T = unknown> = TreeNodeInfo<T>;
/** A folder tree (Blueprint Tree). Folders: hasCaret + isExpanded + childNodes. */
export function Tree<T>({ nodes, onClick, onToggle }: { nodes: TreeNode<T>[]; onClick: (node: TreeNode<T>) => void; onToggle: (node: TreeNode<T>) => void }) {
  return <BlueprintTree<T> contents={nodes} onNodeClick={onClick} onNodeExpand={onToggle} onNodeCollapse={onToggle} />;
}

/** The name of a control shown on hover/focus. */
export function Tooltip({ text, placement = 'right', children }: { text: string; placement?: 'right' | 'top' | 'bottom' | 'left'; children: JSX.Element }) {
  return <BlueprintTooltip content={text} placement={placement} hoverOpenDelay={150}>{children}</BlueprintTooltip>;
}

/** A small label or count. */
export function Tag({ children, intent, round, minimal, label }: { children?: ReactNode; intent?: 'primary' | 'success' | 'warning' | 'danger'; round?: boolean; minimal?: boolean; label?: string }) {
  return <BlueprintTag intent={intent ?? 'none'} round={round} minimal={minimal} aria-label={label}>{children}</BlueprintTag>;
}

/** A bordered white surface (Blueprint Card, compact). */
export function Card({ children, label, style, className }: { children?: ReactNode; label?: string; style?: CSSProperties; className?: string }) {
  return <BlueprintCard compact aria-label={label} role={label ? 'region' : undefined} style={style} className={className}>{children}</BlueprintCard>;
}

/** A window over the page with a title, a body and footer buttons (Blueprint Dialog). */
export function Dialog({ isOpen, onClose, title, children, footer, width = 440 }: { isOpen: boolean; onClose: () => void; title: string; children?: ReactNode; footer?: ReactNode; width?: number }) {
  return <BlueprintDialog isOpen={isOpen} onClose={onClose} title={title} style={{ width }} className="fw-dialog">
    <DialogBody>{children}</DialogBody>
    {footer && <DialogFooter actions={footer} />}
  </BlueprintDialog>;
}

/** A labelled multi-line text box. */
export function TextArea({ label, value, onChange, rows = 8, isDisabled, isReadOnly, placeholder, hideLabel, maxLength, isRequired }: { label: string; value: string; onChange: (value: string) => void; rows?: number;
  isDisabled?: boolean; isReadOnly?: boolean; placeholder?: string; hideLabel?: boolean; maxLength?: number; isRequired?: boolean }) {
  const id = useId();
  const box = <BlueprintTextArea id={id} fill rows={rows} value={value} disabled={isDisabled} readOnly={isReadOnly} placeholder={placeholder} maxLength={maxLength}
    required={isRequired} aria-label={hideLabel ? label : undefined} onChange={event => onChange(event.currentTarget.value)} />;
  if (hideLabel) return box;
  return <FormGroup label={label} labelFor={id} labelInfo={isRequired ? '*' : undefined} disabled={isDisabled} className="fw-field">{box}</FormGroup>;
}

export { Picker, type PickMode, type PickOption, type PickColumn } from './Picker';
export { Chart, StatTiles, type ChartKind, type ChartSeries } from './Chart';
