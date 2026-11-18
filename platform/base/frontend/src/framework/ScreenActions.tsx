import { useState } from 'react';
import { AlertDialog, Button } from './ui';
import { useProgramPermission } from './system/programAccess';
import { AsyncFeedback } from './AsyncFeedback';
import { useSubmission } from './useSubmission';

export type ScreenAction = { onClick?: () => void | Promise<void>; form?: string; disabled?: boolean; pending?: boolean; confirm?: string; /** Shown instead of the usual word, e.g. '첨부 2'. */ label?: string };
export type ScreenActionSet = Partial<Record<'query' | 'create' | 'copy' | 'remove' | 'save' | 'import' | 'export' | 'print' | 'detail' | 'links' | 'files' | 'history', ScreenAction>>;
export type ScreenActionsProps = { actions: ScreenActionSet; beforeAction?: (action: keyof ScreenActionSet) => void };
const labels = { query: '조회', create: '신규', copy: '복사', remove: '삭제', save: '저장', import: '올리기', export: '엑셀', print: '출력', detail: '내역', links: '연결', files: '첨부', history: '이력' };
// Each action carries its role's colour, quietly: coloured outline for 조회/신규/삭제, filled only for 저장 (the commit).
const looks: Record<keyof typeof labels, { variant?: 'primary' | 'success' | 'destructive'; outlined?: boolean; icon: string }> = {
  query: { variant: 'primary', outlined: true, icon: 'search' }, create: { variant: 'success', outlined: true, icon: 'plus' }, copy: { icon: 'duplicate' },
  remove: { variant: 'destructive', outlined: true, icon: 'trash' }, save: { variant: 'primary', icon: 'floppy-disk' }, import: { icon: 'import' }, export: { icon: 'th' }, print: { icon: 'print' }, detail: { icon: 'list-detail-view' }, links: { icon: 'link' }, files: { icon: 'paperclip' }, history: { icon: 'history' },
};

export function ScreenActions({ actions, beforeAction }: ScreenActionsProps) {
  const submission = useSubmission();
  // Confirmation is an in-app dialog: native window.confirm is suppressed by embedded browsers.
  const [confirming, setConfirming] = useState<keyof ScreenActionSet | null>(null);

  function perform(key: keyof ScreenActionSet) {
    const action = actions[key];
    if (!action) return;
    beforeAction?.(key);
    if (action.form) {
      requestAnimationFrame(() => {
        const form = document.getElementById(action.form ?? '');
        if (form instanceof HTMLFormElement) form.requestSubmit();
      });
    }
    if (action.onClick) void submission.run(action.onClick);
  }

  // Role-based program permission: actions the user's roles do not grant are not shown (the API refuses them too).
  const permission = useProgramPermission();
  const granted: Record<keyof ScreenActionSet, boolean> = { query: permission.query, create: permission.create, copy: permission.create,
    save: permission.save || permission.create, remove: permission.delete, import: permission.create, export: permission.print, print: permission.print, detail: permission.query, links: permission.query, files: permission.query, history: permission.query };
  const pendingConfirm = confirming ? actions[confirming] : undefined;
  return <div style={{ display: 'grid', gap: 4 }}>
    <div role="toolbar" aria-label="업무 버튼" style={{ display: 'flex', gap: 4, flexWrap: 'wrap', justifyContent: 'flex-end' }}>
      {(Object.keys(labels) as (keyof ScreenActionSet)[]).map(key => {
        const action = actions[key];
        if (!action || !granted[key]) return null;
        return <Button key={key} label={action.label ?? labels[key]} {...looks[key]} type={action.form ? 'submit' : 'button'} form={action.form}
          isDisabled={action.disabled || submission.pending || action.pending || (!action.form && !action.onClick)} isLoading={action.pending}
          onClick={event => {
            if (action.form) event.preventDefault();
            if (action.confirm) setConfirming(key);
            else perform(key);
          }} />;
      })}
    </div>
    <AlertDialog isOpen={Boolean(pendingConfirm)} onOpenChange={open => { if (!open) setConfirming(null); }}
      title={confirming ? labels[confirming] : ''} description={pendingConfirm?.confirm ?? ''}
      cancelLabel="취소" actionLabel={confirming ? labels[confirming] : '확인'}
      actionVariant={confirming === 'remove' ? 'destructive' : undefined}
      onAction={() => { const key = confirming; setConfirming(null); if (key) perform(key); }} />
    <AsyncFeedback error={submission.error} />
  </div>;
}
