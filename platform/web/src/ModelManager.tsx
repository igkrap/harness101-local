import {useEffect,useState} from 'react';
import {VStack,HStack} from '@astryxdesign/core/Layout';
import {Text,Heading} from '@astryxdesign/core/Text';
import {TextInput} from '@astryxdesign/core/TextInput';
import {Button} from '@astryxdesign/core/Button';
import {Card} from '@astryxdesign/core/Card';
import {StatusBadge} from './StatusBadge';
import {apiFetch} from './api';
export type ModelConfig={id:string;name:string;model:string;url:string;temperature:number;max_tokens:number;timeout:number};
const empty={name:'',model:'',url:'http://127.0.0.1:8099/v1',temperature:'1',max_tokens:'4096',timeout:'600'};
type Form=typeof empty & {id?:string};
export default function ModelManager({token}:{token:string}){
 const [models,setModels]=useState<ModelConfig[]>([]),[defaultId,setDefaultId]=useState(''),[form,setForm]=useState<Form>(empty),[busy,setBusy]=useState(false),[formOpen,setFormOpen]=useState(false),[error,setError]=useState(''),[result,setResult]=useState<{success:boolean;message:string}|null>(null);
 async function load(){const r=await apiFetch('/api/model-configs');const d=await r.json();if(!r.ok)throw Error(d.error);setModels(d.models);setDefaultId(d.default||'');}
 useEffect(()=>{load().catch(e=>setError(String(e)));},[]);
 function edit(m:ModelConfig){setFormOpen(true);setForm({...m,temperature:String(m.temperature),max_tokens:String(m.max_tokens),timeout:String(m.timeout)});setResult(null);setError('');}
 function field(key:keyof Form,value:string){setForm(f=>({...f,[key]:value}));setResult(null);}
 async function send(action:string,id?:string){setBusy(true);setError('');setResult(null);try{
  const payload=action==='save'||action==='test'?{...form,temperature:Number(form.temperature),max_tokens:Number(form.max_tokens),timeout:Number(form.timeout)}:{id,action};
  const r=await apiFetch('/api/model-configs'+(action==='test'?'/test':''),{method:'POST',headers:{'Content-Type':'application/json','X-Platform-Token':token},body:JSON.stringify(payload)});const d=await r.json();if(!r.ok)throw Error(d.error);
  if(action==='test'){setResult({success:d.success,message:d.success?`응답 확인 · ${(d.duration_ms/1000).toFixed(1)}초 · ${d.response}`:d.error});return;}
  if(action==='save'){setForm({...d,temperature:String(d.temperature),max_tokens:String(d.max_tokens),timeout:String(d.timeout)});setResult({success:true,message:'저장했습니다.'});}
  if(action==='remove'&&form.id===id)setForm(empty);await load();
 }catch(e){setError(String(e));}finally{setBusy(false);}}
 return <section aria-label="모델 설정"><VStack gap={5}>
  <HStack hAlign="between" vAlign="center"><Text color="secondary">등록한 모델을 작업 실행에서 선택합니다.</Text><Button label="모델 추가" size="sm" onClick={()=>{setForm(empty);setFormOpen(true);setResult(null);setError('');}}/></HStack>
  {models.map(m=><Card key={m.id} padding={4}><VStack gap={3}><HStack hAlign="between" gap={3} style={{flexWrap:'wrap'}}><HStack gap={2}><Text weight="bold">{m.name}</Text>{defaultId===m.id&&<StatusBadge value="idle" label="현재 프로젝트 기본"/>}</HStack><HStack gap={2}><Button label={`${m.name} 수정`} size="sm" variant="ghost" onClick={()=>edit(m)} isDisabled={busy}>수정</Button>{defaultId!==m.id&&<Button label={`${m.name} 기본으로 사용`} size="sm" variant="ghost" onClick={()=>send('default',m.id)} isDisabled={busy}>기본으로 사용</Button>}<Button label={`${m.name} 삭제`} size="sm" variant="ghost" onClick={()=>send('remove',m.id)} isDisabled={busy}>삭제</Button></HStack></HStack><Text style={{overflowWrap:'anywhere'}}>{m.model}</Text><Text color="secondary" style={{overflowWrap:'anywhere'}}>{m.url} · Temperature {m.temperature} · 최대 {m.max_tokens.toLocaleString()} 토큰 · 응답 대기 {m.timeout}초</Text></VStack></Card>)}
  {(formOpen||!!form.id||!models.length)&&<Card padding={5}><form onSubmit={e=>{e.preventDefault();send('save');}}><VStack gap={4}>
   <Heading level={3}>{form.id?'모델 수정':'모델 등록'}</Heading>
   <TextInput label="설정 이름" value={form.name} onChange={v=>field('name',v)} placeholder="예: Qwen3.8 27B"/>
   <TextInput label="모델 ID" value={form.model} onChange={v=>field('model',v)} placeholder="서버가 사용하는 정확한 모델 ID"/>
   <TextInput label="API 주소" value={form.url} onChange={v=>field('url',v)} placeholder="http://127.0.0.1:8099/v1"/>
   <HStack gap={3} style={{flexWrap:'wrap'}}><TextInput label="Temperature" value={form.temperature} onChange={v=>field('temperature',v)}/><TextInput label="최대 출력 토큰" value={form.max_tokens} onChange={v=>field('max_tokens',v)}/><TextInput label="응답 대기 (초)" value={form.timeout} onChange={v=>field('timeout',v)}/></HStack>
   <Text color="secondary">기본 설정에서는 작업 시간과 모델 호출 횟수에 제한을 두지 않습니다. 응답 대기는 헤더 대기와 본문 수신 중 데이터가 없는 시간에 각각 적용됩니다(30~3,600초). 연결 오류는 최대 4회 재시도하며, 응답 대기 초과는 현재 변경을 보존한 뒤 단계당 한 번 재시도합니다. 도구 실행 제한과 모델 호출 횟수는 별도입니다.</Text>
   <HStack gap={2}><Button label={busy?'요청 중':'저장'} type="submit" isDisabled={busy||!token}/><Button label="연결 확인" variant="secondary" onClick={()=>send('test')} isDisabled={busy||!token}/>{(form.id||formOpen)&&<Button label={form.id?"수정 취소":"닫기"} variant="ghost" onClick={()=>{setForm(empty);setFormOpen(false);}} isDisabled={busy}/>}</HStack>
   {result&&<HStack gap={2}><StatusBadge value={result.success?'passed':'failed'}/><Text role="status" style={{overflowWrap:'anywhere'}}>{result.message}</Text></HStack>}{error&&<Text role="alert" style={{color:'var(--color-text-error)'}}>{error}</Text>}
  </VStack></form></Card>}
 </VStack></section>;
}
