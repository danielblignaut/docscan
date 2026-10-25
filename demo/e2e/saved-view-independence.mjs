import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {chromium} from 'playwright-core';
const browser=await chromium.launch({executablePath:'/usr/bin/google-chrome',args:['--use-fake-ui-for-media-stream','--use-fake-device-for-media-stream','--use-file-for-fake-video-capture=/tmp/docscan-feature-fixtures/items-static.y4m']});
const page=await browser.newPage({viewport:{width:430,height:900}});const errors=[];page.on('pageerror',e=>errors.push(e.message));
await page.addInitScript(()=>{
 window.__saved={views:[],hashes:{},outcome:null,tracks:[]};
 const get=navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
 navigator.mediaDevices.getUserMedia=async o=>{const s=await get(o);window.__saved.tracks.push(...s.getTracks());return s;};
 const NativeWorker=Worker;
 window.Worker=class extends NativeWorker{postMessage(m,...args){
  if(m.kind==='barcodes'){const id=m.id,width=m.image.width,height=m.image.height;crypto.subtle.digest('SHA-256',m.image.data.slice()).then(h=>window.__saved.hashes[id]={kind:'sha256_rgba8',width,height,sha256:Array.from(new Uint8Array(h),v=>v.toString(16).padStart(2,'0')).join('')});}
  super.postMessage(m,...args);
 }};
 addEventListener('docscan:item-view',e=>window.__saved.views.push(e.detail));
 addEventListener('docscan:complete',e=>{if(e.detail.outcome?.scanner==='items')window.__saved.outcome=e.detail.outcome;});
});
try{
 await page.goto((process.env.DOCSCAN_URL??'http://localhost:4203/')+'?mode=items&threads=1&labelReader=fast');
 await page.waitForFunction(()=>window.__saved.views.length===1,null,{timeout:60000});
 for(let n=2;n<=3;n++){await page.getByTestId('save-item-view').click();await page.waitForFunction(n=>window.__saved.views.length===n,n,{timeout:15000});}
 await page.getByTestId('finish-items').click();await page.getByTestId('item-session-results').waitFor();
 const stop=page.getByTestId('cancel-label-reading');if(await stop.count())await stop.click();
 const evidence=await page.evaluate(()=>window.__saved);
 assert.equal(evidence.outcome.pages.length,3);
 for(const [index,v] of evidence.views.entries())assert.deepEqual(evidence.outcome.pages[index].captureFingerprint,evidence.hashes[v.frameId]);
 assert.equal(new Set(evidence.outcome.pages.map(p=>p.captureFingerprint.sha256)).size,1,'fixture must repeat identical analysed pixels');
 assert.equal(await page.evaluate(()=>window.__saved.tracks.every(t=>t.readyState==='ended')),true);
 const download=page.waitForEvent('download');await page.getByTestId('export-document-report').click();
 const result=JSON.parse(readFileSync(await (await download).path())).outcome;
 assert.deepEqual(result.items.views.map(v=>v.duplicateOf),[null,0,0]);assert.ok(result.items.rows.length>0);
 assert.ok(result.items.rows.every(r=>r.framesSeen===1&&r.status==='tentative'));
 assert.ok(result.pages.every(p=>p.captureFingerprint.kind==='sha256_rgba8'));assert.deepEqual(errors,[]);
 console.log('PASS camera fingerprints match actual decoder inputs; three identical saved views count once and never confirm a track');
}finally{await browser.close();}
