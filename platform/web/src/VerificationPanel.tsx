import { useEffect, useState } from 'react';
import { VStack, HStack } from '@astryxdesign/core/Layout';
import { Text } from '@astryxdesign/core/Text';
import { Card } from '@astryxdesign/core/Card';
import { Collapsible } from '@astryxdesign/core/Collapsible';
import { StatusBadge } from './StatusBadge';
import { apiFetch } from './api';

type Criterion = {id:string;requirement_id:string;description:string;check:Record<string,unknown>};
type Result = {id:string;status:string;reason?:string;evidence?:unknown};
type Report = {contract:null|{task:string;requirements:{id:string;description:string}[];criteria:Criterion[]};contract_hash?:string;recorded:boolean;warning?:string;result:null|{success:boolean;results:Result[];layout?:unknown[];report_path?:string};result_time?:string};

export function VerificationPanel({jobId,status}:{jobId:string;status:string}){
 const [report,setReport]=useState<Report|null>(null),[error,setError]=useState('');
 useEffect(()=>{const controller=new AbortController();let timer:ReturnType<typeof setTimeout>;
  async function poll(){try{const r=await apiFetch(`/api/jobs/${jobId}/verification`,{signal:controller.signal}),body=await r.json();if(!r.ok)throw Error(body.error);if(!controller.signal.aborted){setReport(body);setError('');}}catch(e){if(!controller.signal.aborted)setError(String(e));}if(!controller.signal.aborted&&['running','stopping'].includes(status))timer=setTimeout(poll,1500);}
  setReport(null);poll();return()=>{controller.abort();clearTimeout(timer);};
 },[jobId,status]);
 if(error)return <Text role="alert">{error}</Text>;
 if(!report)return <Text color="secondary">완료 조건을 불러오는 중입니다.</Text>;
 if(!report.contract)return <Text color="secondary">이 실행에는 완료 조건 계약이 기록되지 않았습니다. 기존 검사 결과로 요청 달성 여부를 확인할 수 없습니다.</Text>;
 const resultMap=new Map(report.result?.results.map(r=>[r.id,r])||[]);
 return <VStack gap={3} role="region" aria-label="완료 조건 검증" style={{minWidth:0,width:'100%'}}>
  <HStack gap={2}><StatusBadge value={report.result?(report.result.success?'passed':'failed'):'waiting'} label={report.result?(report.result.success?'완료 조건 확인됨':'완료 조건 미충족'):'검증 전'}/><Text color="secondary">{report.result_time?new Date(report.result_time).toLocaleString('ko-KR'):'실행 전 고정한 조건으로 검사합니다.'}</Text></HStack>
  {report.warning&&<Text role="alert">{report.warning}</Text>}
  {report.contract.requirements.map(req=><Card key={req.id} padding={3}><VStack gap={2}>
   <Text weight="bold" style={{whiteSpace:'pre-wrap',overflowWrap:'anywhere'}}>{req.description}</Text>
   {report.contract!.criteria.filter(c=>c.requirement_id===req.id).map(c=>{const r=resultMap.get(c.id);return <VStack key={c.id} gap={1} style={{minWidth:0}}>
    <HStack gap={2}><StatusBadge value={r?.status||'waiting'} label={r?.status==='unverified'?'미확인':undefined}/><Text>{c.description}</Text></HStack>
    {r?.reason&&<Text style={{whiteSpace:'pre-wrap',overflowWrap:'anywhere'}}>{r.reason}</Text>}
    <Collapsible defaultIsOpen={false} trigger={<Text size="sm">검사 조건과 관측값</Text>}><pre style={{whiteSpace:'pre-wrap',overflowWrap:'anywhere',margin:0,fontSize:12}}>{JSON.stringify({check:c.check,evidence:r?.evidence??null},null,2)}</pre></Collapsible>
   </VStack>;})}
  </VStack></Card>)}
  {report.result?.results.filter(r=>r.id.startsWith('system:')).map(r=><HStack key={r.id} gap={2}><StatusBadge value={r.status}/><Text>{r.reason||r.id}</Text></HStack>)}
  {!!report.result?.layout?.length&&<Collapsible defaultIsOpen={false} trigger={<Text>실제 화면 크기와 배치</Text>}><pre style={{whiteSpace:'pre-wrap',overflowWrap:'anywhere',fontSize:12}}>{JSON.stringify(report.result.layout,null,2)}</pre></Collapsible>}
  <Text size="sm" color="secondary" style={{overflowWrap:'anywhere'}}>계약 {report.contract_hash}</Text>
 </VStack>;
}
