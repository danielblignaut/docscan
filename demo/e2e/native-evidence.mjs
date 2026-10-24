// Direct single/threaded WASM contract tests with one procedural, invented QR.
// Uses the repository's documented Playwright browser workflow.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { spawn } from 'node:child_process';
import { chromium } from 'playwright-core';
const source = readFileSync(new URL('../../docscan/src/barcode.rs', import.meta.url), 'utf8');
const rows = [...source.matchAll(/"([01]{25})"/g)].slice(0, 25).map(match => match[1]);
assert.equal(rows.length, 25);
const server = spawn('node', ['node_modules/vite/bin/vite.js', '--port', '4189', '--strictPort'], { cwd: new URL('../', import.meta.url), stdio: 'pipe' });
await new Promise((resolve, reject) => { server.stdout.on('data', d => String(d).includes('4189') && resolve()); server.on('exit', c => reject(new Error(`Vite exited ${c}`))); });
const browser = await chromium.launch({ executablePath: '/usr/bin/google-chrome' });
const page = await browser.newPage();
try {
  await page.goto('http://localhost:4189/');
  for (const threads of [1, 2]) {
    const result = await page.evaluate(async ({ rows, threads, packagePath }) => {
      const workerSource = `self.onmessage = async ({ data: { rows, threads, root } }) => {
        let scanner;
        try {
          const api = await import(root + '/@fs' + ${JSON.stringify(packagePath)} + (threads > 1 ? 'pkg-threads/' : 'pkg/') + 'docscan.js');
          await api.default();
          if (threads > 1) await api.initThreadPool(threads);
          scanner = new api.Scanner();
          const w = 337, h = 221, image = new Uint8Array(w*h*4).fill(255);
          for (let y=0;y<25;y++) for (let x=0;x<25;x++) for (let dy=0;dy<4;dy++) for (let dx=0;dx<4;dx++) {
            const i=((52+4*y+dy)*w+36+4*x+dx)*4;
            image[i]=image[i+1]=image[i+2]=rows[y][x]==='1'?0:255;
          }
          const first = scanner.barcodes(image,w,h,['qrcode']);
          const kept = scanner.barcodes_with_empty_matrix_retry(image,w,h,['qrcode']);
          const copies = [scanner.document(image,w,h,false,'smart_id_back').copy_assessment];
          for (let y=0;y<h;y++) for(let x=0;x<w;x+=2) {const i=(y*w+x)*4;image[i]=image[i+1]=image[i+2]=255;}
          const empty = scanner.barcodes(image,w,h,['qrcode']);
          const recovered = scanner.barcodes_with_empty_matrix_retry(image,w,h,['qrcode']);
          const excluded = scanner.barcodes_with_empty_matrix_retry(image,w,h,['datamatrix']);
          const blank=new Uint8Array(128*128*4).fill(255);
          copies.push(scanner.document(blank,128,128,false,'passport').copy_assessment);
          const models = await Promise.all(['text-detection.rten','text-recognition.rten'].map(async name => new Uint8Array(await (await fetch(root+'/models/'+name)).arrayBuffer())));
          scanner.load_ocr(...models);
          copies.push(scanner.document(blank,128,128,true,'passport').copy_assessment);
          self.postMessage({ first, kept, empty, recovered, excluded, copies });
        } catch (e) { self.postMessage({error:String(e),stack:e.stack}); }
        finally {scanner?.free();}
      };`;
      const url = URL.createObjectURL(new Blob([workerSource], { type: 'text/javascript' }));
      const worker = new Worker(url, { type: 'module' });
      try { return await new Promise((resolve, reject) => {
        const timer=setTimeout(()=>reject(new Error('WASM contract timed out')),120000);
        worker.onmessage=e=>{clearTimeout(timer);resolve(e.data);};
        worker.onerror=e=>{clearTimeout(timer);reject(new Error(e.message));};
        worker.postMessage({ rows, threads, root:location.origin });
      }); } finally {worker.terminate();URL.revokeObjectURL(url);}
    }, { rows, threads, packagePath: new URL('../../docscan/', import.meta.url).pathname });
    assert.equal(result.error, undefined, result.stack);
    assert.equal(result.first.length, 1); assert.deepEqual(result.kept, result.first);
    assert.deepEqual(result.empty, []); assert.deepEqual(result.excluded, []);
    assert.equal(result.recovered.length, 1);
    assert.equal(result.recovered[0].text, 'matrix retry fixture');
    assert.deepEqual(result.recovered[0].bytes, [...Buffer.from('matrix retry fixture')]);
    for (const [x,y] of result.recovered[0].points) assert.ok([[36,52],[136,52],[36,152],[136,152]].some(([a,b])=>Math.abs(x-a)<4&&Math.abs(y-b)<4));
    assert.equal(result.copies.length, 3);
    for (const copy of result.copies) {
      assert.equal(copy.status,'unknown');
      assert.ok(Object.hasOwn(copy,'is_copy')); assert.equal(copy.is_copy,null);
      assert.ok(Object.hasOwn(copy,'confidence')); assert.equal(copy.confidence,null);
    }
    console.log(`PASS ${threads} thread WASM: actual retry recovery, payload/coordinate/filter preservation, baseline equality, explicit nullable copy fields on barcode-only/unsuccessful/OCR reads`);
  }
} finally { await browser.close(); server.kill(); }
