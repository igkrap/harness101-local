"""Which project is being worked on, and what belongs to it.

Every project made on the platform has its own working set: a development database, the app's server (a container
and a port), the address its screens are previewed at, its sign-in files, and the names its setup packs carry. The
modules that build, deploy, check and pack ask `site()` for these instead of holding one project's names.

The project in hand is set for the length of a piece of work with `with use(site): ...` (per thread: a request box
order runs in the queue's thread, a page's question in its own). Outside any such block it is the first project,
local-only, with the names it has always had - so tools run by hand keep working as before.
"""
import contextvars
import re
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SHARE = Path.home() / '.local/share/local-workshop'
DB_CONTAINER, DB_USER, NETWORK, PUBLIC_NETWORK, MAVEN_CACHE = 'mdi-db', 'mdi', 'mdi-internal', 'mdi-public', 'mdi-m2'

# The kinds of site a new project can be. Only those with a template can be made; the others are shown locked
# (the user's decision, 2026-11-14: 쇼핑몰 and 홈페이지 stay listed, locked for now).
KINDS = [
    {'id': 'business', 'label': '업무 사이트', 'description': '기준 정보, 등록·조회 화면, 집계와 현황판, 권한과 메뉴를 갖춘 사내 업무 시스템', 'enabled': True},        # made from the first project (the reference the framework is developed in)
    {'id': 'shop', 'label': '쇼핑몰 사이트', 'description': '상품, 장바구니, 주문과 결제', 'enabled': False},
    {'id': 'homepage', 'label': '홈페이지 사이트', 'description': '회사 소개, 공지, 문의', 'enabled': False},
]
SLUG = re.compile(r'[a-z][a-z0-9-]{1,23}[a-z0-9]')


@dataclass(frozen=True)
class Site:
    slug: str                 # letters for folders, containers, databases and pack names: 'local-only', 'acme-erp'
    title: str                # the name people see: '에이스 업무 시스템'
    kind: str
    root: Path                # the project's folder
    state: Path               # where the platform keeps this project's runs, sign-in files, releases
    db: str                   # development database (in the shared database container)
    api_container: str
    api_port: int
    preview_url: str          # where the app's screens are served while they are being made
    ops_port: int             # this machine's own operating copy
    first: bool = False       # the project the platform started with: it keeps the platform's own state folder and is the reference new projects are copied from

    @property
    def api_url(self):
        return f'http://127.0.0.1:{self.api_port}'

    @property
    def test_db(self):
        return self.db + '_test'

    @property
    def artifacts(self):
        return SHARE / 'artifacts' / self.slug / 'backend'

    @property
    def backups(self):
        return SHARE / 'backups' / self.slug

    @property
    def packs(self):
        return SHARE / 'packs' / self.slug

    @property
    def ops_home(self):
        return SHARE / 'prod' / self.slug

    @property
    def ops_project(self):       # the compose project of this machine's operating copy
        return self.slug + '-ops'

    @property
    def ops_url(self):
        return f'http://127.0.0.1:{self.ops_port}'

    @property
    def credentials(self):       # the platform's own account for checking this project's screens
        return self.state / 'auth/verifier-login.json'

    @property
    def service(self):           # default name of the Windows services and of the install folder in a setup pack
        return re.sub(r'[^A-Z0-9]+', '-', self.slug.upper()).strip('-')


# The names the first project had before projects carried their own (used only until its record says otherwise).
DEFAULT = Site('local-only', 'local-only', 'business', ROOT / 'local-only', ROOT / 'platform/state', 'mdi_local', 'mdi-local-api', 8083, 'http://127.0.0.1:5292', 5300, True)
FIRST_OWN = {'slug': 'local-only', 'kind': 'business', 'db': 'mdi_local', 'api_container': 'mdi-local-api', 'api_port': 8083, 'preview_port': 5292, 'ops_port': 5300, 'first': True}
_current = contextvars.ContextVar('site', default=None)
_first = {'stamp': None, 'site': DEFAULT}


def default():
    """The first project as its record says (it can be renamed like any other): what a tool run by hand works on."""
    path = ROOT / 'platform/state/projects.json'
    try:
        stamp = path.stat().st_mtime_ns
        if stamp != _first['stamp']:
            import json
            _first.update(stamp=stamp, site=of(json.loads(path.read_text(encoding='utf-8'))[0], ROOT / 'platform/state'))
    except (OSError, ValueError, IndexError, KeyError):
        pass
    return _first['site']


def site():
    return _current.get() or default()


@contextmanager
def use(chosen):
    token = _current.set(chosen)
    try:
        yield chosen or default()
    finally:
        _current.reset(token)


def of(record, state):
    """The working set of a registered project (its record in projects.json). A project without one of its own is the first project."""
    own = (record or {}).get('site')
    if not own:        # a record from before projects carried their names: the first project as it was
        import dataclasses
        return dataclasses.replace(DEFAULT, title=record['title']) if (record or {}).get('title') else DEFAULT
    return Site(own['slug'], own.get('title') or own['slug'], own.get('kind', 'business'), Path(record['root']), Path(state), own['db'], own['api_container'],
                int(own['api_port']), f"http://127.0.0.1:{int(own['preview_port'])}", int(own['ops_port']), bool(own.get('first')))


def of_app(app):
    return of(getattr(app, 'metadata', None), getattr(app, 'state', DEFAULT.state)) if getattr(app, 'metadata', None) else default()
