import { useEffect, useState } from 'react';
import { VStack, HStack } from '@astryxdesign/core/Layout';
import { Heading, Text } from '@astryxdesign/core/Text';
import { TextInput } from '@astryxdesign/core/TextInput';
import { Selector } from '@astryxdesign/core/Selector';
import { Button } from '@astryxdesign/core/Button';
import { Card } from '@astryxdesign/core/Card';
import { Collapsible } from '@astryxdesign/core/Collapsible';
import { apiFetch, forgetProject, projectId } from './api';
type Project={id:string;name:string;root:string;preview_url:string;available:boolean;active?:{status:string}|null;title?:string;site?:{title:string;slug:string;kind:string;first?:boolean}};
type Kind={id:string;label:string;description:string;enabled:boolean};
const titleOf=(p:Project)=>p.site?.title||p.title||p.name;
const shown=(p:Project)=>titleOf(p)!==p.name?`${titleOf(p)} (${p.name})`:p.name;
export function switchProject(id:string){if(id===projectId)return;const url=new URL(window.location.href);url.searchParams.set('project',id);window.location.assign(url);}
export function ProjectPicker(){
  const [projects,setProjects]=useState<Project[]>([]);
  useEffect(()=>{const c=new AbortController();apiFetch('/api/projects',{signal:c.signal}).then(async r=>{if(r.ok)return r.json();if(projectId!=='default')forgetProject();return {};}).then(d=>{if(c.signal.aborted)return;const list:Project[]=d.projects||[];
    if(list.length&&projectId!=='default'&&!list.some(p=>p.id===projectId)){forgetProject();return;}setProjects(list);}).catch(()=>{});return()=>c.abort();},[]);
  return <Selector label="프로젝트" size="sm" isLabelHidden value={projectId} options={projects.map(p=>({value:p.id,label:titleOf(p),disabled:!p.available}))} onChange={switchProject}/>;
}
type EnvWay={way:string;label:string;command:string};
type EnvItem={id:string;label:string;why:string;state:'ok'|'missing'|'off';detail:string;find:boolean;fix:{label:string;command:string;installs:boolean;manual?:boolean;note?:string;ways?:EnvWay[]}|null};
/** What this computer needs for the platform and its projects: looked at, found where it is installed, and set up from here -
 *  by several ways (official builds, or Homebrew / winget when there); a program is put on the computer only when asked once more. */
export function EnvironmentCheck({token}:{token:string}){
  const [items,setItems]=useState<EnvItem[]|null>(null),[busy,setBusy]=useState(''),[said,setSaid]=useState(''),[all,setAll]=useState(false);
  const [asking,setAsking]=useState<{id:string;way?:string;text:string;every?:boolean}|null>(null),[typing,setTyping]=useState<{id:string;path:string}|null>(null);
  const load=()=>apiFetch('/api/environment').then(r=>r.json()).then(d=>setItems(d.items||[])).catch(e=>setSaid(String(e)));
  useEffect(()=>{void load();},[]);
  async function call(path:string,body:object,label:string){setBusy(label);setSaid('');setAsking(null);try{
    const response=await apiFetch(path,{method:'POST',headers:{'Content-Type':'application/json','X-Platform-Token':token},body:JSON.stringify(body)});
    const result=await response.json();if(!response.ok)throw Error(result.error);if(result.items)setItems(result.items);return result;
  }catch(e){setSaid(String(e instanceof Error?e.message:e));return null;}finally{setBusy('');}}
  async function fix(id:string,way?:string,sure=false){const result=await call('/api/environment/fix',{id,way,sure},id);if(!result)return;
    if(result.ask)setAsking({id,way:result.way,text:result.ask});else setSaid([result.said,result.command].filter(Boolean).join(' '));}
  async function everything(sure=false){const result=await call('/api/environment/setup-all',{sure},'all');if(!result)return;
    if(result.ask)setAsking({id:'all',text:result.ask+' (나머지도 이어서 셋업합니다)',every:true});else setSaid([result.said,result.command].filter(Boolean).join(' '));}
  async function find(id:string,path?:string){const result=await call('/api/environment/find',{id,path},id);if(result){setSaid(result.said||'');if(result.done)setTyping(null);}}
  const lacking=(items||[]).filter(item=>item.state!=='ok').length;
  return <Card padding={5}><VStack gap={3}>
    <HStack hAlign="between"><Heading level={2}>개발 환경 점검</Heading><HStack gap={2}>
      {lacking>0&&<Button label={busy==='all'?'셋업하는 중…':'모두 셋업'} variant="primary" isDisabled={!!busy||!token} onClick={()=>void everything()}/>}
      <Button label="다시 점검" variant="secondary" isDisabled={!!busy} onClick={()=>{setItems(null);void load();}}/></HStack></HStack>
    {items===null?<Text color="secondary">점검하는 중…</Text>:<HStack gap={2} vAlign="center"><Text color="secondary">{lacking?`${items.length}개 중 ${lacking}개가 준비되지 않았습니다.`:`${items.length}개 모두 준비됨`}</Text>
      <Button label={all?'접기':'자세히'} variant="secondary" onClick={()=>setAll(v=>!v)}/></HStack>}
    {(items||[]).filter(item=>all||item.state!=='ok').map(item=><VStack key={item.id} gap={2}>
      <HStack hAlign="between" gap={3} style={{flexWrap:'wrap'}}>
        <VStack gap={1}><Text weight="bold">{item.state==='ok'?'✓':item.state==='off'?'!':'✗'} {item.label}</Text><Text color="secondary">{item.detail} · {item.why}</Text></VStack>
        <HStack gap={2} vAlign="center" style={{flexWrap:'wrap'}}>
          {item.find&&<Button label={busy===item.id?'찾는 중…':'찾기'} variant="secondary" isDisabled={!!busy||!token} onClick={()=>void find(item.id)}/>}
          {item.find&&<Button label="경로 지정" variant="secondary" isDisabled={!!busy} onClick={()=>setTyping({id:item.id,path:''})}/>}
          {item.fix?.ways?item.fix.ways.map(way=><Button key={way.way} label={way.label} variant="secondary" isDisabled={!!busy||!token} onClick={()=>void fix(item.id,way.way)}/>)
            :item.fix&&<Button label={busy===item.id?'하는 중…':item.fix.label} variant="primary" isDisabled={!!busy||!token} onClick={()=>void fix(item.id)}/>}
        </HStack></HStack>
      {item.fix?.ways&&<Text color="secondary">{item.fix.ways.map(way=>`${way.label}: ${way.command}`).join(' · ')}</Text>}
      {typing?.id===item.id&&<HStack gap={2} vAlign="end"><div style={{flex:'1 1 360px'}}><TextInput label={`${item.label} 이(가) 있는 곳 (프로그램 파일 또는 폴더)`} value={typing.path} onChange={v=>setTyping({id:item.id,path:v})} placeholder="예: /Applications/Docker.app/Contents/Resources/bin/docker"/></div>
        <Button label="이 경로 쓰기" variant="primary" isDisabled={!!busy||!typing.path.trim()} onClick={()=>void find(item.id,typing.path)}/><Button label="그만두기" variant="secondary" onClick={()=>setTyping(null)}/></HStack>}
    </VStack>)}
    {asking&&<HStack gap={2} vAlign="center" style={{flexWrap:'wrap'}}><Text>{asking.text}</Text>
      <Button label="설치" variant="primary" isDisabled={!!busy} onClick={()=>void (asking.every?everything(true):fix(asking.id,asking.way,true))}/><Button label="그만두기" variant="secondary" onClick={()=>setAsking(null)}/></HStack>}
    {said&&<Text role="status">{said}</Text>}
  </VStack></Card>;
}

type ProjectEnv={id:string;title:string;root:string;ports:{api_port:number;preview_port:number};db:string;api_container:string;running:{api:boolean;preview:boolean};
  items:EnvItem[];git:{branch:string;last:string;unrecorded:number};free:{api:number[];preview:number[]}};
/** One project's development environment: its ports (moved to other free ones here), database and server, whether its servers run,
 *  its screen packages, where its records stand. */
function ProjectEnvironment({id,token}:{id:string;token:string}){
  const [env,setEnv]=useState<ProjectEnv|null>(null),[ports,setPorts]=useState<Record<string,string>>({}),[busy,setBusy]=useState(''),[said,setSaid]=useState('');
  const load=()=>apiFetch(`/api/projects/environment?id=${encodeURIComponent(id)}`).then(r=>r.json()).then(d=>{if(d.ports){setEnv(d);setPorts(Object.fromEntries(Object.entries(d.ports).map(([k,v])=>[k,String(v)])));}else setSaid(d.error||'');}).catch(e=>setSaid(String(e)));
  useEffect(()=>{void load();},[id]);
  async function post(path:string,body:object,label:string,done:string){setBusy(label);setSaid('');try{
    const response=await apiFetch(path,{method:'POST',headers:{'Content-Type':'application/json','X-Platform-Token':token},body:JSON.stringify(body)});
    const result=await response.json();if(!response.ok)throw Error(result.error);if(result.ports)setEnv(result);else void load();setSaid(result.said||done);
  }catch(e){setSaid(String(e instanceof Error?e.message:e));}finally{setBusy('');}}
  if(!env)return <Text color="secondary">{said||'읽는 중…'}</Text>;
  const changed=Object.entries(env.ports).some(([k,v])=>String(v)!==ports[k]);
  const pick=(label:string,key:'api_port'|'preview_port',list:number[])=><div style={{flex:'1 1 150px'}}>
    <Selector label={label} value={ports[key]||''} isDisabled={!!busy} options={[...new Set([env.ports[key],...list])].map(port=>({value:String(port),label:String(port)+(port===env.ports[key]?' (지금)':'')}))} onChange={v=>setPorts(previous=>({...previous,[key]:v}))}/></div>;
  return <VStack gap={3} style={{marginTop:12}}>
    <HStack gap={3} vAlign="end" style={{flexWrap:'wrap'}}>
      {pick('백엔드(API) 포트','api_port',env.free.api)}{pick('화면(미리보기) 포트','preview_port',env.free.preview)}
      <Button label={busy==='ports'?'바꾸는 중… (서버를 다시 띄움)':'포트 바꾸기'} variant="primary" isDisabled={!!busy||!token||!changed} onClick={()=>void post('/api/projects/change-ports',{id,...ports},'ports','포트를 바꿨습니다.')}/>
    </HStack>
    <Text color="secondary">DB {env.db} · 서버 {env.api_container} {env.running.api?'켜짐':'꺼짐'} · 미리보기 {env.running.preview?'켜짐':'꺼짐'}</Text>
    <Text color="secondary">형상관리: 작업 공간 {env.git.branch||'-'} · 마지막 기록 {env.git.last||'-'} · 기록 안 된 변경 {env.git.unrecorded}개</Text>
    {env.items.map(item=><HStack key={item.id} gap={2} vAlign="center"><Text>{item.state==='ok'?'✓':'✗'} {item.label} - {item.detail}</Text>
      {item.fix&&<Button label={busy===item.id?'설치하는 중…':item.fix.label} variant="secondary" isDisabled={!!busy||!token} onClick={()=>void post('/api/environment/fix',{id:item.id},item.id,'설치했습니다.')}/>}</HStack>)}
    {said&&<Text role="status">{said}</Text>}
  </VStack>;
}

export default function ProjectManager({token}:{token:string}){
  const [projects,setProjects]=useState<Project[]>([]),[modelUrl,setModelUrl]=useState('http://127.0.0.1:8099/v1'),[db,setDb]=useState(''),[error,setError]=useState(''),[busy,setBusy]=useState(false);
  const [envOpen,setEnvOpen]=useState<string|null>(null);
  const [kinds,setKinds]=useState<Kind[]>([]),[kind,setKind]=useState('business'),[title,setTitle]=useState(''),[slug,setSlug]=useState(''),[making,setMaking]=useState(false),[makeError,setMakeError]=useState('');
  useEffect(()=>{const c=new AbortController();apiFetch('/api/projects',{signal:c.signal}).then(r=>r.json()).then(d=>{if(!c.signal.aborted){setProjects(d.projects||[]);setKinds(d.kinds||[]);}}).catch(e=>{if(!c.signal.aborted)setError(String(e));});return()=>c.abort();},[]);
  async function add(){setBusy(true);setError('');try{
    const headers={'Content-Type':'application/json','X-Platform-Token':token};
    const picked=await apiFetch('/api/projects/pick',{method:'POST',headers,body:'{}'});const folder=await picked.json();if(!picked.ok)throw Error(folder.error);if(folder.cancelled)return;
    const existing=projects.find(p=>p.root===folder.root);if(existing){switchProject(existing.id);return;}
    const response=await apiFetch('/api/projects',{method:'POST',headers,body:JSON.stringify({root:folder.root,model_url:modelUrl,test_db_url:db})});const result=await response.json();if(!response.ok)throw Error(result.error);switchProject(result.id);
  }catch(e){setError(String(e));}finally{setBusy(false);}}
  const [removing,setRemoving]=useState<Project|null>(null),[typedName,setTypedName]=useState('');
  const [renaming,setRenaming]=useState<Project|null>(null),[newTitle,setNewTitle]=useState(''),[newSlug,setNewSlug]=useState('');
  async function rename(p:Project){
    setBusy(true);setError('');try{
      const body:{id:string;title?:string;slug?:string}={id:p.id};
      if(newTitle.trim()&&newTitle.trim()!==titleOf(p))body.title=newTitle.trim();
      if(p.site&&newSlug&&newSlug!==p.name)body.slug=newSlug;
      const response=await apiFetch('/api/projects/rename',{method:'POST',headers:{'Content-Type':'application/json','X-Platform-Token':token},body:JSON.stringify(body)});
      const result=await response.json();if(!response.ok)throw Error(result.error||'이름을 바꾸지 못했습니다.');
      setRenaming(null);
      // The English name is part of the project's identity here: with it the address of the project changes too.
      if(result.id!==p.id&&p.id===projectId){switchProject(result.id);return;}
      setProjects(list=>list.map(item=>item.id===p.id?{...item,...result}:item));
    }catch(e){setError(String(e instanceof Error?e.message:e));}finally{setBusy(false);}}
  async function remove(p:Project){
    setBusy(true);setError('');try{
      const response=await apiFetch('/api/projects/remove',{method:'POST',headers:{'Content-Type':'application/json','X-Platform-Token':token},body:JSON.stringify({id:p.id,confirm:typedName.trim()})});
      const result=await response.json();if(!response.ok)throw Error(result.error||'지우지 못했습니다.');
      setRemoving(null);setTypedName('');
      if(p.id===projectId)forgetProject();else setProjects(list=>list.filter(item=>item.id!==p.id));
    }catch(e){setError(String(e instanceof Error?e.message:e));}finally{setBusy(false);}}
  // the services of the new project: the first free ports by default, any other free one chosen from the list
  const [free,setFree]=useState<{api:number[];preview:number[]}>({api:[],preview:[]}),[ports,setPorts]=useState({api_port:'',preview_port:''});
  const loadPorts=()=>apiFetch('/api/projects/ports').then(r=>r.json()).then(d=>{if(d&&d.api){setFree(d);setPorts({api_port:String(d.api[0]??''),preview_port:String(d.preview[0]??'')});}}).catch(()=>{});
  useEffect(()=>{void loadPorts();},[]);
  const portField=(label:string,key:'api_port'|'preview_port',list:number[])=><div style={{flex:'1 1 150px'}}>
    <Selector label={label} value={ports[key]} isDisabled={making} options={[...new Set([...(ports[key]?[Number(ports[key])]:[]),...list])].map(port=>({value:String(port),label:String(port)}))} onChange={v=>setPorts(previous=>({...previous,[key]:v}))}/></div>;
  const slugOk=/^[a-z][a-z0-9-]{1,23}[a-z0-9]$/.test(slug);
  async function make(){setMaking(true);setMakeError('');try{
    const response=await apiFetch('/api/projects/create',{method:'POST',headers:{'Content-Type':'application/json','X-Platform-Token':token},body:JSON.stringify({title:title.trim(),slug,kind,...ports})});
    const result=await response.json();if(!response.ok)throw Error(result.error||'프로젝트를 만들지 못했습니다.');switchProject(result.id);
  }catch(e){setMakeError(String(e instanceof Error?e.message:e));}finally{setMaking(false);}}
  return <VStack gap={5}>
    <Card padding={5}><VStack gap={4}>
      <Heading level={2}>새 프로젝트 만들기</Heading>
      <div className="project-kinds" role="radiogroup" aria-label="사이트 종류">{kinds.map(k=>
        <button key={k.id} type="button" role="radio" aria-checked={kind===k.id} disabled={!k.enabled||making} className={`project-kind${kind===k.id?' is-chosen':''}`} onClick={()=>setKind(k.id)}>
          <strong>{k.label}{!k.enabled&&<span className="project-kind-soon">잠금</span>}</strong><span>{k.description}</span>
        </button>)}</div>
      <HStack gap={3} vAlign="end" style={{flexWrap:'wrap'}}>
        <div style={{flex:'1 1 260px'}}><TextInput label="프로젝트 이름 (화면과 셋업 팩에 보이는 이름)" value={title} onChange={setTitle} placeholder="예: 에이스 업무 시스템" isDisabled={making}/></div>
        <div style={{flex:'1 1 220px'}}><TextInput label="영문 이름 (폴더·DB·팩 파일 이름)" value={slug} onChange={v=>setSlug(v.toLowerCase().replace(/[^a-z0-9-]/g,''))} placeholder="예: acme-erp" isDisabled={making}/></div>
        <Button label={making?'만드는 중… (1~3분)':'만들기'} variant="primary" isDisabled={making||!token||!title.trim()||!slugOk} onClick={make}/>
      </HStack>
      <VStack gap={2}><Text weight="bold">개발 환경</Text>
        <HStack gap={3} vAlign="end" style={{flexWrap:'wrap'}}>
          {portField('백엔드(API) 포트','api_port',free.api)}{portField('화면(미리보기) 포트','preview_port',free.preview)}
          <div style={{flex:'1 1 200px'}}><Text color="secondary">DB 이름: {slug?'mdi_'+slug.replace(/-/g,'_'):'(영문 이름으로 정해짐)'}</Text></div>
          <Button label="빈 포트 다시 찾기" variant="secondary" isDisabled={making} onClick={()=>void loadPorts()}/>
        </HStack>
        <Text color="secondary">처음에는 비어 있는 첫 포트가 들어가 있습니다. 목록에는 다른 프로젝트나 이 컴퓨터가 쓰지 않는 포트만 나옵니다.</Text></VStack>
      <Text color="secondary">기본 프레임워크(공통 화면, 권한·메뉴, 화면 정의 엔진)를 그대로 담은 새 프로젝트를 만들고, 전용 개발 DB·서버·미리보기를 준비합니다. 화면은 0개에서 시작하며 셋업 팩도 이 이름으로 만들어집니다.</Text>
      {makeError&&<Text role="alert">{makeError}</Text>}
    </VStack></Card>
    {projects.map(p=><Card key={p.id} padding={4}><HStack hAlign="between" gap={3}><VStack gap={2}><Text weight="bold">{shown(p)}{p.id===projectId?' · 현재 프로젝트':''}</Text><Text color="secondary" style={{overflowWrap:'anywhere'}}>{p.root}</Text>{p.active&&<Text>실행 중</Text>}{!p.available&&<Text>프로젝트 폴더를 찾을 수 없습니다.</Text>}</VStack><HStack gap={2}>{p.site&&<Button label={envOpen===p.id?'개발 환경 닫기':'개발 환경'} variant="ghost" onClick={()=>setEnvOpen(envOpen===p.id?null:p.id)}/>}<Button label={`${p.name} 이름 바꾸기`} variant="ghost" isDisabled={busy||making} onClick={()=>{setRenaming(p);setRemoving(null);setNewTitle(titleOf(p));setNewSlug(p.name);setError('');}}/>{p.site&&!p.site.first&&<Button label={`${p.name} 지우기`} variant="ghost" isDisabled={busy||making} onClick={()=>{setRemoving(p);setRenaming(null);setTypedName('');setError('');}}/>}<Button label={`${p.name} 열기`} isDisabled={!p.available||p.id===projectId} onClick={()=>switchProject(p.id)}/></HStack></HStack>
      {envOpen===p.id&&<ProjectEnvironment id={p.id} token={token}/>}
      {renaming?.id===p.id&&<VStack gap={2} style={{marginTop:12}}>
        <HStack gap={2} vAlign="end" style={{flexWrap:'wrap'}}>
          <div style={{flex:'1 1 260px'}}><TextInput label="프로젝트 이름 (보이는 이름)" value={newTitle} onChange={setNewTitle}/></div>
          {p.site&&<div style={{flex:'1 1 220px'}}><TextInput label="영문 이름 (폴더·DB·서버·팩 파일 이름)" value={newSlug} onChange={v=>setNewSlug(v.toLowerCase().replace(/[^a-z0-9-]/g,''))}/></div>}
          <Button label={busy?'바꾸는 중…':'바꾸기'} variant="primary" isDisabled={busy||!newTitle.trim()||(newTitle.trim()===titleOf(p)&&newSlug===p.name)||(!!p.site&&!/^[a-z][a-z0-9-]{1,23}[a-z0-9]$/.test(newSlug))} onClick={()=>void rename(p)}/>
          <Button label="그만두기" variant="secondary" onClick={()=>setRenaming(null)}/></HStack>
        <Text color="secondary">{p.site?'영문 이름을 바꾸면 폴더, 개발 DB, 서버가 새 이름으로 옮겨지고 서버가 다시 켜집니다 (30초쯤). 자료와 깃 기록은 그대로입니다.':''}</Text>
      </VStack>}
      {removing?.id===p.id&&<VStack gap={2} style={{marginTop:12}}><Text>이 프로젝트의 폴더, 개발 DB, 서버, 실행 기록이 사라지고 되돌릴 수 없습니다 (이미 만든 셋업 팩은 남습니다). 지우려면 영문 이름 <b>{p.name}</b> 을(를) 그대로 적으세요.</Text>
        <HStack gap={2} vAlign="end"><div style={{flex:'0 1 280px'}}><TextInput label="영문 이름 확인" value={typedName} onChange={setTypedName} placeholder={p.name}/></div>
          <Button label="지우기" variant="destructive" isDisabled={busy||typedName.trim()!==p.name} onClick={()=>void remove(p)}/><Button label="그만두기" variant="secondary" onClick={()=>setRemoving(null)}/></HStack></VStack>}
    </Card>)}
    <Card padding={5}><VStack gap={4}><HStack hAlign="between"><Heading level={2}>이미 있는 폴더를 프로젝트로 등록</Heading><Button label={busy?'폴더 선택 중':'폴더 선택'} isDisabled={busy||!token} onClick={add}/></HStack><Collapsible trigger="실행 설정" defaultIsOpen={false}><VStack gap={3}><TextInput label="모델 서버" value={modelUrl} onChange={setModelUrl}/><TextInput label="테스트 DB URL" value={db} onChange={setDb} placeholder="jdbc:postgresql://호스트:5432/프로젝트_test"/><Text color="secondary">백엔드 검사는 프로젝트 전용 테스트 DB를 지정해야 사용할 수 있습니다.</Text></VStack></Collapsible>{error&&<Text role="alert">{error}</Text>}</VStack></Card>
  </VStack>;
}
