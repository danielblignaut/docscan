import assert from 'node:assert/strict';
import {test} from 'node:test';
import {loadPureModule} from './load-pure-module.mjs';
const D=await loadPureModule(new URL('../src/item-data.ts',import.meta.url));
const {luhnValid}=await loadPureModule(new URL('../src/item-grouping.ts',import.meta.url));
const imei=n=>{const stem=`001${String(n).padStart(11,'0')}`;for(let d=0;d<10;d++)if(luhnValid(stem+d))return stem+d;};
const line=(text,x,y)=>({format:'code128',text,count:1,points:[[x,y],[x+200,y]]});
const leaf=()=>({kind:'barcodes',labels:false,itemMode:true,barcodes:[],observations:[line(imei(11),40,100),line(imei(12),40,150),line(imei(21),700,100),line(imei(22),700,150)],imageSize:[1280,960],fields:[],meta:{source:'photo',input:{sha256:'fixture-hash',pageIndex:0}}});
test('reviewing one boundary preserves other units as proximity candidates',()=>{
 const value=leaf();assert.equal(D.savedItemSession(value).rows.length,2);
 value.itemRegions=[{id:'left',bbox:[20,70,260,120],origin:'manual'}];
 const result=D.savedItemSession(value);
 assert.equal(result.rows.length,2);assert.equal(result.views[0].grouping.items.filter(i=>i.strength==='explicit').length,1);
 assert.ok(result.rows.every(r=>r.identity&&r.imeiUnindexed.length));
});
test('repeated files and OCR enrichment never increase independent-view counts',()=>{
 const value=leaf(),copy=structuredClone(value);
 const result=D.savedItemSession({kind:'batch',pages:[value,copy]});
 assert.equal(result.views[1].duplicateOf,0);assert.ok(result.rows.every(r=>r.framesSeen===1));
 copy.fields=[{label:'IMEI1',name:'IMEI1',value:imei(11),kind:'imei',source:'both',check_digit_valid:true,barcode_format:'code128',barcode_unread:false,bbox:[40,75,200,50]}];
 const enriched=D.savedItemSession({kind:'batch',pages:[copy,value]});
 assert.ok(enriched.rows.every(r=>r.framesSeen===1));
});
test('linear GS1 elements keep scan-line geometry rather than setting a two-pixel grouping unit',()=>{
 const value=D.groupBarcodeReadings([line(']C1010950600013435221FICTS0001',40,100),line(imei(11),40,140),line(imei(12),40,180)],[],[1280,960]);
 assert.ok(value.members.filter(m=>m.origins.some(o=>o.kind==='gs1')).every(m=>m.geometry==='estimated'));
 assert.ok(value.unit>=20);assert.equal(value.items.length,1);
});
test('saved-view rebuilding retains once-seen units beyond the live-camera expiry',()=>{
 const pages=Array.from({length:15},(_,i)=>({...leaf(),observations:[line(imei(100+i),40,100)],meta:{source:'camera'}}));
 const result=D.savedItemSession({kind:'batch',pages});
 assert.equal(result.rows.length,15);assert.ok(result.rows.every(r=>r.framesSeen===1));assert.equal(result.status,'review');
 assert.deepEqual(result.losses,{droppedTracks:0,refusedGroups:0,rejectedFrames:0,limitedFrames:0});
});
test('grouping limits make the saved session explicitly partial',()=>{
 const value={...leaf(),observations:Array.from({length:201},(_,i)=>line(imei(1000+i),40+(i%10)*300,100+Math.floor(i/10)*200))};
 const result=D.savedItemSession(value);
 assert.equal(result.status,'partial');assert.equal(result.losses.limitedFrames,1);
});
