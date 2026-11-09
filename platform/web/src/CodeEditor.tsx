import { forwardRef, useEffect, useImperativeHandle, useRef } from "react";
import * as monaco from "monaco-editor/editor/editor.api";
import "monaco-editor/editor/contrib/find/browser/findController.js";
import "monaco-editor/editor/contrib/folding/browser/folding.js";
import "monaco-editor/editor/contrib/bracketMatching/browser/bracketMatching.js";
import "monaco-editor/languages/definitions/typescript/register.js";
import "monaco-editor/languages/definitions/javascript/register.js";
import "monaco-editor/languages/definitions/java/register.js";
import "monaco-editor/languages/definitions/python/register.js";
import "monaco-editor/languages/definitions/sql/register.js";
import "monaco-editor/languages/definitions/shell/register.js";
import "monaco-editor/languages/definitions/markdown/register.js";
import "monaco-editor/languages/definitions/xml/register.js";
import "monaco-editor/languages/definitions/html/register.js";
import "monaco-editor/languages/definitions/css/register.js";
import "monaco-editor/languages/definitions/ini/register.js";
import "monaco-editor/languages/features/json/register.js";
import EditorWorker from "monaco-editor/editor/editor.worker.js?worker";
import JsonWorker from "monaco-editor/languages/features/json/json.worker.js?worker";

self.MonacoEnvironment = { getWorker: (_id, label) => label === "json" ? new JsonWorker() : new EditorWorker() };
export type EditorHandle = { find: () => void };
export const languageOf = (path: string) => ({tsx:"typescript",ts:"typescript",js:"javascript",jsx:"javascript",py:"python",java:"java",sql:"sql",json:"json",css:"css",md:"markdown",xml:"xml",html:"html",properties:"ini",sh:"shell"})[path.split(".").at(-1) as "tsx"] || "plaintext";

export default forwardRef<EditorHandle, {path:string;content:string;open:string[];wrap:boolean;onCursor:(line:number,column:number)=>void}>(function CodeEditor({path,content,open,wrap,onCursor}, ref) {
  const host = useRef<HTMLDivElement>(null);
  const editor = useRef<monaco.editor.IStandaloneCodeEditor | null>(null);
  const models = useRef(new Map<string,monaco.editor.ITextModel>());
  const views = useRef(new Map<string,monaco.editor.ICodeEditorViewState>());
  const current = useRef("");
  const callback = useRef(onCursor); callback.current=onCursor;
  useImperativeHandle(ref,()=>({find:()=>{editor.current?.focus();editor.current?.getAction("actions.find")?.run();}}),[]);
  useEffect(()=>{
    if(!host.current)return;
    const instance=monaco.editor.create(host.current,{model:null,theme:"vs",readOnly:true,domReadOnly:true,automaticLayout:true,fontSize:13,lineHeight:22,fontFamily:"Menlo, Monaco, Consolas, monospace",minimap:{enabled:false},scrollBeyondLastLine:false,renderValidationDecorations:"off",quickSuggestions:false,wordBasedSuggestions:"off",padding:{top:12},lineNumbers:"on",folding:true,contextmenu:true});
    editor.current=instance;
    const cursor=instance.onDidChangeCursorPosition(e=>callback.current(e.position.lineNumber,e.position.column));
    return()=>{cursor.dispose();instance.dispose();models.current.forEach(m=>m.dispose());models.current.clear();editor.current=null;};
  },[]);
  useEffect(()=>{
    const instance=editor.current;if(!instance)return;
    const view=instance.saveViewState();if(view&&current.current)views.current.set(current.current,view);
    let model=models.current.get(path);
    if(!model){model=monaco.editor.createModel(content,languageOf(path),monaco.Uri.parse("inmemory://project/"+path));models.current.set(path,model);}
    else if(model.getValue()!==content)model.setValue(content);
    instance.setModel(model);current.current=path;
    instance.updateOptions({ariaLabel:path});
    const previous=views.current.get(path);if(previous)instance.restoreViewState(previous);
    const position=instance.getPosition();if(position)callback.current(position.lineNumber,position.column);
  },[path,content]);
  useEffect(()=>{editor.current?.updateOptions({wordWrap:wrap?"on":"off"});},[wrap]);
  useEffect(()=>{for(const [key,model] of models.current){if(!open.includes(key)){model.dispose();models.current.delete(key);views.current.delete(key);}}},[open]);
  return <div ref={host} className="source-editor" />;
});
