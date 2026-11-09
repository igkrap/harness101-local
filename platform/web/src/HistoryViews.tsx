import { compactEvents } from "./logEntries";
import { apiFetch } from "./api";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import { HStack, VStack } from "@astryxdesign/core/Layout";
import { Text } from "@astryxdesign/core/Text";
import { Button } from "@astryxdesign/core/Button";
import type { FlowEvent } from "./flowState";
export type RunRecord={id:string;kind:string;goal:string;checks:string[];rounds:number;status:string;started_at:string;finished_at:string|null;exit_code:number|null;completion_policy?:string};
type EventPage={events:FlowEvent[];next_before:number|null;next_after?:number|null;total:number};
async function read<T>(url:string,signal?:AbortSignal):Promise<T>{const response=await apiFetch(url,{signal,cache:"no-store"});const result=await response.json();if(!response.ok)throw Error(result.error||`HTTP ${response.status}`);return result;}
const mergeJobs=(old:RunRecord[],fresh:RunRecord[])=>[...new Map([...old,...fresh].map(j=>[j.id,j])).values()].sort((a,b)=>b.started_at.localeCompare(a.started_at)||b.id.localeCompare(a.id));
const mergeEvents=(old:FlowEvent[],fresh:FlowEvent[])=>[...new Map([...old,...fresh].map(e=>[e.seq,e])).values()].sort((a,b)=>b.seq-a.seq);

function VirtualRows({count,render,height=560,onEnd,label}:{count:number;render:(i:number)=>ReactNode;height?:number;onEnd?:()=>void;label:string}){
  const scroll=useRef<HTMLDivElement>(null);
  const list=useVirtualizer({count,getScrollElement:()=>scroll.current,estimateSize:()=>108,overscan:4});
  const items=list.getVirtualItems();const last=items.at(-1)?.index;
  useEffect(()=>{if(last!==undefined&&last>=count-3)onEnd?.();},[last,count,onEnd]);
  return <div ref={scroll} role="region" aria-label={label} style={{height,maxHeight:"65dvh",overflow:"auto",minWidth:0,overflowAnchor:"none"}}><div style={{height:list.getTotalSize(),position:"relative",width:"100%"}}>{items.map(item=><div key={item.key} data-index={item.index} ref={list.measureElement} style={{position:"absolute",top:0,left:0,width:"100%",transform:`translateY(${item.start}px)`}}>{render(item.index)}</div>)}</div></div>;
}

export function JobHistory({recent,cursor,total,selected,onSelect,renderJob,kind}:{recent:RunRecord[];cursor?:string|null;total?:number;selected?:string;kind?:string;onSelect:(job:RunRecord)=>void;renderJob:(job:RunRecord,select:()=>void,selected:boolean)=>ReactNode}){
  const [jobs,setJobs]=useState(recent),[next,setNext]=useState(cursor||null),[loading,setLoading]=useState(false),[error,setError]=useState("");
  const busy=useRef(false),older=useRef(false),request=useRef<AbortController|null>(null);
  useEffect(()=>{setJobs(previous=>mergeJobs(previous,recent));if(!older.current)setNext(cursor||null);},[recent,cursor]);
  useEffect(()=>()=>request.current?.abort(),[]);
  const more=async()=>{
    if(!next||busy.current||error)return;busy.current=true;setLoading(true);const controller=new AbortController();request.current=controller;
    try{const page=await read<{jobs:RunRecord[];next:string|null}>("/api/jobs?limit=20"+(kind?"&kind="+encodeURIComponent(kind):"")+"&before="+encodeURIComponent(next),controller.signal);if(!controller.signal.aborted){older.current=true;setJobs(previous=>mergeJobs(previous,page.jobs));setNext(page.next ?? null);}}
    catch(e){if(!controller.signal.aborted)setError(String(e));}
    finally{busy.current=false;if(!controller.signal.aborted)setLoading(false);}
  };
  return <VStack gap={2}><Text color="secondary">{total??jobs.length}개</Text>{!jobs.length?<Text color="secondary">실행 기록 없음</Text>:<VirtualRows count={jobs.length+(next?1:0)} label="실행 기록 목록" onEnd={more} render={i=>i<jobs.length?renderJob(jobs[i],()=>onSelect(jobs[i]),jobs[i].id===selected):<VStack padding={3}><Button label={loading?"불러오는 중":"다음 기록"} size="sm" variant="ghost" isDisabled={loading} onClick={()=>{setError("");busy.current=false;more();}}/></VStack>}/>}{error&&<Text role="alert">{error}</Text>}</VStack>;
}

export function PagedEvents({jobId,recent,renderRow}:{jobId:string;recent:FlowEvent[];renderRow:(event:FlowEvent)=>ReactNode}){
  const [filter,setFilter]=useState("all"),[rows,setRows]=useState(()=>mergeEvents([],recent)),[next,setNext]=useState<number|null>(recent.length&&recent[0].seq>1?recent[0].seq:null),[loading,setLoading]=useState(false),[error,setError]=useState("");
  const request=useRef<AbortController|null>(null),busy=useRef(false),ready=useRef(false),version=useRef(0);
  const matches=(e:FlowEvent)=>filter==="all"||e.type.startsWith(filter+".");
  useEffect(()=>{setRows(previous=>mergeEvents(previous,recent.filter(matches)));},[recent,filter]);
  useEffect(()=>{
    const epoch=++version.current;request.current?.abort();const controller=new AbortController();request.current=controller;busy.current=true;ready.current=false;setLoading(true);setRows([]);setNext(null);setError("");
    read<EventPage>(`/api/jobs/${jobId}/events?limit=80&kind=${filter}`,controller.signal).then(page=>{if(epoch===version.current&&!controller.signal.aborted){setRows(mergeEvents([],page.events));setNext(page.next_before ?? null);ready.current=true;}}).catch(e=>{if(!controller.signal.aborted)setError(String(e));}).finally(()=>{if(epoch===version.current){busy.current=false;setLoading(false);}});
    return()=>controller.abort();
  },[jobId,filter]);
  const more=async()=>{
    if(next===null||busy.current||!ready.current||error)return;const epoch=version.current;busy.current=true;setLoading(true);const controller=new AbortController();request.current=controller;
    try{const page=await read<EventPage>(`/api/jobs/${jobId}/events?limit=80&kind=${filter}&before=${next}`,controller.signal);if(epoch===version.current&&!controller.signal.aborted){setRows(previous=>mergeEvents(previous,page.events));setNext(page.next_before ?? null);}}
    catch(e){if(!controller.signal.aborted)setError(String(e));}
    finally{if(epoch===version.current){busy.current=false;setLoading(false);}}
  };
  const visible=compactEvents(rows);
  return <VStack gap={3}><HStack gap={1} style={{flexWrap:"wrap"}}>{[["all","전체"],["model","모델"],["tool","도구"],["check","검사"],["autonomy","재시도·단계"]].map(([key,label])=><Button key={key} label={label} size="sm" variant={filter===key?"secondary":"ghost"} onClick={()=>setFilter(key)}/>)}</HStack>{error&&<Text role="alert">{error}</Text>}{!visible.length?<Text color="secondary">{loading?"불러오는 중":"이벤트 없음"}</Text>:<VirtualRows key={filter} count={visible.length+(next!==null?1:0)} label="이벤트 목록" onEnd={more} render={i=>i<visible.length?renderRow(visible[i]):<VStack padding={3}><Button label={loading?"불러오는 중":"이전 이벤트"} size="sm" variant="ghost" isDisabled={loading} onClick={more}/></VStack>}/>}</VStack>;
}
