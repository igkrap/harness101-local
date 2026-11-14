/**
 * The platform as a desktop app: one window instead of a browser tab, and the things the platform needs are looked
 * after from here - the platform's own server, the preview of the first project's screens, the development database
 * and app server (Docker containers) and the local model's server.
 *
 * Each is started only when it is not already answering, so the app can be opened beside a platform that was started
 * by hand. When the app quits it stops what it started itself - except the local model's server, which is left
 * running (loading the model takes a minute and other work may be using it); the menu can stop it.
 */
const { app, BrowserWindow, Menu, shell, dialog, nativeImage } = require('electron');
const { spawn, execFile, execFileSync } = require('child_process');
const http = require('http');
const path = require('path');
const fs = require('fs');

const PLATFORM = path.resolve(__dirname, '..');
const ROOT = path.resolve(PLATFORM, '..');
const STATE = path.join(PLATFORM, 'state');
const URLS = { platform: 'http://127.0.0.1:5293', preview: 'http://127.0.0.1:5292', model: 'http://127.0.0.1:8099/v1/models' };
const SMOKE = process.argv.includes('--smoke');
const started = {};          // what this app started: name -> child process
let win = null, quitting = false;

// An app opened from the Dock has a bare PATH: take the one a terminal would have, so node, python and docker are found.
function shellPath() {
  try { return execFileSync(process.env.SHELL || '/bin/zsh', ['-lc', 'printf %s "$PATH"'], { encoding: 'utf8', timeout: 8000 }).trim() || process.env.PATH; }
  catch { return process.env.PATH; }
}
const ENV = { ...process.env, PATH: [shellPath(), '/opt/homebrew/bin', '/usr/local/bin', '/usr/bin', '/bin'].join(':') };

function answers(url, timeout = 2000) {
  return new Promise(resolve => {
    const request = http.get(url, { timeout }, response => { response.resume(); resolve(response.statusCode < 500); });
    request.on('timeout', () => { request.destroy(); resolve(false); });
    request.on('error', () => resolve(false));
  });
}
async function until(url, seconds) {
  for (let waited = 0; waited < seconds; waited += 1) { if (await answers(url)) return true; await new Promise(done => setTimeout(done, 1000)); }
  return false;
}
function log(name) { fs.mkdirSync(STATE, { recursive: true }); return fs.openSync(path.join(STATE, `desktop-${name}.log`), 'a'); }
function run(name, command, args, cwd, detached = false) {
  const out = log(name);
  const child = spawn(command, args, { cwd, env: ENV, stdio: ['ignore', out, out], detached });
  child.on('error', error => { fs.writeSync(out, `\n[desktop] ${name} 시작 실패: ${error.message}\n`); });
  child.on('exit', () => { if (started[name] === child) delete started[name]; });
  if (detached) child.unref(); else started[name] = child;
  return child;
}

/** Bring up whatever is not answering. Returns what was found wrong, in plain words (empty when all is well). */
async function bringUp(tell) {
  const problems = [];
  tell('도커(개발 DB와 앱 서버) 확인');
  await new Promise(done => execFile('docker', ['start', 'mdi-db', 'mdi-local-api'], { env: ENV, timeout: 30000 }, error => {
    if (error) problems.push('도커가 꺼져 있거나 개발 DB·앱 서버 컨테이너가 없습니다. 도커를 켠 뒤 메뉴의 "다시 확인"을 누르세요.');
    done();
  }));
  if (!(await answers(URLS.model))) {
    const script = path.join(PLATFORM, 'scripts/qwen-serve-forever.sh');
    if (fs.existsSync(script)) { tell('로컬 모델 서버 켜는 중 (모델을 올리는 데 1분쯤 걸립니다)'); run('model', script, [], PLATFORM, true); }
    else problems.push('로컬 모델 서버를 켜는 스크립트가 없습니다.');
  }
  if (!(await answers(URLS.preview))) {
    const frontend = path.join(ROOT, 'local-only/frontend');
    if (fs.existsSync(path.join(frontend, 'node_modules/vite/bin/vite.js'))) { tell('앱 화면(미리보기) 켜는 중'); run('preview', 'node', ['node_modules/vite/bin/vite.js', '--host', '127.0.0.1', '--port', '5292', '--strictPort'], frontend); }
  }
  if (!(await answers(URLS.platform + '/api/state'))) {
    if (!fs.existsSync(path.join(PLATFORM, 'web/dist/index.html'))) {
      tell('플랫폼 화면 빌드');
      await new Promise(done => execFile('npm', ['--prefix', path.join(PLATFORM, 'web'), 'run', 'build'], { env: ENV, timeout: 300000 }, () => done()));
    }
    tell('플랫폼 서버 켜는 중');
    run('platform', 'python3', ['server.py'], PLATFORM);
    if (!(await until(URLS.platform + '/api/state', 60))) problems.push(`플랫폼 서버가 켜지지 않았습니다. ${path.join(STATE, 'desktop-platform.log')} 를 확인하세요.`);
  }
  return problems;
}

async function status() {
  const [platform, preview, model] = await Promise.all([answers(URLS.platform + '/api/state'), answers(URLS.preview), answers(URLS.model)]);
  const docker = await new Promise(done => execFile('docker', ['inspect', '-f', '{{.State.Running}}', 'mdi-db', 'mdi-local-api'], { env: ENV, timeout: 10000 }, (error, out) => done(!error && out.trim().split('\n').every(line => line === 'true'))));
  return { platform, preview, model, docker, mine: Object.keys(started) };
}

const loading = text => `data:text/html;charset=utf-8,${encodeURIComponent(`<!doctype html><meta charset="utf-8"><body style="margin:0;height:100vh;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:14px;font:14px -apple-system,'Apple SD Gothic Neo','Malgun Gothic',sans-serif;background:#f4f5f7;color:#1c2127"><div style="font-size:20px;font-weight:600">Local Workshop</div><div id="t">${text}</div></body>`)}`;
const tell = text => { if (win && !win.isDestroyed() && !win.webContents.getURL().startsWith('http')) win.webContents.executeJavaScript(`document.getElementById('t').textContent=${JSON.stringify(text)}`).catch(() => {}); };

async function open() {
  win = new BrowserWindow({ width: 1480, height: 940, minWidth: 1000, minHeight: 640, title: 'Local Workshop', show: !SMOKE, backgroundColor: '#f4f5f7',
    webPreferences: { contextIsolation: true, nodeIntegration: false, sandbox: true } });
  // Pages of the platform (and the app's own screens it previews) stay in the window; anything else goes to the browser.
  const inside = url => /^http:\/\/(127\.0\.0\.1|localhost)(:\d+)?\//.test(url);
  win.webContents.setWindowOpenHandler(({ url }) => { if (inside(url)) return { action: 'allow' }; shell.openExternal(url); return { action: 'deny' }; });
  win.webContents.on('will-navigate', (event, url) => { if (!inside(url) && !url.startsWith('data:')) { event.preventDefault(); shell.openExternal(url); } });
  await win.loadURL(loading('준비하는 중…'));
  const problems = await bringUp(tell);
  if (await answers(URLS.platform + '/api/state')) await win.loadURL(URLS.platform + '/');
  else await win.loadURL(loading('플랫폼을 켜지 못했습니다.<br><br>' + problems.join('<br>')));
  if (problems.length && !SMOKE && (await answers(URLS.platform + '/api/state'))) dialog.showMessageBox(win, { type: 'warning', message: '일부가 준비되지 않았습니다', detail: problems.join('\n') });
  if (SMOKE) {      // a run without a person: say what happened, keep a picture, and leave
    await new Promise(done => setTimeout(done, 3500));
    const picture = await win.webContents.capturePage().catch(() => null);
    const file = path.join(STATE, 'desktop-smoke.png');
    if (picture) fs.writeFileSync(file, picture.toPNG());
    const inner = await win.webContents.executeJavaScript('({ title: document.title, heading: (document.querySelector(".home-ask h1")||{}).innerText || "", text: document.body.innerText.slice(0, 200) })').catch(error => ({ error: String(error) }));
    console.log('SMOKE ' + JSON.stringify({ url: win.webContents.getURL(), ...inner, problems, status: await status(), picture: picture ? file : null }));
    app.quit();
  }
}

function menu() {
  const say = async () => { const now = await status(); const mark = ok => (ok ? '켜짐' : '꺼짐');
    dialog.showMessageBox(win, { type: 'info', message: '상태', detail: `플랫폼 서버: ${mark(now.platform)}\n앱 화면(미리보기): ${mark(now.preview)}\n도커(개발 DB·앱 서버): ${mark(now.docker)}\n로컬 모델 서버: ${mark(now.model)}\n\n이 앱이 켠 것: ${now.mine.join(', ') || '없음'}` }); };
  const again = async () => { const problems = await bringUp(() => {}); if (win && (await answers(URLS.platform + '/api/state'))) win.loadURL(URLS.platform + '/');
    if (problems.length) dialog.showMessageBox(win, { type: 'warning', message: '준비되지 않은 것이 있습니다', detail: problems.join('\n') }); };
  const stopModel = () => { for (const name of ['qwen-supervisor.pid', 'qwen-model-server.pid']) { try { process.kill(Number(fs.readFileSync(path.join(STATE, name), 'utf8').trim())); } catch { /* not running */ } } };
  Menu.setApplicationMenu(Menu.buildFromTemplate([
    { label: 'Local Workshop', submenu: [{ label: '상태 보기', click: say }, { label: '다시 확인 (꺼진 것 켜기)', click: again }, { type: 'separator' },
      { label: '기록 폴더 열기', click: () => shell.openPath(STATE) }, { label: '로컬 모델 서버 끄기', click: stopModel }, { type: 'separator' }, { role: 'hide', label: '숨기기' }, { role: 'quit', label: '끝내기' }] },
    { label: '편집', submenu: [{ role: 'undo', label: '되돌리기' }, { role: 'redo', label: '다시 하기' }, { type: 'separator' }, { role: 'cut', label: '잘라내기' }, { role: 'copy', label: '복사' }, { role: 'paste', label: '붙여넣기' }, { role: 'selectAll', label: '모두 선택' }] },
    { label: '보기', submenu: [{ role: 'reload', label: '새로 고침' }, { role: 'resetZoom', label: '원래 크기' }, { role: 'zoomIn', label: '크게' }, { role: 'zoomOut', label: '작게' }, { type: 'separator' }, { role: 'togglefullscreen', label: '전체 화면' }, { role: 'toggleDevTools', label: '개발자 도구' }] },
    { label: '창', submenu: [{ role: 'minimize', label: '최소화' }, { role: 'close', label: '창 닫기' }] },
  ]));
}

if (!app.requestSingleInstanceLock()) app.quit();
else {
  app.on('second-instance', () => { if (win) { if (win.isMinimized()) win.restore(); win.focus(); } });
  app.whenReady().then(() => { menu(); return open(); });
  app.on('activate', () => { if (BrowserWindow.getAllWindows().length === 0) open(); });
  app.on('window-all-closed', () => { if (process.platform !== 'darwin' || SMOKE) app.quit(); });
  // What this app started goes with it (the model's server was started apart from it, on purpose).
  app.on('before-quit', () => { if (quitting) return; quitting = true; for (const child of Object.values(started)) { try { child.kill('SIGTERM'); } catch { /* gone */ } } });
}
