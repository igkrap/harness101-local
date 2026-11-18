#!/usr/bin/env python3
"""The platform from a command line - for a person in a terminal and for an agent working on the projects.

Everything here goes through the running platform (http://127.0.0.1:5293), the same way its pages do: the same
queue (one piece of work at a time), the same checks, the same records in the run history. Nothing reaches into a
project's git, database or containers on its own. Answers are JSON on standard output; the exit code is 0 only when
the thing asked for was done.

  ctl.py projects                                   the projects and the kinds a new one can be
  ctl.py create <slug> "<name>" [--kind business] [--api-port N --preview-port N]   a new project with the base framework (ports: the first free ones unless given)
  ctl.py framework                                  the platform's framework and where every project stands with it
  ctl.py framework-update                           bring every project to the platform's framework now (it also happens by itself)
  ctl.py ports                                      the free ports for a new project's services (api / preview)
  ctl.py rename <slug> [--title "<name>"] [--slug <new>]   another name: the one people see, and/or the English one (folder, database, server, packs)
  ctl.py remove <slug> --confirm <slug>             a project away for good (its packs are kept)
  ctl.py status [-p slug]                           git (work space, remote, unrecorded changes), packs, what the newest pack lacks
  ctl.py screens [-p slug]                          the screens the development site holds (key, title, fields)
  ctl.py screen <key> [--rev <commit>] [-p slug]    one screen in full; with --rev as that record held it and what differs from now
  ctl.py records <key> [-p slug]                    the newest records of a screen (read only)
  ctl.py server-log [-p slug]                       the last lines of the project's development server
  ctl.py ask "<request>" [-p slug]                  a request in plain words, as typed into the request box (the local model makes the screen)
  ctl.py apply "<request>" --file <json> [-p slug]  a definition already written ({action,key,definition}): checked, applied and committed without asking the model
  ctl.py commit [-m "message"] [-p slug]            record what the development site holds
  ctl.py undo [--sha <commit>] [-p slug]            take a recorded change back (the newest by default); the site follows
  ctl.py branch <name> [--create] [-p slug]         move to a work space, making it first with --create; the site follows
  ctl.py sync [-p slug]                             bring the development site to what git holds
  ctl.py remote <url> [-p slug] / ctl.py push       where the remote repository is / send the records there
  ctl.py log [-p slug]                              the last records
  ctl.py pack [-p slug]                             the setup packs of the current state (recorded first, tried by installing)
  ctl.py undo-request <queue id> [-p slug]          take back what one request applied (as the 되돌리기 button)
"""
import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = 'http://127.0.0.1:5293'


class Platform:
    def __init__(self, project=None):
        self.project_id = None
        try:
            state = self.call('GET', '/api/state')
        except OSError as error:
            raise SystemExit(json.dumps({'ok': False, 'error': f'플랫폼이 켜져 있지 않습니다 ({BASE}): {error}'}, ensure_ascii=False))
        self.token = state.get('token') or state.get('platform_token')
        self.catalog = self.call('GET', '/api/projects')
        if project:
            found = next((item for item in self.catalog['projects'] if project in (item['id'], item['name'], (item.get('site') or {}).get('slug'))), None)
            if not found:
                raise SystemExit(json.dumps({'ok': False, 'error': f'프로젝트를 찾지 못했습니다: {project}'}, ensure_ascii=False))
            self.project_id = found['id']

    def call(self, method, path, body=None, timeout=1800):
        if self.project_id:
            path += ('&' if '?' in path else '?') + 'project=' + urllib.parse.quote(self.project_id)
        headers = {'Content-Type': 'application/json'}
        if getattr(self, 'token', None):
            headers['X-Platform-Token'] = self.token
        request = urllib.request.Request(BASE + path, data=json.dumps(body).encode() if body is not None else None, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as answer:
                return json.load(answer)
        except urllib.error.HTTPError as error:
            text = error.read().decode(errors='replace')
            try:
                problem = json.loads(text).get('error') or text
            except ValueError:
                problem = text
            raise RuntimeError(str(problem)[:800])

    def order(self, goal, order=None, wait=10800):
        """Put one piece of work in the queue and wait for it. Returns the finished queue."""
        queue = self.call('POST', '/api/queues', {'goal': goal, **({'order': order} if order else {})})
        end = time.time() + wait
        while time.time() < end:
            time.sleep(1 if order else 4)
            current = self.call('GET', '/api/queues/' + queue['id'])
            current = current.get('queue', current)
            if current['status'] not in ('planning', 'running', 'stopping'):
                return current
        raise RuntimeError('기다리는 시간이 지났습니다. 플랫폼에서 진행 상황을 확인하세요.')


def show(queue):
    result = queue.get('release_result') or queue.get('definition_result') or {}
    ok = queue['status'] == 'succeeded'
    print(json.dumps({'ok': ok, 'status': queue['status'], 'said': queue.get('detail', ''), 'queue': queue['id'], 'route': queue.get('route'),
                      'result': {key: value for key, value in result.items() if key not in ('shipped',)}}, ensure_ascii=False, indent=1))
    return 0 if ok else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('command', choices=['projects', 'ports', 'create', 'rename', 'remove', 'status', 'screens', 'screen', 'records', 'server-log', 'apply', 'ask', 'commit', 'undo', 'branch', 'sync', 'remote', 'push', 'log', 'pack', 'undo-request', 'framework', 'framework-update'])
    parser.add_argument('values', nargs='*')
    parser.add_argument('-p', '--project')
    parser.add_argument('-m', '--message')
    parser.add_argument('--kind', default='business')
    parser.add_argument('--api-port', dest='api_port', default=None)
    parser.add_argument('--preview-port', dest='preview_port', default=None)
    parser.add_argument('--confirm')
    parser.add_argument('--title')
    parser.add_argument('--slug')
    parser.add_argument('--create', action='store_true')
    parser.add_argument('--sha')
    parser.add_argument('--rev')
    parser.add_argument('--file')
    args = parser.parse_args()
    platform = Platform(args.project)
    need = lambda count, what: len(args.values) >= count or parser.error(what)
    try:
        if args.command == 'projects':
            print(json.dumps({'ok': True, 'kinds': platform.catalog.get('kinds'), 'projects': [{'id': item['id'], 'slug': item['name'], 'title': (item.get('site') or {}).get('title') or item['name'],
                              'root': item['root'], 'site': item.get('site')} for item in platform.catalog['projects']]}, ensure_ascii=False, indent=1))
            return 0
        if args.command == 'create':
            need(2, 'create <slug> "<name>"')
            made = platform.call('POST', '/api/projects/create', {'slug': args.values[0], 'title': args.values[1], 'kind': args.kind,
                                                                   'api_port': args.api_port, 'preview_port': args.preview_port})
            print(json.dumps({'ok': True, 'project': made}, ensure_ascii=False, indent=1))
            return 0
        if args.command in ('framework', 'framework-update'):
            said = platform.call('POST', '/api/framework/update', {}, timeout=7200) if args.command == 'framework-update' else platform.call('GET', '/api/framework')
            print(json.dumps({'ok': all(item.get('state') in ('ok', 'waiting') for item in said['projects']), **said}, ensure_ascii=False, indent=1))
            return 0
        if args.command == 'ports':
            print(json.dumps({'ok': True, 'free': platform.call('GET', '/api/projects/ports')}, ensure_ascii=False, indent=1))
            return 0
        if args.command == 'rename':
            need(1, 'rename <slug> [--title ...] [--slug ...]')
            target = Platform(args.values[0])
            done = platform.call('POST', '/api/projects/rename', {'id': target.project_id or 'default', 'title': args.title, 'slug': args.slug})
            print(json.dumps({'ok': True, 'project': done}, ensure_ascii=False, indent=1))
            return 0
        if args.command == 'remove':
            need(1, 'remove <slug> --confirm <slug>')
            target = Platform(args.values[0])
            print(json.dumps({'ok': True, **platform.call('POST', '/api/projects/remove', {'id': target.project_id, 'confirm': args.confirm})}, ensure_ascii=False, indent=1))
            return 0
        if args.command == 'status':
            print(json.dumps({'ok': True, **platform.call('GET', '/api/release')['status']}, ensure_ascii=False, indent=1))
            return 0
        if args.command == 'screens':
            print(json.dumps({'ok': True, **platform.call('GET', '/api/release/screens')}, ensure_ascii=False, indent=1))
            return 0
        if args.command == 'screen':
            need(1, 'screen <key>')
            print(json.dumps({'ok': True, **platform.call('GET', '/api/tools/screen?key=' + urllib.parse.quote(args.values[0]) + ('&rev=' + urllib.parse.quote(args.rev) if args.rev else ''))}, ensure_ascii=False, indent=1))
            return 0
        if args.command == 'records':
            need(1, 'records <key>')
            print(json.dumps({'ok': True, **platform.call('GET', '/api/tools/records?key=' + urllib.parse.quote(args.values[0]))}, ensure_ascii=False, indent=1))
            return 0
        if args.command == 'server-log':
            print(json.dumps({'ok': True, **platform.call('GET', '/api/tools/log')}, ensure_ascii=False, indent=1))
            return 0
        if args.command == 'apply':
            need(1, 'apply "<request>" --file <json>')
            import os
            return show(platform.order(args.values[0], {'kind': 'replay', 'file': os.path.abspath(args.file or '')}))
        if args.command == 'ask':
            need(1, 'ask "<request>"')
            return show(platform.order(args.values[0]))
        if args.command == 'undo-request':
            need(1, 'undo-request <queue id>')
            print(json.dumps({'ok': True, **platform.call('POST', f'/api/queues/{args.values[0]}/undo', {})}, ensure_ascii=False, indent=1))
            return 0
        orders = {'commit': lambda: {'kind': 'record', **({'message': args.message} if args.message else {})},
                  'undo': lambda: {'kind': 'git-undo', **({'sha': args.sha} if args.sha else {})},
                  'branch': lambda: (need(1, 'branch <name>'), {'kind': 'git-branch', 'name': args.values[0], 'create': args.create})[1],
                  'sync': lambda: {'kind': 'git-sync'}, 'push': lambda: {'kind': 'git-push'}, 'log': lambda: {'kind': 'git-log'}, 'pack': lambda: {'kind': 'pack'},
                  'remote': lambda: (need(1, 'remote <url>'), {'kind': 'git-remote', 'url': args.values[0]})[1]}
        order = orders[args.command]()
        return show(platform.order(f"[도구] {args.command} {' '.join(args.values)}".strip(), order))
    except RuntimeError as error:
        print(json.dumps({'ok': False, 'error': str(error)}, ensure_ascii=False, indent=1))
        return 1


if __name__ == '__main__':
    sys.exit(main())
