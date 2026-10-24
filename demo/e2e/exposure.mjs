// Explicit brightness comparison: original OCR stays primary, with no automatic merge.
// Uses procedural fixtures from eval/text_eval.py, then linear exposure *0.18.
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {chromium} from 'playwright-core';
const server=spawn('node',['node_modules/vite/bin/vite.js','preview','--port','4192','--strictPort'],{cwd:new URL('../',import.meta.url),stdio:'pipe'});
await new Promise((resolve,reject)=>{server.stdout.on('data',d=>String(d).includes('4192')&&resolve());server.on('exit',c=>reject(new Error(`Preview exited ${c}`)));});
const browser=await chromium.launch({executablePath:'/usr/bin/google-chrome'});
const page=await browser.newPage({viewport:{width:390,height:844}});
const errors=[];page.on('pageerror',e=>errors.push(e.message));
await page.addInitScript(()=>{window.__exposureOutcomes=[];window.addEventListener('docscan:file',e=>window.__exposureOutcomes.push(e.detail.outcome));});
async function read(file){
 await page.locator('[data-photo=text]').setInputFiles(file);
 await page.locator('[data-testid=results][data-kind=text]').waitFor({timeout:180000});
 return page.evaluate(()=>window.__exposureOutcomes.at(-1));
}
async function home(){await page.locator('[data-testid=results-home]').click();await page.locator('[data-testid=home]').waitFor();}
try {
 await page.goto(`http://localhost:4192/?threads=${process.env.DOCSCAN_TEST_THREADS??'1'}&textEngine=ppocr_v6_tiny`);
 await page.waitForFunction(()=>window.__docscan?.ready,null,{timeout:60000});
 const original=await read('/tmp/docscan-exposure-browser/dark.png');await home();
 await page.getByTestId('text-engine').selectOption('ppocr_v6_tiny_exposure');
 const compared=await read('/tmp/docscan-exposure-browser/dark.png');
 assert.equal(compared.result.text,original.result.text,'brightness comparison must retain baseline text');
 assert.deepEqual(compared.result.lines,original.result.lines);
 assert.equal(compared.documentEvidence.files[0].original.sha256,original.documentEvidence.files[0].original.sha256);
 const e=compared.result.exposure;
 assert.equal(e.version,'frozen-global-exposure-v1');assert.equal(e.status,'compared');assert.equal(e.applied,true);
 assert.ok(e.gain>1&&e.gain<=4);assert.equal(e.ocrPasses,2);assert.equal(e.error,null);assert.ok(e.elapsedMs>0);
 assert.equal(compared.meta.ocrFrames,2);assert.equal(typeof e.alternative.text,'string');
 assert.equal(await page.getByLabel('Extracted text',{exact:true}).inputValue(),original.result.text);
 assert.equal(await page.getByLabel('Brighter alternative text',{exact:true}).inputValue(),e.alternative.text);
 console.log('PASS dark-page comparison: primary text/positions/hash unchanged; separate bounded alternative');
 await home();
 await page.getByTestId('text-engine').selectOption('ppocr_v6_tiny_exposure');
 const clean=await read('/tmp/docscan-exposure-browser/clean.png');
 assert.equal(clean.result.exposure.status,'unchanged');assert.equal(clean.result.exposure.applied,false);
 assert.equal(clean.result.exposure.gain,1);assert.equal(clean.result.exposure.alternative,null);assert.equal(clean.meta.ocrFrames,1);
 assert.equal(await page.getByLabel('Brighter alternative text',{exact:true}).count(),0);
 assert.match(clean.result.text,/DOCUMENT CAPTURE DEVELOPMENT SAMPLE/);
 console.log('PASS clean page no-op, one OCR pass, no invented alternative');
 assert.deepEqual(errors,[]);
} finally {await browser.close();server.kill();}
