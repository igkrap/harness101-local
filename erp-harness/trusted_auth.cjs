const fs = require('node:fs');
const path = require('node:path');

function trustedOrigin(base, localProxy = false) {
  const url = new URL(base);
  if (!['http:', 'https:'].includes(url.protocol) || !['127.0.0.1', 'localhost', '[::1]'].includes(url.hostname)) return false;
  const allowed = (process.env.HARNESS_AUTH_ORIGINS || 'http://127.0.0.1:5292,http://127.0.0.1:8083').split(',');
  return localProxy || allowed.includes(url.origin);
}

async function ensureAuthenticated(request, base, { localProxy = false } = {}) {
  if (!trustedOrigin(base, localProxy)) return false;
  const url = new URL('/api/auth/session', base).toString();
  const response = await request.get(url, { maxRedirects: 0, timeout: 10000 });
  if (response.status() === 404) return false;
  if (!response.ok()) throw new Error('Trusted application session endpoint returned HTTP ' + response.status());
  const session = await response.json();
  if (typeof session.authenticated !== 'boolean') return false;
  if (session.authenticated) return true;
  if (!session.csrf?.token || session.csrf.headerName !== 'X-CSRF-TOKEN') throw new Error('Invalid trusted session CSRF contract');
  // The checker signs in with its own account (platform/provision_verifier.py): the app allows one live session
  // per account, so sharing the administrator's would sign the person using the app out on every check.
  const own = path.resolve(__dirname, '../platform/state/auth/verifier-login.json');
  const file = process.env.HARNESS_LOGIN_CREDENTIALS || (fs.existsSync(own) ? own : path.resolve(__dirname, '../platform/state/auth/local-login.json'));
  if (!fs.existsSync(file)) throw new Error('Local test login is not provisioned; run platform/bootstrap_auth.py');
  const account = JSON.parse(fs.readFileSync(file, 'utf8'));
  const login = await request.post(new URL('/api/auth/login', base).toString(), {
    form: { username: account.username, password: account.password },
    headers: { [session.csrf.headerName]: session.csrf.token },
    maxRedirects: 0, timeout: 10000,
  });
  if (!login.ok()) throw new Error('Trusted test login failed with HTTP ' + login.status());
  const verified = await (await request.get(url)).json();
  if (!verified.authenticated) throw new Error('Trusted test login did not establish a session');
  return true;
}

async function authenticationHeaders(base) {
  if (!trustedOrigin(base)) return {};
  const cookies = new Map();
  const send = async (url, options = {}) => {
    const headers = new Headers(options.headers);
    if (cookies.size) headers.set('Cookie', [...cookies].map(([name,value]) => name + '=' + value).join('; '));
    const response = await fetch(url, { ...options, headers, redirect: 'error', signal: AbortSignal.timeout(10000) });
    for (const cookie of response.headers.getSetCookie()) {
      const first = cookie.split(';')[0], separator = first.indexOf('=');
      if (separator > 0) cookies.set(first.slice(0, separator), first.slice(separator + 1));
    }
    return { status: () => response.status, ok: () => response.ok, json: () => response.json() };
  };
  const request = {
    get: url => send(url),
    post: (url, options) => send(url, { method: 'POST', headers: { ...options.headers, 'Content-Type': 'application/x-www-form-urlencoded' }, body: new URLSearchParams(options.form) }),
  };
  if (!await ensureAuthenticated(request, base)) return {};
  const session = await (await request.get(new URL('/api/auth/session', base).toString())).json();
  return { Cookie: [...cookies].map(([name,value]) => name + '=' + value).join('; '), [session.csrf.headerName]: session.csrf.token };
}
module.exports = { ensureAuthenticated, authenticationHeaders, trustedOrigin };
