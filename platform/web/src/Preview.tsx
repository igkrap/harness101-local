import { useEffect, useState } from 'react';
import { VStack, HStack } from '@astryxdesign/core/Layout';
import { Heading, Text } from '@astryxdesign/core/Text';
import { Button } from '@astryxdesign/core/Button';
import { Collapsible } from '@astryxdesign/core/Collapsible';
import { apiFetch } from './api';
type State={status:string;url:string;error:string;output?:string};
export default function Preview({token}:{token:string}){
  const [state,setState]=useState<State>({status:'starting',url:'',error:''}),[attempt,setAttempt]=useState(0),[frame,setFrame]=useState(0);
  useEffect(()=>{if(!token)return;const controller=new AbortController();let timer:ReturnType<typeof setTimeout>;
    async function poll(start=false){try{const response=await apiFetch('/api/preview',start?{method:'POST',headers:{'Content-Type':'application/json','X-Platform-Token':token},body:'{}',signal:controller.signal}:{signal:controller.signal});const data=await response.json();if(!response.ok)throw Error(data.error);if(!controller.signal.aborted)setState(data);}catch(e){if(!controller.signal.aborted)setState({status:'failed',url:'',error:String(e)});}if(!controller.signal.aborted)timer=setTimeout(()=>poll(),2000);}
    poll(true);return()=>{controller.abort();clearTimeout(timer);};},[token,attempt]);
  return <VStack gap={4}><HStack hAlign="between" vAlign="center" gap={3}><HStack gap={2}><Button label="새로고침" size="sm" variant="secondary" isDisabled={state.status!=='ready'} onClick={()=>setFrame(n=>n+1)}/><Button label="새 창으로 열기" size="sm" isDisabled={!state.url} onClick={()=>window.open(state.url,'_blank','noopener,noreferrer')}/></HStack></HStack>
    {state.status==='ready'&&state.url?<iframe key={frame} title="앱 미리보기" src={state.url} sandbox="allow-scripts allow-same-origin allow-forms" style={{width:'100%',minHeight:'65dvh',border:'1px solid var(--color-border)',borderRadius:'var(--radius-container)',background:'var(--color-background-card)'}}/>:<VStack gap={3}>
      <Text role="status">{state.status==='installing'?'미리보기에 필요한 패키지를 설치하고 있습니다.':state.status==='failed'?'미리보기를 실행하지 못했습니다.':'개발 서버를 준비하고 있습니다.'}</Text>
      {state.error&&<Text role="alert">{state.error}</Text>}
      {state.output&&<Collapsible trigger="실행 로그" defaultIsOpen={false}><pre style={{whiteSpace:'pre-wrap',maxHeight:'24rem',overflow:'auto'}}>{state.output}</pre></Collapsible>}
      {state.status==='failed'&&<Button label="다시 시도" variant="secondary" onClick={()=>{setState({status:'starting',url:'',error:''});setAttempt(n=>n+1);}}/>}
    </VStack>}
  </VStack>;
}
