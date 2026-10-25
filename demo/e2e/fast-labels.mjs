// Optional private inputs are supplied by env; no decoded identifiers are logged or saved.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createHash} from 'node:crypto';
import {chromium} from 'playwright-core';
const image=process.env.DOCSCAN_PERF_IMAGE, report=process.env.DOCSCAN_EXPECTED_REPORT;
if(!image||!report)throw Error('Set DOCSCAN_PERF_IMAGE and DOCSCAN_EXPECTED_REPORT');
const baseline=JSON.parse(readFileSync(report)).outcome;
const digest=rows=>createHash('sha256').update(JSON.stringify(rows.sort())).digest('hex');
const fields=rows=>digest(rows.map(f=>JSON.stringify([f.label,f.value,f.kind,f.check_digit_valid])));
const codes=rows=>digest(rows.map(b=>`${b.format}|${b.text}`));
const browser=await chromium.launch({executablePath:'/usr/bin/google-chrome'});
try{
 for(const threads of [1,2]){
  const page=await browser.newPage({viewport:{width:430,height:900}});
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.addInitScript(()=>{
   window.__labels={initial:null,final:null,requests:[]};
   addEventListener('docscan:file',e=>window.__labels.initial=e.detail);
   addEventListener('docscan:enriched',e=>window.__labels.final=e.detail);
   const NativeWorker=Worker;
   window.Worker=class extends NativeWorker{postMessage(msg,...args){if(msg.kind==='labelled')window.__labels.requests.push({kind:msg.kind,profile:msg.profile});super.postMessage(msg,...args);}};
  });
  await page.goto((process.env.DOCSCAN_URL??'http://localhost:4197/')+`?threads=${threads}`);
  await page.waitForFunction(()=>window.__docscan?.captureReady,null,{timeout:90000});
  await page.getByTestId('label-engine-barcodes').selectOption('fast');
  await page.locator('[data-photo=barcodes]').setInputFiles(image);
  await page.getByTestId('barcode-results').waitFor({timeout:10000});
  await page.waitForFunction(()=>window.__labels.final?.status==='complete',null,{timeout:60000});
  const data=await page.evaluate(()=>({ ...window.__labels, ready:window.__docscan.paddleRuntimeReady??window.__docscan.ready, isolated:crossOriginIsolated }));
  assert.equal(data.final.sourceOperationId,data.initial.operationId);assert.equal(data.final.batchComplete,true);
  assert.equal(data.initial.outcome.fields.length,0);assert.equal(data.initial.outcome.meta.ocrFrames,0);
  assert.equal(codes(data.final.outcome.barcodes),codes(baseline.barcodes));
  assert.equal(fields(data.final.outcome.fields),fields(baseline.fields),'fast reader lost/changed labelled values or check digits');
  assert.equal(data.final.outcome.labelReader,'fast');assert.deepEqual(data.requests,[{kind:'labelled',profile:'fast'}]);
  await page.getByText('Experimental fast reading can miss or change fields.',{exact:false}).waitFor();
  const download=page.waitForEvent('download');await page.getByTestId('export-document-report').click();
  const output=JSON.parse(readFileSync(await (await download).path()));
  assert.equal(output.outcome.labelReader,'fast');assert.match(output.outcome.labelReaderInterpretation,/miss or change/);
  assert.equal(fields(output.outcome.fields),fields(baseline.fields));assert.deepEqual(errors,[]);
  const sourceChanges=data.final.outcome.fields.filter(f=>!baseline.fields.some(b=>b.label===f.label&&b.value===f.value&&b.source===f.source)).length;
  console.log(JSON.stringify({requestedThreads:threads,actualThreads:data.ready.threads,isolated:data.isolated,codes:data.final.outcome.barcodes.length,fields:data.final.outcome.fields.length,sourceChanges,barcodeMs:data.initial.outcome.meta.captureMs,labelMs:data.final.outcome.labelReadMs}));
  assert.ok(data.final.outcome.labelReadMs<Number(process.env.DOCSCAN_FAST_LABEL_BUDGET_MS??6000),'fast label read exceeded budget');
  await page.close();
 }
 const page=await browser.newPage();
 await page.addInitScript(()=>{window.__retry={initial:null,final:null};addEventListener('docscan:file',e=>window.__retry.initial=e.detail);addEventListener('docscan:enriched',e=>window.__retry.final=e.detail);});
 await page.route('**/models/ppocr-v6-tiny-*',r=>r.abort());
 await page.goto((process.env.DOCSCAN_URL??'http://localhost:4197/')+'?threads=1&labelReader=fast');
 await page.waitForFunction(()=>window.__docscan?.captureReady,null,{timeout:90000});
 await page.locator('[data-photo=barcodes]').setInputFiles(image);
 await page.waitForFunction(()=>window.__retry.final?.status==='failed',null,{timeout:30000});
 const failed=await page.evaluate(()=>window.__retry);
 assert.equal(codes(failed.final.outcome.barcodes),codes(baseline.barcodes));
 assert.equal(failed.final.outcome.labelReader,'fast');assert.equal(failed.final.sourceOperationId,failed.initial.operationId);
 await page.unroute('**/models/ppocr-v6-tiny-*');
 await page.getByTestId('read-printed-labels').click();
 await page.waitForFunction(()=>window.__retry.final?.status==='complete',null,{timeout:60000});
 const retried=await page.evaluate(()=>window.__retry.final.outcome);
 assert.equal(retried.labelReader,'fast');assert.equal(fields(retried.fields),fields(baseline.fields));
 console.log('PASS Fast-model download failure retains codes and the requested profile; retry succeeds without fallback');
 await page.close();
}finally{await browser.close();}
