import { useEffect, useState } from 'react';
import { Card } from '@astryxdesign/core/Card';
import { VStack, HStack } from '@astryxdesign/core/Layout';
import { Text } from '@astryxdesign/core/Text';
import { Button } from '@astryxdesign/core/Button';
import { Collapsible } from '@astryxdesign/core/Collapsible';
import { apiFetch } from './api';
import './context.css';
type Budget={estimated_input_tokens:number;reserved_output_tokens:number;budget_tokens:number;remaining_tokens:number;pressure:number;system_tokens_estimate:number;tools_tokens_estimate:number;message_count:number;tool_result_count:number;estimated:boolean};
type Managed={usage?:{input_tokens:number;reserve_tokens:number;max_context_tokens:number;ratio:number;calibrated:boolean};thresholds?:{soft:number;hard:number};stats?:{compactions:number;prunes:number;failures:number;recoveries:number;fallbacks:number;restores:number};last_compaction?:null|{time:string;version:number;before_tokens:number;after_tokens:number;source:string;level:string;repaired?:string[]};checkpoint_version?:number;last_failure?:string|null;chars_per_token?:number|null};
type Usage={prompt_tokens?:number;completion_tokens?:number;prompt_tokens_details?:{cached_tokens?:number}};
type Report={management?:Managed|null;job:{id:string;status:string};current:null|{seq:number;time:string;model:string;estimated_input_tokens?:number;context:Budget|null};confirmed:null|{seq:number;time:string;usage:Usage|null;finish_reason?:string};waiting:boolean;compaction:null|{time:string;reason:string;before:Budget;after:Budget;removed_messages:number;retained_paths:string[];model_calls:number};files:string[];counts:{requests:number;compactions:number}};
const number=(n:number|undefined)=>typeof n==='number'?n.toLocaleString():'기록 없음';
export function ContextBar({budget,compact=false}:{budget:Budget;compact?:boolean}){
 const capacity=Math.max(1,budget.budget_tokens),total=budget.estimated_input_tokens+budget.reserved_output_tokens;
 const input=Math.min(100,100*budget.estimated_input_tokens/capacity),reserve=Math.min(100-input,100*budget.reserved_output_tokens/capacity);
 const percent=Math.round(100*total/capacity);
 return <VStack gap={compact?1:2} style={{width:'100%',minWidth:0}}><HStack hAlign="between" gap={3}><Text size="sm">컨텍스트 약 {number(total)} / {number(capacity)} 토큰</Text><Text size="sm" weight="bold">{percent}%</Text></HStack><div className={`context-bar ${compact?'is-compact':''}`} data-pressure={percent>=90?'high':'normal'} role="progressbar" aria-label="컨텍스트 예산 사용량" aria-valuemin={0} aria-valuemax={capacity} aria-valuenow={Math.min(capacity,total)} aria-valuetext={`입력 추정 ${number(budget.estimated_input_tokens)}, 출력 예약 ${number(budget.reserved_output_tokens)}, 남은 예산 약 ${number(budget.remaining_tokens)} 토큰`}><span className="context-bar-input" data-context-segment="input" style={{width:`${input}%`}} title={`입력 추정 ${number(budget.estimated_input_tokens)} 토큰`}/><span className="context-bar-reserve" data-context-segment="reserved" style={{width:`${reserve}%`}} title={`출력 예약 ${number(budget.reserved_output_tokens)} 토큰`}/></div>{!compact&&<HStack gap={4} style={{flexWrap:'wrap'}}><Text size="sm"><span className="context-key context-key-input"/>입력 추정 {number(budget.estimated_input_tokens)}</Text><Text size="sm"><span className="context-key context-key-reserve"/>출력 예약 {number(budget.reserved_output_tokens)}</Text><Text size="sm" color="secondary">남은 예산 약 {number(budget.remaining_tokens)}</Text></HStack>}</VStack>;
}
export function ContextPanel({jobId,status,compact=false,onOpen}:{jobId:string;status:string;compact?:boolean;onOpen?:()=>void}){
 const [data,setData]=useState<Report|null>(null),[error,setError]=useState('');
 useEffect(()=>{const c=new AbortController();let timer:ReturnType<typeof setTimeout>;async function poll(){try{const r=await apiFetch(`/api/jobs/${jobId}/context`,{signal:c.signal}),d=await r.json();if(!r.ok)throw Error(d.error);if(!c.signal.aborted){setData(d);setError('');}}catch(e){if(!c.signal.aborted)setError(String(e));}if(!c.signal.aborted&&['running','stopping'].includes(status))timer=setTimeout(poll,1500);}poll();return()=>{c.abort();clearTimeout(timer);};},[jobId,status]);
 const budget=data?.current?.context,usage=data?.confirmed?.usage,cut=data?.compaction;
 if(compact)return <HStack gap={3} vAlign="center" style={{flexWrap:'wrap'}}><div style={{flex:'1 1 240px',minWidth:0}}>{budget?<ContextBar budget={budget} compact/>:<Text color="secondary">{data?.current?`컨텍스트 입력 추정 약 ${number(data.current.estimated_input_tokens)} 토큰`:'아직 모델 요청 없음'}</Text>}</div><Button label="컨텍스트 보기" size="sm" variant="ghost" onClick={onOpen}/></HStack>;
 return <VStack gap={4} role="region" aria-label="컨텍스트 상태">
  {error&&<Text role="alert">{error}</Text>}
  {!data?<Text color="secondary">불러오는 중</Text>:<>
   <Card padding={4}><VStack gap={3}><HStack hAlign="between" gap={3} style={{flexWrap:'wrap'}}><Text weight="bold">{data.waiting?'현재 요청의 컨텍스트':'마지막 요청의 컨텍스트'}</Text><Text color="secondary">모델 요청 {number(data.counts.requests)}회 · 문맥 재구성 {number(data.counts.compactions)}회</Text></HStack>
    {budget?<><HStack gap={5} style={{flexWrap:'wrap'}}><VStack gap={1}><Text color="secondary">입력 추정</Text><Text weight="bold">약 {number(budget.estimated_input_tokens)} 토큰</Text></VStack><VStack gap={1}><Text color="secondary">출력 예약</Text><Text weight="bold">{number(budget.reserved_output_tokens)} 토큰</Text></VStack><VStack gap={1}><Text color="secondary">하네스 예산</Text><Text weight="bold">{number(budget.budget_tokens)} 토큰</Text></VStack><VStack gap={1}><Text color="secondary">예상 여유</Text><Text weight="bold">약 {number(budget.remaining_tokens)} 토큰</Text></VStack></HStack><ContextBar budget={budget}/><Text color="secondary">입력과 출력 예약 합계 약 {Math.round(budget.pressure*100)}%. 입력량은 추정치이며, 하네스 예산은 모델 자체의 최대 입력 길이와 다릅니다.</Text><Collapsible trigger="입력 구성" defaultIsOpen={false}><VStack gap={2}><Text>시스템 메시지 약 {number(budget.system_tokens_estimate)} 토큰</Text><Text>도구 스키마 약 {number(budget.tools_tokens_estimate)} 토큰</Text><Text>메시지 {number(budget.message_count)}개 · 도구 결과 {number(budget.tool_result_count)}개</Text></VStack></Collapsible></>:<Text color="secondary">{data.current?`이 실행에는 예산 정보가 기록되지 않았습니다. 입력 추정치는 약 ${number(data.current.estimated_input_tokens)} 토큰입니다.`:'아직 모델 요청이 없습니다.'}</Text>}
   </VStack></Card>
   <Card padding={4}><VStack gap={2}><Text weight="bold">{data.waiting?'직전 응답의 확정 사용량':'최근 응답의 확정 사용량'}</Text>{usage?<><Text>입력 {number(usage.prompt_tokens)} · 출력 {number(usage.completion_tokens)} 토큰</Text>{data.confirmed?.finish_reason==='length'&&<Text role="status">출력 한도에 도달해 응답이 잘렸습니다.</Text>}{typeof usage.prompt_tokens_details?.cached_tokens==='number'&&<Text color="secondary">서버 프롬프트 캐시 적중 {number(usage.prompt_tokens_details.cached_tokens)} 토큰. 문맥 압축과는 별도입니다.</Text>}</>:<Text color="secondary">서버가 반환한 사용량 기록이 없습니다.</Text>}</VStack></Card>
   <Card padding={4}><VStack gap={2}><Text weight="bold">최근 문맥 재구성</Text><Text color="secondary">현재 목표·규칙·작업 소스·마지막 오류를 유지하고 오래된 실행 기록을 정리합니다.</Text>{cut?<><Text>입력 추정 약 {number(cut.before?.estimated_input_tokens)} → {number(cut.after?.estimated_input_tokens)} 토큰</Text><Text>메시지 {number(cut.removed_messages)}개 정리 · 모델 호출 {number(cut.model_calls)}회</Text><Text color="secondary" style={{overflowWrap:'anywhere'}}>사유: {cut.reason}</Text><Text color="secondary">{new Date(cut.time).toLocaleString('ko-KR')}</Text></>:<Text color="secondary">기록된 문맥 재구성이 없습니다.</Text>}</VStack></Card>
   {data.management&&<ManagedCard m={data.management}/>}
   {!!data.files.length&&<Card padding={4}><VStack gap={2}><Text weight="bold">최근 자동 분석 파일</Text>{data.files.map(file=><Text key={file} style={{overflowWrap:'anywhere'}}>{file}</Text>)}</VStack></Card>}
  </>}
 </VStack>;
}

function ManagedCard({m}:{m:Managed}){
 const u=m.usage,st=m.stats,last=m.last_compaction,pct=(x?:number)=>typeof x==='number'?Math.round(x*100)+'%':'-';
 return <Card padding={4}><VStack gap={2}><Text weight="bold">자동 컨텍스트 관리</Text>
  {u&&<Text>현재 {number(u.input_tokens)} + 출력 예약 {number(u.reserve_tokens)} / {number(u.max_context_tokens)} 토큰 ({pct(u.ratio)}){u.calibrated?' · 실제 토큰 수로 보정됨':' · 추정치'}</Text>}
  <Text color="secondary">자동 압축 기준 {pct(m.thresholds?.soft)} · 긴급 압축 {pct(m.thresholds?.hard)} · 체크포인트 v{m.checkpoint_version??0}</Text>
  {st&&<Text color="secondary">압축 {st.compactions}회 · 규칙 정리 {st.prunes}회 · 실패 {st.failures}회 (복구 {st.recoveries}, 대체 {st.fallbacks}) · 재시작 복원 {st.restores}회</Text>}
  {last?<Text>최근 압축 {new Date(last.time).toLocaleTimeString('ko-KR')} · {number(last.before_tokens)} → {number(last.after_tokens)} 토큰 · {last.source==='llm'?'AI 요약':'규칙 기반 대체'}{last.repaired?.length?` · 보정: ${last.repaired.join(', ')}`:''}</Text>:<Text color="secondary">아직 압축하지 않았습니다.</Text>}
  {m.last_failure&&<Text role="alert">최근 압축 실패: {m.last_failure}</Text>}
 </VStack></Card>;
}
