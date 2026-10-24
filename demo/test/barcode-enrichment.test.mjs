import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import {transformWithEsbuild} from 'vite';
const path=new URL('../src/barcode-enrichment.ts',import.meta.url).pathname;
const {code}=await transformWithEsbuild(readFileSync(path,'utf8'),path);
const {mergeLabelReading,replaceOutcome,barcodeLeaves,cancelLabelReadings,enrichmentDetail,enrichmentComplete}=await import(`data:text/javascript,${encodeURIComponent(code)}`);
const original=()=>({kind:'barcodes',labels:false,barcodes:[{format:'qr',text:'original',count:2}],fields:[],imageUrl:'blob:retained',blob:new Blob(['original']),meta:{source:'photo',captureMs:400,ocrFrames:0},documentEvidence:{original:true}});
test('label refinement retains decoded payloads, preview, provenance and capture latency',()=>{
 const before=original(), labels={...original(),barcodes:[],imageUrl:'blob:temporary',fields:[{label:'SN',value:'fictional',check_digit_valid:null}],meta:{ocrFrames:1,ocrMs:700}};
 const after=mergeLabelReading(before,labels,800);
 assert.equal(after.barcodes,before.barcodes);assert.equal(after.blob,before.blob);assert.equal(after.imageUrl,before.imageUrl);
 assert.equal(after.documentEvidence,before.documentEvidence);assert.equal(after.fields,labels.fields);
 assert.equal(after.meta.captureMs,400);assert.equal(after.meta.ocrFrames,1);assert.equal(after.labelReadMs,800);
});
test('failed label reading cannot erase barcodes; incomplete evidence is surfaced',()=>{
 const before=original(), fail={kind:'file_error',message:'model unavailable'};
 const failed=mergeLabelReading(before,fail,5);
 assert.equal(failed.barcodes,before.barcodes);assert.equal(failed.labelReadError,'model unavailable');
 const incomplete=mergeLabelReading(before,{kind:'batch',pages:[fail,{...before,fields:[{value:'fictional'}]}]},10);
 assert.equal(incomplete.fields.length,1);assert.equal(incomplete.labelReadWarning,'model unavailable');
});
test('refining one batch page retains unrelated pages and their resources',()=>{
 const one=original(),two=original(),warning={kind:'file_error',message:'unsupported metadata'};
 const root={kind:'batch',pages:[one,warning,{kind:'batch',pages:[two]}]};
 const replacement={...two,fields:[{value:'fictional'}]}, next=replaceOutcome(root,two,replacement);
 assert.equal(next.pages[0],one);assert.equal(next.pages[1],warning);assert.equal(next.pages[2].pages[0],replacement);
 assert.deepEqual(barcodeLeaves(next),[one,replacement]);assert.equal(root.pages[2].pages[0],two);
});

test('batch cancellation closes running and queued pages with source correlation',()=>{
 const one={...original(),labelReadStatus:'pending'},two=original();
 const root={kind:'batch',operationId:'source-scan',pages:[one,two],meta:{ocrFrames:0}};
 const result=cancelLabelReadings(root);
 assert.equal(result.cancelled.length,2);assert.equal(enrichmentComplete(result.outcome),true);
 assert.deepEqual(result.cancelled.map(p=>enrichmentDetail(result.outcome,p,'label-operation')).map(e=>[e.sourceOperationId,e.pageIndex,e.status,e.batchComplete]),[
  ['source-scan',0,'cancelled',true],['source-scan',1,'cancelled',true]
 ]);
 assert.equal(result.outcome.pages[0].blob,one.blob);assert.equal(result.outcome.pages[1].imageUrl,two.imageUrl);
 assert.equal(cancelLabelReadings(result.outcome).cancelled.length,0);
});
test('batch completion remains false until all eligible pages terminate',()=>{
 const first={...original(),labelReadStatus:'complete'},second=original();
 const root={kind:'batch',operationId:'source',pages:[first,second],meta:{ocrFrames:1}};
 assert.equal(enrichmentDetail(root,first,'one').batchComplete,false);
 const done=mergeLabelReading(second,{kind:'file_error',message:'failed'},10);
 const next=replaceOutcome(root,second,done);
 assert.equal(enrichmentDetail(next,done,'two').batchComplete,true);
 assert.equal(enrichmentDetail(next,done,'two').status,'failed');
});
