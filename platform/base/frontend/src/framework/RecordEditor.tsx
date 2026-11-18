import { useEffect, useRef, useState, type ReactNode } from 'react';
import { Panel } from './Panel';
import { FormActions } from './FormActions';
import { AsyncFeedback } from './AsyncFeedback';
import { Fields, fieldDefaults, validateFields, type DraftControls, type FieldDefinition, type FieldValues } from './fields';
import { useSubmission } from './useSubmission';
import { useUnsavedChanges } from './workspace/DirtyContext';
import { useOwnActions } from './toolbarContext';

export type RecordKey = string | number;
export type EditableRecord = { id: RecordKey; values: FieldValues };
export type RecordEditorProps = {
  fields: readonly FieldDefinition[];
  record: EditableRecord | null;
  defaults?: FieldValues;
  onSave: (values: FieldValues, id: RecordKey | null) => Promise<void>;
  onNew: () => void;
  resetKey?: string | number;
  formId?: string;
  showActions?: boolean;
  compact?: boolean;
  children?: (controls: DraftControls) => ReactNode;
};

// framed=false: no own box (inside a container). group: show only that field group; draft and validation
// still cover every field. onInvalid: invalid field names after a failed save. columns: field grid columns.
/** Layout options BusinessWorkspace sets for its grouped editor (kept out of the public editor props). */
export type RecordEditorLayout = { framed?: boolean; group?: string; columns?: number; onInvalid?: (names: string[]) => void };

export function RecordEditor(props: RecordEditorProps & RecordEditorLayout) {
  // Each selected record owns its draft; a list/query rerender (same record values) cannot erase edits.
  // Selecting a record again with its row values reloads them. A record given only an id (values {}),
  // e.g. right after saving a new one, keeps the draft that was just saved.
  const draft = useRef<FieldValues>({});
  const session = useRef<{ key: string; id: unknown; adopted?: unknown }>({ key: '', id: null });
  const given = props.record && Object.keys(props.record.values ?? {}).length ? props.record.values : null;
  const id = props.record?.id ?? null;
  let key = JSON.stringify([id, props.resetKey ?? null, given]);
  // A new record that just got its id (values {}) stays the same session: draft and saved status remain.
  const adopt = id !== null && !given && session.current.key !== '' && (session.current.id === null || session.current.adopted === id);
  if (adopt) key = session.current.key;
  session.current = { key, id, adopted: adopt ? id : undefined };
  const initial = props.record && !given ? draft.current : props.record?.values;
  return <EditorSession key={key} {...props} initial={initial} onDraft={values => { draft.current = values; }} />;
}

function EditorSession({ fields, record, defaults, onSave, onNew, children, formId, showActions: requestedActions, compact = false, framed = true, group, onInvalid, columns, initial, onDraft }: RecordEditorProps & RecordEditorLayout & { initial?: FieldValues; onDraft: (values: FieldValues) => void }) {
  const showActions = useOwnActions(requestedActions);
  const [values, setValues] = useState(() => fieldDefaults(fields, { ...defaults, ...initial }));
  useEffect(() => { onDraft(values); }, [values, onDraft]);
  const [savedValues, setSavedValues] = useState(values);
  useUnsavedChanges(JSON.stringify(values) !== JSON.stringify(savedValues));
  const [errors, setErrors] = useState<FieldValues>({});
  const submission = useSubmission();
  const setValue = (name: string, value: string) => setValues(previous => ({ ...previous, [name]: value }));
  const title = record ? '수정' : '신규 등록';
  return <form id={formId} aria-label={title} data-ui="record-editor" onSubmit={event => {
    event.preventDefault();
    const issues = validateFields(fields, values);
    setErrors(issues);
    if (Object.keys(issues).length) onInvalid?.(Object.keys(issues));
    if (!Object.keys(issues).length) void submission.run(async () => {
      const submitted = { ...values };
      await onSave(submitted, record?.id ?? null);
      setSavedValues(submitted);
    });
  }}><Panel title={title} framed={framed}>
    <fieldset disabled={submission.pending} style={{ border: 0, margin: 0, padding: 0, display: 'grid', gridTemplateColumns: columns ? `repeat(${columns}, minmax(0, 1fr))` : compact ? 'repeat(auto-fit, minmax(160px, 1fr))' : undefined, gap: 12 }}>
      <Fields fields={group ? fields.filter(field => !field.group || field.group === group) : fields} values={values} setValue={setValue} errors={errors} disabled={submission.pending} />
      {children?.({ values, setValue })}
        {showActions && <div style={{ gridColumn: '1 / -1' }}><FormActions submitLabel={record ? '저장' : '추가'} pending={submission.pending} secondary={{label: '신규', onClick: () => {
          setValues(fieldDefaults(fields, defaults));
          setSavedValues(fieldDefaults(fields, defaults));
          setErrors({});
          submission.reset();
          onNew();
        }}} /></div>}
    </fieldset>
    <AsyncFeedback error={submission.error} succeeded={submission.succeeded} successText="저장되었습니다." />
  </Panel></form>;
}
