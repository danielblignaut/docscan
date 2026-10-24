// Synthetic multi-code upload and camera-to-file transition regression.
// Run after the production build; DOCSCAN_URL optionally checks deployed Pages.
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { chromium } from 'playwright-core';
const root = process.env.DOCSCAN_URL ?? 'http://localhost:4191/';
let server;
if (!process.env.DOCSCAN_URL) {
  server = spawn('node', ['node_modules/vite/bin/vite.js','preview','--port','4191','--strictPort'], {cwd:new URL('../',import.meta.url),stdio:'pipe'});
  await new Promise((resolve,reject)=>{server.stdout.on('data',d=>String(d).includes('4191')&&resolve());server.on('exit',c=>reject(new Error(`Preview exited ${c}`)));});
}
const browser = await chromium.launch({executablePath:'/usr/bin/google-chrome',args:['--use-fake-ui-for-media-stream','--use-fake-device-for-media-stream']});
const context = await browser.newContext({viewport:{width:390,height:844}});
const page = await context.newPage();
const errors=[];page.on('pageerror',e=>errors.push(e.message));
const fixture=new URL('../../testdata/synth/multi_barcode.png',import.meta.url).pathname;
const expected=JSON.parse(readFileSync(new URL('../../testdata/synth/multi_barcode.json',import.meta.url))).barcodes.map(b=>b.text).sort();
await page.addInitScript(()=>{
  window.__importTracks=[];window.__importEvents=[];
  const get=navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
  navigator.mediaDevices.getUserMedia=async(...args)=>{const stream=await get(...args);window.__importTracks.push(...stream.getTracks());return stream;};
  window.addEventListener('docscan:complete',e=>window.__importEvents.push(e.detail));
});
async function checkResults(){
  await page.locator('[data-testid=results][data-kind=barcodes]').waitFor({timeout:180000});
  assert.deepEqual((await page.locator('[data-testid=barcodes] input').evaluateAll(xs=>xs.map(x=>x.value))).sort(),expected);
  assert.equal(await page.locator('[data-testid=file-evidence]').count(),1);
  assert.equal(await page.evaluate(()=>window.__importEvents.length),0,'file import must not announce a camera capture');
  await page.locator('[data-testid=results-home]').click();
  await page.locator('[data-testid=home]').waitFor();
}
try {
  await page.goto(root+'?threads=1');
  await page.waitForFunction(()=>window.__docscan?.ready,null,{timeout:60000});
  await page.locator('[data-photo=barcodes]').setInputFiles(fixture);await checkResults();
  console.log('PASS home image upload: all eight synthetic barcodes');
  await page.locator('[data-scanner=barcodes]').click();
  await page.waitForFunction(()=>window.__importTracks.some(t=>t.readyState==='live'));
  const buttons=await Promise.all(['capture-home','capture-import'].map(id=>page.locator(`[data-testid=${id}]`).boundingBox()));
  assert.ok(buttons[0].x+buttons[0].width<=buttons[1].x,'phone navigation and import controls must not overlap');
  await page.locator('[data-testid=capture-import]').setInputFiles(fixture);await checkResults();
  assert.ok(await page.evaluate(()=>window.__importTracks.length>0&&window.__importTracks.every(t=>t.readyState==='ended')));
  assert.equal(new URL(page.url()).searchParams.get('mode'),null,'leaving an imported result must not reopen camera mode');
  console.log('PASS camera-to-file switch releases camera and returns home, all eight barcodes');
  await page.evaluate(()=>{navigator.mediaDevices.getUserMedia=async()=>{throw new DOMException('Synthetic permission denial','NotAllowedError');};});
  await page.locator('[data-scanner=barcodes]').click();
  await page.locator('[data-testid=capture-import]').setInputFiles(fixture);await checkResults();
  console.log('PASS image upload remains available when camera permission is denied');
  assert.deepEqual(errors,[]);
} finally {await browser.close();server?.kill();}
