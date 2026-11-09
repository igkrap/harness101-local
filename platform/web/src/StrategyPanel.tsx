import { useEffect, useState } from 'react';
import { VStack, HStack } from '@astryxdesign/core/Layout';
import { Text } from '@astryxdesign/core/Text';
import { Card } from '@astryxdesign/core/Card';
import { Collapsible } from '@astryxdesign/core/Collapsible';
import { StatusBadge } from './StatusBadge';
import { apiFetch } from './api';

type Stage = {id:string;title:string;domain?:string;instructions?:string;criterion_ids?:string[];depends_on?:string[];paths?:string[]};
type Strategy = {recorded:boolean;stages:Stage[];job_status?:string;state:null|{completed_stage_ids?:string[];active_stage_id?:string;phase?:string}};

export function StrategyPanel({jobId,status}:{jobId:string;status:string}){
 const [report,setReport]=useState<Strategy|null>(null),[error,setError]=useState('');
 useEffect(()=>{const controller=new AbortController();let timer:ReturnType<typeof setTimeout>;
  async function poll(){try{const r=await apiFetch(`/api/jobs/${jobId}/strategy`,{signal:controller.signal}),body=await r.json();if(!r.ok)throw Error(body.error);if(!controller.signal.aborted){setReport(body);setError('');}}catch(e){if(!controller.signal.aborted)setError(String(e));}if(!controller.signal.aborted&&['running','stopping'].includes(status))timer=setTimeout(poll,1500);}
  setReport(null);poll();return()=>{controller.abort();clearTimeout(timer);};
 },[jobId,status]);
 if(error)return <Text role="alert">{error}</Text>;
 if(!report?.recorded)return null;
 const completed=new Set(report.state?.completed_stage_ids||[]),active=report.state?.active_stage_id;
 return <VStack gap={3} role="region" aria-label="작업 분할 계획" style={{minWidth:0,width:'100%',textAlign:'left'}}>
  <Text color="secondary">각 작업을 검증한 뒤 전체 요청을 다시 확인합니다. 단계 통과는 전체 완료와 구분됩니다.</Text>
  {report.stages.map((stage,index)=>{
   const final=stage.id==='integration',done=final?report.state?.phase==='success'&&status==='succeeded':completed.has(stage.id);
   const current=active===stage.id&&!done;
   const state=done?'passed':current?(['failed','interrupted','stopped'].includes(status)?status:'running'):'waiting';
   return <Card key={stage.id} padding={3}><VStack gap={2} style={{minWidth:0}}>
    <HStack gap={2} style={{flexWrap:'wrap',justifyContent:'flex-start'}}><Text color="secondary">{index+1}</Text><Text weight="bold">{stage.title}</Text><StatusBadge value={state} label={done?(final?'전체 검증 통과':'단계 통과'):undefined}/>{stage.domain&&<Text size="sm" color="secondary">{stage.domain==='backend'?'백엔드':'화면'}</Text>}</HStack>
    {stage.instructions&&<Text style={{whiteSpace:'pre-wrap',overflowWrap:'anywhere'}}>{stage.instructions}</Text>}
    {!!stage.depends_on?.length&&<Text size="sm" color="secondary">선행 작업: {stage.depends_on.map(id=>report.stages.find(s=>s.id===id)?.title||id).join(', ')}</Text>}
    {!!stage.criterion_ids?.length&&<Text size="sm" color="secondary">완료 조건: {stage.criterion_ids.join(', ')}</Text>}
    {!!stage.paths?.length&&<Collapsible defaultIsOpen={false} trigger={<Text size="sm">수정 대상</Text>}><pre style={{margin:0,whiteSpace:'pre-wrap',overflowWrap:'anywhere'}}>{stage.paths.join('\n')}</pre></Collapsible>}
   </VStack></Card>;
  })}
 </VStack>;
}
