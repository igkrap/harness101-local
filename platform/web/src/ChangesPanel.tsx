import { lazy, Suspense, useEffect, useState } from 'react';
import { VStack, HStack } from '@astryxdesign/core/Layout';
import { Text, Heading } from '@astryxdesign/core/Text';
import { Card } from '@astryxdesign/core/Card';
import { Button } from '@astryxdesign/core/Button';
import { apiFetch } from './api';
const DiffEditor=lazy(()=>import('./DiffEditor'));
type File={path:string;status:string;added:number;removed:number;revision?:string;current?:string};
const currentLabel:Record<string,[string,string]>={applied:['현재 코드에 반영됨','applied'],reverted:['되돌려짐 · 현재 코드에 없음','reverted'],changed:['이후 다시 수정됨','changed'],unknown:['현재 상태 확인 불가','changed']};
type Contents={path:string;before:string;after:string};
export function ChangesPanel({jobId,refreshKey,embedded=false,autoOpen=false}:{jobId:string;refreshKey?:string|number;embedded?:boolean;autoOpen?:boolean}){
  const [files,setFiles]=useState<File[]>([]),[recorded,setRecorded]=useState<boolean|null>(null),[selected,setSelected]=useState(''),[body,setBody]=useState<Contents|null>(null),[error,setError]=useState(''),[side,setSide]=useState(false),[warnings,setWarnings]=useState<string[]>([]);
  useEffect(()=>{const c=new AbortController();apiFetch(`/api/jobs/${jobId}/diff`,{signal:c.signal}).then(async r=>{const d=await r.json();if(!r.ok)throw Error(d.error);if(!c.signal.aborted){const next=Array.isArray(d.files)?d.files:[];setFiles(next);setSelected(previous=>next.some((f:File)=>f.path===previous)?previous:autoOpen?next[0]?.path||"":"");setRecorded(d.recorded===true);setWarnings(d.warnings||[]);setError('');}}).catch(e=>{if(!c.signal.aborted)setError(String(e));});return()=>c.abort();},[jobId,refreshKey,autoOpen]);
  const revision=files.find(f=>f.path===selected)?.revision;
  useEffect(()=>{setBody(null);if(!selected||!files.some(f=>f.path===selected))return;const c=new AbortController();apiFetch(`/api/jobs/${jobId}/diff?path=${encodeURIComponent(selected)}`,{signal:c.signal}).then(async r=>{const d=await r.json();if(!r.ok)throw Error(d.error);if(!c.signal.aborted)setBody(d);}).catch(e=>{if(!c.signal.aborted)setError(String(e));});return()=>c.abort();},[jobId,selected,revision]);
  const content=<VStack gap={3}><HStack hAlign="between"><Heading level={3}>코드 변경</Heading><Text color="secondary">{files.length}개 파일</Text></HStack>{error&&<Text role="alert">{error}</Text>}{recorded===false&&<Text color="secondary">이 실행은 변경 전 코드를 저장하지 않았습니다.</Text>}{recorded&&files.length===0&&<Text color="secondary">반영된 코드 변경이 없습니다.</Text>}{warnings.map((w,i)=><Text key={i} color="secondary">{w}</Text>)}
    {files.map(f=><HStack key={f.path} hAlign="between" gap={2}><Button label={f.path} className="change-file" size="sm" variant={selected===f.path?'secondary':'ghost'} onClick={()=>setSelected(f.path)}/><HStack gap={2}>{f.current&&<span className={`change-current change-${currentLabel[f.current]?.[1]||'changed'}`}>{currentLabel[f.current]?.[0]||f.current}</span>}<Text color="secondary">{{added:'추가',deleted:'삭제',modified:'수정'}[f.status]}</Text><Text style={{color:'var(--color-text-success)'}}>+{f.added}</Text><Text style={{color:'var(--color-text-error)'}}>−{f.removed}</Text></HStack></HStack>)}
    {body&&<><HStack hAlign="between"><Text color="secondary">변경 전 → 변경 후</Text><Button label={side?'한 화면으로 보기':'나란히 보기'} size="sm" variant="ghost" onClick={()=>setSide(!side)}/></HStack><Suspense fallback={<Text>변경 비교 불러오는 중</Text>}><DiffEditor {...body} sideBySide={side}/></Suspense></>}
  </VStack>;
  return embedded?<VStack role="region" aria-label="코드 변경">{content}</VStack>:<Card padding={5} role="region" aria-label="코드 변경">{content}</Card>;
}
