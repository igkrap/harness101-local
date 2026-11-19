/**
 * A drop-down that opens its list right under its box in every browser (a Blueprint pop-up placed by script - the browser's own
 * <select> opens over its box on a Mac). A native <select> with the same value stays under the box, unseen: it is what the label
 * names and what checks, keyboards and screen readers set; the box and its list are what people click.
 */
import { useState, type ChangeEvent } from 'react';
import { Button, Menu, MenuItem, Popover } from '@blueprintjs/core';

export type DropOption = { value: string; label: string; disabled?: boolean };

export function DropSelect({ id, value, options, onChange, disabled, ariaLabel }: { id?: string; value: string; options: readonly DropOption[];
  onChange: (value: string) => void; disabled?: boolean; ariaLabel?: string }) {
  const [open, setOpen] = useState(false);
  const chosen = options.find(option => option.value === value);
  return <div className="fw-dropselect">
    <Popover isOpen={open && !disabled} onInteraction={next => setOpen(next)} placement="bottom-start" minimal matchTargetWidth fill
      content={<Menu className="fw-dropselect-menu" role="listbox">
        {options.map(option => <MenuItem key={option.value} text={option.label || ' '} roleStructure="listoption" selected={option.value === value}
          disabled={option.disabled} onClick={() => { setOpen(false); if (option.value !== value) onChange(option.value); }} />)}
      </Menu>}>
      <Button fill alignText="left" endIcon="caret-down" disabled={disabled} tabIndex={-1} aria-hidden className="fw-dropselect-box"
        text={chosen?.label ?? value} onClick={() => setOpen(next => !next)} />
    </Popover>
    <select id={id} value={value} disabled={disabled} aria-label={ariaLabel} className="fw-dropselect-native"
      onChange={(event: ChangeEvent<HTMLSelectElement>) => onChange(event.currentTarget.value)}
      onKeyDown={event => { if (event.key === ' ' || event.key === 'Enter') { event.preventDefault(); setOpen(true); } }}>
      {options.map(option => <option key={option.value} value={option.value} disabled={option.disabled}>{option.label}</option>)}
    </select>
  </div>;
}
