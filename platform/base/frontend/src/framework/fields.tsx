import { useEffect, useState, type ReactNode } from 'react';
import { DateInput, DateRangeInput, NumberInput, Picker, TextArea, TextInput, TimeInput, YesNoInput } from './ui';
import { isDate, isTime, readNumber } from './format';
import { useCommonCodes } from './system/commonCodes';
import { fetchLines, useLookup, type Lookup } from './lookup';

export type FieldValues = Record<string, string>;
export type FieldControl = {
  value: string;
  onChange: (value: string) => void;
  disabled: boolean;
  error?: string;
};
/** A field that depends on another: it holds when that field's value is one of `is` (stored values: a code, an id, 'true'/'false' for a tick box, '' for empty). */
export type When = { field: string; is: string[]; not?: boolean };
/** values: the form (or the line) the field is in; above: for a line, the record it belongs to. */
export function holds(when: When | null | undefined, values: FieldValues, above?: FieldValues): boolean {
  if (!when) return false;
  const value = (when.field in values ? values[when.field] : above?.[when.field]) ?? '';
  const matches = when.is.includes(value.trim()) || (value.trim() === '' && when.is.includes('false'));
  return when.not ? !matches : matches;
}
export type FieldDefinition = {
  name: string;
  label: string;
  /** integer and decimal are right-aligned and read with thousands separators; date reads 2026/11/14, time 09:30:00;
   *  yesno is a tick box ('true' or ''); memo is a box of several lines across the whole form. */
  type?: 'text' | 'email' | 'password' | 'integer' | 'decimal' | 'date' | 'time' | 'yesno' | 'memo';
  /** Decimal places a number is read with (1,500.00). */
  decimals?: number | null;
  required?: boolean;
  min?: number;
  max?: number;
  placeholder?: string;
  validate?: (value: string, values: FieldValues) => string | undefined;
  render?: (control: FieldControl) => ReactNode;
  /** Drop-down of a common-code group; stores the code. */
  codeGroup?: string;
  /** How a code or lookup is chosen: 'dropdown' (default), 'search' (type to find) or 'popup' (search window; lookups only). */
  pick?: 'dropdown' | 'search' | 'popup';
  /** Drop-down of another screen's records; stores the id. */
  lookup?: Lookup;
  /** Whole row of the form. */
  wide?: boolean;
  /** Tab/section the field belongs to when an editor shows its fields in groups. */
  group?: string;
  /** A period in one control: this field holds the start, `to` names the field that holds the end. */
  dateRange?: { to: string };
  /** A line of another master with details (a step of an item's routing), offered only for the record whose `withinTarget` equals this form's `within`. */
  lineLookup?: { entity: string; label: string; within?: string | null; withinTarget?: string | null };
  /** The field is there only when the condition holds / must be filled when it holds / cannot be changed when it holds. */
  showWhen?: When | null;
  requiredWhen?: When | null;
  lockWhen?: When | null;
};
export type DraftControls = { values: FieldValues; setValue: (name: string, value: string) => void };

export function fieldDefaults(fields: readonly FieldDefinition[], initial: FieldValues = {}): FieldValues {
  return Object.fromEntries(fields.map(field => [field.name, initial[field.name] ?? '']));
}

export function validateFields(fields: readonly FieldDefinition[], values: FieldValues): FieldValues {
  const errors: FieldValues = {};
  for (const field of fields) {
    const value = values[field.name] ?? '';
    if (field.showWhen && !holds(field.showWhen, values)) continue;       // not there: asked for nothing
    if ((field.required || holds(field.requiredWhen, values)) && !value.trim()) errors[field.name] = `${field.label}을(를) 입력하세요.`;
    else if (value.trim() && (field.type === 'integer' || field.type === 'decimal')) {
      const number = Number(readNumber(value));
      if (!Number.isFinite(number) || (field.type === 'integer' && !Number.isInteger(number)))
        errors[field.name] = field.type === 'integer' ? '정수를 입력하세요.' : '숫자를 입력하세요.';
      else if (field.min !== undefined && number < field.min) errors[field.name] = `${field.min} 이상이어야 합니다.`;
      else if (field.max !== undefined && number > field.max) errors[field.name] = `${field.max} 이하여야 합니다.`;
    }
    else if (value.trim() && field.type === 'date' && !isDate(value)) errors[field.name] = '2026/01/15 같은 날짜로 입력하세요.';
    else if (value.trim() && field.type === 'time' && !isTime(value)) errors[field.name] = '09:30 같은 시각으로 입력하세요.';
    const custom = field.validate?.(value, values);
    if (custom) errors[field.name] = custom;
  }
  return errors;
}

/** The drop-down (or search box) of a common-code group. hideLabel: in a table cell. */
export function CodeField({ field, control, hideLabel }: { field: Pick<FieldDefinition, 'label' | 'required' | 'codeGroup' | 'pick'>; control: Pick<FieldControl, 'value' | 'onChange' | 'disabled'>; hideLabel?: boolean }) {
  const codes = useCommonCodes(field.codeGroup ?? '');
  // A stored code that is no longer in use still shows, so old records stay readable.
  return <Picker label={field.label} hideLabel={hideLabel} isRequired={field.required} mode={field.pick === 'search' ? 'search' : 'dropdown'} value={control.value} isDisabled={control.disabled} onChange={control.onChange}
    options={codes.options.filter(option => option.value !== '')} />;
}

/** Choosing a line of another master: the lines of the record that goes with this one (same item ...), read when that value changes. */
export function LineField({ field, lookup, control, owner, hideLabel }: { field: Pick<FieldDefinition, 'label' | 'required'>; lookup: NonNullable<FieldDefinition['lineLookup']>; control: Pick<FieldControl, 'value' | 'onChange' | 'disabled'>; owner?: string; hideLabel?: boolean }) {
  const [lines, setLines] = useState<Record<string, unknown>[]>([]);
  useEffect(() => {
    let alive = true;
    if (lookup.within && !owner) { setLines([]); return; }
    void fetchLines(lookup.entity, lookup.withinTarget, owner).then(found => { if (alive) setLines(found); }).catch(() => {});
    return () => { alive = false; };
  }, [lookup.entity, lookup.withinTarget, owner]);   // eslint-disable-line react-hooks/exhaustive-deps
  const options = lines.map(line => ({ value: String(line.id), label: String(line[lookup.label] ?? '') }));
  return <Picker label={field.label} hideLabel={hideLabel} isRequired={field.required} mode="dropdown" value={control.value} isDisabled={control.disabled || (Boolean(lookup.within) && !owner)} onChange={control.onChange}
    options={options} />;
}

export function LookupField({ field, lookup, control, hideLabel }: { field: FieldDefinition; lookup: Lookup; control: Pick<FieldControl, 'value' | 'onChange' | 'disabled'>; hideLabel?: boolean }) {
  const source = useLookup(lookup);
  // The other screen may hold more records than were read: the one this field points at is fetched by itself, and typing searches there.
  useEffect(() => { void source.ensure(control.value); }, [control.value, source.choices.length]);   // eslint-disable-line react-hooks/exhaustive-deps
  // A stored id whose record is gone still shows, so old records stay readable.
  return <Picker label={field.label} hideLabel={hideLabel} isRequired={field.required} mode={(mode => (source.more && mode === 'dropdown' ? 'popup' : mode))(field.pick ?? lookup.pick ?? 'dropdown')} value={control.value} isDisabled={control.disabled} onChange={control.onChange}
    options={source.choices} columns={lookup.columns} title={lookup.title} split={Boolean(lookup.code)} search={source.more ? source.search : undefined} />;
}

export function Fields({ fields, values, setValue, errors, disabled = false }: DraftControls & {
  fields: readonly FieldDefinition[];
  errors: FieldValues;
  disabled?: boolean;
}) {
  return fields.map(given => {
    if (given.showWhen && !holds(given.showWhen, values)) return null;
    const off = disabled || holds(given.lockWhen, values);
    const field = given.requiredWhen && holds(given.requiredWhen, values) ? { ...given, required: true } : given;
    const control: FieldControl = {
      value: values[field.name] ?? '',
      onChange: value => { if (!off) setValue(field.name, value); },
      disabled: off,
      error: errors[field.name],
    };
    return <div key={field.name} style={{ minWidth: 0, gridColumn: field.wide || field.type === 'memo' ? '1 / -1' : undefined }}>
      {field.dateRange ? <DateRangeInput label={field.label} from={values[field.name] ?? ''} to={values[field.dateRange.to] ?? ''} isDisabled={off}
          onChange={(from, to) => { setValue(field.name, from); setValue(field.dateRange!.to, to); }} />
        : field.render ? field.render(control) : field.lineLookup ? <LineField field={field} lookup={field.lineLookup} control={control} owner={field.lineLookup.within ? values[field.lineLookup.within] : undefined} />
        : field.codeGroup ? <CodeField field={field} control={control} /> : field.lookup ? <LookupField field={field} lookup={field.lookup} control={control} />
        : field.type === 'integer' || field.type === 'decimal' ? <NumberInput label={field.label} value={control.value} onChange={control.onChange} isRequired={field.required} isDisabled={off} placeholder={field.placeholder} aria-invalid={!!control.error} decimals={field.decimals} />
        : field.type === 'time' ? <TimeInput label={field.label} value={control.value} onChange={control.onChange} isRequired={field.required} isDisabled={off} placeholder={field.placeholder} aria-invalid={!!control.error} />
        : field.type === 'yesno' ? <YesNoInput label={field.label} value={control.value} onChange={control.onChange} isDisabled={off} />
        : field.type === 'memo' ? <TextArea label={field.label} isRequired={field.required} value={control.value} onChange={control.onChange} isDisabled={off} rows={3} placeholder={field.placeholder} />
        : field.type === 'date' ? <DateInput label={field.label} value={control.value} onChange={control.onChange} isRequired={field.required} isDisabled={off} placeholder={field.placeholder} aria-invalid={!!control.error} />
        : <TextInput
        label={field.label}
        type={field.type === 'email' || field.type === 'password' ? field.type : 'text'}
        value={control.value}
        onChange={control.onChange}
        isRequired={field.required}
        isDisabled={off}
        placeholder={field.placeholder}
        aria-invalid={!!control.error}
      />}
      {control.error && <div role="alert" style={{ color: '#b42318', fontSize: 13 }}>{control.error}</div>}
    </div>;
  });
}
