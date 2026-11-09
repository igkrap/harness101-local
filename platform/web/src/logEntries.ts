import type { FlowEvent } from './flowState';
export function compactEvents(events:FlowEvent[]) {
  const rows=[...events].sort((a,b)=>a.seq-b.seq),pending=new Map<string,FlowEvent>(),hidden=new Set<number>();
  const starts:Record<string,string>={'model.request':'model','tool.started':'tool','check.started':'check'};
  const ends:Record<string,string>={'model.response':'model','model.error':'model','tool.finished':'tool','check.finished':'check'};
  for(const event of rows){const begin=starts[event.type],end=ends[event.type];if(begin)pending.set(begin,event);if(end){const start=pending.get(end);if(start){hidden.add(start.seq);pending.delete(end);}}}
  return rows.filter(e=>!hidden.has(e.seq)&&(starts[e.type]||ends[e.type]||['requirement.contract_rejected','requirement.review','requirement.contract','verification.finished','autonomy.rollback','autonomy.blocked','autonomy.conflict','autonomy.error','autonomy.strategy','autonomy.retry','autonomy.accepted','autonomy.step_finished','autonomy.analysis','autonomy.compact','autonomy.proposal_rejected','autonomy.stage_started','autonomy.stage_verified','autonomy.stage_failed','autonomy.handoff','autonomy.integration_failed','autonomy.stage_stalled'].includes(e.type))).reverse();
}
