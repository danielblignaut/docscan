import { describeBarcodes } from './barcode-data';
import { groupItems, barcodeBox, createItemTracker, updateItemTracker, trackedRows, luhnValid, type FieldInput, type FrameGrouping, type ItemRegion, type Divider } from './item-grouping';
import type { Outcome, SeenCode } from './outcome';
import type { LabelledField } from './types';

type BarcodeOutcome=Extract<Outcome,{kind:'barcodes'}>;
const aiRole={ '01':'gtin','21':'serial','8040':'imei1','8041':'imei2' } as const;
const aiLabel={ '01':'GTIN','21':'SN','8040':'IMEI1','8041':'IMEI2' } as const;

export function groupBarcodeReadings(codes: readonly SeenCode[], labels: readonly LabelledField[], size: [number,number], regions?: ItemRegion[], dividers?: Divider[], dropped?: SeenCode[]): FrameGrouping {
  const barcodes=describeBarcodes(codes).map(c=>({...c,points:c.points??[]}));
  const fields:FieldInput[]=labels.map((f,index)=>({...f,origins:[{kind:'label_field',index}]}));
  for(const [barcode,code] of barcodes.entries()){
    if(code.gs1?.status!=='parsed'||!code.points.length)continue;
    const geometry = barcodeBox(code.points);
    for(const [element,field] of code.gs1.fields.entries()){
      if(!Object.hasOwn(aiRole,field.ai)||field.errors.length)continue;
      const ai=field.ai as keyof typeof aiRole,imei=ai==='8040'||ai==='8041';
      fields.push({label:aiLabel[ai],name:aiLabel[ai],value:field.value,kind:imei?'imei':ai==='01'?'gtin':'text',role:aiRole[ai],source:'barcode',
        barcode_unread:false,barcode_format:code.format,check_digit_valid:imei?luhnValid(field.value):ai==='01'?field.checks.checksum:null,
        ...geometry,origins:[{kind:'gs1',barcode,ai,element}]});
    }
  }
  return groupItems({barcodes,fields,dropped: dropped?.map(c=>({...c,points:c.points??[]})),width:size[0],height:size[1],regions,dividers,options:{outsideRegions:"proximity"}});
}

export function outcomeGrouping(outcome: BarcodeOutcome): FrameGrouping | null {
  const size=outcome.imageSize;
  if(!size||!size.every(n=>Number.isFinite(n)&&n>0)||!outcome.observations)return null;
  return groupBarcodeReadings(outcome.observations,outcome.fields,size,outcome.itemRegions,outcome.itemDividers,outcome.droppedObservations);
}

/** Rebuild from each saved view once; adding OCR to that view is not a second independent observation. */
export function savedItemSession(root: Outcome) {
  const pages:BarcodeOutcome[]=[];
  const visit=(o:Outcome)=>{if(o.kind==='barcodes')pages.push(o);else if(o.kind==='batch')o.pages.forEach(visit);};visit(root);
  let state=createItemTracker({maxGapMs:0,poseHistory:0,tentativeTtlFrames:10_000,maxTracks:1024});
  const views:{page:number;grouping:FrameGrouping;duplicateOf:number|null}[]=[];
  const fingerprints=new Map<string,number>();
  const losses={droppedTracks:0,refusedGroups:0,rejectedFrames:0,limitedFrames:0};
  for(const [page,outcome] of pages.entries()){
    const grouping=outcomeGrouping(outcome);if(!grouping)continue;
    const input=outcome.meta.input;
    const fingerprint=input?.sha256?`${input.sha256}|${input.pageIndex??0}`:null;
    const duplicateOf=fingerprint?fingerprints.get(fingerprint)??null:null;
    views.push({page,grouping,duplicateOf});
    if(duplicateOf!==null)continue;
    if(fingerprint)fingerprints.set(fingerprint,page);
    const next=updateItemTracker(state,{seq:page+1,at:page*1000,grouping});
    state=next.state;
    losses.droppedTracks+=next.update.dropped.length;
    losses.refusedGroups+=next.update.refused.length;
    losses.rejectedFrames+=Number(!next.update.accepted);
    losses.limitedFrames+=Number(grouping.limits.incomplete||next.update.capacityReached);
  }
  return {rows:trackedRows(state),unanchored:state.unanchored,views,losses,
    status:Object.values(losses).some(n=>n>0)||pages.some(p=>p.blob&&p.labelReadStatus!=='complete')?'partial' as const:'review' as const,
    interpretation:'identifier_observations_not_stock_quantity' as const};
}
