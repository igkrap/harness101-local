"""The running framework as a tool: ask what it can do, read and write definitions, use the data API.

The harness holds no rules about screens or fields of its own. What a definition may contain comes
from GET /api/meta/capabilities, and whether a definition is acceptable is decided by the framework
when the definition is sent to it.
"""
import http.cookiejar
import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'platform')) if str(Path(__file__).resolve().parents[1] / 'platform') not in sys.path else None
from sites import site      # the project in hand: its server, its screens' address, the account to look with


def app_url():
    """Where the project's screens are served (for looking at them in a browser)."""
    return site().preview_url.rstrip('/')


class Failed(Exception):
    def __init__(self, status, message):
        super().__init__(f'{status}: {message}')
        self.status, self.message = status, message


class Framework:
    def __init__(self, base=None):
        self.base = base or site().api_url
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.csrf = {}
        self._sign_in()

    def _raw(self, method, path, body=None, form=None):
        headers = dict(self.csrf)
        data = None
        if form is not None:
            data = urllib.parse.urlencode(form).encode(); headers['Content-Type'] = 'application/x-www-form-urlencoded'
        elif body is not None:
            data = json.dumps(body, ensure_ascii=False).encode('utf-8'); headers['Content-Type'] = 'application/json'
        request = urllib.request.Request(self.base + urllib.parse.quote(path, safe='/?=&%'), data=data, method=method, headers=headers)
        try:
            with self.opener.open(request, timeout=30) as response:
                text = response.read().decode('utf-8')
                return response.status, (json.loads(text) if text else None)
        except urllib.error.HTTPError as error:
            text = error.read().decode('utf-8', 'replace')
            try:
                detail = json.loads(text)
            except ValueError:
                detail = {'detail': text[:300]}
            return error.code, detail

    def _sign_in(self):
        account = json.loads(site().credentials.read_text())
        self.username = account['username']
        _, session = self._raw('GET', '/api/auth/session')
        self.csrf = {session['csrf']['headerName']: session['csrf']['token']}
        status, _ = self._raw('POST', '/api/auth/login', form={'username': account['username'], 'password': account['password']})
        if status != 200:
            raise Failed(status, 'sign-in for checks failed')
        _, session = self._raw('GET', '/api/auth/session')
        self.csrf = {session['csrf']['headerName']: session['csrf']['token']}

    def call(self, method, path, body=None):
        """(status, json). Never raises for 4xx: a refusal is an answer the caller wants to look at."""
        status, data = self._raw(method, path, body)
        if status == 401:
            # One live session per account: the browser check signs in with the same account and ends this one.
            self._sign_in()
            status, data = self._raw(method, path, body)
        return status, data

    def ok(self, method, path, body=None):
        status, data = self.call(method, path, body)
        if status >= 400:
            raise Failed(status, (data or {}).get('detail') or (data or {}).get('message') or str(data)[:300])
        return data

    def capabilities(self):
        return self.ok('GET', '/api/meta/capabilities')

    def definitions(self):
        return self.ok('GET', '/api/meta/definitions?drafts=true')

    def save_definition(self, key, definition, status):
        return self.ok('PUT', f'/api/system/definitions/{key}', {'definition': definition, 'status': status})

    def validate_definition(self, key, definition):
        """The framework's judgement of a definition as it would be saved under this key; nothing is stored."""
        return self.ok('PUT', f'/api/system/definitions/{key}?validate=true', {'definition': definition})

    def delete_definition(self, key, force=False):
        return self.call('DELETE', f'/api/system/definitions/{key}' + ('?force=true' if force else ''))

    def codes(self, group):
        return (self.ok('GET', f'/api/auth/codes?groups={group}') or {}).get(group, [])
