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
test('identical decoded camera views do not become independent confirmations',()=>{
 const a={...leaf(),meta:{source:'camera'},captureFingerprint:{kind:'sha256_rgba8',sha256:'a'.repeat(64),width:1280,height:960}};
 const b=structuredClone(a);
 const result=D.savedItemSession({kind:'batch',pages:[a,b]});
 assert.equal(result.views[1].duplicateOf,0);assert.ok(result.rows.every(r=>r.framesSeen===1&&r.status==='tentative'));
 b.captureFingerprint.sha256='b'.repeat(64);
 const independent=D.savedItemSession({kind:'batch',pages:[a,b]});
 assert.equal(independent.views[1].duplicateOf,null);assert.ok(independent.rows.every(r=>r.framesSeen===2));
});
test('a successful label read is used instead of an identical failed copy, without double counting',()=>{
 const first={...leaf(),labelReadStatus:'failed'},second={...leaf(),labelReadStatus:'complete'};
 second.fields=[{label:'IMEI1',name:'IMEI1',value:imei(11),kind:'imei',source:'both',check_digit_valid:true,barcode_format:'code128',barcode_unread:false,bbox:[40,75,200,50]}];
 const result=D.savedItemSession({kind:'batch',pages:[first,second]});
 assert.equal(result.views[0].duplicateOf,1);assert.equal(result.views[1].duplicateOf,null);
 assert.ok(result.rows.some(r=>r.imei1.value===imei(11)));assert.ok(result.rows.every(r=>r.framesSeen===1));
 first.itemRegions=[{id:'reviewed',bbox:[20,70,260,120],origin:'manual'}];
 const reviewed=D.savedItemSession({kind:'batch',pages:[first,second]});
 assert.equal(reviewed.views[0].duplicateOf,null);assert.equal(reviewed.views[1].duplicateOf,0);
 assert.equal(reviewed.views[0].grouping.items.filter(i=>i.strength==='explicit').length,1);
});
test('choosing a later successful duplicate preserves the first-observed track order',()=>{
 const first={...leaf(),observations:[line(imei(11),40,100)],labelReadStatus:'failed'};
 const other={...leaf(),observations:[line(imei(21),40,100)],meta:{source:'photo',input:{sha256:'other-fixture',pageIndex:0}}};
 const last={...first,labelReadStatus:'complete'};
 const result=D.savedItemSession({kind:'batch',pages:[first,other,last]});
 assert.deepEqual(result.rows.map(r=>r.identity.value),[imei(11),imei(21)]);
 assert.deepEqual(result.rows.map(r=>r.framesSeen),[1,1]);
 assert.equal(result.views[0].duplicateOf,2);
});
