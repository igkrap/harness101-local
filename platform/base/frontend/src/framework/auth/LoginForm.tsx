import { useState } from 'react';
import { Fields, validateFields, type FieldDefinition } from '../fields';
import { Panel } from '../Panel';
import { Button } from '../ui';
import { FormActions } from '../FormActions';
import { AsyncFeedback } from '../AsyncFeedback';
import { useSubmission } from '../useSubmission';
import { useBranding } from '../system/useBranding';
import { apiFetch, sessionNotice } from './sessionClient';

export type LoginFormProps = { onSignIn: (username: string, password: string) => Promise<void>; title?: string };

const baseSignupFields: FieldDefinition[] = [
  { name: 'username', label: '아이디', required: true, placeholder: '영문·숫자 3자 이상' },
  { name: 'displayName', label: '이름', required: true },
  { name: 'email', label: '이메일', type: 'email' },
  { name: 'password', label: '비밀번호', type: 'password', required: true },
  { name: 'confirm', label: '비밀번호 확인', type: 'password', required: true,
    validate: (value, values) => value && value !== values.password ? '비밀번호가 서로 다릅니다.' : undefined },
];

/** Sign-in, with sign-up beside it: a sign-up waits for an administrator's approval before it can sign in. */
export function LoginForm({ onSignIn, title }: LoginFormProps) {
  const branding = useBranding();
  const [mode, setMode] = useState<'login' | 'signup'>('login');
  // The password rule comes from the system settings; the server checks it again.
  const least = Number(branding.passwordMinLength) || 8, mix = branding.passwordRequireMix === 'true', special = branding.passwordRequireSpecial === 'true';
  const rule = `${least}자 이상${mix ? ', 영문과 숫자 포함' : ''}${special ? ', 특수문자 포함' : ''}`;
  const signupFields = baseSignupFields.map(field => field.name !== 'password' ? field : { ...field, placeholder: rule,
    validate: (value: string) => value && (value.length < least || (mix && !(/[A-Za-z]/.test(value) && /[0-9]/.test(value))) || (special && !/[^A-Za-z0-9]/.test(value))) ? `${rule}이어야 합니다.` : undefined });
  const [values, setValues] = useState({ username: '', password: '' });
  const [signup, setSignup] = useState<Record<string, string>>({ username: '', displayName: '', email: '', password: '', confirm: '' });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [done, setDone] = useState('');
  const submission = useSubmission();
  if (mode === 'signup') return <form aria-label="회원가입" style={{ width: 'min(420px, calc(100vw - 32px))' }} onSubmit={event => {
    event.preventDefault();
    const issues = validateFields(signupFields, signup);
    setErrors(issues);
    if (Object.keys(issues).length) return;
    void submission.run(async () => {
      const response = await apiFetch('/api/auth/signup', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username: signup.username.trim(), displayName: signup.displayName.trim(), email: signup.email.trim(), password: signup.password }) });
      if (!response.ok) {
        const body = await response.json().catch(() => ({})) as { detail?: string };
        throw new Error(body.detail || '가입 신청을 처리하지 못했습니다.');
      }
      setDone('가입 신청이 접수되었습니다. 관리자가 승인하면 로그인할 수 있습니다.');
      setSignup({ username: '', displayName: '', email: '', password: '', confirm: '' });
      setMode('login');
    });
  }}>
    <Panel title={`${branding.systemName} 회원가입`}>
      <fieldset disabled={submission.pending} style={{ display: 'grid', gap: 14, padding: 0, margin: 0, border: 0 }}>
        <Fields fields={signupFields} values={signup} setValue={(name, value) => setSignup(previous => ({ ...previous, [name]: value }))} errors={errors} disabled={submission.pending} />
        <FormActions submitLabel="가입 신청" pending={submission.pending} />
      </fieldset>
      <AsyncFeedback error={submission.error} />
      <div style={{ marginTop: 12 }}><Button label="로그인으로 돌아가기" variant="ghost" onClick={() => { setMode('login'); submission.reset(); }} /></div>
    </Panel>
  </form>;
  return <form aria-label="로그인" onSubmit={event => {
    event.preventDefault();
    setDone('');
    void submission.run(async () => { await onSignIn(values.username.trim(), values.password); setValues({ username: '', password: '' }); });
  }} style={{ width: 'min(400px, calc(100vw - 32px))' }}>
    <Panel title={title ?? `${branding.systemName} 로그인`}>
      <fieldset disabled={submission.pending} style={{ display: 'grid', gap: 16, padding: 0, margin: 0, border: 0 }}>
        <Fields fields={[{ name: 'username', label: '아이디', required: true }, { name: 'password', label: '비밀번호', type: 'password', required: true }]}
          values={values} setValue={(name, value) => setValues(previous => ({ ...previous, [name]: value }))} errors={{}} disabled={submission.pending} />
        <FormActions submitLabel="로그인" pending={submission.pending} />
      </fieldset>
      <AsyncFeedback error={submission.error} />
      {done && <div role="status" style={{ marginTop: 10, fontSize: 13 }}>{done}</div>}
      {!done && sessionNotice() && <div role="status" data-ui="session-notice" style={{ marginTop: 10, fontSize: 13, color: '#935610' }}>{sessionNotice()}</div>}
      <div style={{ marginTop: 12 }}><Button label="계정이 없으면 회원가입" variant="ghost" onClick={() => { setMode('signup'); submission.reset(); }} /></div>
    </Panel>
  </form>;
}
