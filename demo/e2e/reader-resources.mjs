// Production-browser resource/parity loop. Generated fictional image only.
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {readFileSync,writeFileSync,mkdirSync} from 'node:fs';
import {chromium} from 'playwright-core';
const root=process.env.DOCSCAN_URL??'http://localhost:4201/';
const image='/tmp/docscan-feature-fixtures/box-1.png';
const output=process.env.DOCSCAN_RESOURCE_OUTPUT;
if(!output)throw Error('Set fresh DOCSCAN_RESOURCE_OUTPUT');
const baseline=process.env.DOCSCAN_RESOURCE_BASELINE?JSON.parse(readFileSync(process.env.DOCSCAN_RESOURCE_BASELINE)):null;
const browser=await chromium.launch({executablePath:'/usr/bin/google-chrome'});
const page=await browser.newPage({viewport:{width:430,height:900}});const errors=[],network=[],downloads=[];
page.on('pageerror',e=>errors.push(e.message));
page.on('response',r=>{if(r.url().includes('/models/')){const entry={file:new URL(r.url()).pathname.split('/').at(-1),bytes:0,status:r.status()};network.push(entry);downloads.push(r.body().then(b=>entry.bytes=b.length));}});
await page.addInitScript(()=>{
 window.__resources={responses:[],files:[],workers:0};
 const OriginalWorker=Worker;
 window.Worker=class extends OriginalWorker{constructor(...args){super(...args);window.__resources.workers++;this.addEventListener('message',e=>{const m=e.data;if(m.kind==='result')window.__resources.responses.push({request:m.request,ms:m.ms,memoryBytes:m.memoryBytes});});}};
 addEventListener('docscan:file',e=>window.__resources.files.push(e.detail));
});
const digest=v=>createHash('sha256').update(JSON.stringify(v)).digest('hex');
const report={inputSha256:createHash('sha256').update(readFileSync(image)).digest('hex'),idle:null,phases:[],errors:null};
try{
 await page.goto(root+'?threads=1&labelReader=fast&textEngine=ppocr_v6_tiny');
 await page.waitForFunction(()=>window.__docscan?.captureReady,null,{timeout:60000});
 await page.waitForTimeout(2000);
 await Promise.all(downloads);
 const tagger=await page.locator('[data-testid=address-method] option[value=tagger]').evaluate(e=>({disabled:e.disabled,text:e.textContent}));
 if(baseline){assert.equal(tagger.disabled,false,'a not-yet-loaded tagger is unknown, not unavailable');assert.doesNotMatch(await page.locator('[data-testid=address-method] option[value=auto]').textContent(),/rules/);}
 report.idle={models:[...network],workers:await page.evaluate(()=>window.__resources.workers)};
 for(const mode of ['labels','text','labels']){
  await page.locator(`[data-photo=${mode}]`).setInputFiles(image);
  await page.getByTestId('results').waitFor({timeout:90000});
  const reading=await page.evaluate(()=>window.__resources.files.at(-1).outcome);
  const core=reading.kind==='barcodes'?reading.fields.map(f=>[f.label,f.value,f.kind,f.source,f.check_digit_valid,f.bbox]):{text:reading.result.text,lines:reading.result.lines};
  const raw=await page.evaluate(()=>window.__resources.responses);
  await Promise.all(downloads);
  report.phases.push({mode,digest:digest(core),fields:reading.fields?.length??null,lastResponse:raw.at(-1),models:[...network]});
  await page.getByTestId('results-home').click();await page.getByTestId('home').waitFor();
 }
 report.errors=errors;assert.deepEqual(errors,[]);
 writeFileSync(output,JSON.stringify(report,null,2),{flag:'wx',mode:0o600});
 if(baseline){
  assert.equal(report.inputSha256,baseline.inputSha256);assert.deepEqual(report.phases.map(p=>p.digest),baseline.phases.map(p=>p.digest),'recognition changed');
  assert.equal(report.idle.models.length,0,'home must not fetch OCR weights');
  assert.equal(report.idle.workers,1,'home should initialize only the lightweight scanner');
  const files=report.phases.at(-1).models.map(m=>m.file);
  assert.deepEqual(files.sort(),['ppocr-v6-tiny-det.onnx','ppocr-v6-tiny-rec.onnx'].sort(),'Fast/Text should share one tiny pair without full OCR weights');
  assert.ok(report.phases.at(-1).lastResponse.memoryBytes<baseline.phases.at(-1).lastResponse.memoryBytes,'shared reader did not reduce peak WASM memory');
 }
 console.log(JSON.stringify({output,idleModelBytes:report.idle.models.reduce((n,m)=>n+m.bytes,0),idleWorkers:report.idle.workers,phases:report.phases.map(p=>({mode:p.mode,fields:p.fields,memoryBytes:p.lastResponse.memoryBytes,ms:p.lastResponse.ms})),parity:baseline?'exact':'baseline'}));
}finally{await browser.close();}
