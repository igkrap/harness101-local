"""Do the framework's screens score 90 or more in Lighthouse (performance, accessibility, best practices)?

The framework draws every screen, so this is a check of the framework: run it after changing it. The screens are built the way a
setup pack builds them (a development preview is not optimised and would say nothing about operation), served beside the
development server's API, and measured signed in as the platform's checking account - the home page, and one screen of every kind
the project has (a form, a master with details, a take-over list, a stock view, a summary ...).

Run: python3 tests/lighthouse_check.py [--keep]     (needs Lighthouse in ~/.local/share/local-workshop/tools/lighthouse)
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'harness2'))
sys.path.append(str(ROOT / 'platform'))
from framework import Framework, site  # noqa: E402

LIGHTHOUSE = Path.home() / '.local/share/local-workshop/tools/lighthouse/node_modules/.bin/lighthouse'
LEAST = 90
CATEGORIES = ('performance', 'accessibility', 'best-practices')


def chrome():
    found = sorted((Path.home() / 'Library/Caches/ms-playwright').glob('chromium-*/chrome-mac*/*.app/Contents/MacOS/*'))
    return str(found[-1]) if found else os.environ.get('CHROME_PATH', '')


def kind(definition):
    for part, word in (('take', '이어받기'), ('stockView', '재고 보기'), ('summary', '집계'), ('dashboard', '현황판'), ('over', '업무 화면'), ('calendar', '달력'), ('tree', '트리')):
        if definition.get(part):
            return word
    return '마스터-디테일' if definition.get('lines') else '업무(번호·상태)' if definition.get('status') or any(f.get('type') == 'serial' for f in definition.get('fields', [])) else '기준 정보'


def main():
    if not LIGHTHOUSE.exists():
        print(f'Lighthouse 가 없습니다: {LIGHTHOUSE}')
        return 2
    framework = Framework()
    framework.ok('GET', '/api/auth/session')
    cookie = next('; '.join(f'{c.name}={c.value}' for c in handler.cookiejar) for handler in framework.opener.handlers if hasattr(handler, 'cookiejar'))
    work = Path(tempfile.mkdtemp(prefix='lighthouse-'))
    built = work / 'dist'
    frontend = Path(site().root) / 'frontend'
    done = subprocess.run(['npx', 'vite', 'build', '--outDir', str(built), '--emptyOutDir'], cwd=frontend, capture_output=True, text=True, timeout=600)
    if done.returncode:
        print('빌드 실패', done.stderr[-800:])
        return 1
    port = 5398
    server = subprocess.Popen(['node', str(Path(__file__).with_name('lighthouse_serve.mjs')), str(built), str(port), str(site().api_port)], cwd=str(work), stdout=subprocess.PIPE, text=True)
    server.stdout.readline()
    headers = work / 'headers.json'
    headers.write_text(json.dumps({'Cookie': cookie}))
    # one screen of every kind the project has (the first of each), and the home page
    picked = {}
    for item in framework.definitions():
        picked.setdefault(kind(item['definition']), item)
    targets = [('홈', '')] + [(f"{word}: {item['definition']['title']}", f"#open={item['programCode']}") for word, item in picked.items()]
    results, failed = [], []
    try:
        for name, address in targets:
            out = work / 'report.json'
            run = subprocess.run([str(LIGHTHOUSE), f'http://127.0.0.1:{port}/{address}', f'--extra-headers={headers}', '--output=json', f'--output-path={out}',
                                  '--only-categories=' + ','.join(CATEGORIES), '--chrome-flags=--headless=new --no-sandbox', '--quiet', '--preset=desktop'],
                                 env=dict(os.environ, CHROME_PATH=chrome()), capture_output=True, text=True, timeout=300)
            if run.returncode:
                print(f'  실패  {name}: Lighthouse 를 돌리지 못했습니다 {run.stderr[-300:]}')
                failed.append(name)
                continue
            report = json.loads(out.read_text())
            scores = {key: round((value['score'] or 0) * 100) for key, value in report['categories'].items()}
            low = []
            for category, value in scores.items():
                if value < 100:     # below the line it is why it failed; above it, what still costs points
                    for audit in (ref['id'] for ref in report['categories'][category]['auditRefs'] if ref['weight'] > 0):
                        if report['audits'][audit]['score'] is not None and report['audits'][audit]['score'] < 0.9:
                            low.append(f"{category}: {report['audits'][audit]['title']}")
            ok = all(value >= LEAST for value in scores.values())
            print(f"  {'통과' if ok else '실패'}  {name}  " + '  '.join(f'{key} {value}' for key, value in scores.items()) + ('\n          ' + ('' if ok else '') + '\n          '.join(low[:8]) if low else ''))
            results.append(ok)
            if not ok:
                failed.append(name)
    finally:
        server.terminate()
        if '--keep' not in sys.argv:
            shutil.rmtree(work, ignore_errors=True)
    print(f'\n{sum(results)}/{len(targets)} 통과 (기준: 세 영역 모두 {LEAST} 이상)' + (' · 실패: ' + ', '.join(failed) if failed else ''))
    return 0 if not failed else 1


if __name__ == '__main__':
    sys.exit(main())
