import { useState } from 'react';
import { Button, Select } from '../ui';
import { MENU_ICONS, MenuIcon } from '../workspace/menuIcons';

const MAX_BYTES = 40 * 1024;

/**
 * Choose an icon: the default, one of the built-in icons, or an uploaded vector image (SVG).
 * value: '' (default), a built-in name, or an SVG data: URL.
 */
export function IconPicker({ label, value, onChange, defaultIcon, defaultLabel }: { label: string; value: string; onChange: (value: string) => void;
  defaultIcon: string; defaultLabel: string }) {
  const [error, setError] = useState('');
  const custom = value.startsWith('data:');
  return <div style={{ display: 'flex', gap: 8, alignItems: 'flex-end', flexWrap: 'wrap' }}>
    <span aria-hidden="true" style={{ width: 34, height: 34, display: 'inline-grid', placeItems: 'center', border: '1px solid var(--fw-border)', borderRadius: 8, background: 'var(--fw-panel)' }}>
      <MenuIcon name={value || defaultIcon} /></span>
    <div style={{ width: 150 }}><Select label={label} value={custom ? '__custom' : value} onChange={next => { setError(''); if (next !== '__custom') onChange(next); }}
      options={[{ value: '', label: defaultLabel }, ...MENU_ICONS.map(name => ({ value: name, label: name })), ...(custom ? [{ value: '__custom', label: '올린 이미지' }] : [])]} /></div>
    <label className="bp6-button bp6-small" style={{ cursor: 'pointer' }}>SVG 올리기
      <input type="file" accept="image/svg+xml,.svg" hidden aria-label={`${label} SVG 이미지`} onChange={event => {
        const file = event.target.files?.[0]; event.target.value = '';
        if (!file) return;
        if (file.type !== 'image/svg+xml' && !file.name.toLowerCase().endsWith('.svg')) return setError('SVG(벡터 이미지) 파일만 올릴 수 있습니다.');
        if (file.size > MAX_BYTES) return setError('SVG는 40KB 이하여야 합니다.');
        const reader = new FileReader();
        reader.onload = () => {
          // Always store as base64 with the SVG type, whatever the browser reported.
          const text = String(reader.result);
          if (!/<svg[\s>]/i.test(text)) return setError('SVG 이미지가 아닙니다.');
          setError('');
          onChange('data:image/svg+xml;base64,' + btoa(unescape(encodeURIComponent(text))));
        };
        reader.onerror = () => setError('파일을 읽지 못했습니다.');
        reader.readAsText(file);
      }} /></label>
    {value && <Button label="기본으로" size="sm" onClick={() => { setError(''); onChange(''); }} />}
    {error && <span role="alert" style={{ color: '#b42318', fontSize: 13 }}>{error}</span>}
  </div>;
}
