import { useEffect, useState } from 'react';
import { apiFetch, loadSession } from '../auth/sessionClient';
import { Button, Dialog, TextInput } from '../ui';
import { adminApi } from './adminApi';
import { formatDateTime } from '../gridExport';

type Me = { username: string; displayName: string; email: string; passwordChangedAt: string | null };

/** 내 정보: the signed-in user's own name and e-mail, and changing the password (current password required). */
export function AccountDialog({ isOpen, onClose }: { isOpen: boolean; onClose: () => void }) {
  const [me, setMe] = useState<Me | null>(null);
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [current, setCurrent] = useState('');
  const [next, setNext] = useState('');
  const [again, setAgain] = useState('');
  const [policy, setPolicy] = useState('');
  const [message, setMessage] = useState<{ text: string; bad?: boolean } | null>(null);
  useEffect(() => {
    if (!isOpen) return;
    setMessage(null); setCurrent(''); setNext(''); setAgain('');
    void adminApi<Me>('/api/auth/me').then(value => { setMe(value); setName(value.displayName); setEmail(value.email); }).catch(() => {});
    void apiFetch('/api/auth/password-policy').then(async response => { if (response.ok) setPolicy(((await response.json()) as { description: string }).description); }).catch(() => {});
  }, [isOpen]);
  const fail = (cause: unknown) => setMessage({ text: cause instanceof Error ? cause.message : '처리하지 못했습니다.', bad: true });
  return <Dialog isOpen={isOpen} onClose={onClose} title="내 정보" footer={<Button label="닫기" onClick={onClose} />}>
    <div data-ui="account-dialog" style={{ display: 'grid', gap: 10 }}>
      <TextInput label="아이디" value={me?.username ?? ''} isDisabled onChange={() => undefined} />
      <TextInput label="이름" value={name} isRequired onChange={setName} />
      <TextInput label="이메일" type="email" value={email} onChange={setEmail} />
      <div><Button label="이름·이메일 저장" variant="primary" isDisabled={!name.trim()} onClick={() => void adminApi<Me>('/api/auth/me', 'PUT', { displayName: name, email })
        .then(async value => { setMe(value); await loadSession(); setMessage({ text: '저장했습니다.' }); }).catch(fail)} /></div>
      <hr style={{ width: '100%', border: 0, borderTop: '1px solid var(--fw-border)', margin: '4px 0' }} />
      <strong>비밀번호 변경</strong>
      {me?.passwordChangedAt && <div style={{ fontSize: 12, color: 'var(--fw-muted)' }}>마지막 변경: {formatDateTime(me.passwordChangedAt)}</div>}
      <TextInput label="현재 비밀번호" type="password" value={current} onChange={setCurrent} />
      <TextInput label={policy ? `새 비밀번호 (${policy})` : '새 비밀번호'} type="password" value={next} onChange={setNext} />
      <TextInput label="새 비밀번호 확인" type="password" value={again} onChange={setAgain} aria-invalid={Boolean(again) && again !== next} />
      <div><Button label="비밀번호 변경" isDisabled={!current || !next || next !== again} onClick={() => void adminApi('/api/auth/me/password', 'POST', { currentPassword: current, newPassword: next })
        .then(() => { setCurrent(''); setNext(''); setAgain(''); setMessage({ text: '비밀번호를 바꿨습니다.' }); }).catch(fail)} /></div>
      {message && <div role={message.bad ? 'alert' : 'status'} style={{ fontSize: 13, color: message.bad ? '#b42318' : '#1c6e42' }}>{message.text}</div>}
    </div>
  </Dialog>;
}
