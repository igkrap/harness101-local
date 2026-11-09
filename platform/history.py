"""Cursor queries over journal offsets; existing JSONL files remain the source."""
import base64
from collections import Counter
import json
from pathlib import Path
import sqlite3
import threading


class History:
    def __init__(self, root):
        self.root = Path(root)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(self.root/'history.sqlite3', check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.known = {}
        had_failures = self.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='failures'").fetchone()
        self.db.executescript('''
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, started TEXT NOT NULL, body TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS jobs_order ON jobs(started DESC,id DESC);
            CREATE INDEX IF NOT EXISTS jobs_kind ON jobs(json_extract(body,'$.kind'),started DESC,id DESC);
            CREATE TABLE IF NOT EXISTS journals(job TEXT PRIMARY KEY,inode INTEGER,offset INTEGER,size INTEGER,mtime INTEGER);
            CREATE TABLE IF NOT EXISTS events(job TEXT,seq INTEGER,offset INTEGER,length INTEGER,type TEXT,time TEXT,mode TEXT,hash TEXT,PRIMARY KEY(job,seq));
            CREATE INDEX IF NOT EXISTS evidence ON events(mode,hash,time DESC,seq DESC);
            CREATE INDEX IF NOT EXISTS latest_evidence ON events(mode,time DESC,seq DESC);
            CREATE TABLE IF NOT EXISTS counts(job TEXT,type TEXT,n INTEGER,PRIMARY KEY(job,type));
            CREATE INDEX IF NOT EXISTS event_types ON events(job,type,seq DESC);
            CREATE TABLE IF NOT EXISTS failures(job TEXT,seq INTEGER,offset INTEGER,length INTEGER,type TEXT,time TEXT,PRIMARY KEY(job,seq));
        ''')
        if 'status' not in {row['name'] for row in self.db.execute('PRAGMA table_info(jobs)')}:
            self.db.execute('ALTER TABLE jobs ADD COLUMN status TEXT')
        self.db.execute('CREATE INDEX IF NOT EXISTS failed_jobs ON jobs(status,started DESC,id DESC)')
        if not had_failures:
            # One migration pass backfills the failure index from existing journals.
            for table in ('events','counts','journals'): self.db.execute('DELETE FROM '+table)
        self.db.commit()

    def sync(self, job):
        key = job['id']
        with self.lock:
            body = json.dumps(job, ensure_ascii=False)
            if self.known.get(key) != body:
                self.db.execute('INSERT OR REPLACE INTO jobs(id,started,body,status) VALUES(?,?,?,?)', (key, job.get('started_at',''), body,job.get('status')))
                self.known[key] = body
            path = self.root/key/'events.jsonl'
            if not path.exists():
                self.db.commit()
                return
            stat = path.stat()
            prior = self.db.execute('SELECT * FROM journals WHERE job=?',(key,)).fetchone()
            if prior and stat.st_ino == prior['inode'] and stat.st_size == prior['size'] and stat.st_mtime_ns == prior['mtime']:
                self.db.commit()
                return
            offset = prior['offset'] if prior else 0
            if prior and (stat.st_ino != prior['inode'] or stat.st_size < offset or
                          (stat.st_size <= prior['size'] and stat.st_mtime_ns != prior['mtime'])):
                self.db.execute('DELETE FROM events WHERE job=?',(key,))
                self.db.execute('DELETE FROM counts WHERE job=?',(key,))
                self.db.execute('DELETE FROM failures WHERE job=?',(key,))
                offset = 0
            maximum = self.db.execute('SELECT COALESCE(MAX(seq),0) FROM events WHERE job=?',(key,)).fetchone()[0]
            increments = Counter()
            with path.open('rb') as stream:
                stream.seek(offset)
                while True:
                    position = stream.tell()
                    line = stream.readline()
                    if not line or not line.endswith(b'\n'):
                        break  # An in-progress append is retried from this position.
                    offset = stream.tell()
                    try:
                        event = json.loads(line)
                        if not isinstance(event,dict): continue
                        seq = event.get('seq',maximum+1)
                        if type(seq) is not int or seq < 1: continue
                        data = event.get('data') or {}
                        if not isinstance(data,dict): continue
                        kind = str(event.get('type',''))
                        inserted = self.db.execute('INSERT OR IGNORE INTO events VALUES(?,?,?,?,?,?,?,?)',
                            (key,seq,position,len(line),kind,str(event.get('time','')),data.get('mode') if kind=='check.finished' else None,data.get('source_hash'))).rowcount
                        if inserted: increments[kind] += 1
                        negative = (kind in ('check.finished','tool.finished','verification.finished','autonomy.stage_verified','autonomy.stage_failed','autonomy.integration_failed','requirement.contract_rejected') and (data.get('success') is False or bool(data.get('error')))) or kind in ('model.error','run.error','autonomy.error','autonomy.conflict','autonomy.exhausted','autonomy.blocked','autonomy.rollback','autonomy.proposal_rejected')
                        if inserted and negative:
                            self.db.execute('INSERT OR IGNORE INTO failures VALUES(?,?,?,?,?,?)',(key,seq,position,len(line),kind,str(event.get('time',''))))
                        maximum = max(maximum,seq)
                    except (ValueError,TypeError):
                        continue
            for kind, count in increments.items():
                self.db.execute('INSERT INTO counts VALUES(?,?,?) ON CONFLICT(job,type) DO UPDATE SET n=n+excluded.n',(key,kind,count))
            self.db.execute('INSERT OR REPLACE INTO journals VALUES(?,?,?,?,?)',(key,stat.st_ino,offset,stat.st_size,stat.st_mtime_ns))
            self.db.commit()

    @staticmethod
    def limit(value, default=20, maximum=100):
        try: number = int(value) if value is not None else default
        except (ValueError,TypeError): raise ValueError('조회 개수가 올바르지 않습니다.')
        if not 1 <= number <= maximum: raise ValueError('조회 개수가 범위를 벗어났습니다.')
        return number

    def jobs(self, before=None, limit=20, kind=None):
        size = self.limit(limit)
        params = []
        conditions = []
        if kind is not None:
            if kind not in ('agent','checks','harness'):raise ValueError('실행 종류가 올바르지 않습니다.')
            conditions.append("json_extract(body,'$.kind')=?");params.append(kind)
        if before:
            try:
                cursor = json.loads(base64.urlsafe_b64decode(before+'='*(-len(before)%4)))
                if not isinstance(cursor,list) or len(cursor)!=2 or not all(isinstance(x,str) for x in cursor): raise ValueError()
                conditions.append('(started,id)<(?,?)'); params.extend(cursor)
            except (ValueError,TypeError): raise ValueError('실행 기록 커서가 올바르지 않습니다.')
        with self.lock:
            condition='WHERE '+' AND '.join(conditions) if conditions else ''
            rows = self.db.execute(f'SELECT * FROM jobs {condition} ORDER BY started DESC,id DESC LIMIT ?',(*params,size+1)).fetchall()
            total = self.db.execute("SELECT COUNT(*) FROM jobs WHERE json_extract(body,'$.kind')=?",(kind,)).fetchone()[0] if kind else self.db.execute('SELECT COUNT(*) FROM jobs').fetchone()[0]
        visible = rows[:size]
        cursor = base64.urlsafe_b64encode(json.dumps([visible[-1]['started'],visible[-1]['id']]).encode()).decode().rstrip('=') if len(rows)>size else None
        return {'jobs':[json.loads(row['body']) for row in visible], 'next':cursor, 'total':total}

    def read(self, row):
        with (self.root/row['job']/'events.jsonl').open('rb') as stream:
            stream.seek(row['offset'])
            return json.loads(stream.read(row['length']))

    def latest_failed(self):
        with self.lock:
            row=self.db.execute("SELECT body FROM jobs WHERE status='failed' ORDER BY started DESC,id DESC LIMIT 1").fetchone()
            return json.loads(row['body']) if row else None

    def last_failure(self, job):
        with self.lock:
            row=self.db.execute('SELECT * FROM failures WHERE job=? ORDER BY seq DESC LIMIT 1',(job,)).fetchone()
            return self.read(row) if row else None

    def last_event(self, job, kind):
        with self.lock:
            row=self.db.execute('SELECT * FROM events WHERE job=? AND type=? ORDER BY seq DESC LIMIT 1',(job,kind)).fetchone()
            return self.read(row) if row else None

    def counts(self, job):
        with self.lock:
            return dict(self.db.execute('SELECT type,n FROM counts WHERE job=?',(job,)).fetchall())

    def event(self, job, seq):
        try: seq=int(seq)
        except (TypeError,ValueError): raise ValueError('이벤트 번호가 올바르지 않습니다.')
        with self.lock:
            row=self.db.execute('SELECT * FROM events WHERE job=? AND seq=?',(job,seq)).fetchone()
            if row is None: raise ValueError('이벤트를 찾을 수 없습니다.')
            return self.read(row)

    def events(self, job, before=None, after=None, limit=80, kind=None):
        size = self.limit(limit,80,200)
        if before is not None and after is not None: raise ValueError('이벤트 커서를 하나만 지정하세요.')
        condition, params = 'job=?', [job]
        if kind and kind!='all':
            if kind not in ('model','tool','check','autonomy','run'): raise ValueError('이벤트 분류가 올바르지 않습니다.')
            condition += ' AND type LIKE ?';params.append(kind+'.%')
        base_condition, base_params=condition,params[:]
        for name,value,operator in [('before',before,'<'),('after',after,'>')]:
            if value is not None:
                try: value = int(value)
                except (ValueError,TypeError): raise ValueError('이벤트 커서가 올바르지 않습니다.')
                if value < 0: raise ValueError('이벤트 커서가 올바르지 않습니다.')
                condition += f' AND seq{operator}?'; params.append(value)
        with self.lock:
            order = 'ASC' if after is not None else 'DESC'
            rows = self.db.execute(f'SELECT * FROM events WHERE {condition} ORDER BY seq {order} LIMIT ?',(*params,size+1)).fetchall()
            visible = rows[:size]
            if after is None: visible.reverse()
            first, last = (visible[0]['seq'],visible[-1]['seq']) if visible else (None,None)
            older = first if first is not None and self.db.execute(f'SELECT 1 FROM events WHERE {base_condition} AND seq<? LIMIT 1',(*base_params,first)).fetchone() else None
            counts = dict(self.db.execute('SELECT type,n FROM counts WHERE job=?',(job,)).fetchall())
            total=sum(value for key,value in counts.items() if not kind or kind=='all' or key.startswith(kind+'.'))
            return {'events':[self.read(row) for row in visible],'next_before':older,'next_after':last if len(rows)>size and after is not None else None,'total':total,'counts':counts}

    def evidence(self, mode, signature):
        with self.lock:
            row = self.db.execute('SELECT * FROM events WHERE mode=? AND hash=? ORDER BY time DESC,seq DESC LIMIT 1',(mode,signature)).fetchone()
            if row is None:
                row = self.db.execute('SELECT * FROM events WHERE mode=? ORDER BY time DESC,seq DESC LIMIT 1',(mode,)).fetchone()
            if row is None: return None
            event = self.read(row)
            return {**event['data'],'time':event.get('time'),'source':'플랫폼 실행','job_id':row['job']}

    def close(self):
        with self.lock: self.db.close()

    def latest_agent(self):
        with self.lock:
            row=self.db.execute("SELECT body FROM jobs WHERE json_extract(body,'$.kind')='agent' ORDER BY started DESC,id DESC LIMIT 1").fetchone()
            return json.loads(row['body']) if row else None
