const { isDeepStrictEqual } = require('node:util');

module.exports = {
  run: async (check, base, allowWrites) => {
    const evidence = { method: check.method, path: check.path, status: null, expectedStatus: check.status, actualValue: null };
    try {
      if (!base) throw new Error('missing base');
      const url = new URL(check.path, base);
      if (url.origin !== new URL(base).origin) throw new Error('origin mismatch');
      if (!['localhost', '127.0.0.1', '[::1]'].includes(url.hostname)) throw new Error('non localhost');
      if (url.pathname.includes('\\') || /[\x00-\x1F]/.test(url.pathname)) throw new Error('invalid path');

      if (check.method !== 'GET' && !allowWrites) return { status: 'unverified', reason: 'isolation required', evidence };

      const options = {
        method: check.method,
        headers: { ...(check.status === 401 ? {} : await require('./trusted_auth.cjs').authenticationHeaders(base)), ...(check.headers || {}) },
        signal: AbortSignal.timeout(10000),
        redirect: 'error'
      };
      if (check.body !== undefined && check.method !== 'GET') {
        options.body = JSON.stringify(check.body);
        options.headers['Content-Type'] = 'application/json';
      }

      const res = await fetch(url.toString(), options);
      evidence.status = res.status;
      evidence.expectedStatus = check.status;

      if (res.status !== check.status) return { status: 'failed', reason: 'status mismatch', evidence: JSON.stringify(evidence, null, 2).slice(0, 2000) };

      let actualValue = null;
      if (check.json_path || check.equals !== undefined) {
        const text = await res.text();
        actualValue = text ? JSON.parse(text) : null;
        evidence.actualValue = actualValue;

        if (check.json_path) {
          if (check.equals === undefined) return { status: 'failed', reason: 'missing equals for json_path', evidence };
          let current = actualValue;
          for (const key of check.json_path) {
            current = current?.[key];
          }
          if (!isDeepStrictEqual(current, check.equals)) {
            return { status: 'failed', reason: 'json_path mismatch', evidence: JSON.stringify(evidence, null, 2).slice(0, 2000) };
          }
        } else if (!isDeepStrictEqual(actualValue, check.equals)) {
          return { status: 'failed', reason: 'body mismatch', evidence: JSON.stringify(evidence, null, 2).slice(0, 2000) };
        }
      }

      return { status: 'passed', reason: '', evidence };
    } catch (err) {
      return { status: 'failed', reason: err.message, evidence: JSON.stringify(evidence, null, 2).slice(0, 2000) };
    }
  }
};
