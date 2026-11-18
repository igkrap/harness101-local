import { useState, type ReactNode } from 'react';
import { Panel } from './Panel';
import { FormActions } from './FormActions';
import { AsyncFeedback } from './AsyncFeedback';
import { Fields, fieldDefaults, validateFields, type DraftControls, type FieldDefinition, type FieldValues } from './fields';
import { useSubmission } from './useSubmission';
import { QuerySections } from './QuerySections';
import { useOwnActions } from './toolbarContext';

export type QueryPanelProps = {
  fields: readonly FieldDefinition[];
  advancedFields?: readonly FieldDefinition[];
  initialValues?: FieldValues;
  onQuery: (values: FieldValues) => void | Promise<void>;
  label?: string;
  formId?: string;
  showActions?: boolean;
  children?: (controls: DraftControls) => ReactNode;
};

export function QueryPanel({ fields, advancedFields = [], initialValues, onQuery, label = '조회 조건', formId, showActions: requestedActions, children }: QueryPanelProps) {
  const showActions = useOwnActions(requestedActions);
  const allFields = [...fields, ...advancedFields];
  const primary = [...fields, ...advancedFields.filter(field => field.required)];
  const details = advancedFields.filter(field => !field.required);
  const [values, setValues] = useState(() => fieldDefaults(allFields, initialValues));
  const [errors, setErrors] = useState<FieldValues>({});
  const submission = useSubmission();
  const setValue = (name: string, value: string) => setValues(previous => ({ ...previous, [name]: value }));
  function query(next: FieldValues) {
    const issues = validateFields(allFields, next);
    setErrors(issues);
    if (!Object.keys(issues).length) void submission.run(() => onQuery({ ...next }));
  }
  return <form id={formId} aria-label={label} data-ui="query-panel" onSubmit={event => { event.preventDefault(); query(values); }}><Panel compact>
    <fieldset disabled={submission.pending} style={{ border: 0, margin: 0, padding: 0, display: 'flex', flexWrap: 'wrap', alignItems: 'end', gap: 8 }}>
      <QuerySections primary={<><Fields fields={primary} values={values} setValue={setValue} errors={errors} disabled={submission.pending} />{children?.({ values, setValue })}</>}
        advanced={details.length > 0 && <Fields fields={details} values={values} setValue={setValue} errors={errors} disabled={submission.pending} />} />
      {showActions && <FormActions submitLabel="조회" pending={submission.pending} secondary={{label: '조건 지우기', onClick: () => {
        const cleared = fieldDefaults(allFields, initialValues);
        setValues(cleared);
        query(cleared);
      }}} />}
    </fieldset>
    <AsyncFeedback error={submission.error} />
  </Panel></form>;
}
