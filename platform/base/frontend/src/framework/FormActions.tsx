import { Button } from './ui';

export type FormActionsProps = { submitLabel: string; pending: boolean; secondary?: { label: string; onClick: () => void } };
export function FormActions({ submitLabel, pending, secondary }: FormActionsProps) {
  return <div style={{ display: 'flex', gap: 8 }}>
    <Button type="submit" variant="primary" label={submitLabel} isLoading={pending} />
    {secondary && <Button type="button" label={secondary.label} isDisabled={pending} onClick={secondary.onClick} />}
  </div>;
}
