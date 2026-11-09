import { useEffect, useState } from 'react';
import { VStack, HStack } from '@astryxdesign/core/Layout';
import { Heading, Text } from '@astryxdesign/core/Text';
import { TextInput } from '@astryxdesign/core/TextInput';
import { Selector } from '@astryxdesign/core/Selector';
import { Button } from '@astryxdesign/core/Button';
import { Card } from '@astryxdesign/core/Card';
import { Collapsible } from '@astryxdesign/core/Collapsible';
import { apiFetch, projectId } from './api';
type Project={id:string;name:string;root:string;preview_url:string;available:boolean;active?:{status:string}|null};
export function switchProject(id:string){if(id===projectId)return;const url=new URL(window.location.href);url.searchParams.set('project',id);window.location.assign(url);}
export function ProjectPicker(){
  const [projects,setProjects]=useState<Project[]>([]);
  useEffect(()=>{const c=new AbortController();apiFetch('/api/projects',{signal:c.signal}).then(r=>r.json()).then(d=>{if(!c.signal.aborted)setProjects(d.projects||[]);}).catch(()=>{});return()=>c.abort();},[]);
  return <Selector label="프로젝트" size="sm" isLabelHidden value={projectId} options={projects.map(p=>({value:p.id,label:p.name,disabled:!p.available}))} onChange={switchProject}/>;
}
export default function ProjectManager({token}:{token:string}){
  const [projects,setProjects]=useState<Project[]>([]),[modelUrl,setModelUrl]=useState('http://127.0.0.1:8099/v1'),[db,setDb]=useState(''),[error,setError]=useState(''),[busy,setBusy]=useState(false);
  useEffect(()=>{const c=new AbortController();apiFetch('/api/projects',{signal:c.signal}).then(r=>r.json()).then(d=>{if(!c.signal.aborted)setProjects(d.projects||[]);}).catch(e=>{if(!c.signal.aborted)setError(String(e));});return()=>c.abort();},[]);
  async function add(){setBusy(true);setError('');try{
    const headers={'Content-Type':'application/json','X-Platform-Token':token};
    const picked=await apiFetch('/api/projects/pick',{method:'POST',headers,body:'{}'});const folder=await picked.json();if(!picked.ok)throw Error(folder.error);if(folder.cancelled)return;
    const existing=projects.find(p=>p.root===folder.root);if(existing){switchProject(existing.id);return;}
    const response=await apiFetch('/api/projects',{method:'POST',headers,body:JSON.stringify({root:folder.root,model_url:modelUrl,test_db_url:db})});const result=await response.json();if(!response.ok)throw Error(result.error);switchProject(result.id);
  }catch(e){setError(String(e));}finally{setBusy(false);}}
  return <VStack gap={5}>
    {projects.map(p=><Card key={p.id} padding={4}><HStack hAlign="between" gap={3}><VStack gap={2}><Text weight="bold">{p.name}{p.id===projectId?' · 현재 프로젝트':''}</Text><Text color="secondary" style={{overflowWrap:'anywhere'}}>{p.root}</Text>{p.active&&<Text>실행 중</Text>}{!p.available&&<Text>프로젝트 폴더를 찾을 수 없습니다.</Text>}</VStack><Button label={`${p.name} 열기`} isDisabled={!p.available||p.id===projectId} onClick={()=>switchProject(p.id)}/></HStack></Card>)}
    <Card padding={5}><VStack gap={4}><HStack hAlign="between"><Heading level={2}>프로젝트 추가</Heading><Button label={busy?'폴더 선택 중':'폴더 선택'} isDisabled={busy||!token} onClick={add}/></HStack><Collapsible trigger="실행 설정" defaultIsOpen={false}><VStack gap={3}><TextInput label="모델 서버" value={modelUrl} onChange={setModelUrl}/><TextInput label="테스트 DB URL" value={db} onChange={setDb} placeholder="jdbc:postgresql://호스트:5432/프로젝트_test"/><Text color="secondary">백엔드 검사는 프로젝트 전용 테스트 DB를 지정해야 사용할 수 있습니다.</Text></VStack></Collapsible>{error&&<Text role="alert">{error}</Text>}</VStack></Card>
  </VStack>;
}
