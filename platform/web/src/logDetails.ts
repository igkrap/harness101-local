import type { FlowEvent } from './flowState';
const pretty=(value:unknown)=>typeof value==='string'?value:JSON.stringify(value,null,2);
function argumentsText(value:unknown){if(typeof value==='string'){try{return JSON.stringify(JSON.parse(value),null,2);}catch{return value;}}return pretty(value);}
export function detailText(event:FlowEvent):string{
 const d=event.data,sections:string[]=[];
 if(d.error)sections.push(`오류\n${d.error}`);
 if(d.reason)sections.push(`기록된 사유\n${d.reason}`);
 if(event.type==='requirement.review')sections.push(`완료 조건 검토\n${pretty({approved:d.approved,issues:d.issues})}`);
 if(event.type==='requirement.contract')sections.push(`고정된 완료 조건\n${pretty(d.contract)}`);
 if(event.type==='verification.finished')sections.push(`완료 조건 검사\n${pretty(d.results)}${d.contract_hash?`\n계약: ${d.contract_hash}`:''}`);
 if(event.type==='autonomy.stage_verified')sections.push(`단계 조건 검사\n${pretty(d.results)}`);
 if(event.type==='autonomy.handoff')sections.push(`다음 단계에 전달한 검증 결과\n${pretty({changed_paths:d.changed_paths,source_hashes:d.source_hashes,verified_results:d.verified_results})}`);
 if(d.stage_id)sections.push(`담당 단계: ${d.stage_id}`);
 if(event.type==='definition.step'){sections.push(`${d.title}${d.state==='refused'?' (받아들여지지 않음)':''}${d.seconds!=null?` · ${d.seconds}초`:''}`);if(d.detail)sections.push(String(d.detail));}
 if(event.type==='model.response'){
  if(d.text)sections.push(`모델 메시지\n${d.text}`);
  const calls=Array.isArray(d.tool_calls)?d.tool_calls:[];
  if(calls.length)sections.push('모델이 요청한 도구\n'+calls.map((call,i)=>{const f=call?.function||{};return `${i+1}. ${f.name||'이름 없음'}${call.id?` (${call.id})`:''}\n인자\n${argumentsText(f.arguments??{})}`;}).join('\n\n'));
  if(!d.text)sections.push('이 응답에는 도구 선택 이유에 대한 별도 설명이 없습니다.');
  if(d.finish_reason)sections.push(`응답 종료 사유: ${d.finish_reason}`);
  if(d.usage)sections.push(`토큰 사용량\n${pretty(d.usage)}`);
  if(d.seconds)sections.push(`걸린 시간: ${d.seconds}초`);
 }else if(event.type==='model.request'){
  if(d.model)sections.push(`요청 모델: ${d.model}`);
  if(d.estimated_input_tokens)sections.push(`입력 토큰: ${d.estimated_input_tokens}${d.cached_tokens?` (그중 ${d.cached_tokens}은 앞서 읽어 둔 것을 다시 씀)`:''}`);
  if(d.prompt)sections.push(`모델에게 준 것 (매번 같은 부품 설명은 빼고)\n${d.prompt}`);
  if(d.timeout_policy)sections.push(`연결·응답 대기 설정\n${pretty(d.timeout_policy)}`);
 }else if(event.type.startsWith('tool.')){
  if(d.text)sections.push(`입력\n${d.text}`);
  else if(d.path||d.query)sections.push(`입력\n${pretty(Object.fromEntries(['path','query','scope','search_mode'].filter(k=>d[k]!=null).map(k=>[k,d[k]])))}`);
  if(event.type==='tool.finished'&&!d.stdout&&!d.error)sections.push('이 기록에는 도구 반환 본문이 저장되어 있지 않습니다. 원본 호출 인자는 앞선 모델 응답에서 확인할 수 있습니다.');
  if(typeof d.changed==='boolean')sections.push(`파일 변경: ${d.changed?'있음':'없음'}`);
 }else {
  if(d.text)sections.push(String(d.text));
  if(d.round!=null)sections.push(`모델 호출 횟수: ${d.round}`);
  if(d.paths)sections.push(`대상 파일\n${pretty(d.paths)}`);
  if(d.title)sections.push(`단계: ${d.title}`);
  if(d.engine)sections.push(`분석기: ${d.engine}`);
  if(d.model_calls!=null)sections.push(`분석에 사용한 모델 호출: ${d.model_calls}회`);
  if(d.before&&d.after)sections.push(`재구성 전후 입력 추정\n${JSON.stringify(d.before,null,2)}\n→\n${JSON.stringify(d.after,null,2)}`);
  if(d.retained_paths)sections.push(`보존한 작업 파일\n${pretty(d.retained_paths)}`);
 }
 if(d.stdout)sections.push(`${event.type.startsWith('tool.')?'반환 결과':'표준 출력'}\n${d.stdout}`);
 if(d.stderr)sections.push(`오류 출력\n${d.stderr}`);
 if(d.truncated||d.text_truncated)sections.push('저장된 출력이 길이 제한으로 일부 생략되었습니다.');
 return sections.join('\n\n')||'추가 출력이 없습니다.';
}
export function readActivity(events:FlowEvent[]){
 const ordered=[...events].sort((a,b)=>a.seq-b.seq);let lastAccepted=-1;
 for(let i=0;i<ordered.length;i++)if(ordered[i].type==='autonomy.accepted')lastAccepted=i;
 const recent=ordered.slice(lastAccepted+1),paths=new Map<string,number>();
 for(const e of recent)if(e.type==='tool.finished'&&e.data.name==='read_file'&&e.data.success!==false&&typeof e.data.path==='string')paths.set(e.data.path,(paths.get(e.data.path)||0)+1);
 return {reads:[...paths.values()].reduce((a,b)=>a+b,0),repeated:[...paths].filter(([,n])=>n>=3),accepted:ordered.filter(e=>e.type==='autonomy.accepted').length};
}
