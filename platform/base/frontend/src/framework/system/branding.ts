/** System identity and look kept on the server: name (also the browser tab title), logo, favicon, theme. */
export type Branding = { systemName: string; logo: string; favicon: string; themeColor: string; themeMode: 'light' | 'dark';
  /** How much colour the screens carry: plain (greys), tint (light washes of the accent), solid (heading rows in the full accent). */ themeStyle: 'plain' | 'tint' | 'solid';
  /** block: a new sign-in ends the earlier one of the same account (default); allow: several at once. */ duplicateLogin: 'block' | 'allow';
  /** Password rules: least length ('8'), letters+digits required ('true'/'false'), a special character required. */
  passwordMinLength: string; passwordRequireMix: string; passwordRequireSpecial: string;
  /** URL of the login page background image ('' = none). */ loginBackground: string;
  /** The company itself, as printed forms show it. */ companyName?: string; companyCeo?: string; companyBizNo?: string; companyAddress?: string; companyPhone?: string };
export const DEFAULT_BRANDING: Branding = { systemName: '업무 시스템', logo: '', favicon: '', themeColor: '#2d72d2', themeMode: 'light', themeStyle: 'solid', duplicateLogin: 'block', passwordMinLength: '8', passwordRequireMix: 'false', passwordRequireSpecial: 'false', loginBackground: '' };
type Listener = (branding: Branding) => void;
let current: Branding = DEFAULT_BRANDING;
const listeners = new Set<Listener>();

export function currentBranding() { return current; }
export function subscribeBranding(listener: Listener) { listeners.add(listener); return () => { listeners.delete(listener); }; }

/** Tab title, favicon, accent colour and light/dark mode follow the settings everywhere, sign-in page included. */
export function applyBranding(branding: Branding) {
  current = branding;
  document.title = branding.systemName;
  const icon = branding.favicon || branding.logo;
  let link = document.querySelector<HTMLLinkElement>('link[rel="icon"]');
  if (icon) {
    if (!link) { link = document.createElement('link'); link.rel = 'icon'; document.head.appendChild(link); }
    link.href = icon;
  } else if (link?.href.startsWith('data:')) link.remove();
  document.documentElement.style.setProperty('--fw-accent', branding.themeColor);
  document.body.classList.toggle('bp6-dark', branding.themeMode === 'dark');
  document.documentElement.dataset.theme = branding.themeMode;
  document.documentElement.dataset.look = branding.themeStyle || 'solid';
  listeners.forEach(listener => listener(branding));
}

export async function loadBranding(): Promise<Branding> {
  try {
    const response = await fetch('/api/auth/branding', { credentials: 'same-origin', headers: { Accept: 'application/json' } });
    if (response.ok) {
      const value = await response.json() as Partial<Branding>;
      applyBranding({ ...DEFAULT_BRANDING, ...Object.fromEntries(Object.entries(value).filter(([, v]) => typeof v === 'string' && v !== '')),
        logo: value.logo ?? '', favicon: value.favicon ?? '',
        loginBackground: value.loginBackground ? `/api/auth/branding/login-background?v=${value.loginBackground}` : '' } as Branding);
    } else applyBranding(current);
  } catch { applyBranding(current); }
  return current;
}
