from pathlib import Path
import json,sys,tempfile,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from history import History
class HistoryTests(unittest.TestCase):
 def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.index=History(self.root)
 def tearDown(self):self.index.close();self.tmp.cleanup()
 def job(self,i,events=()):
  key=f'{i:032x}';job={'id':key,'started_at':'2026-11-01T00:00:00+00:00','status':'succeeded','kind':'checks'};path=self.root/key;path.mkdir(exist_ok=True);(path/'events.jsonl').write_text(''.join(json.dumps(e)+'\n' for e in events));self.index.sync(job);return job,path
 def event(self,seq,kind='model.request',**data):return {'seq':seq,'type':kind,'time':f'2026-11-01T00:{seq%60:02}:00Z','data':data}
 def test_keyset_jobs_no_duplicate_after_new_insertion(self):
  for i in range(45):self.job(i)
  first=self.index.jobs(limit=20);self.assertEqual(len(first['jobs']),20);self.job(100)
  second=self.index.jobs(first['next'],20);third=self.index.jobs(second['next'],20)
  ids=[j['id'] for page in (first,second,third) for j in page['jobs']];self.assertEqual(len(ids),45);self.assertEqual(len(set(ids)),45);self.assertIsNone(third['next'])
 def test_bounded_events_and_incremental_after_cursor(self):
  job,path=self.job(1,[self.event(i) for i in range(1,202)]);page=self.index.events(job['id']);self.assertEqual(len(page['events']),80);self.assertEqual(page['events'][0]['seq'],122);self.assertEqual(page['next_before'],122)
  older=self.index.events(job['id'],before=122);self.assertEqual([e['seq'] for e in older['events']],list(range(42,122)))
  with (path/'events.jsonl').open('a') as stream:stream.write(json.dumps(self.event(202))+'\n')
  self.index.sync(job);tail=self.index.events(job['id'],after=201);self.assertEqual([e['seq'] for e in tail['events']],[202]);self.assertEqual(tail['total'],202)
 def test_partial_append_is_not_lost(self):
  job,path=self.job(1,[self.event(1)]);line=json.dumps(self.event(2));file=path/'events.jsonl'
  with file.open('a') as stream:stream.write(line[:20])
  self.index.sync(job);self.assertEqual(self.index.events(job['id'])['total'],1)
  with file.open('a') as stream:stream.write(line[20:]+'\n')
  self.index.sync(job);self.assertEqual(self.index.events(job['id'])['total'],2)
 def test_rewrite_rebuilds_counts_and_offsets(self):
  job,path=self.job(1,[self.event(1)]);(path/'events.jsonl').write_text(json.dumps(self.event(1,'tool.started'))+'\n');self.index.sync(job);page=self.index.events(job['id']);self.assertEqual(page['counts'],{'tool.started':1})
 def test_old_source_matching_evidence_is_available(self):
  self.job(1,[self.event(1,'check.finished',mode='frontend',source_hash='good',success=True)]);self.job(2,[self.event(2,'check.finished',mode='frontend',source_hash='other',success=False)])
  self.assertTrue(self.index.evidence('frontend','good')['success']);self.assertFalse(self.index.evidence('frontend','unknown')['success'])
 def test_filter_is_applied_before_pagination(self):
  job,_=self.job(1,[self.event(i,'tool.started' if i%3 else 'check.finished') for i in range(1,100)]);page=self.index.events(job['id'],limit=10,kind='check');self.assertEqual(len(page['events']),10);self.assertEqual(page['total'],33);self.assertTrue(all(e['type']=='check.finished' for e in page['events']));self.assertIsNotNone(page['next_before'])
 def test_event_detail_is_read_on_demand(self):
  job,_=self.job(1,[self.event(1,'check.finished',stdout='large output')]);self.assertEqual(self.index.event(job['id'],1)['data']['stdout'],'large output')
 def test_bad_cursors_and_sizes(self):
  for before in ('bad','%%%%','e30'):
   with self.assertRaises(ValueError):self.index.jobs(before)
  for limit in (0,1000,'bad'):
   with self.assertRaises(ValueError):self.index.jobs(limit=limit)
  with self.assertRaises(ValueError):self.index.events('a',before=1,after=2)
 def test_latest_failed_job_is_not_limited_to_first_page(self):
  job,path=self.job(1,[self.event(1,'check.finished',success=False,mode='frontend')]);job['status']='failed';self.index.sync(job)
  for i in range(2,40):self.job(i)
  self.assertEqual(self.index.latest_failed()['id'],job['id']);self.assertEqual(self.index.last_failure(job['id'])['seq'],1)
  with (path/'events.jsonl').open('a') as stream:stream.write(json.dumps(self.event(2,'autonomy.accepted'))+'\n')
  self.index.sync(job);self.assertEqual(self.index.last_event(job['id'],'autonomy.accepted')['seq'],2)
 def test_failure_index_backfills_existing_journals(self):
  job,path=self.job(1,[self.event(1,'autonomy.blocked',error='file missing')]);self.index.db.execute('DROP TABLE failures');self.index.db.commit();self.index.close();self.index=History(self.root);self.index.sync(job);self.assertEqual(self.index.last_failure(job['id'])['data']['error'],'file missing')

 def test_job_kind_filter_is_applied_before_pagination(self):
  for i in range(1,66):
   job,_=self.job(i);job['kind']='agent' if i%2 else 'harness';self.index.sync(job)
  page=self.index.jobs(limit=20,kind='agent');self.assertEqual(page['total'],33);self.assertEqual(len(page['jobs']),20);self.assertTrue(all(j['kind']=='agent' for j in page['jobs']))
  older=self.index.jobs(before=page['next'],limit=20,kind='agent');self.assertEqual(len(older['jobs']),13);self.assertFalse(set(j['id'] for j in page['jobs']) & set(j['id'] for j in older['jobs']))
