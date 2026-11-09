import { useEffect, useRef } from 'react';
import * as monaco from 'monaco-editor/editor/editor.api';
import 'monaco-editor/editor/browser/widget/diffEditor/diffEditor.contribution.js';
import '../node_modules/monaco-editor/esm/vs/base/browser/ui/codicons/codicon/codicon.css'; // package exports hide CSS; diff view needs the icon font too
import { languageOf } from './CodeEditor';
export default function DiffEditor({path,before,after,sideBySide}:{path:string;before:string;after:string;sideBySide:boolean}){
  const host=useRef<HTMLDivElement>(null),editor=useRef<monaco.editor.IStandaloneDiffEditor|null>(null);
  useEffect(()=>{if(!host.current)return;const original=monaco.editor.createModel(before,languageOf(path)),modified=monaco.editor.createModel(after,languageOf(path));const instance=monaco.editor.createDiffEditor(host.current,{readOnly:true,originalEditable:false,domReadOnly:true,automaticLayout:true,renderSideBySide:sideBySide,ignoreTrimWhitespace:false,minimap:{enabled:false},fontSize:13,lineHeight:22,scrollBeyondLastLine:false,originalAriaLabel:'변경 전 '+path,modifiedAriaLabel:'변경 후 '+path});const view=instance.createViewModel({original,modified});instance.setModel(view);editor.current=instance;return()=>{instance.setModel(null);view.dispose();instance.dispose();original.dispose();modified.dispose();editor.current=null;};},[path,before,after]);
  useEffect(()=>{editor.current?.updateOptions({renderSideBySide:sideBySide});},[sideBySide]);
  return <div ref={host} style={{height:'32rem',minWidth:0}} role="region" aria-label={`${path} 변경 비교`}/>;
}
