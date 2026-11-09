import { apiFetch } from "./api";
import { useEffect, useRef, useState } from "react";
import { VStack, HStack } from "@astryxdesign/core/Layout";
import { Text, Heading } from "@astryxdesign/core/Text";
import { Card } from "@astryxdesign/core/Card";
import { Button } from "@astryxdesign/core/Button";
import { Collapsible } from "@astryxdesign/core/Collapsible";
import type { RunRecord } from "./HistoryViews";
type Report={job:RunRecord|null;reason?:string;code?:string;used?:number;limit?:number;completed_steps?:number;total_steps?:number|null;later_verified?:boolean;exit_code?:number|null;failure?:{seq:number|null;time:string;type:string;mode?:string;tool?:string;path?:string;message:string}|null};
const modes:Record<string,string>={frontend:"프론트 빌드",framework:"화면 동작",backend:"백엔드 통합",harness:"하네스 검사"};
export function FailurePanel({jobId,refreshKey,embedded=false}:{jobId:string;refreshKey?:string;embedded?:boolean}){
  const [report,setReport]=useState<Report|null>(null),[error,setError]=useState(""),[retry,setRetry]=useState(0),[original,setOriginal]=useState("");
  const detailRequest=useRef<AbortController|null>(null);
  useEffect(()=>{const controller=new AbortController();detailRequest.current?.abort();detailRequest.current=null;setReport(null);setOriginal("");setError("");apiFetch("/api/failure?job="+encodeURIComponent(jobId),{signal:controller.signal,cache:"no-store"}).then(async r=>{const result=await r.json();if(!r.ok)throw Error(result.error||`HTTP ${r.status}`);if(!controller.signal.aborted)setReport(result);}).catch(e=>{if(!controller.signal.aborted)setError(String(e));});return()=>{controller.abort();detailRequest.current?.abort();};},[jobId,refreshKey,retry]);
  const fault=report?.failure;
  const loadOriginal=async()=>{
    if(original||!fault?.seq||!report?.job||detailRequest.current)return;
    const controller=new AbortController();detailRequest.current=controller;
    try{const r=await apiFetch(`/api/jobs/${report.job.id}/events?at=${fault.seq}`,{cache:"no-store",signal:controller.signal});const result=await r.json();if(!r.ok)throw Error(result.error||`HTTP ${r.status}`);const d=result.event.data;if(!controller.signal.aborted)setOriginal(String(d.error||d.reason||[d.stdout,d.stderr].filter(Boolean).join("\n")||JSON.stringify(d,null,2)));}
    catch(e){if(!controller.signal.aborted)setOriginal('원문 조회 오류: '+String(e));}
  };
  if(error)return <Card padding={4}><HStack hAlign="between"><Text role="alert">실패 기록 조회 오류</Text><Button label="다시 조회" variant="ghost" size="sm" onClick={()=>setRetry(v=>v+1)}/></HStack></Card>;
  if(!report?.job||!["failed","interrupted"].includes(report.job.status))return null;
  const title=report.job.status==="interrupted"?"종료 상태":"실패 원인";
  const content=<VStack gap={3}>
    {!embedded&&<><HStack hAlign="between" gap={3} vAlign="center"><Heading level={3}>{title}</Heading><Text color="secondary">{new Date(report.job.finished_at||report.job.started_at).toLocaleString("ko-KR")}</Text></HStack><Text>{report.job.goal||report.job.checks.map(c=>modes[c]||c).join(" · ")}</Text></>}
    <Text weight="bold">{report.reason}</Text>
    <HStack gap={3} style={{flexWrap:"wrap"}}>
      {report.job.kind==="agent"&&typeof report.used==="number"&&<Text color="secondary">모델 요청 {report.used} / {report.limit}회</Text>}
      {typeof report.total_steps==="number"&&<Text color="secondary">작업 단계 {report.completed_steps} / {report.total_steps}</Text>}
      {typeof report.exit_code==="number"&&<Text color="secondary">종료 코드 {report.exit_code}</Text>}
    </HStack>
    {fault&&<VStack gap={2}>
      <Text weight="bold">{report.later_verified?"이전 오류 · 이후 수정 검사 통과":"마지막 오류"}{fault.mode?` · ${modes[fault.mode]||fault.mode}`:fault.tool?` · ${fault.tool}`:""}</Text>
      {fault.path&&<Text color="secondary" style={{overflowWrap:"anywhere"}}>{fault.path}</Text>}
      <pre style={{margin:0,fontFamily:"var(--font-family-mono,monospace)",fontSize:"var(--text-small-size)",whiteSpace:"pre-wrap",overflowWrap:"anywhere",maxHeight:"12rem",overflow:"auto",lineHeight:1.6}}>{fault.message}</pre>
      {!!fault.seq&&<Collapsible trigger="원문 보기" defaultIsOpen={false} onOpenChange={open=>{if(open)loadOriginal();}}><pre style={{margin:0,whiteSpace:"pre-wrap",overflowWrap:"anywhere",fontSize:"var(--text-small-size)",maxHeight:"24rem",overflow:"auto"}}>{original||"불러오는 중"}</pre></Collapsible>}
    </VStack>}
    {!fault&&report.code!=="round_limit"&&<Text color="secondary">구체적인 오류 메시지가 기록되지 않았습니다.</Text>}
  </VStack>;
  return embedded?content:<Card padding={5} role="region" aria-label={title} style={{borderLeft:"3px solid var(--color-text-error)"}}>{content}</Card>;
}
