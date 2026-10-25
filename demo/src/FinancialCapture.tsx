import { useCallback } from 'react';
import { PageCapture, type CapturedPage, type PageWork } from './PageCapture';
import { readFinancialPages } from './financial-data';
import { textRequest, type TextEngine } from './text-engine';
import type { TextResult } from './TextCapture';
import type { CaptureMeta, Outcome } from './outcome';
import type { ScannerClient } from './scanner-client';

export function FinancialCapture({client,captureClient,onDone,engine="ocrs"}:{engine?:Exclude<TextEngine,"ppocr_v6_tiny_exposure">;client:ScannerClient;captureClient?:ScannerClient;onDone:(outcome:Outcome)=>void}){
  const read=useCallback(async(page:CapturedPage,meta:CaptureMeta,work:PageWork)=>{
    const {result,memoryBytes}=await client.run<TextResult>(textRequest(engine,page.flat));
    if(!work.active()){URL.revokeObjectURL(page.imageUrl);return;}
    const pages=[{pageIndex:0,fileIndex:0,reading:result,imageUrl:page.imageUrl}];
    const outcome:Outcome={kind:'financial',operationId:work.operationId,pages,options:{},incompleteInputs:0,report:readFinancialPages(pages),meta:{...meta,ocrFrames:1,memoryBytes}};
    work.done();window.dispatchEvent(new CustomEvent('docscan:financial',{detail:{operationId:work.operationId,report:outcome.report,meta:outcome.meta}}));
    window.dispatchEvent(new CustomEvent('docscan:complete',{detail:outcome}));onDone(outcome);
  },[client,onDone,engine]);
  return <PageCapture client={client} captureClient={captureClient} title="Financial tables" scanner="tables" onRead={read}/>;
}
