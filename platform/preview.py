"""Discover the selected project's server or own a separate Vite process."""
import json
import os
from pathlib import Path
import signal
import subprocess
import threading
import time
import urllib.request

BASE=Path(__file__).resolve().parent


def environment():
    env=os.environ.copy()
    node=Path.home()/'.nvm/versions/node/v22.15.0/bin'
    env['PATH']=str(node)+os.pathsep+env.get('PATH','')
    env['BROWSER']='none'
    return env


def find_running(frontend):
    """Match the listener's cwd, never guess which app occupies a port."""
    result=subprocess.run(['lsof','-nP','-iTCP','-sTCP:LISTEN','-Fpcn'],capture_output=True,text=True,timeout=4)
    pid,command=None,''
    candidates=[]
    for line in result.stdout.splitlines():
        if line.startswith('p'): pid=line[1:]
        elif line.startswith('c'): command=line[1:]
        elif line.startswith('n') and pid and any(x in command.lower() for x in ('node','bun','deno')):
            port=line.rsplit(':',1)[-1]
            if port.isdigit(): candidates.append((pid,port))
    checked={}
    for pid,port in candidates:
        if pid not in checked:
            cwd=subprocess.run(['lsof','-a','-p',pid,'-d','cwd','-Fn'],capture_output=True,text=True,timeout=3)
            checked[pid]=any(line.startswith('n') and Path(line[1:]).resolve()==frontend.resolve() for line in cwd.stdout.splitlines())
        if checked[pid]:
            url='http://127.0.0.1:'+port+'/'
            if healthy(url): return url
    return ''


def healthy(url):
    try:
        with urllib.request.urlopen(url,timeout=1) as response:return response.status==200
    except (OSError,ValueError):return False


class Previews:
    def __init__(self,state):
        self.folder=Path(state)/'previews';self.folder.mkdir(exist_ok=True)
        self.items={};self.lock=threading.RLock();self.closing=False

    def status(self,record):
        with self.lock:
            item=self.items.get(record['id'])
            if not item:return {'status':'idle','url':'','error':'','managed':False}
            process=item.get('process')
            if item['status']=='ready' and time.monotonic()-item.get('checked',0)>3:
                item['checked']=time.monotonic()
                if (process and process.poll() is not None) or not healthy(item['url']):
                    item.update(status='failed',error='미리보기 서버가 종료됐습니다.',url='')
            result={k:item[k] for k in ('status','url','error','managed')}
            if item['status']=='failed' and item.get('log'):
                try:
                    with Path(item['log']).open('rb') as stream:
                        stream.seek(0,2);stream.seek(max(0,stream.tell()-5000));result['output']=stream.read().decode('utf-8','replace')
                except OSError:pass
            return result

    def ensure(self,record):
        with self.lock:
            current=self.status(record)
            if current['status'] in ('starting','installing','ready'):return current
            if self.closing:raise RuntimeError('플랫폼이 종료 중입니다.')
            self.items[record['id']]={'status':'starting','url':'','error':'','managed':False,'log':str(self.folder/(record['id']+'.log'))}
            threading.Thread(target=self._start,args=(dict(record),),daemon=True).start()
            return self.status(record)

    def _spawn(self,command,frontend,item,extra=None,**kwargs):
        with self.lock:
            if self.closing:raise RuntimeError('플랫폼이 종료 중입니다.')
            process=subprocess.Popen(command,cwd=frontend,env={**environment(),**(extra or {})},start_new_session=True,**kwargs)
            item['process']=process;item['managed']=True
            return process

    def _start(self,record):
        item=self.items[record['id']];frontend=Path(record['root'])/'frontend'
        try:
            package=frontend/'package.json'
            if not package.is_file():raise ValueError('프론트엔드 package.json이 없어 미리보기를 실행할 수 없습니다.')
            metadata=json.loads(package.read_text())
            running=find_running(frontend)
            if running:
                with self.lock:item.update(status='ready',url=running,checked=time.monotonic())
                return
            dependencies={**metadata.get('dependencies',{}),**metadata.get('devDependencies',{})}
            vite=frontend/'node_modules/vite/dist/node/index.js'
            if 'vite' not in dependencies and not vite.is_file():raise ValueError('현재 자동 미리보기는 Vite 프로젝트를 지원합니다.')
            with Path(item['log']).open('w') as log:
                if not vite.is_file():
                    with self.lock:item['status']='installing'
                    command=['npm','ci' if (frontend/'package-lock.json').is_file() else 'install','--no-audit','--no-fund']
                    process=self._spawn(command,frontend,item,stdout=log,stderr=subprocess.STDOUT)
                    try:code=process.wait(timeout=600)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid,signal.SIGTERM);raise ValueError('의존성 설치 시간이 초과됐습니다.')
                    if code:raise ValueError('프론트엔드 의존성을 설치하지 못했습니다.')
                with self.lock:item['status']='starting'
                own=record.get('site') or {}
                extra={'PLATFORM_PREVIEW_PORT':str(own['preview_port']),'PLATFORM_PREVIEW_API':f"http://127.0.0.1:{own['api_port']}"} if own else None
                process=self._spawn(['node',str(BASE/'preview_server.mjs'),str(frontend)],frontend,item,extra=extra,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,bufsize=1)
                with process.stdout as output:
                    for line in output:
                        log.write(line);log.flush()
                        if line.startswith('PLATFORM_PREVIEW_READY '):
                            data=json.loads(line.split(' ',1)[1])
                            with self.lock:item.update(status='ready',url=data['url'],checked=time.monotonic())
                code=process.wait()
                if not self.closing:raise ValueError(f'미리보기 서버가 종료됐습니다. 종료 코드 {code}')
        except (OSError,ValueError,RuntimeError,subprocess.SubprocessError) as error:
            with self.lock:item.update(status='stopped' if self.closing else 'failed',error=str(error),url='')

    def close(self):
        with self.lock:
            self.closing=True
            processes=[i['process'] for i in self.items.values() if i.get('process') and i['process'].poll() is None]
        for process in processes:
            try:
                os.killpg(process.pid,signal.SIGTERM)
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                try:os.killpg(process.pid,signal.SIGKILL)
                except ProcessLookupError:pass
            except ProcessLookupError:pass
