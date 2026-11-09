import { StatusBadge } from "./StatusBadge";
import { Button } from '@astryxdesign/core/Button';
import type { RunRecord } from './HistoryViews';
const states:Record<string,[string,string]>={succeeded:['성공','✓'],failed:['실패','×'],running:['실행 중','◌'],stopping:['중지 중','◌'],stopped:['중지됨','−'],interrupted:['종료 확인 필요','!']};
function duration(job:RunRecord){if(!job.finished_at)return '';const seconds=Math.max(0,Math.round((Date.parse(job.finished_at)-Date.parse(job.started_at))/1000));return seconds>=60?`${Math.floor(seconds/60)}분 ${seconds%60}초`:`${seconds}초`;}
export function RunRecordRow({job,selected,onClick}:{job:RunRecord;selected:boolean;onClick:()=>void}){
  const [label,icon]=states[job.status]||[job.status,'·'];
  const legacy=job.kind==='agent'&&job.status==='succeeded'&&!job.completion_policy;
  return <Button data-job-id={job.id} label={job.goal||'작업'} className="run-record" variant="ghost" width="100%" aria-current={selected?'true':undefined} data-status={job.status} onClick={onClick} style={{height:'auto',justifyContent:'flex-start',textAlign:'left'}}>
    <span className="run-record-body"><span className="run-record-heading"><span className="run-record-icon" aria-hidden="true">{icon}</span><span className="run-record-title">{job.goal||'작업'}</span></span>
      <span className="run-record-meta"><StatusBadge value={legacy?'unknown':job.status} label={legacy?'기존 성공 판정':label}/><span>·</span><span>{new Date(job.started_at).toLocaleString('ko-KR',{month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit',hour12:false})}</span>{duration(job)&&<><span>·</span><span>{duration(job)}</span></>}</span>
      <span className="run-record-id">#{job.id.slice(0,8)}</span>
    </span>
  </Button>;
}
