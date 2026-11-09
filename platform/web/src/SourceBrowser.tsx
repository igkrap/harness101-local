import { apiFetch } from "./api";
import { lazy, Suspense, useEffect, useRef, useState } from "react";
import { HStack, VStack } from "@astryxdesign/core/Layout";
import { Text, Heading } from "@astryxdesign/core/Text";
import { TextInput } from "@astryxdesign/core/TextInput";
import { Button } from "@astryxdesign/core/Button";
import type { EditorHandle } from "./CodeEditor";
import "./source.css";
const Editor=lazy(()=>import("./CodeEditor"));
type Tree = {name:string;path:string;children:Tree[];file:boolean};
function treeOf(files:string[]) {
  const root:Tree={name:"",path:"",children:[],file:false};
  for(const file of files){let parent=root;file.split("/").forEach((name,i,parts)=>{const path=parts.slice(0,i+1).join("/");let child=parent.children.find(c=>c.path===path);if(!child){child={name,path,children:[],file:i===parts.length-1};parent.children.push(child);}parent=child;});}
  const sort=(node:Tree)=>{node.children.sort((a,b)=>Number(a.file)-Number(b.file)||a.name.localeCompare(b.name));node.children.forEach(sort);};sort(root);return root.children;
}
async function read<T>(url:string,signal?:AbortSignal):Promise<T>{const response=await apiFetch(url,{signal,cache:"no-store"});const data=await response.json();if(!response.ok)throw Error(data.error||`HTTP ${response.status}`);return data;}
export default function SourceBrowser() {
  const [files,setFiles]=useState<string[]>([]),[filter,setFilter]=useState(""),[expanded,setExpanded]=useState(new Set(["frontend","frontend/src","frontend/src/screens","backend","backend/src","harness"]));
  const [tabs,setTabs]=useState<string[]>([]),[active,setActive]=useState(""),[contents,setContents]=useState<Record<string,string>>({}),[error,setError]=useState(""),[loading,setLoading]=useState("");
  const [explorer,setExplorer]=useState(true),[width,setWidth]=useState(250),[wrap,setWrap]=useState(false),[cursor,setCursor]=useState([1,1]);
  const editor=useRef<EditorHandle>(null),search=useRef<HTMLInputElement>(null),request=useRef<AbortController|null>(null);
  const cache=useRef(contents);cache.current=contents;
  const refreshTree=()=>read<{files:string[]}>("/api/source/tree").then(r=>setFiles(r.files)).catch(e=>setError(String(e)));
  useEffect(()=>{const controller=new AbortController();read<{files:string[]}>("/api/source/tree",controller.signal).then(r=>setFiles(r.files)).catch(e=>{if(!controller.signal.aborted)setError(String(e));});return()=>{controller.abort();request.current?.abort();};},[]);
  const load=async(path:string,force=false)=>{
    request.current?.abort();const controller=new AbortController();request.current=controller;setActive(path);setTabs(t=>t.includes(path)?t:[...t,path]);setError("");
    if(!force&&cache.current[path]!==undefined){setLoading("");return;}
    setLoading(path);
    try{const result=await read<{content:string}>("/api/source?path="+encodeURIComponent(path),controller.signal);if(!controller.signal.aborted)setContents(c=>({...c,[path]:result.content}));}
    catch(e){if(!controller.signal.aborted)setError(String(e));}
    finally{if(!controller.signal.aborted)setLoading("");}
  };
  const close=(path:string)=>{const next=tabs.filter(p=>p!==path);setTabs(next);setContents(c=>{const copy={...c};delete copy[path];return copy;});if(active===path){request.current?.abort();setLoading("");const index=tabs.indexOf(path);const target=next[Math.min(index,next.length-1)]||"";if(target)load(target);else setActive("");}};
  const filtered=files.filter(p=>p.toLowerCase().includes(filter.toLowerCase()));
  const render=(nodes:Tree[],depth=0):React.ReactNode=>nodes.map(node=>{const isOpen=!!filter||expanded.has(node.path);return <li key={node.path} role="none"><button role="treeitem" className={`source-file ${active===node.path?"is-selected":""}`} style={{paddingLeft:12+depth*15}} aria-label={node.path} aria-selected={node.file?active===node.path:undefined} aria-expanded={node.file?undefined:isOpen} title={node.path} onClick={()=>node.file?load(node.path):setExpanded(previous=>{const next=new Set(previous);next.has(node.path)?next.delete(node.path):next.add(node.path);return next;})}><span aria-hidden="true" className="source-glyph">{node.file?"·":isOpen?"⌄":"›"}</span>{node.name}</button>{!node.file&&isOpen&&<ul role="group">{render(node.children,depth+1)}</ul>}</li>;});
  return <VStack gap={3}>
    <HStack hAlign="between" vAlign="center"><Text color="secondary">읽기 전용</Text></HStack>
    <section className="source-workbench" aria-label="소스 탐색기" onKeyDown={e=>{if((e.metaKey||e.ctrlKey)&&e.key.toLowerCase()==="p"){e.preventDefault();setExplorer(true);setTimeout(()=>search.current?.focus(),0);}}}>
      {explorer&&<aside className="source-explorer" style={{width}} aria-label="파일 탐색기"><header><Text weight="bold">파일</Text><Button label="목록 새로고침" variant="ghost" size="sm" onClick={refreshTree}/></header><VStack padding={2}><TextInput ref={search} label="파일 찾기" isLabelHidden placeholder="파일 찾기" value={filter} onChange={setFilter}/></VStack><ul role="tree" aria-label="프로젝트 파일">{render(treeOf(filtered))}</ul>{!filtered.length&&<Text color="secondary">파일 없음</Text>}</aside>}
      {explorer&&<div className="source-divider" role="separator" aria-label="탐색기 너비" aria-orientation="vertical" aria-valuemin={160} aria-valuemax={420} aria-valuenow={width} tabIndex={0} onKeyDown={e=>{if(e.key==="ArrowLeft"||e.key==="ArrowRight"){e.preventDefault();setWidth(w=>Math.max(160,Math.min(420,w+(e.key==="ArrowLeft"?-20:20))));}}} onPointerDown={e=>{e.currentTarget.setPointerCapture(e.pointerId);e.currentTarget.dataset.start=String(e.clientX-width);}} onPointerMove={e=>{if(e.currentTarget.hasPointerCapture(e.pointerId))setWidth(Math.max(160,Math.min(420,e.clientX-Number(e.currentTarget.dataset.start))));}}/>}
      <div className="source-main"><header className="source-tabs" role="tablist" aria-label="열린 파일"><Button label={explorer?"탐색기 접기":"탐색기 열기"} variant="ghost" size="sm" onClick={()=>setExplorer(x=>!x)}/>{tabs.map(path=><div key={path} className={`source-tab ${active===path?"is-active":""}`}><button role="tab" aria-selected={active===path} aria-label={path} onClick={()=>load(path)}>{path.split("/").at(-1)}</button><button className="source-close" aria-label={`${path} 닫기`} onClick={()=>close(path)}>×</button></div>)}</header>
        {active&&<div className="source-toolbar"><Text color="secondary" style={{overflowWrap:"anywhere",minWidth:0}}>{active.split("/").join(" / ")}</Text><HStack gap={1}><Button label="찾기" variant="ghost" size="sm" onClick={()=>editor.current?.find()}/><Button label="줄바꿈" variant={wrap?"secondary":"ghost"} size="sm" onClick={()=>setWrap(w=>!w)}/><Button label="파일 새로고침" variant="ghost" size="sm" onClick={()=>load(active,true)}/></HStack></div>}
        {error&&<div className="source-notice" role="alert">{error}</div>}
        {loading&&contents[active]===undefined?<div className="source-empty">불러오는 중</div>:active&&contents[active]!==undefined?<Suspense fallback={<div className="source-empty">편집기 불러오는 중</div>}><Editor ref={editor} path={active} content={contents[active]} open={tabs} wrap={wrap} onCursor={(line,column)=>setCursor([line,column])}/></Suspense>:<div className="source-empty">파일을 선택하세요.</div>}
        <footer className="source-status"><Text color="secondary">{active?`${active.split(".").at(-1)?.toUpperCase()} · UTF-8`:""}</Text><Text color="secondary">{active?`${cursor[0]}행 ${cursor[1]}열 · `:""}읽기 전용</Text></footer>
      </div>
    </section>
  </VStack>;
}
