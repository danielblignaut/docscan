import { useEffect, useRef, useState } from 'react';
import { grab, openCamera, snapshot, toJpeg } from './camera';
import { describeBarcodes } from './barcode-data';
import { groupBarcodeReadings } from './item-data';
import { createItemTracker, updateItemTracker, trackedRows, type TrackedRow } from './item-grouping';
import { countFrame, quietClock } from './barcode-completion';
import { createProcessingSession } from './processing';
import type { ScannerClient } from './scanner-client';
import type { Barcode } from './types';
import type { Outcome, SeenCode } from './outcome';

const MAX_VIEWS=6, MAX_WIDTH=1280, MAX_BYTES=20*1024*1024;
interface View { blob:Blob; codes:SeenCode[]; size:[number,number]; frame:number; at:number }

/** Continuous acquisition: physical views are saved; each gets one later OCR read. */
export function ItemsCapture({client,onDone}:{client:ScannerClient;onDone:(outcome:Outcome)=>void}) {
  const video=useRef<HTMLVideoElement>(null);
  const finishNow=useRef<()=>void>(()=>{});
  const saveRequested=useRef(false),finishRequested=useRef(false);
  const [saved,setSaved]=useState(0),[rows,setRows]=useState<TrackedRow[]>([]),[productCount,setProductCount]=useState(0);
  const [error,setError]=useState<string|null>(null),[started,setStarted]=useState(false);
  useEffect(()=>{
    let stopped=false,finishing=false,stream:MediaStream|null=null;
    const views:View[]=[],covered=new Set<string>(),seen=new Map<string,SeenCode>(),clock=quietClock();
    let tracker=createItemTracker(),frame=0,lastSaved=-Infinity,totalBytes=0,presented=0,lastPresented=-1;
    const canvas=document.createElement('canvas');
    const session=createProcessingSession('items','camera'),t0=performance.now();
    const release=()=>stream?.getTracks().forEach(t=>t.stop());
    async function save(codes:SeenCode[],size:[number,number],at:number){
      if(views.length>=MAX_VIEWS)return;
      // Sample before awaiting JPEG encoding: the camera cannot replace these pixels.
      const pixels=grab(canvas,{x:0,y:0,w:canvas.width,h:canvas.height},MAX_WIDTH);
      const blob=await toJpeg(pixels);
      if(stopped)return;
      if(totalBytes+blob.size>MAX_BYTES)throw Error('Saved views reached the 20 MiB limit. Finish this session.');
      totalBytes+=blob.size;views.push({blob,codes,size,frame,at});
      for(const c of codes)covered.add(`${c.format}|${c.text}`);
      lastSaved=at;setSaved(views.length);
      window.dispatchEvent(new CustomEvent('docscan:item-view',{detail:{operationId:session.id,viewIndex:views.length-1,frameId:frame,status:'captured',validation:'pending'}}));
    }
    function finish(){
      if(stopped||finishing||!views.length)return;
      finishing=true;stopped=true;release();session.captured({inputCount:views.length});session.stage('finalizing_items');
      const urls:string[]=[];
      try{
        const pages:Outcome[]=views.map((v,index)=>{
          const imageUrl=URL.createObjectURL(v.blob);urls.push(imageUrl);
          return {kind:'barcodes',labels:false,itemMode:true,operationId:session.id,barcodes:v.codes,observations:v.codes,imageSize:v.size,
            fields:[],blob:v.blob,imageUrl,finishedBy:`saved view ${index+1}`,meta:{source:'camera',captureMs:v.at-t0,frames:1,ocrFrames:0}};
        });
        const outcome:Outcome={kind:'batch',scanner:'items',operationId:session.id,pages,meta:{source:'camera',captureMs:performance.now()-t0,frames:frame,ocrFrames:0}};
        session.complete();window.dispatchEvent(new CustomEvent('docscan:complete',{detail:{operationId:session.id,outcome}}));onDone(outcome);
      }catch(e){urls.forEach(url=>URL.revokeObjectURL(url));session.fail(e);setError(String(e));}
    }
    finishNow.current=finish;
    async function loop(){
      if(stopped)return;
      if(finishRequested.current&&views.length){finish();return;}
      const v=video.current;
      if(!v||v.readyState<2||client.busy){requestAnimationFrame(loop);return;}
      const hasFrames=typeof v.requestVideoFrameCallback==='function';
      const token=hasFrames?presented:Math.floor(v.currentTime*30);
      if(token===lastPresented){requestAnimationFrame(loop);return;}lastPresented=token;
      snapshot(v,canvas);const image=grab(canvas,{x:0,y:0,w:canvas.width,h:canvas.height},MAX_WIDTH);
      const size:[number,number]=[image.width,image.height];frame++;
      try{
        const {result}=await client.run<Barcode[]>({kind:'barcodes',image,formats:[]});if(stopped)return;
        const at=performance.now(),codes=describeBarcodes(result);
        countFrame(seen,clock,codes,at);
        const grouping=groupBarcodeReadings(codes,[],size);
        const tracked=updateItemTracker(tracker,{seq:frame,at,grouping});tracker=tracked.state;
        setRows(trackedRows(tracker));setProductCount(tracker.unanchored.length);
        window.dispatchEvent(new CustomEvent('docscan:items',{detail:{operationId:session.id,frameId:frame,rows:trackedRows(tracker),ambiguities:tracked.update.ambiguous,interpretation:'identifier_observations_not_stock_quantity'}}));
        const newCodes=codes.some(c=>(seen.get(`${c.format}|${c.text}`)?.count??0)>=2&&!covered.has(`${c.format}|${c.text}`));
        if(saveRequested.current||(newCodes&&at-lastSaved>=1000)){
          saveRequested.current=false;await save(codes,size,at);
        }
        if(stopped)return;
        if(views.length>=MAX_VIEWS||finishRequested.current){finish();if(stopped)return;}
      }catch(e){if(stopped)return;setError(e instanceof Error?e.message:String(e));release();return;}
      requestAnimationFrame(loop);
    }
    openCamera().then(async s=>{
      stream=s;if(stopped){release();return;}
      const v=video.current;if(!v){release();return;}v.srcObject=s;await v.play();if(stopped)return;
      const tick=()=>{if(stopped)return;presented++;v.requestVideoFrameCallback(tick);};
      if('requestVideoFrameCallback' in v)v.requestVideoFrameCallback(tick);
      setStarted(true);requestAnimationFrame(loop);
    }).catch(e=>{if(!stopped)setError(String(e));});
    return()=>{stopped=true;finishNow.current=()=>{};session.cancel();release();};
  },[client,onDone]);
  return <div className="capture"><div className="viewport">
    <video ref={video} playsInline muted />
    <div className="step-label">Item scan session · {saved}/{MAX_VIEWS} views saved</div>
    <div className="capture-foot"><div className="hint" data-testid="hint">{error??'Pan slowly across the boxes. New codes save a view; printed labels are read after Finish.'}</div>
      <p>{rows.length} identifier tracks · {productCount} product-only sightings. These are not quantities.</p>
      <button type="button" data-testid="save-item-view" disabled={!started||!!error||saved>=MAX_VIEWS} onClick={()=>{saveRequested.current=true;}}>Save this view</button>
      <button type="button" data-testid="finish-items" disabled={!saved} onClick={()=>{if(error)finishNow.current();else finishRequested.current=true;}}>Finish and read labels</button>
      {rows.length>0&&<ul className="codes">{rows.map(row=><li key={row.id}>{row.id} · {row.serial.value??row.imei1.value??row.imeiUnindexed[0]?.value??'identifier'} · {row.status==='confirmed'?'seen in multiple frames':'tentative'}</li>)}</ul>}
    </div>
  </div></div>;
}
