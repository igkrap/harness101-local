import { useEffect, useState } from 'react';
import { ScreenTitle } from '../../ScreenTitle';
import { AsyncFeedback } from '../../AsyncFeedback';
import { Button, Select, TextInput } from '../../ui';
import { loadBranding, type Branding } from '../branding';
import { useBranding } from '../useBranding';
import { adminApi } from '../adminApi';
import './admin.css';

export const meta = { code: 'SYS0006', title: '시스템 설정', icon: 'settings', keywords: ['시스템명', '로고', '파비콘', '테마', '색상', '다크 모드'] };

const MAX_BYTES = 200 * 1024, MAX_BACKGROUND = 5 * 1024 * 1024;
function readImage(file: File, limit = MAX_BYTES, text = '이미지는 200KB 이하여야 합니다.'): Promise<string> {
  return new Promise((resolve, reject) => {
    if (file.size > limit) return reject(new Error(text));
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = () => reject(new Error('이미지를 읽지 못했습니다.'));
    reader.readAsDataURL(file);
  });
}

/** System name (also the browser tab title), logo, favicon, theme colour and light/dark mode. */
export default function SystemSettings() {
  const branding = useBranding();
  const [draft, setDraft] = useState<Branding>(branding);
  const [error, setError] = useState('');
  const [saved, setSaved] = useState(false);
  useEffect(() => { void loadBranding().then(setDraft); }, []);
  // The background is saved on its own (it can be megabytes), keeping the other unsaved edits on this page.
  const saveBackground = (image: string) => adminApi('/api/system/settings/login-background', 'PUT', { image }).then(() => loadBranding())
    .then(next => { setDraft(previous => ({ ...previous, loginBackground: next.loginBackground })); setSaved(true); });
  const change = (changes: Partial<Branding>) => { setSaved(false); setDraft(previous => ({ ...previous, ...changes })); };
  const upload = (key: 'logo' | 'favicon') => <div className="sys-actions">
    <div className="sys-preview">{draft[key] ? <img src={draft[key]} alt="" /> : <span className="sys-muted">없음</span>}</div>
    <label className="bp6-button bp6-small" style={{ cursor: 'pointer' }}>{key === 'logo' ? '로고 고르기' : '파비콘 고르기'}
      <input type="file" accept="image/png,image/jpeg,image/webp,image/svg+xml,image/x-icon" hidden aria-label={key === 'logo' ? '로고 이미지' : '파비콘 이미지'}
        onChange={event => { const file = event.target.files?.[0]; event.target.value = ''; if (file) void readImage(file).then(value => change({ [key]: value })).catch(cause => setError(cause.message)); }} /></label>
    {draft[key] && <Button label="지우기" size="sm" onClick={() => change({ [key]: '' })} />}
  </div>;
  return <div className="sys-page is-flow" data-ui="system-settings">
    <div className="sys-head"><ScreenTitle>시스템 설정</ScreenTitle>
      <Button label="저장" variant="primary" size="sm" isDisabled={!draft.systemName.trim()}
        onClick={() => { setError(''); void adminApi('/api/system/settings', 'PUT', { systemName: draft.systemName, logo: draft.logo, favicon: draft.favicon, themeColor: draft.themeColor, themeMode: draft.themeMode, themeStyle: draft.themeStyle, duplicateLogin: draft.duplicateLogin,
          passwordMinLength: draft.passwordMinLength, passwordRequireMix: draft.passwordRequireMix, passwordRequireSpecial: draft.passwordRequireSpecial,
          companyName: draft.companyName ?? '', companyCeo: draft.companyCeo ?? '', companyBizNo: draft.companyBizNo ?? '', companyAddress: draft.companyAddress ?? '', companyPhone: draft.companyPhone ?? '' }).then(() => loadBranding()).then(() => setSaved(true))
          .catch(cause => setError(cause instanceof Error ? cause.message : '저장하지 못했습니다.')); }} /></div>
    <AsyncFeedback error={error} succeeded={saved} successText="저장되었습니다. 로그인 화면을 포함한 모든 화면에 바로 적용됩니다." />
    <section className="sys-card bp6-card" aria-label="시스템 이름"><h3>시스템 이름</h3>
      <TextInput label="시스템 이름 (브라우저 탭 제목과 사이드바에 표시)" value={draft.systemName} isRequired onChange={value => change({ systemName: value })} /></section>
    <section className="sys-card bp6-card" aria-label="로고와 파비콘"><h3>로고</h3>{upload('logo')}
      <h3>파비콘 (브라우저 탭 아이콘)</h3>{upload('favicon')}
      <div className="sys-muted">PNG·JPG·WEBP·SVG·ICO, 200KB 이하. 파비콘을 비우면 로고를 씁니다.</div></section>
    <section className="sys-card bp6-card" aria-label="회사 정보"><h3>회사 정보 (출력 양식에 들어갑니다)</h3>
      <div className="sys-grid" style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(240px, 1fr))', gap: 8 }}>
        <TextInput label="상호" value={draft.companyName ?? ''} onChange={value => change({ companyName: value })} />
        <TextInput label="대표자" value={draft.companyCeo ?? ''} onChange={value => change({ companyCeo: value })} />
        <TextInput label="사업자등록번호" value={draft.companyBizNo ?? ''} onChange={value => change({ companyBizNo: value })} />
        <TextInput label="전화" value={draft.companyPhone ?? ''} onChange={value => change({ companyPhone: value })} />
        <div style={{ gridColumn: '1 / -1' }}><TextInput label="주소" value={draft.companyAddress ?? ''} onChange={value => change({ companyAddress: value })} /></div>
      </div></section>
    <section className="sys-card bp6-card" aria-label="로그인 화면 배경"><h3>로그인 화면 배경</h3>
      <div className="sys-actions">
        <div className="sys-preview" style={{ width: 160, height: 90 }}>{branding.loginBackground ? <img src={branding.loginBackground} alt="" style={{ width: '100%', height: '100%', objectFit: 'cover' }} /> : <span className="sys-muted">없음</span>}</div>
        <label className="bp6-button bp6-small" style={{ cursor: 'pointer' }}>배경 고르기
          <input type="file" accept="image/png,image/jpeg,image/webp,image/gif" hidden aria-label="로그인 화면 배경 이미지"
            onChange={event => { const file = event.target.files?.[0]; event.target.value = ''; if (!file) return; setError(''); setSaved(false);
              void readImage(file, MAX_BACKGROUND, '배경 이미지는 5MB 이하여야 합니다.').then(image => saveBackground(image)).catch(cause => setError(cause.message)); }} /></label>
        {branding.loginBackground && <Button label="지우기" size="sm" onClick={() => { setError(''); void saveBackground('').catch(cause => setError(cause.message)); }} />}
      </div>
      <div className="sys-muted">PNG·JPG·WEBP·GIF(움직이는 그림 포함), 5MB 이하. 고르는 즉시 적용되고 화면에 꽉 차게 표시됩니다.</div></section>
    <section className="sys-card bp6-card" aria-label="접속"><h3>중복 접속</h3>
      <div className="sys-form">
        <Select label="같은 계정으로 다시 로그인하면" value={draft.duplicateLogin} onChange={value => change({ duplicateLogin: value === 'allow' ? 'allow' : 'block' })}
          options={[{ value: 'block', label: '이전 접속을 끊음 (중복 접속 방지)' }, { value: 'allow', label: '둘 다 유지 (중복 접속 허용)' }]} />
      </div>
      <div className="sys-muted">방지하면 한 계정은 한 곳에서만 쓸 수 있고, 끊긴 쪽에는 사유가 표시됩니다.</div></section>
    <section className="sys-card bp6-card" aria-label="비밀번호 규칙"><h3>비밀번호 규칙</h3>
      <div className="sys-form">
        <TextInput label="최소 길이 (4~64)" value={draft.passwordMinLength} onChange={value => change({ passwordMinLength: value.replace(/[^0-9]/g, '').slice(0, 2) })} />
        <Select label="영문과 숫자 함께" value={draft.passwordRequireMix} onChange={value => change({ passwordRequireMix: value })} options={[{ value: 'false', label: '요구하지 않음' }, { value: 'true', label: '반드시 포함' }]} />
        <Select label="특수문자" value={draft.passwordRequireSpecial} onChange={value => change({ passwordRequireSpecial: value })} options={[{ value: 'false', label: '요구하지 않음' }, { value: 'true', label: '반드시 포함' }]} />
      </div>
      <div className="sys-muted">회원가입, 본인 비밀번호 변경, 관리자의 비밀번호 초기화에 모두 적용됩니다. 이미 쓰고 있는 비밀번호는 바뀌지 않습니다.</div></section>
    <section className="sys-card bp6-card" aria-label="테마"><h3>테마</h3>
      <div className="sys-form">
        <label style={{ display: 'grid', gap: 4, fontSize: 13 }}>강조색
          <input type="color" aria-label="강조색" value={draft.themeColor} onChange={event => change({ themeColor: event.target.value })} style={{ width: 80, height: 32, padding: 0, border: '1px solid var(--fw-border)', borderRadius: 6 }} /></label>
        <Select label="화면 스타일" value={draft.themeStyle} onChange={value => change({ themeStyle: value === 'plain' || value === 'tint' ? value : 'solid' })}
          options={[{ value: 'solid', label: '기본 (회색 머리줄, 둥근 모서리)' }, { value: 'tint', label: '옅은 색' }, { value: 'plain', label: '회색 (색 없음)' }]} />
        <Select label="화면 모드" value={draft.themeMode} onChange={value => change({ themeMode: value === 'dark' ? 'dark' : 'light' })}
          options={[{ value: 'light', label: '밝게' }, { value: 'dark', label: '어둡게' }]} />
      </div></section>
  </div>;
}
