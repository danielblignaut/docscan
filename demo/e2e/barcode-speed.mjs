// Real browser regression for the fast path. Optional private image/expected JSON
// are supplied by env and never copied to the repo or printed as decoded values.
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {readFileSync} from 'node:fs';
import {createHash} from 'node:crypto';
import {chromium} from 'playwright-core';
const image=process.env.DOCSCAN_PERF_IMAGE??new URL('../../testdata/synth/multi_barcode.png',import.meta.url).pathname;
const expected=process.env.DOCSCAN_EXPECTED_CODES?JSON.parse(readFileSync(process.env.DOCSCAN_EXPECTED_CODES)):
 JSON.parse(readFileSync(new URL('../../testdata/synth/multi_barcode.json',import.meta.url))).barcodes.map(b=>({format:b.format.toLowerCase(),text:b.text}));
const digest=codes=>createHash('sha256').update(JSON.stringify(codes.map(b=>`${b.format}|${b.text}`).sort())).digest('hex');
const root=process.env.DOCSCAN_URL??'http://localhost:4193/';
let server;
if(!process.env.DOCSCAN_URL){
 server=spawn('node',['node_modules/vite/bin/vite.js','preview','--port','4193','--strictPort'],{cwd:new URL('../',import.meta.url),stdio:'pipe'});
 await new Promise((resolve,reject)=>{server.stdout.on('data',d=>String(d).includes('4193')&&resolve());server.on('exit',c=>reject(Error(`Preview exited ${c}`)));});
}
const browser=await chromium.launch({executablePath:'/usr/bin/google-chrome',args:[
 '--use-fake-ui-for-media-stream','--use-fake-device-for-media-stream',
 `--use-file-for-fake-video-capture=${new URL('../../testdata/video/multi-barcode.y4m',import.meta.url).pathname}`,
]});
try {
 for(const cold of [false,true]){
  const context=await browser.newContext();const page=await context.newPage();const errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  if(cold)await page.route('**/models/**',route=>route.abort());
  await page.addInitScript(()=>{
   window.__speed={events:[],requests:[],result:null,enriched:null,processingSeen:false};
   const NativeWorker=Worker;
   window.Worker=class extends NativeWorker{postMessage(message,...args){if(typeof message.kind==='string'&&message.kind!=='init')window.__speed.requests.push(message.kind);super.postMessage(message,...args);}};
   for(const type of ['docscan:capture-ready','docscan:processing'])window.addEventListener(type,e=>window.__speed.events.push({type,...e.detail}));
   window.addEventListener('docscan:file',e=>{window.__speed.result=e.detail;});
   window.addEventListener('docscan:enriched',e=>{window.__speed.enriched=e.detail;});
   new MutationObserver(()=>{if(document.querySelector('[data-testid=processing]'))window.__speed.processingSeen=true;}).observe(document,{subtree:true,childList:true});
  });
  await page.goto(root+'?threads=1');
  await page.waitForFunction(()=>window.__docscan?.captureReady,null,{timeout:60000});
  if(!cold)await page.waitForFunction(()=>window.__docscan?.ready,null,{timeout:60000});
  await page.locator('[data-photo=barcodes]').setInputFiles(image);
  await page.locator('[data-testid=results][data-kind=barcodes]').waitFor({timeout:10000});
  const measured=await page.evaluate(()=>window.__speed);
  const outcome=measured.result.outcome;
  assert.equal(digest(outcome.barcodes),digest(expected),'decoded barcode payload set changed');
  assert.equal(outcome.fields.length,0);assert.equal(outcome.meta.ocrFrames,0);
  assert.equal(measured.requests[0],'barcodes','barcodes must precede background OCR');
  assert.equal(measured.requests.filter(k=>k==='barcodes').length,1);
  assert.equal(measured.processingSeen,true);
  const captured=measured.events.filter(e=>e.type==='docscan:capture-ready');
  assert.equal(captured.length,1);assert.equal(captured[0].validation,'pending');assert.ok(captured[0].elapsedMs<100);
  assert.equal(measured.result.operationId,captured[0].operationId);
  assert.deepEqual(measured.events.filter(e=>e.type==='docscan:processing'&&e.operationId===captured[0].operationId).map(e=>e.status),['captured','processing','complete']);
  assert.ok(outcome.meta.captureMs<Number(process.env.DOCSCAN_BARCODE_BUDGET_MS??2000),`barcode-only read took ${outcome.meta.captureMs.toFixed(1)} ms`);
  assert.deepEqual(errors,[]);
  console.log(JSON.stringify({scenario:cold?'OCR models unavailable':'warm',captureReadyMs:captured[0].elapsedMs,resultMs:outcome.meta.captureMs,codes:outcome.barcodes.length,blockingOcrCalls:0}));
  if(!cold && process.env.DOCSCAN_EXPECTED_REPORT){
   await page.waitForFunction(()=>window.__speed.enriched,null,{timeout:120000});
   const final=await page.evaluate(()=>window.__speed.enriched.outcome);
   const terminal=await page.evaluate(()=>window.__speed.enriched);
   assert.equal(terminal.sourceOperationId,measured.result.operationId);
   assert.equal(terminal.status,'complete');assert.equal(terminal.pageIndex,0);assert.equal(terminal.batchComplete,true);
   const baseline=JSON.parse(readFileSync(process.env.DOCSCAN_EXPECTED_REPORT)).outcome;
   const fields=rows=>digest(rows.map(f=>({format:JSON.stringify([f.label,f.kind,f.check_digit_valid,f.barcode_unread]),text:f.value})));
   assert.equal(digest(final.barcodes),digest(baseline.barcodes),'background read changed decoded codes');
   assert.equal(fields(final.fields),fields(baseline.fields),'labelled IMEI/SN/GTIN output changed');
   assert.equal(final.labelReadError,undefined);
   console.log(JSON.stringify({scenario:'background labels',fields:final.fields.length,labelReadMs:final.labelReadMs,baselineMs:baseline.meta.captureMs}));
  } else if(cold) {
   await page.waitForFunction(()=>document.querySelector('[data-testid=barcode-results] [role=alert]'),null,{timeout:15000});
   await page.unroute('**/models/**');
   await page.getByTestId('read-printed-labels').click();
   await page.waitForFunction(()=>window.__docscan?.ready,null,{timeout:60000});
   await page.getByTestId('cancel-label-reading').click();
   await page.getByTestId('barcode-results').waitFor();
   const cancelled=await page.evaluate(()=>window.__speed.enriched);
   assert.equal(cancelled.status,'cancelled');assert.equal(cancelled.sourceOperationId,measured.result.operationId);
   assert.equal(cancelled.batchComplete,true);
   console.log('PASS model download failure retries without reloading the page or losing barcodes');
  } else {
   const cancel=page.getByTestId('cancel-label-reading');
   if(await cancel.count())await cancel.click();
   await page.getByTestId('barcode-results').waitFor();
  }
  await context.close();
 }
 const context=await browser.newContext({permissions:['camera']});const page=await context.newPage();
 await page.addInitScript(()=>{
  window.__handoff={fastInits:0,streams:[]};
  const OriginalWorker=Worker;
  window.Worker=class extends OriginalWorker{postMessage(message,...args){if(message.kind==='init'&&message.loadModels===false)window.__handoff.fastInits++;super.postMessage(message,...args);}};
  const get=navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
  navigator.mediaDevices.getUserMedia=async options=>{const stream=await get(options);window.__handoff.streams.push(stream);return stream;};
 });
 await page.goto(root+'?threads=1&mode=multi');
 await page.waitForFunction(()=>window.__docscan?.frames.length>0,null,{timeout:60000});
 assert.equal(await page.evaluate(()=>window.__handoff.fastInits),1);
 await page.getByTestId('capture-import').setInputFiles(image);
 await page.locator('[data-testid=results][data-kind=barcodes]').waitFor({timeout:10000});
 assert.equal(await page.evaluate(()=>window.__handoff.fastInits),1,'camera-to-file import must reuse the warm decoder');
 assert.equal(await page.evaluate(()=>window.__handoff.streams.every(s=>s.getTracks().every(t=>t.readyState==='ended'))),true);
 if(await page.getByTestId('cancel-label-reading').count())await page.getByTestId('cancel-label-reading').click();
 await page.getByTestId('barcode-results').waitFor();
 assert.equal(await page.locator('[data-testid=barcode-results] img').evaluate(img=>img.complete&&img.naturalWidth>0),true,'cancelling labels must retain the preview');
 console.log('PASS camera-to-file handoff reuses decoder, releases camera, and cancellation retains barcode results');
 await page.getByTestId('results-home').click();
 await page.getByTestId('home').waitFor();
 await page.evaluate(()=>{
  window.__batch={source:null,events:[]};
  window.addEventListener('docscan:file',e=>window.__batch.source=e.detail.operationId);
  window.addEventListener('docscan:enriched',e=>window.__batch.events.push({source:e.detail.sourceOperationId,page:e.detail.pageIndex,status:e.detail.status,done:e.detail.batchComplete}));
 });
 await page.locator('[data-photo=barcodes]').setInputFiles([image,image]);
 await page.getByTestId('cancel-label-reading').waitFor();
 await page.getByTestId('cancel-label-reading').click();
 await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
 const batch=await page.evaluate(()=>window.__batch);
 assert.deepEqual(batch.events.map(e=>[e.source,e.page,e.status,e.done]),[
  [batch.source,0,'cancelled',true],[batch.source,1,'cancelled',true],
 ]);
 assert.equal(await page.getByTestId('barcode-results').count(),2);
 assert.equal(await page.getByTestId('cancel-label-reading').count(),0);
 console.log('PASS batch cancellation emits correlated terminal events for every queued page and retains both barcode results');
 await page.addInitScript(()=>{
  window.__cameraCorrelation={source:null,enriched:null};
  window.addEventListener('docscan:complete',e=>window.__cameraCorrelation.source=e.detail.operationId);
  window.addEventListener('docscan:enriched',e=>window.__cameraCorrelation.enriched=e.detail);
 });
 await page.goto(root+'?threads=1&mode=multi');
 await page.getByTestId('cancel-label-reading').waitFor({timeout:30000});
 await page.getByTestId('cancel-label-reading').click();
 const camera=await page.evaluate(()=>window.__cameraCorrelation);
 assert.ok(camera.source);assert.equal(camera.enriched.sourceOperationId,camera.source);
 assert.equal(camera.enriched.status,'cancelled');
 console.log('PASS camera barcode completion and cancelled label enrichment share their source operation');
 await context.close();
 const failedContext=await browser.newContext({permissions:['camera']});const failed=await failedContext.newPage();
 await failed.addInitScript(()=>{
  window.__fastStarts=0;const Original=Worker;
  window.Worker=class extends Original{postMessage(message,...args){if(message.kind==='init'&&message.loadModels===false)window.__fastStarts++;super.postMessage(message,...args);}};
 });
 await failed.route('**/*.wasm',route=>route.abort());
 await failed.goto(root+'?threads=1&mode=multi');
 await failed.waitForFunction(()=>document.querySelector('[data-testid=hint]')?.textContent?.includes('Error'),null,{timeout:30000});
 const starts=await failed.evaluate(()=>window.__fastStarts);
 await failed.evaluate(()=>new Promise(resolve=>{let frames=0;function tick(){if(++frames===30)resolve();else requestAnimationFrame(tick);}requestAnimationFrame(tick);}));
 assert.equal(await failed.evaluate(()=>window.__fastStarts),starts,'failed camera init must not spawn workers every frame');
 assert.ok(starts<=2);await failedContext.close();
 console.log('PASS persistent camera worker startup failure does not respawn per frame');
}finally{await browser.close();server?.kill();}
